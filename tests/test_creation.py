"""Creation boundaries: real routes/client with only upstream HTTP substituted."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_unconfigured_creation_is_independent_of_video(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        response = client.get('/api/creation/config')
        assert response.status_code == 200
        assert response.json()['configured'] is False
        response = client.post('/api/creation/script', json={'prompt': 'A robot finds a flower'})
        assert response.status_code == 503
        assert 'LLM_' in response.json()['detail']


def creation_client(tmp_path, handler):
    from app.llm import TextModel

    settings = Settings(data_dir=tmp_path, llm_base_url='https://text.example/v1/',
                        llm_api_key='private-llm-key', llm_model='writer-model', llm_timeout_seconds=10)
    text = TextModel(settings, http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return TestClient(create_app(settings, llm=text))


def completion(value, *, finish_reason='stop'):
    content = json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value
    return httpx.Response(200, json={'id': 'completion-1', 'object': 'chat.completion',
        'model': 'writer-model', 'choices': [{'index': 0, 'finish_reason': finish_reason,
                                           'message': {'role': 'assistant', 'content': content}}]})


def shot(number=1, duration=8, prompt='A robot walks slowly toward a yellow flower.'):
    return {'number': number, 'title': 'Flower', 'duration': duration, 'visual': 'Robot in a garden',
            'camera': 'Slow push in', 'audio': 'Birdsong; no dialogue', 'prompt': prompt}


def test_script_calls_configured_service_without_video_setup(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        return completion({'title': ' 花 ', 'content': ' 角色：小机器人。场景：花园。 '})

    with creation_client(tmp_path, handler) as client:
        config = client.get('/api/creation/config').json()
        assert config['configured'] is True and config['model'] == 'writer-model'
        assert 'private-llm-key' not in json.dumps(config)
        response = client.post('/api/creation/script', json={'prompt': ' 机器人发现花朵 '})
        assert response.status_code == 200
        assert response.json() == {'title': '花', 'content': '角色：小机器人。场景：花园。'}
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == 'https://text.example/v1/chat/completions'
    assert request.headers['authorization'] == 'Bearer private-llm-key'
    body = json.loads(request.content)
    assert body['model'] == 'writer-model'
    assert json.loads(body['messages'][1]['content'])['prompt'] == '机器人发现花朵'


@pytest.mark.parametrize('target,custom', [('generic', ''), ('custom', 'Kling: clear action and camera')])
def test_storyboard_uses_edited_script_count_duration_and_style(tmp_path, target, custom):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return completion({'shots': [shot(1, 6), shot(2, 6)]})

    with creation_client(tmp_path, handler) as client:
        response = client.post('/api/creation/storyboard', json={
            'script': 'EDITED SCRIPT: robot gives flower to friend.', 'shot_count': 2, 'duration': 6,
            'target_model': target, 'custom_model': custom, 'visual_style': 'clay animation'})
        assert response.status_code == 200
        assert [item['number'] for item in response.json()['shots']] == [1, 2]
        assert [item['duration'] for item in response.json()['shots']] == [6, 6]
    payload = json.loads(requests[0]['messages'][1]['content'])
    assert payload['script'] == 'EDITED SCRIPT: robot gives flower to friend.'
    assert payload['shot_count'] == 2 and payload['duration'] == 6
    assert payload['visual_style'] == 'clay animation'
    assert payload['target_model'] == target and payload['custom_model'] == custom


def test_h3_prompt_constraints_and_fenced_response(tmp_path):
    requests = []
    prompt = ('integrated_multimodal_description: [Shot 1] The robot (S1) says '
              '<d>[Chinese] 你好。</d> and waves for eight seconds.\n\n'
              'overall_soundscape: Birds.\n\nnon_diegetic_music: N/A')

    def handler(request):
        requests.append(json.loads(request.content))
        return completion('```json\n' + json.dumps({'shots': [shot(prompt=prompt)]}) + '\n```')

    with creation_client(tmp_path, handler) as client:
        response = client.post('/api/creation/storyboard', json={
            'script': '机器人打招呼。', 'shot_count': 1, 'duration': 8, 'target_model': 'h3'})
        assert response.status_code == 200
        assert '你好' in response.json()['shots'][0]['prompt']
    system = requests[0]['messages'][0]['content']
    assert all(name in system for name in (
        'integrated_multimodal_description', 'overall_soundscape', 'non_diegetic_music'))
    assert 'English' in system and 'original language' in system


@pytest.mark.parametrize('path,body', [
    ('script', {'prompt': '   '}), ('script', {'prompt': 'x' * 20001}),
    ('storyboard', {'script': ' '}), ('storyboard', {'script': 'x' * 40001}),
    ('storyboard', {'script': 'story', 'shot_count': 0}),
    ('storyboard', {'script': 'story', 'shot_count': 25}),
    ('storyboard', {'script': 'story', 'shot_count': True}),
    ('storyboard', {'script': 'story', 'duration': 0}),
    ('storyboard', {'script': 'story', 'duration': 8.5}),
    ('storyboard', {'script': 'story', 'target_model': 'unsupported'}),
    ('storyboard', {'script': 'story', 'target_model': 'custom', 'custom_model': ' '}),
    ('storyboard', {'script': 'story', 'target_model': 'h3', 'duration': 16}),
])
def test_invalid_input_rejected_before_upstream_call(tmp_path, path, body):
    def handler(request):
        pytest.fail('Invalid input reached a paid upstream call')

    with creation_client(tmp_path, handler) as client:
        assert client.post('/api/creation/' + path, json=body).status_code == 422


@pytest.mark.parametrize('value,reason', [
    ('not JSON private-llm-key', 'stop'), ('', 'stop'),
    ({'title': 'Flower'}, 'stop'), ({'title': '', 'content': 'story'}, 'stop'),
    ({'title': 'Flower', 'content': 'story'}, 'length'),
    ({'title': 'Flower', 'content': 'story'}, 'content_filter'),
])
def test_invalid_script_response_is_safe_and_not_retried(tmp_path, value, reason):
    requests = []

    def handler(request):
        requests.append(request)
        return completion(value, finish_reason=reason)

    with creation_client(tmp_path, handler) as client:
        response = client.post('/api/creation/script', json={'prompt': 'story'})
        assert response.status_code == 502
        assert 'private-llm-key' not in response.text
    assert len(requests) == 1


@pytest.mark.parametrize('shots', [
    [], [shot(2)], [shot(duration=7)], [shot(prompt=' ')],
    [shot(prompt='x' * 20001)], [dict(shot(), camera='')],
    [dict(shot(), number=True)], [shot(), shot(2)],
])
def test_invalid_storyboard_cannot_enter_ui(tmp_path, shots):
    with creation_client(tmp_path, lambda request: completion({'shots': shots})) as client:
        response = client.post('/api/creation/storyboard', json={
            'script': 'story', 'shot_count': 1, 'duration': 8, 'target_model': 'generic'})
        assert response.status_code == 502


def test_h3_response_must_include_sections_in_order(tmp_path):
    with creation_client(tmp_path, lambda request: completion({'shots': [shot()]})) as client:
        response = client.post('/api/creation/storyboard', json={
            'script': 'story', 'shot_count': 1, 'duration': 8, 'target_model': 'h3'})
        assert response.status_code == 502


@pytest.mark.parametrize('upstream_status,expected', [(401, 502), (403, 502), (429, 429), (500, 502)])
def test_upstream_errors_do_not_leak_response_or_retry(tmp_path, upstream_status, expected):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(upstream_status, json={'error': 'private-llm-key private details'})

    with creation_client(tmp_path, handler) as client:
        response = client.post('/api/creation/script', json={'prompt': 'story'})
        assert response.status_code == expected
        assert 'private' not in response.text
    assert len(requests) == 1


@pytest.mark.parametrize('error,expected', [(httpx.ReadTimeout, 504), (httpx.ConnectError, 502)])
def test_transport_errors_are_safe(tmp_path, error, expected):
    def handler(request):
        raise error('private-llm-key transport details', request=request)

    with creation_client(tmp_path, handler) as client:
        response = client.post('/api/creation/script', json={'prompt': 'story'})
        assert response.status_code == expected
        assert 'private' not in response.text


@pytest.mark.parametrize('envelope', [{}, {'choices': []}, {'choices': [None]},
    {'choices': [{'message': {'content': [{'type': 'text', 'text': 'unexpected'}]}}]}])
def test_malformed_provider_envelopes_are_safe(tmp_path, envelope):
    with creation_client(tmp_path, lambda request: httpx.Response(200, json=envelope)) as client:
        response = client.post('/api/creation/script', json={'prompt': 'story'})
        assert response.status_code == 502


def test_llm_environment_and_repr_keep_credentials_private(monkeypatch, tmp_path):
    monkeypatch.setenv('VIDEO_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('LLM_BASE_URL', 'https://text.example/v1/')
    monkeypatch.setenv('LLM_API_KEY', 'private-llm-key')
    monkeypatch.setenv('LLM_MODEL', 'writer-model')
    monkeypatch.setenv('LLM_TIMEOUT_SECONDS', '45')
    settings = Settings.from_env()
    assert settings.llm_base_url == 'https://text.example/v1'
    assert settings.llm_model == 'writer-model' and settings.llm_timeout_seconds == 45
    assert 'private-llm-key' not in repr(settings)


@pytest.mark.parametrize('base_url', ['https://text.example:invalid/v1', 'https://text.example:99999/v1'])
def test_invalid_llm_url_port_is_reported_as_configuration_error(tmp_path, base_url):
    from app.llm import TextModel

    settings = Settings(data_dir=tmp_path, llm_api_key='private-llm-key', llm_model='writer',
                        llm_base_url=base_url)
    text = TextModel(settings, http=httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: pytest.fail('Invalid address reached transport'))))
    with TestClient(create_app(settings, llm=text), raise_server_exceptions=False) as client:
        assert client.get('/api/creation/config').json()['configured'] is False
        response = client.post('/api/creation/script', json={'prompt': 'story'})
        assert response.status_code == 503
        assert 'private-llm-key' not in response.text


@pytest.mark.parametrize('embedded', [False, True])
def test_deep_provider_json_returns_safe_format_error(tmp_path, embedded):
    nested = '[' * 50000 + '0' + ']' * 50000
    upstream = completion(nested) if embedded else httpx.Response(200, content='{"extra":' + nested + '}')
    with creation_client(tmp_path, lambda request: upstream) as client:
        response = client.post('/api/creation/script', json={'prompt': 'story'})
        assert response.status_code == 502
        assert 'JSON' in response.json()['detail']


@pytest.mark.parametrize('prompt', [
    'integrated_multimodal_description:\noverall_soundscape:\nnon_diegetic_music:',
    'integrated_multimodal_description: [Shot 1] A robot.\noverall_soundscape:\nnon_diegetic_music: N/A',
    'overall_soundscape: Birds\nintegrated_multimodal_description: Robot\nnon_diegetic_music: N/A',
    'integrated_multimodal_description: Robot\noverall_soundscape: Birds\n'
    'overall_soundscape: More birds\nnon_diegetic_music: N/A',
])
def test_empty_or_duplicate_h3_sections_are_rejected(tmp_path, prompt):
    with creation_client(tmp_path, lambda request: completion({'shots': [shot(prompt=prompt)]})) as client:
        response = client.post('/api/creation/storyboard', json={
            'script': 'story', 'shot_count': 1, 'duration': 8, 'target_model': 'h3'})
        assert response.status_code == 502

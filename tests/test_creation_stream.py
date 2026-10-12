"""Streaming must expose useful output before completion and validate final results."""
import asyncio
import json
import socket

import httpx
import pytest
import uvicorn

from app.config import Settings
from app.llm import TextModel, TextModelError
from app.main import create_app
from tests.test_creation import creation_client, shot


def event(content=None, reason=None):
    delta = {} if content is None else {'content': content}
    return ('data: ' + json.dumps({'choices': [{'index': 0, 'delta': delta,
                                              'finish_reason': reason}]}, ensure_ascii=False) + '\r\n\r\n').encode()


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


def streamed(chunks, reason='stop', done=True):
    wire = b': keepalive\r\n\r\n' + b''.join(event(c) for c in chunks)
    if reason:
        wire += event(reason=reason)
    if done:
        wire += b'data: [DONE]\r\n\r\n'
    # Split UTF-8 characters and SSE lines across transport chunks.
    return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                          stream=Chunks([wire[i:i + 7] for i in range(0, len(wire), 7)]))


def events(response):
    assert response.headers['content-type'].startswith('text/event-stream')
    result = []
    for block in response.text.split('\n\n'):
        lines = block.splitlines()
        name = next((line[7:] for line in lines if line.startswith('event: ')), None)
        data = next((line[6:] for line in lines if line.startswith('data: ')), None)
        if name and data:
            result.append((name, json.loads(data)))
    return result


async def test_provider_yields_first_content_before_upstream_finishes():
    gate = asyncio.Event()

    class Gated(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield event('{"title":"花","content":"开始')
            await gate.wait()
            yield event('结束"}') + event(reason='stop') + b'data: [DONE]\n\n'

    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=Gated())

    settings = Settings(llm_api_key='private-key', llm_model='writer', llm_timeout_seconds=2)
    model = TextModel(settings, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        assert hasattr(model, 'stream'), 'TextModel must offer real streaming'
        stream = model.stream('system', 'user')
        assert await asyncio.wait_for(anext(stream), .5) == '{"title":"花","content":"开始'
        assert requests[0]['stream'] is True
        gate.set()
        assert ''.join([c async for c in stream]) == '结束"}'
    finally:
        await model.close()


def test_script_preview_decodes_partial_escaped_text_before_result(tmp_path):
    chunks = ['```json\n{"title":"花", "content":"他说\\"你', '好\\"\\n再见', '"}\n```']
    with creation_client(tmp_path, lambda r: streamed(chunks)) as client:
        result = events(client.post('/api/creation/script/stream', json={'prompt': 'story'}))
    previews = [data for name, data in result if name == 'preview']
    assert any(p.get('content') == '他说"你' for p in previews)
    assert result[-1] == ('result', {'title': '花', 'content': '他说"你好"\n再见'})


def test_storyboard_previews_include_unfinished_shot_fields(tmp_path):
    full = json.dumps({'shots': [shot(), shot(2)]}, ensure_ascii=False)
    split = full.index('Robot in a garden') + 5
    with creation_client(tmp_path, lambda r: streamed([full[:split], full[split:]])) as client:
        result = events(client.post('/api/creation/storyboard/stream', json={
            'script': 'story', 'shot_count': 2, 'target_model': 'generic'}))
    preview = next(data for name, data in result if name == 'preview')
    assert preview['shots'][0]['visual'] == 'Robot'
    assert result[-1][0] == 'result'
    assert len(result[-1][1]['shots']) == 2


@pytest.mark.parametrize('reason,done', [('length', True), (None, False)])
def test_incomplete_upstream_never_emits_success(tmp_path, reason, done):
    with creation_client(tmp_path, lambda r: streamed(['{"title":"花","content":"故事"}'], reason, done)) as client:
        result = events(client.post('/api/creation/script/stream', json={'prompt': 'story'}))
    assert any(name == 'preview' for name, _ in result)
    assert result[-1][0] == 'error'
    assert not any(name == 'result' for name, _ in result)


@pytest.mark.parametrize('value', [{'shots': [shot(2)]}, {'shots': [shot(prompt='wrong H3 format')]}])
def test_final_stream_result_still_enforces_shot_and_h3_constraints(tmp_path, value):
    with creation_client(tmp_path, lambda r: streamed([json.dumps(value)])) as client:
        result = events(client.post('/api/creation/storyboard/stream', json={'script': 'story', 'shot_count': 1}))
    assert result[-1][0] == 'error'
    assert not any(name == 'result' for name, _ in result)


@pytest.mark.parametrize('status', [401, 429, 500])
def test_stream_error_is_safe_and_not_retried(tmp_path, status):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, json={'error': 'private-llm-key details'})

    with creation_client(tmp_path, handler) as client:
        response = client.post('/api/creation/script/stream', json={'prompt': 'story'})
        result = events(response)
    assert result[-1][0] == 'error'
    assert 'private' not in response.text
    assert len(requests) == 1


async def test_total_timeout_applies_while_stream_is_idle():
    class Idle(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield event('{"title":"花"')
            await asyncio.Event().wait()

    model = TextModel(Settings(llm_api_key='key', llm_model='writer', llm_timeout_seconds=1),
                      httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(
                          200, headers={'content-type': 'text/event-stream'}, stream=Idle()))))
    try:
        assert hasattr(model, 'stream'), 'TextModel must offer real streaming'
        with pytest.raises(TextModelError) as exc:
            _ = [part async for part in model.stream('system', 'user')]
        assert exc.value.status_code == 504
    finally:
        await model.close()


def test_preview_updates_do_not_resend_finished_shots(tmp_path):
    first = json.dumps({'shots': [shot()]})[:-2]
    second = ', ' + json.dumps(shot(2)) + ']}'

    class Slow(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield event(first)
            await asyncio.sleep(.12)
            yield event(second) + event(reason='stop') + b'data: [DONE]\n\n'

    with creation_client(tmp_path, lambda r: httpx.Response(
            200, headers={'content-type': 'text/event-stream'}, stream=Slow())) as client:
        result = events(client.post('/api/creation/storyboard/stream', json={
            'script': 'story', 'shot_count': 2, 'target_model': 'generic'}))
    previews = [data for name, data in result if name == 'preview']
    assert len(previews) == 2
    assert [s['number'] for s in previews[1]['shots']] == [2]
    assert result[-1][0] == 'result'


def test_large_valid_chinese_storyboard_fits_browser_frame_limit(tmp_path):
    value = {'shots': [dict(shot(number), title='花' * 300, visual='花' * 5000,
                           camera='花' * 5000, audio='花' * 5000, prompt='花' * 20000)
                       for number in range(1, 25)]}
    wire = event(json.dumps(value, ensure_ascii=False)) + event(reason='stop') + b'data: [DONE]\n\n'
    assert len(wire) < 3 * 1024 * 1024
    with creation_client(tmp_path, lambda r: httpx.Response(
            200, headers={'content-type': 'text/event-stream'}, stream=Chunks([wire]))) as client:
        response = client.post('/api/creation/storyboard/stream', json={
            'script': 'story', 'shot_count': 24, 'target_model': 'generic'})
    result_frame = next(block for block in response.text.split('\n\n') if block.startswith('event: result'))
    assert len(result_frame) < 3 * 1024 * 1024
    assert events(response)[-1][0] == 'result'


@pytest.fixture
async def live_stream_server(tmp_path):
    """Real loopback HTTP, with only the external provider replaced."""
    gate, closed = asyncio.Event(), asyncio.Event()

    class Gated(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield event('{"title":"花","content":"开始')
            await gate.wait()
            yield event('结束"}') + event(reason='stop') + b'data: [DONE]\n\n'

        async def aclose(self):
            closed.set()

    settings = Settings(data_dir=tmp_path, llm_api_key='fake-local-key', llm_model='writer')
    model = TextModel(settings, httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(
        200, headers={'content-type': 'text/event-stream'}, stream=Gated()))))
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(settings, llm=model), log_level='error'))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(3):
            while not server.started:
                await asyncio.sleep(.01)
        yield f'http://127.0.0.1:{port}', gate, closed
    finally:
        gate.set()
        server.should_exit = True
        await asyncio.wait_for(task, 3)
        sock.close()


async def test_live_http_delivers_preview_before_model_completion(live_stream_server):
    url, gate, _ = live_stream_server
    async with httpx.AsyncClient() as client:
        async with client.stream('POST', url + '/api/creation/script/stream', json={'prompt': 'story'}) as response:
            chunks = response.aiter_text()
            first = await asyncio.wait_for(anext(chunks), 1)
            assert 'event: preview' in first and '开始' in first
            assert not gate.is_set()
            gate.set()
            rest = ''.join([part async for part in chunks])
            assert 'event: result' in rest and '开始结束' in rest


async def test_browser_disconnect_closes_pending_upstream(live_stream_server):
    url, gate, closed = live_stream_server
    async with httpx.AsyncClient() as client:
        async with client.stream('POST', url + '/api/creation/script/stream', json={'prompt': 'story'}) as response:
            assert 'event: preview' in await asyncio.wait_for(anext(response.aiter_text()), 1)
            assert not gate.is_set()
        await asyncio.wait_for(closed.wait(), 1)

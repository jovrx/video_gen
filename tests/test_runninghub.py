import json

import httpx
import pytest

from app.runninghub import RunningHub, RunningHubError, SubmissionUnknown


async def test_client_uses_correct_auth_and_preserves_long_task_id(tmp_path):
    def handler(request):
        assert request.headers["Authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        if request.url.path == "/task/openapi/create":
            assert payload["workflowId"] == "2108942308824670209"
            assert payload["apiKey"] == "test-key"
            assert payload["nodeInfoList"] == [{"nodeId": "1", "fieldName": "image", "fieldValue": "a"}]
            return httpx.Response(200, json={"code": 0, "msg": "success", "data": {
                "taskId": 2108942308824670211, "taskStatus": "QUEUED", "netWssUrl": None,
                "clientId": "c", "promptTips": '{"result":true,"node_errors":{}}'}})
        assert payload == {"taskId": "2108942308824670211"}
        return httpx.Response(200, json={"taskId": "2108942308824670211", "status": "SUCCESS",
            "errorCode": "", "errorMessage": "", "results": [{"url": "https://example.test/final.mp4",
            "outputType": "mp4"}], "clientId": "", "promptTips": ""})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        rh = RunningHub("test-key", http=http)
        task = await rh.create("2108942308824670209", [{"nodeId": "1", "fieldName": "image", "fieldValue": "a"}])
        assert task["taskId"] == "2108942308824670211"
        assert (await rh.query(task["taskId"]))["results"][0]["url"] == "https://example.test/final.mp4"


async def test_upload_returns_file_name_not_signed_url(tmp_path):
    path = tmp_path / "ref.png"
    path.write_bytes(b"image bytes")

    def handler(request):
        assert request.url.path == "/openapi/v2/media/upload/binary"
        assert b'image bytes' in request.content
        return httpx.Response(200, json={"code": 0, "message": "success", "data": {
            "fileName": "openapi/ref.png", "download_url": "https://example.test/signed.png", "size": "11",
            "type": "image"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        assert await RunningHub("key", http=http).upload(path) == "openapi/ref.png"


async def test_legacy_running_code_is_progress_not_error():
    def handler(request):
        return httpx.Response(200, json={"code": 804, "msg": "APIKEY_TASK_IS_RUNNING", "data": {
            "netWssUrl": "wss://www.runninghub.cn/ws?auth=sensitive"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        assert (await RunningHub("key", http=http).get_wss("task")).startswith("wss://")


async def test_create_timeout_is_unknown_and_never_retried():
    requests = []

    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("private request URL", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(SubmissionUnknown):
            await RunningHub("key", http=http).create("workflow", [])
    assert len(requests) == 1


@pytest.mark.parametrize("envelope", [
    {"code": 0, "data": None}, {"data": {}}, {"code": 0, "data": {}},
    {"code": None, "data": {}}, {"code": 0, "data": {"taskId": {"bad": 1}}},
    {"code": 0, "data": {"taskId": True}},
])
async def test_accepted_but_malformed_create_response_is_unknown(envelope):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=envelope))) as http:
        with pytest.raises(SubmissionUnknown):
            await RunningHub("key", http=http).create("workflow", [])


async def test_remote_error_redacts_key_and_download_does_not_send_auth(tmp_path):
    def handler(request):
        if request.url.host == "www.runninghub.cn":
            return httpx.Response(200, json={"code": 401, "msg": "invalid test-secret", "data": None})
        assert "authorization" not in request.headers
        return httpx.Response(200, content=b"video-content")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        rh = RunningHub("test-secret", http=http)
        with pytest.raises(RunningHubError) as exc:
            await rh.create("workflow", [])
        assert "test-secret" not in str(exc.value)
        path = tmp_path / "final.mp4"
        await rh.download("https://example.test/final.mp4", path)
        assert path.read_bytes() == b"video-content"

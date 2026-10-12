import asyncio
import json

import httpx

from app.config import Settings
from app.jobs import JobManager
from app.runninghub import RunningHub
from app.store import Store


async def wait_terminal(store, job_id):
    for _ in range(200):
        state = store.get(job_id)
        if state["phase"] in {"succeeded", "failed", "submission_unknown", "download_failed"}:
            return state
        await asyncio.sleep(0.01)
    raise AssertionError(f"job did not finish: {store.get(job_id)['phase']}")


def prepare(settings, store, graph, mapping, png_bytes):
    path = settings.data_dir / "uploads" / "ref.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png_bytes)
    return store.create(prompt="walk in the park", duration=8, image_count=1,
        private={"graph": graph, "mapping": mapping, "image_paths": [str(path)],
                 "workflow_id": settings.workflow_id})


async def test_generation_selects_video_not_intermediate_image_and_saves_local(tmp_path, api_graph, mapping, png_bytes):
    requests = []
    query_count = 0

    def handler(request):
        nonlocal query_count
        requests.append(request.url.path)
        if request.url.path.endswith("/upload/binary"):
            return httpx.Response(200, json={"code": 0, "data": {"fileName": "openapi/ref.png"}})
        if request.url.path.endswith("/create"):
            assert json.loads(request.content)["nodeInfoList"] == [
                {"nodeId": "10", "fieldName": "image", "fieldValue": "openapi/ref.png"},
                {"nodeId": "20", "fieldName": "prompt", "fieldValue": "walk in the park"},
                {"nodeId": "20", "fieldName": "duration", "fieldValue": 8}]
            return httpx.Response(200, json={"code": 0, "data": {"taskId": "2108942308824670209",
                "taskStatus": "QUEUED", "netWssUrl": None}})
        if request.url.path.endswith("/outputs"):
            return httpx.Response(200, json={"code": 804, "msg": "APIKEY_TASK_IS_RUNNING",
                "data": {"netWssUrl": None}})
        if request.url.path.endswith("/query"):
            query_count += 1
            return httpx.Response(200, json={"status": "RUNNING" if query_count == 1 else "SUCCESS",
                "results": [{"url": "https://media.test/preview.png", "outputType": "png"},
                            {"url": "https://media.test/final.mp4", "outputType": "mp4"}]})
        assert request.url.path == "/final.mp4"
        return httpx.Response(200, content=b"final-video")

    settings = Settings(data_dir=tmp_path, api_key="key", poll_seconds=0.01)
    store = Store(tmp_path / "jobs.sqlite3")
    job = prepare(settings, store, api_graph, mapping, png_bytes)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        manager = JobManager(settings, store, RunningHub("key", http=http))
        manager.start(job["id"])
        state = await wait_terminal(store, job["id"])
        await manager.close()
    assert state["phase"] == "succeeded"
    assert state["video_ready"] is True
    assert (tmp_path / "videos" / f"{job['id']}.mp4").read_bytes() == b"final-video"
    assert requests.count("/task/openapi/create") == 1
    assert "/preview.png" not in requests


async def test_restart_recovers_existing_remote_task_without_resubmitting(tmp_path, api_graph, mapping, png_bytes):
    def handler(request):
        assert request.url.path == "/openapi/v2/query"
        assert json.loads(request.content) == {"taskId": "existing-task"}
        return httpx.Response(200, json={"status": "FAILED", "errorMessage": "node failed",
            "failedReason": {"node_id": "20", "node_name": "H3", "exception_message": "out of memory"}})

    settings = Settings(data_dir=tmp_path, api_key="key", poll_seconds=0.01)
    store = Store(tmp_path / "jobs.sqlite3")
    job = prepare(settings, store, api_graph, mapping, png_bytes)
    store.update(job["id"], phase="running", remote_task_id="existing-task")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        manager = JobManager(settings, Store(tmp_path / "jobs.sqlite3"), RunningHub("key", http=http))
        manager.recover()
        state = await wait_terminal(store, job["id"])
        await manager.close()
    assert state["phase"] == "failed"
    assert "20" in state["error"]


async def test_unknown_submission_is_not_retried_after_restart(tmp_path, api_graph, mapping, png_bytes):
    creates = []

    def handler(request):
        if request.url.path.endswith("/upload/binary"):
            return httpx.Response(200, json={"code": 0, "data": {"fileName": "openapi/ref.png"}})
        creates.append(request)
        raise httpx.ReadTimeout("timeout", request=request)

    settings = Settings(data_dir=tmp_path, api_key="key", poll_seconds=0.01)
    store = Store(tmp_path / "jobs.sqlite3")
    job = prepare(settings, store, api_graph, mapping, png_bytes)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        manager = JobManager(settings, store, RunningHub("key", http=http))
        manager.start(job["id"])
        state = await wait_terminal(store, job["id"])
        manager.recover()
        await asyncio.sleep(0.03)
        await manager.close()
    assert state["phase"] == "submission_unknown"
    assert len(creates) == 1


async def test_restart_in_submission_marks_unknown_without_network(tmp_path, api_graph, mapping, png_bytes):
    def handler(request):
        raise AssertionError("No network call is safe for a submit without a known taskId")

    settings = Settings(data_dir=tmp_path, api_key="key")
    store = Store(tmp_path / "jobs.sqlite3")
    job = prepare(settings, store, api_graph, mapping, png_bytes)
    store.update(job["id"], phase="submitting")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        manager = JobManager(settings, store, RunningHub("key", http=http))
        manager.recover()
        state = await wait_terminal(store, job["id"])
        await manager.close()
    assert state["phase"] == "submission_unknown"

import asyncio
import json

import httpx
from websockets.asyncio.server import serve

from app.config import Settings
from app.jobs import JobManager
from app.runninghub import RunningHub
from app.store import Store


async def test_real_websocket_progress_and_disconnect_keep_original_remote_task(tmp_path, api_graph, mapping):
    received = asyncio.Event()
    finish = asyncio.Event()

    async def websocket_handler(socket):
        for event in [
            {"type": "execution_start", "data": {"prompt_id": "comfy-prompt-id"}},
            {"type": "executing", "data": {"node": "20", "prompt_id": "comfy-prompt-id"}},
            {"type": "progress", "data": {"node": "20", "value": 50, "max": 100,
                                          "prompt_id": "comfy-prompt-id"}},
            {"type": "progress", "data": {"node": "20", "value": 99, "max": 100,
                                          "prompt_id": "unrelated-task"}},
        ]:
            await socket.send(json.dumps(event))
        received.set()
        await socket.close()

    def handler(request):
        assert request.url.path in {"/openapi/v2/query", "/task/openapi/outputs"}
        assert json.loads(request.content)["taskId"] == "runninghub-task-id"
        if request.url.path.endswith("/outputs"):
            return httpx.Response(200, json={"code": 804, "data": {"netWssUrl": None}})
        return httpx.Response(200, json={"status": "FAILED" if finish.is_set() else "RUNNING",
                                       "errorMessage": "finished fixture" if finish.is_set() else ""})

    settings = Settings(data_dir=tmp_path, api_key="key", poll_seconds=0.01)
    store = Store(tmp_path / "jobs.sqlite3")
    async with serve(websocket_handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        job = store.create(prompt="p", duration=5, image_count=1,
            private={"graph": api_graph, "mapping": mapping, "workflow_id": "workflow",
                     "wss_url": f"ws://127.0.0.1:{port}"})
        store.update(job["id"], phase="running", remote_task_id="runninghub-task-id")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            manager = JobManager(settings, store, RunningHub("key", http=http))
            manager.start(job["id"])
            try:
                await asyncio.wait_for(received.wait(), 3)
                for _ in range(100):
                    if store.get(job["id"])["progress"].get("node_percent") == 50:
                        break
                    await asyncio.sleep(0.01)
                state = store.get(job["id"])
                assert state["progress"]["node_percent"] == 50
                assert state["progress"]["node_name"] == "视频生成"
                assert state["phase"] == "running"
                assert state["private"]["prompt_id"] == "comfy-prompt-id"
                assert "wss_url" not in store.public(state)
                finish.set()
                await asyncio.wait_for(manager.tasks[job["id"]], 3)
                assert store.get(job["id"])["phase"] == "failed"
            finally:
                await manager.close()


async def test_supplied_websocket_still_reports_progress_while_query_is_offline(tmp_path, api_graph):
    from app.runninghub import RunningHubError
    received = asyncio.Event()

    async def websocket_handler(socket):
        await socket.send(json.dumps({"type": "progress", "data": {"node": "20", "value": 1, "max": 4}}))
        received.set()
        await socket.wait_closed()

    def handler(request):
        raise RunningHubError("query unavailable")

    settings = Settings(data_dir=tmp_path, api_key="key", poll_seconds=0.01)
    store = Store(tmp_path / "jobs.sqlite3")
    async with serve(websocket_handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        job = store.create(prompt="p", duration=5, image_count=1,
            private={"graph": api_graph, "wss_url": f"ws://127.0.0.1:{port}"})
        store.update(job["id"], phase="running", remote_task_id="existing")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            manager = JobManager(settings, store, RunningHub("key", http=http))
            manager.start(job["id"])
            try:
                await asyncio.wait_for(received.wait(), 1)
                for _ in range(100):
                    if store.get(job["id"])["progress"].get("node_percent") == 25:
                        break
                    await asyncio.sleep(0.01)
                assert store.get(job["id"])["progress"]["node_percent"] == 25
            finally:
                await manager.close()

"""Explicit local RunningHub substitute for browser verification; no real API calls."""
import asyncio
import json
import time
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import FileResponse

from app.config import Settings
from app.main import create_app as studio_app

FIXTURES = Path(__file__).resolve().parents[1] / ".playwright-mcp"
GRAPH = {
    "10": {"class_type": "OptionalImage", "inputs": {"image": "None"}, "_meta": {"title": "参考图1"}},
    "11": {"class_type": "OptionalImage", "inputs": {"image": "None"}, "_meta": {"title": "参考图2"}},
    "20": {"class_type": "H3", "inputs": {"prompt": "", "duration": 5}, "_meta": {"title": "视频生成"}},
}


def create_app():
    settings = Settings(data_dir=FIXTURES / "e2e-data", api_key="browser-test-only",
                        base_url="http://127.0.0.1:8766/rh", poll_seconds=0.25)
    application = studio_app(settings)
    remote = FastAPI()
    started = {}

    @remote.post("/api/openapi/getJsonApiFormat")
    def get_graph():
        return {"code": 0, "msg": "success", "data": {"prompt": json.dumps(GRAPH)}}

    @remote.post("/openapi/v2/media/upload/binary")
    def upload():
        return {"code": 0, "message": "success", "data": {"fileName": "openapi/test-reference.png"}}

    @remote.post("/task/openapi/create")
    def create():
        task_id = str(2108942308824670209 + len(started))
        started[task_id] = time.monotonic()
        return {"code": 0, "msg": "success", "data": {"taskId": task_id, "taskStatus": "QUEUED",
            "netWssUrl": f"ws://127.0.0.1:8766/rh/ws/{task_id}"}}

    @remote.post("/openapi/v2/query")
    async def query(request: Request):
        task_id = (await request.json())["taskId"]
        elapsed = time.monotonic() - started.get(task_id, 0)
        status = "QUEUED" if elapsed < 1 else "RUNNING" if elapsed < 8 else "SUCCESS"
        return {"taskId": task_id, "status": status, "errorCode": "", "errorMessage": "",
                "results": [{"url": "http://127.0.0.1:8766/rh/video", "outputType": "mp4"}]
                if status == "SUCCESS" else None}

    @remote.post("/task/openapi/outputs")
    async def wss(request: Request):
        task_id = (await request.json())["taskId"]
        return {"code": 804, "data": {"netWssUrl": f"ws://127.0.0.1:8766/rh/ws/{task_id}"}}

    @remote.websocket("/ws/{task_id}")
    async def events(socket: WebSocket, task_id: str):
        await socket.accept()
        await socket.send_json({"type": "execution_start", "data": {"prompt_id": f"comfy-{task_id}"}})
        await socket.send_json({"type": "execution_cached", "data": {"nodes": ["10", "11"]}})
        await socket.send_json({"type": "executing", "data": {"node": "20"}})
        for value in range(5):
            await socket.send_json({"type": "progress", "data": {"node": "20", "value": value, "max": 4}})
            await asyncio.sleep(1)
        await socket.send_json({"type": "execution_success", "data": {}})
        await socket.close()

    @remote.get("/video")
    def video():
        return FileResponse(FIXTURES / "fixture.mp4", media_type="video/mp4")

    application.mount("/rh", remote)
    return application

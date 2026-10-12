import json
import os

import asyncio
import httpx
import pytest

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_page_and_layout_assets_revalidate_to_avoid_mixed_versions(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        for path in ("/", "/static/style.css", "/static/app.js"):
            response = client.get(path)
            assert response.status_code == 200
            assert response.headers.get("Cache-Control") == "no-cache"


def test_history_api_filters_and_validates_pagination(tmp_path):
    application = create_app(Settings(data_dir=tmp_path))
    job = application.state.store.create(prompt="find me", duration=5, image_count=1, private={})
    application.state.store.update(job["id"], phase="failed")
    with TestClient(application) as client:
        response = client.get("/api/jobs/history", params={"status": "attention", "search": "find", "page_size": 12})
        assert response.status_code == 200
        assert response.json()["items"][0]["id"] == job["id"]
        assert client.get("/api/jobs/history?page=0").status_code == 422
        assert client.get("/api/jobs/history?page_size=10000").status_code == 422
        assert client.get("/api/jobs/history?sort=unknown").status_code == 422


def test_open_generated_resources_creates_and_opens_only_video_directory(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(os, "startfile", opened.append, raising=False)
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        response = client.post("/api/resources/open-directory")
    assert response.status_code == 200
    assert opened == [str((tmp_path / "videos").resolve())]
    assert (tmp_path / "videos").is_dir()


def test_open_resources_reports_os_error_without_exposing_private_details(tmp_path, monkeypatch):
    def fail(_):
        raise OSError("private system error")

    monkeypatch.setattr(os, "startfile", fail, raising=False)
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        response = client.post("/api/resources/open-directory")
    assert response.status_code == 500
    assert "private system error" not in response.text


def test_another_website_cannot_launch_resource_directory(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(os, "startfile", opened.append, raising=False)
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        response = client.post("/api/resources/open-directory", headers={"Origin": "https://other.example"})
    assert response.status_code == 403
    assert opened == []


def test_unconfigured_server_explains_setup_and_rejects_generation(tmp_path, png_bytes):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        assert client.get("/").status_code == 200
        config = client.get("/api/config").json()
        assert config["key_configured"] is False
        assert config["mapping_ready"] is False
        response = client.post("/api/jobs", data={"prompt": "hi", "duration": 5},
            files=[("images", ("ref.png", png_bytes, "image/png"))])
        assert response.status_code == 503
        assert "KEY" in response.json()["detail"]
        assert client.get("/api/jobs").json() == []


def test_import_mapping_validation_and_forged_image_rejected(tmp_path, api_graph, mapping):
    settings = Settings(data_dir=tmp_path, api_key="test-secret")
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/config/workflow/import", files={
            "file": ("workflow-api.json", json.dumps(api_graph).encode(), "application/json")})
        assert response.status_code == 200
        assert client.put("/api/config/mapping", json=mapping).status_code == 200
        config = client.get("/api/config").json()
        assert config["mapping_ready"] is True
        assert "test-secret" not in json.dumps(config)
        response = client.post("/api/jobs", data={"prompt": "hi", "duration": 5},
            files=[("images", ("fake.png", b"not an image", "image/png"))])
        assert response.status_code == 422
        assert client.get("/api/jobs").json() == []


def test_mapping_is_not_ready_after_importing_different_graph(tmp_path, api_graph, mapping):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        client.post("/api/config/workflow/import", files={"file": ("api.json", json.dumps(api_graph).encode())})
        client.put("/api/config/mapping", json=mapping)
        different = {"90": {"class_type": "Text", "inputs": {"text": "hi"}}}
        client.post("/api/config/workflow/import", files={"file": ("api.json", json.dumps(different).encode())})
        assert client.get("/api/config").json()["mapping_ready"] is False


def test_missing_job_and_video_are_404(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        assert client.get("/api/jobs/unknown").status_code == 404
        assert client.get("/api/jobs/unknown/video").status_code == 404


def test_complete_api_flow_sse_download_and_range(tmp_path, api_graph, mapping, png_bytes):
    import time
    import httpx
    from app.runninghub import RunningHub

    def handler(request):
        if request.url.path.endswith("/upload/binary"):
            return httpx.Response(200, json={"code": 0, "data": {"fileName": "openapi/reference.png"}})
        if request.url.path.endswith("/create"):
            return httpx.Response(200, json={"code": 0, "data": {"taskId": "2108942308824670209",
                                                                 "taskStatus": "QUEUED"}})
        if request.url.path.endswith("/query"):
            return httpx.Response(200, json={"status": "SUCCESS", "results": [
                {"url": "https://media.test/result.mp4", "outputType": "mp4"}]})
        return httpx.Response(200, content=b"0123456789-video")

    settings = Settings(data_dir=tmp_path, api_key="key", poll_seconds=0.01)
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with TestClient(create_app(settings, RunningHub("key", http=http))) as client:
        client.post("/api/config/workflow/import", files={"file": ("api.json", json.dumps(api_graph).encode())})
        client.put("/api/config/mapping", json=mapping)
        response = client.post("/api/jobs", data={"prompt": "hello", "duration": 6},
            files=[("images", ("ref.png", png_bytes, "image/png"))])
        assert response.status_code == 202
        job_id = response.json()["id"]
        for _ in range(100):
            state = client.get(f"/api/jobs/{job_id}").json()
            if state["phase"] == "succeeded":
                break
            time.sleep(0.01)
        assert state["phase"] == "succeeded"
        assert "private" not in state
        events = client.get(f"/api/jobs/{job_id}/events")
        assert "event: snapshot" in events.text
        assert '"phase": "succeeded"' in events.text
        video = client.get(state["video_url"], headers={"Range": "bytes=0-3"})
        assert video.status_code == 206
        assert video.content == b"0123"
        download = client.get(state["video_url"] + "?download=true")
        assert download.headers["content-disposition"].startswith("attachment")


def test_download_retry_runs_on_event_loop_and_never_creates_remote_task(tmp_path, api_graph):
    import time
    import httpx
    from app.runninghub import RunningHub

    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/already-generated.mp4"
        return httpx.Response(200, content=b"retried-download")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    application = create_app(Settings(data_dir=tmp_path, api_key="key"), RunningHub("key", http=http))
    store = application.state.store
    job = store.create(prompt="p", duration=5, image_count=1,
        private={"graph": api_graph, "result_url": "https://media.test/already-generated.mp4",
                 "video_extension": "mp4"})
    store.update(job["id"], phase="download_failed", remote_task_id="existing")
    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.post(f"/api/jobs/{job['id']}/retry-download")
        assert response.status_code == 202
        for _ in range(100):
            state = client.get(f"/api/jobs/{job['id']}").json()
            if state["phase"] == "succeeded":
                break
            time.sleep(0.01)
        assert state["phase"] == "succeeded"
        assert client.get(state["video_url"]).content == b"retried-download"


@pytest.mark.asyncio
async def test_two_attach_requests_cannot_change_a_running_monitor_task_id(tmp_path, api_graph):
    from app.runninghub import RunningHub
    first_entered = asyncio.Event()
    release_first = asyncio.Event()

    async def handler(request):
        task_id = json.loads(request.content)["taskId"]
        if task_id == "first":
            first_entered.set()
            await release_first.wait()
        return httpx.Response(200, json={"status": "RUNNING", "results": None})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        application = create_app(Settings(data_dir=tmp_path, api_key="key"), RunningHub("key", http=http))
        store = application.state.store
        job = store.create(prompt="p", duration=5, image_count=1, private={"graph": api_graph})
        store.update(job["id"], phase="submission_unknown")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
            first = asyncio.create_task(client.post(f"/api/jobs/{job['id']}/attach", json={"task_id": "first"}))
            await first_entered.wait()
            second = await client.post(f"/api/jobs/{job['id']}/attach", json={"task_id": "second"})
            release_first.set()
            first_response = await first
            assert second.status_code == 202
            assert first_response.status_code == 409
            assert store.get(job["id"])["remote_task_id"] == "second"
        await application.state.manager.close()


@pytest.mark.asyncio
async def test_download_retry_waits_for_old_runner_cleanup(tmp_path, api_graph):
    from app.runninghub import RunningHub
    cleanup = asyncio.Event()

    async def old_runner():
        await cleanup.wait()

    def handler(request):
        assert request.method == "GET"
        return httpx.Response(200, content=b"saved-video")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        application = create_app(Settings(data_dir=tmp_path, api_key="key"), RunningHub("key", http=http))
        manager, store = application.state.manager, application.state.store
        job = store.create(prompt="p", duration=5, image_count=1, private={"graph": api_graph,
            "result_url": "https://test/video.mp4", "video_extension": "mp4"})
        store.update(job["id"], phase="download_failed", remote_task_id="existing")
        manager.tasks[job["id"]] = asyncio.create_task(old_runner())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
            pending = asyncio.create_task(client.post(f"/api/jobs/{job['id']}/retry-download"))
            await asyncio.sleep(0.02)
            cleanup.set()
            assert (await pending).status_code == 202
            for _ in range(100):
                if store.get(job["id"])["phase"] == "succeeded":
                    break
                await asyncio.sleep(0.01)
            assert store.get(job["id"])["phase"] == "succeeded"
        await manager.close()

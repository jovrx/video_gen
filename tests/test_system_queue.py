import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.jobs import JobManager
from app.main import create_app
from app.store import Store
from tests.test_jobs import prepare


class ControlledPlatform:
    """External platform substitute; local scheduler, database and API stay real."""

    def __init__(self):
        self.created = []
        self.finished = set()

    async def upload(self, path):
        return "openapi/ref.png"

    async def create(self, workflow_id, overrides, **kwargs):
        task_id = f"remote-{len(self.created)}"
        self.created.append(task_id)
        return {"taskId": task_id, "taskStatus": "QUEUED"}

    async def query(self, task_id):
        return {"status": "FAILED" if task_id in self.finished else "QUEUED",
                "errorMessage": "controlled failure", "results": None}

    async def get_wss(self, task_id):
        return None

    @staticmethod
    def safe_text(value):
        return value

    async def close(self):
        pass


async def wait_until(condition):
    async with asyncio.timeout(3):
        while not condition():
            await asyncio.sleep(0.01)


def test_settings_persist_and_reject_invalid_limits(tmp_path):
    settings = Settings(data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/system-settings").json() == {
            "max_concurrent_generations": 3, "client_cooldown_seconds": 60}
        for value in (0, -1, 1.5, True):
            assert client.put("/api/system-settings", json={
                "max_concurrent_generations": value, "client_cooldown_seconds": 60}).status_code == 422
        assert client.put("/api/system-settings", json={
            "max_concurrent_generations": 2, "client_cooldown_seconds": -1}).status_code == 422
        response = client.put("/api/system-settings", json={
            "max_concurrent_generations": 2, "client_cooldown_seconds": 0})
        assert response.status_code == 200
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/system-settings").json() == {
            "max_concurrent_generations": 2, "client_cooldown_seconds": 0}


def test_atomic_cooldown_independent_clients_and_expiration(tmp_path, monkeypatch):
    from app.store import CooldownError
    monkeypatch.setattr("app.store.time.time", lambda: 1000)
    store = Store(tmp_path / "jobs.sqlite3")

    def submit():
        try:
            return store.create(prompt="p", duration=5, image_count=1, private={}, client_id="browser-a")
        except CooldownError as exc:
            return exc.retry_after

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: submit(), range(5)))
    assert len([value for value in results if isinstance(value, dict)]) == 1
    assert results.count(60) == 4
    store.create(prompt="p", duration=5, image_count=1, private={}, client_id="browser-b")
    assert len(store.list()) == 2
    monkeypatch.setattr("app.store.time.time", lambda: 1059)
    assert submit() == 1
    monkeypatch.setattr("app.store.time.time", lambda: 1060)
    assert isinstance(submit(), dict)
    assert Store(store.path).client_status("browser-a")["retry_after"] == 60


async def test_three_full_lifecycle_slots_and_fifo_positions(tmp_path, api_graph, mapping, png_bytes):
    settings = Settings(data_dir=tmp_path, api_key="key", poll_seconds=0.01)
    store = Store(tmp_path / "jobs.sqlite3")
    remote = ControlledPlatform()
    manager = JobManager(settings, store, remote)
    jobs = [prepare(settings, store, api_graph, mapping, png_bytes) for _ in range(5)]
    try:
        for job in jobs:
            manager.start(job["id"])
        await wait_until(lambda: len(remote.created) >= 3)
        await asyncio.sleep(0.04)
        assert len(remote.created) == 3
        assert store.get(jobs[3]["id"])["phase"] == "waiting"
        assert store.public(store.get(jobs[3]["id"]))["queue_position"] == 1
        assert store.public(store.get(jobs[4]["id"]))["queue_position"] == 2
        remote.finished.add("remote-0")
        await wait_until(lambda: store.get(jobs[3]["id"])["remote_task_id"] is not None)
        assert store.get(jobs[3]["id"])["remote_task_id"] == "remote-3"
        assert store.get(jobs[4]["id"])["queue_position"] == 1
    finally:
        await manager.close()


async def test_dynamic_limits_and_restart_prioritize_existing_remote_tasks(tmp_path, api_graph, mapping, png_bytes):
    from app.config import SystemSettings
    settings = Settings(data_dir=tmp_path, api_key="key", poll_seconds=0.01)
    store = Store(tmp_path / "jobs.sqlite3")
    store.save_system_settings(SystemSettings(max_concurrent_generations=1))
    remote = ControlledPlatform()
    manager = JobManager(settings, store, remote)
    jobs = [prepare(settings, store, api_graph, mapping, png_bytes) for _ in range(4)]
    try:
        for job in jobs:
            manager.start(job["id"])
        await wait_until(lambda: len(remote.created) == 1)
        store.save_system_settings(SystemSettings(max_concurrent_generations=2))
        manager.dispatch()
        await wait_until(lambda: len(remote.created) == 2)
        store.save_system_settings(SystemSettings(max_concurrent_generations=1))
        manager.dispatch()
        remote.finished.add("remote-0")
        await wait_until(lambda: store.get(jobs[0]["id"])["phase"] == "failed")
        await asyncio.sleep(0.04)
        assert len(remote.created) == 2
        await manager.close()
        manager = JobManager(settings, Store(store.path), remote)
        manager.recover()
        await asyncio.sleep(0.04)
        assert len(remote.created) == 2
        assert store.get(jobs[2]["id"])["queue_position"] == 1
        remote.finished.add("remote-1")
        await wait_until(lambda: store.get(jobs[2]["id"])["remote_task_id"] is not None)
        assert store.get(jobs[2]["id"])["remote_task_id"] == "remote-2"
        assert store.get(jobs[3]["id"])["queue_position"] == 1
    finally:
        await manager.close()


def configure(client, api_graph, mapping):
    client.post("/api/config/workflow/import", files={"file": ("api.json", json.dumps(api_graph).encode())})
    client.put("/api/config/mapping", json=mapping)


def submit_image(client, content):
    return client.post("/api/jobs", data={"prompt": "hello", "duration": 6},
                       files=[("images", ("ref.png", content, "image/png"))])


def test_api_browser_cooldown_refresh_and_invalid_upload(tmp_path, api_graph, mapping, png_bytes):
    settings = Settings(data_dir=tmp_path, api_key="key", poll_seconds=0.01)
    application = create_app(settings, ControlledPlatform())
    with TestClient(application) as client:
        configure(client, api_graph, mapping)
        assert submit_image(client, b"invalid image").status_code == 422
        assert client.get("/api/client-status").json()["retry_after"] == 0
        accepted = submit_image(client, png_bytes)
        assert accepted.status_code == 202
        rejected = submit_image(client, png_bytes)
        assert rejected.status_code == 429
        assert 1 <= int(rejected.headers["Retry-After"]) <= 60
        assert client.get("/api/client-status").json()["retry_after"] > 0
        assert len(application.state.store.list()) == 1
        cookie = client.cookies.get("video_client")
        assert cookie
    with TestClient(create_app(settings, ControlledPlatform())) as refreshed:
        refreshed.cookies.set("video_client", cookie)
        assert refreshed.get("/api/client-status").json()["retry_after"] > 0
        assert submit_image(refreshed, png_bytes).status_code == 429
        refreshed.cookies.clear()
        refreshed.get("/api/client-status")
        assert submit_image(refreshed, png_bytes).status_code == 202


def test_unknown_submission_reserves_capacity_until_explicit_resolution(tmp_path, api_graph, mapping, png_bytes):
    from app.config import SystemSettings
    settings = Settings(data_dir=tmp_path, api_key="key", poll_seconds=0.01)
    application = create_app(settings, ControlledPlatform())
    store = application.state.store
    store.save_system_settings(SystemSettings(max_concurrent_generations=1))
    unknown = prepare(settings, store, api_graph, mapping, png_bytes)
    store.update(unknown["id"], phase="submitting", slot_reserved=True)
    waiting = prepare(settings, store, api_graph, mapping, png_bytes)
    with TestClient(application) as client:
        client.put("/api/system-settings", json={
            "max_concurrent_generations": 1, "client_cooldown_seconds": 60})
        assert store.get(unknown["id"])["phase"] == "submission_unknown"
        assert store.get(waiting["id"])["remote_task_id"] is None
        assert client.post(f"/api/jobs/{unknown['id']}/resolve-unknown", json={
            "confirmed_not_submitted": False}).status_code == 422
        response = client.post(f"/api/jobs/{unknown['id']}/resolve-unknown", json={
            "confirmed_not_submitted": True})
        assert response.status_code == 200
        assert response.json()["phase"] == "interrupted"
        assert store.get(waiting["id"])["phase"] != "waiting"


async def test_parallel_api_submissions_share_cookie_and_leave_no_rejected_uploads(
        tmp_path, api_graph, mapping, png_bytes):
    settings = Settings(data_dir=tmp_path, api_key="key", poll_seconds=0.01)
    application = create_app(settings, ControlledPlatform())
    (tmp_path / "workflow-api.json").write_text(json.dumps(api_graph), encoding="utf-8")
    (tmp_path / "mapping.json").write_text(json.dumps(mapping), encoding="utf-8")
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
            await client.get("/api/client-status")
            responses = await asyncio.gather(*(client.post("/api/jobs", data={"prompt": "p", "duration": 6},
                files=[("images", ("ref.png", png_bytes, "image/png"))]) for _ in range(5)))
            assert sorted(response.status_code for response in responses) == [202, 429, 429, 429, 429]
            assert len(application.state.store.list()) == 1
            assert len(list((tmp_path / "uploads").iterdir())) == 1
            client.cookies.clear()
            rejected = await client.post("/api/jobs", data={"prompt": "p", "duration": 6},
                files=[("images", ("ref.png", png_bytes, "image/png"))])
            assert rejected.status_code == 428
            assert len(application.state.store.list()) == 1
    finally:
        await application.state.manager.close()


async def test_successful_generation_keeps_slot_until_video_saved(tmp_path, api_graph, mapping, png_bytes):
    from app.config import SystemSettings
    settings = Settings(data_dir=tmp_path, api_key="key", poll_seconds=0.01)
    store = Store(tmp_path / "jobs.sqlite3")
    store.save_system_settings(SystemSettings(max_concurrent_generations=1))
    saving = asyncio.Event()
    release = asyncio.Event()

    class DownloadingPlatform(ControlledPlatform):
        async def query(self, task_id):
            return {"status": "SUCCESS", "results": [{"url": "https://media.test/video.mp4", "outputType": "mp4"}]}

        async def download(self, url, path):
            saving.set()
            await release.wait()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"video")

    platform = DownloadingPlatform()
    manager = JobManager(settings, store, platform)
    first = prepare(settings, store, api_graph, mapping, png_bytes)
    second = prepare(settings, store, api_graph, mapping, png_bytes)
    try:
        manager.start(first["id"])
        manager.start(second["id"])
        await asyncio.wait_for(saving.wait(), 3)
        assert store.get(first["id"])["phase"] == "downloading"
        assert store.get(second["id"])["queue_position"] == 1
        assert len(platform.created) == 1
        release.set()
        await wait_until(lambda: store.get(second["id"])["phase"] == "succeeded")
        assert store.get(first["id"])["video_ready"] is True
        assert store.get(second["id"])["video_ready"] is True
        assert len(platform.created) == 2
        assert store.queue_status()["active"] == 0
    finally:
        await manager.close()


def test_settings_change_without_api_key_preserves_pending_jobs(tmp_path, api_graph, mapping, png_bytes):
    settings = Settings(data_dir=tmp_path)
    application = create_app(settings, ControlledPlatform())
    store = application.state.store
    job = prepare(settings, store, api_graph, mapping, png_bytes)
    store.update(job["id"], phase="waiting", queue_position=1)
    with TestClient(application) as client:
        assert client.put("/api/system-settings", json={
            "max_concurrent_generations": 2, "client_cooldown_seconds": 60}).status_code == 200
        assert store.get(job["id"])["phase"] == "waiting"
        assert store.get(job["id"])["remote_task_id"] is None


async def test_download_retry_does_not_reserve_another_generation_slot(tmp_path, api_graph, mapping, png_bytes):
    from app.config import SystemSettings
    settings = Settings(data_dir=tmp_path, api_key="key", poll_seconds=0.01)
    downloading = asyncio.Event()
    release = asyncio.Event()

    class RetryPlatform(ControlledPlatform):
        async def download(self, url, path):
            downloading.set()
            await release.wait()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"retried")

    application = create_app(settings, RetryPlatform())
    store = application.state.store
    store.save_system_settings(SystemSettings(max_concurrent_generations=1))
    running = prepare(settings, store, api_graph, mapping, png_bytes)
    store.update(running["id"], phase="running", remote_task_id="existing", slot_reserved=True)
    retry = store.create(prompt="p", duration=5, image_count=1, private={
        "graph": api_graph, "result_url": "https://media.test/video.mp4", "video_extension": "mp4"})
    store.update(retry["id"], phase="download_failed", remote_task_id="already-generated")
    manager = application.state.manager
    manager.recover()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
            assert (await client.post(f"/api/jobs/{retry['id']}/retry-download")).status_code == 202
            await asyncio.wait_for(downloading.wait(), 3)
            assert store.queue_status()["active"] == 1
            assert store.get(retry["id"])["slot_reserved"] is False
            await manager.close()
            downloading.clear()
            manager = JobManager(settings, Store(store.path), RetryPlatform())
            manager.recover()
            await asyncio.wait_for(downloading.wait(), 3)
            assert store.queue_status()["active"] == 1
            release.set()
            await wait_until(lambda: store.get(retry["id"])["phase"] == "succeeded")
    finally:
        await manager.close()

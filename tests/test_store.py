from app.store import Store


def test_history_pagination_reaches_older_than_recent_100_and_excludes_private_data(tmp_path):
    store = Store(tmp_path / "jobs.sqlite3")
    ids = []
    for i in range(125):
        job = store.create(prompt=f"video {i}", duration=5, image_count=1, private={"secret": "hidden"})
        store.update(job["id"], phase="succeeded")
        ids.append(job["id"])
    result = store.history(page=11, page_size=12)
    assert result["total"] == 125
    assert result["page"] == 11
    assert len(result["items"]) == 5
    assert {j["id"] for j in result["items"]} == set(ids[:5])
    assert "hidden" not in str(result)
    assert result["counts"] == {"all": 125, "active": 0, "succeeded": 125, "attention": 0}


def test_history_filters_searches_literal_text_and_counts_entire_library(tmp_path):
    store = Store(tmp_path / "jobs.sqlite3")
    for phase, prompt in [("running", "special 100%"), ("succeeded", "special 100x"),
                          ("failed", "winter"), ("download_failed", "winter"),
                          ("submission_unknown", "summer")]:
        job = store.create(prompt=prompt, duration=5, image_count=1, private={})
        store.update(job["id"], phase=phase, remote_task_id="remote-" + phase)
    result = store.history(status="active", search="100%")
    assert [j["prompt"] for j in result["items"]] == ["special 100%"]
    assert result["counts"] == {"all": 5, "active": 1, "succeeded": 1, "attention": 3}
    assert store.history(status="attention")["total"] == 3
    assert store.history(search="remote-succeeded")["total"] == 1
    assert store.history(search="no match")["items"] == []


def test_history_active_first_and_out_of_range_page(tmp_path):
    store = Store(tmp_path / "jobs.sqlite3")
    active = store.create(prompt="old active", duration=5, image_count=1, private={})
    done = store.create(prompt="new done", duration=5, image_count=1, private={})
    store.update(done["id"], phase="succeeded")
    assert store.history(sort="active")["items"][0]["id"] == active["id"]
    assert store.history(sort="oldest")["items"][0]["id"] == active["id"]
    result = store.history(page=999, page_size=1)
    assert result["page"] == 2
    assert result["items"][0]["id"] == active["id"]


def test_database_reopen_preserves_task_id_and_keeps_private_fields_out(tmp_path):
    db = tmp_path / "jobs.sqlite3"
    store = Store(db)
    job = store.create(prompt="hello", duration=8, image_count=2, private={"graph": {}, "wss": "secret"})
    store.update(job["id"], remote_task_id="2108942308824670209", phase="running")
    reopened = Store(db)
    result = reopened.get(job["id"])
    assert result["remote_task_id"] == "2108942308824670209"
    assert result["prompt"] == "hello"
    assert "private" not in reopened.public(result)
    assert "secret" not in str(reopened.list())
    assert reopened.recoverable()[0]["id"] == job["id"]


def test_finished_and_unknown_submissions_do_not_recover(tmp_path):
    store = Store(tmp_path / "jobs.sqlite3")
    for phase in ["succeeded", "failed", "submission_unknown", "download_failed"]:
        job = store.create(prompt="p", duration=5, image_count=1, private={})
        store.update(job["id"], phase=phase)
    assert store.recoverable() == []


def test_update_merges_progress_and_does_not_clobber_private_metadata(tmp_path):
    store = Store(tmp_path / "jobs.sqlite3")
    job = store.create(prompt="p", duration=5, image_count=1, private={"graph": {"1": "node"}})
    store.update(job["id"], progress={"node_id": "1"})
    assert store.get(job["id"])["private"]["graph"] == {"1": "node"}
    assert store.get(job["id"])["progress"] == {"node_id": "1"}


def test_long_active_job_is_not_hidden_by_newer_completed_jobs(tmp_path):
    store = Store(tmp_path / "jobs.sqlite3")
    running = store.create(prompt="long generation", duration=10, image_count=1, private={})
    store.update(running["id"], phase="running", remote_task_id="remote")
    for _ in range(5):
        job = store.create(prompt="finished", duration=5, image_count=1, private={})
        store.update(job["id"], phase="succeeded")
    visible = store.list(limit=2)
    assert any(job["id"] == running["id"] for job in visible)
    assert len(visible) == 3

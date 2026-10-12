from app.progress import Progress


def test_node_changes_and_real_inner_progress():
    progress = Progress({"1": "加载图片", "2": "生成视频"})
    progress.apply({"type": "executing", "data": {"node": "1", "prompt_id": "task"}}, "task")
    assert progress.snapshot()["node_percent"] is None
    progress.apply({"type": "executing", "data": {"node": "2", "prompt_id": "task"}}, "task")
    progress.apply({"type": "progress", "data": {"value": 2, "max": 8, "node": "2"}}, "task")
    snapshot = progress.snapshot()
    assert snapshot["node_name"] == "生成视频"
    assert snapshot["node_percent"] == 25
    assert snapshot["completed_nodes"] == ["1"]


def test_cache_is_idempotent_and_foreign_task_events_ignored():
    progress = Progress({"1": "Image", "2": "H3"})
    event = {"type": "execution_cached", "data": {"nodes": ["1", "1"], "prompt_id": "other"}}
    assert not progress.apply(event, "task")
    event["data"]["prompt_id"] = "task"
    progress.apply(event, "task")
    progress.apply(event, "task")
    assert progress.snapshot()["completed_nodes"] == ["1"]


def test_null_node_is_not_success_and_progress_without_node_uses_current():
    progress = Progress({"2": "H3"})
    progress.apply({"type": "executing", "data": {"node": "2"}}, "task")
    progress.apply({"type": "progress", "data": {"value": 3, "max": 0}}, "task")
    assert progress.snapshot()["node_percent"] is None
    progress.apply({"type": "executing", "data": {"node": None}}, "task")
    assert progress.snapshot()["execution_finished"] is False


def test_rehydration_and_dynamic_node_does_not_make_fake_global_percent():
    progress = Progress({"2": "H3"}, {"node_id": "2", "completed_nodes": ["1"], "node_percent": 40})
    progress.apply({"type": "progress", "data": {"node": "2:1", "value": 1, "max": 4}}, "task")
    assert progress.snapshot()["node_name"] == "2:1"
    assert progress.snapshot()["node_percent"] == 25
    assert "overall_percent" not in progress.snapshot()


def test_restart_retains_observed_execution_end():
    progress = Progress({"2": "H3"}, {"execution_finished": True, "completed_nodes": ["2"]})
    assert progress.snapshot()["execution_finished"] is True

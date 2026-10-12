import pytest

from app.workflow import WorkflowConfig, parse_graph


@pytest.fixture
def graph():
    return {
        "1": {"class_type": "OptionalImage", "inputs": {"image": "template-a.png"}},
        "2": {"class_type": "OptionalImage", "inputs": {"image": "template-b.png"}},
        "3": {"class_type": "H3", "inputs": {"prompt": "old", "duration": 5, "images": ["1", 0]}},
    }


def config(**kwargs):
    return WorkflowConfig.model_validate({
        "prompt": {"node_id": "3", "field_name": "prompt"},
        "duration": {"node_id": "3", "field_name": "duration"},
        "images": [{"node_id": "1", "field_name": "image"},
                   {"node_id": "2", "field_name": "image", "empty_value": "None"}],
        "min_duration": 5, "max_duration": 15, **kwargs,
    })


def test_ordered_images_and_unused_slots_do_not_use_template_images(graph):
    overrides = config().build_overrides(graph, ["openapi/a.png"], "hello", 8)
    assert overrides == [
        {"nodeId": "1", "fieldName": "image", "fieldValue": "openapi/a.png"},
        {"nodeId": "2", "fieldName": "image", "fieldValue": "None"},
        {"nodeId": "3", "fieldName": "prompt", "fieldValue": "hello"},
        {"nodeId": "3", "fieldName": "duration", "fieldValue": 8},
    ]


def test_missing_explicit_empty_value_rejects_fewer_images(graph):
    cfg = config(images=[{"node_id": "1", "field_name": "image"},
                         {"node_id": "2", "field_name": "image"}])
    with pytest.raises(ValueError, match="空值"):
        cfg.build_overrides(graph, ["a.png"], "hi", 5)


@pytest.mark.parametrize("files,duration", [([], 5), (["a", "b", "c"], 5), (["a"], 4), (["a"], 16)])
def test_input_limits_are_enforced_before_submission(graph, files, duration):
    with pytest.raises(ValueError):
        config().build_overrides(graph, files, "hi", duration)


def test_mapping_cannot_replace_a_comfyui_connection(graph):
    with pytest.raises(ValueError, match="连线"):
        config(prompt={"node_id": "3", "field_name": "images"}).validate_graph(graph)


def test_unknown_and_duplicate_mapping_rejected(graph):
    with pytest.raises(ValueError, match="不存在"):
        config(duration={"node_id": "99", "field_name": "duration"}).validate_graph(graph)
    with pytest.raises(ValueError, match="重复"):
        config(duration={"node_id": "3", "field_name": "prompt"}).validate_graph(graph)


def test_string_duration_retains_original_type(graph):
    graph["3"]["inputs"]["duration"] = "5"
    assert config().build_overrides(graph, ["a", "b"], "hi", 9)[-1]["fieldValue"] == "9"


def test_list_mode_and_zip_binding(graph):
    graph["3"]["inputs"]["references"] = []
    cfg = config(image_mode="list", images=[{"node_id": "3", "field_name": "references"}], max_images=9)
    assert cfg.build_overrides(graph, ["a", "b"], "hi", 5)[0]["fieldValue"] == ["a", "b"]
    graph["3"]["inputs"]["references"] = "[]"
    cfg.list_encoding = "json"
    assert cfg.build_overrides(graph, ["a", "b"], "hi", 5)[0]["fieldValue"] == '["a", "b"]'
    graph["3"]["inputs"]["upload"] = "template.zip"
    cfg = config(image_mode="zip", images=[{"node_id": "3", "field_name": "upload"}], max_images=9)
    assert cfg.build_overrides(graph, ["openapi/input.zip"], "hi", 5)[0]["fieldValue"] == "openapi/input.zip"


def test_ui_format_is_rejected_and_api_envelope_parsed(graph):
    import json
    assert parse_graph({"data": {"prompt": json.dumps(graph)}}) == graph
    with pytest.raises(ValueError, match="API"):
        parse_graph({"nodes": [{"id": 1}], "links": []})


@pytest.mark.parametrize("meta", [None, "title", {"title": ["invalid"]}])
def test_malformed_node_metadata_is_rejected_at_import(graph, meta):
    graph["1"]["_meta"] = meta
    with pytest.raises(ValueError, match="元信息"):
        parse_graph(graph)

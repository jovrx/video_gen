import copy
import json

import httpx
import pytest

from app.runninghub import RunningHub
from app.workflow import WorkflowConfig


@pytest.fixture
def h3_graph():
    return {
        "150": {"class_type": "LoadImage", "inputs": {"image": "template-first.png"}},
        "164": {"class_type": "LoadImage", "inputs": {"image": "template-second.png"}},
        "240": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "old prompt"}},
        "132": {"class_type": "PrimitiveFloat", "inputs": {"value": 5}},
        "136": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {
            "ref_images.ref_image_0": ["150", 0], "ref_images.ref_image_1": ["164", 0],
            "prompt": ["238", 0], "width": 1344}},
        "238": {"class_type": "QwenH3PromptLocal", "inputs": {
            "reference_images.reference_image_0": ["150", 0],
            "reference_images.reference_image_1": ["164", 0],
            "prompt": ["240", 0], "duration": ["132", 0]}},
        "180": {"class_type": "VHS_VideoCombine", "inputs": {"format": "video/h264-mp4"}},
    }


def h3_mapping():
    return WorkflowConfig(prompt={"node_id": "240", "field_name": "value"},
                          duration={"node_id": "132", "field_name": "value"},
                          images=[{"node_id": "150", "field_name": "image"},
                                  {"node_id": "164", "field_name": "image"}],
                          image_mode="h3_dynamic", min_images=1, max_images=9,
                          min_duration=5, max_duration=15)


@pytest.mark.parametrize("count", [1, 3, 9])
def test_all_h3_consumers_receive_exact_ordered_uploads_without_template_images(h3_graph, count):
    original = copy.deepcopy(h3_graph)
    files = [f"openapi/upload-{i}.png" for i in range(count)]
    graph = h3_mapping().build_workflow(h3_graph, files, "new prompt", 8)
    assert h3_graph == original
    assert graph["240"]["inputs"]["value"] == "new prompt"
    assert graph["132"]["inputs"]["value"] == 8
    assert graph["180"] == original["180"]
    assert "template-first.png" not in json.dumps(graph)
    assert "template-second.png" not in json.dumps(graph)
    for node, prefix in [("136", "ref_images.ref_image_"),
                         ("238", "reference_images.reference_image_")]:
        fields = {k: v for k, v in graph[node]["inputs"].items() if k.startswith(prefix)}
        assert len(fields) == count
        assert [graph[fields[f"{prefix}{i}"][0]]["inputs"]["image"]
                for i in range(count)] == files
    assert graph["136"]["inputs"]["prompt"] == ["238", 0]


@pytest.mark.parametrize("count", [0, 10])
def test_dynamic_h3_rejects_unsupported_image_count(h3_graph, count):
    with pytest.raises(ValueError):
        h3_mapping().build_workflow(h3_graph, ["a.png"] * count, "hi", 5)


def test_dynamic_h3_does_not_apply_to_an_unrecognized_workflow(h3_graph):
    h3_graph["238"]["class_type"] = "OtherPromptNode"
    with pytest.raises(ValueError, match="H3"):
        h3_mapping().validate_graph(h3_graph)


def test_dynamic_h3_rejects_image_mapping_unrelated_to_reference_loaders(h3_graph):
    mapping = h3_mapping()
    mapping.images[0].node_id = "180"
    mapping.images[0].field_name = "format"
    with pytest.raises(ValueError, match="参考图来源"):
        mapping.validate_graph(h3_graph)


async def test_create_sends_custom_workflow_as_json_string(h3_graph):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"code": 0, "msg": "success", "data": {
            "taskId": "2108942308824670209", "taskStatus": "QUEUED", "netWssUrl": None}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await RunningHub("test-key", http=http).create("target", [], workflow=h3_graph)
    assert json.loads(requests[0]["workflow"]) == h3_graph
    assert requests[0]["apiKey"] == "test-key"
    assert requests[0]["nodeInfoList"] == []

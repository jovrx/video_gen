import io

import pytest
from PIL import Image


@pytest.fixture
def api_graph():
    return {"10": {"class_type": "LoadImage", "inputs": {"image": "default.png"}},
            "20": {"class_type": "H3", "inputs": {"prompt": "old", "duration": 5},
                   "_meta": {"title": "视频生成"}}}


@pytest.fixture
def mapping():
    return {"prompt": {"node_id": "20", "field_name": "prompt"},
            "duration": {"node_id": "20", "field_name": "duration"},
            "images": [{"node_id": "10", "field_name": "image"}],
            "min_duration": 5, "max_duration": 15}


@pytest.fixture
def png_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), "blue").save(buffer, format="PNG")
    return buffer.getvalue()

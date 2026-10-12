from typing import Any


class Progress:
    """Observed node progress only; never infer an overall time percentage."""

    def __init__(self, names: dict[str, str], previous: dict | None = None):
        self.names = names
        previous = previous or {}
        self.node_id = previous.get("node_id")
        self.percent = previous.get("node_percent")
        self.completed = set(previous.get("completed_nodes", []))
        self.finished = bool(previous.get("execution_finished", False))

    def apply(self, event: dict, prompt_id: str | None = None) -> bool:
        if not isinstance(event, dict) or not isinstance(event.get("data"), dict):
            return False
        data = event["data"]
        if prompt_id and data.get("prompt_id") is not None and str(data["prompt_id"]) != prompt_id:
            return False
        kind = event.get("type")
        if kind == "executing":
            node = str(data["node"]) if data.get("node") is not None else None
            if self.node_id and self.node_id != node:
                self.completed.add(self.node_id)
            if node != self.node_id:
                self.percent = None
            self.node_id = node
        elif kind == "progress":
            if data.get("node") is not None:
                node = str(data["node"])
                if self.node_id != node:
                    self.percent = None
                self.node_id = node
            value, maximum = data.get("value"), data.get("max")
            if isinstance(value, (int, float)) and isinstance(maximum, (int, float)) and maximum > 0:
                self.percent = round(max(0, min(100, value / maximum * 100)), 1)
            else:
                self.percent = None
        elif kind == "execution_cached":
            if isinstance(data.get("nodes"), list):
                self.completed.update(str(node) for node in data["nodes"] if node is not None)
        elif kind == "execution_success":
            if self.node_id:
                self.completed.add(self.node_id)
            self.finished = True
        else:
            return False
        return True

    def snapshot(self) -> dict[str, Any]:
        return {"node_id": self.node_id, "node_name": self.names.get(self.node_id, self.node_id),
                "node_percent": self.percent, "completed_nodes": sorted(self.completed),
                "total_nodes": len(self.names), "execution_finished": self.finished}

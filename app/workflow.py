import copy
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def parse_graph(value: Any) -> dict:
    if isinstance(value, dict) and "data" in value:
        value = value["data"]
    if isinstance(value, dict) and "prompt" in value:
        value = value["prompt"]
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError) as exc:
            raise ValueError("工作流不是有效的 API JSON") from exc
    if not isinstance(value, dict) or not value or "nodes" in value:
        raise ValueError("请导入『导出工作流 API』格式的 JSON")
    for node_id, node in value.items():
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict) or not node.get("class_type"):
            raise ValueError(f"节点 {node_id} 不符合工作流 API 格式")
        meta = node.get("_meta", {})
        if not isinstance(meta, dict) or ("title" in meta and not isinstance(meta["title"], str)):
            raise ValueError(f"节点 {node_id} 的元信息格式无效")
    return value


class Binding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str
    field_name: str

    def override(self, value: Any) -> dict:
        return {"nodeId": self.node_id, "fieldName": self.field_name, "fieldValue": value}


class ImageBinding(Binding):
    empty_value: Any = None


class WorkflowConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    prompt: Binding
    duration: Binding
    images: list[ImageBinding] = Field(min_length=1)
    image_mode: Literal["slots", "list", "zip", "h3_dynamic"] = "slots"
    list_encoding: Literal["array", "json"] = "array"
    min_images: int = Field(default=1, ge=1)
    max_images: int = Field(default=9, ge=1, le=100)
    min_duration: int = Field(ge=1)
    max_duration: int = Field(ge=1)

    @model_validator(mode="after")
    def coherent_limits(self):
        if self.min_duration > self.max_duration or self.min_images > self.max_images:
            raise ValueError("最小值不能大于最大值")
        if self.image_mode in {"list", "zip"} and len(self.images) != 1:
            raise ValueError("数组或 ZIP 模式需要恰好一个图片输入映射")
        if self.image_mode == "slots" and self.min_images > len(self.images):
            raise ValueError("最小图数不能超过图片槽位数")
        if self.image_mode == "h3_dynamic" and self.max_images > 9:
            raise ValueError("H3 参考图节点最多支持 9 张图片")
        return self

    def validate_graph(self, graph: dict) -> None:
        seen = set()
        for binding in [*self.images, self.prompt, self.duration]:
            key = (binding.node_id, binding.field_name)
            if key in seen:
                raise ValueError("节点字段映射重复")
            seen.add(key)
            if binding.node_id not in graph or binding.field_name not in graph[binding.node_id]["inputs"]:
                raise ValueError(f"节点字段不存在：{binding.node_id}.{binding.field_name}")
            value = graph[binding.node_id]["inputs"][binding.field_name]
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and value[0] in graph:
                if isinstance(value[1], int):
                    raise ValueError(f"不能覆盖连线字段：{binding.node_id}.{binding.field_name}")
        if not isinstance(self.value_at(graph, self.prompt), str):
            raise ValueError("提示词映射需要文本字段")
        duration = self.value_at(graph, self.duration)
        if isinstance(duration, bool) or not isinstance(duration, (str, int, float)):
            raise ValueError("时长映射需要秒数文本或数值字段")
        if self.image_mode == "list":
            value = self.value_at(graph, self.images[0])
            expected = list if self.list_encoding == "array" else str
            if not isinstance(value, expected):
                raise ValueError("图片数组编码与工作流字段类型不一致")
        else:
            if any(not isinstance(self.value_at(graph, slot), str) for slot in self.images):
                raise ValueError("图片槽位或 ZIP 映射需要文件名文本字段")
        if self.image_mode == "h3_dynamic":
            targets = self.h3_targets(graph)
            sources = {v[0] for node_id, prefix in targets
                       for k, v in graph[node_id]["inputs"].items() if k.startswith(prefix)}
            if (any(slot.field_name != "image" for slot in self.images)
                    or {slot.node_id for slot in self.images} != sources):
                raise ValueError("H3 图片映射需与两个节点的 LoadImage 参考图来源一致")

    @staticmethod
    def h3_targets(graph: dict) -> list[tuple[str, str]]:
        targets = []
        for class_type, prefix in [("MiniMaxH3ReferenceToVideo", "ref_images.ref_image_"),
                                   ("QwenH3PromptLocal", "reference_images.reference_image_")]:
            matches = [node_id for node_id, node in graph.items() if node["class_type"] == class_type]
            if len(matches) != 1:
                raise ValueError(f"H3 动态图片模式需要一个 {class_type} 节点")
            node_id = matches[0]
            references = [v for k, v in graph[node_id]["inputs"].items() if k.startswith(prefix)]
            if not references or any(
                not isinstance(v, list) or len(v) != 2 or v[1] != 0
                or v[0] not in graph or graph[v[0]]["class_type"] != "LoadImage"
                for v in references
            ):
                raise ValueError("H3 动态图片模式需要已确认的 LoadImage 参考图连线")
            targets.append((node_id, prefix))
        return targets

    @staticmethod
    def value_at(graph: dict, binding: Binding) -> Any:
        return graph[binding.node_id]["inputs"][binding.field_name]

    def validate_request(self, count: int, prompt: str, duration: int) -> None:
        upper = min(self.max_images, len(self.images)) if self.image_mode == "slots" else self.max_images
        if not self.min_images <= count <= upper:
            raise ValueError(f"参考图数量需为 {self.min_images}–{upper} 张")
        if not prompt.strip() or len(prompt) > 20000:
            raise ValueError("提示词不能为空，且不能超过 20000 字符")
        if not self.min_duration <= duration <= self.max_duration:
            raise ValueError(f"时长需为 {self.min_duration}–{self.max_duration} 秒整数")
        if self.image_mode == "slots":
            for slot in self.images[count:]:
                if "empty_value" not in slot.model_fields_set:
                    raise ValueError(f"未使用图片槽位 {slot.node_id} 需要配置明确的空值")

    def build_overrides(self, graph: dict, files: list[str], prompt: str, duration: int) -> list[dict]:
        if self.image_mode == "h3_dynamic":
            raise ValueError("H3 动态图片模式需要提交完整工作流")
        self.validate_graph(graph)
        if self.image_mode != "zip":
            self.validate_request(len(files), prompt, duration)
        else:
            if len(files) != 1 or not prompt.strip() or not self.min_duration <= duration <= self.max_duration:
                raise ValueError("ZIP 上传或时长参数无效")
        if self.image_mode == "slots":
            result = [slot.override(files[index] if index < len(files) else slot.empty_value)
                      for index, slot in enumerate(self.images)]
        elif self.image_mode == "list":
            value = files if self.list_encoding == "array" else json.dumps(files, ensure_ascii=False)
            result = [self.images[0].override(value)]
        else:
            result = [self.images[0].override(files[0])]
        original_duration = self.value_at(graph, self.duration)
        encoded_duration = str(duration) if isinstance(original_duration, str) else duration
        result += [self.prompt.override(prompt), self.duration.override(encoded_duration)]
        return result

    def build_workflow(self, graph: dict, files: list[str], prompt: str, duration: int) -> dict:
        self.validate_graph(graph)
        self.validate_request(len(files), prompt, duration)
        if self.image_mode != "h3_dynamic":
            raise ValueError("完整工作流构建仅用于 H3 动态图片模式")
        graph = copy.deepcopy(graph)
        old_loaders = set()
        targets = self.h3_targets(graph)
        for node_id, prefix in targets:
            inputs = graph[node_id]["inputs"]
            for field in list(inputs):
                if field.startswith(prefix):
                    old_loaders.add(inputs.pop(field)[0])
        next_id = max((int(n) for n in graph if n.isdecimal()), default=0) + 1
        for index, filename in enumerate(files):
            node_id = str(next_id + index)
            graph[node_id] = {"class_type": "LoadImage", "inputs": {"image": filename},
                              "_meta": {"title": f"参考图{index + 1}"}}
            for target_id, prefix in targets:
                graph[target_id]["inputs"][f"{prefix}{index}"] = [node_id, 0]
        # Remove only obsolete loaders with no remaining consumer.
        referenced = {v[0] for node in graph.values() for v in node["inputs"].values()
                      if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str)
                      and isinstance(v[1], int)}
        for node_id in old_loaders - referenced:
            del graph[node_id]
        graph[self.prompt.node_id]["inputs"][self.prompt.field_name] = prompt
        original = self.value_at(graph, self.duration)
        graph[self.duration.node_id]["inputs"][self.duration.field_name] = (
            str(duration) if isinstance(original, str) else duration)
        return graph


def node_names(graph: dict) -> dict[str, str]:
    return {node_id: node.get("_meta", {}).get("title") or node["class_type"]
            for node_id, node in graph.items()}

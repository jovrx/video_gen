import json
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.workflow import parse_graph


class RunningHubError(Exception):
    """Definite platform rejection or a read-side error, with safe public text."""


class SubmissionUnknown(Exception):
    """The paid create may have reached the platform; do not submit again."""


class RunningHub:
    def __init__(self, api_key: str, base_url: str = "https://www.runninghub.cn", *,
                 http: httpx.AsyncClient | None = None):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._owns_http = http is None
        self.http = http or httpx.AsyncClient(timeout=httpx.Timeout(60, connect=15), follow_redirects=True)

    def safe_text(self, text: str) -> str:
        return str(text).replace(self.api_key, "[REDACTED]")[:800] if self.api_key else str(text)[:800]

    async def close(self):
        if self._owns_http:
            await self.http.aclose()

    async def _post(self, path: str, payload: dict, *, legacy=False, create=False) -> dict:
        if not self.api_key:
            raise RunningHubError("尚未配置 RUNNINGHUB_API_KEY")
        body = {**payload, "apiKey": self.api_key} if legacy else payload
        try:
            response = await self.http.post(self.base_url + path, json=body,
                                            headers={"Authorization": f"Bearer {self.api_key}"})
            if create and response.status_code >= 500:
                raise SubmissionUnknown("平台提交响应异常；请到 RunningHub 任务列表核实，系统不会自动重提")
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("not an object")
            return result
        except (httpx.RequestError, ValueError) as exc:
            if create:
                raise SubmissionUnknown("提交结果未知；请到 RunningHub 核实，系统不会自动重提") from exc
            raise RunningHubError("RunningHub 暂时无法连接或返回了无效响应") from exc
        except httpx.HTTPStatusError as exc:
            raise RunningHubError(f"RunningHub 请求失败（HTTP {exc.response.status_code}）") from exc

    def _data(self, result: dict) -> dict:
        if result.get("code") != 0:
            message = result.get("msg") or result.get("message") or "平台拒绝请求"
            raise RunningHubError(self.safe_text(f"RunningHub {result.get('code')}: {message}"))
        data = result.get("data")
        if not isinstance(data, dict):
            raise RunningHubError("RunningHub 响应缺少数据")
        return data

    async def get_workflow(self, workflow_id: str) -> dict:
        result = await self._post("/api/openapi/getJsonApiFormat", {"workflowId": workflow_id}, legacy=True)
        return parse_graph(self._data(result))

    async def upload(self, path: Path) -> str:
        if not self.api_key:
            raise RunningHubError("尚未配置 RUNNINGHUB_API_KEY")
        try:
            with path.open("rb") as file:
                response = await self.http.post(self.base_url + "/openapi/v2/media/upload/binary",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    files={"file": (path.name, file, mimetypes.guess_type(path.name)[0] or "application/octet-stream")})
            response.raise_for_status()
            data = self._data(response.json())
            if not isinstance(data.get("fileName"), str) or not data["fileName"]:
                raise RunningHubError("上传响应没有 fileName")
            return data["fileName"]
        except (httpx.HTTPError, ValueError) as exc:
            raise RunningHubError("图片上传失败，请检查网络和 RunningHub 服务") from exc

    async def create(self, workflow_id: str, overrides: list[dict], *, workflow: dict | None = None) -> dict:
        payload = {"workflowId": workflow_id, "nodeInfoList": overrides}
        if workflow is not None:
            payload["workflow"] = json.dumps(workflow, ensure_ascii=False)
        result = await self._post("/task/openapi/create", payload, legacy=True, create=True)
        if type(result.get("code")) is not int:
            raise SubmissionUnknown("提交响应缺少状态，结果未知，请到 RunningHub 核实")
        if result["code"] != 0:
            self._data(result)  # Only an explicit platform rejection is a definite failure.
        data = result.get("data")
        task_id = data.get("taskId") if isinstance(data, dict) else None
        valid_id = ((isinstance(task_id, str) and bool(task_id.strip()))
                    or (type(task_id) is int and task_id > 0))
        if not valid_id:
            raise SubmissionUnknown("提交响应没有 taskId，请到 RunningHub 核实")
        data["taskId"] = str(data["taskId"])
        # Persist the taskId even if promptTips contains errors; query will reconcile the task.
        return data

    async def query(self, task_id: str) -> dict:
        result = await self._post("/openapi/v2/query", {"taskId": str(task_id)})
        if result.get("status") not in {"QUEUED", "RUNNING", "SUCCESS", "FAILED"}:
            raise RunningHubError("平台未返回可识别的任务状态")
        return result

    async def get_wss(self, task_id: str) -> str | None:
        result = await self._post("/task/openapi/outputs", {"taskId": str(task_id)}, legacy=True)
        if result.get("code") == 804 and isinstance(result.get("data"), dict):
            address = result["data"].get("netWssUrl")
            if isinstance(address, str) and address.startswith("wss://"):
                return address
        if result.get("code") in {0, 804, 813, 805}:
            return None
        raise RunningHubError("详细进度接口暂不可用，继续查询任务状态")

    async def download(self, url: str, path: Path) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise RunningHubError("视频结果地址无效")
        temporary = path.with_suffix(path.suffix + ".part")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            # Credentials are intentionally absent on media requests and redirects.
            async with self.http.stream("GET", url, timeout=httpx.Timeout(120, connect=15)) as response:
                response.raise_for_status()
                size = 0
                with temporary.open("wb") as file:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 2 * 1024**3:
                            raise RunningHubError("视频文件超过本地 2GB 保存上限")
                        file.write(chunk)
                if size == 0:
                    raise RunningHubError("平台返回了空视频文件")
            temporary.replace(path)
        except httpx.HTTPError as exc:
            raise RunningHubError("视频下载失败，可重试下载，无需重新生成") from exc
        finally:
            temporary.unlink(missing_ok=True)


def validation_error(prompt_tips: str | dict | None) -> str | None:
    try:
        tips = json.loads(prompt_tips) if isinstance(prompt_tips, str) and prompt_tips else prompt_tips
    except ValueError:
        return None
    if isinstance(tips, dict) and (tips.get("result") is False or tips.get("node_errors")):
        return "工作流节点校验异常，请查看 RunningHub 任务详情和节点映射"
    return None

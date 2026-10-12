import asyncio
import contextlib
import json
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from websockets.asyncio.client import connect

from app.config import Settings
from app.progress import Progress
from app.runninghub import RunningHub, RunningHubError, SubmissionUnknown, validation_error
from app.store import Store, TERMINAL_PHASES
from app.workflow import WorkflowConfig, node_names

VIDEO_EXTENSIONS = {"mp4", "webm", "mov", "mkv", "avi"}


def video_result(results: list) -> tuple[str, str] | None:
    for item in reversed(results):
        if not isinstance(item, dict) or not isinstance(item.get("url"), str):
            continue
        extension = str(item.get("outputType", "")).lower().removeprefix("video/").lstrip(".")
        path_extension = Path(urlparse(item["url"]).path).suffix.lower().lstrip(".")
        if extension in VIDEO_EXTENSIONS or path_extension in VIDEO_EXTENSIONS:
            return item["url"], extension if extension in VIDEO_EXTENSIONS else path_extension
    return None


class JobManager:
    def __init__(self, settings: Settings, store: Store, client: RunningHub):
        self.settings, self.store, self.client = settings, store, client
        self.tasks: dict[str, asyncio.Task] = {}
        self.closing = False
        self.recovering = False

    def start(self, job_id: str, *, reserve_slot: bool = True):
        existing = self.tasks.get(job_id)
        if existing and not existing.done():
            return
        job = self.store.get(job_id)
        if not job or job["phase"] in TERMINAL_PHASES:
            return
        if job.get("remote_task_id"):
            self.store.update(job_id, slot_reserved=reserve_slot and not job.get("download_only", False),
                              queue_position=None)
            self._launch(job_id)
        else:
            self.store.update(job_id, phase="waiting", slot_reserved=False, queue_position=None)
        if not self.recovering:
            self.dispatch()

    def _launch(self, job_id: str):
        self.tasks[job_id] = asyncio.create_task(self._run(job_id), name=f"video-{job_id}")

    def dispatch(self):
        if self.closing or self.recovering or not self.settings.api_key:
            return
        self.tasks = {key: task for key, task in self.tasks.items() if not task.done()}
        available = max(0, self.store.system_settings().max_concurrent_generations
                        - self.store.queue_status()["active"])
        for job in self.store.recoverable():
            if not available:
                break
            if job["phase"] != "waiting":
                continue
            self.store.update(job["id"], phase="uploading", slot_reserved=True, queue_position=None)
            self._launch(job["id"])
            available -= 1
        self.store.refresh_queue_positions()

    async def settle(self, job_id: str):
        """Wait for cleanup of a runner whose terminal state was already persisted."""
        previous = self.tasks.get(job_id)
        if previous and not previous.done():
            await asyncio.shield(previous)

    def recover(self):
        if not self.settings.api_key:
            return
        self.recovering = True
        try:
            for job in self.store.recoverable():
                if job["id"] in self.tasks and not self.tasks[job["id"]].done():
                    continue
                if job["phase"] == "submitting" and not job.get("remote_task_id"):
                    self.store.update(job["id"], phase="submission_unknown", slot_reserved=True,
                        queue_position=None,
                        error="服务在提交时中断，结果未知。请从 RunningHub 任务列表核实并关联任务 ID。")
                else:
                    self.start(job["id"])
        finally:
            self.recovering = False
        self.dispatch()

    async def close(self):
        self.closing = True
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(self, job_id: str):
        try:
            job = self.store.get(job_id)
            if job["phase"] in TERMINAL_PHASES:
                return
            if not job.get("remote_task_id"):
                await self._submit(job_id)
            job = self.store.get(job_id)
            if job.get("remote_task_id"):
                if job["phase"] == "downloading" and job["private"].get("result_url"):
                    await self._download(job_id)
                else:
                    await self._monitor(job_id)
        except SubmissionUnknown as exc:
            self.store.update(job_id, phase="submission_unknown", error=str(exc))
        except (RunningHubError, ValueError, OSError) as exc:
            self.store.update(job_id, phase="failed", error=self.client.safe_text(str(exc)))
        except asyncio.CancelledError:
            raise
        except Exception:
            # Do not expose exception reprs, which can contain signed URLs or workflow credentials.
            self.store.update(job_id, phase="failed", error="任务处理出现异常，请检查本地配置和工作流")
        finally:
            job = self.store.get(job_id)
            if job and job["phase"] in TERMINAL_PHASES and job["phase"] != "submission_unknown":
                self.store.update(job_id, slot_reserved=False, queue_position=None)
            self.dispatch()

    async def _submit(self, job_id: str):
        job = self.store.get(job_id)
        private = job["private"]
        mapping = WorkflowConfig.model_validate(private["mapping"])
        paths = [Path(name) for name in private["image_paths"]]
        mapping.validate_request(len(paths), job["prompt"], job["duration"])
        mapping.validate_graph(private["graph"])
        self.store.update(job_id, phase="uploading", notice=None)
        if mapping.image_mode == "zip":
            archive = self.settings.data_dir / "uploads" / f"{job_id}.zip"
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
                for index, path in enumerate(paths, 1):
                    bundle.write(path, f"{index:03d}{path.suffix}")
            paths = [archive]
        filenames = []
        for index, path in enumerate(paths, 1):
            filenames.append(await self.client.upload(path))
            self.store.update(job_id, notice=f"素材上传 {index}/{len(paths)}")
        workflow = None
        if mapping.image_mode == "h3_dynamic":
            workflow = mapping.build_workflow(private["graph"], filenames, job["prompt"], job["duration"])
            private = {**private, "graph": workflow}
            overrides = []
        else:
            overrides = mapping.build_overrides(private["graph"], filenames, job["prompt"], job["duration"])
        self.store.update(job_id, phase="submitting", notice=None, private=private)
        # A crash from here until taskId is persisted is an unknown submission, never a retry.
        if workflow is not None:
            response = await self.client.create(private["workflow_id"], overrides, workflow=workflow)
        else:
            response = await self.client.create(private["workflow_id"], overrides)
        private = {**private, "wss_url": response.get("netWssUrl"), "prompt_id": response.get("promptId")}
        phase = "queued" if response.get("taskStatus") == "QUEUED" else "running"
        self.store.update(job_id, remote_task_id=response["taskId"], phase=phase, private=private,
                          notice=validation_error(response.get("promptTips")))

    async def _monitor(self, job_id: str):
        job = self.store.get(job_id)
        remote_id = job["remote_task_id"]
        progress = Progress(node_names(job["private"]["graph"]), job.get("progress"))
        socket_task = asyncio.create_task(self._progress_loop(job_id, progress))
        query_errors = 0
        success_without_outputs = 0
        try:
            while True:
                try:
                    result = await self.client.query(remote_id)
                    query_errors = 0
                except RunningHubError:
                    query_errors += 1
                    self.store.update(job_id, notice="状态查询暂时失败，正在重连；不会重新提交生成")
                    await asyncio.sleep(min(30, self.settings.poll_seconds * max(1, query_errors)))
                    continue
                status = result["status"]
                if status == "FAILED":
                    reason = result.get("failedReason") or {}
                    if not isinstance(reason, dict):
                        reason = {}
                    detail = result.get("errorMessage") or "RunningHub 生成失败"
                    node = reason.get("node_id") or reason.get("node_name")
                    if node:
                        detail += f"（节点 {node}）"
                    if reason.get("exception_message"):
                        detail += f"：{reason['exception_message']}"
                    self.store.update(job_id, phase="failed", error=self.client.safe_text(detail), notice=None)
                    return
                if status == "SUCCESS":
                    results = result.get("results")
                    if results is None:
                        success_without_outputs += 1
                        self.store.update(job_id, phase="fetching", notice="工作流已结束，等待视频结果")
                        if success_without_outputs > 12:
                            raise RunningHubError("工作流已结束但未返回输出；请检查 RunningHub 任务详情")
                    else:
                        selected = video_result(results) if isinstance(results, list) else None
                        if not selected:
                            raise RunningHubError("工作流成功但没有视频输出，请检查视频保存节点")
                        url, extension = selected
                        private = {**self.store.get(job_id)["private"], "result_url": url,
                                   "video_extension": extension}
                        self.store.update(job_id, phase="downloading", private=private, notice=None)
                        await self._download(job_id)
                        return
                else:
                    self.store.update(job_id, phase="queued" if status == "QUEUED" else "running",
                                      notice=None if not validation_error(result.get("promptTips"))
                                      else validation_error(result.get("promptTips")))
                await asyncio.sleep(self.settings.poll_seconds)
        finally:
            if socket_task:
                socket_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await socket_task

    async def _progress_loop(self, job_id: str, progress: Progress):
        job = self.store.get(job_id)
        address = job["private"].get("wss_url")
        while True:
            job = self.store.get(job_id)
            if job["phase"] in TERMINAL_PHASES or job["phase"] in {"fetching", "downloading"}:
                return
            if address:
                await self._watch_socket(job_id, address, progress)
                address = None
            elif job["phase"] == "running":
                try:
                    address = await self.client.get_wss(job["remote_task_id"])
                except RunningHubError:
                    address = None
                if address:
                    continue
                self.store.update(job_id, notice="生成中，详细节点进度暂不可用")
            await asyncio.sleep(min(15, self.settings.poll_seconds * 2))

    async def _watch_socket(self, job_id: str, address: str, progress: Progress):
        expected_prompt = self.store.get(job_id)["private"].get("prompt_id")
        try:
            async with connect(address, open_timeout=15, ping_interval=20, ping_timeout=30,
                               max_size=2 * 1024**2) as websocket:
                async for raw in websocket:
                    if not isinstance(raw, str):
                        continue  # ComfyUI binary preview frames are not progress events.
                    try:
                        event = json.loads(raw)
                    except ValueError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    data = event.get("data")
                    if not isinstance(data, dict):
                        continue
                    observed_prompt = data.get("prompt_id")
                    # ComfyUI prompt_id is not assumed to equal RunningHub taskId.
                    if expected_prompt is None and observed_prompt is not None and event.get("type") in {
                            "execution_start", "executing", "progress"}:
                        expected_prompt = str(observed_prompt)
                        private = {**self.store.get(job_id)["private"], "prompt_id": expected_prompt}
                        self.store.update(job_id, private=private)
                    if progress.apply(event, str(expected_prompt) if expected_prompt else None):
                        self.store.update(job_id, progress=progress.snapshot())
        except asyncio.CancelledError:
            raise
        except Exception:
            # Keep polling the original task even when the expiring WSS address disconnects.
            self.store.update(job_id, notice="实时进度连接中断，仍在查询生成状态")

    async def _download(self, job_id: str):
        job = self.store.get(job_id)
        private = job["private"]
        extension = private.get("video_extension", "mp4")
        if extension not in VIDEO_EXTENSIONS:
            raise RunningHubError("视频格式不受支持")
        path = self.settings.data_dir / "videos" / f"{job_id}.{extension}"
        try:
            await self.client.download(private["result_url"], path)
        except (RunningHubError, OSError):
            self.store.update(job_id, phase="download_failed", error="视频已生成，下载失败。可仅重试下载。")
            return
        private = {**private, "video_path": str(path)}
        self.store.update(job_id, phase="succeeded", video_ready=True, private=private,
                          error=None, notice=None)

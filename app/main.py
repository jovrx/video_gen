import asyncio
import io
import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ValidationError

from app.config import Settings, SystemSettings
from app.jobs import JobManager
from app.runninghub import RunningHub, RunningHubError
from app.store import CooldownError, Store, TERMINAL_PHASES
from app.workflow import WorkflowConfig, node_names, parse_graph

STATIC = Path(__file__).parent / "static"


def atomic_json(path: Path, value: dict):
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_setup(settings: Settings) -> tuple[dict, WorkflowConfig]:
    try:
        graph = parse_graph(json.loads((settings.data_dir / "workflow-api.json").read_text(encoding="utf-8")))
        mapping = WorkflowConfig.model_validate_json((settings.data_dir / "mapping.json").read_text(encoding="utf-8"))
        mapping.validate_graph(graph)
        return graph, mapping
    except (OSError, ValueError, ValidationError) as exc:
        raise HTTPException(409, "请先导入或拉取工作流 API JSON，并保存有效的参数映射") from exc


class AttachTask(BaseModel):
    task_id: str


class ResolveUnknown(BaseModel):
    confirmed_not_submitted: Literal[True]


def create_app(settings: Settings | None = None, client: RunningHub | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    store = Store(settings.data_dir / "jobs.sqlite3")
    rh = client or RunningHub(settings.api_key, settings.base_url)
    manager = JobManager(settings, store, rh)

    @asynccontextmanager
    async def lifespan(app):
        manager.recover()
        yield
        await manager.close()
        await rh.close()

    application = FastAPI(title="RunningHub Video Studio", lifespan=lifespan)
    application.state.store = store
    application.state.manager = manager
    application.mount("/static", StaticFiles(directory=STATIC, check_dir=False), name="static")

    @application.middleware("http")
    async def browser_identity(request: Request, call_next):
        cookie = request.cookies.get("video_client", "")
        valid = len(cookie) == 32 and all(char in "0123456789abcdef" for char in cookie)
        request.state.client_id = cookie if valid else uuid.uuid4().hex
        request.state.has_client_cookie = valid
        response = await call_next(request)
        if request.url.path in {"/", "/static/style.css", "/static/app.js", "/static/i18n.js"}:
            response.headers["Cache-Control"] = "no-cache"
        if not valid:
            response.set_cookie("video_client", request.state.client_id, max_age=31536000,
                                httponly=True, samesite="lax", secure=request.url.scheme == "https")
        return response

    @application.get("/api/system-settings")
    def get_system_settings():
        return store.system_settings()

    @application.put("/api/system-settings")
    async def save_system_settings(body: SystemSettings):
        value = store.save_system_settings(body)
        manager.dispatch()
        return value

    def client_state(request: Request):
        return {**store.client_status(request.state.client_id), "queue": store.queue_status(),
                "system_settings": store.system_settings().model_dump()}

    @application.get("/api/client-status")
    def get_client_status(request: Request):
        return client_state(request)

    def reject_cooldown(seconds: int):
        raise HTTPException(429, {"message": f"提交过于频繁，请等待 {seconds} 秒后再试", "retry_after": seconds},
                            headers={"Retry-After": str(seconds)})

    @application.get("/")
    def home():
        return FileResponse(STATIC / "index.html")

    @application.post("/api/resources/open-directory")
    def open_resource_directory(request: Request):
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "请从本机工作台页面打开目录")
        if not hasattr(os, "startfile"):
            raise HTTPException(501, "当前系统不支持打开本地目录")
        directory = (settings.data_dir / "videos").resolve()
        try:
            directory.mkdir(parents=True, exist_ok=True)
            os.startfile(str(directory))
        except OSError as exc:
            raise HTTPException(500, "无法打开生成资源目录，请检查系统权限") from exc
        return {"opened": True}

    @application.get("/api/config")
    def configuration():
        graph, mapping, error = None, None, None
        try:
            path = settings.data_dir / "workflow-api.json"
            if path.exists():
                graph = parse_graph(json.loads(path.read_text(encoding="utf-8")))
            path = settings.data_dir / "mapping.json"
            if path.exists():
                mapping = WorkflowConfig.model_validate_json(path.read_text(encoding="utf-8"))
                if graph:
                    mapping.validate_graph(graph)
        except (ValueError, OSError) as exc:
            mapping = None
            error = str(exc)[:300]
        nodes = []
        if graph:
            names = node_names(graph)
            for node_id, node in graph.items():
                fields = []
                for field_name, value in node["inputs"].items():
                    is_link = (isinstance(value, list) and len(value) == 2 and isinstance(value[0], str)
                               and value[0] in graph and isinstance(value[1], int))
                    if not is_link:
                        fields.append({"name": field_name, "type": type(value).__name__})
                nodes.append({"id": node_id, "name": names[node_id], "class_type": node["class_type"],
                              "fields": fields})
        return {"key_configured": bool(settings.api_key), "workflow_id": settings.workflow_id,
                "graph_loaded": graph is not None, "mapping_ready": graph is not None and mapping is not None,
                "mapping": mapping.model_dump(exclude_unset=True) if mapping else None,
                "nodes": nodes, "error": error, "max_image_bytes": settings.max_image_bytes}

    @application.post("/api/config/workflow/fetch")
    async def fetch_workflow():
        if not settings.api_key:
            raise HTTPException(503, "请在 .env 中配置 RUNNINGHUB_API_KEY 并重启服务")
        try:
            graph = await rh.get_workflow(settings.workflow_id)
        except (RunningHubError, ValueError) as exc:
            raise HTTPException(502, rh.safe_text(str(exc))) from exc
        atomic_json(settings.data_dir / "workflow-api.json", graph)
        return configuration()

    @application.post("/api/config/workflow/import")
    async def import_workflow(file: UploadFile = File(...)):
        content = await file.read(4 * 1024**2 + 1)
        await file.close()
        if len(content) > 4 * 1024**2:
            raise HTTPException(413, "工作流 JSON 不能超过 4MB")
        try:
            graph = parse_graph(json.loads(content.decode("utf-8-sig")))
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(422, "请导入有效的工作流 API JSON") from exc
        atomic_json(settings.data_dir / "workflow-api.json", graph)
        return configuration()

    @application.put("/api/config/mapping")
    def save_mapping(mapping: WorkflowConfig):
        try:
            graph = parse_graph(json.loads((settings.data_dir / "workflow-api.json").read_text(encoding="utf-8")))
            mapping.validate_graph(graph)
        except (OSError, ValueError) as exc:
            raise HTTPException(422, "映射无效：" + str(exc)[:300]) from exc
        atomic_json(settings.data_dir / "mapping.json", mapping.model_dump(exclude_unset=True))
        return configuration()

    @application.get("/api/jobs")
    def list_jobs():
        return store.list()

    @application.get("/api/jobs/history")
    def job_history(page: int = Query(1, ge=1), page_size: int = Query(12, ge=1, le=48),
                    status: Literal["all", "active", "succeeded", "attention"] = "all",
                    search: str = Query("", max_length=200),
                    sort: Literal["newest", "oldest", "active"] = "newest"):
        return store.history(page=page, page_size=page_size, status=status, search=search, sort=sort)

    @application.get("/api/events")
    async def all_job_events(request: Request):
        async def stream():
            last = None
            last_client = None
            heartbeat = 0
            while not await request.is_disconnected():
                encoded = json.dumps(store.list(), ensure_ascii=False)
                if encoded != last:
                    yield f"event: jobs\ndata: {encoded}\n\n"
                    last = encoded
                current_client = json.dumps(client_state(request), ensure_ascii=False)
                if current_client != last_client:
                    yield f"event: client\ndata: {current_client}\n\n"
                    last_client = current_client
                heartbeat += 1
                if heartbeat % 15 == 0:
                    yield ": keepalive\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    def required_job(job_id: str):
        job = store.get(job_id)
        if job is None:
            raise HTTPException(404, "任务不存在")
        return job

    @application.post("/api/jobs", status_code=202)
    async def submit_job(request: Request, prompt: str = Form(...), duration: int = Form(...),
                         images: list[UploadFile] = File(...)):
        if not settings.api_key:
            raise HTTPException(503, "请先配置 RUNNINGHUB_API_KEY")
        graph, mapping = load_setup(settings)
        try:
            mapping.validate_request(len(images), prompt, duration)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not request.state.has_client_cookie:
            raise HTTPException(428, "请先打开工作台或读取客户端状态，再提交生成任务")
        retry_after = store.client_status(request.state.client_id)["retry_after"]
        if retry_after:
            reject_cooldown(retry_after)
        upload_dir = settings.data_dir / "uploads" / uuid.uuid4().hex
        upload_dir.mkdir(parents=True)
        paths = []
        try:
            for index, upload in enumerate(images, 1):
                content = await upload.read(settings.max_image_bytes + 1)
                if not content or len(content) >= settings.max_image_bytes:
                    raise HTTPException(422, "每张参考图需小于 30MB，且不能为空")
                try:
                    with Image.open(io.BytesIO(content)) as image:
                        if image.width * image.height > 40_000_000:
                            raise HTTPException(422, "参考图像素数不能超过 4000 万")
                        extension = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}.get(image.format)
                        if not extension:
                            raise HTTPException(422, "仅支持 PNG、JPEG 和 WEBP 图片")
                        image.verify()
                except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
                    raise HTTPException(422, "文件不是有效的 PNG、JPEG 或 WEBP 图片") from exc
                path = upload_dir / f"{index:03d}{extension}"
                path.write_bytes(content)
                paths.append(str(path.resolve()))
            job = store.create(prompt=prompt.strip(), duration=duration, image_count=len(paths),
                client_id=request.state.client_id,
                private={"graph": graph, "mapping": mapping.model_dump(exclude_unset=True),
                         "workflow_id": settings.workflow_id, "image_paths": paths})
        except Exception as exc:
            for path in upload_dir.iterdir():
                path.unlink()
            upload_dir.rmdir()
            if isinstance(exc, CooldownError):
                reject_cooldown(exc.retry_after)
            raise
        finally:
            for upload in images:
                await upload.close()
        manager.start(job["id"])
        return store.public(store.get(job["id"]))

    @application.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        return store.public(required_job(job_id))

    @application.get("/api/jobs/{job_id}/events")
    async def job_events(job_id: str, request: Request):
        required_job(job_id)

        async def stream():
            last = None
            heartbeat = 0
            while not await request.is_disconnected():
                job = required_job(job_id)
                public = store.public(job)
                encoded = json.dumps(public, ensure_ascii=False)
                if encoded != last:
                    yield f"event: snapshot\ndata: {encoded}\n\n"
                    last = encoded
                if job["phase"] in TERMINAL_PHASES:
                    return
                heartbeat += 1
                if heartbeat % 15 == 0:
                    yield ": keepalive\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @application.get("/api/jobs/{job_id}/video")
    def serve_video(job_id: str, download: bool = False):
        job = required_job(job_id)
        path = Path(job["private"].get("video_path", ""))
        if not job.get("video_ready") or not path.is_file():
            raise HTTPException(404, "视频尚未保存完成")
        return FileResponse(path, filename=f"video-{job_id[:8]}{path.suffix}" if download else None,
                            content_disposition_type="attachment" if download else "inline")

    @application.post("/api/jobs/{job_id}/retry-download", status_code=202)
    async def retry_download(job_id: str):
        job = required_job(job_id)
        if job["phase"] != "download_failed" or not job["private"].get("result_url"):
            raise HTTPException(409, "只有下载失败的已生成视频可以重试下载")
        await manager.settle(job_id)
        if required_job(job_id)["phase"] != "download_failed":
            raise HTTPException(409, "下载已开始，请勿重复重试")
        updated = store.update(job_id, phase="downloading", error=None, slot_reserved=False, download_only=True)
        manager.start(job_id, reserve_slot=False)
        return store.public(updated)

    @application.post("/api/jobs/{job_id}/attach", status_code=202)
    async def attach_task(job_id: str, body: AttachTask):
        job = required_job(job_id)
        if job["phase"] != "submission_unknown":
            raise HTTPException(409, "只有提交结果未知的任务可以关联平台任务 ID")
        if not body.task_id.strip():
            raise HTTPException(422, "请输入 RunningHub 任务 ID")
        try:
            await rh.query(body.task_id.strip())
        except RunningHubError as exc:
            raise HTTPException(422, str(exc)) from exc
        if required_job(job_id)["phase"] != "submission_unknown":
            raise HTTPException(409, "任务已关联，请刷新后查看")
        await manager.settle(job_id)
        if required_job(job_id)["phase"] != "submission_unknown":
            raise HTTPException(409, "任务已关联，请刷新后查看")
        updated = store.update(job_id, phase="queued", remote_task_id=body.task_id.strip(), error=None)
        manager.start(job_id)
        return store.public(updated)

    @application.post("/api/jobs/{job_id}/resolve-unknown")
    async def resolve_unknown(job_id: str, body: ResolveUnknown):
        if required_job(job_id)["phase"] != "submission_unknown":
            raise HTTPException(409, "只有提交结果未知的任务可以核实解除")
        await manager.settle(job_id)
        if required_job(job_id)["phase"] != "submission_unknown":
            raise HTTPException(409, "任务状态已变化，请刷新后查看")
        updated = store.update(job_id, phase="interrupted", slot_reserved=False,
                               error=None, notice="已人工确认平台未创建任务，生成名额已释放")
        manager.dispatch()
        return store.public(updated)

    return application

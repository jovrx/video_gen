# RunningHub H3 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan inline, task-by-task. User already approved implementation; no new execution-choice question is needed.

**Goal:** 多参考图、提示词、时长输入，异步运行工作流，进度和本地视频输出。

**Architecture:** FastAPI HTTP/SSE，SQLite 持久化，RunningHub HTTP/WSS 适配器，显式工作流映射。单进程后台任务管理，重启恢复监控。

**Tech Stack:** Python >=3.11, FastAPI, httpx, websockets, SQLite, Pillow, 原生 JavaScript。

**Spec:** ../specs/2026-10-10-runninghub-h3-design.md

## Global Constraints

- Workflow ID `2108942308824670209`，KEY 稍后在本地环境配置。
- 工作流节点、数量和时长由真实 JSON 和显式映射确认，不能猜测。
- 不自动重提结果未知的收费请求；重启监控原 taskId。
- 单 worker，KEY 不进入浏览器或公共任务 JSON。

## Task 1: 工作流映射和真实进度

Files: `app/workflow.py`, `app/progress.py`, `tests/test_workflow.py`, `tests/test_progress.py`。
Interfaces: `WorkflowConfig.build_overrides(graph, files, prompt, duration) -> list[dict]`; `Progress.apply(event, prompt_id) -> bool`; `Progress.snapshot() -> dict`。

- [ ] 创建测试，独立断言图片顺序、空槽拒绝与清空、图数/时长校验、连线字段拒绝以及 WS 缓存、重复、跨任务和无百分比事件。
- [ ] 运行 `python -m pytest tests/test_workflow.py tests/test_progress.py -q`，确认缺少对应功能。
- [ ] 实现 Pydantic 映射模型、类型校验和纯事件解释器。
- [ ] 重跑同一组测试。

核心断言示例：
```python
assert overrides[0] == {"nodeId": "1", "fieldName": "image", "fieldValue": "openapi/a.png"}
assert progress.snapshot()["node_percent"] is None
```

## Task 2: 平台客户端和持久化

Files: `app/config.py`, `app/runninghub.py`, `app/store.py`, `tests/test_runninghub.py`, `tests/test_store.py`。
Interfaces: `RunningHub.get_workflow/upload/create/query/get_wss/download`; `Store.create/get/list/update/recoverable`。

- [ ] HTTP transport 边界测试使用官方完整响应形状；断言 V2 输出规范化、804 WSS、API 错误及不重试 create。
- [ ] SQLite 使用真实临时文件，验证重开后 taskId 保持字符串、公开信息无密钥/WSS、恢复只选择未结束任务。
- [ ] 运行 `python -m pytest tests/test_runninghub.py tests/test_store.py -q`。
- [ ] 实现 HTTP Bearer/body apiKey、上传 fileName、视频流下载、短暂网络错误表示以及 SQLite JSON 存储。
- [ ] 重跑对应测试。

HTTP 输出断言示例：
```python
assert result["status"] == "SUCCESS"
assert result["results"][0]["url"] == "https://example.test/final.mp4"
```

## Task 3: 后台生成和 Web API

Files: `app/jobs.py`, `app/main.py`, `tests/test_jobs.py`, `tests/test_api.py`。
Interfaces: `JobManager.start/recover/close`; `create_app(settings, client=None) -> FastAPI`。

- [ ] 写入外部 HTTP 替身与真实 SQLite/Pillow 联合测试：排队、运行、最终图片与视频混合结果、下载、重启原 taskId、提交超时只标记未知。
- [ ] 测试未配置 KEY 不能提交、无效图片拒绝、显式映射验证、任务 API 和视频预览路由。
- [ ] 运行 `python -m pytest tests/test_jobs.py tests/test_api.py -q`。
- [ ] 实现持久化阶段、并行 WSS/V2 监控、原 taskId 恢复、SSE 快照和下载重试，配置上传/拉取/保存。
- [ ] 重跑整个 `python -m pytest -q`。

## Task 4: 网页、启动和联调

Files: `app/static/index.html`, `app/static/app.js`, `app/static/style.css`, `README.md`, `start.ps1`。

- [ ] 网页多图排序/移除、时长输入、任务卡、节点进度、配置弹窗、视频预览下载和友好错误。
- [ ] `python -m compileall -q app`; `node --check app/static/app.js`; `python -m pytest -q`。
- [ ] 启动 localhost，浏览器验证无 KEY 状态、配置导入、表单校验和任务刷新。
- [ ] 文档说明工作流映射、环境变量、单 worker、未知提交恢复和真实生成尚需 KEY。

工作状态由 claude-mem `runninghub-h3` 跟踪；此文档记录静态实施步骤。

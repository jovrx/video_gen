# 技术与配置说明

返回项目介绍：[English](../README.md) | [简体中文](../README.zh-CN.md)

通过 RunningHub ComfyUI 工作流接收多张有序参考图、提示词和时长，异步生成并保存视频。

默认工作流：`2108942308824670209`。已认证获取真实节点定义，并适配 H3 和本地 Qwen 提示词增强节点的可变参考图输入。

## 启动

Python 3.11+。Windows PowerShell：

```powershell
.\start.ps1
```

启动脚本会创建 `.env`、虚拟环境并安装依赖。打开 http://127.0.0.1:8765 。更换端口使用 `./start.ps1 -Port 8766`。

也可手动启动：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8765 --workers 1
```

## 首次配置

1. 在本地 `.env` 填入 `RUNNINGHUB_API_KEY` 并重启服务。密钥不会发送到浏览器。
2. 点击网页右上角“工作流待配置”。点击“从 RunningHub 拉取”，或导入编辑器中“导出工作流 API”获得的 JSON。普通画布 JSON 不适用。
3. 从真实节点字段中选择提示词、秒数时长和图片输入；填写实际支持的图片数量及时间范围。保存时会校验节点、字段、类型和重复映射。
4. 上传参考图，调整顺序，填写提示词及秒数，点击生成。完成后可播放、下载。

生成记录旁的“打开生成资源目录”会在 Windows 文件资源管理器中打开本机 `data/videos`（跟随 `VIDEO_DATA_DIR` 配置），便于直接访问生成视频。

工作台采用紧凑创作栏和视频网格，支持按全部/进行中/已完成/需处理筛选、搜索提示词或任务 ID、按创建时间或进行中优先排序。历史记录在服务器分页，每页可选 12/24/48 条，能访问超过最近 100 条的旧记录。页面只挂载当前页卡片，可见区域附近才加载视频；刷新任务数据会保留未变更视频的播放状态。

布局以 PC 使用为主：鼠标操作的桌面浏览器保持左侧创建栏和右侧视频网格，队列概况位于标题旁；桌面窗口小于 960px 时保留工作区宽度，可横向滚动。触屏设备按窗口宽度采用上下排列。页面、样式和脚本会重新校验缓存，避免更新后混用旧版布局。

目标工作流已确认：提示词 `240.value`，秒数时长 `132.value`，图片加载 `150.image` 和 `164.image`。选择 **H3 可变参考图** 模式，按上传数量同步重建 `MiniMaxH3ReferenceToVideo` 和 `QwenH3PromptLocal` 的参考图连线，并通过官方 `workflow` 参数提交原工作流的适配副本。原始模板不被修改。

两个参考图节点的源码均限制最多 9 张图，本地设置为 1–9 张。秒数输入先按 24fps 转换并向上对齐模型帧数网格，实际成片可能略长于输入时长。本地首版时长设为 5–15 秒，依据节点源码标注的模型训练范围；这是本地使用范围，不是平台 API 的硬限制。

### 可变数量图片

支持四种输入方式：

- **图片槽位**：按图片顺序配置多个文件名字段。未使用槽位必须设置该节点真正支持的空值，例如可选节点支持的字符串 `"None"`。留空代表该槽位必填；少图提交会被拒绝。普通 `LoadImage` 不一定接受空值，不能盲目填 `null` 或 `"None"`。需要在工作流使用支持可选图片的节点，或改用批量节点。
- **图片列表**：映射一个字段，按工作流要求使用 JSON 数组或 JSON 文本。
- **ZIP 图片包**：本地将参考图按 `001.png`、`002.jpg` 等有序名称打包，上传后映射到支持 ZIP 的加载节点字段。
- **H3 可变参考图**：针对这个工作流，提供 1–9 张有序图片。自动为实际上传图创建加载节点，同时重建 Qwen 和 H3 的动态参考输入，移除不再使用的模板加载节点；单图不会带入第二张模板图片。需要原工作流包含这两种已确认的节点。

图片输入上限由配置决定。应用本地要求每张图片小于 30MiB、像素数不超过 4000 万，仅支持 PNG/JPEG/WEBP，并检查实际文件内容。

### 映射文件

网页配置存为 `data/workflow-api.json` 和 `data/mapping.json`。也可手动保存映射后重启或刷新。例如下面仅说明结构，节点编号不代表当前工作流：

```json
{
  "prompt": {"node_id": "20", "field_name": "prompt"},
  "duration": {"node_id": "20", "field_name": "duration"},
  "images": [
    {"node_id": "10", "field_name": "image"},
    {"node_id": "11", "field_name": "image", "empty_value": "None"}
  ],
  "image_mode": "slots",
  "min_images": 1,
  "max_images": 2,
  "min_duration": 5,
  "max_duration": 15
}
```

时长映射要求以秒为单位的字段；若原字段是字符串，则传入字符串秒数，否则传入数字。只有帧数输入的工作流需先在工作流提供秒数输入并完成换算。

## 进度与长任务

### 系统设置与提交队列

点击右上角 **系统设置**，可调整以下参数，保存到 SQLite 后立即生效，重启仍保留：

- **最大同时生成数**：默认 **3**，范围 1–100。名额从素材上传开始，占用至生成和视频保存结束；超额任务按提交顺序等待，显示从 1 开始的当前排队号，通过 SSE 每秒检查并更新。平台自身排队另显示为“平台排队中”。提高上限立即补位；降低上限不会停止已有任务，待占用低于新上限后再启动队首。
- **同一客户端提交间隔**：默认 **60 秒**，范围 0–86400 秒，0 表示关闭。以服务端设置的浏览器 Cookie 识别客户端，同一浏览器的多个标签页共用等待时间，刷新和服务重启后仍有效。输入校验失败不消耗间隔；后端原子检查并限制并发提交，返回 429 和 `Retry-After`，页面显示倒计时。间隔到期允许提交下一条，即使上一条还在生成。

浏览器身份用于防止正常重复提交；不同浏览器、隐私窗口或清除 Cookie 会视为新客户端。通过 API 提交时先调用 `GET /api/client-status` 并保留响应 Cookie；没有身份 Cookie 的提交返回 428，避免首次并发请求绕过间隔。

等待任务及素材保留在本机；服务启动时先恢复已有平台任务，再按原顺序启动等待任务。提交结果未知的任务暂时保留名额，防止平台实际已经开始生成时重复释放名额。请在平台找到任务后“关联任务 ID”；确实没有创建任务时，点击“核实未提交并释放名额”。

服务使用新版 `/openapi/v2/query` 查询排队、运行、成功和失败，通过平台返回的 WebSocket 地址获取节点事件，再用 SSE 推送网页。节点未上报百分比时显示当前状态与已等待时间，不伪造总进度或 ETA。

排队后获取 WebSocket 地址依赖官方示例中的旧 `/task/openapi/outputs`，该接口已标记弃用；不可用或断线时继续用 V2 查询原任务。部分 H3 节点等待外部模型时没有连续进度。

关闭网页不停止服务的后台生成。服务重启后从 SQLite 恢复原 RunningHub taskId，不重新提交收费任务。若服务在提交期间中断、请求超时或提交响应不明确，则标记“待核实提交”；在 RunningHub 任务列表找到对应 ID，再在网页关联 ID。

生成结果中的最后一个视频文件会保存到 `data/videos`，中间图片不会被选为视频。如工作流输出多个不同视频，请先将工作流的最终输出整理为单个视频。下载失败可单独重试下载，不会再次生成，也不重新占用生成名额。视频可否在浏览器播放取决于输出格式与编码，通常建议工作流输出 H.264 MP4。

首版面向本机使用，运行一个服务进程及一个 worker；不支持多个 worker 同时监控同一 SQLite 数据库。默认绑定 localhost。Webhook 和平台取消任务暂未加入首版界面。

## 环境变量

| 变量 | 默认值 |
| --- | --- |
| `RUNNINGHUB_API_KEY` | 空；配置后重启 |
| `RUNNINGHUB_WORKFLOW_ID` | `2108942308824670209` |
| `RUNNINGHUB_BASE_URL` | `https://www.runninghub.cn` |
| `VIDEO_DATA_DIR` | `./data` |
| `VIDEO_POLL_SECONDS` | `5`，环境配置最小 1 秒 |

`data` 和 `.env` 均已加入 `.gitignore`。输入素材与生成视频会保留在本机，按需要自行备份或清理已结束任务的文件。

## API

| 接口 | 用途 |
| --- | --- |
| `GET /api/config` | 查询 KEY 和映射配置状态、节点字段（不返回密钥） |
| `POST /api/config/workflow/fetch` | 认证拉取当前工作流 |
| `POST /api/config/workflow/import` | multipart `file` 导入 API JSON |
| `PUT /api/config/mapping` | 保存并验证映射 |
| `POST /api/jobs` | multipart `images` 多个文件、`prompt`、整数 `duration`；返回 202 |
| `GET /api/jobs` | 最近 100 个任务及全部未完成任务 |
| `GET /api/jobs/history` | 全库分页：`page`、`page_size`（1–48）、`status`、`search`、`sort`；返回当前页与全库任务统计 |
| `POST /api/resources/open-directory` | 在 Windows 文件资源管理器中打开本机生成视频目录 |
| `GET /api/jobs/{id}` | 任务状态 |
| `GET /api/system-settings` | 读取系统并发与客户端间隔设置 |
| `PUT /api/system-settings` | JSON `max_concurrent_generations`、`client_cooldown_seconds`；保存并即时生效 |
| `GET /api/client-status` | 建立浏览器身份、读取剩余等待秒数、队列概况与系统设置 |
| `GET /api/events` | 近期及全部未完成任务共用的 SSE，事件 `jobs` 更新任务与排队号，`client` 更新倒计时及队列概况 |
| `GET /api/jobs/{id}/events` | SSE，事件类型 `snapshot` |
| `GET /api/jobs/{id}/video` | 本地视频，支持 HTTP Range |
| `GET /api/jobs/{id}/video?download=true` | 下载视频 |
| `POST /api/jobs/{id}/retry-download` | 只重试下载 |
| `POST /api/jobs/{id}/attach` | JSON `{"task_id":"RunningHub任务ID"}`，恢复未知提交 |
| `POST /api/jobs/{id}/resolve-unknown` | JSON `{"confirmed_not_submitted":true}`；人工确认未创建远程任务后释放名额 |

OpenAPI 页面：http://127.0.0.1:8765/docs 。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests
node --check app/static/app.js
```

测试使用临时 SQLite、真实图片和模拟 RunningHub HTTP/WSS，避免真实计费。API 能力与文档来源见 [调研记录](runninghub-api-research.md)。

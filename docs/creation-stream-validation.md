# 剧本与分镜实时生成验证（2026-10-12）

页面改用独立流式入口 `/api/creation/script/stream` 和 `/api/creation/storyboard/stream`。上游 `chat/completions` 发送 `stream: true`，SSE 内容增量解析为结构化预览；页面实时更新剧本、标题和各镜字段。首次输出前显示等待状态，生成中显示镜头数量。最终结果校验通过后才保存并允许编辑、复制和填入视频表单。

预览只发送变化字段，最多约每 75ms 刷新一次，避免每个 token 重发整批分镜。下游保留 UTF-8 中文，避免合法长分镜因 Unicode 转义膨胀超过浏览器消息上限。原 JSON API 保留。

分镜区增加灰色承托背景，卡片交替淡紫/淡绿底色，独立标题栏、4px 左边框、26px 桌面间距；触屏间距 22px。截图：`.playwright-mcp/creation-stream-separated.png`、`creation-stream-shot-1.png`、`creation-stream-shot-2.png`。

结果：155 项完整 Python 回归通过，另新增的 2 项实际 HTTP 流式验证通过；3 个浏览器流程、5 项语言测试、Ruff/JS 语法/diff 检查通过。8765 服务已重启加载流式接口，并在该地址重跑流式浏览器验收通过。全部改动留在 `feat/script-storyboard` 工作区，未提交。

## 验证范围

- Python 流式测试：上游完成前收到首段内容；跨传输块 UTF-8 和 CRLF；不完整 JSON 的字段预览；代码围栏和转义对白；截断/断流/超时；安全错误且不自动重试；最终数量/序号/时长/H3 格式校验；只发送变更分镜；24 镜最大合法中文字段。
- 实际本机 HTTP 测试：模型尚未完成时，Uvicorn 的真实 TCP 响应已向客户端发送预览；浏览器断开后关闭上游流。仅替换外部文本服务，使用随机隔离端口和临时数据，无真实收费请求。
- 浏览器流式测试：响应未结束时出现分镜字段及剧本；预览不写入草稿；最终保存；失败/缺失终止事件恢复原草稿；双语；文本安全；卡片底色/标题栏/边框/间隔断言。
- 原创作浏览器流程：编辑、复制、填入、时长、不完整返回、草稿恢复、配置重试、中英切换、1440/1024 PC 和 390 触屏。
- 原双语浏览器流程、语言单元测试、Python 完整回归、Ruff、JS 语法、diff 空白检查。

独立代码复核发现大中文 SSE 帧膨胀问题，补入失败测试后修正，再次复核无未修复 Critical/Important。

## 运行

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests
node --test tests/i18n.test.cjs
node --check app/static/creation-stream.js
node --check app/static/creation.js
node tests/browser_creation_stream.cjs
node tests/browser_creation.cjs
node tests/browser_i18n.cjs
```

浏览器测试的 `PLAYWRIGHT_MODULE`、`CHROMIUM_PATH` 和 `STUDIO_URL` 根据本机安装设置。浏览器测试不会调用真实文本服务或视频生成服务。文本服务商本身需支持流式协议；本次没有额外发起收费生成。

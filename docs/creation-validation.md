# 剧本与分镜模块验证记录

日期：2026-10-12。实现位于 `feat/script-storyboard`，未提交、未推送。

## 结果

- 完整 Python 测试：125 passed，包含原有 74 项及新增 51 项创作接口/客户端测试。
- JavaScript 语言测试：5 passed；修改脚本语法检查、Ruff、git diff --check 通过。
- `tests/browser_creation.cjs` 与原有 `tests/browser_i18n.cjs` 均通过，使用 Chromium 和隔离服务 `127.0.0.1:8770` 的当前真实页面资源；浏览器测试中的 API 结果为模拟响应。
- 浏览器覆盖剧本生成与修改、三种目标格式、指定数量/时长/风格、分镜编辑、锁定生成中的依赖输入、失败保留结果、复制成功与失败、刷新恢复、损坏/不可用存储、配置重试、语言切换、Prompt 字数更新、时长兼容提示及不会自动提交视频。
- 检查 1440/1024 桌面与 390 触屏布局；创建弹窗没有内容横向溢出。模型提供的 HTML 样式文字仅作为文本展示。
- `/` 与 `/static/creation.js` 在新服务中返回 200 和 `Cache-Control: no-cache`。

## 接口验证方式

后端使用真实 FastAPI 路由、Pydantic 校验、TextModel 和 httpx，仅通过 MockTransport 替代外部文本服务。验证请求的 API 根地址、认证头、文本模型名和用户实际编辑后的剧本，未依赖真实 RunningHub 配置。

覆盖认证、限流、连接、超时、无效上游响应、截断、错误分镜数量/序号/时长、空字段、超长 Prompt、H3 格式、非法端口及深度嵌套 JSON。错误不返回上游原始响应或 API Key，不自动重试付费生成。

独立后端复核发现并修正三项问题：非法端口被误判为已配置、深度 JSON 引发未处理异常、空 H3 核心段通过校验。补充回归先复现失败，再通过修正验证；独立定向复核的 9 项测试通过。

最终独立整体复核通过，未发现可复现的待修复缺陷；复核者再次运行了 125 项 Python 测试、创作浏览器验收、5 项语言测试及 Ruff/diff 检查。功能代码保留在当前分支供用户查看和使用。

## 真实环境与限制

没有提供文本服务的有效 Key 和模型名，未执行真实服务商调用。`.env` 已补入缺少的 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`、`LLM_TIMEOUT_SECONDS` 占位配置，没有修改已有 RunningHub Key。配置文本服务后需重启应用再联调真实生成。

现有 `127.0.0.1:8765` 服务的队列检查为 active/waiting/unknown 全部 0，但自动审批拒绝了重启该服务的命令，仅返回 `blocked by policy`；命令未执行，现有服务仍在运行旧后端。用户需手动停止并重新运行 `./start.ps1`，才能在原地址使用新增后端接口。

pytest 报告 1 项现有 Starlette/AnyIO 弃用提示，不影响测试结果。Git 报告部分文件的 LF/CRLF 自动转换提示，diff 空白检查通过。

## 重现命令

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests
node --test tests/i18n.test.cjs
node --check app/static/creation.js
node --check app/static/i18n.js
node --check app/static/app.js
git diff --check

# Playwright 安装位置及 Chromium 路径按本机环境填写。
$env:STUDIO_URL='http://127.0.0.1:8770'
node tests/browser_creation.cjs
node tests/browser_i18n.cjs
```

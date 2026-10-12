# RunningHub MINIMAX H3 工作流 API 调研

调研日期：2026-10-10。目标工作流：`2108942308824670209`。

工作流地址：https://www.runninghub.cn/workflow/2108942308824670209?source=workspace

## 结论和证据边界

RunningHub 支持通过 API 上传参考图、覆盖已有工作流的节点输入、异步提交任务、查询状态和获取生成视频。官方提供 WebSocket 进度示例，支持当前节点、缓存节点及节点内进度事件。

本次已读取官方 API 文档及其 Markdown/OpenAPI 导出。没有 API Key，未提交收费任务，也未完成真实视频生成验证。目标工作流网页在未登录时显示登录入口及“Token已过期”，未能读取节点定义。因此该工作流的图片输入节点、提示词节点、时长节点、输出节点及输入限制尚未确认，不能填写猜测的节点编号。

以上是初次无 KEY 调研的证据边界。2026-10-11 认证联调的新增证据见文末。

## 接入接口

域名：`https://www.runninghub.cn`。

请求头按接口文档使用 `Authorization: Bearer <API_KEY>`。工作流相关接口还要求 JSON 请求体中的 `apiKey`；上传接口使用 multipart，不要自行设置 multipart boundary。

| 用途 | 方法和路径 | 请求关键字段 | 响应关键字段 |
| --- | --- | --- | --- |
| 获取工作流 API JSON | POST `/api/openapi/getJsonApiFormat` | `apiKey`, `workflowId` | `code`, `data.prompt`（JSON 字符串） |
| 上传参考图 | POST `/openapi/v2/media/upload/binary` | multipart `file` | `code`, `data.fileName`, `data.download_url` |
| 提交工作流 | POST `/task/openapi/create` | `apiKey`, `workflowId`, `nodeInfoList` | `code`, `data.taskId`, `data.taskStatus`, `data.netWssUrl`, `data.promptTips` |
| 查询状态和结果，推荐 | POST `/openapi/v2/query` | `taskId` | `status`, `results[].url`, `results[].outputType`, `errorCode`, `errorMessage` |
| 获取运行中 WSS，兼容接口 | POST `/task/openapi/outputs` | `apiKey`, `taskId` | 运行中：`code=804`, `data.netWssUrl` |
| 取消工作流任务 | POST `/task/openapi/cancel` | `apiKey`, `taskId` | `code`, `msg` |

旧版 `/task/openapi/status`、`/task/openapi/outputs` 已标记 `deprecated: true`；新版 `/openapi/v2/query` 未弃用。新版查询文档没有列出 `netWssUrl`、总百分比、当前节点或排队名次，不能假设它会返回这些字段。

### 图片上传

上传接口支持 JPG、JPEG、PNG、WEBP，以及 ZIP 图片包。ComfyUI 加载节点应使用返回的 `fileName`，标准模型接口使用 `download_url`。二者不能互换，不能把 `fileName` 随意拼接成外链。

官方标明上传文件的 URL 有效期为一天；这项说明针对上传资源，不代表生成视频的链接也具有相同有效期。

### 工作流参数替换

```json
{
  "apiKey": "<API_KEY>",
  "workflowId": "2108942308824670209",
  "nodeInfoList": [
    {
      "nodeId": "<从目标工作流读取的节点ID>",
      "fieldName": "<该节点 inputs 中的字段名>",
      "fieldValue": "<替换后的输入>"
    }
  ]
}
```

以上是结构示例，尖括号字段必须由目标工作流确定，不能直接执行。只覆盖需要变更的字段；保持连线和无关配置。数值等字段按真实节点类型传入，并验证服务端接受的编码，文档的自然语言说明与部分 schema 的字符串类型存在差异。

`workflowId`、`taskId` 始终按字符串保存，避免 JavaScript 对长整型 ID 的精度损失。

`promptTips` 可能包含 ComfyUI 节点校验错误，创建任务时应检查；不要仅凭 HTTP 200 判定成功。

### 状态和结果

新版查询的请求仅需 `taskId`（API Key 放请求头），示例状态包括 `QUEUED`、`RUNNING`、`SUCCESS`、`FAILED`。

```json
{
  "taskId": "<TASK_ID>"
}
```

成功时从 `results` 中按 `outputType` 选择视频结果，不能把工作流产生的中间图片误当最终视频。输出节点的选择规则需要目标工作流确认。结果就绪后保存视频到本地，提供预览和下载。

任务创建支持 `webhookUrl`。官方完成回调示例为 `event: "TASK_END"`、`taskId` 和 JSON 字符串 `eventData`；它是结束通知，不能用作连续进度来源。公网服务可加回调，本地开发可先使用轮询。

## 进度能力

官方《任务进度显示示例》使用任务响应中的 `netWssUrl` 建立 WebSocket，按节点映射显示名称。地址由平台返回，应直接使用，不自行拼接实例地址或认证参数，也不暴露到浏览器和普通日志。

| WebSocket 事件 | 示例字段 | 可展示的内容 |
| --- | --- | --- |
| `executing` | `data.node` | 当前执行节点 |
| `progress` | `data.node`, `data.value`, `data.max` | 当前节点进度，`value / max` |
| `execution_cached` | `data.nodes` | 使用缓存的节点 |
| `execution_success` | 执行完成事件 | 随后查询最终结果 |

官方完整示例按 `class_type` 映射节点名；实际产品可优先使用 JSON 的 `_meta.title`，其次使用 `class_type`，最后显示节点 ID。

### 排队与 WebSocket 地址

1. 提交时若返回 `netWssUrl`，立即连接。
2. 排队时创建响应的 `netWssUrl` 可为 null。
3. 官方进度示例轮询旧 `/task/openapi/outputs`，运行中响应 `code=804` 返回 `data.netWssUrl`；排队为 `code=813`，失败示例为 `code=805`。
4. 同时用新版 `/openapi/v2/query` 查询状态和结果。WSS 连接失败或旧接口不可用时，保留查询能力，显示“生成中，详细进度暂不可用”。
5. 不因暂时断线或长时间没有事件自动重新提交任务；继续跟踪原 `taskId`。

兼容旧接口是否仍可为该工作流返回 WSS，必须在认证实测中确认。这是目前文档中明确提供的排队后获取 WSS 的路径，不能将其描述为长期稳定的新接口保证。

### 进度含义

- 节点进度仅在对应节点上报 `progress` 时可用。H3 若在单个节点等待远端生成，可能只有“当前正在生成视频”的状态，没有连续百分比。
- 官方示例的总百分比按已完成节点数除以工作流节点总数计算，是节点计数进度，不是耗时比例。视频生成节点可能占据绝大部分执行时间。
- 分支、未执行节点、缓存和重连都会影响节点计数。建议显示“当前节点 + 节点内进度（有事件时）+ 已运行时间”，将节点计数标为参考值，不用于预测剩余时间。
- 前端最终完成状态以查询到成功且视频结果可用为准。收到 WSS 成功事件时可以先显示“获取生成结果”。
- 重连后不能还原未收到的中间事件，应保留已观察到的进度，未知信息显示为未知。

## 不定数量参考图和时长

“不定数量”应为模型和工作流支持范围内的可变数量，不是无限张数。

官方另一个标准模型接口 `/openapi/v2/minimax/hailuo-h3/multimodal-to-video` 支持 `imageUrls` 数组，最多 9 张，每张小于 30 MB；`duration` 是字符串枚举 `"5"` 至 `"15"`。官方 `MiniMax H3 ref2va RH插件流 支持多参` 也描述最多 9 张图，时长为 5–15 秒整数。另一个 RH Enhanced 变体则描述 4–15 秒，说明 H3 不同变体限制可能不同。

这些接口不能证明目标工作流具有同样的限制，也不能把它们的节点编号复制到目标工作流。用户指定接入工作流，本方案继续使用该工作流 API；标准模型 API 仅作为可比较的替代方案。

读取目标工作流后需要确认：

1. 图片采用固定槽位、ZIP 批量加载还是列表输入；图片顺序与提示词中的“参考图1”等引用如何对应。
2. 少量图片时，未使用槽位如何禁用、清空或从执行图移除。只省略覆盖参数会保留模板默认图片，可能导致错误参考。
3. 提示词传入哪个节点，是否经过自动增强，以及增强模型与其他默认配置。
4. 时长字段是秒数、帧数还是组合参数，支持哪些值。
5. 最终视频输出节点、视频格式和默认分辨率。

获取上述信息可使用认证后的 `getJsonApiFormat`；也可在工作流编辑器选择“导出工作流 API”，将 API 格式 JSON 放入项目。普通画布 JSON 的节点/连线格式与 API 格式不同。

## 建议的首版系统（待确认）

采用 Python FastAPI + SQLite + 简单网页。Python 便于对接 ComfyUI 和 WebSocket，SQLite 持久化任务，首版无需引入独立队列服务。

浏览器提交参考图、提示词和时长后，服务器创建本地任务并返回任务 ID；后台上传图片、映射工作流参数、提交 RunningHub 任务。服务器通过 RunningHub WSS 接收进度，通过 SSE 发送给网页，同时每隔约 5 秒用新版查询确认状态和结果。网页支持刷新后恢复跟踪、视频预览和下载。

SQLite 保存本地任务 ID、RunningHub taskId、阶段、已观察到的节点进度、结果和错误；服务重启恢复已有 taskId 的查询，避免重复创建收费任务。创建请求超时且不知道是否被接受时，标记为“提交结果未知”，不能盲目重试。

API Key 仅由服务器配置读取。工作流映射是明确的配置，启动时根据真实 API JSON 验证；不能用通用关键词自动猜测并直接提交。

拟验证：不同图片数量和顺序、默认图片不泄漏到少图任务、时长与提示词准确映射、长整型 ID、排队后获取 WSS、无节点百分比、缓存事件、WSS 断线与查询兜底、服务重启恢复、失败节点显示，以及最终视频输出选择。最后用认证后的目标工作流进行一次完整生成，确认真实进度粒度。

与其他方案比较：直接调用标准模型 API 输入数组更简单，但不保证执行用户指定的工作流；引入 Redis/Celery 适合后续多实例和高并发，目前没有相关需求。

## 官方来源

- [文档中心](https://www.runninghub.cn/runninghub-api-doc-cn/)
- [发起 ComfyUI 任务（高级）](https://www.runninghub.cn/runninghub-api-doc-cn/api-425749013)
- [获取工作流 JSON](https://www.runninghub.cn/runninghub-api-doc-cn/api-425749014)
- [关于 nodeInfoList](https://www.runninghub.cn/runninghub-api-doc-cn/doc-8287336)
- [文件上传](https://www.runninghub.cn/runninghub-api-doc-cn/api-425749007)
- [查询任务生成结果 V2](https://www.runninghub.cn/runninghub-api-doc-cn/api-425767306)
- [旧查询任务生成结果（含运行中 WSS 响应）](https://www.runninghub.cn/runninghub-api-doc-cn/api-425749004)
- [任务进度显示示例](https://www.runninghub.cn/runninghub-api-doc-cn/doc-8287341)
- [工作流完整接入示例](https://www.runninghub.cn/runninghub-api-doc-cn/doc-8287342)
- [取消 ComfyUI 任务](https://www.runninghub.cn/runninghub-api-doc-cn/api-425749015)
- [MiniMax-H3 多模态参考生视频](https://www.runninghub.cn/runninghub-api-doc-cn/api-495380672)
- [MiniMax H3 ref2va RH 插件流](https://www.runninghub.cn/runninghub-api-doc-cn/api-502119461)
- [Minimax H3 RH Enhanced Multi-Reference](https://www.runninghub.cn/runninghub-api-doc-cn/api-520877434)

## 2026-10-11 认证联调补充

KEY 配置后已通过 `getJsonApiFormat` 获取目标工作流的 25 个节点。入口为 `240.value`（提示词）与 `132.value`（秒数）；`150`、`164` 为标准 `LoadImage`，同时连接到 `136` 的 `ref_images.ref_image_*` 和 `238` 的 `reference_images.reference_image_*`。输出 `180` 为 `VHS_VideoCombine`，使用 H.264 MP4、24fps，包含生成音频。

仅覆盖现有图片字段会固定为两张，且普通 `LoadImage` 没有已确认的空值语义。官方高级创建接口另支持字符串字段 `workflow`，传入完整工作流 JSON 后忽略 `workflowId`。应用据此提交从目标模板复制的 API 图，按实际图数同时调整两个消费者的 Autogrow 输入，并移除未被使用的模板加载节点。

源码依据：[ComfyUI H3 节点](https://github.com/comfyanonymous/ComfyUI/blob/master/comfy_extras/nodes_minimax_h3.py) 的 `MiniMaxH3ReferenceToVideo`，以及 [Qwen H3 Prompt](https://github.com/chflame163/ComfyUI_Qwen_H3_Prompt/blob/main/node.py) 的 `QwenH3PromptLocal`，两者参考图输入均 `max=9`。H3 节点注明训练帧数约 124–362；本地选用 5–15 秒范围。模板按 24fps 与 `17k+5` 帧数网格向上对齐，5 秒请求对应 124 帧，实际约 5.17 秒。

单图、5 秒真实任务 `2108965528990351361` 已完成，平台接受完整工作流。WebSocket 报告模型加载、参考图、Qwen 提示词增强、H3 采样和 VAE 解码；采样节点连续上报百分比，实际观察到 11.1% 至 88.9%。视频成功保存并通过浏览器播放、下载和 Range 验证，详见 `validation.md`。

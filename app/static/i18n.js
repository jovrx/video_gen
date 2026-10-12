"use strict";

// Chinese source phrases are stable message keys, including messages from older job records.
const I18n = (() => {
  const messages = {
    "正在等待模型输出…": "Waiting for the model…",
    "正在生成剧本，内容实时更新…": "Writing your script live…",
    "正在生成分镜 {count} / {total}，内容实时更新…": "Generating shot {count} / {total} live…",
    "生成完成，可编辑并使用。": "Complete. Ready to edit and use.",
    "生成中": "Generating",
    "文本模型流式输出中断，请重试；原草稿已保留": "The stream was interrupted. Retry; your original draft is preserved.",
    "文本模型服务未返回流式响应，请检查模型是否支持流式输出": "The text service did not return a stream. Check that the model supports streaming.",
    "服务未返回流式响应，请重启服务后重试。": "The service did not return a stream. Restart it and try again.",
    "剧本与分镜": "Script & Storyboard",
    "关闭创作弹窗": "Close creation dialog",
    "清空创作草稿": "Clear Draft",
    "1 · 创作剧本": "1 · Create a Script",
    "创意与故事要求": "Idea & Story Requirements",
    "描述故事、角色与受众…": "Describe your story, characters, and audience…",
    "生成剧本": "Generate Script",
    "剧本标题": "Script Title",
    "可编辑剧本": "Editable Script",
    "生成剧本，或粘贴已有剧本…": "Generate a script or paste your own…",
    "草稿保存在当前浏览器，可关闭弹窗后继续。": "Drafts are saved in this browser. Close the dialog and continue later.",
    "2 · 生成分镜": "2 · Create a Storyboard",
    "分镜数量": "Shot Count",
    "每镜时长（秒）": "Seconds per Shot",
    "目标 Prompt 格式": "Target Prompt Format",
    "通用": "Generic",
    "自定义": "Custom",
    "自定义模型与格式要求": "Custom Model & Format Requirements",
    "视觉风格（可选）": "Visual Style (Optional)",
    "写实电影、动画、广告…": "Cinematic realism, animation, advertising…",
    "格式决定 Prompt 写法；实际视频模型由工作流决定。": "The format shapes each Prompt. Your workflow determines the actual video model.",
    "生成分镜": "Generate Storyboard",
    "剧本已更改；现有分镜尚未更新，请重新生成。": "The script changed. Regenerate to update the existing storyboard.",
    "分镜会显示在这里，每镜都可编辑并用于视频生成。": "Your editable shots will appear here. Use each Prompt to create a video.",
    "无法恢复创作草稿；你仍可继续编辑。浏览器存储可能不可用或草稿已损坏。": "Could not restore the creation draft. You can still edit. Browser storage may be unavailable or the draft may be corrupt.",
    "浏览器无法保存草稿；仍可编辑和生成，但刷新后可能丢失内容。": "The browser cannot save your draft. Editing and generation still work, but refreshing may lose your changes.",
    "正在生成…": "Generating…",
    "正在读取文本模型配置…": "Loading text model configuration…",
    "文本模型已连接": "Text model connected",
    "请在 .env 中配置 LLM_API_KEY 和 LLM_MODEL 并重启服务；仍可手动编辑剧本及使用已保存的分镜。": "Set LLM_API_KEY and LLM_MODEL in .env and restart the service. You can still edit scripts manually and use saved shots.",
    "镜头标题": "Shot Title",
    "时长（秒）": "Duration (Seconds)",
    "画面与动作": "Visuals & Action",
    "景别与运镜": "Framing & Camera Movement",
    "对白与声音": "Dialogue & Sound",
    "分镜 Prompt": "Shot Prompt",
    "复制 Prompt": "Copy Prompt",
    "用于视频生成": "Use for Video",
    "镜头 {number}": "Shot {number}",
    "Prompt 已复制": "Prompt copied",
    "无法访问剪贴板，请手动选择并复制 Prompt。": "Clipboard is unavailable. Select and copy the Prompt manually.",
    "Prompt 必须为 1–{max} 字符，请编辑后再使用。": "Prompt must contain 1–{max} characters. Edit it before using it.",
    "Prompt 已填入视频表单，请确认参考图后生成视频。": "Prompt added to the video form. Confirm your reference images before generating.",
    "Prompt 已填入；当前工作流不支持此分镜时长或尚未配置，请手动确认视频时长。": "Prompt added. The workflow does not support this shot duration or is not configured. Check the video duration manually.",
    "创意输入必须为 1–20000 字符。": "The idea must contain 1–20000 characters.",
    "剧本必须为 1–40000 字符。": "The script must contain 1–40000 characters.",
    "分镜数量必须是 1–24 的整数。": "Shot count must be an integer from 1 to 24.",
    "H3 每镜时长必须是 4–15 的整数。": "H3 shot duration must be an integer from 4 to 15.",
    "分镜时长必须是 1–120 的整数。": "Shot duration must be an integer from 1 to 120.",
    "请填写自定义模型名称与格式要求。": "Enter the custom model name and format requirements.",
    "文本模型返回了无效内容，请重试": "The text model returned invalid content. Try again.",
    "请在 .env 中配置有效的 LLM_BASE_URL、LLM_API_KEY 和 LLM_MODEL，并重启服务": "Set a valid LLM_BASE_URL, LLM_API_KEY, and LLM_MODEL in .env, then restart the service.",
    "文本模型认证失败，请检查 LLM_API_KEY 和模型访问权限": "Text model authentication failed. Check LLM_API_KEY and model access permissions.",
    "文本模型请求受限，请稍后再试": "The text model is rate limited. Try again later.",
    "文本模型服务暂不可用，请检查服务地址和模型名": "The text model service is unavailable. Check the service URL and model name.",
    "文本模型返回内容过长，请减少分镜数量或缩短剧本": "The text model response is too long. Request fewer shots or shorten the script.",
    "文本模型请求超时，请稍后重试或减少生成内容": "The text model request timed out. Try again later or request less content.",
    "无法连接文本模型服务，请检查服务地址和网络": "Could not connect to the text model service. Check the service URL and network.",
    "文本模型输出未完成，请减少生成内容或调整输入后重试": "The text model output is incomplete. Request less content or adjust your input and retry.",
    "文本模型未返回有效 JSON，请重试或更换文本模型": "The text model did not return valid JSON. Retry or choose another text model.",
    "文本模型返回字段不完整或超出范围，请重试或更换文本模型": "The text model returned missing or out-of-range fields. Retry or choose another text model.",
    "文本模型返回的分镜数量、序号或时长不符合要求，请重试": "The returned shot count, numbering, or duration does not match your request. Try again.",
    "文本模型未返回完整的 H3 Prompt 格式，请重试": "The text model did not return the complete H3 Prompt format. Try again.",
    "请选择自定义目标模型并填写格式要求": "Select a custom target model and enter its format requirements.",
    "H3 分镜时长需为 4–15 秒": "H3 shot duration must be 4–15 seconds.",
    "清空剧本与全部分镜草稿？此操作无法撤销。": "Clear the script and all storyboard drafts? This cannot be undone.",
    "H3 视频工作台": "H3 Video Studio",
    "H3 视频工作台首页": "H3 Video Studio home",
    "视频工作台": "Video Studio",
    "⚙ 系统设置": "⚙ System Settings",
    "读取配置中": "Loading configuration",
    "视频生成": "Video Generation",
    "工作台": "Workspace",
    "持续创作，集中查看任务进度与生成视频。": "Keep creating. Track progress and manage your videos in one place.",
    "正在读取生成队列…": "Loading generation queue…",
    "连接工作流 ↗": "Workflow Setup ↗",
    "创建视频": "Create Video",
    "参考图": "Reference Images",
    "0 张": "0 images",
    "点击添加，或将图片拖到这里": "Click to add or drag images here",
    "PNG / JPG / WEBP · 每张小于 30MB": "PNG / JPG / WEBP · Under 30MB each",
    "添加参考图": "Add reference images",
    "图片顺序对应「参考图1、参考图2…」，可调整顺序。": "Images correspond to Reference 1, Reference 2, etc. You can reorder them.",
    "提示词": "Prompt",
    "描述参考图中的主体、动作、镜头和声音…": "Describe the subjects, actions, camera movement, and sound…",
    "视频时长": "Duration",
    "连接工作流后，按实际支持范围选择。": "Connect a workflow to see the supported range.",
    "秒": "s",
    "生成视频": "Generate Video",
    "先连接工作流，即可开始创作": "Connect a workflow to start creating",
    "提交后按系统设置等待，再创建下一条；已有任务在后台运行。": "Wait for the submission interval before creating another task. Existing tasks run in the background.",
    "生成记录": "Video Library",
    "打开生成资源目录": "Open Video Folder",
    "刷新生成记录": "Refresh video library",
    "任务统计": "Task statistics",
    "全部任务": "All Tasks",
    "进行中": "In Progress",
    "已完成": "Completed",
    "需处理": "Needs Attention",
    "筛选任务": "Filter tasks",
    "全部": "All",
    "搜索提示词或任务 ID": "Search prompts or task IDs",
    "任务排序": "Sort tasks",
    "最新创建": "Newest First",
    "进行中优先": "Active First",
    "最早创建": "Oldest First",
    "正在读取任务…": "Loading tasks…",
    "每页": "Per page",
    "每页任务数": "Tasks per page",
    "条": "tasks",
    "创建你的第一段视频": "Create your first video",
    "提交任务后，在这里查看进度与生成结果。": "Submit a task to see its progress and video here.",
    "任务分页": "Task pagination",
    "← 上一页": "← Previous",
    "下一页 →": "Next →",
    "参考图 → 提示词 → 视频": "Reference Images → Prompt → Video",
    "查看 RunningHub 工作流 ↗": "View RunningHub Workflow ↗",
    "系统设置": "System Settings",
    "关闭系统设置": "Close system settings",
    "控制全系统的视频生成数量和客户端提交间隔，保存后立即生效。": "Set generation limits and submission intervals for the whole system. Changes take effect when saved.",
    "最大同时生成数": "Maximum Concurrent Generations",
    "默认 3 个。超出的任务按提交顺序排队，排队号自动更新。降低上限后，已有任务继续运行。": "Default: 3. Additional tasks queue in submission order, with positions updated automatically. Existing tasks continue if you lower the limit.",
    "同一客户端提交间隔（秒）": "Submission Interval per Client (seconds)",
    "默认 60 秒，0 表示关闭间隔限制。同一浏览器的多个标签页共用等待时间，刷新仍有效。": "Default: 60 seconds. Set to 0 to disable the interval. Tabs in the same browser share the countdown, which persists after refresh.",
    "保存系统设置": "Save System Settings",
    "连接工作流": "Workflow Setup",
    "关闭配置": "Close workflow setup",
    "首次连接时，确认工作流的输入位置。配置会保存在本机。": "Confirm the workflow input fields on first setup. Configuration is saved locally.",
    "在项目 .env 中设置 RUNNINGHUB_API_KEY，保存后重启服务。": "Set RUNNINGHUB_API_KEY in the project's .env file, then restart the service.",
    "1. 读取工作流": "1. Load Workflow",
    "从 RunningHub 拉取": "Fetch from RunningHub",
    "导入 API JSON": "Import API JSON",
    "尚未读取节点": "No nodes loaded",
    "2. 对应输入参数": "2. Map Input Fields",
    "选项来自工作流的真实节点；请按节点用途选择。": "Select fields from the workflow's actual nodes according to their purpose.",
    "提示词字段": "Prompt Field",
    "时长字段（秒）": "Duration Field (seconds)",
    "图片输入方式": "Image Input Mode",
    "逐张图片槽位": "Individual Image Slots",
    "图片列表": "Image List",
    "ZIP 图片包": "ZIP Image Archive",
    "H3 可变参考图": "H3 Dynamic References",
    "列表传入格式": "List Encoding",
    "JSON 数组": "JSON Array",
    "JSON 文本": "JSON Text",
    "图片输入（按参考图顺序）": "Image Inputs (reference order)",
    "＋ 添加槽位": "＋ Add Slot",
    "可选槽位请填写工作流支持的空值（JSON，例如 \"None\"）。留空则必须上传该槽位的图片，避免带入模板默认图。": "For optional slots, enter a supported empty value as JSON (e.g. \"None\"). Otherwise an image is required for that slot to avoid using the template's default image.",
    "按上传数量同步提供给提示词增强和视频生成节点，支持 1–9 张有序参考图。": "Provide the uploaded images to both prompt enhancement and video generation nodes. Supports 1–9 ordered references.",
    "最少参考图": "Minimum Images",
    "最多参考图": "Maximum Images",
    "最短时长（秒）": "Minimum Duration (seconds)",
    "最长时长（秒）": "Maximum Duration (seconds)",
    "数量和时长请按当前工作流支持范围填写。": "Use image counts and durations supported by the current workflow.",
    "保存并验证映射": "Save and Validate Mapping",
    "任务详情": "Task Details",
    "关闭任务详情": "Close task details",
    "语言": "Language",
    "等待处理": "Pending",
    "等待生成名额": "Waiting for a Slot",
    "上传素材": "Uploading Assets",
    "提交生成": "Submitting",
    "平台排队中": "Platform Queue",
    "生成中": "Generating",
    "获取结果": "Fetching Results",
    "保存视频": "Saving Video",
    "生成失败": "Generation Failed",
    "待核实提交": "Verify Submission",
    "下载失败": "Download Failed",
    "已中断": "Interrupted",
    "服务未返回有效响应，请确认服务仍在运行。": "The service returned an invalid response. Check that it is still running.",
    "请求失败": "Request failed",
    "正在提交…": "Submitting…",
    "请等待 {seconds} 秒": "Wait {seconds}s",
    "提交成功后需等待，还剩 {seconds} 秒可再次提交": "You can submit again in {seconds} seconds",
    "正在读取客户端提交状态…": "Loading client submission status…",
    "生成任务在后台运行，名额已满时自动排队": "Tasks run in the background and queue when all slots are occupied",
    "生成名额：{active} / {limit} · 等待队列：{waiting} 个": "Generation slots: {active} / {limit} · Waiting: {waiting}",
    " · {unknown} 个提交待核实，暂时保留名额": " · {unknown} submissions to verify; slots reserved",
    "工作流已连接": "Workflow Connected",
    "工作流待配置": "Workflow Setup",
    "先在本地配置 API Key，再连接你的 H3 工作流。": "Configure your API key locally, then connect your H3 workflow.",
    "API Key 已配置，请读取工作流并确认参数映射。": "API key configured. Load the workflow and confirm the input mapping.",
    "当前工作流：{min}–{max} 秒": "Workflow range: {min}–{max}s",
    "，实际成片可能略长": "; the final video may be slightly longer",
    "仅支持 PNG、JPEG 和 WEBP 图片。": "Only PNG, JPEG, and WEBP images are supported.",
    "{name} 需要小于 30MB。": "{name} must be under 30MB.",
    "当前配置最多接受 {max} 张参考图。": "The current configuration accepts up to {max} reference images.",
    "{count} 张": "{count} images",
    "参考图{index}：{name}": "Reference {index}: {name}",
    "参考图{index}向前移动": "Move reference {index} earlier",
    "移除参考图{index}": "Remove reference {index}",
    "参考图{index}向后移动": "Move reference {index} later",
    "移除": "Remove",
    "等待生成名额 · 当前排队第 {position} 位": "Waiting for a slot · Queue position {position}",
    "等待平台开始执行": "Waiting for the platform to start",
    "生成的视频": "Generated video",
    "视频 · {id}": "Video · {id}",
    "点击详情查看完整提示词": "Open details to view the full prompt",
    "{count} 张图": "{count} images",
    "{seconds} 秒": "{seconds}s",
    "无需重复提交，轮到后自动开始；排队号实时更新": "Starts automatically when a slot is available. Queue positions update live.",
    "已观察到 {count} 个节点完成 ·": "{count} nodes observed complete ·",
    "执行已结束，正在获取结果": "Execution finished; fetching results",
    "当前节点上报的进度": "Progress reported by the current node",
    "持续查询中，有节点进度时自动显示": "Checking status; node progress appears when available",
    "查看详情 ↗": "View Details ↗",
    "↓ 下载": "↓ Download",
    "重试下载": "Retry Download",
    "关联任务 ID": "Link Task ID",
    "核实未提交并释放名额": "Confirm Not Submitted and Release Slot",
    "没有符合条件的任务": "No matching tasks",
    "试试其他关键词，或切换状态筛选。": "Try another keyword or status filter.",
    "{seconds}秒": "{seconds}s",
    "{minutes}分{seconds}秒": "{minutes}m {seconds}s",
    "{hours}小时{minutes}分": "{hours}h {minutes}m",
    "耗时": "Duration",
    "已等待": "Elapsed",
    "共 {total} 条符合条件的任务": "{total} matching tasks",
    "共 {total} 条生成记录": "{total} generation records",
    "显示 {start}–{end} / {total} 条": "Showing {start}–{end} of {total}",
    "请选择真实的工作流节点字段。": "Select an actual workflow node field.",
    "请选择节点字段": "Select a node field",
    "图片输入字段": "Image input field",
    "空值 JSON（可留空）": "Empty value JSON (optional)",
    "未使用图片槽位的空值": "Empty value for an unused image slot",
    "移除图片槽位": "Remove image slot",
    "● API Key 已配置（密钥仅保存在服务端）": "● API key configured (stored only on the server)",
    "○ API Key 尚未配置": "○ API key not configured",
    "工作流 ID：{id}": "Workflow ID: {id}",
    "已读取 {count} 个节点。": "Loaded {count} nodes.",
    " 原映射需重新确认。": " Confirm the previous mapping again.",
    "尚未读取节点；导入时请选择『导出工作流 API』格式。": "No nodes loaded. Import the Export Workflow API format.",
    "任务已接收，当前排队第 {position} 位，轮到后自动生成。": "Task accepted at queue position {position}. Generation starts automatically.",
    "任务已提交，下一次提交时间见倒计时。": "Task submitted. See the countdown for your next submission.",
    "任务已提交，记录暂时未刷新，请稍后刷新查看。": "Task submitted. Refresh the library shortly to see it.",
    "已打开生成资源目录": "Video folder opened",
    "{count} 张参考图 · {seconds} 秒": "{count} reference images · {seconds}s",
    "任务 ID": "Task ID",
    "请先在 RunningHub 任务列表确认此次提交，然后填入对应的任务 ID：": "Verify this submission in your RunningHub task list, then enter its task ID:",
    "请先在 RunningHub 任务列表核实：确实没有创建此任务？确认后将释放生成名额；若任务存在，请关联任务 ID。": "Check your RunningHub task list first. Confirm that this task was never created to release the slot. If it exists, link its task ID instead.",
    "工作流节点已读取，请确认参数映射。": "Workflow nodes loaded. Confirm the input mapping.",
    "工作流已导入。": "Workflow imported.",
    "空值需为合法 JSON，例如 \"None\"（含引号）或 null。": "Enter valid JSON for the empty value, e.g. \"None\" (with quotes) or null.",
    "映射已验证并保存。": "Mapping validated and saved.",
    "系统设置已保存并生效。": "System settings saved and applied.",
    "连接服务失败": "Unable to connect to the service",
    "素材上传 {current}/{total}": "Uploading assets {current}/{total}",
    "状态查询暂时失败，正在重连；不会重新提交生成": "Status check failed. Reconnecting without resubmitting generation.",
    "工作流已结束，等待视频结果": "Workflow finished; waiting for video results",
    "生成中，详细节点进度暂不可用": "Generating; detailed node progress is temporarily unavailable",
    "实时进度连接中断，仍在查询生成状态": "Live progress disconnected; still checking generation status",
    "已人工确认平台未创建任务，生成名额已释放": "Confirmed that no platform task was created. Generation slot released.",
    "服务在提交时中断，结果未知。请从 RunningHub 任务列表核实并关联任务 ID。": "The service stopped during submission. Verify the result in RunningHub and link the task ID.",
    "任务处理出现异常，请检查本地配置和工作流": "Task processing failed. Check the local configuration and workflow.",
    "视频已生成，下载失败。可仅重试下载。": "Video generated, but download failed. Retry the download only.",
    "工作流已结束但未返回输出；请检查 RunningHub 任务详情": "Workflow finished without outputs. Check the RunningHub task details.",
    "工作流成功但没有视频输出，请检查视频保存节点": "Workflow succeeded without video outputs. Check the video save node.",
    "视频格式不受支持": "Unsupported video format",
    "尚未配置 RUNNINGHUB_API_KEY": "RUNNINGHUB_API_KEY is not configured",
    "平台提交响应异常；请到 RunningHub 任务列表核实，系统不会自动重提": "Unexpected submission response. Verify in RunningHub; the system will not resubmit automatically.",
    "提交结果未知；请到 RunningHub 核实，系统不会自动重提": "Submission result unknown. Verify in RunningHub; the system will not resubmit automatically.",
    "RunningHub 暂时无法连接或返回了无效响应": "RunningHub is unavailable or returned an invalid response",
    "RunningHub 请求失败（HTTP {status}）": "RunningHub request failed (HTTP {status})",
    "平台拒绝请求": "Platform rejected the request",
    "RunningHub 响应缺少数据": "RunningHub response is missing data",
    "上传响应没有 fileName": "Upload response is missing fileName",
    "图片上传失败，请检查网络和 RunningHub 服务": "Image upload failed. Check the network and RunningHub service.",
    "提交响应缺少状态，结果未知，请到 RunningHub 核实": "Submission response is missing its status. Verify the result in RunningHub.",
    "提交响应没有 taskId，请到 RunningHub 核实": "Submission response is missing taskId. Verify in RunningHub.",
    "平台未返回可识别的任务状态": "Platform returned an unrecognized task status",
    "详细进度接口暂不可用，继续查询任务状态": "Detailed progress is unavailable; continuing to check task status",
    "视频结果地址无效": "Invalid video result URL",
    "视频文件超过本地 2GB 保存上限": "Video exceeds the local 2GB storage limit",
    "平台返回了空视频文件": "Platform returned an empty video file",
    "视频下载失败，可重试下载，无需重新生成": "Video download failed. Retry the download without generating again.",
    "工作流节点校验异常，请查看 RunningHub 任务详情和节点映射": "Workflow node validation failed. Check the RunningHub task details and node mapping.",
    "RunningHub 生成失败": "RunningHub generation failed",
    "（节点 {node}）": "(node {node})",
    "请先导入或拉取工作流 API JSON，并保存有效的参数映射": "Import or fetch the workflow API JSON and save a valid input mapping first",
    "提交过于频繁，请等待 {seconds} 秒后再试": "Submitting too frequently. Wait {seconds} seconds and try again.",
    "请从本机工作台页面打开目录": "Open the folder from the local studio page",
    "当前系统不支持打开本地目录": "Opening a local folder is not supported on this system",
    "无法打开生成资源目录，请检查系统权限": "Unable to open the video folder. Check system permissions.",
    "请在 .env 中配置 RUNNINGHUB_API_KEY 并重启服务": "Configure RUNNINGHUB_API_KEY in .env and restart the service",
    "工作流 JSON 不能超过 4MB": "Workflow JSON must not exceed 4MB",
    "请导入有效的工作流 API JSON": "Import a valid workflow API JSON file",
    "映射无效：": "Invalid mapping: ",
    "任务不存在": "Task not found",
    "请先配置 RUNNINGHUB_API_KEY": "Configure RUNNINGHUB_API_KEY first",
    "请先打开工作台或读取客户端状态，再提交生成任务": "Open the studio or load client status before submitting a generation task",
    "每张参考图需小于 30MB，且不能为空": "Each reference image must be nonempty and under 30MB",
    "参考图像素数不能超过 4000 万": "Reference images must not exceed 40 million pixels",
    "仅支持 PNG、JPEG 和 WEBP 图片": "Only PNG, JPEG, and WEBP images are supported",
    "文件不是有效的 PNG、JPEG 或 WEBP 图片": "File is not a valid PNG, JPEG, or WEBP image",
    "视频尚未保存完成": "Video has not finished saving",
    "只有下载失败的已生成视频可以重试下载": "Only generated videos with failed downloads can be retried",
    "下载已开始，请勿重复重试": "Download already started. Do not retry again.",
    "只有提交结果未知的任务可以关联平台任务 ID": "Only tasks with unknown submission results can be linked to a platform task ID",
    "请输入 RunningHub 任务 ID": "Enter a RunningHub task ID",
    "任务已关联，请刷新后查看": "Task already linked. Refresh to view it.",
    "只有提交结果未知的任务可以核实解除": "Only tasks with unknown submission results can be verified and released",
    "任务状态已变化，请刷新后查看": "Task status changed. Refresh to view it.",
    "工作流不是有效的 API JSON": "Workflow is not valid API JSON",
    "请导入『导出工作流 API』格式的 JSON": "Import JSON in Export Workflow API format",
    "节点 {id} 不符合工作流 API 格式": "Node {id} does not match the workflow API format",
    "节点 {id} 的元信息格式无效": "Invalid metadata format for node {id}",
    "最小值不能大于最大值": "Minimum values must not exceed maximum values",
    "数组或 ZIP 模式需要恰好一个图片输入映射": "Array or ZIP mode requires exactly one image input mapping",
    "最小图数不能超过图片槽位数": "Minimum image count must not exceed the number of image slots",
    "H3 参考图节点最多支持 9 张图片": "H3 reference nodes support up to 9 images",
    "节点字段映射重复": "Duplicate node field mapping",
    "节点字段不存在：{field}": "Node field does not exist: {field}",
    "不能覆盖连线字段：{field}": "Cannot override a connected field: {field}",
    "提示词映射需要文本字段": "Prompt mapping requires a text field",
    "时长映射需要秒数文本或数值字段": "Duration mapping requires a text or numeric field in seconds",
    "图片数组编码与工作流字段类型不一致": "Image array encoding does not match the workflow field type",
    "图片槽位或 ZIP 映射需要文件名文本字段": "Image slot or ZIP mapping requires a filename text field",
    "H3 图片映射需与两个节点的 LoadImage 参考图来源一致": "H3 image mapping must match the LoadImage reference source of both nodes",
    "H3 动态图片模式需要一个 {type} 节点": "H3 dynamic image mode requires a {type} node",
    "H3 动态图片模式需要已确认的 LoadImage 参考图连线": "H3 dynamic image mode requires confirmed LoadImage reference connections",
    "参考图数量需为 {min}–{max} 张": "Reference image count must be {min}–{max}",
    "提示词不能为空，且不能超过 20000 字符": "Prompt must be nonempty and must not exceed 20000 characters",
    "时长需为 {min}–{max} 秒整数": "Duration must be an integer between {min} and {max} seconds",
    "未使用图片槽位 {id} 需要配置明确的空值": "Unused image slot {id} requires an explicit empty value",
    "H3 动态图片模式需要提交完整工作流": "H3 dynamic image mode requires submitting the full workflow",
    "ZIP 上传或时长参数无效": "Invalid ZIP upload or duration parameters",
    "完整工作流构建仅用于 H3 动态图片模式": "Full workflow construction is only supported in H3 dynamic image mode"
};
  const storageKey = "h3-studio-language";
  const supported = new Set(["en", "zh-CN"]);
  let language = "en";
  try {
    const saved = localStorage.getItem(storageKey);
    if (supported.has(saved)) language = saved;
  } catch { /* Language selection still works when browser storage is disabled. */ }
  document.documentElement.lang = language;

  function interpolate(text, values) {
    return text.replace(/\{(\w+)\}/g, (match, name) => Object.hasOwn(values, name) ? String(values[name]) : match);
  }

  function t(key, values = {}) {
    let template = language === "en" ? messages[key] ?? key : key;
    if (language === "en" && Number(values.count ?? values.total) === 1) template = singular(template);
    return interpolate(template, values);
  }

  function singular(template) {
    return template.replace(/\b(images|nodes|tasks|records)\b/g, word => word.slice(0,-1));
  }

  // Translate only application messages, never user prompts, file names, or workflow node names.
  function messagePattern(source, target) {
    const names = [];
    const escaped = source.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const pattern = escaped.replace(/\\\{(\w+)\\\}/g, (_, name) => {
      names.push(name);
      return source.endsWith(`{${name}}`) ? "(.+)" : "(.+?)";
    });
    return {source, target, names, exact:new RegExp(`^${pattern}$`), regex:new RegExp(pattern,"g")};
  }
  const patterns = Object.entries(messages).map(([key, english]) => messagePattern(key,english))
    .sort((a,b) => b.source.length-a.source.length);
  const reversePatterns = Object.entries(messages).flatMap(([key, english]) => {
    const forms = [messagePattern(english,key)];
    if (/\{(count|total)\}/.test(key) && singular(english) !== english) forms.push(messagePattern(singular(english),key));
    return forms;
  });
  let groupIndex = 1;
  const fragments = patterns.map(pattern => {
    const fragment = {...pattern,groupIndex};
    groupIndex += 1 + pattern.names.length;
    return fragment;
  });
  const fragmentRegex = new RegExp(fragments.map(({regex}) => `(${regex.source})`).join("|"),"g");

  function message(value) {
    const original = String(value ?? "");
    if (language !== "en") {
      for (const {target,names,exact} of reversePatterns) {
        const match = original.match(exact);
        if (match) return interpolate(target,Object.fromEntries(names.map((name,index) => [name,match[index+1]])));
      }
      return original;
    }
    if (reversePatterns.some(({exact}) => exact.test(original))) return original;
    if (Object.hasOwn(messages,original)) return messages[original];
    for (const {target,names,exact} of patterns) {
      const match = original.match(exact);
      if (match) return interpolate(target,Object.fromEntries(names.map((name,index) => [name,match[index+1]])));
    }
    // One replacement pass prevents interpolated user values from being translated again.
    return original.replace(fragmentRegex, (...args) => {
      const fragment = fragments.find(item => args[item.groupIndex] !== undefined);
      return interpolate(fragment.target,Object.fromEntries(fragment.names.map((name,index) => [name,args[fragment.groupIndex+index+1]])));
    });
  }

  function apply(root = document) {
    document.documentElement.lang = language;
    root.querySelectorAll("[data-i18n]").forEach(element => { element.textContent = t(element.dataset.i18n); });
    for (const attribute of ["aria-label", "title", "placeholder"]) {
      root.querySelectorAll(`[data-i18n-${attribute}]`).forEach(element => {
        element.setAttribute(attribute,t(element.getAttribute(`data-i18n-${attribute}`)));
      });
    }
    const select = document.querySelector("#language-select");
    if (select) select.value = language;
  }

  function setLanguage(value) {
    language = supported.has(value) ? value : "en";
    try { localStorage.setItem(storageKey,language); } catch { /* Continue without persistence. */ }
    window.dispatchEvent(new Event("languagechange"));
  }

  return {get language() { return language; },t,message,apply,setLanguage};
})();

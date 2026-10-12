"use strict";

const {t} = I18n;
const $ = (selector) => document.querySelector(selector);
const terminal = new Set(["succeeded", "failed", "submission_unknown", "download_failed", "interrupted"]);
const phaseKeys = {created:"等待处理", waiting:"等待生成名额", uploading:"上传素材", submitting:"提交生成", queued:"平台排队中", running:"生成中", fetching:"获取结果", downloading:"保存视频", succeeded:"已完成", failed:"生成失败", submission_unknown:"待核实提交", download_failed:"下载失败", interrupted:"已中断"};
let configuration = null;
let detailsJobId = null;
let clientStatus = null;
let cooldownDeadline = 0;
let images = [];
let filter = "all";
let submitting = false;
let toastTimer;
const jobs = new Map();
let eventStream = null;
let page = 1;
let pageSize = 12;
let total = 0;
let pageIds = [];
let loadRequest = 0;
let searchTimer;
let liveRefreshTimer;
let liveMembership = "";
const videoObserver = new IntersectionObserver(entries => {
  entries.forEach(({target, isIntersecting}) => {
    if (!isIntersecting) return;
    target.preload = "metadata";
    target.src = target.dataset.src;
    videoObserver.unobserve(target);
  });
}, {rootMargin:"200px"});

function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[char]));
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  let data;
  try { data = await response.json(); } catch { throw new Error(t("服务未返回有效响应，请确认服务仍在运行。")); }
  if (!response.ok) {
    const detail = data.detail;
    const message = Array.isArray(detail) ? detail.map(item => item.msg).join("; ") : typeof detail === "object" ? detail?.message || "请求失败" : detail || "请求失败";
    const error = new Error(I18n.message(message));
    error.originalMessage = message;
    error.retryAfter = Number(detail?.retry_after || response.headers.get("Retry-After") || 0);
    throw error;
  }
  return data;
}

function showError(id, message) {
  const element = $(id);
  element.dataset.message = message;
  element.textContent = I18n.message(message);
  element.hidden = !message;
}

function toast(message) {
  clearTimeout(toastTimer);
  $("#toast").dataset.message = message;
  $("#toast").textContent = I18n.message(message);
  $("#toast").hidden = false;
  toastTimer = setTimeout(() => { $("#toast").hidden = true; }, 3500);
}

function updateSubmit() {
  const ready = configuration?.key_configured && configuration?.mapping_ready;
  const remaining = Math.max(0, Math.ceil((cooldownDeadline - Date.now()) / 1000));
  $("#generate-button").disabled = !ready || !clientStatus || submitting || remaining > 0 || !images.length || !$("#prompt").value.trim();
  $("#generate-button").innerHTML = submitting ? t("正在提交…") : remaining > 0 ? t("请等待 {seconds} 秒", {seconds:remaining}) : `<span>✦</span> ${t("生成视频")} <span class="button-arrow">↗</span>`;
  $("#submit-hint").textContent = !ready ? t("先连接工作流，即可开始创作") : !clientStatus ? t("正在读取客户端提交状态…") : remaining > 0 ? t("提交成功后需等待，还剩 {seconds} 秒可再次提交", {seconds:remaining}) : t("生成任务在后台运行，名额已满时自动排队");
}

function applyClientStatus(state) {
  clientStatus = state;
  cooldownDeadline = Date.now() + Math.max(0, state.next_submit_at - state.server_time) * 1000;
  renderQueue();
  updateSubmit();
}

function renderQueue() {
  if (!clientStatus) return;
  const queue = clientStatus.queue;
  $("#queue-overview").textContent = t("生成名额：{active} / {limit} · 等待队列：{waiting} 个", {active:queue.active,limit:queue.limit,waiting:queue.waiting}) + (queue.unknown ? t(" · {unknown} 个提交待核实，暂时保留名额", {unknown:queue.unknown}) : "");
}

async function refreshClientStatus() { applyClientStatus(await api("/api/client-status")); }

function applyConfig(config) {
  configuration = config;
  const ready = config.key_configured && config.mapping_ready;
  $("#open-settings").classList.toggle("ready", ready);
  $("#connection-label").textContent = ready ? t("工作流已连接") : t("工作流待配置");
  $("#setup-banner").hidden = ready;
  $("#setup-message").textContent = !config.key_configured ? t("先在本地配置 API Key，再连接你的 H3 工作流。") : t("API Key 已配置，请读取工作流并确认参数映射。");
  $("#workflow-link").href = `https://www.runninghub.cn/workflow/${encodeURIComponent(config.workflow_id)}?source=workspace`;
  if (config.mapping) {
    const mapping = config.mapping;
    $("#duration").min = mapping.min_duration;
    $("#duration").max = mapping.max_duration;
    $("#duration").value = Math.max(mapping.min_duration, Math.min(mapping.max_duration, Number($("#duration").value)));
    $("#duration-help").textContent = t("当前工作流：{min}–{max} 秒", {min:mapping.min_duration,max:mapping.max_duration}) + (mapping.image_mode === "h3_dynamic" ? t("，实际成片可能略长") : "");
  }
  updateSubmit();
}

function addImages(files) {
  showError("#form-error", "");
  const max = configuration?.mapping ? (configuration.mapping.image_mode && configuration.mapping.image_mode !== "slots" ? configuration.mapping.max_images : Math.min(configuration.mapping.max_images || 9, configuration.mapping.images.length)) : 100;
  for (const file of files) {
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) { showError("#form-error", t("仅支持 PNG、JPEG 和 WEBP 图片。")); continue; }
    if (file.size >= (configuration?.max_image_bytes || 30 * 1024 ** 2)) { showError("#form-error", t("{name} 需要小于 30MB。", {name:file.name})); continue; }
    if (images.length >= max) { showError("#form-error", t("当前配置最多接受 {max} 张参考图。", {max})); break; }
    images.push({file, url:URL.createObjectURL(file)});
  }
  renderImages();
}

function renderImages() {
  $("#image-count").textContent = t("{count} 张", {count:images.length});
  $("#image-list").innerHTML = images.map((item, index) => `<div class="image-item"><img src="${escapeHTML(item.url)}" alt="${escapeHTML(t("参考图{index}：{name}", {index:index+1,name:item.file.name}))}"><span class="image-number">${index+1}</span><div class="image-controls"><button type="button" data-image-action="left" data-index="${index}" ${index===0?"disabled":""} aria-label="${escapeHTML(t("参考图{index}向前移动", {index:index+1}))}">←</button><button type="button" data-image-action="remove" data-index="${index}" aria-label="${escapeHTML(t("移除参考图{index}", {index:index+1}))}">${t("移除")}</button><button type="button" data-image-action="right" data-index="${index}" ${index===images.length-1?"disabled":""} aria-label="${escapeHTML(t("参考图{index}向后移动", {index:index+1}))}">→</button></div></div>`).join("");
  updateSubmit();
}

function watchJobs() {
  if (eventStream) return;
  eventStream = new EventSource("/api/events");
  eventStream.addEventListener("client", event => {
    try { applyClientStatus(JSON.parse(event.data)); } catch { /* Reconnect or next snapshot restores state. */ }
  });
  eventStream.addEventListener("jobs", event => {
    try {
      const states = JSON.parse(event.data);
      states.forEach(state => {
        const previous = jobs.get(state.id);
        if (previous && state.updated_at >= previous.updated_at) jobs.set(state.id, state);
      });
      renderJobs();
      const membership = states.map(state => `${state.id}:${state.phase}`).sort().join("|");
      if (membership !== liveMembership) {
        liveMembership = membership;
        clearTimeout(liveRefreshTimer);
        liveRefreshTimer = setTimeout(() => loadJobs().catch(() => {}), 500);
      }
    } catch { /* Keep the native SSE reconnect active for transient invalid data. */ }
  });
}

function jobHTML(job) {
  const progress = job.progress || {};
  const active = !terminal.has(job.phase);
  const percentage = typeof progress.node_percent === "number" ? progress.node_percent : null;
  const nodeLabel = job.phase === "waiting" ? t("等待生成名额 · 当前排队第 {position} 位", {position:job.queue_position || "…"}) : progress.node_name || (job.phase === "queued" ? t("等待平台开始执行") : t(phaseKeys[job.phase] || job.phase));
  const knownProgress = percentage !== null && job.phase === "running";
  return `<div class="job-media">${job.video_ready?`<video class="job-video" data-src="/api/jobs/${encodeURIComponent(job.id)}/video" controls preload="none" playsinline aria-label="${t("生成的视频")}"></video>`:`<div class="job-placeholder ${active?"is-active":""}"><span class="placeholder-icon" aria-hidden="true">${active?"✦":"◇"}</span><span>${escapeHTML(active?nodeLabel:t(phaseKeys[job.phase] || job.phase))}</span>${knownProgress?`<strong>${percentage}%</strong>`:""}</div>`}<span class="badge ${escapeHTML(job.phase)}">${escapeHTML(t(phaseKeys[job.phase] || job.phase) || job.phase)}</span></div>
    <div class="job-body"><div class="job-top"><div class="job-title">${escapeHTML(t("视频 · {id}", {id:job.id.slice(0,8)}))}</div><div class="job-date">${new Date(job.created_at*1000).toLocaleString(I18n.language === "en" ? "en-US" : "zh-CN",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"})}</div></div>
    <p class="job-prompt" title="${t("点击详情查看完整提示词")}">${escapeHTML(job.prompt)}</p><div class="job-meta"><span>${t("{count} 张图", {count:job.image_count})}</span><span>${t("{seconds} 秒", {seconds:job.duration})}</span><span class="elapsed" data-start="${job.created_at}" data-end="${active?"":job.updated_at}"></span></div>
    ${active?`<div class="progress-panel"><div class="progress-label"><span>${escapeHTML(nodeLabel)}</span><span>${knownProgress?`${percentage}%`:""}</span></div>${knownProgress?`<div class="progress-track"><div class="progress-fill" style="width:${Math.max(0,Math.min(100,percentage))}%"></div></div>`:""}<div class="progress-note">${job.phase === "waiting" ? t("无需重复提交，轮到后自动开始；排队号实时更新") : `${progress.completed_nodes?.length?t("已观察到 {count} 个节点完成 ·", {count:progress.completed_nodes.length}) + " ":""}${progress.execution_finished?t("执行已结束，正在获取结果"):knownProgress?t("当前节点上报的进度"):t("持续查询中，有节点进度时自动显示")}`}</div></div>`:""}
    ${job.notice?`<div class="job-notice">${escapeHTML(I18n.message(job.notice))}</div>`:""}
    ${job.error?`<div class="job-error">${escapeHTML(I18n.message(job.error))}</div>`:""}
    <div class="job-actions"><button class="text-button" data-job-action="details" data-job-id="${job.id}">${t("查看详情 ↗")}</button>
    ${job.video_ready?`<a class="secondary-button" href="/api/jobs/${encodeURIComponent(job.id)}/video?download=true">${t("↓ 下载")}</a>`:""}
    ${job.phase==="download_failed"?`<button class="secondary-button" data-job-action="retry-download" data-job-id="${job.id}">${t("重试下载")}</button>`:""}
    ${job.phase==="submission_unknown"?`<button class="secondary-button" data-job-action="attach" data-job-id="${job.id}">${t("关联任务 ID")}</button><button class="text-button" data-job-action="resolve-unknown" data-job-id="${job.id}">${t("核实未提交并释放名额")}</button>`:""}</div></div>`;
}

function renderJobs() {
  const container = $("#jobs-container");
  const ordered = pageIds.map(id => jobs.get(id)).filter(Boolean);
  const wanted = new Set(ordered.map(job => `job-${job.id}`));
  [...container.children].forEach(card => {
    if (wanted.has(card.id)) return;
    card.querySelectorAll("video").forEach(video => { videoObserver.unobserve(video); video.pause(); });
    card.remove();
  });
  for (const job of ordered) {
    let card = document.getElementById(`job-${job.id}`);
    if (!card) { card = document.createElement("article"); card.id = `job-${job.id}`; card.className = "job-card"; container.append(card); }
    const signature = I18n.language + JSON.stringify(job);
    if (card.dataset.signature !== signature) {
      const video = card.querySelector("video");
      card.querySelectorAll("video").forEach(video => videoObserver.unobserve(video));
      card.innerHTML = jobHTML(job); card.dataset.signature = signature;
      if (video && job.video_ready) {
        video.setAttribute("aria-label", t("生成的视频"));
        card.querySelector("video").replaceWith(video);
      }
      card.querySelectorAll("video[data-src]:not([src])").forEach(video => videoObserver.observe(video));
    }
    // Moving an existing card is unnecessary and would interrupt video playback.
  }
  // New tasks belong at the front; existing video elements retain their state.
  ordered.forEach((job,index) => { const card = document.getElementById(`job-${job.id}`); if (container.children[index] !== card) container.insertBefore(card,container.children[index] || null); });
  $("#empty-state").hidden = ordered.length > 0;
  const filtered = filter !== "all" || $("#job-search").value.trim();
  $("#empty-title").textContent = filtered ? t("没有符合条件的任务") : t("创建你的第一段视频");
  $("#empty-description").textContent = filtered ? t("试试其他关键词，或切换状态筛选。") : t("提交任务后，在这里查看进度与生成结果。");
  updateElapsed();
}

function updateElapsed() {
  document.querySelectorAll(".elapsed").forEach(element => {
    const seconds = Math.max(0, Math.floor((element.dataset.end ? Number(element.dataset.end) : Date.now()/1000) - Number(element.dataset.start)));
    const text = seconds < 60 ? t("{seconds}秒", {seconds}) : seconds < 3600 ? t("{minutes}分{seconds}秒", {minutes:Math.floor(seconds/60),seconds:seconds%60}) : t("{hours}小时{minutes}分", {hours:Math.floor(seconds/3600),minutes:Math.floor(seconds%3600/60)});
    element.textContent = `${element.dataset.end?t("耗时"):t("已等待")} ${text}`;
  });
}

async function loadJobs() {
  const request = ++loadRequest;
  const params = new URLSearchParams({page, page_size:pageSize, status:filter,
    search:$("#job-search").value.trim(), sort:$("#job-sort").value});
  let data;
  try { data = await api(`/api/jobs/history?${params}`); }
  catch(error) { if (request === loadRequest) showError("#library-error",error.originalMessage || error.message); throw error; }
  if (request !== loadRequest) return;
  showError("#library-error", "");
  page = data.page; total = data.total;
  const previous = new Map(jobs);
  jobs.clear();
  data.items.forEach(job => {
    const current = previous.get(job.id);
    jobs.set(job.id, current && current.updated_at > job.updated_at ? current : job);
  });
  pageIds = data.items.map(job => job.id);
  $("#job-count").textContent = data.counts.all;
  document.querySelectorAll("[data-count]").forEach(element => { element.textContent=data.counts[element.dataset.count]; });
  renderPagination();
  renderJobs();
}

function renderPagination() {
  const pages = Math.max(1,Math.ceil(total/pageSize));
  const start = total ? (page-1)*pageSize+1 : 0;
  const end = Math.min(page*pageSize,total);
  $("#result-count").textContent = t(filter !== "all" || $("#job-search").value.trim() ? "共 {total} 条符合条件的任务" : "共 {total} 条生成记录", {total});
  $("#page-range").textContent = t("显示 {start}–{end} / {total} 条", {start,end,total});
  $("#page-label").textContent = `${page} / ${pages}`;
  $("#previous-page").disabled = page <= 1;
  $("#next-page").disabled = page >= pages;
  $("#pagination").hidden = total === 0;
}

function bindingValue(binding) { return binding ? JSON.stringify([binding.node_id,binding.field_name]) : ""; }
function readBinding(value) { if (!value) throw new Error(t("请选择真实的工作流节点字段。")); const [node_id,field_name] = JSON.parse(value); return {node_id,field_name}; }

function populateOptions(select, binding, types = null) {
  select.innerHTML = `<option value="">${t("请选择节点字段")}</option>`;
  for (const node of configuration?.nodes || []) for (const field of node.fields) {
    if (types && !types.includes(field.type)) continue;
    const option = document.createElement("option");
    option.value = JSON.stringify([node.id,field.name]);
    option.textContent = `${node.id} · ${node.name} / ${field.name}`;
    select.append(option);
  }
  select.value = bindingValue(binding);
}

function addBindingRow(binding = null) {
  const row = document.createElement("div");
  row.className = "image-binding";
  row.innerHTML = `<select required aria-label="${t("图片输入字段")}" data-i18n-aria-label="图片输入字段"></select><input class="empty-value" placeholder="${t("空值 JSON（可留空）")}" data-i18n-placeholder="空值 JSON（可留空）" aria-label="${t("未使用图片槽位的空值")}" data-i18n-aria-label="未使用图片槽位的空值"><button type="button" class="icon-button" aria-label="${t("移除图片槽位")}" data-i18n-aria-label="移除图片槽位">×</button>`;
  populateOptions(row.querySelector("select"), binding);
  if (binding && Object.hasOwn(binding,"empty_value")) row.querySelector("input").value = JSON.stringify(binding.empty_value);
  row.querySelector("button").addEventListener("click", () => { row.remove(); updateImageMode(); });
  $("#image-bindings").append(row);
  updateImageMode();
}

function updateImageMode() {
  const mode = $("#image-mode").value;
  $("#list-encoding-label").hidden = mode !== "list";
  $("#empty-slot-help").hidden = mode !== "slots";
  $("#h3-dynamic-help").hidden = mode !== "h3_dynamic";
  $("#add-image-binding").disabled = !["slots","h3_dynamic"].includes(mode) && $("#image-bindings").children.length > 0;
  $("#image-bindings").querySelectorAll(".image-binding").forEach(row => {
    row.classList.toggle("single",mode !== "slots");
    row.querySelector("input").hidden = mode !== "slots";
  });
}

function populateSettings() {
  const config = configuration;
  const mapping = config.mapping;
  renderSettingsStatus();
  $("#fetch-workflow").disabled = !config.key_configured;
  populateOptions($("#prompt-binding"),mapping?.prompt,["str"]);
  populateOptions($("#duration-binding"),mapping?.duration,["str","int","float"]);
  $("#image-mode").value = mapping?.image_mode || "slots";
  $("#list-encoding").value = mapping?.list_encoding || "array";
  $("#image-bindings").replaceChildren();
  if (mapping) mapping.images.forEach(addBindingRow); else addBindingRow();
  $("#min-images").value = mapping?.min_images || 1;
  $("#max-images").value = mapping?.max_images || mapping?.images.length || "";
  $("#min-duration").value = mapping?.min_duration || "";
  $("#max-duration").value = mapping?.max_duration || "";
  $("#save-mapping").disabled = !config.graph_loaded;
}

function renderSettingsStatus() {
  const config = configuration;
  $("#key-state").textContent = config.key_configured ? t("● API Key 已配置（密钥仅保存在服务端）") : t("○ API Key 尚未配置");
  $("#workflow-id").textContent = t("工作流 ID：{id}", {id:config.workflow_id});
  $("#graph-state").textContent = config.graph_loaded ? t("已读取 {count} 个节点。", {count:config.nodes.length}) + (config.error ? t(" 原映射需重新确认。") : "") : t("尚未读取节点；导入时请选择『导出工作流 API』格式。");

}

function openSettings() { if (!configuration) return; showError("#settings-error",""); populateSettings(); $("#settings-dialog").showModal(); }
$("#open-settings").addEventListener("click",openSettings);
$("#banner-settings").addEventListener("click",openSettings);
$("#close-settings").addEventListener("click",() => $("#settings-dialog").close());
$("#image-input").addEventListener("change",event => { addImages(event.target.files); event.target.value=""; });
for (const eventName of ["dragenter","dragover"]) $("#dropzone").addEventListener(eventName,event => { event.preventDefault(); $("#dropzone").classList.add("drag-over"); });
for (const eventName of ["dragleave","drop"]) $("#dropzone").addEventListener(eventName,event => { event.preventDefault(); $("#dropzone").classList.remove("drag-over"); });
$("#dropzone").addEventListener("drop",event => addImages(event.dataTransfer.files));
$("#image-list").addEventListener("click",event => {
  const button = event.target.closest("button[data-image-action]"); if (!button) return;
  const index = Number(button.dataset.index);
  if (button.dataset.imageAction === "remove") URL.revokeObjectURL(images.splice(index,1)[0].url);
  else { const next = index + (button.dataset.imageAction === "left" ? -1 : 1); if (next>=0 && next<images.length) [images[index],images[next]]=[images[next],images[index]]; }
  renderImages();
});
$("#prompt").addEventListener("input",() => { $("#prompt-count").textContent=`${$("#prompt").value.length} / 20000`; updateSubmit(); });
$("#generate-form").addEventListener("submit",async event => {
  event.preventDefault(); if (submitting || !clientStatus || cooldownDeadline > Date.now()) return;
  showError("#form-error","");
  const data = new FormData(); data.append("prompt",$("#prompt").value); data.append("duration",$("#duration").value);
  images.forEach(item => data.append("images",item.file));
  submitting = true; updateSubmit();
  try {
    const job = await api("/api/jobs",{method:"POST",body:data});
    cooldownDeadline = Date.now() + (clientStatus.system_settings.client_cooldown_seconds || 0) * 1000;
    await refreshClientStatus().catch(() => {});
    filter="all"; page=1; $("#job-search").value=""; $("#job-sort").value="newest";
    clearTimeout(searchTimer); updateFilters();
    toast(job.phase === "waiting" ? t("任务已接收，当前排队第 {position} 位，轮到后自动生成。", {position:job.queue_position}) : t("任务已提交，下一次提交时间见倒计时。"));
    await loadJobs().catch(() => toast("任务已提交，记录暂时未刷新，请稍后刷新查看。"));
  }
  catch(error) { if (error.retryAfter) cooldownDeadline = Date.now() + error.retryAfter * 1000; showError("#form-error",error.originalMessage || error.message); await refreshClientStatus().catch(() => {}); }
  finally { submitting=false; updateSubmit(); }
});
function updateFilters() { document.querySelectorAll("[data-filter]").forEach(button => button.classList.toggle("active",button.dataset.filter===filter)); }
document.querySelectorAll("[data-filter]").forEach(button => button.addEventListener("click",() => {
  filter=button.dataset.filter; page=1; updateFilters(); loadJobs().catch(() => {});
}));
$("#job-search").addEventListener("input",() => {
  page=1; loadRequest++; clearTimeout(searchTimer);
  searchTimer=setTimeout(() => loadJobs().catch(() => {}),250);
});
$("#job-sort").addEventListener("change",() => { page=1; loadJobs().catch(() => {}); });
$("#page-size").addEventListener("change",() => { pageSize=Number($("#page-size").value); page=1; loadJobs().catch(() => {}); });
$("#previous-page").addEventListener("click",() => { if (page>1) { page--; loadJobs().catch(() => {}); } });
$("#next-page").addEventListener("click",() => { if (page*pageSize<total) { page++; loadJobs().catch(() => {}); } });
$("#close-job-details").addEventListener("click",() => $("#job-details-dialog").close());
$("#refresh-jobs").addEventListener("click",() => loadJobs().catch(error => toast(error.originalMessage || error.message)));
$("#open-resource-directory").addEventListener("click",async event => {
  const button = event.currentTarget;
  button.disabled = true;
  try { await api("/api/resources/open-directory",{method:"POST"}); toast("已打开生成资源目录"); }
  catch(error) { toast(error.originalMessage || error.message); }
  finally { button.disabled = false; }
});
$("#jobs-container").addEventListener("click",async event => {
  const button = event.target.closest("button[data-job-action]"); if (!button) return;
  if (button.dataset.jobAction === "details") {
    const job=jobs.get(button.dataset.jobId); if (!job) return;
    detailsJobId = job.id;
    renderDetails(job);
    $("#job-details-dialog").showModal(); return;
  }
  let options = {method:"POST"};
  if (button.dataset.jobAction === "attach") {
    const task_id = window.prompt(t("请先在 RunningHub 任务列表确认此次提交，然后填入对应的任务 ID：")); if (!task_id?.trim()) return;
    options = {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({task_id:task_id.trim()})};
  }
  if (button.dataset.jobAction === "resolve-unknown") {
    if (!confirm(t("请先在 RunningHub 任务列表核实：确实没有创建此任务？确认后将释放生成名额；若任务存在，请关联任务 ID。"))) return;
    options = {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({confirmed_not_submitted:true})};
  }
  button.disabled=true;
  try { const job = await api(`/api/jobs/${button.dataset.jobId}/${button.dataset.jobAction}`,options); jobs.set(job.id,job); renderJobs(); await loadJobs(); }
  catch(error) { toast(error.originalMessage || error.message); button.disabled=false; }
});
$("#add-image-binding").addEventListener("click",() => addBindingRow());
$("#image-mode").addEventListener("change",updateImageMode);
$("#fetch-workflow").addEventListener("click",async () => {
  $("#fetch-workflow").disabled=true; showError("#settings-error","");
  try { applyConfig(await api("/api/config/workflow/fetch",{method:"POST"})); populateSettings(); toast("工作流节点已读取，请确认参数映射。"); }
  catch(error) { showError("#settings-error",error.originalMessage || error.message); }
  finally { $("#fetch-workflow").disabled=!configuration.key_configured; }
});
$("#workflow-file").addEventListener("change",async event => {
  const file = event.target.files[0]; if (!file) return;
  const data = new FormData(); data.append("file",file); showError("#settings-error","");
  try { applyConfig(await api("/api/config/workflow/import",{method:"POST",body:data})); populateSettings(); toast("工作流已导入。"); }
  catch(error) { showError("#settings-error",error.originalMessage || error.message); }
  event.target.value="";
});
$("#mapping-form").addEventListener("submit",async event => {
  event.preventDefault(); showError("#settings-error","");
  try {
    const bindings = [...$("#image-bindings").children].map(row => {
      const binding = readBinding(row.querySelector("select").value);
      const value = row.querySelector("input").value.trim();
      if (value && $("#image-mode").value === "slots") { try { binding.empty_value=JSON.parse(value); } catch { throw new Error(t("空值需为合法 JSON，例如 \"None\"（含引号）或 null。")); } }
      return binding;
    });
    const mapping = {prompt:readBinding($("#prompt-binding").value),duration:readBinding($("#duration-binding").value),images:bindings,image_mode:$("#image-mode").value,list_encoding:$("#list-encoding").value,min_images:Number($("#min-images").value),max_images:Number($("#max-images").value),min_duration:Number($("#min-duration").value),max_duration:Number($("#max-duration").value)};
    $("#save-mapping").disabled=true;
    applyConfig(await api("/api/config/mapping",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(mapping)}));
    $("#settings-dialog").close(); toast("映射已验证并保存。");
  } catch(error) { showError("#settings-error",error.originalMessage || error.message); }
  finally { $("#save-mapping").disabled=!configuration?.graph_loaded; }
});

$("#open-system-settings").addEventListener("click",async () => {
  showError("#system-settings-error", "");
  $("#open-system-settings").disabled = true;
  try {
    const settings = await api("/api/system-settings");
    $("#max-concurrent-generations").value = settings.max_concurrent_generations;
    $("#client-cooldown-seconds").value = settings.client_cooldown_seconds;
    $("#system-settings-dialog").showModal();
  } catch(error) { toast(error.originalMessage || error.message); }
  finally { $("#open-system-settings").disabled = false; }
});
$("#close-system-settings").addEventListener("click",() => $("#system-settings-dialog").close());
$("#system-settings-form").addEventListener("submit",async event => {
  event.preventDefault();
  $("#save-system-settings").disabled = true;
  showError("#system-settings-error", "");
  try {
    await api("/api/system-settings",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({
      max_concurrent_generations:Number($("#max-concurrent-generations").value),
      client_cooldown_seconds:Number($("#client-cooldown-seconds").value)
    })});
    $("#system-settings-dialog").close();
    toast("系统设置已保存并生效。");
    await refreshClientStatus().catch(() => {});
    await loadJobs().catch(() => {});
  } catch(error) { showError("#system-settings-error",error.originalMessage || error.message); }
  finally { $("#save-system-settings").disabled = false; }
});

async function init() {
  await refreshClientStatus().catch(error => toast(error.originalMessage || error.message));
  const results = await Promise.allSettled([api("/api/config"),loadJobs()]);
  if (results[0].status==="fulfilled") applyConfig(results[0].value); else { $("#connection-label").dataset.i18n="连接服务失败"; $("#connection-label").textContent=t("连接服务失败"); toast(results[0].reason.originalMessage || results[0].reason.message); }
  if (results[1].status==="rejected") toast(results[1].reason.originalMessage || results[1].reason.message);
  watchJobs();
}
setInterval(() => { updateElapsed(); updateSubmit(); },1000);
setInterval(() => { if (!document.hidden) { loadJobs().catch(() => {}); refreshClientStatus().catch(() => {}); } },15000);
document.addEventListener("visibilitychange",() => { if (!document.hidden) { loadJobs().catch(error => toast(error.originalMessage || error.message)); refreshClientStatus().catch(() => {}); } });
window.addEventListener("beforeunload",() => { images.forEach(item => URL.revokeObjectURL(item.url)); eventStream?.close(); });
init();

function renderDetails(job) {
  $("#job-details-content").innerHTML=`<div class="detail-meta"><span>${escapeHTML(t(phaseKeys[job.phase] || job.phase))}</span><span>${t("{count} 张参考图 · {seconds} 秒", {count:job.image_count,seconds:job.duration})}</span></div><h3>${t("提示词")}</h3><p class="detail-prompt">${escapeHTML(job.prompt)}</p><h3>${t("任务 ID")}</h3><p class="detail-id">${escapeHTML(job.id)}${job.remote_task_id?`<br>RunningHub · ${escapeHTML(job.remote_task_id)}`:""}</p>${job.error?`<div class="job-error">${escapeHTML(I18n.message(job.error))}</div>`:""}`;
}

function changeLanguage() {
  I18n.apply();
  if (configuration) {
    const duration = $("#duration").value;
    applyConfig(configuration);
    $("#duration").value = duration;
    renderSettingsStatus();
  }
  renderQueue();
  renderImages();
  renderPagination();
  renderJobs();
  document.querySelectorAll("select option[value='']").forEach(option => { option.textContent = t("请选择节点字段"); });
  document.querySelectorAll("[data-message]").forEach(element => { element.textContent = I18n.message(element.dataset.message); });
  if ($("#job-details-dialog").open && jobs.has(detailsJobId)) renderDetails(jobs.get(detailsJobId));
}
$("#language-select").addEventListener("change",event => I18n.setLanguage(event.target.value));
window.addEventListener("languagechange",changeLanguage);
I18n.apply();

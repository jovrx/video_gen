"use strict";

// Keep creation state independent of video jobs and workflow setup.
(() => {
  const find = selector => document.querySelector(selector);
  const dialog = find("#creation-dialog");
  const storageKey = "h3-studio-creation-v1";
  const fields = {prompt:"#creation-prompt",title:"#creation-script-title",script:"#creation-script",
    shot_count:"#shot-count",duration:"#shot-duration",target_model:"#target-model",
    custom_model:"#custom-model",visual_style:"#visual-style"};
  const textLimits = {prompt:20000,title:300,script:40000,custom_model:2000,visual_style:2000};
  const shotLimits = {title:300,visual:5000,camera:5000,audio:5000,prompt:20000};
  const defaults = () => ({version:1,prompt:"",title:"",script:"",shot_count:6,duration:8,
    target_model:"h3",custom_model:"",visual_style:"",source_script:"",shots:[]});
  let draft = defaults(), busy = "", llmConfig = null, configPending = false, storageMessage = "";
  let feedbackTimer;
  let previewDraft = null, streamStatus = "", previewCount = 0;
  const isText = (value,max) => typeof value === "string" && value.length <= max;
  const integer = (value,min,max) => Number.isInteger(value) && value >= min && value <= max;

  function validDraft(value) {
    return value && value.version === 1 && Object.entries(textLimits).every(([key,max]) => isText(value[key],max))
      && isText(value.source_script,40000) && ["h3","generic","custom"].includes(value.target_model)
      // Numeric inputs may be temporarily blank or invalid while the user types.
      && ["shot_count","duration"].every(key => (typeof value[key] === "number" && Number.isFinite(value[key])) || isText(value[key],20))
      && Array.isArray(value.shots) && value.shots.length <= 24 && value.shots.every((shot,index) =>
        shot && shot.number === index+1 && ((typeof shot.duration === "number" && Number.isFinite(shot.duration)) || isText(shot.duration,20))
        && Object.entries(shotLimits).every(([key,max]) => isText(shot[key],max)));
  }

  function storageNotice(message) {
    storageMessage = message;
    const element = find("#creation-storage-status");
    element.hidden = !message; element.textContent = I18n.t(message);
  }

  try {
    const saved = localStorage.getItem(storageKey);
    if (saved) {
      const parsed = JSON.parse(saved);
      if (!validDraft(parsed)) throw new Error("invalid draft");
      draft = parsed;
    }
  } catch {
    storageNotice("无法恢复创作草稿；你仍可继续编辑。浏览器存储可能不可用或草稿已损坏。");
  }

  function saveDraft() {
    try {localStorage.setItem(storageKey,JSON.stringify(draft));}
    catch {storageNotice("浏览器无法保存草稿；仍可编辑和生成，但刷新后可能丢失内容。");}
  }

  function syncState() {
    find("#custom-model-label").hidden = draft.target_model !== "custom";
    const duration = find("#shot-duration");
    duration.min = draft.target_model === "h3" ? "4" : "1";
    duration.max = draft.target_model === "h3" ? "15" : "120";
    find("#creation-script-count").textContent = `${find(fields.script).value.length} / 40000`;
    find("#creation-stale").hidden = !draft.shots.length || draft.script === draft.source_script;
    find("#creation-empty").hidden = Boolean((previewDraft?.shots || draft.shots).length);
    dialog.setAttribute("aria-busy",String(Boolean(busy)));
    // Freeze all dependent inputs while results are being generated, including saved shots.
    dialog.querySelectorAll("input,textarea,select,[data-shot-action]").forEach(element => {element.disabled = Boolean(busy);});
    find("#clear-creation").disabled = Boolean(busy);
    find("#generate-script").disabled = Boolean(busy) || configPending || !llmConfig?.configured || !draft.prompt.trim();
    find("#generate-storyboard").disabled = Boolean(busy) || configPending || !llmConfig?.configured || !draft.script.trim();
    for (const [id,type,label] of [["#generate-script","script","生成剧本"],["#generate-storyboard","storyboard","生成分镜"]]) {
      const button = find(id);
      button.dataset.i18n = busy === type ? "正在生成…" : label;
      button.textContent = I18n.t(button.dataset.i18n);
    }
  }

  function configStatus() {
    const element = find("#creation-config-status");
    if (configPending) element.textContent = I18n.t("正在读取文本模型配置…");
    else if (llmConfig?.configured) element.textContent = `${I18n.t("文本模型已连接")} · ${llmConfig.model || ""}`;
    else if (llmConfig?.error) element.textContent = I18n.message(llmConfig.error);
    else element.textContent = I18n.t("请在 .env 中配置 LLM_API_KEY 和 LLM_MODEL 并重启服务；仍可手动编辑剧本及使用已保存的分镜。");
  }

  async function loadConfig() {
    if (configPending) return;
    configPending = true; configStatus(); syncState();
    try {llmConfig = await api("/api/creation/config");}
    catch (error) {llmConfig = {configured:false,error:error.originalMessage || error.message};}
    finally {configPending = false; configStatus(); syncState();}
  }

  function renderShots(shots = draft.shots) {
    const container = find("#creation-shots"); container.replaceChildren();
    for (const [index,shot] of shots.entries()) {
      const card = document.createElement("article"); card.className = "shot-card";
      const header = document.createElement("div"); header.className = "shot-header";
      const heading = document.createElement("h4");
      heading.dataset.shotHeading = shot.number;
      header.append(heading);
      if (previewDraft) {
        const badge = document.createElement("span"); badge.className="shot-stream-badge";
        badge.dataset.i18n="生成中"; header.append(badge);
      }
      card.append(header);
      for (const [key,label] of [["title","镜头标题"],["duration","时长（秒）"],["visual","画面与动作"],["camera","景别与运镜"],["audio","对白与声音"],["prompt","分镜 Prompt"]]) {
        const wrapper = document.createElement("div"); wrapper.className = `shot-field shot-${key}`;
        const caption = document.createElement("label"); caption.dataset.i18n = label;
        const input = document.createElement(["duration","title"].includes(key) ? "input" : "textarea");
        input.id = `creation-shot-${index}-${key}`; caption.htmlFor = input.id;
        input.dataset.shotField = key; input.value = shot[key] ?? "";
        if (key === "duration") {input.type = "number"; input.min = "1"; input.max = "120"; input.step = "1";}
        else {input.maxLength = shotLimits[key]; if (input.tagName === "TEXTAREA") input.rows = key === "prompt" ? 5 : 2;}
        input.addEventListener("input",() => {shot[key] = input.value; saveDraft();});
        wrapper.append(caption,input); card.append(wrapper);
      }
      const actions = document.createElement("div"); actions.className = "shot-actions";
      for (const [action,label] of [["copy","复制 Prompt"],["use","用于视频生成"]]) {
        const button = document.createElement("button"); button.type = "button";
        button.className = "secondary-button"; button.dataset.shotAction = action; button.dataset.i18n = label;
        button.addEventListener("click",() => action === "copy" ? copyShot(shot) : useShot(shot));
        actions.append(button);
      }
      card.append(actions); container.append(card);
    }
    translate(); syncState();
  }

  function translate() {
    I18n.apply(dialog);
    dialog.querySelectorAll("[data-shot-heading]").forEach(element => {
      element.textContent = I18n.t("镜头 {number}",{number:element.dataset.shotHeading});
    });
    configStatus(); storageNotice(storageMessage);
    const status = find("#creation-stream-status");
    status.hidden = !streamStatus;
    status.textContent = I18n.t(streamStatus,{count:previewCount,total:draft.shot_count});
  }

  function showPreview(type, value) {
    if (type === "script") {
      for (const key of ["title","content"]) {
        const limit = key === "title" ? 300 : 40000;
        if (isText(value[key],limit)) find(key === "title" ? fields.title : fields.script).value = value[key];
      }
      streamStatus = "正在生成剧本，内容实时更新…";
    } else if (Array.isArray(value.shots) && value.shots.length <= Number(draft.shot_count)) {
      const shots = (previewDraft?.shots || []).map(shot => ({...shot}));
      for (const update of value.shots) {
        if (!update || !integer(update.number,1,Number(draft.shot_count))) continue;
        while (shots.length < update.number) shots.push({number:shots.length+1,duration:"",
          ...Object.fromEntries(Object.keys(shotLimits).map(key=>[key,""]))});
        const shot = shots[update.number-1];
        if (Object.hasOwn(update,"duration")) shot.duration = integer(update.duration,1,120)?update.duration:"";
        for (const [key,max] of Object.entries(shotLimits)) if (isText(update[key],max)) shot[key]=update[key];
      }
      previewDraft = {shots}; previewCount = shots.length;
      if (find("#creation-shots").children.length !== shots.length || !find(".shot-stream-badge")) renderShots(shots);
      find("#creation-shots").querySelectorAll(".shot-card").forEach((card,index) => {
        card.querySelectorAll("[data-shot-field]").forEach(input => {input.value=shots[index][input.dataset.shotField] ?? "";});
      });
      streamStatus = "正在生成分镜 {count} / {total}，内容实时更新…";
    }
    translate(); syncState();
  }

  async function copyShot(shot) {
    let message;
    try {await navigator.clipboard.writeText(shot.prompt); message = "Prompt 已复制";}
    catch {message = "无法访问剪贴板，请手动选择并复制 Prompt。";}
    toast(message);
    // Native modal dialogs appear above the page toast; keep copy feedback in the modal too.
    const feedback = find("#creation-feedback");
    feedback.dataset.message = message; feedback.textContent = I18n.t(message); feedback.hidden = false;
    clearTimeout(feedbackTimer); feedbackTimer = setTimeout(() => {feedback.hidden = true;},3500);
  }

  function useShot(shot) {
    const prompt = find("#prompt"), text = shot.prompt.trim();
    const limit = Math.min(20000,prompt.maxLength > 0 ? prompt.maxLength : 20000);
    if (!text || shot.prompt.length > limit) {
      showError("#creation-error",I18n.t("Prompt 必须为 1–{max} 字符，请编辑后再使用。",{max:limit})); return;
    }
    const seconds = Number(shot.duration), mapping = configuration?.mapping;
    if (!integer(seconds,1,120)) {showError("#creation-error","分镜时长必须是 1–120 的整数。"); return;}
    prompt.value = shot.prompt; prompt.dispatchEvent(new Event("input",{bubbles:true}));
    if (mapping && seconds >= Number(mapping.min_duration) && seconds <= Number(mapping.max_duration)) {
      const duration = find("#duration"); duration.value = String(seconds); duration.dispatchEvent(new Event("input",{bubbles:true}));
      toast("Prompt 已填入视频表单，请确认参考图后生成视频。");
    } else toast("Prompt 已填入；当前工作流不支持此分镜时长或尚未配置，请手动确认视频时长。");
    saveDraft(); dialog.close(); prompt.focus(); prompt.scrollIntoView({block:"center",behavior:"smooth"});
  }

  async function generate(type) {
    if (busy || configPending || !llmConfig?.configured) return;
    const prompt = draft.prompt.trim(), script = draft.script.trim();
    let payload;
    if (type === "script") {
      if (!prompt || prompt.length > 20000) {showError("#creation-error","创意输入必须为 1–20000 字符。"); return;}
      payload = {prompt};
    } else {
      const count = Number(draft.shot_count), duration = Number(draft.duration), h3 = draft.target_model === "h3";
      if (!script || script.length > 40000) {showError("#creation-error","剧本必须为 1–40000 字符。"); return;}
      if (!integer(count,1,24)) {showError("#creation-error","分镜数量必须是 1–24 的整数。"); return;}
      if (!integer(duration,h3?4:1,h3?15:120)) {showError("#creation-error",h3?"H3 每镜时长必须是 4–15 的整数。":"分镜时长必须是 1–120 的整数。"); return;}
      if (draft.target_model === "custom" && !draft.custom_model.trim()) {showError("#creation-error","请填写自定义模型名称与格式要求。"); return;}
      payload = {script,shot_count:count,duration,target_model:draft.target_model,
        custom_model:draft.target_model === "custom" ? draft.custom_model.trim() : "",visual_style:draft.visual_style.trim()};
    }
    busy = type; previewDraft = null; previewCount = 0;
    streamStatus = "正在等待模型输出…";
    showError("#creation-error",""); translate(); syncState();
    try {
      const result = await streamCreation(`/api/creation/${type}/stream`,payload,value => showPreview(type,value));
      if (type === "script") {
        if (!isText(result.content,40000) || !result.content.trim() || !isText(result.title,300) || !result.title.trim()) throw new Error("文本模型返回了无效内容，请重试");
        draft.script = result.content; draft.title = result.title;
        find(fields.script).value = draft.script; find(fields.title).value = draft.title;
      } else {
        const candidate = {...draft,source_script:draft.script,shots:result.shots};
        if (!validDraft(candidate) || result.shots.length !== payload.shot_count || result.shots.some(shot => shot.duration !== payload.duration || Object.keys(shotLimits).some(key => !shot[key].trim()))) throw new Error("文本模型返回了无效内容，请重试");
        draft = candidate; previewDraft = null; renderShots();
      }
      streamStatus = "生成完成，可编辑并使用。";
      saveDraft();
    } catch (error) {
      streamStatus = ""; previewDraft = null;
      find(fields.script).value = draft.script; find(fields.title).value = draft.title;
      renderShots(); showError("#creation-error",error.originalMessage || error.message);
    }
    finally {busy = ""; previewDraft = null; translate(); syncState();}
  }

  for (const [key,selector] of Object.entries(fields)) {
    const element = find(selector); element.value = draft[key];
    element.addEventListener("input",() => {draft[key] = element.value; saveDraft(); syncState();});
  }
  find("#generate-script").addEventListener("click",() => generate("script"));
  find("#generate-storyboard").addEventListener("click",() => generate("storyboard"));
  find("#open-creation").addEventListener("click",() => {dialog.showModal(); loadConfig();});
  find("#close-creation").addEventListener("click",() => dialog.close());
  find("#clear-creation").addEventListener("click",() => {
    if (busy || !window.confirm(I18n.t("清空剧本与全部分镜草稿？此操作无法撤销。"))) return;
    draft = defaults(); streamStatus = "";
    for (const [key,selector] of Object.entries(fields)) find(selector).value = draft[key];
    showError("#creation-error",""); renderShots();
    try {localStorage.removeItem(storageKey);}
    catch {storageNotice("浏览器无法保存草稿；仍可编辑和生成，但刷新后可能丢失内容。");}
  });
  // Input edits save synchronously, so closing or refreshing cannot race a debounce.
  window.addEventListener("languagechange",() => {translate(); syncState();});
  renderShots();
})();

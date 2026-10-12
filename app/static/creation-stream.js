"use strict";

// A POST response remains open while structured previews arrive from the model.
async function streamCreation(path, payload, onPreview) {
  const abort = new AbortController();
  // The backend caps generation at 600 seconds; also bound a lost browser connection.
  const timeout = setTimeout(() => abort.abort(),650000);
  let reader;
  const fail = message => {const error=new Error(message);error.originalMessage=message;return error;};
  try {
    const response = await fetch(path,{method:"POST",headers:{"Content-Type":"application/json","Accept":"text/event-stream"},
      body:JSON.stringify(payload),signal:abort.signal});
    if (!response.ok) {
      const data = await response.json();
      throw fail(typeof data.detail === "string" ? data.detail : "请求失败");
    }
    if (!response.body || !response.headers.get("Content-Type")?.includes("text/event-stream")) {
      throw fail("服务未返回流式响应，请重启服务后重试。");
    }
    reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const {value,done} = await reader.read();
      buffer += decoder.decode(value,{stream:!done});
      if (buffer.length > 3 * 1024 * 1024) throw fail("文本模型返回内容过长，请减少分镜数量或缩短剧本");
      buffer = buffer.replace(/\r\n/g,"\n");
      let end;
      while ((end = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0,end); buffer = buffer.slice(end+2);
        let name = "message"; const data = [];
        for (const line of frame.split("\n")) {
          if (line.startsWith("event:")) name = line.slice(6).trim();
          if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /,""));
        }
        if (!data.length) continue;
        const item = JSON.parse(data.join("\n"));
        if (!item || typeof item !== "object" || Array.isArray(item)) throw fail("文本模型返回了无效内容，请重试");
        if (name === "error") throw fail(typeof item.detail === "string" ? item.detail : "请求失败");
        if (name === "preview") onPreview(item);
        if (name === "result") return item;
      }
      if (done) throw fail("文本模型流式输出中断，请重试；原草稿已保留");
    }
  } catch (error) {
    if (error.originalMessage) throw error;
    throw fail("文本模型流式输出中断，请重试；原草稿已保留");
  } finally {
    clearTimeout(timeout);
    if (reader) {try {await reader.cancel();} catch { /* Connection already closed. */ }}
    abort.abort();
  }
}

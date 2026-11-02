// Streaming chat client for the Stella Cloud gateway (OpenAI-compatible wire format).

/** Build fetch() arguments for one streaming request. */
export function buildRequest({ target, messages, maxTokens, temperature }) {
  const headers = { "Content-Type": "application/json" };
  if (target.apiKey) headers.Authorization = `Bearer ${target.apiKey}`;
  const body = { model: target.model, messages, stream: true, stream_options: { include_usage: true } };
  if (maxTokens) body.max_tokens = maxTokens;
  if (temperature !== undefined) body.temperature = temperature;
  return { url: target.url, init: { method: "POST", headers, body: JSON.stringify(body) } };
}

/** Interpret one SSE `data:` JSON payload. */
export function parseChunk(obj) {
  const out = { token: "", usage: null, error: "", model: "" };
  if (!obj || typeof obj !== "object") return out;
  if (obj.error) out.error = typeof obj.error === "string" ? obj.error : obj.error.message || JSON.stringify(obj.error);
  const delta = obj.choices?.[0]?.delta;
  if (delta && typeof delta.content === "string") out.token = delta.content;
  if (obj.usage && obj.usage.prompt_tokens !== undefined) out.usage = { input: obj.usage.prompt_tokens || 0, output: obj.usage.completion_tokens || 0 };
  if (typeof obj.model === "string") out.model = obj.model;
  return out;
}

/**
 * Stream a chat completion. Calls onToken(fullTextSoFar) as text arrives.
 * Resolves with { text, usage: {input, output}, routedVia }.
 */
export async function streamChat({ target, messages, maxTokens, temperature, signal, onToken }) {
  const { url, init } = buildRequest({ target, messages, maxTokens, temperature });
  let resp;
  try {
    resp = await fetch(url, { ...init, signal });
  } catch (e) {
    if (e.name === "AbortError") throw e;
    throw new Error(`нет соединения с ${url} (${e.message}). Проверьте, что сервер запущен и адрес верный.`);
  }
  if (!resp.ok || !resp.body) {
    const errText = await resp.text().catch(() => "");
    const err = new Error(`HTTP ${resp.status}: ${extractError(errText) || resp.statusText}`);
    err.status = resp.status;
    err.detail = extractError(errText) || resp.statusText;
    throw err;
  }
  let routedVia = resp.headers.get("x-routed-via") || "";
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let text = "";
  const usage = { input: 0, output: 0 };
  let serverError = "";
  let finished = false;
  while (!finished) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop();
    for (const line of lines) {
      const t = line.trim();
      if (!t.startsWith("data:")) continue;
      const payload = t.slice(5).trim();
      if (payload === "[DONE]") {
        finished = true;
        break;
      }
      let obj;
      try {
        obj = JSON.parse(payload);
      } catch {
        continue;
      }
      const c = parseChunk(obj);
      if (c.error) serverError = c.error;
      if (c.usage) {
        usage.input = c.usage.input || usage.input;
        usage.output = c.usage.output || usage.output;
      }
      if (c.model && !routedVia && c.model !== target.model) routedVia = c.model;
      if (c.token) {
        text += c.token;
        onToken?.(text);
      }
    }
  }
  if (serverError && !text) throw new Error(`сервер: ${serverError}`);
  return { text, usage, routedVia };
}

function extractError(body) {
  try {
    const j = JSON.parse(body);
    return j.error?.message || j.error || j.message || body.slice(0, 200);
  } catch {
    return body.slice(0, 200);
  }
}

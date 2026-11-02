// Provider-aware streaming client for chat completions.
// OpenAI-compatible wire format for FreeLLMAPI, OpenAI, Gemini (OpenAI endpoint), Qwen, Kimi,
// Ollama/custom and the local server; native Messages API for Anthropic.

const ANTHROPIC_VERSION = "2023-06-01";

/** Resolve endpoint/model/key for the active provider. */
export function resolveTarget(preset, pData = {}, localApiBase = "http://localhost:8080") {
  const url =
    (pData.customUrl && pData.customUrl.trim()) ||
    (preset.id === "local" ? `${localApiBase.replace(/\/$/, "")}/v1/chat/completions` : preset.url);
  return { url, model: (pData.model && pData.model.trim()) || preset.defaultModel, apiKey: (pData.apiKey || "").trim() };
}

/** Build fetch() arguments for one streaming request. */
export function buildRequest({ preset, target, messages, maxTokens, temperature }) {
  const headers = { "Content-Type": "application/json" };
  if (preset.type === "anthropic") {
    if (target.apiKey) headers["x-api-key"] = target.apiKey;
    headers["anthropic-version"] = ANTHROPIC_VERSION;
    // Required by Anthropic for calls made directly from a browser.
    headers["anthropic-dangerous-direct-browser-access"] = "true";
    const system = messages.filter((m) => m.role === "system").map((m) => m.content).join("\n\n");
    const body = {
      model: target.model,
      max_tokens: maxTokens,
      stream: true,
      messages: mergeRoles(messages.filter((m) => m.role !== "system")),
    };
    if (system) body.system = system;
    return { url: target.url, init: { method: "POST", headers, body: JSON.stringify(body) } };
  }

  if (target.apiKey) headers.Authorization = `Bearer ${target.apiKey}`;
  const body = { model: target.model, messages, stream: true, stream_options: { include_usage: true } };
  const isOpenAI = /api\.openai\.com/.test(target.url);
  // Newer OpenAI models take max_completion_tokens and only the default temperature.
  if (isOpenAI) body.max_completion_tokens = maxTokens;
  else body.max_tokens = maxTokens;
  if (!(isOpenAI && /^(o\d|gpt-5)/.test(target.model)) && temperature !== undefined) body.temperature = temperature;
  return { url: target.url, init: { method: "POST", headers, body: JSON.stringify(body) } };
}

/** Anthropic rejects consecutive messages with the same role: merge them. */
function mergeRoles(msgs) {
  const out = [];
  for (const m of msgs) {
    const last = out[out.length - 1];
    if (last && last.role === m.role) last.content += "\n\n" + m.content;
    else out.push({ role: m.role, content: m.content });
  }
  if (out.length && out[0].role !== "user") out.unshift({ role: "user", content: "(начало диалога)" });
  return out;
}

/** Interpret one SSE `data:` JSON payload from any supported provider. */
export function parseChunk(obj) {
  const out = { token: "", usage: null, error: "", model: "" };
  if (!obj || typeof obj !== "object") return out;
  if (obj.error) out.error = typeof obj.error === "string" ? obj.error : obj.error.message || JSON.stringify(obj.error);
  if (obj.type === "error" && obj.error) out.error = obj.error.message || "error";
  // Anthropic
  if (obj.type === "content_block_delta" && obj.delta?.type === "text_delta") out.token = obj.delta.text || "";
  if (obj.type === "message_start" && obj.message?.usage) out.usage = { input: obj.message.usage.input_tokens || 0, output: 0 };
  if (obj.type === "message_delta" && obj.usage) out.usage = { input: 0, output: obj.usage.output_tokens || 0 };
  // OpenAI-compatible
  const delta = obj.choices?.[0]?.delta;
  if (delta && typeof delta.content === "string") out.token = delta.content;
  if (obj.usage && obj.usage.prompt_tokens !== undefined) out.usage = { input: obj.usage.prompt_tokens || 0, output: obj.usage.completion_tokens || 0 };
  if (typeof obj.model === "string") out.model = obj.model;
  // Custom local server
  if (!out.token && typeof obj.token === "string") out.token = obj.token;
  return out;
}

/**
 * Stream a chat completion. Calls onToken(fullTextSoFar) as text arrives.
 * Resolves with { text, usage: {input, output}, routedVia }.
 */
export async function streamChat({ preset, target, messages, maxTokens, temperature, signal, onToken }) {
  const { url, init } = buildRequest({ preset, target, messages, maxTokens, temperature });
  let resp;
  try {
    resp = await fetch(url, { ...init, signal });
  } catch (e) {
    if (e.name === "AbortError") throw e;
    throw new Error(`нет соединения с ${url} (${e.message}). Проверьте, что сервер запущен и адрес верный.`);
  }
  if (!resp.ok || !resp.body) {
    const errText = await resp.text().catch(() => "");
    throw new Error(`HTTP ${resp.status}: ${extractError(errText) || resp.statusText}`);
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

/** Base URL (…/v1) for an OpenAI-compatible chat endpoint. */
export function apiBase(chatUrl) {
  return chatUrl.replace(/\/chat\/completions\/?$/, "").replace(/\/messages\/?$/, "");
}

/** GET /models from an OpenAI-compatible server (FreeLLMAPI, OpenAI, Ollama, …). */
export async function listModels(preset, target) {
  const headers = {};
  if (preset.type === "anthropic") {
    if (target.apiKey) headers["x-api-key"] = target.apiKey;
    headers["anthropic-version"] = ANTHROPIC_VERSION;
    headers["anthropic-dangerous-direct-browser-access"] = "true";
  } else if (target.apiKey) headers.Authorization = `Bearer ${target.apiKey}`;
  const resp = await fetch(`${apiBase(target.url)}/models`, { headers });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${extractError(await resp.text().catch(() => ""))}`);
  const j = await resp.json();
  const items = Array.isArray(j) ? j : j.data || j.models || [];
  return items.map((m) => (typeof m === "string" ? m : m.id || m.name)).filter(Boolean);
}

/** Send a tiny prompt to verify key, endpoint and model. */
export async function testConnection(preset, target) {
  const started = Date.now();
  const r = await streamChat({ preset, target, messages: [{ role: "user", content: "Ответь одним словом: ок" }], maxTokens: 16, temperature: 0 });
  return { ok: !!r.text.trim(), ms: Date.now() - started, text: r.text.trim(), routedVia: r.routedVia };
}

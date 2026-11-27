'use strict';
// Клиент OpenRouter (OpenAI-совместимый API) со стримингом и вызовом инструментов.

const OPENROUTER_BASE = process.env.STELLA_OPENROUTER_BASE || 'https://openrouter.ai/api/v1';
const OPENROUTER_URL = OPENROUTER_BASE + '/chat/completions';
const MODELS_URL = OPENROUTER_BASE + '/models';

/** Инкрементальный парсер SSE: принимает куски текста, возвращает массив JSON-событий. */
class SSEParser {
  constructor() { this.buf = ''; this.done = false; }
  push(chunk) {
    this.buf += chunk;
    const events = [];
    let idx;
    while ((idx = this.buf.indexOf('\n')) >= 0) {
      const line = this.buf.slice(0, idx).replace(/\r$/, '');
      this.buf = this.buf.slice(idx + 1);
      if (!line || line.startsWith(':')) continue; // комментарии OpenRouter (": OPENROUTER PROCESSING")
      if (!line.startsWith('data:')) continue;
      const data = line.slice(5).trim();
      if (data === '[DONE]') { this.done = true; continue; }
      try { events.push(JSON.parse(data)); } catch { /* неполная строка невозможна после \n — пропускаем мусор */ }
    }
    return events;
  }
}

/** Собирает дельты tool_calls по индексу. */
function mergeToolCallDeltas(acc, deltas) {
  for (const d of deltas || []) {
    const i = d.index ?? acc.length;
    if (!acc[i]) acc[i] = { id: d.id || '', type: 'function', function: { name: '', arguments: '' } };
    if (d.id) acc[i].id = d.id;
    if (d.function?.name) acc[i].function.name += d.function.name;
    if (d.function?.arguments) acc[i].function.arguments += d.function.arguments;
  }
  return acc;
}

function safeJson(s) {
  if (!s || !String(s).trim()) return {};
  try { return JSON.parse(s); } catch {
    // иногда модели присылают лишнюю запятую или обрезанный JSON
    try { return JSON.parse(String(s).replace(/,\s*([}\]])/g, '$1')); } catch { return { __raw: s }; }
  }
}

function describeHttpError(status, bodyText, provider = 'openrouter') {
  let msg = bodyText;
  try { const j = JSON.parse(bodyText); msg = j.error?.message || j.message || bodyText; } catch { /* */ }
  const hints = {
    401: 'Неверный ключ OpenRouter. Проверьте его в Настройках.',
    402: 'На балансе OpenRouter недостаточно средств.',
    403: 'Доступ запрещён (модерация или ограничения ключа).',
    404: 'Модель не найдена или не поддерживает нужные функции.',
    408: 'Превышено время ожидания ответа.',
    429: 'Слишком много запросов — подождите немного.',
    502: 'Провайдер модели временно недоступен.',
    503: 'Нет доступных провайдеров для этой модели.',
  };
  const e = provider === 'cloud'
    ? new Error(`Stella Cloud: ${String(msg).slice(0, 300)}`)
    : new Error(`${hints[status] || 'Ошибка OpenRouter'} (${status}) ${String(msg).slice(0, 300)}`.trim());
  e.status = status; e.raw = msg;
  return e;
}

/**
 * Один запрос к модели со стримингом.
 * @returns {Promise<{content:string, toolCalls:Array, finishReason:string|null, usage:object|null}>}
 */
async function streamChat({ apiKey, model, messages, tools, temperature = 0.8, maxTokens = 1200, signal, onToken, fetchImpl = fetch, baseUrl, provider = 'openrouter' }) {
  if (!apiKey) throw new Error(provider === 'cloud' ? 'Войдите в Stella Cloud (Настройки → Stella Cloud)' : 'Не задан ключ OpenRouter. Откройте вкладку «ИИ».');
  const body = { model, messages, stream: true, temperature, max_tokens: maxTokens };
  if (tools && tools.length) { body.tools = tools; body.tool_choice = 'auto'; }
  const res = await fetchImpl(baseUrl ? baseUrl.replace(/\/$/, '') + '/chat/completions' : OPENROUTER_URL, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
      'HTTP-Referer': 'https://github.com/stella-assistant',
      'X-Title': 'Stella Assistant',
    },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) throw describeHttpError(res.status, await res.text(), provider);
  const parser = new SSEParser();
  let content = '', finishReason = null, usage = null;
  const toolCalls = [];
  const decoder = new TextDecoder();
  const handle = (events) => {
    for (const ev of events) {
      if (ev.error) throw describeHttpError(ev.error.code || 500, JSON.stringify(ev));
      const ch = ev.choices?.[0];
      if (ev.usage) usage = ev.usage;
      if (!ch) continue;
      const d = ch.delta || {};
      if (d.content) { content += d.content; onToken?.(d.content); }
      if (d.tool_calls) mergeToolCallDeltas(toolCalls, d.tool_calls);
      if (ch.finish_reason) finishReason = ch.finish_reason;
    }
  };
  if (res.body && typeof res.body.getReader === 'function') {
    const reader = res.body.getReader();
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      handle(parser.push(decoder.decode(value, { stream: true })));
    }
  } else {
    handle(parser.push(await res.text()));
  }
  handle(parser.push('\n'));
  return { content, toolCalls: toolCalls.filter(Boolean), finishReason, usage };
}

/**
 * Агентный цикл: модель → инструменты → модель … пока модель не ответит текстом.
 * @param {object} o
 * @param {Array} o.messages история без системного промпта
 * @param {(call:{id,name,args}) => Promise<{ok:boolean, output:string, image?:string}>} o.executeTool
 */
async function runAgent(o) {
  const { systemPrompt, history, tools, executeTool, onToken, onToolStart, onToolEnd, onStep, maxSteps = 12, signal } = o;
  const messages = [{ role: 'system', content: systemPrompt }, ...history];
  const newMessages = [];
  let toolsEnabled = !!(tools && tools.length);
  let finalText = '';
  for (let step = 0; step < maxSteps; step++) {
    if (signal?.aborted) throw Object.assign(new Error('Отменено'), { name: 'AbortError' });
    onStep?.(step);
    let r;
    try {
      r = await streamChat({ ...o, messages, tools: toolsEnabled ? tools : undefined, onToken });
    } catch (e) {
      // модель не умеет инструменты — повторяем без них
      if (toolsEnabled && (e.status === 404 || e.status === 400) && /tool|function/i.test(e.raw || e.message)) {
        toolsEnabled = false; step--; o.onWarning?.('Эта модель не поддерживает управление компьютером — отвечаю без инструментов.');
        continue;
      }
      throw e;
    }
    const assistantMsg = { role: 'assistant', content: r.content || '' };
    if (r.toolCalls.length) assistantMsg.tool_calls = r.toolCalls.map((t, i) => ({ ...t, id: t.id || `call_${step}_${i}` }));
    messages.push(assistantMsg); newMessages.push(assistantMsg);
    if (r.content) finalText += (finalText ? '\n' : '') + r.content;
    if (!r.toolCalls.length) return { text: finalText, newMessages, steps: step + 1 };
    const images = [];
    for (const tc of assistantMsg.tool_calls) {
      const args = safeJson(tc.function.arguments);
      onToolStart?.({ id: tc.id, name: tc.function.name, args });
      let result;
      try { result = await executeTool({ id: tc.id, name: tc.function.name, args }); } catch (e) { result = { ok: false, output: `Ошибка: ${e.message}` }; }
      onToolEnd?.({ id: tc.id, name: tc.function.name, args, ...result });
      const toolMsg = { role: 'tool', tool_call_id: tc.id, content: String(result.output ?? '').slice(0, 20000) };
      messages.push(toolMsg); newMessages.push(toolMsg);
      if (result.image) images.push(result.image);
    }
    if (images.length) {
      const imgMsg = { role: 'user', content: [{ type: 'text', text: '[Автоматически] Скриншот экрана после действия:' }, ...images.map((url) => ({ type: 'image_url', image_url: { url } }))] };
      messages.push(imgMsg); // картинку не сохраняем в историю, чтобы не раздувать её
    }
  }
  return { text: finalText || 'Я сделала много шагов подряд и остановилась, чтобы не зациклиться. Продолжить?', newMessages, steps: maxSteps, truncated: true };
}

/** Список моделей OpenRouter. */
async function listModels({ fetchImpl = fetch, baseUrl, apiKey } = {}) {
  const res = await fetchImpl(baseUrl ? baseUrl.replace(/\/$/, '') + '/models' : MODELS_URL, apiKey ? { headers: { Authorization: `Bearer ${apiKey}` } } : undefined);
  if (!res.ok) throw new Error(`Не удалось получить список моделей (${res.status})`);
  const j = await res.json();
  return (j.data || []).map((m) => ({
    id: m.id,
    name: m.name || m.id,
    context: m.context_length || 0,
    tools: Array.isArray(m.supported_parameters) ? m.supported_parameters.includes('tools') : false,
    vision: Array.isArray(m.architecture?.input_modalities) ? m.architecture.input_modalities.includes('image') : /vision|image/.test(m.architecture?.modality || ''),
    promptPrice: Number(m.pricing?.prompt || 0) * 1e6,
    completionPrice: Number(m.pricing?.completion || 0) * 1e6,
    free: Number(m.pricing?.prompt || 0) === 0 && Number(m.pricing?.completion || 0) === 0,
  })).sort((a, b) => a.id.localeCompare(b.id));
}

/** Обрезает историю под контекст: оставляет последние N сообщений, не разрывая пары tool_calls/tool. */
function trimHistory(history, maxMessages = 40) {
  if (history.length <= maxMessages) return history.slice();
  let start = history.length - maxMessages;
  while (start < history.length && history[start].role === 'tool') start++;
  return history.slice(start);
}

module.exports = { SSEParser, mergeToolCallDeltas, safeJson, describeHttpError, streamChat, runAgent, listModels, trimHistory, OPENROUTER_URL };

// Минимальный клиент Groq API (OpenAI-совместимый): чат, распознавание голоса.
// Повторы при перегрузке (429/5xx) и переход на запасные модели.

export class GroqError extends Error {
  constructor(message, { status = 0, code = '', retryAfterMs = 0 } = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.retryAfterMs = retryAfterMs;
  }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function retryAfter(headers) {
  const raw = headers.get('retry-after');
  if (!raw) return 0;
  const seconds = Number(raw);
  if (Number.isFinite(seconds)) return seconds * 1000;
  const date = Date.parse(raw);
  return Number.isNaN(date) ? 0 : Math.max(0, date - Date.now());
}

// Параметры рассуждений отличаются у разных семейств моделей
export function reasoningParams(model, effort) {
  if (model.startsWith('openai/gpt-oss')) {
    return { include_reasoning: false, reasoning_effort: effort || 'medium' };
  }
  if (/qwen3/i.test(model)) {
    return effort === 'none' ? { reasoning_effort: 'none' } : { reasoning_format: 'hidden' };
  }
  return {};
}

export class GroqClient {
  constructor({ apiKey, baseUrl = 'https://api.groq.com/openai/v1', timeoutMs = 60000, logger, fetchImpl }) {
    this.apiKey = apiKey;
    this.baseUrl = baseUrl;
    this.timeoutMs = timeoutMs;
    this.logger = logger;
    this.fetch = fetchImpl || globalThis.fetch;
    this.authBroken = false;
  }

  async post(path, body, { isForm = false } = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await this.fetch(`${this.baseUrl}${path}`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${this.apiKey}`,
          ...(isForm ? {} : { 'Content-Type': 'application/json' }),
        },
        body: isForm ? body : JSON.stringify(body),
        signal: controller.signal,
      });
      const text = await response.text();
      let json = null;
      try {
        json = text ? JSON.parse(text) : null;
      } catch {
        json = null;
      }
      if (!response.ok) {
        const err = json?.error || {};
        throw new GroqError(err.message || `Groq HTTP ${response.status}`, {
          status: response.status,
          code: err.code || err.type || '',
          retryAfterMs: retryAfter(response.headers),
        });
      }
      return json;
    } catch (error) {
      if (error instanceof GroqError) throw error;
      if (error.name === 'AbortError') throw new GroqError(`Groq не ответил за ${this.timeoutMs / 1000} с`, { status: 0, code: 'timeout' });
      throw new GroqError(`Нет связи с Groq: ${error.cause?.code || error.message}`, { status: 0, code: 'network' });
    } finally {
      clearTimeout(timer);
    }
  }

  // Выполнить запрос с повторами; при недоступности модели — следующая из списка
  async withFallback(models, run) {
    if (!this.apiKey) throw new GroqError('GROQ_API_KEY не задан', { status: 401, code: 'no_key' });
    let lastError;
    for (const model of [...new Set(models.filter(Boolean))]) {
      for (let attempt = 0; attempt < 3; attempt += 1) {
        try {
          const result = await run(model);
          this.authBroken = false;
          return result;
        } catch (error) {
          lastError = error;
          if (!(error instanceof GroqError)) throw error;
          if (error.status === 401 || error.status === 403) {
            this.authBroken = true;
            throw error;
          }
          // модель выключена/не найдена/слишком большой запрос — пробуем следующую
          if (error.status === 404 || error.status === 413 || /decommission|not.?found|does not exist|model_not_active/i.test(`${error.code} ${error.message}`)) {
            this.logger?.warn({ model, err: error.message }, 'Модель Groq недоступна — пробую запасную');
            break;
          }
          const retryable = error.status === 429 || error.status >= 500 || error.status === 0;
          if (!retryable) break;
          if (attempt === 2) break;
          const wait = error.retryAfterMs > 0 ? error.retryAfterMs : 1500 * 2 ** attempt;
          if (wait > 20000) break; // долгий лимит — сразу на запасную модель
          await sleep(wait);
        }
      }
    }
    throw lastError;
  }

  async chat({ model, fallbacks = [], messages, maxTokens = 1500, temperature = 0.4, json = false, reasoningEffort }) {
    return this.withFallback([model, ...fallbacks], async (current) => {
      const body = {
        model: current,
        messages,
        temperature,
        max_completion_tokens: maxTokens,
        ...reasoningParams(current, reasoningEffort),
        ...(json ? { response_format: { type: 'json_object' } } : {}),
      };
      const data = await this.post('/chat/completions', body);
      const choice = data?.choices?.[0];
      const text = (choice?.message?.content || '').replace(/<think>[\s\S]*?<\/think>/gi, '').trim();
      if (!text) throw new GroqError('Пустой ответ модели', { status: 502, code: 'empty' });
      return { text, model: current, usage: data.usage, finishReason: choice.finish_reason };
    });
  }

  async transcribe(buffer, { model, filename = 'voice.ogg', mimetype = 'audio/ogg', prompt = '', language = '' }) {
    return this.withFallback([model, 'whisper-large-v3'], async (current) => {
      const form = new FormData();
      form.append('file', new Blob([buffer], { type: mimetype.split(';')[0] }), filename);
      form.append('model', current);
      form.append('response_format', 'json');
      form.append('temperature', '0');
      if (prompt) form.append('prompt', prompt.slice(0, 800));
      if (language) form.append('language', language);
      const data = await this.post('/audio/transcriptions', form, { isForm: true });
      return (data?.text || '').trim();
    });
  }
}

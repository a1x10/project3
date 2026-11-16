// Кто «думает»: для каждой роли — свой провайдер и модель.
//   chat       — ответы на вопросы;
//   understand — понимание сообщений чата (о чём, кому, что сделать);
//   vision     — фото заданий.
// Если выбранный провайдер не ответил (нет ключа, лимит, сбой) — пробуем другой, затем запасной ИИ.
import { GroqError } from './groq.js';

export const ROLES = ['chat', 'understand', 'vision'];
export const PROVIDER_NAMES = { groq: 'Groq', openrouter: 'OpenRouter', backup: 'запасной ИИ' };

// Картинки запасному ИИ не отправляем (не все модели их понимают) — только текст
export function textOnly(messages) {
  return messages.map((m) => (Array.isArray(m.content)
    ? { ...m, content: `${m.content.filter((c) => c.type === 'text').map((c) => c.text).join('\n')}\n(К сообщению было приложено фото, но сейчас я его не вижу.)` }
    : m));
}

export class AiRouter {
  // clients: { groq, openrouter } — GroqClient или любой объект с chat() и hasKey
  constructor({ config, clients = {}, backup = null, logger }) {
    this.config = config;
    this.clients = clients;
    this.backup = backup;
    this.logger = logger;
    this.last = {}; // роль → { provider, model, at, ms }
    this.stats = {}; // провайдер → { ok, fail, lastError, lastOkAt }
  }

  hasKey(provider) {
    const client = this.clients[provider];
    if (!client) return false;
    return client.hasKey ?? true;
  }

  get anyKey() {
    return this.hasKey('groq') || this.hasKey('openrouter') || Boolean(this.backup?.client());
  }

  defaultModel(provider, role) {
    const c = this.config;
    if (provider === 'groq') return { chat: c.groq.model, understand: c.groq.fastModel, vision: c.groq.visionModel }[role];
    return { chat: c.openrouter.model, understand: c.openrouter.understandModel, vision: c.openrouter.visionModel }[role];
  }

  // Провайдер, выбранный для роли (auto → OpenRouter, если есть ключ, иначе Groq)
  preferred(role) {
    const route = this.config.ai.routing?.[role] || { provider: 'auto' };
    if (route.provider && route.provider !== 'auto') return route.provider;
    return this.hasKey('openrouter') ? 'openrouter' : 'groq';
  }

  // Порядок попыток для роли
  plan(role) {
    const route = this.config.ai.routing?.[role] || {};
    const first = this.preferred(role);
    return [first, ...['openrouter', 'groq'].filter((p) => p !== first)]
      .filter((p) => this.hasKey(p))
      .map((provider) => ({
        provider,
        client: this.clients[provider],
        model: (provider === first && route.model) || this.defaultModel(provider, role),
        fallbacks: provider === 'groq' && role !== 'vision' ? this.config.groq.fallbackModels : [],
      }));
  }

  note(provider, ok, error) {
    const s = (this.stats[provider] ??= { ok: 0, fail: 0, lastError: null, lastOkAt: null, lastErrorAt: null });
    if (ok) {
      s.ok += 1;
      s.lastOkAt = Date.now();
    } else {
      s.fail += 1;
      s.lastError = String(error?.message || error).slice(0, 200);
      s.lastErrorAt = Date.now();
    }
  }

  // Запрос к ИИ для роли. params — как у GroqClient.chat (model выбирается здесь)
  async chat(role, params) {
    let lastError = null;
    const started = Date.now();
    for (const attempt of this.plan(role)) {
      try {
        const result = await attempt.client.chat({ ...params, model: attempt.model, fallbacks: attempt.fallbacks });
        this.note(attempt.provider, true);
        this.last[role] = { provider: attempt.provider, model: result.model || attempt.model, at: Date.now(), ms: Date.now() - started };
        return { ...result, provider: attempt.provider };
      } catch (error) {
        lastError = error;
        this.note(attempt.provider, false, error);
        if (!(error instanceof GroqError)) throw error;
        this.logger?.warn({ provider: attempt.provider, model: attempt.model, role, err: error.message }, 'ИИ не ответил — пробую следующий');
      }
    }
    const backup = this.backup?.client();
    if (backup) {
      try {
        const result = await backup.client.chat({ ...params, model: backup.model, fallbacks: [], messages: textOnly(params.messages) });
        this.note('backup', true);
        this.last[role] = { provider: 'backup', model: backup.model, at: Date.now(), ms: Date.now() - started };
        return { ...result, provider: 'backup', viaBackup: true };
      } catch (error) {
        this.note('backup', false, error);
        lastError = error;
      }
    }
    throw lastError || new GroqError('Нет ни одного ключа ИИ — добавьте ключ OpenRouter или Groq в панели', { status: 401, code: 'no_key' });
  }

  // Для панели: что выбрано и как работает
  status() {
    return {
      providers: {
        groq: { hasKey: this.hasKey('groq') },
        openrouter: { hasKey: this.hasKey('openrouter') },
        backup: { hasKey: Boolean(this.backup?.client()) },
      },
      roles: Object.fromEntries(ROLES.map((role) => {
        const plan = this.plan(role);
        return [role, {
          provider: plan[0]?.provider || null,
          model: plan[0]?.model || null,
          fallback: plan.slice(1).map((p) => `${PROVIDER_NAMES[p.provider]}: ${p.model}`),
          last: this.last[role] || null,
        }];
      })),
      stats: this.stats,
    };
  }
}

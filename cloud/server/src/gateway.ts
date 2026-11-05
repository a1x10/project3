import type http from 'node:http';
import type { Auth } from './auth.js';
import type { Config } from './config.js';
import type { Plan, Store, User } from './db.js';
import { HttpError, readBody, sendError, sendJson, type Req } from './http.js';
import type { Upstream } from './upstream.js';

export interface GatewaySettings {
  systemPrompt: string;
  promptMode: 'prepend' | 'off';
  defaultModel: string;
  /** Empty = every upstream model is allowed. */
  allowedModels: string[];
}

export function gatewaySettings(store: Store, cfg: Config): GatewaySettings {
  return {
    systemPrompt: store.getSetting('system_prompt', cfg.defaultSystemPrompt),
    promptMode: store.getSetting('prompt_mode', 'prepend'),
    defaultModel: store.getSetting('default_model', cfg.defaultModel),
    // Locked to the default model unless the owner lists other models in the admin panel.
    allowedModels: store.getSetting('allowed_models', [cfg.defaultModel] as string[]),
  };
}

export function limitStatus(store: Store, user: User): { ok: boolean; reason?: string; plan: Plan; usage: { requests: number; tokens: number } } {
  const plans = store.plans();
  const plan = plans[user.plan] ?? plans.free ?? { name: user.plan, dailyRequests: 0, dailyTokens: 0 };
  const usage = store.usageToday(user.id);
  if (user.role === 'admin') return { ok: true, plan, usage };
  if (plan.dailyRequests !== null && usage.requests >= plan.dailyRequests) return { ok: false, reason: `Дневной лимит запросов исчерпан (${plan.dailyRequests} на тарифе ${plan.name}).`, plan, usage };
  if (plan.dailyTokens !== null && usage.tokens >= plan.dailyTokens) return { ok: false, reason: `Дневной лимит токенов исчерпан (${plan.dailyTokens} на тарифе ${plan.name}).`, plan, usage };
  return { ok: true, plan, usage };
}

/** Put the owner's system prompt first; merge with a client system message if there is one. */
export function injectPrompt(messages: any[], s: GatewaySettings): any[] {
  if (s.promptMode === 'off' || !s.systemPrompt.trim() || !Array.isArray(messages)) return messages;
  const out = [...messages];
  const firstSystem = out.findIndex((m) => m?.role === 'system' || m?.role === 'developer');
  if (firstSystem === 0) {
    const m = out[0];
    const clientText = typeof m.content === 'string' ? m.content : Array.isArray(m.content) ? m.content.map((p: any) => p?.text ?? '').join('\n') : '';
    out[0] = { ...m, role: 'system', content: `${s.systemPrompt.trim()}\n\n${clientText}`.trim() };
    return out;
  }
  return [{ role: 'system', content: s.systemPrompt.trim() }, ...out];
}

export class Gateway {
  constructor(
    private readonly cfg: Config,
    private readonly store: Store,
    private readonly auth: Auth,
    private readonly upstream: Upstream,
  ) {}

  private authenticate(req: Req): User {
    const r = this.auth.resolve(req.headers.authorization);
    if (!r) throw new HttpError(401, 'Неверный или отсутствующий ключ. Войдите через Telegram-бота и получите ключ.', 'authentication_error');
    if (r.user.status !== 'active') throw new HttpError(403, 'Аккаунт заблокирован администратором.', 'permission_error');
    this.store.touch(r.user.id);
    return r.user;
  }

  async models(req: Req, res: http.ServerResponse) {
    this.authenticate(req);
    const s = gatewaySettings(this.store, this.cfg);
    let ids: string[] = [];
    try {
      ids = await this.upstream.models();
    } catch {
      ids = [];
    }
    if (s.allowedModels.length) ids = s.allowedModels;
    if (!ids.includes(s.defaultModel)) ids = [s.defaultModel, ...ids];
    sendJson(res, 200, { object: 'list', data: ids.map((id) => ({ id, object: 'model', owned_by: 'stella-cloud' })) });
  }

  async chat(req: Req, res: http.ServerResponse) {
    const user = this.authenticate(req);
    const lim = limitStatus(this.store, user);
    if (!lim.ok) throw new HttpError(429, lim.reason!, 'rate_limit_error');
    const raw = await readBody(req, this.cfg.maxBodyBytes);
    let body: any;
    try {
      body = JSON.parse(raw.toString('utf8'));
    } catch {
      throw new HttpError(400, 'Invalid JSON body');
    }
    if (!Array.isArray(body?.messages)) throw new HttpError(400, '`messages` must be an array');
    const s = gatewaySettings(this.store, this.cfg);
    const requested = typeof body.model === 'string' && body.model.trim() ? body.model.trim() : s.defaultModel;
    let model = requested === 'default' ? s.defaultModel : requested;
    // a single allowed model means "everyone uses this model": rewrite instead of refusing
    if (s.allowedModels.length === 1) model = s.allowedModels[0]!;
    if (s.allowedModels.length && !s.allowedModels.includes(model)) throw new HttpError(403, `Модель ${model} недоступна. Доступны: ${s.allowedModels.join(', ')}`, 'permission_error');
    const client = String(req.headers['x-stella-client'] ?? '').slice(0, 30) || undefined;
    const upstreamBody = { ...body, model, messages: injectPrompt(body.messages, s) };
    if (upstreamBody.stream) upstreamBody.stream_options = { ...(upstreamBody.stream_options ?? {}), include_usage: true };
    delete upstreamBody.user;

    const ctl = new AbortController();
    res.on('close', () => {
      if (!res.writableFinished) ctl.abort();
    });
    const send = async (refresh: boolean) =>
      fetch(`${this.upstream.baseUrl}/chat/completions`, {
        method: 'POST',
        headers: { 'content-type': 'application/json', ...(await this.upstream.headers(refresh)) },
        body: JSON.stringify(upstreamBody),
        signal: ctl.signal,
      });
    let up: Response;
    try {
      up = await send(false);
      if (up.status === 401) up = await send(true); // router key rotated
    } catch (e) {
      if (ctl.signal.aborted) return;
      this.store.recordUsage({ userId: user.id, model, client, input: 0, output: 0, status: 502 });
      throw new HttpError(502, `Сервер моделей недоступен: ${(e as Error).message}`, 'upstream_error');
    }
    const passHeaders: Record<string, string> = { 'content-type': up.headers.get('content-type') ?? 'application/json' };
    const routed = up.headers.get('x-routed-via');
    if (routed) passHeaders['x-routed-via'] = routed;
    if (lim.plan.dailyRequests !== null) passHeaders['x-ratelimit-remaining-requests'] = String(Math.max(0, lim.plan.dailyRequests - lim.usage.requests - 1));

    if (!up.ok || !up.body) {
      const text = await up.text().catch(() => '');
      this.store.recordUsage({ userId: user.id, model, client, input: 0, output: 0, status: up.status });
      res.writeHead(up.status, passHeaders);
      res.end(text || JSON.stringify({ error: { message: `upstream HTTP ${up.status}` } }));
      return;
    }

    let input = 0;
    let output = 0;
    const stream = !!upstreamBody.stream;
    res.writeHead(200, stream ? { ...passHeaders, 'cache-control': 'no-cache', 'x-accel-buffering': 'no' } : passHeaders);
    const reader = up.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    let full = '';
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        res.write(value);
        const text = decoder.decode(value, { stream: true });
        if (stream) {
          buf += text;
          let nl: number;
          while ((nl = buf.indexOf('\n')) >= 0) {
            const line = buf.slice(0, nl).trim();
            buf = buf.slice(nl + 1);
            if (!line.startsWith('data:')) continue;
            const payload = line.slice(5).trim();
            if (payload === '[DONE]') continue;
            try {
              const j = JSON.parse(payload);
              if (j.usage) {
                input = j.usage.prompt_tokens ?? input;
                output = j.usage.completion_tokens ?? output;
              }
            } catch {
              /* partial */
            }
          }
        } else if (full.length < 5_000_000) full += text;
      }
    } catch {
      /* client went away */
    }
    res.end();
    if (!stream) {
      try {
        const j = JSON.parse(full);
        input = j.usage?.prompt_tokens ?? 0;
        output = j.usage?.completion_tokens ?? 0;
      } catch {
        /* ignore */
      }
    }
    this.store.recordUsage({ userId: user.id, model, client, input, output, status: 200 });
  }

  handleError(res: http.ServerResponse, e: unknown) {
    if (e instanceof HttpError) sendError(res, e.status, e.message, e.type);
    else sendError(res, 500, (e as Error).message || 'Internal error');
  }
}

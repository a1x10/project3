import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { z } from 'zod';
import { Auth, publicUser, type Client, type LoginKind } from './auth.js';
import { Bot } from './bot.js';
import type { Config } from './config.js';
import { Store, type Plan, type User } from './db.js';
import { Gateway, gatewaySettings, limitStatus } from './gateway.js';
import { HttpError, RateLimiter, Router, applyCors, clientIp, readJson, sendJson, serveStatic, type Req } from './http.js';
import { TelegramClient } from './telegram.js';
import { Upstream } from './upstream.js';

export interface App {
  server: http.Server;
  store: Store;
  auth: Auth;
  bot: Bot | null;
  tg: TelegramClient;
  upstream: Upstream;
  /** Resolves once the Telegram bot is polling (false when disabled). */
  botReady: Promise<boolean>;
  listen(): Promise<number>;
  close(): Promise<void>;
}

const PlanSchema = z.object({ name: z.string().min(1).max(40), dailyRequests: z.number().int().min(0).nullable(), dailyTokens: z.number().int().min(0).nullable() });
const SettingsSchema = z.object({
  systemPrompt: z.string().max(100_000).optional(),
  promptMode: z.enum(['prepend', 'off']).optional(),
  defaultModel: z.string().min(1).max(200).optional(),
  allowedModels: z.array(z.string().min(1).max(200)).max(500).optional(),
  plans: z.record(z.string().regex(/^[a-z0-9_-]{1,30}$/), PlanSchema).optional(),
  defaultPlan: z.string().optional(),
});
const UserPatch = z.object({ plan: z.string().optional(), role: z.enum(['user', 'admin']).optional(), status: z.enum(['active', 'banned']).optional(), name: z.string().min(1).max(80).optional() });

export function createApp(cfg: Config, opts: { store?: Store } = {}): App {
  const store = opts.store ?? new Store(cfg.dbPath);
  const auth = new Auth(store, { sessionTtlDays: cfg.sessionTtlDays, loginTtlSec: cfg.loginTtlSec });
  const upstream = new Upstream(cfg);
  const gateway = new Gateway(cfg, store, auth, upstream);
  const tg = new TelegramClient(cfg.botToken, cfg.telegramApiUrl);
  if (cfg.botUsername) tg.username = cfg.botUsername;
  const bot = tg.enabled ? new Bot(tg, store, auth, cfg) : null;
  const authLimiter = new RateLimiter(30, 60_000);
  const router = new Router();
  let closed = false;

  const who = (req: Req): User => {
    const r = auth.resolve(req.headers.authorization);
    if (!r) throw new HttpError(401, 'Требуется вход', 'authentication_error');
    if (r.user.status !== 'active') throw new HttpError(403, 'Аккаунт заблокирован', 'permission_error');
    store.touch(r.user.id);
    return r.user;
  };
  const admin = (req: Req): User => {
    const u = who(req);
    if (u.role !== 'admin') throw new HttpError(403, 'Только для администраторов', 'permission_error');
    return u;
  };
  const botLink = (payload?: string) => (tg.username ? `https://t.me/${tg.username}${payload ? `?start=${payload}` : ''}` : null);
  const userView = (u: User) => {
    const lim = limitStatus(store, u);
    const unlimited = u.role === 'admin';
    return {
      ...publicUser(u),
      planInfo: { id: u.plan, ...lim.plan, dailyRequests: unlimited ? null : lim.plan.dailyRequests, dailyTokens: unlimited ? null : lim.plan.dailyTokens },
      usageToday: lim.usage,
    };
  };
  const downloads = () => {
    try {
      return fs
        .readdirSync(cfg.downloadsDir)
        .filter((f) => /\.(exe|msi|zip|dmg|AppImage|deb)$/i.test(f))
        .map((f) => ({ name: f, url: `/downloads/${encodeURIComponent(f)}`, size: fs.statSync(path.join(cfg.downloadsDir, f)).size }));
    } catch {
      return [];
    }
  };

  // ---------------- public
  router.get('/api/health', async (_req, res) => sendJson(res, 200, { ok: true, bot: !!bot, botUsername: tg.username || null }));
  router.get('/api/config', async (_req, res) =>
    sendJson(res, 200, { name: 'Stella Cloud', publicUrl: cfg.publicUrl, apiBase: `${cfg.publicUrl}/v1`, botUsername: tg.username || null, botLink: botLink(), downloads: downloads(), plans: store.plans() }),
  );

  // ---------------- Telegram login (device flow)
  router.post('/api/auth/start', async (req, res) => {
    if (!authLimiter.allow(clientIp(req))) throw new HttpError(429, 'Слишком много попыток, подождите минуту');
    const b = await readJson(req);
    const client: Client = ['web', 'studio', 'stella', 'other'].includes(b.client) ? b.client : 'web';
    const kind: LoginKind = b.kind === 'apikey' || (client !== 'web' && b.kind !== 'session') ? 'apikey' : 'session';
    const r = auth.startLogin(client, kind, typeof b.device === 'string' ? b.device : undefined);
    sendJson(res, 200, { id: r.id, code: r.code, expiresAt: r.expires_at, link: botLink(`login_${r.id}`), botUsername: tg.username || null, interval: 2 });
  });
  router.get('/api/auth/poll', async (req, res) => {
    const id = req.query.get('id') ?? '';
    const r = auth.poll(id);
    if (r.status !== 'approved') return sendJson(res, 200, { status: r.status });
    if (r.user.status !== 'active') return sendJson(res, 200, { status: 'denied' });
    sendJson(res, 200, { status: 'approved', token: r.token, apiKey: r.apiKey, user: userView(r.user), apiBase: `${cfg.publicUrl}/v1` });
  });
  router.post('/api/auth/logout', async (req, res) => {
    const t = (req.headers.authorization ?? '').replace(/^Bearer\s+/i, '');
    if (t.startsWith('sess_')) auth.deleteSession(t);
    else {
      // apps sign out by revoking the API key they received at login
      const r = auth.resolve(t);
      if (r?.keyId) auth.revokeKey(r.user.id, r.keyId);
    }
    sendJson(res, 200, { ok: true });
  });

  // ---------------- cabinet
  router.get('/api/me', async (req, res) => sendJson(res, 200, { user: userView(who(req)), apiBase: `${cfg.publicUrl}/v1`, botLink: botLink() }));
  router.get('/api/me/usage', async (req, res) => sendJson(res, 200, { days: store.usageDays(who(req).id, 30) }));
  router.get('/api/me/keys', async (req, res) => sendJson(res, 200, { keys: auth.listKeys(who(req).id) }));
  router.post('/api/me/keys', async (req, res) => {
    const u = who(req);
    const b = await readJson(req);
    if (auth.listKeys(u.id).length >= 50) throw new HttpError(400, 'Слишком много ключей — отзовите ненужные');
    const k = auth.createApiKey(u.id, typeof b.name === 'string' && b.name.trim() ? b.name.trim() : 'Ключ с сайта', 'web');
    sendJson(res, 200, { key: k.key, id: k.id, prefix: k.prefix });
  });
  router.delete('/api/me/keys/:id', async (req, res) => {
    const ok = auth.revokeKey(who(req).id, Number(req.params.id));
    if (!ok) throw new HttpError(404, 'Ключ не найден');
    sendJson(res, 200, { ok });
  });
  router.delete('/api/me', async (req, res) => {
    const u = who(req);
    store.deleteUser(u.id);
    sendJson(res, 200, { ok: true });
  });

  // ---------------- admin
  router.get('/api/admin/stats', async (req, res) => {
    admin(req);
    sendJson(res, 200, { stats: store.stats() });
  });
  router.get('/api/admin/users', async (req, res) => {
    admin(req);
    const limit = Math.min(200, Number(req.query.get('limit')) || 50);
    const offset = Math.max(0, Number(req.query.get('offset')) || 0);
    const { users, total } = store.listUsers({ q: req.query.get('q') ?? '', limit, offset });
    sendJson(res, 200, { total, users: users.map((u) => ({ ...publicUser(u), requestsToday: Number(u.requests_today), tokensToday: Number(u.tokens_today), keys: Number(u.keys) })) });
  });
  router.get('/api/admin/users/:id', async (req, res) => {
    admin(req);
    const u = store.userById(Number(req.params.id));
    if (!u) throw new HttpError(404, 'Пользователь не найден');
    sendJson(res, 200, { user: userView(u), keys: auth.listKeys(u.id), usage: store.usageDays(u.id, 30) });
  });
  router.patch('/api/admin/users/:id', async (req, res) => {
    const me = admin(req);
    const id = Number(req.params.id);
    if (!store.userById(id)) throw new HttpError(404, 'Пользователь не найден');
    const p = UserPatch.safeParse(await readJson(req));
    if (!p.success) throw new HttpError(400, p.error.issues[0]?.message ?? 'Неверные данные');
    if (p.data.plan && !store.plans()[p.data.plan]) throw new HttpError(400, `Нет тарифа ${p.data.plan}`);
    if (id === me.id && (p.data.status === 'banned' || p.data.role === 'user')) throw new HttpError(400, 'Нельзя заблокировать себя или снять с себя права администратора');
    const u = store.updateUser(id, p.data)!;
    if (p.data.status === 'banned') auth.revokeAllKeys(id);
    sendJson(res, 200, { user: userView(u) });
  });
  router.delete('/api/admin/users/:id', async (req, res) => {
    const me = admin(req);
    const id = Number(req.params.id);
    if (id === me.id) throw new HttpError(400, 'Нельзя удалить себя');
    if (!store.deleteUser(id)) throw new HttpError(404, 'Пользователь не найден');
    sendJson(res, 200, { ok: true });
  });
  router.post('/api/admin/users/:id/revoke-keys', async (req, res) => {
    admin(req);
    sendJson(res, 200, { revoked: auth.revokeAllKeys(Number(req.params.id)) });
  });
  router.delete('/api/admin/keys/:id', async (req, res) => {
    admin(req);
    sendJson(res, 200, { ok: auth.revokeKey(null, Number(req.params.id)) });
  });
  router.get('/api/admin/settings', async (req, res) => {
    admin(req);
    sendJson(res, 200, { ...gatewaySettings(store, cfg), plans: store.plans(), defaultPlan: store.getSetting('default_plan', 'free') });
  });
  router.put('/api/admin/settings', async (req, res) => {
    admin(req);
    const p = SettingsSchema.safeParse(await readJson(req, 2_000_000));
    if (!p.success) throw new HttpError(400, p.error.issues.map((i) => `${i.path.join('.')}: ${i.message}`).join('; '));
    const d = p.data;
    if (d.systemPrompt !== undefined) store.setSetting('system_prompt', d.systemPrompt);
    if (d.promptMode) store.setSetting('prompt_mode', d.promptMode);
    if (d.defaultModel) store.setSetting('default_model', d.defaultModel);
    if (d.allowedModels) store.setSetting('allowed_models', d.allowedModels);
    if (d.plans) {
      if (!Object.keys(d.plans).length) throw new HttpError(400, 'Нужен хотя бы один тариф');
      store.setSetting('plans', d.plans as Record<string, Plan>);
    }
    if (d.defaultPlan) {
      if (!store.plans()[d.defaultPlan]) throw new HttpError(400, `Нет тарифа ${d.defaultPlan}`);
      store.setSetting('default_plan', d.defaultPlan);
    }
    sendJson(res, 200, { ...gatewaySettings(store, cfg), plans: store.plans(), defaultPlan: store.getSetting('default_plan', 'free') });
  });
  router.get('/api/admin/upstream', async (req, res) => {
    admin(req);
    const h = await upstream.health();
    let models: string[] = [];
    if (h.ok) models = await upstream.models().catch(() => []);
    sendJson(res, 200, { baseUrl: upstream.baseUrl, routerUrl: cfg.routerUrl || null, ...h, modelIds: models.slice(0, 500) });
  });

  // ---------------- OpenAI-compatible gateway
  router.get('/v1/models', (req, res) => gateway.models(req, res));
  router.post('/v1/chat/completions', (req, res) => gateway.chat(req, res));

  const server = http.createServer(async (rawReq, res) => {
    const url = new URL(rawReq.url ?? '/', 'http://x');
    const req = Object.assign(rawReq, { pathname: url.pathname, query: url.searchParams, params: {} }) as Req;
    const isApi = url.pathname.startsWith('/api/') || url.pathname.startsWith('/v1/');
    if (isApi) applyCors(req, res);
    if (req.method === 'OPTIONS') {
      res.writeHead(204);
      return res.end();
    }
    try {
      const m = router.match(req.method ?? 'GET', url.pathname);
      if (m) {
        req.params = m.params;
        await m.handler(req, res);
        return;
      }
      if (isApi) throw new HttpError(404, 'Not found');
      if (req.method === 'GET' && url.pathname.startsWith('/downloads/')) {
        const name = path.basename(decodeURIComponent(url.pathname.slice('/downloads/'.length)));
        const file = path.join(cfg.downloadsDir, name);
        if (name && fs.existsSync(file) && fs.statSync(file).isFile()) {
          res.writeHead(200, { 'content-type': 'application/octet-stream', 'content-disposition': `attachment; filename="${name.replace(/"/g, '')}"`, 'content-length': fs.statSync(file).size });
          fs.createReadStream(file).pipe(res);
          return;
        }
        throw new HttpError(404, 'Файл не найден');
      }
      if ((req.method === 'GET' || req.method === 'HEAD') && serveStatic(cfg.webDir, url.pathname, res)) return;
      res.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' });
      res.end('Stella Cloud: сайт не собран (cloud/web → npm run build).');
    } catch (e) {
      if (!(e instanceof HttpError)) console.error('[http]', req.method, url.pathname, e);
      gateway.handleError(res, e);
    }
  });
  server.requestTimeout = 0; // long streaming completions
  server.headersTimeout = 60_000;

  return {
    server,
    store,
    auth,
    bot,
    tg,
    upstream,
    async listen() {
      await new Promise<void>((resolve) => server.listen(cfg.port, cfg.host, resolve));
      if (bot) {
        this.botReady = (async () => {
          for (let attempt = 0; !closed; attempt++) {
            try {
              await tg.init();
              console.log(`[bot] @${tg.username} запущен`);
              bot.start();
              return true;
            } catch (e) {
              console.error('[bot] не удалось запустить Telegram-бота:', (e as Error).message, '— повтор через 30 с');
              await new Promise((r) => setTimeout(r, attempt ? 30_000 : 5_000).unref());
            }
          }
          return false;
        })();
      }
      const addr = server.address();
      return typeof addr === 'object' && addr ? addr.port : cfg.port;
    },
    botReady: Promise.resolve(false),
    async close() {
      closed = true;
      tg.stop();
      await new Promise<void>((r) => {
        server.close(() => r());
        server.closeAllConnections();
      });
      store.close();
    },
  };
}

// Веб-сервер бота: сайт с презентацией, панель управления (API + живые события), /health и /qr.
// Без внешних зависимостей: свой маленький роутер, статика из web/, Three.js из node_modules.
//
// Безопасность: панель — только после входа (HttpOnly-кука, SameSite=Strict), изменяющие запросы требуют
// служебный заголовок и совпадение Origin (защита от CSRF), жёсткая CSP, лимит размера запросов,
// секреты наружу только маской. По умолчанию порт открыт лишь на самом сервере (127.0.0.1) — заходите через
// SSH-туннель или HTTPS-прокси (см. README).
import { createHash, timingSafeEqual } from 'node:crypto';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import zlib from 'node:zlib';
import { BilimAuthError, BilimClassClient } from '../bilimclass/client.js';
import { ConfigError } from '../config.js';
import { HomeworkPhotos } from '../homework/message.js';
import { contentSummary } from '../inbox.js';
import { mask } from '../secrets.js';
import { addDays, formatClock, mondayOf, nowParts, parseDayArg } from '../utils/dates.js';
import { Terminal } from './console.js';

const MIME = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.ico': 'image/x-icon',
  '.ttf': 'font/ttf', '.woff2': 'font/woff2', '.txt': 'text/plain; charset=utf-8', '.webmanifest': 'application/manifest+json',
};
const COMPRESSIBLE = new Set(['.html', '.js', '.mjs', '.css', '.json', '.svg', '.txt', '.webmanifest']);
const MAX_BODY = 64 * 1024;
const COOKIE = 'hwb_session';
const SSE_LIMIT = 20;

class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function tokenOk(provided, expected) {
  if (!expected || !provided) return false;
  const a = Buffer.from(String(provided));
  const b = Buffer.from(expected);
  return a.length === b.length && timingSafeEqual(a, b);
}

const qrPage = (title, body, refresh) => `<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">${refresh ? `<meta http-equiv="refresh" content="${refresh}">` : ''}
<title>${title}</title><style>body{font-family:system-ui,sans-serif;max-width:520px;margin:40px auto;padding:0 16px;text-align:center;color:#222}
img{width:100%;max-width:360px;image-rendering:pixelated}code{font-size:28px;letter-spacing:3px}</style></head><body>${body}</body></html>`;

// Файлы, которые можно отдавать: всё из web/, шрифты и Three.js (только .js)
function staticTable(root) {
  const table = new Map();
  const walk = (dir, prefix) => {
    if (!fs.existsSync(dir)) return;
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full, `${prefix}${entry.name}/`);
      else if (MIME[path.extname(entry.name)]) table.set(`${prefix}${entry.name}`, full);
    }
  };
  walk(path.join(root, 'web'), '/');
  for (const name of ['NotoSans-Regular.ttf', 'NotoSans-Bold.ttf']) table.set(`/fonts/${name}`, path.join(root, 'assets', 'fonts', name));
  table.set('/', path.join(root, 'web', 'index.html'));
  table.set('/app', path.join(root, 'web', 'app.html'));
  return table;
}

function threeDir(root) {
  const candidates = [path.join(root, 'node_modules', 'three')];
  return candidates.find((dir) => fs.existsSync(path.join(dir, 'build', 'three.module.min.js'))) || null;
}

// SHA-256 встроенного importmap — чтобы разрешить его в CSP без 'unsafe-inline'
function importMapHashes(files) {
  const hashes = new Set();
  for (const file of files) {
    try {
      const html = fs.readFileSync(file, 'utf8');
      for (const m of html.matchAll(/<script type="importmap">([\s\S]*?)<\/script>/g)) {
        hashes.add(`'sha256-${createHash('sha256').update(m[1]).digest('base64')}'`);
      }
    } catch {
      /* страницы может не быть */
    }
  }
  return [...hashes].join(' ');
}

export function startWebServer(app) {
  const { config, logger, wa, homework, core, auth } = app;
  if (!config.http.port) return null;
  const root = config.root;
  const files = staticTable(root);
  const three = threeDir(root);
  const cache = new Map(); // path -> { etag, body, gzip, type, mtime }
  const csp = [
    "default-src 'self'",
    `script-src 'self' ${importMapHashes([files.get('/'), files.get('/app')])}`.trim(),
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join('; ');
  const terminal = new Terminal(app);
  const version = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8')).version;
  const sse = new Set();
  const trustProxy = Boolean(config.panel.trustProxy);

  const clientIp = (req) => {
    const fwd = trustProxy ? String(req.headers['x-forwarded-for'] || '').split(',')[0].trim() : '';
    return fwd || req.socket.remoteAddress?.replace(/^::ffff:/, '') || '';
  };
  const isHttps = (req) => (trustProxy && req.headers['x-forwarded-proto'] === 'https') || config.panel.publicUrl.startsWith('https://');

  function securityHeaders(res, extra = {}) {
    res.setHeader('Content-Security-Policy', csp);
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('X-Frame-Options', 'DENY');
    res.setHeader('Referrer-Policy', 'no-referrer');
    res.setHeader('Permissions-Policy', 'camera=(), microphone=(), geolocation=(), payment=()');
    res.setHeader('Cross-Origin-Opener-Policy', 'same-origin');
    for (const [k, v] of Object.entries(extra)) res.setHeader(k, v);
  }

  function json(res, status, data) {
    const body = JSON.stringify(data);
    res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
    res.end(body);
  }

  function cookies(req) {
    const out = {};
    for (const part of String(req.headers.cookie || '').split(';')) {
      const i = part.indexOf('=');
      if (i > 0) out[part.slice(0, i).trim()] = decodeURIComponent(part.slice(i + 1).trim());
    }
    return out;
  }

  function setSession(req, res, token) {
    const flags = ['HttpOnly', 'SameSite=Strict', 'Path=/', `Max-Age=${30 * 24 * 3600}`, ...(isHttps(req) ? ['Secure'] : [])];
    res.setHeader('Set-Cookie', `${COOKIE}=${token}; ${flags.join('; ')}`);
  }

  function clearSession(res) {
    res.setHeader('Set-Cookie', `${COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0`);
  }

  async function readBody(req) {
    const chunks = [];
    let size = 0;
    for await (const chunk of req) {
      size += chunk.length;
      if (size > MAX_BODY) throw new HttpError(413, 'Слишком большой запрос');
      chunks.push(chunk);
    }
    if (!size) return {};
    try {
      return JSON.parse(Buffer.concat(chunks).toString('utf8'));
    } catch {
      throw new HttpError(400, 'Неверный JSON');
    }
  }

  // Изменяющий запрос — только со своей страницы (заголовок + Origin)
  function checkCsrf(req) {
    if (req.headers['x-hwb'] !== '1') throw new HttpError(403, 'Запрос отклонён (CSRF)');
    const origin = req.headers.origin;
    if (origin) {
      let host;
      try {
        host = new URL(origin).host;
      } catch {
        throw new HttpError(403, 'Запрос отклонён (Origin)');
      }
      const allowed = [req.headers.host, req.headers['x-forwarded-host']].filter(Boolean);
      if (!allowed.includes(host)) throw new HttpError(403, 'Запрос отклонён (Origin)');
    }
  }

  // --- статика ---
  function serveStatic(req, res, urlPath) {
    let file = files.get(urlPath);
    let vendor = false;
    if (!file && three && urlPath.startsWith('/vendor/three/')) {
      const rel = urlPath.slice('/vendor/three/'.length);
      const base = rel.startsWith('addons/') ? path.join(three, 'examples', 'jsm') : path.join(three, 'build');
      const target = path.resolve(base, rel.startsWith('addons/') ? rel.slice('addons/'.length) : rel);
      if (target.startsWith(base + path.sep) && target.endsWith('.js') && fs.existsSync(target)) {
        file = target;
        vendor = true;
      }
    }
    if (!file) return false;
    let stat;
    try {
      stat = fs.statSync(file);
    } catch {
      return false;
    }
    const ext = path.extname(file) || '.html';
    let entry = cache.get(file);
    if (!entry || entry.mtime !== stat.mtimeMs) {
      const body = fs.readFileSync(file);
      entry = {
        mtime: stat.mtimeMs,
        body,
        gzip: COMPRESSIBLE.has(ext) && body.length > 1024 ? zlib.gzipSync(body, { level: 7 }) : null,
        etag: `"${createHash('sha1').update(body).digest('base64url').slice(0, 20)}"`,
        type: MIME[ext] || 'application/octet-stream',
      };
      cache.set(file, entry);
    }
    const isHtml = ext === '.html';
    securityHeaders(res);
    res.setHeader('ETag', entry.etag);
    res.setHeader('Cache-Control', isHtml ? 'no-cache' : vendor || urlPath.startsWith('/fonts/') ? 'public, max-age=604800, immutable' : 'public, max-age=300');
    if (req.headers['if-none-match'] === entry.etag) {
      res.writeHead(304);
      res.end();
      return true;
    }
    const gzip = entry.gzip && /\bgzip\b/.test(String(req.headers['accept-encoding'] || ''));
    res.writeHead(200, { 'Content-Type': entry.type, ...(gzip ? { 'Content-Encoding': 'gzip', Vary: 'Accept-Encoding' } : {}) });
    res.end(req.method === 'HEAD' ? undefined : gzip ? entry.gzip : entry.body);
    return true;
  }

  // --- данные для панели ---
  function overview() {
    const s = homework.status();
    const today = homework.today();
    const plan = app.scheduler.plan;
    const usage = core.store.data.usage;
    const stats = [];
    for (let i = 13; i >= 0; i -= 1) {
      const date = addDays(today, -i);
      const u = usage[date] || {};
      stats.push({ date, ai: u.ai || 0, dm: u.dm || 0, digest: u.digest || 0, voice: u.voice || 0, vision: u.vision || 0 });
    }
    const keyInUse = app.keys.list().find((k) => k.inUse);
    const diaryStatus = app.diary.status();
    return {
      bot: { name: config.ai.botName, version, startedAt: core.startedAt, now: Date.now(), timezone: config.timezone, memoryMb: Math.round(process.memoryUsage().rss / 1048576) },
      whatsapp: { ...wa.info(), qr: undefined, hasQr: Boolean(wa.qr) },
      bilim: {
        ok: !s.lastError, error: s.lastError, lastSyncAt: s.lastSuccessAt || null, mode: diaryStatus.mode, siteAvailable: diaryStatus.siteAvailable,
        loggedIn: app.bilim.loggedIn, className: s.session?.className || '', schoolName: s.session?.schoolName || '', fullName: s.session?.fullName || '',
      },
      ai: {
        enabled: app.assistant.enabled, mode: config.ai.mode, provider: app.assistant.lastProvider, key: keyInUse?.label || null,
        keys: app.keys.list().length, backup: app.backup.describe().enabled, today: usage[today]?.ai || 0, dailyLimit: config.ai.dailyLimit,
      },
      digest: {
        today: plan?.date === today ? { at: plan.at != null ? formatClock(plan.at) : null, lessonsEnd: plan.lessonsEnd != null ? formatClock(plan.lessonsEnd) : null, source: plan.source, quiet: plan.quiet, scope: plan.scope } : null,
        sentToday: core.store.data.jobs.digest === today,
        last: core.store.data.jobs.digest || null,
        week: app.scheduler.weekPlanLines(),
        pausedUntil: config.schedule.pausedUntil,
      },
      groups: core.targets().map((jid) => ({ jid, name: core.store.data.groups[jid]?.name || jid, ...core.groupSettings(jid) })),
      stats,
      inbox: { unread: app.inbox.unreadTotal(), chats: app.inbox.list().length },
      alerts: (core.store.data.alertLog || []).slice(0, 8),
      queue: wa.queue.length,
    };
  }

  function lessonOut(l) {
    return { subject: l.subject, start: l.start || '', end: l.end || '', room: l.room || l.cabinet || '', theme: l.theme || '' };
  }
  function entryOut(e) {
    return { key: e.key, subject: e.subject, text: e.text || '', books: e.books || [], hasFiles: Boolean(e.hasFiles), manual: Boolean(e.manual), id: e.id ?? null, author: e.author || '' };
  }

  function contentFor(view, today) {
    const photos = new HomeworkPhotos({ config, screenshotter: app.siteBrowser?.available ? app.siteBrowser : null, logger, className: () => app.bilim.session?.className });
    return photos.messages([view], today).then((list) => list[0]);
  }

  // --- маршруты API ---
  const routes = [];
  const route = (method, pattern, handler, { auth: needAuth = true } = {}) => routes.push({ method, pattern, handler, needAuth });

  route('GET', /^\/api\/public\/status$/, () => ({ online: wa.isOpen, name: config.ai.botName }), { auth: false });
  route('GET', /^\/api\/auth\/me$/, ({ session }) => ({ authenticated: Boolean(session), methods: auth.methods(), session: session ? { method: session.method, createdAt: session.createdAt } : null }), { auth: false });
  route('POST', /^\/api\/auth\/login$/, ({ body, req, res, meta }) => {
    const result = auth.loginPassword(body.password, meta);
    if (result.error) throw new HttpError(result.status, result.error);
    setSession(req, res, result.token);
    return { ok: true };
  }, { auth: false });
  route('POST', /^\/api\/auth\/code$/, ({ meta }) => {
    const result = auth.requestCode(meta);
    if (result.error) throw new HttpError(result.status, result.error);
    return result;
  }, { auth: false });
  route('POST', /^\/api\/auth\/code\/verify$/, ({ body, req, res, meta }) => {
    const result = auth.loginCode(body.code, meta);
    if (result.error) throw new HttpError(result.status, result.error);
    setSession(req, res, result.token);
    return { ok: true };
  }, { auth: false });
  route('POST', /^\/api\/auth\/logout$/, ({ res, token }) => {
    auth.logout(token);
    clearSession(res);
    return { ok: true };
  }, { auth: false });

  route('GET', /^\/api\/overview$/, () => overview());
  route('GET', /^\/api\/logs$/, ({ url }) => ({ items: app.logBuffer.recent(Math.min(Number(url.searchParams.get('limit')) || 200, 1500), url.searchParams.get('level') || 'info') }));
  route('POST', /^\/api\/console$/, async ({ body, session }) => ({ output: await terminal.run(String(body.command || '').slice(0, 2000), { session }) }));

  // проверка ИИ из панели
  route('POST', /^\/api\/ai\/ask$/, async ({ body }) => {
    const question = String(body.question || '').trim().slice(0, 2000);
    if (!question) throw new HttpError(400, 'Напишите вопрос');
    if (!app.assistant.enabled) throw new HttpError(400, 'ИИ выключен или нет рабочего ключа — проверьте «Ключи и доступ»');
    const started = Date.now();
    const answer = await app.assistant.answer({ question, senderName: 'Админ', isPrivate: true });
    return { answer, ms: Date.now() - started, provider: app.assistant.lastProvider };
  });

  // настройки
  route('GET', /^\/api\/settings$/, () => ({ fields: app.settings.describe() }));
  route('PUT', /^\/api\/settings$/, ({ body }) => {
    const changed = app.settings.update(body.values || {}, { by: 'panel' });
    return { changed, fields: app.settings.describe() };
  });
  route('POST', /^\/api\/settings\/reset$/, ({ body }) => ({ changed: app.settings.reset(body.paths), fields: app.settings.describe() }));

  // переписка
  route('GET', /^\/api\/chats$/, () => ({ chats: app.inbox.list(), unread: app.inbox.unreadTotal() }));
  route('GET', /^\/api\/chats\/([^/]+)$/, ({ params }) => {
    const chat = app.inbox.get(params[0]);
    if (!chat) throw new HttpError(404, 'Чат не найден');
    app.inbox.markRead(params[0]);
    return chat;
  });
  route('POST', /^\/api\/chats\/([^/]+)\/send$/, async ({ params, body }) => {
    const text = String(body.text || '').trim();
    if (!text) throw new HttpError(400, 'Пустое сообщение');
    if (text.length > 4000) throw new HttpError(400, 'Сообщение слишком длинное');
    if (!wa.isOpen) throw new HttpError(503, 'WhatsApp сейчас не на связи — сообщение уйдёт, когда он подключится');
    app.inbox.takeover(params[0]);
    wa.sendText(params[0], text, { meta: { by: 'admin' }, maxAgeMs: 3600 * 1000 }).catch(() => {});
    return { ok: true };
  });
  route('POST', /^\/api\/chats\/([^/]+)\/ai$/, ({ params, body }) => {
    app.inbox.setAi(params[0], body.state);
    return { ok: true, ai: app.inbox.aiState(params[0]) };
  });
  route('POST', /^\/api\/chats\/([^/]+)\/homework$/, async ({ params, body }) => {
    const today = homework.today();
    const date = body.date ? parseDayArg(String(body.date), today) : (await homework.nextSchoolDay(today)) || addDays(today, 1);
    if (!date) throw new HttpError(400, 'Неверная дата');
    const content = await contentFor(await homework.dayView(date, { fresh: true }), today);
    wa.send(params[0], content, {}, { meta: { by: 'admin' }, maxAgeMs: 3600 * 1000 }).catch(() => {});
    return { ok: true, date };
  });
  route('DELETE', /^\/api\/chats\/([^/]+)$/, ({ params }) => {
    app.inbox.remove(params[0]);
    return { ok: true };
  });

  // домашка
  route('GET', /^\/api\/homework$/, async ({ url }) => {
    const today = homework.today();
    const monday = /^\d{4}-\d{2}-\d{2}$/.test(url.searchParams.get('monday') || '') ? mondayOf(url.searchParams.get('monday')) : mondayOf(today);
    const days = await homework.weekView(monday);
    return {
      today,
      monday,
      days: days.map((d) => ({ date: d.date, isHoliday: Boolean(d.isHoliday), missing: Boolean(d.missing), lessons: d.lessons.map(lessonOut), entries: d.entries.map(entryOut) })),
    };
  });
  route('GET', /^\/api\/preview$/, async ({ url }) => {
    const today = homework.today();
    const date = parseDayArg(url.searchParams.get('date') || 'завтра', today);
    if (!date) throw new HttpError(400, 'Неверная дата');
    const content = await contentFor(await homework.dayView(date, { fresh: true }), today);
    return content.image ? { kind: 'image', caption: content.caption, data: content.image.toString('base64') } : { kind: 'text', text: content.text };
  });
  route('POST', /^\/api\/homework\/manual$/, ({ body }) => {
    const today = homework.today();
    const date = parseDayArg(String(body.date || ''), today);
    const subject = String(body.subject || '').trim().slice(0, 80);
    const text = String(body.text || '').trim().slice(0, 2000);
    if (!date || !subject || !text) throw new HttpError(400, 'Нужны день, предмет и задание');
    const id = core.store.update((s) => {
      const newId = s.nextManualId++;
      s.manual.push({ id: newId, date, subject, text, author: 'панель', createdAt: Date.now() });
      return newId;
    });
    return { ok: true, id };
  });
  route('DELETE', /^\/api\/homework\/manual\/(\d+)$/, ({ params }) => {
    const id = Number(params[0]);
    core.store.update((s) => {
      s.manual = s.manual.filter((m) => m.id !== id);
    });
    return { ok: true };
  });

  // действия
  route('POST', /^\/api\/actions\/digest$/, async ({ body }) => {
    const targets = body.jid ? [body.jid] : app.scheduler.digestTargets();
    if (!targets.length) throw new HttpError(400, 'Нет групп для рассылки — добавьте бота в группу и напишите там !привязать');
    await app.scheduler.sendDigest({ targets, force: true });
    return { ok: true, groups: targets.length };
  });
  route('POST', /^\/api\/actions\/digest\/preview$/, async () => {
    const weekday = nowParts(config.timezone).weekday;
    const digest = await app.scheduler.buildDigest({ force: true, scope: config.schedule.days[weekday]?.scope });
    return {
      firstTime: digest.firstTime,
      fresh: digest.fresh.length,
      messages: (digest.messages || []).map((m) => (m.image ? { kind: 'image', caption: m.caption, data: m.image.toString('base64') } : { kind: 'text', text: m.text })),
    };
  });
  route('POST', /^\/api\/actions\/poll$/, async () => app.scheduler.runPoll({ manual: true }));
  route('GET', /^\/api\/alerts$/, () => ({ items: core.store.data.alertLog || [] }));
  route('POST', /^\/api\/alerts\/clear$/, () => {
    core.store.update((s) => {
      s.alertLog = [];
    });
    return { ok: true };
  });

  // группы
  route('GET', /^\/api\/groups$/, async () => {
    const targets = core.targets();
    let all = [];
    try {
      all = wa.isOpen ? await wa.allGroups() : [];
    } catch {
      /* WhatsApp недоступен */
    }
    const map = new Map(all.map((g) => [g.id, { jid: g.id, name: g.subject, members: g.participants?.length || 0 }]));
    for (const jid of targets) if (!map.has(jid)) map.set(jid, { jid, name: core.store.data.groups[jid]?.name || jid, members: null });
    return {
      groups: [...map.values()].map((g) => ({ ...g, bound: targets.includes(g.jid), fromEnv: config.whatsapp.groupIds.includes(g.jid), ...core.groupSettings(g.jid) })),
    };
  });
  route('PUT', /^\/api\/groups\/([^/]+)$/, ({ params, body }) => {
    const jid = params[0];
    if (!/@g\.us$/.test(jid)) throw new HttpError(400, 'Неверная группа');
    if (body.bound === true && !core.isTarget(jid)) core.bindGroup(jid, String(body.name || ''));
    if (body.bound === false) core.unbindGroup(jid);
    for (const key of ['digest', 'ai']) if (typeof body[key] === 'boolean' && core.isTarget(jid)) core.setGroupOption(jid, key, body[key]);
    return { ok: true };
  });

  // ключи и доступ
  route('GET', /^\/api\/access$/, ({ token }) => ({
    groq: app.keys.list(),
    backup: app.backup.describe(),
    bilim: { login: mask(config.bilim.login), loginHint: config.bilim.login ? `${config.bilim.login.slice(0, 2)}•••` : '', fromPanel: Boolean(app.secrets.get('bilim')), loggedIn: app.bilim.loggedIn, error: homework.status().lastError, className: app.bilim.session?.className || '', fullName: app.bilim.session?.fullName || '', mode: app.diary.status().mode },
    whatsapp: { ...wa.info(), qr: undefined, hasQr: Boolean(wa.qr), admins: config.whatsapp.admins.map((p) => `+${p.slice(0, 4)}•••${p.slice(-2)}`) },
    panel: { hasPassword: Boolean(auth.passwordHash), passwordFromPanel: Boolean(app.secrets.get('panel')?.passwordHash), methods: auth.methods(), sessions: auth.listSessions(token) },
    system: { canRestart: Boolean(app.restart), version, node: process.version },
  }));
  route('POST', /^\/api\/access\/groq$/, async ({ body }) => {
    const id = app.keys.add({ key: body.key, label: body.label });
    const test = await app.groq.testKey(app.keys.byId(id).key);
    if (!test.ok) app.keys.byId(id).status = test.status === 401 || test.status === 403 ? 'invalid' : 'unknown';
    app.keys.save();
    return { id, test: { ok: test.ok, message: test.message || null, models: test.models?.length || 0 }, keys: app.keys.list() };
  });
  route('POST', /^\/api\/access\/groq\/([^/]+)\/test$/, async ({ params }) => {
    const entry = app.keys.byId(params[0]);
    if (!entry) throw new HttpError(404, 'Ключ не найден');
    const test = await app.groq.testKey(entry.key);
    entry.status = test.ok ? 'ok' : test.status === 401 || test.status === 403 ? 'invalid' : entry.status;
    entry.lastError = test.ok ? null : test.message;
    if (test.ok) entry.lastOkAt = Date.now();
    app.keys.save();
    return { test: { ok: test.ok, message: test.message || null, models: test.models?.length || 0 }, keys: app.keys.list() };
  });
  route('POST', /^\/api\/access\/groq\/([^/]+)\/activate$/, ({ params }) => {
    app.keys.activate(params[0]);
    return { keys: app.keys.list() };
  });
  route('DELETE', /^\/api\/access\/groq\/([^/]+)$/, ({ params }) => {
    app.keys.remove(params[0]);
    return { keys: app.keys.list() };
  });
  route('PUT', /^\/api\/access\/backup$/, ({ body }) => {
    app.backup.update({ enabled: Boolean(body.enabled), baseUrl: body.baseUrl, apiKey: body.apiKey, model: body.model, label: body.label });
    return { backup: app.backup.describe() };
  });
  route('POST', /^\/api\/access\/backup\/test$/, async () => {
    const backup = app.backup.client();
    if (!backup) throw new HttpError(400, 'Запасной ИИ не включён');
    try {
      const r = await backup.client.chat({ model: backup.model, messages: [{ role: 'user', content: 'Ответь одним словом: работает?' }], maxTokens: 20, temperature: 0 });
      return { ok: true, text: r.text.slice(0, 100) };
    } catch (error) {
      return { ok: false, message: error.message };
    }
  });
  route('PUT', /^\/api\/access\/bilim$/, async ({ body }) => {
    const login = String(body.login || '').trim();
    const password = String(body.password || '');
    if (!login || !password) throw new HttpError(400, 'Введите логин и пароль BilimClass');
    const probe = new BilimClassClient({ ...config.bilim, login, password, deviceId: core.store.data.deviceId, logger });
    try {
      await probe.login();
    } catch (error) {
      throw new HttpError(error instanceof BilimAuthError ? 400 : 502, `BilimClass не пустил: ${error.message}`);
    }
    app.secrets.set('bilim', { login, password, changedAt: Date.now() });
    config.bilim.login = login;
    config.bilim.password = password;
    app.diary.setCredentials({ login, password });
    core.clearAlert('bilim-auth');
    return { ok: true, fullName: probe.session?.fullName || '', className: probe.session?.className || '', schoolName: probe.session?.schoolName || '' };
  });
  route('POST', /^\/api\/access\/bilim\/relogin$/, async () => {
    app.bilim.setCredentials({});
    await app.bilim.login();
    return { ok: true, className: app.bilim.session?.className || '', fullName: app.bilim.session?.fullName || '' };
  });
  route('POST', /^\/api\/access\/whatsapp\/reconnect$/, () => {
    wa.reconnect();
    return { ok: true };
  });
  route('POST', /^\/api\/access\/whatsapp\/relink$/, async ({ body }) => {
    if (body.confirm !== 'ОТВЯЗАТЬ') throw new HttpError(400, 'Подтвердите: введите слово ОТВЯЗАТЬ');
    const number = body.pairingNumber ? String(body.pairingNumber).replace(/\D/g, '') : '';
    if (number && !/^\d{10,15}$/.test(number)) throw new HttpError(400, 'Номер: только цифры с кодом страны');
    await wa.relink({ pairingNumber: number });
    return { ok: true };
  });
  route('GET', /^\/api\/access\/whatsapp\/qr$/, async () => ({ status: wa.status, pairingCode: wa.pairingCode, qr: wa.qr ? await wa.qrDataUrl() : null, me: wa.me }));
  route('PUT', /^\/api\/access\/password$/, ({ body, token }) => {
    try {
      auth.setPassword(body.next, { current: body.current, currentToken: token });
    } catch (error) {
      throw new HttpError(400, error.message);
    }
    return { ok: true };
  });
  route('POST', /^\/api\/access\/sessions\/revoke$/, ({ token }) => {
    auth.revokeOthers(token);
    return { ok: true, sessions: auth.listSessions(token) };
  });
  route('POST', /^\/api\/system\/restart$/, () => {
    if (!app.restart) throw new HttpError(400, 'Бот запущен без Docker/PM2/systemd — перезапустите его на сервере');
    setTimeout(() => app.restart('panel'), 300);
    return { ok: true };
  });

  // --- живые события (Server-Sent Events) ---
  function events(req, res) {
    if (sse.size >= SSE_LIMIT) throw new HttpError(429, 'Слишком много открытых вкладок панели');
    res.writeHead(200, { 'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'no-store', Connection: 'keep-alive', 'X-Accel-Buffering': 'no' });
    const send = (event, data) => res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
    send('hello', { at: Date.now() });
    const listeners = [
      [app.logBuffer, 'log', (item) => send('log', item)],
      [core, 'alert', (entry) => send('alert', entry)],
      [app.inbox, 'message', (e) => send('chat', e)],
      [app.inbox, 'read', (e) => send('read', e)],
      [app.inbox, 'chat', (e) => send('chatState', e)],
      [wa, 'state', () => send('wa', { ...wa.info(), qr: undefined, hasQr: Boolean(wa.qr) })],
      [app.settings, 'change', (paths) => send('settings', { paths })],
    ];
    for (const [emitter, name, fn] of listeners) emitter.on(name, fn);
    const ping = setInterval(() => res.write(': ping\n\n'), 25000);
    const client = { res };
    sse.add(client);
    req.on('close', () => {
      clearInterval(ping);
      for (const [emitter, name, fn] of listeners) emitter.off(name, fn);
      sse.delete(client);
    });
  }

  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    const meta = { ip: clientIp(req), ua: req.headers['user-agent'] || '' };
    try {
      if (url.pathname === '/health') {
        const waDownFor = wa.isOpen ? 0 : Date.now() - (wa.lastDisconnect?.at || core.startedAt);
        // «нездоров», если WhatsApp не на связи дольше 10 минут (и бот уже был привязан)
        const healthy = wa.isOpen || wa.status === 'qr' || waDownFor < 10 * 60 * 1000;
        const s = homework.status();
        json(res, healthy ? 200 : 503, {
          status: healthy ? 'ok' : 'degraded',
          whatsapp: wa.status,
          uptimeSec: Math.round((Date.now() - core.startedAt) / 1000),
          bilimLastSync: s.lastSuccessAt ? new Date(s.lastSuccessAt).toISOString() : null,
          bilimError: s.lastError,
          queue: wa.queue.length,
          groups: core.targets().length,
        });
        return;
      }
      if (url.pathname === '/qr') {
        if (!tokenOk(url.searchParams.get('token'), config.http.token)) {
          res.writeHead(403, { 'Content-Type': 'text/plain; charset=utf-8' });
          res.end('Доступ запрещён. Задайте HTTP_TOKEN в .env и откройте /qr?token=ВАШ_ТОКЕН — или привяжите WhatsApp в панели управления.');
          return;
        }
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
        if (wa.isOpen) res.end(qrPage('WhatsApp подключён', `<h2>✅ WhatsApp подключён</h2><p>${wa.me?.id || ''}</p>`));
        else if (wa.pairingCode) res.end(qrPage('Код привязки', `<h2>Код для привязки</h2><code>${wa.pairingCode}</code><p>WhatsApp → Связанные устройства → Привязка устройства → «Привязать по номеру телефона»</p>`, 20));
        else if (wa.qr) res.end(qrPage('QR для WhatsApp', `<h2>Отсканируйте в WhatsApp</h2><p>Настройки → Связанные устройства → Привязка устройства</p><img src="${await wa.qrDataUrl()}" alt="QR"><p>Страница обновляется сама</p>`, 15));
        else res.end(qrPage('Подключение…', `<h2>Подключаюсь к WhatsApp… (${wa.status})</h2>`, 5));
        return;
      }
      if (!config.panel.enabled && (url.pathname.startsWith('/api/') || url.pathname === '/app' || url.pathname.startsWith('/auth/'))) {
        res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
        res.end('Панель управления выключена (ADMIN_PANEL=false)');
        return;
      }

      const token = cookies(req)[COOKIE] || '';
      const session = auth.session(token);

      if (url.pathname === '/auth/link' && req.method === 'GET') {
        const result = auth.loginLink(url.searchParams.get('t'), meta);
        if (result.token) setSession(req, res, result.token);
        res.writeHead(302, { Location: result.token ? '/app' : '/?login=expired', 'Cache-Control': 'no-store' });
        res.end();
        return;
      }

      if (url.pathname.startsWith('/api/')) {
        if (url.pathname === '/api/events' && req.method === 'GET') {
          if (!session) throw new HttpError(401, 'Нужно войти');
          events(req, res);
          return;
        }
        const match = routes
          .map((r) => ({ r, m: r.method === req.method ? r.pattern.exec(url.pathname) : null }))
          .find((x) => x.m);
        if (!match) {
          const exists = routes.some((r) => r.pattern.test(url.pathname));
          throw new HttpError(exists ? 405 : 404, exists ? 'Метод не поддерживается' : 'Не найдено');
        }
        if (req.method !== 'GET') checkCsrf(req);
        if (match.r.needAuth && !session) throw new HttpError(401, 'Нужно войти в панель');
        const body = req.method === 'GET' ? {} : await readBody(req);
        const params = match.m.slice(1).map((p) => decodeURIComponent(p));
        const result = await match.r.handler({ req, res, url, body, params, session, token, meta });
        if (!res.headersSent) json(res, 200, result ?? { ok: true });
        return;
      }

      if ((req.method === 'GET' || req.method === 'HEAD') && serveStatic(req, res, url.pathname === '/index.html' ? '/' : url.pathname)) return;
      securityHeaders(res);
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('Not found');
    } catch (error) {
      const status = error instanceof HttpError ? error.status
        : error instanceof ConfigError ? 400
          : error instanceof BilimAuthError ? 400
            : /не найден|неправильно|уже добавлен|Укажите|Адрес API|должен/.test(error.message) ? 400 : 500;
      if (status >= 500) logger.error({ err: error, path: url.pathname }, 'Ошибка веб-сервера');
      if (!res.headersSent) json(res, status, { error: error.message || 'Ошибка' });
      else res.end();
    }
  });
  server.on('error', (error) => logger.error({ err: error.message }, 'Веб-сервер не запустился'));
  server.listen(config.http.port, config.http.host, () => {
    logger.info(`Сайт и панель: http://${config.http.host === '0.0.0.0' ? 'localhost' : config.http.host}:${config.http.port}  (health: /health)`);
  });
  server.closeAll = () => {
    for (const client of sse) client.res.end();
    server.close();
  };
  return server;
}

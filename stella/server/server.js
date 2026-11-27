'use strict';
// Stella Cloud — сервер подписок и прокси к ИИ/голосу. Только встроенные модули Node.js.
const http = require('http');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { DB } = require('./db');

function loadEnv(file) {
  if (!fs.existsSync(file)) return;
  for (const line of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
    if (m && !(m[1] in process.env)) process.env[m[1]] = m[2].replace(/^["']|["']$/g, '');
  }
}

const day = (ts = Date.now()) => new Date(ts).toISOString().slice(0, 10);
const month = (ts = Date.now()) => new Date(ts).toISOString().slice(0, 7);
const sha = (s) => crypto.createHash('sha256').update(String(s)).digest('hex');
const token = () => crypto.randomBytes(32).toString('base64url');
const hashPw = (pw, salt = crypto.randomBytes(16).toString('hex')) => ({ salt, hash: crypto.scryptSync(String(pw), salt, 64).toString('hex') });
const checkPw = (pw, salt, hash) => { const a = crypto.scryptSync(String(pw), salt, 64); const b = Buffer.from(hash, 'hex'); return a.length === b.length && crypto.timingSafeEqual(a, b); };

class HttpError extends Error { constructor(status, message, extra = {}) { super(message); this.status = status; this.extra = extra; } }

function createApp(opts = {}) {
  const cfg = {
    adminPassword: opts.adminPassword ?? process.env.ADMIN_PASSWORD ?? '',
    openrouterKey: opts.openrouterKey ?? process.env.OPENROUTER_API_KEY ?? '',
    elevenKey: opts.elevenKey ?? process.env.ELEVENLABS_API_KEY ?? '',
    openrouterBase: opts.openrouterBase ?? process.env.OPENROUTER_BASE ?? 'https://openrouter.ai/api/v1',
    elevenBase: opts.elevenBase ?? process.env.ELEVENLABS_BASE ?? 'https://api.elevenlabs.io/v1',
    defaultModel: opts.defaultModel ?? process.env.DEFAULT_MODEL ?? 'openai/gpt-4o-mini',
    openRegistration: String(opts.openRegistration ?? process.env.OPEN_REGISTRATION ?? 'true') === 'true',
    defaultPlan: opts.defaultPlan ?? process.env.DEFAULT_PLAN ?? 'free',
    ipRatePerMin: Number(opts.ipRatePerMin ?? process.env.IP_RATE_PER_MIN ?? 120),
    trustProxy: String(opts.trustProxy ?? process.env.TRUST_PROXY ?? 'false') === 'true',
    fetch: opts.fetch || fetch,
  };
  const db = opts.db || new DB(opts.dataDir || process.env.DATA_DIR || path.join(__dirname, 'data'));
  const adminSessions = new Map();
  const buckets = new Map();

  // ---------- утилиты ----------
  const clientIp = (req) => {
    const fwd = cfg.trustProxy && String(req.headers['x-forwarded-for'] || '').split(',')[0].trim();
    return (fwd || req.socket.remoteAddress || '').replace(/^::ffff:/, '');
  };
  function rateLimit(ip) {
    const now = Date.now();
    const b = buckets.get(ip) || { tokens: cfg.ipRatePerMin, ts: now };
    b.tokens = Math.min(cfg.ipRatePerMin, b.tokens + ((now - b.ts) / 60000) * cfg.ipRatePerMin);
    b.ts = now;
    if (b.tokens < 1) throw new HttpError(429, 'Слишком много запросов с вашего IP, подождите минуту');
    b.tokens -= 1;
    buckets.set(ip, b);
  }
  const readBody = (req, limit = 25 * 1024 * 1024) => new Promise((resolve, reject) => {
    const chunks = []; let n = 0;
    req.on('data', (c) => { n += c.length; if (n > limit) { reject(new HttpError(413, 'Слишком большой запрос')); req.destroy(); } else chunks.push(c); });
    req.on('end', () => resolve(Buffer.concat(chunks)));
    req.on('error', reject);
  });
  const readJson = async (req) => { const b = await readBody(req, 5 * 1024 * 1024); if (!b.length) return {}; try { return JSON.parse(b.toString('utf8')); } catch { throw new HttpError(400, 'Некорректный JSON'); } };
  const send = (res, status, data, headers = {}) => { res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', ...headers }); res.end(JSON.stringify(data)); };

  function publicUser(u) {
    const plan = planOf(u);
    return {
      id: u.id, username: u.username, email: u.email || '', plan: plan.id, planName: plan.name, planColor: plan.color, planExpiresAt: u.planExpiresAt || null,
      createdAt: u.createdAt, banned: !!u.banned, ipLock: u.ipLock || [], limits: limitsOf(u), usage: usageOf(u), lastIp: u.lastIp || '', lastSeen: u.lastSeen || 0, notes: u.notes || '',
    };
  }
  function planOf(u) {
    let id = u.plan || cfg.defaultPlan;
    if (u.planExpiresAt && u.planExpiresAt < Date.now()) id = cfg.defaultPlan;
    return db.data.plans[id] || db.data.plans.free || Object.values(db.data.plans)[0];
  }
  function limitsOf(u) { const p = planOf(u); return { messagesPerDay: p.messagesPerDay, ttsCharsPerMonth: p.ttsCharsPerMonth, sttPerDay: p.sttPerDay, models: p.models, tools: p.tools, ...(u.customLimits || {}) }; }
  function usageOf(u) {
    const d = db.data.usage[u.id] || {};
    return { messagesToday: d['m:' + day()] || 0, ttsCharsMonth: d['t:' + month()] || 0, sttToday: d['s:' + day()] || 0, totalMessages: d.totalMessages || 0, totalTokens: d.totalTokens || 0 };
  }
  function addUsage(u, key, n) {
    const d = (db.data.usage[u.id] ||= {});
    d[key] = (d[key] || 0) + n;
    db.save();
  }
  function modelAllowed(u, model) { const m = limitsOf(u).models || ['*']; return m.includes('*') || m.includes(model) || m.some((x) => x.endsWith('/*') && model.startsWith(x.slice(0, -1))); }

  function authUser(req, ip) {
    const h = String(req.headers.authorization || '');
    const t = h.startsWith('Bearer ') ? h.slice(7) : '';
    if (!t) throw new HttpError(401, 'Нужен вход в аккаунт Stella Cloud');
    const s = db.data.sessions.find((x) => x.tokenHash === sha(t));
    if (!s) throw new HttpError(401, 'Сессия истекла — войдите заново');
    const u = db.data.users.find((x) => x.id === s.userId);
    if (!u) throw new HttpError(401, 'Аккаунт не найден');
    if (u.banned) throw new HttpError(403, 'Аккаунт заблокирован');
    if (u.ipLock?.length && !u.ipLock.includes(ip)) throw new HttpError(403, `Доступ с IP ${ip} запрещён для этого аккаунта`);
    u.lastIp = ip; u.lastSeen = Date.now();
    if (!u.ips) u.ips = [];
    if (!u.ips.includes(ip)) { u.ips.push(ip); if (u.ips.length > 20) u.ips.shift(); }
    db.save();
    return u;
  }
  function authAdmin(req) {
    const t = String(req.headers.authorization || '').replace(/^Bearer /, '');
    const s = adminSessions.get(sha(t));
    if (!s || s < Date.now()) throw new HttpError(401, 'Нужен вход администратора');
  }
  function newSession(u, ip) {
    const t = token();
    db.data.sessions.push({ tokenHash: sha(t), userId: u.id, createdAt: Date.now(), ip });
    if (db.data.sessions.length > 20000) db.data.sessions.splice(0, db.data.sessions.length - 20000);
    db.save();
    return t;
  }
  function validName(n) { if (!/^[\p{L}\p{N}_.-]{2,32}$/u.test(String(n || ''))) throw new HttpError(400, 'Логин: 2–32 символа (буквы, цифры, _ . -)'); return String(n); }
  function createUser({ username, password, email, plan }, ip) {
    validName(username);
    if (String(password || '').length < 6) throw new HttpError(400, 'Пароль должен быть не короче 6 символов');
    if (db.data.users.some((u) => u.username.toLowerCase() === String(username).toLowerCase())) throw new HttpError(409, 'Такой пользователь уже есть');
    const { salt, hash } = hashPw(password);
    const u = { id: 'u_' + crypto.randomBytes(6).toString('hex'), username, email: email || '', salt, hash, plan: plan || cfg.defaultPlan, createdAt: Date.now(), regIp: ip, ips: [ip] };
    db.data.users.push(u);
    db.log('register', { user: u.username, ip });
    db.save();
    return u;
  }

  // ---------- прокси ----------
  async function proxyChat(req, res, u, ip) {
    const body = await readJson(req);
    const lim = limitsOf(u), use = usageOf(u);
    if (use.messagesToday >= lim.messagesPerDay) throw new HttpError(429, `Дневной лимит сообщений тарифа исчерпан (${lim.messagesPerDay}). Обновите подписку.`, { code: 'quota' });
    const model = body.model || cfg.defaultModel;
    if (!modelAllowed(u, model)) throw new HttpError(403, `Модель ${model} недоступна на вашем тарифе`);
    if (!lim.tools) delete body.tools;
    if (!cfg.openrouterKey) throw new HttpError(503, 'На сервере не настроен ключ OpenRouter');
    const upstream = await cfg.fetch(cfg.openrouterBase + '/chat/completions', {
      method: 'POST',
      headers: { Authorization: `Bearer ${cfg.openrouterKey}`, 'Content-Type': 'application/json', 'HTTP-Referer': 'https://stella.cloud', 'X-Title': 'Stella Cloud' },
      body: JSON.stringify({ ...body, model, user: u.id, usage: { include: true } }),
    });
    if (upstream.ok) { addUsage(u, 'm:' + day(), 1); addUsage(u, 'totalMessages', 1); }
    res.writeHead(upstream.status, { 'Content-Type': upstream.headers.get('content-type') || 'text/event-stream', 'Cache-Control': 'no-cache' });
    if (!upstream.body) { res.end(await upstream.text()); return; }
    const reader = upstream.body.getReader();
    let tail = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      res.write(value);
      tail = (tail + Buffer.from(value).toString('utf8')).slice(-4000);
    }
    res.end();
    const m = tail.match(/"total_tokens"\s*:\s*(\d+)/g);
    if (m) addUsage(u, 'totalTokens', Number(m.at(-1).match(/\d+/)[0]));
    db.log('chat', { user: u.username, model, ip });
  }

  async function proxyTts(req, res, u) {
    const body = await readJson(req);
    const text = String(body.text || '').slice(0, 5000);
    const lim = limitsOf(u), use = usageOf(u);
    if (use.ttsCharsMonth + text.length > lim.ttsCharsPerMonth) throw new HttpError(429, `Лимит озвучки на месяц исчерпан (${lim.ttsCharsPerMonth} символов)`, { code: 'quota' });
    if (!cfg.elevenKey) throw new HttpError(503, 'На сервере не настроен ключ ElevenLabs');
    const up = await cfg.fetch(`${cfg.elevenBase}/text-to-speech/${encodeURIComponent(body.voiceId || '21m00Tcm4TlvDq8ikWAM')}?output_format=mp3_44100_128`, {
      method: 'POST', headers: { 'xi-api-key': cfg.elevenKey, 'Content-Type': 'application/json', Accept: 'audio/mpeg' },
      body: JSON.stringify({ text, model_id: body.modelId || 'eleven_multilingual_v2', voice_settings: body.voiceSettings || {} }),
    });
    if (!up.ok) throw new HttpError(up.status, 'ElevenLabs: ' + (await up.text()).slice(0, 200));
    const buf = Buffer.from(await up.arrayBuffer());
    addUsage(u, 't:' + month(), text.length);
    res.writeHead(200, { 'Content-Type': 'audio/mpeg', 'Content-Length': buf.length });
    res.end(buf);
  }

  async function proxyStt(req, res, u) {
    const lim = limitsOf(u), use = usageOf(u);
    if (use.sttToday >= lim.sttPerDay) throw new HttpError(429, 'Дневной лимит распознавания речи исчерпан', { code: 'quota' });
    if (!cfg.elevenKey) throw new HttpError(503, 'На сервере не настроен ключ ElevenLabs');
    const raw = await readBody(req, 20 * 1024 * 1024);
    const up = await cfg.fetch(`${cfg.elevenBase}/speech-to-text`, { method: 'POST', headers: { 'xi-api-key': cfg.elevenKey, 'Content-Type': req.headers['content-type'] }, body: raw });
    const txt = await up.text();
    if (up.ok) addUsage(u, 's:' + day(), 1);
    res.writeHead(up.status, { 'Content-Type': 'application/json' });
    res.end(txt);
  }

  // ---------- маршруты ----------
  const routes = [];
  const route = (method, pattern, fn) => routes.push({ method, re: new RegExp('^' + pattern.replace(/:(\w+)/g, '(?<$1>[^/]+)') + '$'), fn });

  route('GET', '/api/health', () => ({ ok: true, name: 'Stella Cloud', version: '1.0.0', openRegistration: cfg.openRegistration, ai: !!cfg.openrouterKey, voice: !!cfg.elevenKey }));
  route('GET', '/api/plans', () => Object.values(db.data.plans).map(({ id, name, price, messagesPerDay, ttsCharsPerMonth, sttPerDay, color }) => ({ id, name, price, messagesPerDay, ttsCharsPerMonth, sttPerDay, color })));
  route('POST', '/api/auth/register', async (req, res, ctx) => {
    if (!cfg.openRegistration) throw new HttpError(403, 'Регистрация закрыта — обратитесь к администратору');
    const b = await readJson(req);
    const u = createUser({ username: b.username, password: b.password, email: b.email }, ctx.ip);
    return { token: newSession(u, ctx.ip), user: publicUser(u) };
  });
  route('POST', '/api/auth/login', async (req, res, ctx) => {
    const b = await readJson(req);
    const u = db.data.users.find((x) => x.username.toLowerCase() === String(b.username || '').toLowerCase());
    if (!u || !checkPw(b.password || '', u.salt, u.hash)) { db.log('login_fail', { user: b.username, ip: ctx.ip }); throw new HttpError(401, 'Неверный логин или пароль'); }
    if (u.banned) throw new HttpError(403, 'Аккаунт заблокирован');
    if (u.ipLock?.length && !u.ipLock.includes(ctx.ip)) throw new HttpError(403, `Вход с IP ${ctx.ip} запрещён для этого аккаунта`);
    db.log('login', { user: u.username, ip: ctx.ip });
    return { token: newSession(u, ctx.ip), user: publicUser(u) };
  });
  route('POST', '/api/auth/logout', async (req) => {
    const t = String(req.headers.authorization || '').replace(/^Bearer /, '');
    db.data.sessions = db.data.sessions.filter((s) => s.tokenHash !== sha(t)); db.save(); return { ok: true };
  });
  route('GET', '/api/me', (req, res, ctx) => publicUser(authUser(req, ctx.ip)));
  route('POST', '/api/redeem', async (req, res, ctx) => {
    const u = authUser(req, ctx.ip);
    const { code } = await readJson(req);
    const c = db.data.codes.find((x) => x.code === String(code || '').trim().toUpperCase());
    if (!c) throw new HttpError(404, 'Код не найден');
    if (c.usedBy) throw new HttpError(409, 'Код уже использован');
    if (!db.data.plans[c.plan]) throw new HttpError(400, 'Тариф кода не существует');
    const base = u.plan === c.plan && u.planExpiresAt > Date.now() ? u.planExpiresAt : Date.now();
    u.plan = c.plan; u.planExpiresAt = base + c.days * 86400000;
    c.usedBy = u.username; c.usedAt = Date.now();
    db.log('redeem', { user: u.username, code: c.code, ip: ctx.ip });
    db.save();
    return publicUser(u);
  });
  route('POST', '/api/chat/completions', async (req, res, ctx) => { await proxyChat(req, res, authUser(req, ctx.ip), ctx.ip); });
  route('GET', '/api/models', async (req, res, ctx) => {
    const u = authUser(req, ctx.ip);
    const up = await cfg.fetch(cfg.openrouterBase + '/models');
    const j = await up.json();
    return { data: (j.data || []).filter((m) => modelAllowed(u, m.id)) };
  });
  route('POST', '/api/tts', async (req, res, ctx) => { await proxyTts(req, res, authUser(req, ctx.ip)); });
  route('POST', '/api/stt', async (req, res, ctx) => { await proxyStt(req, res, authUser(req, ctx.ip)); });
  route('GET', '/api/voices', async (req, res, ctx) => {
    authUser(req, ctx.ip);
    const up = await cfg.fetch(cfg.elevenBase + '/voices', { headers: { 'xi-api-key': cfg.elevenKey } });
    return up.json();
  });

  // --- админка ---
  route('POST', '/api/admin/login', async (req, res, ctx) => {
    const { password } = await readJson(req);
    if (!cfg.adminPassword) throw new HttpError(503, 'ADMIN_PASSWORD не задан в .env');
    const a = Buffer.from(sha(password || '')), b = Buffer.from(sha(cfg.adminPassword));
    if (!crypto.timingSafeEqual(a, b)) { db.log('admin_fail', { ip: ctx.ip }); throw new HttpError(401, 'Неверный пароль администратора'); }
    const t = token(); adminSessions.set(sha(t), Date.now() + 12 * 3600000);
    db.log('admin_login', { ip: ctx.ip });
    return { token: t };
  });
  route('GET', '/api/admin/stats', (req) => {
    authAdmin(req);
    const users = db.data.users;
    const today = day();
    const msgsToday = Object.values(db.data.usage).reduce((s, d) => s + (d['m:' + today] || 0), 0);
    const byPlan = {}; for (const u of users) { const p = planOf(u).id; byPlan[p] = (byPlan[p] || 0) + 1; }
    return { users: users.length, activeToday: users.filter((u) => u.lastSeen && day(u.lastSeen) === today).length, messagesToday: msgsToday, byPlan, bannedIps: db.data.bannedIps.length, codesFree: db.data.codes.filter((c) => !c.usedBy).length, ai: !!cfg.openrouterKey, voice: !!cfg.elevenKey };
  });
  route('GET', '/api/admin/users', (req) => { authAdmin(req); return db.data.users.map((u) => ({ ...publicUser(u), ips: u.ips || [], regIp: u.regIp })); });
  route('POST', '/api/admin/users', async (req, res, ctx) => { authAdmin(req); const b = await readJson(req); return publicUser(createUser(b, ctx.ip)); });
  route('PATCH', '/api/admin/users/:id', async (req, res, ctx) => {
    authAdmin(req);
    const u = db.data.users.find((x) => x.id === ctx.params.id);
    if (!u) throw new HttpError(404, 'Пользователь не найден');
    const b = await readJson(req);
    if (b.plan !== undefined) { if (!db.data.plans[b.plan]) throw new HttpError(400, 'Нет такого тарифа'); u.plan = b.plan; }
    if (b.days !== undefined) u.planExpiresAt = Number(b.days) > 0 ? Date.now() + Number(b.days) * 86400000 : null;
    if (b.banned !== undefined) u.banned = !!b.banned;
    if (b.ipLock !== undefined) u.ipLock = (Array.isArray(b.ipLock) ? b.ipLock : String(b.ipLock).split(/[\s,]+/)).map((x) => x.trim()).filter(Boolean);
    if (b.notes !== undefined) u.notes = String(b.notes).slice(0, 500);
    if (b.customLimits !== undefined) u.customLimits = b.customLimits && typeof b.customLimits === 'object' ? b.customLimits : undefined;
    if (b.password) { const { salt, hash } = hashPw(b.password); u.salt = salt; u.hash = hash; db.data.sessions = db.data.sessions.filter((s) => s.userId !== u.id); }
    if (b.resetUsage) delete db.data.usage[u.id];
    db.log('admin_update', { user: u.username, ip: ctx.ip, fields: Object.keys(b) });
    db.save();
    return publicUser(u);
  });
  route('DELETE', '/api/admin/users/:id', (req, res, ctx) => {
    authAdmin(req);
    const before = db.data.users.length;
    db.data.users = db.data.users.filter((u) => u.id !== ctx.params.id);
    db.data.sessions = db.data.sessions.filter((s) => s.userId !== ctx.params.id);
    delete db.data.usage[ctx.params.id];
    db.save();
    return { ok: before !== db.data.users.length };
  });
  route('GET', '/api/admin/plans', (req) => { authAdmin(req); return db.data.plans; });
  route('PUT', '/api/admin/plans/:id', async (req, res, ctx) => {
    authAdmin(req);
    const b = await readJson(req);
    const id = ctx.params.id.toLowerCase().replace(/[^a-z0-9_-]/g, '');
    if (!id) throw new HttpError(400, 'Некорректный id тарифа');
    const num = (v, d) => (Number.isFinite(Number(v)) ? Math.max(0, Number(v)) : d);
    const old = db.data.plans[id] || {};
    db.data.plans[id] = { id, name: String(b.name || old.name || id), price: String(b.price ?? old.price ?? ''), color: String(b.color || old.color || '#8b5cf6'),
      messagesPerDay: num(b.messagesPerDay, old.messagesPerDay ?? 30), ttsCharsPerMonth: num(b.ttsCharsPerMonth, old.ttsCharsPerMonth ?? 3000), sttPerDay: num(b.sttPerDay, old.sttPerDay ?? 20),
      models: Array.isArray(b.models) ? b.models : String(b.models ?? (old.models || ['*']).join(',')).split(/[\s,]+/).filter(Boolean), tools: b.tools ?? old.tools ?? true };
    db.save();
    return db.data.plans[id];
  });
  route('DELETE', '/api/admin/plans/:id', (req, res, ctx) => {
    authAdmin(req);
    if (ctx.params.id === cfg.defaultPlan) throw new HttpError(400, 'Нельзя удалить тариф по умолчанию');
    delete db.data.plans[ctx.params.id]; db.save(); return { ok: true };
  });
  route('GET', '/api/admin/codes', (req) => { authAdmin(req); return db.data.codes.slice().reverse(); });
  route('POST', '/api/admin/codes', async (req) => {
    authAdmin(req);
    const b = await readJson(req);
    if (!db.data.plans[b.plan]) throw new HttpError(400, 'Нет такого тарифа');
    const n = Math.min(100, Math.max(1, Number(b.count) || 1));
    const out = [];
    for (let i = 0; i < n; i++) {
      const code = `${b.plan.toUpperCase()}-${crypto.randomBytes(3).toString('hex').toUpperCase()}-${crypto.randomBytes(3).toString('hex').toUpperCase()}`;
      const c = { code, plan: b.plan, days: Math.max(1, Number(b.days) || 30), createdAt: Date.now(), usedBy: null };
      db.data.codes.push(c); out.push(c);
    }
    db.save();
    return out;
  });
  route('GET', '/api/admin/ips', (req) => { authAdmin(req); return db.data.bannedIps; });
  route('POST', '/api/admin/ips/ban', async (req) => { authAdmin(req); const { ip } = await readJson(req); if (ip && !db.data.bannedIps.includes(ip)) db.data.bannedIps.push(String(ip)); db.save(); return db.data.bannedIps; });
  route('POST', '/api/admin/ips/unban', async (req) => { authAdmin(req); const { ip } = await readJson(req); db.data.bannedIps = db.data.bannedIps.filter((x) => x !== ip); db.save(); return db.data.bannedIps; });
  route('GET', '/api/admin/log', (req) => { authAdmin(req); return db.data.log.slice(-300).reverse(); });

  // ---------- обработчик ----------
  async function handler(req, res) {
    const ip = clientIp(req);
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Headers', 'Authorization, Content-Type');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, PATCH, DELETE, OPTIONS');
    res.setHeader('X-Content-Type-Options', 'nosniff');
    if (req.method === 'OPTIONS') { res.writeHead(204); res.end(); return; }
    const url = new URL(req.url, 'http://x');
    try {
      if (db.data.bannedIps.includes(ip)) throw new HttpError(403, 'Ваш IP заблокирован');
      if (url.pathname === '/' || url.pathname === '/admin' || url.pathname === '/admin/') {
        res.writeHead(url.pathname === '/' ? 302 : 200, url.pathname === '/' ? { Location: '/admin' } : { 'Content-Type': 'text/html; charset=utf-8', 'Content-Security-Policy': "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'" });
        res.end(url.pathname === '/' ? '' : fs.readFileSync(path.join(__dirname, 'public', 'admin.html')));
        return;
      }
      if (!url.pathname.startsWith('/api/')) throw new HttpError(404, 'Не найдено');
      if (url.pathname !== '/api/health') rateLimit(ip);
      for (const r of routes) {
        if (r.method !== req.method) continue;
        const m = url.pathname.match(r.re);
        if (!m) continue;
        const out = await r.fn(req, res, { ip, params: m.groups || {}, query: url.searchParams });
        if (out !== undefined && !res.headersSent) send(res, 200, out);
        return;
      }
      throw new HttpError(404, 'Метод не найден');
    } catch (e) {
      const status = e.status || 500;
      if (status === 500) console.error(e);
      if (!res.headersSent) send(res, status, { error: { message: e.message || 'Ошибка сервера', code: e.extra?.code } });
      else res.end();
    }
  }

  return { handler, db, cfg, publicUser };
}

if (require.main === module) {
  loadEnv(path.join(__dirname, '.env'));
  const app = createApp();
  const port = Number(process.env.PORT || 8787), host = process.env.HOST || '0.0.0.0';
  http.createServer(app.handler).listen(port, host, () => {
    console.log(`✦ Stella Cloud запущен: http://${host}:${port}`);
    console.log(`  Админ-панель: http://<IP-сервера>:${port}/admin`);
    if (!app.cfg.adminPassword) console.warn('  ⚠ ADMIN_PASSWORD не задан — админ-панель недоступна');
    if (!app.cfg.openrouterKey) console.warn('  ⚠ OPENROUTER_API_KEY не задан');
    if (!app.cfg.elevenKey) console.warn('  ⚠ ELEVENLABS_API_KEY не задан');
  });
  const stop = () => { app.db.flush(); process.exit(0); };
  process.on('SIGINT', stop); process.on('SIGTERM', stop);
}

module.exports = { createApp, HttpError, loadEnv };

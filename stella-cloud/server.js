// Stella Cloud server.
//  - accounts (each gets a private Linux user + workspace + its own agy agent)
//  - phone web app (PWA) in ./public
//  - live hub: phone <-> server agent <-> Stella on the PC (WebSocket /ws)
//  - WhatsApp (Baileys) + MCP endpoints for the agent
const http = require('http');
const fs = require('fs');
const path = require('path');
const { WebSocketServer } = require('ws');
const users = require('./lib/users');
const agent = require('./lib/agent');
const wa = require('./lib/whatsapp');
const failover = require('./lib/failover');
const services = require('./lib/services');
const office = require('./lib/office');
const sandbox = require('./lib/sandbox');
const team = require('./lib/team');
const grading = require('./lib/grading');

const PORT = Number(process.env.PORT || 8787);
const HOST = process.env.HOST || '127.0.0.1';          // behind Caddy (HTTPS) by default
const PUBLIC = path.join(__dirname, 'public');

/* ================================================================== */
/* hub: every connected device of every user                           */
/* ================================================================== */
const conns = new Map();          // username -> Set<{ws, device, label}>
const pcState = new Map();        // username -> { chats: Map<id, chat>, online }

function devices(name) { if (!conns.has(name)) conns.set(name, new Set()); return conns.get(name); }
function pc(name) { if (!pcState.has(name)) pcState.set(name, { chats: new Map(), online: false }); return pcState.get(name); }
function sendTo(c, msg) { try { if (c.ws.readyState === 1) c.ws.send(JSON.stringify(msg)); } catch {} }
function emit(name, msg, filter) { for (const c of devices(name)) if (!filter || filter(c)) sendTo(c, msg); }
const toPhones = (name, msg) => emit(name, msg, c => c.device !== 'pc');
const toPc = (name, msg) => { let n = 0; for (const c of devices(name)) if (c.device === 'pc') { sendTo(c, msg); n++; } return n; };

agent.setup({ emit, port: PORT });
wa.setup({ emit, agent });
failover.setup({ agent, emit, toPc, toPhones });
team.setup({ agent, emit, toPc, pcOnline: name => pc(name).online });
grading.setup({ agent, emit });

/* ================================================================== */
/* HTTP                                                                */
/* ================================================================== */
const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json', '.webmanifest': 'application/manifest+json', '.png': 'image/png', '.svg': 'image/svg+xml', '.ico': 'image/x-icon' };
const VENDOR = {
  '/vendor/xterm.js': require.resolve('@xterm/xterm/lib/xterm.js'),
  '/vendor/xterm.css': require.resolve('@xterm/xterm/css/xterm.css'),
  '/vendor/addon-fit.js': require.resolve('@xterm/addon-fit/lib/addon-fit.js')
};

function json(res, code, obj) { res.writeHead(code, { 'content-type': 'application/json', 'cache-control': 'no-store' }); res.end(JSON.stringify(obj)); }
function body(req) {
  return new Promise((resolve, reject) => {
    let b = ''; req.on('data', d => { b += d; if (b.length > 2e6) { reject(new Error('too large')); req.destroy(); } });
    req.on('end', () => { try { resolve(b ? JSON.parse(b) : {}); } catch { reject(new Error('bad json')); } });
  });
}
function bearer(req) { const h = req.headers.authorization || ''; return h.startsWith('Bearer ') ? h.slice(7) : ''; }

// The server listens on 127.0.0.1 only, so every request comes through our own proxy:
//  - Cloudflare Tunnel (cloudflared) sets CF-Connecting-IP
//  - our nginx site sets X-Real-IP and strips any client-supplied CF-Connecting-IP
// The left-most X-Forwarded-For entry is client-controlled and is never trusted.
function clientIp(req) {
  return String(req.headers['cf-connecting-ip'] || req.headers['x-real-ip'] || req.socket.remoteAddress || '').slice(0, 64);
}
const buckets = new Map();        // key -> [timestamps]
function limited(req, kind = 'auth', max = 10, windowMs = 10 * 60 * 1000) {
  const key = kind + '|' + clientIp(req);
  const now = Date.now(); const list = (buckets.get(key) || []).filter(t => now - t < windowMs);
  list.push(now); buckets.set(key, list);
  return list.length > max;
}
setInterval(() => { const now = Date.now(); for (const [k, l] of buckets) if (!l.some(t => now - t < 3600e3)) buckets.delete(k); }, 600e3);

// Cloudflare Turnstile (captcha) — enabled when STELLA_TURNSTILE_SITEKEY + STELLA_TURNSTILE_SECRET are set
const TURNSTILE = !!(process.env.STELLA_TURNSTILE_SITEKEY && process.env.STELLA_TURNSTILE_SECRET);
async function captchaOk(req, token) {
  if (!TURNSTILE) return true;
  if (!token || String(token).length > 4096) return false;
  try {
    const r = await fetch('https://challenges.cloudflare.com/turnstile/v0/siteverify', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ secret: process.env.STELLA_TURNSTILE_SECRET, response: String(token), remoteip: clientIp(req) }),
      signal: AbortSignal.timeout(10000)
    });
    const j = await r.json();
    return !!j.success;
  } catch (e) { console.error('turnstile verify failed', e.message); return false; }
}
const meta = req => ({ ip: clientIp(req), ua: req.headers['user-agent'] || '' });

async function api(req, res, url) {
  const p = url.pathname;
  if (req.method === 'POST' && (p === '/api/register' || p === '/api/login')) {
    const reg = p === '/api/register';
    if (limited(req, reg ? 'register' : 'login', reg ? 5 : 15, reg ? 3600e3 : 600e3)) return json(res, 429, { error: 'Слишком много попыток с вашего адреса. Подождите и попробуйте позже.' });
    try {
      const b = await body(req);
      if (!(await captchaOk(req, b.captcha))) return json(res, 400, { error: 'Пройдите проверку «Я не робот»', captcha: true });
      const m = Object.assign(meta(req), { totp: b.totp, kind: b.device === 'pc' ? 'pc' : 'web' });
      const r = reg ? users.register(b.username, b.password, b.invite, m) : users.login(b.username, b.password, m);
      const u = users.get(r.user.name);
      emit(r.user.name, { t: 'notify', title: '🔐 Новый вход в аккаунт', body: `${m.kind === 'pc' ? 'Компьютер' : 'Браузер/телефон'} · IP ${m.ip}. Если это не вы — «Ещё» → «Безопасность» → «Выйти на всех устройствах» и смените пароль.` });
      return json(res, 200, Object.assign(r, { user: users.publicUser(u) }));
    } catch (e) { return json(res, e.status || 400, { error: e.message, need2fa: !!e.need2fa }); }
  }
  if (req.method === 'POST' && p === '/api/logout') { users.logout(bearer(req)); return json(res, 200, { ok: true }); }
  if (req.method === 'GET' && p === '/api/info') return json(res, 200, { signup: process.env.STELLA_SIGNUP || 'invite', sharedKey: !!process.env.STELLA_GEMINI_API_KEY, name: 'Stella Cloud', turnstile: TURNSTILE ? process.env.STELLA_TURNSTILE_SITEKEY : null });
  // pairing: a signed-in device (PC) shows a QR, the phone claims it
  if (req.method === 'POST' && p === '/api/pair') {
    const u = users.byToken(bearer(req)); if (!u) return json(res, 401, { error: 'unauthorized' });
    return json(res, 200, { code: users.createPair(u) });
  }
  if (req.method === 'POST' && p === '/api/pair/claim') {
    if (limited(req, 'pair', 10)) return json(res, 429, { error: 'Слишком много попыток, подождите 10 минут' });
    try { const b = await body(req); return json(res, 200, users.claimPair(b.code, meta(req))); } catch (e) { return json(res, 400, { error: e.message }); }
  }
  if (req.method === 'GET' && p === '/api/me') {
    const u = users.byToken(bearer(req)); if (!u) return json(res, 401, { error: 'unauthorized' });
    return json(res, 200, { user: users.publicUser(u), agy: !!agent.agyPath(u) });
  }

  // PC uploads a snapshot of the project folder while a task runs (for failover)
  if (req.method === 'POST' && p === '/api/pc/snapshot') {
    const u = users.byToken(bearer(req)); if (!u) return json(res, 401, { error: 'unauthorized' });
    try { const r = await failover.saveSnapshot(u, url.searchParams.get('chat'), url.searchParams.get('folder'), req); return json(res, 200, r); }
    catch (e) { return json(res, 413, { error: e.message }); }
  }
  // Stella on the PC fetches a site login to type it into the browser itself (the model never sees it)
  if (req.method === 'GET' && p === '/api/services/secret') {
    const u = users.byToken(bearer(req)); if (!u) return json(res, 401, { error: 'unauthorized' });
    if (limited(req, 'secret', 30, 600e3)) return json(res, 429, { error: 'too many requests' });
    const name = String(url.searchParams.get('name') || '');
    if (name === 'email') return json(res, 403, { error: 'not allowed' });
    const s = services.secret(u, name);
    if (!s) return json(res, 404, { error: 'Сервис не подключён' });
    users.audit('secret_used:' + name, u.name, meta(req));
    return json(res, 200, { login: s.login, password: s.password, url: s.url });
  }
  // grading: photo upload (raw body), photo view, Excel export
  const g = p.match(/^\/api\/grading\/([\w-]+)\/(upload|photo|export)$/);
  if (g) {
    const u = users.byToken(bearer(req)); if (!u) return json(res, 401, { error: 'unauthorized' });
    try {
      if (g[2] === 'upload' && req.method === 'POST') return json(res, 200, await grading.upload(u, g[1], url.searchParams.get('name') || 'photo.jpg', url.searchParams.get('kind'), req, url.searchParams.has('seq') ? Number(url.searchParams.get('seq')) : null));
      if (g[2] === 'photo') { const f = grading.photo(u, g[1], url.searchParams.get('name')); if (!f) return json(res, 404, { error: 'not found' }); res.writeHead(200, { 'content-type': MIME[require('path').extname(f).toLowerCase()] || 'image/jpeg', 'cache-control': 'private, max-age=3600' }); return fs.createReadStream(f).pipe(res); }
      if (g[2] === 'export') { const buf = await grading.exportXlsx(u, g[1]); res.writeHead(200, { 'content-type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'content-disposition': 'attachment; filename="grades.xlsx"' }); return res.end(Buffer.from(buf)); }
    } catch (e) { return json(res, 400, { error: e.message }); }
  }
  // PC downloads results that the server produced
  if (req.method === 'GET' && p === '/api/server/folder') {
    const u = users.byToken(bearer(req)); if (!u) return json(res, 401, { error: 'unauthorized' });
    return failover.exportFolder(u, url.searchParams.get('name'), res);
  }
  // tools for the agent (WhatsApp MCP). Server agents use the account's mcpToken, the PC uses its session token.
  const m = p.match(/^\/api\/mcp\/([a-z_]+)$/);
  if (req.method === 'POST' && m) {
    const tok = bearer(req);
    const u = users.byMcpToken(tok) || users.byToken(tok);
    if (!u) return json(res, 401, { error: 'unauthorized' });
    try {
      const a = await body(req);
      let result;
      switch (m[1]) {
        case 'list_chats': result = wa.listChats(u, a.query, Math.min(100, a.limit || 30)); break;
        case 'read_chat': result = wa.readChat(u, a.contact, a.limit || 40); break;
        case 'writing_style': result = { examples: wa.styleSamples(u, a.contact, 60), hint: "Imitate these exactly: same language, length, punctuation, emoji and casing. Don't sound like an assistant." }; break;
        case 'send_message': result = await wa.sendText(u, a.contact, a.text, { expectReply: a.expect_reply !== false, origin: users.byMcpToken(tok) ? null : agentOriginFromPc(u) }); break;
        case 'notify_user': emit(u.name, { t: 'notify', title: String(a.title || 'Stella').slice(0, 120), body: String(a.text || '').slice(0, 500) }); result = 'notified'; break;
        case 'email_list': result = await services.emailList(u, { folder: a.folder, limit: a.limit || 15, unread: !!a.unread, search: a.search || '' }); break;
        case 'email_read': result = await services.emailRead(u, { id: a.id, folder: a.folder }); break;
        case 'email_send': result = await services.emailSend(u, { to: a.to, subject: a.subject, text: a.text, cc: a.cc }); emit(u.name, { t: 'notify', title: '✉️ Письмо отправлено', body: `${a.to}: ${String(a.subject || '').slice(0, 80)}` }); break;
        case 'create_presentation':
        case 'create_document': {
          const dir = require('path').join(u.home, 'workspace', 'Документы');
          const r = m[1] === 'create_presentation' ? await office.createPresentation(a, dir) : await office.createDocument(a, dir);
          if (u.uid != null) { try { require('child_process').execFileSync('chown', ['-R', `${u.uid}:${u.gid}`, dir]); } catch {} }
          const shown = sandbox.mode() === 'docker' ? sandbox.toIn(u, r.file) : r.file;
          emit(u.name, { t: 'notify', title: m[1] === 'create_presentation' ? '📊 Презентация готова' : '📄 Документ готов', body: require('path').basename(r.file) });
          result = `Created ${shown}. The user can download it from the server; if they want it on the PC, use transfer or tell them.`;
          break;
        }
        case 'create_group': result = await wa.createGroup(u, a.name, a.contacts || []); break;
        case 'broadcast': result = await wa.broadcast(u, a.contacts || [], a.text); break;
        case 'wait_for_reply': result = (await wa.waitForReply(u, a.contact, a.timeout_seconds || 300)) || 'No reply yet (timeout). Stella will forward the reply to the user when it arrives.'; break;
        default: return json(res, 404, { error: 'unknown tool' });
      }
      return json(res, 200, { result });
    } catch (e) { return json(res, 200, { error: e.message }); }
  }
  return json(res, 404, { error: 'not found' });
}
function agentOriginFromPc(u) { return agent.lastOrigin.get(u.name) || null; }

function serveStatic(req, res, url) {
  let p = decodeURIComponent(url.pathname);
  if (VENDOR[p]) return fileOut(res, VENDOR[p]);
  if (p === '/') p = '/index.html';
  const f = path.normalize(path.join(PUBLIC, p));
  if (!f.startsWith(PUBLIC) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) return fileOut(res, path.join(PUBLIC, 'index.html'));
  fileOut(res, f);
}
function fileOut(res, f) {
  res.writeHead(200, { 'content-type': MIME[path.extname(f)] || 'application/octet-stream', 'cache-control': f.endsWith('sw.js') ? 'no-cache' : 'public, max-age=300' });
  fs.createReadStream(f).pipe(res);
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://x');
  res.setHeader('x-content-type-options', 'nosniff');
  res.setHeader('referrer-policy', 'no-referrer');
  res.setHeader('x-frame-options', 'DENY');
  res.setHeader('cross-origin-opener-policy', 'same-origin');
  res.setHeader('permissions-policy', 'camera=(), microphone=(), geolocation=(), payment=(), usb=()');
  res.setHeader('content-security-policy', "default-src 'self'; script-src 'self' https://challenges.cloudflare.com; frame-src https://challenges.cloudflare.com; connect-src 'self' wss: ws:; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'");
  if (req.headers['x-forwarded-proto'] === 'https' || req.headers['cf-connecting-ip']) res.setHeader('strict-transport-security', 'max-age=63072000; includeSubDomains');
  if (url.pathname.startsWith('/api/') && limited(req, 'api', 600, 60e3)) return json(res, 429, { error: 'Слишком много запросов' });
  if (url.pathname.startsWith('/api/')) return api(req, res, url).catch(e => json(res, 500, { error: e.message }));
  serveStatic(req, res, url);
});

/* ================================================================== */
/* WebSocket                                                           */
/* ================================================================== */
const wss = new WebSocketServer({ server, path: '/ws', maxPayload: 8 * 1024 * 1024 });
wss.on('connection', (ws) => {
  let me = null, conn = null;
  const authTimer = setTimeout(() => ws.close(), 10000);
  ws.alive = true;
  ws.on('pong', () => { ws.alive = true; });
  let msgCount = 0, msgWindow = Date.now();
  ws.on('message', async raw => {
    if (Date.now() - msgWindow > 1000) { msgWindow = Date.now(); msgCount = 0; }
    if (++msgCount > 60) return;                                   // flood protection: max 60 messages/s per connection
    let m; try { m = JSON.parse(raw.toString()); } catch { return; }
    if (!me) {
      if (m.t !== 'auth') return;
      me = users.byToken(m.token);
      if (!me) { ws.send(JSON.stringify({ t: 'auth.error' })); return ws.close(); }
      if (devices(me.name).size >= 20) { ws.send(JSON.stringify({ t: 'error', text: 'Слишком много подключённых устройств' })); return ws.close(); }
      ws.token = m.token;
      clearTimeout(authTimer);
      conn = { ws, device: m.device === 'pc' ? 'pc' : 'phone', label: String(m.label || '').slice(0, 60) };
      devices(me.name).add(conn);
      if (conn.device === 'pc') { pc(me.name).online = true; toPhones(me.name, { t: 'pc.online', online: true, label: conn.label }); setTimeout(() => failover.pcReconnected(me), 1500); }
      sendTo(conn, {
        t: 'hello', user: users.publicUser(me), agy: !!agent.agyPath(me),
        pcOnline: pc(me.name).online,
        serverChats: agent.chats(me).map(agent.summary),
        pcChats: [...pc(me.name).chats.values()].map(c => agent.summary(c)),
        wa: wa.overview(me), sharedKey: !!process.env.STELLA_GEMINI_API_KEY,
        profile: services.getProfile(me), services: services.list(me),
        settings: me.settings || { mode: 'yolo' }
      });
      return;
    }
    try { await onMsg(me, conn, m); } catch (e) { sendTo(conn, { t: 'error', text: e.message, ref: m.t }); }
  });
  ws.on('close', () => {
    clearTimeout(authTimer);
    if (!me) return;
    devices(me.name).delete(conn);
    if (conn.device === 'pc' && ![...devices(me.name)].some(c => c.device === 'pc')) {
      pc(me.name).online = false; toPhones(me.name, { t: 'pc.online', online: false });
      failover.pcDisconnected(me, pc(me.name));
    }
  });
});

// heartbeat: a PC that lost power never closes its socket — detect it within ~30 s
setInterval(() => {
  for (const ws of wss.clients) {
    if (!ws.alive) { try { ws.terminate(); } catch {} continue; }
    ws.alive = false;
    try { ws.ping(); } catch {}
  }
}, 15000);

async function onMsg(u, conn, m) {
  const P = pc(u.name);
  switch (m.t) {
    /* ---- server agent ---- */
    case 'server.chat.get': { const c = agent.findChat(u, m.chatId); if (c) sendTo(conn, { t: 'chat', where: 'server', chat: c }); break; }
    case 'server.chat.new': { const c = agent.newChat(u); emit(u.name, { t: 'chat', where: 'server', chat: c }); break; }
    case 'server.chat.delete': agent.deleteChat(u, m.chatId); emit(u.name, { t: 'chat.deleted', where: 'server', chatId: m.chatId }); break;
    case 'server.send': agent.send(u, m.chatId, String(m.text || '').slice(0, 20000)); break;
    case 'server.stop': agent.stop(u, m.chatId); break;
    /* ---- grading (photos of student work) ---- */
    case 'grading.list': sendTo(conn, { t: 'grading.list', list: grading.list(u) }); break;
    case 'grading.create': sendTo(conn, { t: 'grading', batch: grading.create(u, m.spec || {}) }); break;
    case 'grading.get': { const b = grading.get(u, m.id); if (b) sendTo(conn, { t: 'grading', batch: b }); break; }
    case 'grading.start': grading.start(u, m.id); break;
    case 'grading.stop': grading.stopBatch(u, m.id); break;
    case 'grading.edit': grading.edit(u, m.id, m.workId, m.patch || {}); break;
    case 'grading.recheck': grading.recheck(u, m.id, m.workId); break;
    case 'grading.delete': grading.remove(u, m.id); sendTo(conn, { t: 'grading.list', list: grading.list(u) }); break;
    case 'grading.toBilimclass': {
      if (!pc(u.name).online) throw new Error('Компьютер не в сети: включите Stella на ПК и «Браузер для агента»');
      const b = grading.get(u, m.id); let rows = grading.rows(u, m.id).filter(r => !r.review);
      // anonymous check: names live only on the teacher's phone and are sent just for this one entry (not stored, never with photos)
      if (b && b.anonymous) {
        const names = m.names && typeof m.names === 'object' ? m.names : {};
        rows = rows.map(r => ({ ...r, student: String(names[r.no] || '').replace(/[\r\n]/g, ' ').trim().slice(0, 100) })).filter(r => r.student);
      }
      if (!rows.length) throw new Error('Нет проверенных работ без пометки «проверить»' + (b && b.anonymous ? ' и с подписанным именем' : ''));
      const table = rows.map((r, i) => `${i + 1}. ${r.student} — ${r.grade} (${r.total}/${r.max})`).join('\n');
      toPc(u.name, { t: 'pc.run', chatId: 'grades-' + m.id, title: '📝 Оценки: ' + b.title,
        display: `📝 Выставить оценки в BilimClass: ${b.title} (${rows.length} учеников)`,
        text: `Открой BilimClass в браузере агента и войди через stella-desktop service_login {"service":"bilimclass"}. ` +
          `Найди журнал: предмет «${b.subject}», класс ${b.klass}, работа «${b.title}». Выставь оценки ТОЧНО по списку (учитель проверил и подтвердил):\n${table}\n` +
          'Если ученика нет в журнале или фамилия отличается — не выставляй ему, а перечисли таких в конце. Сохрани журнал и кратко отчитайся.' });
      sendTo(conn, { t: 'notify', title: 'Отправлено на компьютер', body: `Агент выставит ${rows.length} оценок в BilimClass` });
      break;
    }

    /* ---- team of agents ---- */
    case 'team.start': team.start(u, String(m.text || '').slice(0, 20000)).catch(e => sendTo(conn, { t: 'error', text: 'Команда: ' + e.message })); break;
    case 'team.stop': team.stop(u, String(m.teamId || '')); break;

    /* ---- profile ("about me") + services ---- */
    case 'profile.get': sendTo(conn, { t: 'profile', profile: services.getProfile(u) }); break;
    case 'profile.set': { const pr = services.setProfile(u, m.profile || {}); emit(u.name, { t: 'profile', profile: pr }); break; }
    case 'services.get': sendTo(conn, { t: 'services', list: services.list(u) }); break;
    case 'services.set': { const l = services.setService(u, String(m.name || ''), m.data || {}); emit(u.name, { t: 'services', list: l }); if (m.name === 'email') { try { await services.emailTest(u); sendTo(conn, { t: 'notify', title: '✅ Почта подключена' }); } catch (e) { sendTo(conn, { t: 'error', text: 'Не удалось войти в почту: ' + (e.authenticationFailed ? 'неверный адрес или пароль' : (e.responseText || e.code || e.message || 'ошибка соединения')) + '. Для Gmail/Яндекс/Mail.ru нужен «пароль приложения».' }); } } break; }
    case 'services.remove': emit(u.name, { t: 'services', list: services.removeService(u, String(m.name || '')) }); break;

    /* ---- account security ---- */
    case 'security.get': sendTo(conn, { t: 'security', twofa: !!u.totp, sessions: users.sessions(u, conn.ws.token) }); break;
    case 'security.2fa.setup': { const r = users.totpSetup(u); const qr = await require('qrcode').toDataURL(r.uri, { margin: 1, width: 240 }); sendTo(conn, { t: 'security.2fa.qr', secret: r.secret, qr }); break; }
    case 'security.2fa.enable': users.totpEnable(u, m.code); sendTo(conn, { t: 'security', twofa: true, sessions: users.sessions(u, conn.ws.token) }); sendTo(conn, { t: 'notify', title: 'Двухфакторная защита включена' }); break;
    case 'security.2fa.disable': users.totpDisable(u, m.password, m.code); sendTo(conn, { t: 'security', twofa: false, sessions: users.sessions(u, conn.ws.token) }); break;
    case 'security.revoke': users.revokeSession(u, m.id); sendTo(conn, { t: 'security', twofa: !!u.totp, sessions: users.sessions(u, conn.ws.token) }); break;
    case 'security.revokeOthers': users.revokeOthers(u, conn.ws.token); for (const c of devices(u.name)) if (c !== conn && c.ws.token !== conn.ws.token) { try { c.ws.close(); } catch {} } sendTo(conn, { t: 'security', twofa: !!u.totp, sessions: users.sessions(u, conn.ws.token) }); break;
    case 'security.password': users.changePassword(u, m.old, m.new, conn.ws.token); for (const c of devices(u.name)) if (c.ws.token !== conn.ws.token) { try { c.ws.close(); } catch {} } sendTo(conn, { t: 'notify', title: 'Пароль изменён', body: 'Все остальные устройства вышли из аккаунта.' }); break;
    case 'admin.unlock': requireAdmin(u); users.unlock(m.name); sendTo(conn, adminState()); break;

    case 'settings.set': u.settings = Object.assign(u.settings || {}, { mode: ['yolo', 'accept-edits', 'plan', 'default'].includes(m.mode) ? m.mode : 'yolo' }); users._save(); emit(u.name, { t: 'settings', settings: u.settings }); break;

    /* ---- terminal (agy sign-in) ---- */
    case 'term.open': { const t = agent.termOpen(u); sendTo(conn, { t: 'term.data', data: t.buf }); break; }
    case 'term.restart': agent.termRestart(u); break;
    case 'term.input': agent.termInput(u, String(m.data || '')); break;
    case 'term.resize': agent.termResize(u, m.cols | 0 || 100, m.rows | 0 || 30); break;

    /* ---- PC (Stella desktop) -> server ---- */
    case 'pc.chats': if (conn.device === 'pc') { const live = P.running || new Map(); const keep = [...live.keys()].map(id => P.chats.get(id)).filter(Boolean); P.chats = new Map((m.chats || []).slice(0, 100).map(c => [c.id, c])); keep.forEach(c => P.chats.set(c.id, c)); toPhones(u.name, { t: 'chats', where: 'pc', list: [...P.chats.values()].map(c => agent.summary(c)) }); } break;
    case 'pc.chat': if (conn.device === 'pc' && m.chat) { P.chats.set(m.chat.id, m.chat); toPhones(u.name, { t: 'chat', where: 'pc', chat: m.chat }); if (m.forTransfer) agent.importFromPc(u, m.chat, m.continueText); } break;
    case 'pc.ev': if (conn.device === 'pc') { failover.applyPcEvent(P, m); if (m.type === 'done') team.pcDone(u.name, m.chatId, P.chats.get(m.chatId)); if (m.started) agent.lastOrigin.set(u.name, { where: 'pc', chatId: m.chatId }); toPhones(u.name, Object.assign({}, m, { t: 'ev', where: 'pc' })); } break;
    case 'pc.status': if (conn.device === 'pc') toPhones(u.name, { t: 'pc.status', status: m.status }); break;

    /* ---- phone -> PC ---- */
    case 'pc.chat.get': { const c = P.chats.get(m.chatId); if (c) sendTo(conn, { t: 'chat', where: 'pc', chat: c }); else toPc(u.name, { t: 'pc.export', chatId: m.chatId }); break; }
    case 'pc.send': if (!toPc(u.name, { t: 'pc.run', chatId: m.chatId || null, text: String(m.text || '') })) throw new Error('Компьютер не в сети'); break;
    case 'pc.stop': toPc(u.name, { t: 'pc.stop', chatId: m.chatId }); break;

    /* ---- transfer ---- */
    case 'transfer.toServer': {        // PC chat -> continue on server
      if (!toPc(u.name, { t: 'pc.export', chatId: m.chatId, forTransfer: true, continueText: m.text || '' })) {
        const c = P.chats.get(m.chatId);
        if (!c) throw new Error('Компьютер не в сети, а копии чата на сервере нет');
        agent.importFromPc(u, c, m.text);
      }
      break;
    }
    case 'transfer.toPc': {           // server chat -> continue on PC
      const c = agent.findChat(u, m.chatId); if (!c) throw new Error('Чат не найден');
      if (!toPc(u.name, { t: 'pc.import', chat: { title: c.title, messages: c.messages.filter(x => x.text).map(x => ({ role: x.role, text: x.text })) }, continueText: m.text || '' })) throw new Error('Компьютер не в сети');
      break;
    }

    /* ---- admin: invites and accounts ---- */
    case 'admin.list': requireAdmin(u); sendTo(conn, adminState()); break;
    case 'admin.invite': requireAdmin(u); users.createInvite(u.name, m.note, m.maxUses || 1); sendTo(conn, adminState()); break;
    case 'admin.revoke': requireAdmin(u); users.revokeInvite(m.code); sendTo(conn, adminState()); break;
    case 'admin.disable': requireAdmin(u); users.setDisabled(m.name, !!m.on); if (m.on) kick(m.name); sendTo(conn, adminState()); break;
    case 'admin.delete': requireAdmin(u); { const t = users.get(m.name); if (t) { agent.stopAll(t); require('./lib/sandbox').removeContainer(t); } kick(m.name); users.remove(m.name); } sendTo(conn, adminState()); break;

    /* ---- WhatsApp ---- */
    case 'wa.connect': sendTo(conn, Object.assign({ t: 'wa.status' }, await wa.connect(u))); break;
    case 'wa.logout': await wa.logout(u); break;
    case 'wa.overview': sendTo(conn, Object.assign({ t: 'wa.overview' }, wa.overview(u))); break;
    case 'wa.search': sendTo(conn, { t: 'wa.chats', list: wa.listChats(u, m.query, 60) }); break;
    case 'wa.auto': { const r = wa.setAuto(u, m.jid, !!m.on); emit(u.name, { t: 'wa.autoChanged', jid: m.jid, on: !!m.on, chat: r }); break; }
  }
}

function requireAdmin(u) { if (!u.admin) throw new Error('Только для администратора'); }
function adminState() {
  return {
    t: 'admin.state',
    users: users.all().map(x => Object.assign(users.adminView(x), { online: [...devices(x.name)].map(c => c.device), running: agent.runningCount(x) })),
    invites: users.listInvites(),
    signup: process.env.STELLA_SIGNUP || 'invite', sharedKey: !!process.env.STELLA_GEMINI_API_KEY
  };
}
function kick(name) { for (const c of devices(name)) { try { c.ws.close(); } catch {} } }

server.listen(PORT, HOST, () => {
  console.log(`Stella Cloud on http://${HOST}:${PORT}  (data: ${require('./lib/store').DATA}, root: ${users.isRoot})`);
  wa.resumeAll();
});

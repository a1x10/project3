// Stella on the PC <-> Stella Cloud (your server).
// The phone sees what the PC agent does, can give it tasks, and work can move PC <-> server.
const WebSocket = require('ws');
const path = require('path');
const fs = require('fs');
const os = require('os');

let H = { log: () => {}, send: () => {}, getSettings: () => ({}), saveSettings: () => {}, readJsonLoose: () => ({}) };
let ws = null, timer = null, retry = 0, status = 'off', lastChats = [];

function init(hooks) { H = Object.assign(H, hooks); const s = H.getSettings(); if (s.cloudUrl && s.cloudToken) connect(); }
function defaultServer() {
  try { return JSON.parse(fs.readFileSync(path.join(__dirname, 'config.json'), 'utf8')).server || ''; } catch { return ''; }
}
const norm = u => String(u || '').trim().replace(/\/+$/, '').replace(/^(?!https?:\/\/)/, 'https://');

function setStatus(st, extra = {}) { status = st; H.send('cloud:status', Object.assign({ status: st, user: H.getSettings().cloudUser || '', url: H.getSettings().cloudUrl || '' }, extra)); }
function getStatus() { const s = H.getSettings(); return { status, user: s.cloudUser || '', url: s.cloudUrl || defaultServer(), signedIn: !!s.cloudToken, fixedServer: !!defaultServer() }; }

// QR code for the phone: opens the server and signs in to the same account
async function pairQr() {
  const s = H.getSettings();
  const r = await fetch(s.cloudUrl + '/api/pair', { method: 'POST', headers: { authorization: 'Bearer ' + s.cloudToken }, signal: AbortSignal.timeout(15000) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok || !j.code) throw new Error(j.error || 'Сервер не дал код');
  const link = s.cloudUrl + '/#pair=' + j.code;
  const qr = await require('qrcode').toDataURL(link, { margin: 1, width: 300 });
  return { link, qr, code: j.code };
}

async function login(url, username, password, invite, mode = 'login') {
  url = norm(url || defaultServer());
  if (!/^https?:\/\/[^/]+/.test(url)) throw new Error('Укажите адрес сервера');
  let r;
  try { r = await fetch(url + '/api/' + (mode === 'register' ? 'register' : 'login'), { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ username, password, invite }), signal: AbortSignal.timeout(20000) }); }
  catch (e) { throw new Error('Сервер не отвечает: ' + url); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok || !j.token) throw new Error(j.error || ('Сервер ответил ' + r.status));
  H.saveSettings({ cloudUrl: url, cloudToken: j.token, cloudUser: j.user.name, cloudAdmin: !!j.user.admin });
  registerWhatsAppMcp(true);
  connect();
  return getStatus();
}

function logout() {
  const s = H.getSettings();
  if (s.cloudUrl && s.cloudToken) fetch(s.cloudUrl + '/api/logout', { method: 'POST', headers: { authorization: 'Bearer ' + s.cloudToken } }).catch(() => {});
  H.saveSettings({ cloudToken: '', cloudUser: '' });
  registerWhatsAppMcp(false);
  clearTimeout(timer);
  if (ws) { try { ws.close(); } catch {} ws = null; }
  setStatus('off');
}

function connect() {
  const s = H.getSettings();
  if (!s.cloudUrl || !s.cloudToken) return;
  clearTimeout(timer);
  if (ws) { try { ws.removeAllListeners(); ws.close(); } catch {} }
  setStatus('connecting');
  const url = s.cloudUrl.replace(/^http/, 'ws') + '/ws';
  const sock = new WebSocket(url, { handshakeTimeout: 15000 });
  ws = sock;
  sock.on('open', () => {
    retry = 0;
    sock.send(JSON.stringify({ t: 'auth', token: s.cloudToken, device: 'pc', label: os.hostname() }));
  });
  sock.on('message', raw => {
    let m; try { m = JSON.parse(raw.toString()); } catch { return; }
    if (m.t === 'auth.error') { H.saveSettings({ cloudToken: '' }); setStatus('error', { error: 'Сессия закончилась или аккаунт заблокирован — войдите снова' }); H.send('cloud:signed-out'); try { sock.close(); } catch {} return; }
    if (m.t === 'hello') { setStatus('online'); if (lastChats.length) push({ t: 'pc.chats', chats: lastChats }); registerWhatsAppMcp(true); return; }
    // commands from the phone / server
    if (['pc.run', 'pc.stop', 'pc.export', 'pc.import'].includes(m.t)) H.send('cloud:command', m);
    if (m.t === 'pc.failover') { pendingFailover.push(...(m.moved || [])); H.send('cloud:failover', { moved: [] }); }
    if (m.t === 'wa.reply' && m.origin && m.origin.where === 'pc') H.send('cloud:wa-reply', m);
    if (m.t === 'notify' && m.where === 'pc') H.send('cloud:notify', m);
  });
  sock.on('close', () => {
    if (ws !== sock) return;
    const st = H.getSettings();
    if (!st.cloudToken) return setStatus('off');
    setStatus('reconnecting');
    timer = setTimeout(connect, Math.min(30000, 1000 * 2 ** retry++));
  });
  sock.on('error', e => H.log('cloud ws error', e.message));
}

function push(m) { if (ws && ws.readyState === 1) { try { ws.send(JSON.stringify(m)); return true; } catch {} } return false; }

// renderer -> server
function syncChats(chats) {
  lastChats = (chats || []).slice(0, 60).map(c => ({
    id: c.id, title: c.title, updated: c.updated || c.created || Date.now(),
    busy: (c.messages || []).some(m => m.busy),
    messages: (c.messages || []).slice(-60).map(m => ({ id: m.id, role: m.role, text: (m.text || '').slice(0, 20000), tools: (m.tools || []).slice(-20), error: m.error, busy: !!m.busy, started: m.started, duration: m.duration, status: m.status, note: m.note }))
  }));
  push({ t: 'pc.chats', chats: lastChats });
}
function sendChat(chat, extra = {}) {
  const c = { id: chat.id, title: chat.title, updated: Date.now(), messages: (chat.messages || []).slice(-80).map(m => ({ id: m.id, role: m.role, text: m.text || '', tools: m.tools || [], error: m.error, busy: !!m.busy, started: m.started, duration: m.duration, status: m.status })) };
  return push(Object.assign({ t: 'pc.chat', chat: c }, extra));
}
function event(ev) { push(Object.assign({ t: 'pc.ev' }, ev)); }

// WhatsApp tools for the agent on the PC too (they talk to the server, where WhatsApp is connected)
function registerWhatsAppMcp(on) {
  try {
    const s = H.getSettings();
    const mcpFile = path.join(os.homedir(), '.gemini', 'config', 'mcp_config.json');
    const setFile = path.join(os.homedir(), '.gemini', 'antigravity-cli', 'settings.json');
    const mcp = H.readJsonLoose(mcpFile); mcp.mcpServers = mcp.mcpServers || {};
    const st = H.readJsonLoose(setFile); st.permissions = st.permissions || {};
    const allow = new Set(st.permissions.allow || []);
    if (on && s.cloudUrl && s.cloudToken) {
      let script = path.join(__dirname, 'mcp-whatsapp.js');
      script = script.replace('app.asar' + path.sep, 'app.asar.unpacked' + path.sep);
      mcp.mcpServers['stella-whatsapp'] = { command: process.execPath, args: [script], env: { ELECTRON_RUN_AS_NODE: '1', STELLA_URL: s.cloudUrl, STELLA_TOKEN: s.cloudToken } };
      allow.add('mcp(stella-whatsapp/*)');
    } else {
      delete mcp.mcpServers['stella-whatsapp'];
      allow.delete('mcp(stella-whatsapp/*)');
    }
    st.permissions.allow = [...allow];
    for (const [f, v] of [[mcpFile, mcp], [setFile, st]]) { fs.mkdirSync(path.dirname(f), { recursive: true }); fs.writeFileSync(f, JSON.stringify(v, null, 2)); }
  } catch (e) { H.log('whatsapp mcp register failed', e.message); }
}

function agentNote() {
  const s = H.getSettings();
  if (!(status === 'online' && s.cloudToken)) return '';
  return '- WhatsApp: the "stella-whatsapp" MCP tools (list_chats, read_chat, writing_style, send_message, wait_for_reply) use the user\'s WhatsApp. ' +
    'Message people ONLY when the user explicitly asks; write in the user\'s own style (call writing_style first). Replies are forwarded to the user automatically.\n';
}

/* ================================================================== */
/* failover: snapshots of the project folder while a task runs          */
/* ================================================================== */
let pendingFailover = [];               // kept until the window has loaded its chats
function takeFailover() { const x = pendingFailover; pendingFailover = []; return x; }
const EXCLUDE = ['node_modules', '.venv', 'venv', '__pycache__', '.next', '.nuxt', 'dist', 'build', 'target', '.cache', '.gradle', '.idea', '.vs'];
const LIMIT = 300 * 1024 * 1024;
const snapTimers = new Map();

function folderSize(dir, limit) {
  let total = 0;
  const stack = [dir];
  while (stack.length) {
    const d = stack.pop();
    let list = [];
    try { list = fs.readdirSync(d, { withFileTypes: true }); } catch { continue; }
    for (const e of list) {
      if (EXCLUDE.includes(e.name)) continue;
      const p = path.join(d, e.name);
      if (e.isDirectory()) stack.push(p);
      else if (e.isFile()) { try { total += fs.statSync(p).size; } catch {} if (total > limit) return total; }
    }
  }
  return total;
}
function snapshotable(ws) {
  if (!ws || !fs.existsSync(ws)) return 'папка не найдена';
  const norm = path.resolve(ws);
  if (norm === path.resolve(os.homedir()) || norm === path.parse(norm).root) return 'рабочая папка — это весь профиль/диск; выберите папку проекта слева';
  if (folderSize(norm, LIMIT) > LIMIT) return 'папка проекта больше 300 МБ';
  return null;
}
function uploadSnapshot(chatId, ws) {
  const s = H.getSettings();
  if (status !== 'online' || !s.cloudToken) return;
  const why = snapshotable(ws);
  if (why) { H.log('snapshot skipped:', why); H.send('cloud:snapshot', { chatId, ok: false, why }); return; }
  const u = new URL(s.cloudUrl + '/api/pc/snapshot?chat=' + encodeURIComponent(chatId) + '&folder=' + encodeURIComponent(path.basename(ws)));
  const mod = u.protocol === 'https:' ? require('https') : require('http');
  const args = ['-czf', '-'];
  for (const x of EXCLUDE) args.push('--exclude', x);
  args.push('-C', ws, '.');
  const tar = require('child_process').spawn('tar', args, { windowsHide: true });
  const req = mod.request(u, { method: 'POST', headers: { authorization: 'Bearer ' + s.cloudToken, 'content-type': 'application/gzip', 'transfer-encoding': 'chunked' }, timeout: 300000 }, res => {
    let b = ''; res.on('data', d => b += d);
    res.on('end', () => { H.log('snapshot', chatId, res.statusCode, b.slice(0, 120)); H.send('cloud:snapshot', { chatId, ok: res.statusCode === 200 }); });
  });
  req.on('error', e => H.log('snapshot upload error', e.message));
  tar.on('error', e => { H.log('tar error', e.message); req.destroy(); });
  tar.stdout.pipe(req);
}
function taskStarted(chatId, ws) {
  taskDone(chatId);
  uploadSnapshot(chatId, ws);
  snapTimers.set(chatId, setInterval(() => uploadSnapshot(chatId, ws), 3 * 60 * 1000));
}
function taskDone(chatId) { clearInterval(snapTimers.get(chatId)); snapTimers.delete(chatId); }

// download what the server produced into "<workspace>-с-сервера-<date>" (never overwrites your files)
async function pullFolder(folder, workspace) {
  const s = H.getSettings();
  const r = await fetch(s.cloudUrl + '/api/server/folder?name=' + encodeURIComponent(folder), { headers: { authorization: 'Bearer ' + s.cloudToken } });
  if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.error || 'сервер ответил ' + r.status); }
  const tmp = path.join(os.tmpdir(), 'stella-pull-' + Date.now() + '.tar.gz');
  fs.writeFileSync(tmp, Buffer.from(await r.arrayBuffer()));
  const stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-');
  const base = workspace && fs.existsSync(workspace) && path.resolve(workspace) !== path.resolve(os.homedir()) ? path.resolve(workspace) : path.join(os.homedir(), 'Documents', folder);
  const dest = base + '-с-сервера-' + stamp;
  fs.mkdirSync(dest, { recursive: true });
  await new Promise((resolve, reject) => {
    const p = require('child_process').spawn('tar', ['-xzf', tmp, '-C', dest], { windowsHide: true });
    p.on('close', c => c === 0 ? resolve() : reject(new Error('tar exit ' + c)));
    p.on('error', reject);
  });
  try { fs.unlinkSync(tmp); } catch {}
  return dest;
}

module.exports = { takeFailover, taskStarted, taskDone, pullFolder, pairQr, defaultServer, init, login, logout, getStatus, syncChats, sendChat, event, agentNote, push };

// Per-account agent on the server: chats, `agy -p --output-format stream-json` runs,
// an interactive terminal (for `agy` sign-in), and transfer of work between PC and server.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { spawn, execSync } = require('child_process');
const { readJson, saveLater } = require('./store');
const users = require('./users');
const sandbox = require('./sandbox');

let pty = null;
try { pty = require('node-pty'); } catch { pty = null; }

const uid = () => Date.now().toString(36) + crypto.randomBytes(3).toString('hex');
let emit = () => {};                     // (username, message) -> broadcast to that user's devices
let PORT = 8787;
function setup(opts) { emit = opts.emit; PORT = opts.port; }

/* ------------------------------------------------------------------ */
/* agy binary + environment for an account                              */
/* ------------------------------------------------------------------ */
function agyPath(u) {
  const own = u && u.home ? [path.join(u.home, '.local', 'bin', 'agy')] : [];
  for (const p of [process.env.AGY_PATH, ...own, '/usr/local/bin/agy', '/usr/bin/agy'].filter(Boolean)) if (fs.existsSync(p)) return p;
  try { return execSync('command -v agy', { encoding: 'utf8', shell: '/bin/bash' }).trim() || null; } catch { return null; }
}

function envFor(u) {
  const shared = process.env.STELLA_GEMINI_API_KEY ? { GEMINI_API_KEY: process.env.STELLA_GEMINI_API_KEY } : {};
  const base = Object.assign({}, process.env);
  for (const k of Object.keys(base)) if (/^STELLA_|_KEY$|TOKEN|SECRET|PASSWORD/i.test(k)) delete base[k];   // never leak server secrets to agents
  return Object.assign(base, shared, {
    HOME: u.home, USER: u.sys || process.env.USER, LOGNAME: u.sys || process.env.LOGNAME,
    PATH: `${path.join(u.home, '.local', 'bin')}:/usr/local/bin:/usr/bin:/bin`,
    TERM: 'xterm-256color', NO_COLOR: '1', LANG: 'C.UTF-8'
  });
}
const spawnOpts = (u, extra = {}) => Object.assign({ cwd: path.join(u.home, 'workspace'), env: envFor(u), uid: u.uid, gid: u.gid }, extra);

// docker container / systemd scope / plain — see sandbox.js
function runner(u, bin, args, extra = {}) {
  const env = { NO_COLOR: '1', TERM: 'xterm-256color', LANG: 'C.UTF-8' };
  if (process.env.STELLA_GEMINI_API_KEY) env.GEMINI_API_KEY = process.env.STELLA_GEMINI_API_KEY;
  return sandbox.wrap(u, bin, args, Object.assign({ env }, extra));
}
function runningCount(u) { return chats(u).filter(c => c.busy).length; }
function stopAll(u) { for (const c of chats(u)) if (c.busy) stop(u, c.id); }

// write MCP config (WhatsApp tools) + permissions into the account's agy config
function prepareAgyConfig(u) {
  const mcpFile = path.join(u.home, '.gemini', 'config', 'mcp_config.json');
  const setFile = path.join(u.home, '.gemini', 'antigravity-cli', 'settings.json');
  const mcp = readJson(mcpFile, {}); mcp.mcpServers = mcp.mcpServers || {};
  mcp.mcpServers['stella-whatsapp'] = sandbox.mcpServer(u, PORT);
  const st = readJson(setFile, {});
  if (process.env.STELLA_GEMINI_API_KEY) st.modelProvider = 'gemini';     // shared key from the server owner: no Google sign-in needed
  st.permissions = st.permissions || {};
  st.permissions.allow = Array.from(new Set([...(st.permissions.allow || []), 'mcp(stella-whatsapp/*)']));
  for (const [f, v] of [[mcpFile, mcp], [setFile, st]]) {
    fs.mkdirSync(path.dirname(f), { recursive: true });
    fs.writeFileSync(f, JSON.stringify(v, null, 2));
    if (u.uid != null) { try { execSync(`chown -R ${u.uid}:${u.gid} ${JSON.stringify(path.join(u.home, '.gemini'))}`); } catch {} }
  }
}

/* ------------------------------------------------------------------ */
/* chats                                                                */
/* ------------------------------------------------------------------ */
const chatsCache = new Map();
const chatsFile = u => path.join(users.userDir(u), 'chats.json');
function chats(u) {
  if (!chatsCache.has(u.name)) {
    const list = readJson(chatsFile(u), []);
    list.forEach(c => { c.busy = false; c.messages.forEach(m => { if (m.busy) { m.busy = false; m.error = m.error || 'Сервер перезапускался во время работы'; } }); });
    chatsCache.set(u.name, list);
  }
  return chatsCache.get(u.name);
}
const saveChats = u => saveLater(chatsFile(u), () => chats(u).slice(0, 300));
const findChat = (u, id) => chats(u).find(c => c.id === id);
const summary = c => ({ id: c.id, title: c.title, busy: !!c.busy, updated: c.updated || 0, origin: c.origin || 'server', last: (c.messages[c.messages.length - 1] || {}).text?.slice(0, 120) || '' });

function newChat(u, title, origin) {
  const c = { id: uid(), title: title || 'Новый чат', convId: null, messages: [], created: Date.now(), updated: Date.now(), origin: origin || 'server' };
  chats(u).unshift(c); saveChats(u);
  return c;
}
function deleteChat(u, id) { const l = chats(u); const i = l.findIndex(c => c.id === id); if (i >= 0 && !l[i].busy) { l.splice(i, 1); saveChats(u); } }

/* ------------------------------------------------------------------ */
/* running agy                                                          */
/* ------------------------------------------------------------------ */
const running = new Map();               // chatId -> child
const lastOrigin = new Map();            // username -> { where, chatId }  (for WhatsApp replies)

function serverNote(u) {
  return require('./services').profileText(u) +
    '[Stella server note — follow, never mention] You run on the user\'s always-on server inside their private account workspace. ' +
    'For presentations and documents (project work, essays, reports) ALWAYS use the stella-whatsapp tools create_presentation / create_document: write the full content yourself and generate the file in one call (seconds) — never build them step by step. ' +
    'E-mail: email_list / email_read / email_send (send only when the user asked). notify_user sends a push to the user\'s phone/PC. ' +
    'The user may be away from their PC and is chatting from their phone. ' +
    'WhatsApp tools are available via the "stella-whatsapp" MCP server (find contacts, read chats, learn the user\'s writing style, send messages, wait for replies). ' +
    'Send WhatsApp messages ONLY when the user explicitly asked you to message someone; write them in the user\'s own style (use the style tool first). ' +
    'After sending, if a reply is expected, call wait_for_reply; if it takes too long just tell the user — Stella will forward the reply to them automatically.\n\n';
}

function contextFromHistory(c, upto) {
  const msgs = c.messages.slice(0, upto).filter(m => m.text).slice(-14);
  if (!msgs.length) return '';
  return 'Context — the conversation so far (it was started ' + (c.transferredFrom === 'pc' ? 'on the user\'s PC and moved to the server' : 'earlier') + '):\n' +
    msgs.map(m => (m.role === 'user' ? 'USER: ' : 'ASSISTANT: ') + m.text.slice(0, 2500)).join('\n\n') + '\n\nNow continue. ';
}

function send(u, chatId, text, opts = {}) {
  const bin = agyPath(u);
  let c = chatId && findChat(u, chatId);
  if (!c) c = newChat(u, null, 'server');
  if (c.busy) throw new Error('Агент ещё работает в этом чате');
  const maxRuns = Number(process.env.STELLA_MAX_RUNS || 2);
  if (runningCount(u) >= maxRuns) throw new Error(`Одновременно можно запускать не больше ${maxRuns} задач. Дождитесь окончания или остановите одну.`);
  if (!bin) throw new Error('На сервере не установлен Antigravity CLI (agy). Запустите install.sh ещё раз.');

  const userMsg = { id: uid(), role: 'user', text, ts: Date.now() };
  if (!opts.hiddenUser) c.messages.push(userMsg);
  if (c.title === 'Новый чат') c.title = text.split('\n')[0].slice(0, 48) || 'Чат';
  const m = { id: uid(), role: 'agent', text: '', tools: [], busy: true, started: Date.now(), status: 'Думает…', log: '' };
  c.messages.push(m);
  c.busy = true; c.updated = Date.now();
  saveChats(u);
  emit(u.name, { t: 'chat', where: 'server', chat: c });
  lastOrigin.set(u.name, { where: 'server', chatId: c.id });

  prepareAgyConfig(u);
  const s = u.settings || {};
  let prompt = serverNote(u);
  if (!c.convId) prompt += contextFromHistory(c, c.messages.length - 2);
  prompt += text;
  const args = ['-p', prompt, '--output-format', 'stream-json'];
  if (c.convId) args.push('--conversation', c.convId);
  if ((s.mode || 'yolo') === 'yolo') args.push('--dangerously-skip-permissions');   // nobody can approve on a server
  else if (s.mode === 'accept-edits' || s.mode === 'plan') args.push('--mode', s.mode);

  let L;
  try { L = runner(u, bin, args, { runId: c.id }); }
  catch (e) { m.busy = false; c.busy = false; m.error = 'Не удалось запустить контейнер агента: ' + e.message; saveChats(u); emit(u.name, { t: 'chat', where: 'server', chat: c }); throw new Error(m.error); }
  const child = spawn(L.cmd, L.args, spawnOpts(u, Object.assign({ stdio: ['ignore', 'pipe', 'pipe'] }, L.opts)));
  child.stopRun = L.kill;
  running.set(c.id, child);
  const ev = e => { applyEvent(m, c, e); emit(u.name, Object.assign({ t: 'ev', where: 'server', chatId: c.id, msgId: m.id }, e)); };

  let buf = '', shown = '', finalText = null, stderr = '';
  const stepText = {}; const toolSeen = {}; let lastTextStep = null;
  const handle = o => {
    if (o.conversation_id && !c.convId) c.convId = o.conversation_id;
    if (o.event === 'step_update') {
      const st = o.step_update || {};
      if (st.conversation_id && !c.convId) c.convId = st.conversation_id;
      const idx = st.step_index ?? 'x'; const done = String(st.state || '').toUpperCase() === 'DONE';
      if (st.step_type === 'agent_response') {
        let t = typeof st.text_delta === 'string' ? st.text_delta : '';
        const prev = stepText[idx] || '';
        if (done && prev && t.startsWith(prev)) t = t.slice(prev.length); else if (done && t === prev) t = '';
        if (t) {
          if (lastTextStep !== null && lastTextStep !== idx && shown && !shown.endsWith('\n\n')) { const sep = shown.endsWith('\n') ? '\n' : '\n\n'; shown += sep; ev({ type: 'delta', text: sep }); }
          lastTextStep = idx; stepText[idx] = prev + t; shown += t; ev({ type: 'delta', text: t });
        }
      } else if (st.step_type === 'tool') {
        const info = st.tool_info || {}; const name = st.tool_name || info.name || 'tool';
        const desc = describeTool(name, info.parameters);
        if (!toolSeen[idx]) { toolSeen[idx] = true; ev({ type: 'activity', text: desc }); ev({ type: 'log', text: '▶ ' + desc + '\n' }); }
        if (done) {
          const out = info.output == null ? '' : (typeof info.output === 'string' ? info.output : JSON.stringify(info.output));
          if (out.trim()) ev({ type: 'log', text: out.trim().slice(0, 4000) + '\n' });
          ev({ type: 'tool', name, detail: desc, error: info.error ? (info.error.message || 'error') : undefined, secs: st.duration_seconds });
        }
      }
    } else if (o.event === 'result') {
      const r = o.result || {};
      if (r.conversation_id && !c.convId) c.convId = r.conversation_id;
      if (typeof r.response === 'string' && r.response.trim()) finalText = r.response;
      const status = String(r.status || '').toUpperCase();
      if (r.error || (status && status !== 'SUCCESS')) ev({ type: 'error', text: r.error || 'Статус: ' + status });
    }
  };
  child.stdout.on('data', d => {
    buf += d.toString('utf8'); let i;
    while ((i = buf.indexOf('\n')) >= 0) { const line = buf.slice(0, i); buf = buf.slice(i + 1); try { handle(JSON.parse(line)); } catch {} }
  });
  child.stderr.on('data', d => { const s = d.toString('utf8'); stderr += s; ev({ type: 'log', text: s }); s.split('\n').map(x => x.trim()).filter(Boolean).forEach(x => ev({ type: 'activity', text: x.slice(0, 200) })); });
  child.on('error', e => ev({ type: 'error', text: 'Не удалось запустить agy: ' + e.message }));
  child.on('close', code => {
    if (buf.trim()) { try { handle(JSON.parse(buf)); } catch {} }
    running.delete(c.id);
    if (finalText && (!shown || finalText.length >= shown.length)) ev({ type: 'final', text: finalText });
    if (!shown && !finalText) {
      const err = stderr.trim();
      if (/authentication required|sign ?in|log ?in|not authenticated/i.test(err)) ev({ type: 'error', text: 'Агент на сервере не вошёл в аккаунт Google. Откройте вкладку «Терминал» и выполните вход.' });
      else if (!m.error) ev({ type: 'error', text: err.slice(-1500) || `agy завершился (код ${code}) без ответа` });
    }
    m.busy = false; m.duration = Math.round((Date.now() - m.started) / 1000);
    c.busy = false; c.updated = Date.now();
    saveChats(u);
    emit(u.name, { t: 'ev', where: 'server', chatId: c.id, msgId: m.id, type: 'done', code, duration: m.duration });
    emit(u.name, { t: 'notify', title: 'Агент на сервере закончил', body: (m.text || m.error || '').slice(0, 140), chatId: c.id, where: 'server' });
  });
  return c;
}

function applyEvent(m, c, e) {
  switch (e.type) {
    case 'delta': m.text += e.text; m.status = 'Пишет ответ…'; break;
    case 'final': m.text = e.text; break;
    case 'activity': m.status = e.text; break;
    case 'log': m.log = ((m.log || '') + e.text).slice(-30000); break;
    case 'tool': m.tools.push({ name: e.name, detail: e.detail, error: e.error, secs: e.secs }); break;
    case 'error': m.error = (m.error ? m.error + '\n' : '') + e.text; break;
  }
}

function stop(u, chatId) {
  const ch = running.get(chatId);
  if (!ch) return;
  if (ch.stopRun) ch.stopRun();                 // process inside the container
  try { process.kill(ch.pid, 'SIGTERM'); } catch {}
}

// append a message to a chat (e.g. "Жена ответила: …")
function addNote(u, chatId, text) {
  const c = findChat(u, chatId); if (!c) return;
  const m = { id: uid(), role: 'agent', text, tools: [], ts: Date.now(), note: true };
  c.messages.push(m); c.updated = Date.now(); saveChats(u);
  emit(u.name, { t: 'chat', where: 'server', chat: c });
}

// a chat exported from the PC continues here
function importFromPc(u, pcChat, continueText) {
  const c = newChat(u, (pcChat.title || 'Чат') + ' ↗', 'pc');
  c.transferredFrom = 'pc';
  c.messages = (pcChat.messages || []).filter(m => m.text).map(m => ({ id: uid(), role: m.role === 'user' ? 'user' : 'agent', text: m.text, ts: Date.now() }));
  saveChats(u);
  emit(u.name, { t: 'chat', where: 'server', chat: c });
  return send(u, c.id, continueText || 'Продолжи работу над этой задачей с того места, где остановились. Если всё уже сделано — кратко отчитайся.');
}

/* ------------------------------------------------------------------ */
/* interactive terminal (sign in to agy, anything else)                 */
/* ------------------------------------------------------------------ */
const terms = new Map();                 // username -> { p, buf }
function termOpen(u) {
  let t = terms.get(u.name);
  if (t) return t;
  if (!pty) throw new Error('node-pty недоступен на сервере');
  const bin = agyPath(u);
  const L = runner(u, bin || '/bin/bash', [], { tty: true, runId: 'term' });
  const p = pty.spawn(L.cmd, L.args, Object.assign(spawnOpts(u), L.opts, { name: 'xterm-256color', cols: 100, rows: 30 }));
  t = { p, buf: '' };
  p.onData(d => { t.buf = (t.buf + d).slice(-100000); emit(u.name, { t: 'term.data', data: d }); });
  p.onExit(() => { terms.delete(u.name); emit(u.name, { t: 'term.data', data: '\r\n[agy завершился — откройте терминал снова]\r\n' }); });
  terms.set(u.name, t);
  return t;
}
function termInput(u, d) { const t = terms.get(u.name); if (t) t.p.write(d); }
function termResize(u, cols, rows) { const t = terms.get(u.name); if (t) { try { t.p.resize(cols, rows); } catch {} } }
function termRestart(u) { const t = terms.get(u.name); if (t) { try { t.p.kill(); } catch {} terms.delete(u.name); } return termOpen(u); }

// one-off agy run without a chat (used by the WhatsApp auto-responder)
function runOnce(u, prompt, timeoutMs = 120000) {
  return new Promise((resolve, reject) => {
    const bin = agyPath(u); if (!bin) return reject(new Error('agy not installed'));
    prepareAgyConfig(u);
    const L = runner(u, bin, ['-p', prompt, '--output-format', 'json']);
    const child = spawn(L.cmd, L.args, spawnOpts(u, Object.assign({ stdio: ['ignore', 'pipe', 'pipe'] }, L.opts)));
    let out = '', err = '';
    const t = setTimeout(() => { try { child.kill('SIGTERM'); } catch {} }, timeoutMs);
    child.stdout.on('data', d => out += d); child.stderr.on('data', d => err += d);
    child.on('error', e => { clearTimeout(t); reject(e); });
    child.on('close', () => {
      clearTimeout(t);
      try { const j = JSON.parse(out.trim()); if (j.response) return resolve(j.response); } catch {}
      if (out.trim()) return resolve(out.trim());
      reject(new Error(err.trim().slice(-500) || 'empty response'));
    });
  });
}

function describeTool(name, params) {
  const p = params && typeof params === 'object' ? params : {};
  const pick = (...keys) => { for (const k of keys) for (const pk of Object.keys(p)) if (pk.toLowerCase() === k.toLowerCase() && p[pk] != null && p[pk] !== '') return String(p[pk]); return ''; };
  const short = s => s.length > 140 ? s.slice(0, 140) + '…' : s;
  const cmd = pick('CommandLine', 'command', 'cmd'); if (cmd) return 'Running ' + short(cmd.replace(/\s+/g, ' '));
  const file = pick('AbsolutePath', 'TargetFile', 'FilePath', 'path', 'file');
  const n = String(name);
  if (/send_message/i.test(n)) return 'WhatsApp → ' + short(pick('contact', 'chat', 'to') || '');
  if (/write|create|save/i.test(n) && file) return 'Writing ' + short(file);
  if (/edit|replace/i.test(n) && file) return 'Editing ' + short(file);
  if (/read|view/i.test(n) && file) return 'Reading ' + short(file);
  const first = file || Object.values(p).find(v => typeof v === 'string') || '';
  return n.replace(/_/g, ' ') + (first ? ' ' + short(String(first)) : '');
}

module.exports = { runningCount, stopAll, setup, chats, summary, findChat, newChat, deleteChat, send, stop, addNote, importFromPc, termOpen, termInput, termResize, termRestart, runOnce, lastOrigin, agyPath, prepareAgyConfig };

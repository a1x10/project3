// Auto-failover: the PC dies in the middle of a task (power cut, crash, network) ->
// after a grace period the server takes the latest project snapshot + conversation and finishes the job.
const fs = require('fs');
const path = require('path');
const { spawn, execFileSync } = require('child_process');
const users = require('./users');
const { readJson, writeJson } = require('./store');

const GRACE = Number(process.env.STELLA_FAILOVER_SEC || 45) * 1000;
const MAX_SNAPSHOT = Number(process.env.STELLA_SNAPSHOT_MB || 300) * 1024 * 1024;
let agent = null, emit = () => {}, toPc = () => 0, toPhones = () => {};
function setup(o) { agent = o.agent; emit = o.emit; toPc = o.toPc; toPhones = o.toPhones; }

const timers = new Map();               // username -> timeout
const snapDir = u => path.join(users.userDir(u), 'snapshots');
const stateFile = u => path.join(users.userDir(u), 'failover.json');
const safeName = s => String(s || 'project').replace(/[^\p{L}\p{N}._ -]/gu, '_').slice(0, 60).trim() || 'project';

/* ---------------- live copy of what the PC is doing ---------------- */
// pc.ev events are applied to the server's copy of the PC chat, so progress survives a power cut
function applyPcEvent(P, m) {
  if (!m.chatId) return;
  P.running = P.running || new Map();
  let c = P.chats.get(m.chatId);
  if (m.type === 'start') {
    P.running.set(m.chatId, { started: Date.now() });
    if (!c) { c = { id: m.chatId, title: (m.messages && m.messages[0] && m.messages[0].text || 'Чат').slice(0, 48), messages: [] }; P.chats.set(m.chatId, c); }
    for (const x of m.messages || []) if (!c.messages.some(y => y.id === x.id)) c.messages.push(Object.assign({}, x));
    const firstUser = (m.messages || []).find(x => x.role === 'user');
    if (firstUser && (!c.title || c.title === 'Новый чат')) c.title = String(firstUser.text || '').split('\n')[0].slice(0, 48);
    c.busy = true;
    return;
  }
  if (!c) return;
  const msg = c.messages.find(x => x.id === m.msgId);
  if (msg) {
    if (m.type === 'delta') msg.text = (msg.text || '') + (m.text || '');
    else if (m.type === 'final') msg.text = m.text || msg.text;
    else if (m.type === 'tool') (msg.tools = msg.tools || []).push({ name: m.name, detail: m.detail, error: m.error });
    else if (m.type === 'error') msg.error = (msg.error ? msg.error + '\n' : '') + (m.text || '');
  }
  if (m.type === 'done') { P.running.delete(m.chatId); c.busy = false; if (msg) msg.busy = false; }
}

/* ---------------- snapshots of the PC project folder ---------------- */
function saveSnapshot(u, chatId, folder, req) {
  return new Promise((resolve, reject) => {
    fs.mkdirSync(snapDir(u), { recursive: true, mode: 0o700 });
    const id = String(chatId).replace(/[^\w-]/g, '').slice(0, 40);
    if (!id) return reject(new Error('bad chat id'));
    const tmp = path.join(snapDir(u), id + '.tmp');
    const out = fs.createWriteStream(tmp, { mode: 0o600 });
    let size = 0, failed = false;
    req.on('data', d => { size += d.length; if (size > MAX_SNAPSHOT && !failed) { failed = true; out.destroy(); req.destroy(); fs.rmSync(tmp, { force: true }); reject(new Error('snapshot too large')); } });
    req.pipe(out);
    out.on('finish', () => {
      if (failed) return;
      fs.renameSync(tmp, path.join(snapDir(u), id + '.tar.gz'));
      writeJson(path.join(snapDir(u), id + '.json'), { folder: safeName(folder), size, at: Date.now() });
      resolve({ size });
    });
    out.on('error', reject);
  });
}

// extract a snapshot into the account's workspace, AS the account user (never as root)
function extractSnapshot(u, chatId, folderName) {
  const id = String(chatId).replace(/[^\w-]/g, '');
  const file = path.join(snapDir(u), id + '.tar.gz');
  if (!fs.existsSync(file)) return Promise.resolve(null);
  const meta = readJson(path.join(snapDir(u), id + '.json'), {});
  const folder = safeName(folderName || meta.folder);
  const dest = path.join(u.home, 'workspace', folder);
  return new Promise((resolve, reject) => {
    fs.mkdirSync(dest, { recursive: true });
    if (u.uid != null) execFileSync('chown', [`${u.uid}:${u.gid}`, dest]);
    const p = spawn('tar', ['-xzf', '-', '--no-same-owner', '--no-same-permissions', '-C', dest], { uid: u.uid, gid: u.gid, stdio: ['pipe', 'ignore', 'pipe'] });
    let err = '';
    p.stderr.on('data', d => err += d);
    fs.createReadStream(file).pipe(p.stdin);
    p.on('close', code => code === 0 ? resolve({ folder, dest, at: meta.at }) : reject(new Error('tar: ' + err.slice(-300))));
    p.on('error', reject);
  });
}

// stream a server workspace folder back to the PC (tar.gz), read AS the account user
function exportFolder(u, folder, res) {
  const dir = path.join(u.home, 'workspace', safeName(folder));
  if (!fs.existsSync(dir)) { res.writeHead(404, { 'content-type': 'application/json' }); return res.end(JSON.stringify({ error: 'нет такой папки на сервере' })); }
  res.writeHead(200, { 'content-type': 'application/gzip', 'content-disposition': `attachment; filename="${encodeURIComponent(safeName(folder))}.tar.gz"` });
  const p = spawn('tar', ['-czf', '-', '-C', dir, '.'], { uid: u.uid, gid: u.gid, stdio: ['ignore', 'pipe', 'ignore'] });
  p.stdout.pipe(res);
}

/* ---------------- failover ---------------- */
function pcDisconnected(u, P) {
  const runningIds = [...(P.running || new Map()).keys()];
  if (!runningIds.length || process.env.STELLA_FAILOVER === '0') return;
  clearTimeout(timers.get(u.name));
  toPhones(u.name, { t: 'notify', title: 'Компьютер пропал посреди задачи', body: `Если он не вернётся за ${Math.round(GRACE / 1000)} сек — задача продолжится на сервере.` });
  timers.set(u.name, setTimeout(() => fire(u, P, runningIds).catch(e => console.error('failover', u.name, e)), GRACE));
}
function pcReconnected(u) {
  if (timers.has(u.name)) { clearTimeout(timers.get(u.name)); timers.delete(u.name); toPhones(u.name, { t: 'notify', title: 'Компьютер снова в сети', body: 'Задача продолжается на компьютере.' }); }
  // tell the PC which of its tasks were finished on the server while it was away
  const st = readJson(stateFile(u), { moved: [] });
  const pending = st.moved.filter(x => !x.toldPc);
  if (pending.length && toPc(u.name, { t: 'pc.failover', moved: pending })) { pending.forEach(x => x.toldPc = true); writeJson(stateFile(u), st); }
}

async function fire(u, P, ids) {
  timers.delete(u.name);
  if (P.online) return;                                  // came back in time
  const st = readJson(stateFile(u), { moved: [] });
  for (const id of ids) {
    if (!P.running || !P.running.has(id)) continue;
    P.running.delete(id);
    const pcChat = P.chats.get(id);
    if (!pcChat) continue;
    pcChat.busy = false;
    let snap = null;
    try { snap = await extractSnapshot(u, id); } catch (e) { console.error('failover extract', e.message); }
    const lastUser = [...pcChat.messages].reverse().find(m => m.role === 'user');
    const text =
      'Компьютер пользователя внезапно выключился (пропало электричество или связь) прямо во время этой задачи. Ты — тот же агент, продолжаешь на сервере. ' +
      (snap ? `Файлы проекта скопированы с компьютера в папку ./${snap.folder} (снимок на ${new Date(snap.at).toLocaleString('ru-RU')}; самые последние секунды работы могли не попасть в снимок — проверь). Работай в этой папке. `
            : 'Файлы проекта с компьютера недоступны (снимка нет) — сделай всё, что возможно, здесь. ') +
      `Исходная задача пользователя: «${(lastUser && lastUser.text || '').slice(0, 2000)}». ` +
      'Доведи задачу до конца. В конце кратко напиши, что сделано и где лежат результаты.';
    const c = agent.importFromPc(u, Object.assign({}, pcChat, { title: '⚡ ' + (pcChat.title || 'Задача') }), text);
    st.moved.push({ pcChatId: id, serverChatId: c.id, folder: snap && snap.folder, at: Date.now(), toldPc: false });
    toPhones(u.name, { t: 'notify', title: '⚡ Компьютер отключился — задача продолжена на сервере', body: pcChat.title || '', where: 'server', chatId: c.id });
  }
  st.moved = st.moved.slice(-50);
  writeJson(stateFile(u), st);
}

module.exports = { setup, applyPcEvent, saveSnapshot, exportFolder, pcDisconnected, pcReconnected, safeName };

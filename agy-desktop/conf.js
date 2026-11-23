// «Конференция»: a small always-on-top window that listens to the meeting (your microphone + the sound of the call),
// shows a live transcript and gives instant hints (what to answer, questions, summary, explain the screen).
// Speech is recognised and answered on the Stella server with the fastest Gemini models.
const { BrowserWindow, ipcMain, desktopCapturer, session, screen } = require('electron');
const fs = require('fs');
const path = require('path');
const os = require('os');

let H = { log: () => {}, send: () => {}, getSettings: () => ({}) };
let win = null;
const streams = new Map();            // id -> AbortController

const server = () => { const s = H.getSettings(); if (!s.cloudUrl || !s.cloudToken) throw new Error('Войдите в аккаунт Stella'); return s; };
async function post(p, body, signal) {
  const s = server();
  return fetch(s.cloudUrl + '/api/conf/' + p, { method: 'POST', headers: { authorization: 'Bearer ' + s.cloudToken, 'content-type': 'application/json' }, body: JSON.stringify(body), signal });
}

function open() {
  if (win && !win.isDestroyed()) { win.show(); win.focus(); return; }
  const wa = screen.getPrimaryDisplay().workArea;
  win = new BrowserWindow({
    width: 410, height: 640, minWidth: 320, minHeight: 300,
    x: wa.x + wa.width - 430, y: wa.y + 40,
    frame: false, alwaysOnTop: true, skipTaskbar: false, resizable: true, title: 'Stella — Конференция',
    backgroundColor: '#16161a', icon: path.join(__dirname, 'renderer', 'icon.png'),
    webPreferences: { preload: path.join(__dirname, 'conf-preload.js'), contextIsolation: true, nodeIntegration: false, sandbox: false, backgroundThrottling: false }
  });
  win.setAlwaysOnTop(true, 'floating');
  win.loadFile(path.join(__dirname, 'renderer', 'conf.html'));
  win.on('closed', () => { win = null; for (const c of streams.values()) c.abort(); streams.clear(); H.send('conf:closed'); });
}
function close() { if (win && !win.isDestroyed()) win.webContents.send('conf:stop'); setTimeout(() => { if (win && !win.isDestroyed()) win.close(); }, 1500); }

function init(hooks) {
  H = Object.assign(H, hooks);
  // the sound of the call: Windows loopback = everything the computer plays (Zoom, Meet, Teams, Telegram…)
  session.defaultSession.setDisplayMediaRequestHandler((req, cb) => {
    desktopCapturer.getSources({ types: ['screen'] }).then(src => cb(src[0] ? { video: src[0], audio: process.platform === 'win32' ? 'loopback' : undefined } : {}))
      .catch(() => cb({}));
  });
  // microphone / screen sound only for Stella's own pages (never for web pages like the captcha window)
  session.defaultSession.setPermissionRequestHandler((wc, perm, cb) => cb(['media', 'display-capture', 'clipboard-sanitized-write'].includes(perm) && String(wc.getURL()).startsWith('file://')));

  ipcMain.handle('conf:open', () => { open(); return true; });
  ipcMain.handle('conf:close', () => { close(); return true; });
  ipcMain.handle('conf:status', async () => {
    try { const s = server(); const r = await fetch(s.cloudUrl + '/api/conf/status', { headers: { authorization: 'Bearer ' + s.cloudToken }, signal: AbortSignal.timeout(10000) }); return await r.json(); }
    catch (e) { return { ready: false, error: e.message }; }
  });
  ipcMain.handle('conf:transcribe', async (_e, { audio, who, hint }) => {
    try {
      const r = await post('transcribe', { audio, who, hint }, AbortSignal.timeout(30000));
      const j = await r.json().catch(() => ({}));
      return r.ok ? j : { error: j.error || 'сервер ' + r.status };
    } catch (e) { return { error: e.message }; }
  });
  // streamed hint: deltas go to the conference window as they arrive
  ipcMain.handle('conf:assist', async (e, req) => {
    const id = String(req.id || Date.now()); const ac = new AbortController(); streams.set(id, ac);
    const to = d => { if (!e.sender.isDestroyed()) e.sender.send('conf:delta', d); };
    try {
      if (req.mode === 'screen') req.image = await shot();
      const r = await post('assist', { mode: req.mode, transcript: req.transcript, question: req.question, image: req.image, title: req.title }, ac.signal);
      if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.error || 'сервер ' + r.status); }
      const dec = new TextDecoder();
      for await (const c of r.body) to({ id, text: dec.decode(c, { stream: true }) });
      to({ id, done: true });
    } catch (err) { to({ id, done: true, error: ac.signal.aborted ? '' : err.message }); }
    streams.delete(id);
    return true;
  });
  ipcMain.on('conf:cancel', (_e, id) => { const c = streams.get(String(id)); if (c) c.abort(); });
  ipcMain.handle('conf:save', (_e, { md, title }) => {
    const dir = path.join(H.getSettings().workspace || os.homedir(), 'Конференции');
    fs.mkdirSync(dir, { recursive: true });
    const d = new Date(), p2 = n => String(n).padStart(2, '0');
    const name = `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())} ${p2(d.getHours())}-${p2(d.getMinutes())}${title ? ' ' + String(title).replace(/[\\/:*?"<>|]/g, '').slice(0, 60) : ''}.md`;
    const file = path.join(dir, name);
    fs.writeFileSync(file, md, 'utf8');
    H.send('conf:saved', { file });
    return file;
  });
  ipcMain.on('conf:opacity', (_e, v) => { if (win) win.setOpacity(Math.max(0.35, Math.min(1, Number(v) || 1))); });
  ipcMain.on('conf:pin', (_e, on) => { if (win) win.setAlwaysOnTop(!!on, 'floating'); });
  ipcMain.on('conf:minimize', () => { if (win) win.minimize(); });
  ipcMain.on('conf:closeWin', () => { if (win) win.close(); });
}

// screenshot of the screen the window is on (the window itself is hidden for a moment so it is not in the picture)
async function shot() {
  const d = win ? screen.getDisplayMatching(win.getBounds()) : screen.getPrimaryDisplay();
  const hide = win && win.isVisible(); if (hide) win.setOpacity(0);
  await new Promise(r => setTimeout(r, 120));
  try {
    const k = Math.min(1, 1600 / Math.max(d.size.width, d.size.height));
    const src = await desktopCapturer.getSources({ types: ['screen'], thumbnailSize: { width: Math.round(d.size.width * d.scaleFactor * k), height: Math.round(d.size.height * d.scaleFactor * k) } });
    const s = src.find(x => String(x.display_id) === String(d.id)) || src[0];
    if (!s) throw new Error('не удалось сделать снимок экрана');
    return s.thumbnail.toJPEG(80).toString('base64');
  } finally { if (hide && win) win.setOpacity(1); }
}

module.exports = { init, open, close };

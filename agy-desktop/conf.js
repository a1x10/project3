// «Конференция»: a small always-on-top window that listens to the meeting (your microphone + the sound of the call),
// shows a live transcript and gives instant hints (what to answer, questions, summary, explain the screen).
// Speech is recognised and answered on the Stella server with the fastest Gemini models.
const { BrowserWindow, ipcMain, desktopCapturer, session, screen, app } = require('electron');
const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');
const { spawn, execFile } = require('child_process');

/* ------------------------------------------------------------------ */
/* Stella Conference (Windows app based on Pluely, GPL-3.0): downloaded */
/* next to Stella, checked by SHA-256, started with the Stella account.  */
/* The built-in window below stays as a fallback.                        */
/* ------------------------------------------------------------------ */
const CONF_URL = 'https://raw.githubusercontent.com/a1x10/project3/claude/happy-ritchie-vx32ws/agy-desktop/release/conference.json';
let proc = null;
const confDir = () => path.join(app.getPath('userData'), 'conference');
const sha = f => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');

async function ensureApp() {
  const dir = confDir(); fs.mkdirSync(dir, { recursive: true });
  const exe = path.join(dir, 'StellaConference.exe'), meta = path.join(dir, 'installed.json');
  let have = null; try { have = JSON.parse(fs.readFileSync(meta, 'utf8')); } catch {}
  let info = null;
  for (const u of confUrls()) {
    try { const r = await fetch(u + '?t=' + Date.now(), { signal: AbortSignal.timeout(15000) }); if (r.ok) { info = await r.json(); break; } }
    catch (e) { H.log('conference: info', u, e.message); }
  }
  if (info && /^[0-9a-f]{64}$/.test(info.sha256 || '') && !(have && have.sha256 === info.sha256 && fs.existsSync(exe))) {
    H.send('conf:progress', { text: 'скачиваю Stella Conference ' + (info.version || '') + '…' });
    const r = await fetch(info.url, { signal: AbortSignal.timeout(10 * 60 * 1000) });
    if (!r.ok) throw new Error('загрузка: ' + r.status);
    const buf = Buffer.from(await r.arrayBuffer());
    if (crypto.createHash('sha256').update(buf).digest('hex') !== info.sha256) throw new Error('контрольная сумма не совпала — файл отклонён');
    if (proc) stopApp();
    fs.writeFileSync(exe + '.new', buf, { mode: 0o755 }); fs.renameSync(exe + '.new', exe);
    fs.writeFileSync(meta, JSON.stringify({ version: info.version, sha256: info.sha256 }));
    have = info;
  }
  if (!fs.existsSync(exe)) throw new Error('Stella Conference ещё не загружена');
  if (have && have.sha256 && sha(exe) !== have.sha256) throw new Error('файл Stella Conference изменён — скачаю заново в следующий раз');
  return exe;
}

// where to get conference.json: your Stella server first, GitHub as a fallback
function confUrls() {
  if (process.env.STELLA_CONF_URL) return [process.env.STELLA_CONF_URL];
  let gh = CONF_URL; try { gh = JSON.parse(fs.readFileSync(path.join(__dirname, 'config.json'), 'utf8')).conferenceUrl || gh; } catch {}
  const s = H.getSettings() || {};
  return [s.cloudUrl ? s.cloudUrl.replace(/\/+$/, '') + '/download/conference.json' : null, gh].filter(Boolean);
}

// Stella Conference needs the Microsoft Edge WebView2 runtime (built into Windows 11, usually present on Windows 10)
const WV2_KEYS = ['HKLM\\SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
  'HKLM\\SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
  'HKCU\\SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'];
const regHas = k => new Promise(r => execFile('reg', ['query', k, '/v', 'pv'], { windowsHide: true }, (e, out) => r(!e && /pv\s+REG_SZ\s+\d+\.\d+/.test(out || '') && !/\s0\.0\.0\.0/.test(out || ''))));
async function ensureWebView2() {
  if (process.platform !== 'win32') return true;
  for (const k of WV2_KEYS) if (await regHas(k)) return true;
  H.send('conf:progress', { text: 'устанавливаю компонент Windows WebView2 для Конференции…' });
  const f = path.join(confDir(), 'MicrosoftEdgeWebview2Setup.exe');
  const r = await fetch('https://go.microsoft.com/fwlink/p/?LinkId=2124703', { signal: AbortSignal.timeout(5 * 60 * 1000) });
  if (!r.ok) throw new Error('WebView2: загрузка ' + r.status);
  fs.writeFileSync(f, Buffer.from(await r.arrayBuffer()));
  await new Promise((ok, fail) => execFile(f, ['/silent', '/install'], { windowsHide: true, timeout: 10 * 60 * 1000 }, e => e ? fail(new Error('WebView2 не установился: ' + e.message)) : ok()));
  try { fs.unlinkSync(f); } catch {}
  return true;
}

// everything the conference needs, prepared in the background when Stella starts (so the button opens it at once)
let preparing = null, prepared = false;
function prepare(quiet) {
  if (preparing) return preparing;
  preparing = (async () => {
    try {
      await ensureWebView2();
      await ensureApp();
      prepared = true;
      if (!quiet) H.send('conf:progress', { text: 'Конференция готова' });
      H.log('conference: prepared');
    } catch (e) { H.log('conference prepare', e.message); if (!quiet) throw e; }
    finally { preparing = null; }
  })();
  return preparing;
}

async function startApp() {
  if (proc) return true;
  const s = server();
  if (preparing) { H.send('conf:progress', { text: 'готовлю Конференцию…' }); await preparing.catch(() => {}); }
  await ensureWebView2();
  const exe = await ensureApp();
  proc = spawn(exe, [], {
    cwd: path.dirname(exe), detached: false, windowsHide: false, stdio: 'ignore',
    env: Object.assign({}, process.env, { STELLA_SERVER: s.cloudUrl, STELLA_TOKEN: s.cloudToken, STELLA_USER: s.cloudUser || '' })
  });
  const p = proc;
  try { await new Promise((ok, fail) => { p.once('spawn', ok); p.once('error', fail); }); }
  catch (e) { proc = null; throw new Error('не запустилась (' + e.message + ')'); }
  p.on('exit', () => { if (proc === p) { proc = null; H.send('conf:closed'); } });
  p.on('error', e => H.log('conference', e.message));
  H.send('conf:progress', { text: 'Stella Conference запущена' });
  return true;
}
function stopApp() {
  if (!proc) return;
  const pid = proc.pid; proc = null;                 // cleared first: this exit is not reported as "closed by the user"
  if (process.platform === 'win32') execFile('taskkill', ['/PID', String(pid), '/T', '/F'], () => {}); else { try { process.kill(pid); } catch {} }
}

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
  // download Stella Conference (+ WebView2) in the background soon after start, then re-check for updates every 6 h
  if (process.platform === 'win32' || process.env.STELLA_CONF_APP_TEST) {
    const tick = () => { const s = H.getSettings() || {}; if (s.cloudUrl && s.cloudToken && !proc) prepare(true); };
    setTimeout(tick, Number(process.env.STELLA_CONF_PREPARE_MS || 15000));
    setInterval(tick, 6 * 3600 * 1000);
  }
  // the sound of the call: Windows loopback = everything the computer plays (Zoom, Meet, Teams, Telegram…)
  session.defaultSession.setDisplayMediaRequestHandler((req, cb) => {
    desktopCapturer.getSources({ types: ['screen'] }).then(src => cb(src[0] ? { video: src[0], audio: process.platform === 'win32' ? 'loopback' : undefined } : {}))
      .catch(() => cb({}));
  });
  // microphone / screen sound only for Stella's own pages (never for web pages like the captcha window)
  session.defaultSession.setPermissionRequestHandler((wc, perm, cb) => cb(['media', 'display-capture', 'clipboard-sanitized-write'].includes(perm) && String(wc.getURL()).startsWith('file://')));

  ipcMain.handle('conf:open', async () => {
    if (process.platform === 'win32' || process.env.STELLA_CONF_APP_TEST) {
      try { await startApp(); return { ok: true, app: true }; }
      catch (e) { H.log('conference app', e.message); H.send('conf:progress', { text: 'Stella Conference: ' + e.message + ' — открываю встроенное окно' }); }
    }
    open(); return { ok: true, app: false };
  });
  ipcMain.handle('conf:close', () => { stopApp(); close(); return true; });
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

module.exports = { init, open, close, stopApp, prepare };

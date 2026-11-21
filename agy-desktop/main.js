// Agy Desktop — main process
// 1) relaunches itself as Administrator (Windows)
// 2) checks / installs Antigravity CLI (agy)
// 3) keeps a hidden pseudo-terminal with interactive `agy` (login, /voice live, slash commands)
// 4) sends chat prompts to `agy -p ... --output-format stream-json` and streams answers back to the UI

const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const { spawn, execSync, execFileSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');

let pty = null, ptyTried = false;
function loadPty() {
  if (!ptyTried) {
    ptyTried = true;
    try { pty = require('node-pty'); } catch (e) { pty = null; try { log('node-pty unavailable:', e.message); } catch {} }
  }
  return pty;
}
function ptyAvailable() {
  try { return fs.existsSync(path.join(path.dirname(require.resolve('node-pty/package.json')), 'package.json')); } catch { return false; }
}

const isWin = process.platform === 'win32';
const ELEVATED_FLAG = '--agy-elevated';

/* ------------------------------------------------------------------ */
/* Administrator rights                                                 */
/* ------------------------------------------------------------------ */
let adminCache = null;
function isAdmin() {
  if (!isWin) return true;
  if (adminCache !== null) return adminCache;
  const tries = ['fltmc', 'net session', 'reg query "HKU\\S-1-5-19"'];
  for (const cmd of tries) {
    try { execSync(cmd, { stdio: 'ignore', windowsHide: true, timeout: 8000 }); return (adminCache = true); } catch {}
  }
  return (adminCache = false);
}

function psQuote(s) { return "'" + String(s).replace(/'/g, "''") + "'"; }

// simple log file: %APPDATA%\agy-desktop\agy-desktop.log
function log(...a) {
  try {
    const dir = path.join(process.env.APPDATA || os.homedir(), 'agy-desktop');
    fs.mkdirSync(dir, { recursive: true });
    fs.appendFileSync(path.join(dir, 'agy-desktop.log'), new Date().toISOString() + ' ' + a.map(String).join(' ') + '\n');
  } catch {}
}
function logFile() { return path.join(process.env.APPDATA || os.homedir(), 'agy-desktop', 'agy-desktop.log'); }
process.on('uncaughtException', e => {
  log('uncaught', e && e.stack || e);
  try { dialog.showErrorBox('Stella — ошибка', String(e && e.stack || e) + '\n\nЛог: ' + logFile()); } catch {}
});

// Returns true if an elevated copy was started (UAC accepted)
function relaunchAsAdmin() {
  const { spawnSync } = require('child_process');
  const args = app.isPackaged ? process.argv.slice(1) : [app.getAppPath()];
  args.push(ELEVATED_FLAG);
  // each argument wrapped in double quotes so paths with spaces / cyrillic survive
  const argString = args.map(a => '"' + String(a).replace(/"/g, '\\"') + '"').join(' ');
  const workDir = app.isPackaged ? path.dirname(process.execPath) : app.getAppPath();
  const ps = `$ErrorActionPreference='Stop'; Start-Process -FilePath ${psQuote(process.execPath)} -ArgumentList ${psQuote(argString)} -WorkingDirectory ${psQuote(workDir)} -Verb RunAs`;
  const encoded = Buffer.from(ps, 'utf16le').toString('base64');
  const r = spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-EncodedCommand', encoded],
                      { windowsHide: true, timeout: 120000, encoding: 'utf8' });
  log('relaunchAsAdmin exit=', r.status, 'err=', (r.stderr || '').trim(), r.error ? r.error.message : '');
  return r.status === 0;
}

// White-screen fixes: elevated Chromium + some GPU drivers render nothing
app.disableHardwareAcceleration();
app.commandLine.appendSwitch('no-sandbox');
app.commandLine.appendSwitch('disable-gpu-sandbox');

log('start argv=', JSON.stringify(process.argv), 'admin=', isAdmin());
if (isWin && !process.env.AGY_NO_ADMIN && !process.argv.includes(ELEVATED_FLAG) && !isAdmin()) {
  if (relaunchAsAdmin()) {
    app.exit(0);
  } else {
    log('UAC cancelled or failed, continuing without admin rights');
  }
}

/* ------------------------------------------------------------------ */
/* Settings / history storage                                           */
/* ------------------------------------------------------------------ */
const dataDir = () => app.getPath('userData');
const settingsFile = () => path.join(dataDir(), 'settings.json');
const chatsFile = () => path.join(dataDir(), 'chats.json');

function readJson(file, def) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return def; }
}
function writeJson(file, val) {
  try { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, JSON.stringify(val, null, 2)); } catch {}
}

let settings = null;
function getSettings() {
  if (!settings) {
    settings = Object.assign({
      workspace: os.homedir(),
      model: '',
      mode: 'default',          // default | accept-edits | plan | yolo
      loggedIn: false,
      theme: 'system'
    }, readJson(settingsFile(), {}));
  }
  return settings;
}

/* ------------------------------------------------------------------ */
/* Locating / installing agy                                            */
/* ------------------------------------------------------------------ */
let agyPath = null;

function refreshPathFromRegistry() {
  if (!isWin) return;
  try {
    const out = execFileSync('powershell.exe', ['-NoProfile', '-Command',
      "[Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')"],
      { encoding: 'utf8', windowsHide: true }).trim();
    if (out) process.env.PATH = out + ';' + process.env.PATH;
  } catch {}
}

function findAgy() {
  const home = os.homedir();
  const local = process.env.LOCALAPPDATA || path.join(home, 'AppData', 'Local');
  const candidates = isWin ? [
    path.join(home, '.local', 'bin', 'agy.exe'),
    path.join(home, '.antigravity', 'bin', 'agy.exe'),
    path.join(home, '.agy', 'bin', 'agy.exe'),
    path.join(local, 'Programs', 'antigravity-cli', 'agy.exe'),
    path.join(local, 'Programs', 'Antigravity CLI', 'agy.exe'),
    path.join(local, 'antigravity-cli', 'agy.exe'),
    path.join(process.env.ProgramData || 'C:\\ProgramData', 'chocolatey', 'bin', 'agy.exe')
  ] : [
    path.join(home, '.local', 'bin', 'agy'),
    path.join(home, '.antigravity', 'bin', 'agy'),
    '/usr/local/bin/agy', '/opt/homebrew/bin/agy'
  ];
  try {
    const out = execSync(isWin ? 'where agy' : 'command -v agy', { encoding: 'utf8', windowsHide: true, stdio: ['ignore', 'pipe', 'ignore'] });
    const lines = out.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
    const exe = lines.find(l => /\.exe$/i.test(l)) || lines[0];
    if (exe && fs.existsSync(exe)) return exe;
  } catch {}
  return candidates.find(p => fs.existsSync(p)) || null;
}

function needsShell(p) { return isWin && /\.(cmd|bat|ps1)$/i.test(p); }

// Build [file, args] so .cmd shims also work
function agyCommand(args) {
  if (!agyPath) throw new Error('agy not found');
  if (/\.ps1$/i.test(agyPath)) return ['powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', agyPath, ...args]];
  if (needsShell(agyPath)) return ['cmd.exe', ['/d', '/s', '/c', [agyPath, ...args].map(winQuote).join(' ')]];
  return [agyPath, args];
}
function winQuote(a) {
  a = String(a);
  if (!/[\s"&|<>^%]/.test(a)) return a;
  return '"' + a.replace(/(["^%])/g, '^$1').replace(/\r?\n/g, ' ') + '"';
}

function installAgy(send) {
  return new Promise((resolve) => {
    let file, args;
    if (isWin) {
      file = 'powershell.exe';
      args = ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
        "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; irm https://antigravity.google/cli/install.ps1 | iex"];
    } else {
      file = 'bash';
      args = ['-lc', 'curl -fsSL https://antigravity.google/cli/install.sh | bash'];
    }
    const p = spawn(file, args, { windowsHide: true, env: process.env });
    const onData = d => send(stripAnsi(d.toString()));
    p.stdout.on('data', onData);
    p.stderr.on('data', onData);
    p.on('error', e => { send('Ошибка: ' + e.message + '\n'); resolve(false); });
    p.on('close', code => {
      if (code !== 0 && isWin) {
        // fallback: CMD installer
        send('\nPowerShell-установщик вернул код ' + code + ', пробую CMD-установщик...\n');
        const tmp = path.join(os.tmpdir(), 'agy-install.cmd');
        const c = spawn('cmd.exe', ['/d', '/c', `curl -fsSL https://antigravity.google/cli/install.cmd -o "${tmp}" && "${tmp}" && del "${tmp}"`], { windowsHide: true });
        c.stdout.on('data', onData); c.stderr.on('data', onData);
        c.on('close', c2 => resolve(c2 === 0));
        c.on('error', () => resolve(false));
      } else resolve(code === 0);
    });
  });
}

function stripAnsi(s) {
  return s.replace(/\x1b\[[0-9;?]*[ -\/]*[@-~]/g, '').replace(/\x1b\][^\x07]*(\x07|\x1b\\)/g, '').replace(/\x1b[@-_]/g, '');
}

/* ------------------------------------------------------------------ */
/* Window                                                               */
/* ------------------------------------------------------------------ */
let win = null;
function send(ch, payload) { if (win && !win.isDestroyed()) win.webContents.send(ch, payload); }

function createWindow() {
  win = new BrowserWindow({
    width: 1280, height: 840, minWidth: 820, minHeight: 560,
    title: 'Stella',
    backgroundColor: '#f7f6f3',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  });
  win.on('page-title-updated', e => e.preventDefault());
  const wc = win.webContents;
  wc.on('did-fail-load', (_e, code, desc, url) => log('did-fail-load', code, desc, url));
  wc.on('preload-error', (_e, p, err) => log('preload-error', p, err && err.stack));
  wc.on('console-message', (_e, level, msg, line, src) => { if (level >= 2) log('renderer:', msg, src + ':' + line); });
  let crashes = 0;
  wc.on('render-process-gone', (_e, d) => {
    log('render-process-gone', JSON.stringify(d));
    if (++crashes <= 2) setTimeout(() => { if (!win.isDestroyed()) win.reload(); }, 500);
    else dialog.showErrorBox('Stella', 'Окно упало (' + d.reason + '). Лог: ' + logFile());
  });
  wc.on('unresponsive', () => log('window unresponsive'));
  win.loadFile(path.join(__dirname, 'renderer', 'index.html')).catch(e => log('loadFile error', e.message));
  win.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: 'deny' }; });
}

app.whenReady().then(() => { log('ready'); createWindow(); })
  .catch(e => { log('ready error', e.stack); dialog.showErrorBox('Stella', String(e.stack || e)); });
app.on('child-process-gone', (_e, d) => log('child-process-gone', JSON.stringify(d)));
process.on('unhandledRejection', e => log('unhandledRejection', e && e.stack || e));
app.on('window-all-closed', () => { killAll(); app.quit(); });
app.on('before-quit', killAll);

/* ------------------------------------------------------------------ */
/* Hidden terminal (pty) with interactive agy                           */
/* ------------------------------------------------------------------ */
let term = null;
let termCols = 120, termRows = 32;
let termBuffer = '';

function startTerm() {
  if (term) return { ok: true, fresh: false };
  if (!agyPath) return { ok: false, error: 'Системные файлы не найдены' };
  const s = getSettings();
  const env = Object.assign({}, process.env, { TERM: 'xterm-256color', COLORTERM: 'truecolor' });
  const [file, args] = agyCommand(modeArgs(s));
  if (loadPty()) {
    try {
      term = pty.spawn(file, args, { name: 'xterm-256color', cols: termCols, rows: termRows, cwd: s.workspace, env, useConpty: true });
      term.onData(d => { pushTerm(d); });
      term.onExit(({ exitCode }) => { term = null; send('term:exit', exitCode); });
      return { ok: true, pty: true, fresh: true };
    } catch (e) { term = null; return { ok: false, error: e.message }; }
  }
  // Fallback without node-pty: plain pipes (TUI features like /voice live may be limited)
  const p = spawn(file, args, { cwd: s.workspace, env, windowsHide: true });
  term = {
    write: d => { try { p.stdin.write(d); } catch {} },
    resize: () => {},
    kill: () => treeKill(p.pid),
    pid: p.pid
  };
  p.stdout.on('data', d => pushTerm(d.toString()));
  p.stderr.on('data', d => pushTerm(d.toString()));
  p.on('close', c => { term = null; send('term:exit', c); });
  return { ok: true, pty: false, fresh: true };
}

function pushTerm(d) {
  termBuffer = (termBuffer + d).slice(-200000);
  send('term:data', d);
  const plain = stripAnsi(d);
  if (/signed in|logged in|authenticated|welcome|вход выполнен|successfully/i.test(plain)) send('term:maybe-logged-in');
  if (/https:\/\/accounts\.google\.com\S+/.test(plain)) {
    const m = plain.match(/https:\/\/accounts\.google\.com\S+/);
    if (m) send('term:auth-url', m[0]);
  }
}

function stopTerm() { if (term) { try { term.kill(); } catch {} term = null; } }

function modeArgs(s) {
  const a = [];
  if (s.model) a.push('--model', s.model);
  if (s.mode === 'accept-edits' || s.mode === 'plan') a.push('--mode', s.mode);
  if (s.mode === 'yolo') a.push('--dangerously-skip-permissions');
  return a;
}

/* ------------------------------------------------------------------ */
/* Chat requests: agy -p "<prompt>" --output-format stream-json         */
/* ------------------------------------------------------------------ */
const running = new Map(); // reqId -> child

function treeKill(pid) {
  if (!pid) return;
  try {
    if (isWin) spawn('taskkill', ['/pid', String(pid), '/T', '/F'], { windowsHide: true });
    else process.kill(pid, 'SIGTERM');
  } catch {}
}

function killAll() {
  for (const c of running.values()) treeKill(c.pid);
  running.clear();
  stopTerm();
}

// keys that usually hold the assistant's text in agy / Gemini style JSON
const TEXT_KEYS = ['response', 'result', 'candidates', 'choices', 'messages', 'text', 'delta', 'content', 'output', 'answer', 'message', 'parts', 'data', 'value', 'chunk', 'final'];
const SKIP_KEYS = /^(input|args|arguments|params|parameters|tool_?input|tool_?args|command|path|file|files|stats|usage|metadata|model|id|type|role|error)$/i;

// collect assistant text from any JSON shape
function deepText(o, depth = 0) {
  if (o == null || depth > 6) return '';
  if (typeof o === 'string') return o;
  if (Array.isArray(o)) return o.map(x => deepText(x, depth + 1)).join('');
  if (typeof o !== 'object') return '';
  if (o.role && /user|system/i.test(o.role)) return '';
  if (o.thought === true) return '';
  for (const k of TEXT_KEYS) {
    if (k in o && !SKIP_KEYS.test(k)) {
      const t = deepText(o[k], depth + 1);
      if (t && t.trim()) return t;
    }
  }
  return '';
}

function findConvId(o, depth = 0) {
  if (!o || typeof o !== 'object' || depth > 4) return null;
  for (const [k, v] of Object.entries(o)) {
    if (/^(conversation_?id|conversationId|session_?id|sessionId|thread_?id)$/i.test(k) && typeof v === 'string') return v;
    if (v && typeof v === 'object') { const r = findConvId(v, depth + 1); if (r) return r; }
  }
  return null;
}

function respLog(text) {
  try { fs.appendFileSync(path.join(path.dirname(logFile()), 'last-response.log'), text); } catch {}
}

function runPrompt({ reqId, prompt, conversationId, continueLast }) {
  const s = getSettings();
  // text = real-time streaming (default); json / stream-json can be chosen in settings.json
  const fmt = ['json', 'stream-json'].includes(s.outputFormat) ? s.outputFormat : 'text';
  const args = ['-p', prompt, '--output-format', fmt, '--print-timeout', '30m', ...modeArgs(s)];
  if (conversationId) args.push('--conversation', conversationId);
  else if (continueLast) args.push('-c');

  let file, fargs;
  try { [file, fargs] = agyCommand(args); }
  catch (e) { send('chat:event', { reqId, type: 'error', text: e.message }); send('chat:done', { reqId, code: -1 }); return; }

  try { fs.writeFileSync(path.join(path.dirname(logFile()), 'last-response.log'), `=== ${new Date().toISOString()}\n${file} ${JSON.stringify(fargs)}\ncwd=${s.workspace}\n--- stdout ---\n`); } catch {}

  const child = spawn(file, fargs, { cwd: s.workspace, env: Object.assign({}, process.env, { NO_COLOR: '1' }), windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
  try { child.stdin.end(); } catch {}           // never let agy wait for stdin
  running.set(reqId, child);
  send('term:data', `\r\n\x1b[90m$ agy -p "${prompt.slice(0, 80).replace(/\n/g, ' ')}${prompt.length > 80 ? '…' : ''}" --output-format ${fmt}\x1b[0m\r\n`);

  const dec = new (require('string_decoder').StringDecoder)('utf8');
  let buf = '', all = '', stderr = '', shown = '', finalText = null, convId = null, looksJson = null;

  const emitConv = o => { const id = findConvId(o); if (id && !convId) { convId = id; send('chat:event', { reqId, type: 'conversation', id }); } };

  // stream-json: one event per line
  const handleEvent = (o) => {
    emitConv(o);
    const type = String(o.type || o.event || o.kind || '').toLowerCase();
    if (/tool/.test(type) || o.tool_name || o.toolName || o.functionCall || o.function_call) {
      const fc = o.functionCall || o.function_call || {};
      const name = o.tool_name || o.toolName || fc.name || (o.tool && (o.tool.name || o.tool)) || o.name || 'tool';
      const detail = o.input || o.args || o.arguments || fc.args || o.command || o.path || '';
      send('chat:event', { reqId, type: 'tool', name: String(name), detail: typeof detail === 'string' ? detail : JSON.stringify(detail).slice(0, 600) });
      return;
    }
    if (/think|reason|thought/.test(type)) { const t = deepText(o); if (t) send('chat:event', { reqId, type: 'thinking', text: t }); return; }
    if ((/error/.test(type) || o.error) && !o.response) {
      const t = (typeof o.error === 'string' ? o.error : (o.error && (o.error.message || JSON.stringify(o.error)))) || deepText(o) || JSON.stringify(o);
      send('chat:event', { reqId, type: 'error', text: t }); return;
    }
    if (/user/.test(type) || o.role === 'user') return;
    if (typeof o.response === 'string' || /result|final|done|complete|end/.test(type)) {
      const t = deepText(o); if (t && t.trim()) finalText = t; return;
    }
    if (/init|start|system|stats|usage/.test(type)) return;
    const t = deepText(o);
    if (t) { shown += t; send('chat:event', { reqId, type: 'delta', text: t }); }
  };

  const handleLine = (line) => {
    if (!line.trim()) return;
    let o = null;
    try { o = JSON.parse(line); } catch {}
    if (o && typeof o === 'object') handleEvent(o);
  };

  child.stdout.on('data', d => {
    const str = dec.write(d);
    all += str; respLog(str);
    send('term:data', str.replace(/\r?\n/g, '\r\n'));
    if (fmt === 'stream-json') {
      buf += str;
      let i;
      while ((i = buf.indexOf('\n')) >= 0) { handleLine(buf.slice(0, i)); buf = buf.slice(i + 1); }
    } else if (fmt === 'text') {
      // if the CLI still answers with a JSON object, let the close handler parse it
      if (looksJson === null && all.trim()) looksJson = /^[\[{]/.test(all.trim());
      if (looksJson === false) {
        const t = stripAnsi(str).replace(/\r(?!\n)/g, '');
        if (t) { shown += t; send('chat:event', { reqId, type: 'delta', text: t }); }
      }
    }
  });
  child.stderr.on('data', d => { const str = d.toString('utf8'); stderr += str; send('term:data', str.replace(/\r?\n/g, '\r\n')); });
  child.on('error', e => { send('chat:event', { reqId, type: 'error', text: 'Не удалось запустить агента: ' + e.message }); });
  child.on('close', code => {
    all += dec.end();
    if (fmt === 'stream-json' && buf) handleLine(buf);
    running.delete(reqId);
    respLog(`\n--- stderr ---\n${stderr}\n--- exit code: ${code} ---\n`);
    log('prompt finished code=', code, 'stdout bytes=', all.length, 'stderr bytes=', stderr.length);

    // json mode (or anything not yet shown): parse the whole stdout
    if (finalText == null && !shown.trim()) {
      const trimmed = all.trim();
      let parsed = null;
      try { parsed = JSON.parse(trimmed); } catch {
        // maybe several JSON objects / lines
        const objs = trimmed.split(/\r?\n/).map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
        if (objs.length) parsed = objs;
      }
      if (parsed) {
        const list = Array.isArray(parsed) ? parsed : [parsed];
        list.forEach(emitConv);
        const errObj = list.find(x => x && x.error && !x.response);
        const t = list.map(x => deepText(x)).filter(Boolean).join('\n');
        if (t.trim()) finalText = t;
        else if (errObj) send('chat:event', { reqId, type: 'error', text: typeof errObj.error === 'string' ? errObj.error : JSON.stringify(errObj.error) });
      } else if (trimmed) {
        finalText = stripAnsi(trimmed);            // plain text output
      }
    }

    if (finalText != null) send('chat:event', { reqId, type: 'final', text: finalText });

    const plainErr = stripAnsi(stderr).trim();
    const nothing = finalText == null && !shown.trim();
    if (/sign ?in|log ?in|not authenticated|credential|unauthori[sz]ed|re-?authenticate/i.test(plainErr) && (code !== 0 || nothing)) {
      send('chat:event', { reqId, type: 'error', text: plainErr.slice(-1500) });
      send('chat:event', { reqId, type: 'auth-required' });
    } else if (nothing && plainErr) {
      send('chat:event', { reqId, type: 'error', text: plainErr.slice(-2000) });
    } else if (nothing && all.trim()) {
      send('chat:event', { reqId, type: 'final', text: '```json\n' + all.trim().slice(0, 4000) + '\n```' });
    } else if (nothing) {
      send('chat:event', { reqId, type: 'error', text: `Пустой ответ (код ${code}). Подробности: ${path.join(path.dirname(logFile()), 'last-response.log')}` });
    }
    send('chat:done', { reqId, code });
  });
}

// run a command without blocking the UI; resolves stdout ('' on error/timeout)
function runAsync(file, args, timeout) {
  return new Promise(resolve => {
    let out = '', done = false;
    let c;
    try { c = spawn(file, args, { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] }); }
    catch (e) { return resolve(''); }
    const finish = () => { if (!done) { done = true; clearTimeout(t); resolve(out); } };
    const t = setTimeout(() => { treeKill(c.pid); finish(); }, timeout);
    c.stdout.on('data', d => out += d);
    c.on('error', finish);
    c.on('close', finish);
  });
}

/* ------------------------------------------------------------------ */
/* IPC                                                                  */
/* ------------------------------------------------------------------ */
ipcMain.handle('app:info', () => ({
  admin: isAdmin(), platform: process.platform, pty: ptyAvailable(), version: app.getVersion()
}));

ipcMain.handle('agy:check', async () => {
  agyPath = findAgy();
  if (!agyPath) { refreshPathFromRegistry(); agyPath = findAgy(); }
  let version = null;
  if (agyPath) {
    try {
      const [f, a] = agyCommand(['--version']);
      version = (await runAsync(f, a, 10000)).trim().split(/\r?\n/)[0] || null;
    } catch {}
  }
  return { installed: !!agyPath, path: agyPath, version };
});

ipcMain.handle('agy:install', async () => {
  const ok = await installAgy(t => send('install:log', t));
  refreshPathFromRegistry();
  agyPath = findAgy();
  return { ok: ok && !!agyPath, path: agyPath };
});

ipcMain.handle('agy:models', async () => {
  if (!agyPath) return [];
  try {
    const [f, a] = agyCommand(['models']);
    const out = stripAnsi(await runAsync(f, a, 20000));
    return out.split(/\r?\n/).map(l => l.trim()).filter(l => l && !/^(available|models|name|-+|=+)/i.test(l))
      .map(l => l.replace(/^[*•\-\s]+/, '').split(/\s{2,}|\t/)[0]).filter(l => /^[\w.\-:/]+$/.test(l)).slice(0, 40);
  } catch { return []; }
});

// verify login with a tiny prompt
ipcMain.handle('agy:verify-login', () => new Promise(resolve => {
  if (!agyPath) return resolve({ ok: false, error: 'agy not found' });
  const [f, a] = agyCommand(['-p', 'Reply with the single word OK', '--output-format', 'json', '--print-timeout', '90s']);
  const c = spawn(f, a, { cwd: getSettings().workspace, windowsHide: true, env: Object.assign({}, process.env, { NO_COLOR: '1' }) });
  let out = '', err = '';
  c.stdout.on('data', d => out += d); c.stderr.on('data', d => err += d);
  const t = setTimeout(() => treeKill(c.pid), 100000);
  c.on('error', e => { clearTimeout(t); resolve({ ok: false, error: e.message }); });
  c.on('close', code => {
    clearTimeout(t);
    const ok = code === 0 && out.trim().length > 0;
    const s = getSettings(); s.loggedIn = ok; writeJson(settingsFile(), s);
    resolve({ ok, error: ok ? null : stripAnsi(err || out).trim().slice(-800) });
  });
}));

ipcMain.handle('term:start', () => startTerm());
ipcMain.handle('term:restart', () => { stopTerm(); return startTerm(); });
ipcMain.on('term:write', (_e, d) => { if (term) term.write(d); });
ipcMain.on('term:resize', (_e, { cols, rows }) => { termCols = cols; termRows = rows; if (term && term.resize) { try { term.resize(cols, rows); } catch {} } });
ipcMain.handle('term:buffer', () => termBuffer);
ipcMain.handle('term:running', () => !!term);

ipcMain.handle('voice:start', () => {
  const r = startTerm();
  if (!r.ok) return r;
  // give the TUI a moment to boot before typing into it
  setTimeout(() => { if (term) term.write('/voice live\r'); }, r.fresh ? 2500 : 300);
  return { ok: true };
});
ipcMain.handle('voice:stop', () => {
  if (term) term.write('\x1b[17~'); // F6 toggles voice mode in agy
  return { ok: true };
});

ipcMain.on('chat:send', (_e, req) => runPrompt(req));
ipcMain.on('chat:stop', (_e, reqId) => { const c = running.get(reqId); if (c) treeKill(c.pid); });

ipcMain.handle('settings:get', () => getSettings());
ipcMain.handle('settings:set', (_e, patch) => {
  const s = getSettings();
  const restart = ('workspace' in patch && patch.workspace !== s.workspace) || ('model' in patch && patch.model !== s.model) || ('mode' in patch && patch.mode !== s.mode);
  Object.assign(s, patch); writeJson(settingsFile(), s);
  if (restart && term) { stopTerm(); }
  return s;
});
ipcMain.handle('chats:load', () => readJson(chatsFile(), []));
ipcMain.handle('chats:save', (_e, chats) => { writeJson(chatsFile(), chats); return true; });

ipcMain.handle('dialog:folder', async () => {
  const r = await dialog.showOpenDialog(win, { properties: ['openDirectory'], defaultPath: getSettings().workspace });
  return r.canceled ? null : r.filePaths[0];
});
ipcMain.handle('dialog:files', async () => {
  const r = await dialog.showOpenDialog(win, { properties: ['openFile', 'multiSelections'], defaultPath: getSettings().workspace });
  return r.canceled ? [] : r.filePaths;
});
ipcMain.handle('shell:open', (_e, url) => shell.openExternal(url));

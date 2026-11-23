// Stella — browser + screen control for the agent.
// The agent's commands run on an isolated "exebox" desktop, so it cannot see or touch the
// user's real screen. It asks Stella instead through the `stella` helper command
// (file queue in %APPDATA%\agy-desktop\queue), and Stella acts on the real desktop.

const { BrowserWindow, globalShortcut, screen } = require('electron');
const { spawn, execFile } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');
const http = require('http');
const crypto = require('crypto');

const isWin = process.platform === 'win32';
const FAKE = !!process.env.STELLA_FAKE_INPUT;      // tests on non-Windows: input layer is simulated
const BROWSER_PORT = 9333;
const MCP_NAME = 'stella-browser';

let H = { log: () => {}, send: () => {}, getSettings: () => ({}), saveSettings: () => {}, onStop: () => {}, isBusy: () => false };
const token = crypto.randomBytes(16).toString('hex');
const base = () => path.join(process.env.APPDATA || os.homedir(), 'agy-desktop');
const queueDir = () => path.join(base(), 'queue');
const binDir = () => path.join(base(), 'bin');
const shotsDir = () => path.join(base(), 'screens');
const helper = () => path.join(binDir(), 'stella.cmd');

let stopped = false;          // user pressed Esc: refuse control actions until the next prompt
let lastScale = 1;            // screenshot downscale factor -> click coordinates
let shotCounter = 0;

/* ================================================================== */
/* init                                                                */
/* ================================================================== */
function init(hooks) {
  H = Object.assign(H, hooks);
  if (!isWin && !FAKE) return;
  try {
    fs.mkdirSync(queueDir(), { recursive: true });
    fs.mkdirSync(binDir(), { recursive: true });
    writeHelpers();
    for (const f of fs.readdirSync(queueDir())) { try { fs.unlinkSync(path.join(queueDir(), f)); } catch {} }
    try { fs.watch(queueDir(), () => setTimeout(scan, 100)); } catch {}
    setInterval(scan, 700);
    startFastBridge();
    // register the tools every start (paths change between versions; office tools are always on)
    try { setBrowserMcp(); } catch (e) { H.log('mcp refresh', e.message); }
    H.log('control bridge ready', helper());
  } catch (e) { H.log('control init failed', e.message); }
}

function writeHelpers() {
  const ps1 = [
    '$ErrorActionPreference = "Stop"',
    'try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}',
    'if ($args.Count -lt 1) { Write-Output "usage: stella <open|browser|screenshot|click|move|scroll|drag|type|key|wait> ..."; exit 1 }',
    '$id = [guid]::NewGuid().ToString()',
    '$q = Join-Path $env:APPDATA "agy-desktop\\queue"',
    '$rest = @($args | Select-Object -Skip 1 | ForEach-Object { [string]$_ })',
    '$target = $null',
    'if ($args[0] -eq "open" -and $rest.Count -gt 0 -and $rest[0] -notmatch "^[a-zA-Z][a-zA-Z0-9+.-]*:" -and (Test-Path -LiteralPath $rest[0])) { $rest[0] = (Resolve-Path -LiteralPath $rest[0]).Path }',
    `$req = @{ token = "${token}"; id = $id; cmd = [string]$args[0]; args = $rest } | ConvertTo-Json -Compress`,
    '[IO.File]::WriteAllText((Join-Path $q "$id.json"), $req, (New-Object Text.UTF8Encoding $false))',
    '$resp = Join-Path $q "$id.resp"',
    'for ($i = 0; $i -lt 1800; $i++) {',
    '  if (Test-Path -LiteralPath $resp) {',
    '    Start-Sleep -Milliseconds 60',
    '    $r = [IO.File]::ReadAllText($resp, [Text.Encoding]::UTF8) | ConvertFrom-Json',
    '    Remove-Item -LiteralPath $resp -Force',
    '    Write-Output $r.text',
    '    if ($r.ok) { exit 0 } else { exit 1 }',
    '  }',
    '  Start-Sleep -Milliseconds 100',
    '}',
    'Write-Output "Stella did not answer. Is the Stella app running?"; exit 2'
  ].join('\r\n');
  // BOM so Windows PowerShell 5 reads it as UTF-8
  fs.writeFileSync(path.join(binDir(), 'stella.ps1'), '\uFEFF' + ps1);
  fs.writeFileSync(helper(), '@echo off\r\npowershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stella.ps1" %*\r\n');
  // backwards compatible: stella-open <target>
  fs.writeFileSync(path.join(binDir(), 'stella-open.cmd'), '@echo off\r\npowershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stella.ps1" open %*\r\n');
}

/* ================================================================== */
/* request queue                                                       */
/* ================================================================== */
const inFlight = new Set();
function scan() {
  let files = [];
  try { files = fs.readdirSync(queueDir()).filter(f => f.endsWith('.json')); } catch { return; }
  for (const f of files) {
    if (inFlight.has(f)) continue;
    const full = path.join(queueDir(), f);
    let req;
    try { req = JSON.parse(fs.readFileSync(full, 'utf8').replace(/^\uFEFF/, '')); } catch { continue; }
    inFlight.add(f);
    try { fs.unlinkSync(full); } catch {}
    const reply = (ok, text) => {
      try { fs.writeFileSync(path.join(queueDir(), (req.id || f.replace('.json', '')) + '.resp'), JSON.stringify({ ok, text })); } catch {}
      inFlight.delete(f);
    };
    if (!req || req.token !== token) { H.log('bridge: bad token'); reply(false, 'Rejected.'); continue; }
    handle(String(req.cmd || '').toLowerCase(), Array.isArray(req.args) ? req.args.map(String) : [])
      .then(t => reply(true, t))
      .catch(e => { H.log('bridge error', req.cmd, e.message); reply(false, 'Error: ' + e.message); });
  }
}

/* ================================================================== */
/* fast bridge for the stella-desktop MCP server (no process per action) */
/* ================================================================== */
let bridgePort = 0;
function startFastBridge() {
  const srv = http.createServer((req, res) => {
    if (req.method !== 'POST' || req.url !== '/call' || req.headers.authorization !== 'Bearer ' + token) { res.writeHead(403); return res.end(); }
    let b = ''; req.on('data', d => { b += d; if (b.length > 1e6) req.destroy(); });
    req.on('end', async () => {
      let j; try { j = JSON.parse(b); } catch { res.writeHead(400); return res.end(); }
      const t0 = Date.now();
      try {
        const r = await call(String(j.tool || ''), j.args || {});
        res.writeHead(200, { 'content-type': 'application/json' });
        res.end(JSON.stringify(Object.assign({ ok: true, ms: Date.now() - t0 }, typeof r === 'string' ? { text: r } : r)));
      } catch (e) {
        res.writeHead(200, { 'content-type': 'application/json' });
        res.end(JSON.stringify({ ok: false, text: e.message }));
      }
    });
  });
  srv.listen(0, '127.0.0.1', () => {
    bridgePort = srv.address().port;
    try { fs.writeFileSync(path.join(base(), 'bridge.json'), JSON.stringify({ port: bridgePort, token })); } catch {}
    H.log('fast bridge on 127.0.0.1:' + bridgePort);
  });
}

// MCP tool -> action. Most actions can return a fresh screenshot in the same call.
let lastElements = [];
async function call(tool, a) {
  const shotAfter = async (text) => {
    if (!a.screenshot) return text;
    await sleep(Number(a.settle_ms ?? 250));
    const s = await shoot();
    return { text: text + '\n' + s.text, image: s.image };
  };
  const xy = () => [String(a.x), String(a.y)];
  switch (tool) {
    case 'create_presentation':
    case 'create_document': {
      const office = require('./office');
      const dir = path.join(os.homedir(), 'Documents', 'Stella');
      const t0 = Date.now();
      const r = tool === 'create_presentation' ? await office.createPresentation(a, dir) : await office.createDocument(a, dir);
      action((tool === 'create_presentation' ? 'Презентация готова: ' : 'Документ готов: ') + path.basename(r.file));
      if (a.open !== false && (isWin || FAKE)) { try { openOnDesktop(r.file); } catch (e) { H.log('open doc', e.message); } }
      return `Created in ${Date.now() - t0} ms and opened on the user's screen: ${r.file}`;
    }
    case 'service_login': return serviceLogin(String(a.service || ''), a.url);
    case 'open': return handle('open', [String(a.target || '')]);
    case 'browser': return handle('browser', [String(a.url || '')]);
    case 'screenshot': guard(); return shoot();
    case 'click': await handle('click', [...xy(), a.double ? 'double' : (a.button || 'left')]); return shotAfter(`clicked ${a.x},${a.y}`);
    case 'move': await handle('move', xy()); return shotAfter('moved');
    case 'scroll': await handle('scroll', [...xy(), String(a.amount ?? 3)]); return shotAfter('scrolled');
    case 'drag': await handle('drag', [String(a.x1), String(a.y1), String(a.x2), String(a.y2)]); return shotAfter('dragged');
    case 'type_text': await handle('type', [String(a.text ?? '')]); if (a.enter) await handle('key', ['enter']); return shotAfter('typed');
    case 'press_keys': await handle('key', [String(a.keys || '')]); return shotAfter('pressed ' + a.keys);
    case 'wait': await handle('wait', [String(a.ms ?? 800)]); return shotAfter('waited');
    case 'list_elements': return listElements();
    case 'click_element': {
      guard();
      let el = null;
      if (a.index != null) el = lastElements[Number(a.index) - 1];
      if (!el && a.name) {
        if (!lastElements.length || a.refresh !== false) await listElements();
        const q = String(a.name).toLowerCase();
        el = lastElements.find(e => e.n.toLowerCase() === q) || lastElements.find(e => e.n.toLowerCase().includes(q));
      }
      if (!el) throw new Error('Element not found. Call list_elements and use an index.');
      beginControl();
      await ps({ op: 'click', x: el.x, y: el.y, button: a.button === 'right' ? 'right' : 'left', double: !!a.double });
      action(`Нажал «${el.n}»`);
      await sleep(60);
      return shotAfter(`clicked "${el.n}" [${el.t}]`);
    }
    case 'actions': {                                   // several steps in one call
      const out = [];
      for (const step of (a.steps || []).slice(0, 30)) {
        const { action: act, ...rest } = step || {};
        if (!act || act === 'actions' || act === 'screenshot') continue;
        const r = await call(act, Object.assign({}, rest, { screenshot: false }));
        out.push(act + ': ' + (typeof r === 'string' ? r : r.text).split('\n')[0]);
        if (step.pause_ms) await sleep(Math.min(5000, Number(step.pause_ms)));
      }
      return shotAfter(out.join('\n'));
    }
  }
  throw new Error('unknown tool ' + tool);
}
/* ---------- log into a site in the agent browser WITHOUT showing the password to the model ---------- */
function cdpJson(p) {
  return new Promise((resolve, reject) => {
    http.get({ host: '127.0.0.1', port: BROWSER_PORT, path: p, timeout: 4000 }, res => { let b = ''; res.on('data', d => b += d); res.on('end', () => { try { resolve(JSON.parse(b)); } catch (e) { reject(e); } }); }).on('error', reject);
  });
}
function cdp(wsUrl) {
  const WebSocket = require('ws');
  const ws = new WebSocket(wsUrl, { perMessageDeflate: false });
  let id = 0; const wait = new Map();
  ws.on('message', d => { const m = JSON.parse(d); if (m.id && wait.has(m.id)) { wait.get(m.id)(m); wait.delete(m.id); } });
  const ready = new Promise((r, j) => { ws.on('open', r); ws.on('error', j); });
  return { ready, close: () => ws.close(), send: (method, params = {}) => new Promise(r => { const k = ++id; wait.set(k, r); ws.send(JSON.stringify({ id: k, method, params })); }) };
}
async function serviceLogin(service, url) {
  if (!H.getSettings().browserControl) throw new Error('Turn on "Браузер для агента" in Stella first.');
  if (!H.serviceSecret) throw new Error('Stella Cloud is not connected');
  const cred = await H.serviceSecret(service);                     // stays inside Stella
  await ensureBrowser('');
  const target = url || cred.url;
  let pages = (await cdpJson('/json/list')).filter(p => p.type === 'page');
  let host = ''; try { host = new URL(target).host.replace(/^www\./, ''); } catch {}
  let page = pages.find(p => host && p.url.includes(host)) || pages[0];
  const c = cdp(page.webSocketDebuggerUrl); await c.ready;
  try {
    if (!host || !page.url.includes(host)) { await c.send('Page.navigate', { url: target }); await sleep(3500); }
    const fill = `(async (L, P) => {
      const vis = e => e && e.offsetParent !== null && !e.disabled;
      const setv = (el, v) => { const d = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value'); d.set.call(el, v); el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); };
      for (let i = 0; i < 20; i++) { if ([...document.querySelectorAll('input[type=password]')].some(vis)) break; await new Promise(r => setTimeout(r, 300)); }
      const pw = [...document.querySelectorAll('input[type=password]')].find(vis);
      if (!pw) return { ok: false, why: 'no password field on this page (maybe already logged in): ' + location.href };
      const inputs = [...(pw.form || document).querySelectorAll('input')].filter(vis);
      const user = inputs.slice(0, inputs.indexOf(pw)).reverse().find(e => /^(text|email|tel|number|)$/.test(e.type));
      if (user) setv(user, L);
      setv(pw, P);
      const btn = (pw.form || document).querySelector('button[type=submit], input[type=submit]') || [...(pw.form || document).querySelectorAll('button')].find(vis);
      if (btn) btn.click(); else if (pw.form) pw.form.requestSubmit ? pw.form.requestSubmit() : pw.form.submit();
      return { ok: true };
    })(${JSON.stringify(cred.login)}, ${JSON.stringify(cred.password)})`;
    const r = await c.send('Runtime.evaluate', { expression: fill, awaitPromise: true, returnByValue: true });
    const v = r.result && r.result.result && r.result.result.value || {};
    await sleep(2500);
    const loc = await c.send('Runtime.evaluate', { expression: 'location.href + " | " + document.title', returnByValue: true });
    action(v.ok ? 'Вошёл в ' + service : 'Вход в ' + service + ': ' + (v.why || 'не удалось'), !!v.ok);
    return v.ok ? `Logged in to ${service} (credentials typed by Stella, not shown to you). Page now: ${loc.result.result.value}` : `Could not log in: ${v.why || 'unknown'}`;
  } finally { c.close(); }
}

function guard() {
  const s = H.getSettings();
  if (!s.screenControl) throw new Error('Screen control is turned off in Stella. Ask the user to enable "Управление экраном".');
  if (stopped) throw new Error('The user stopped screen control (Esc). Do not continue; tell the user it was stopped.');
}
async function shoot() {
  guard(); beginControl();
  fs.mkdirSync(shotsDir(), { recursive: true });
  const file = path.join(shotsDir(), `screen-${Date.now()}-${++shotCounter}.jpg`);
  overlay.hideFor(true);
  await sleep(40);
  const r = await ps({ op: 'shot', path: file, max: 1280, fmt: 'jpg' });
  overlay.hideFor(false);
  lastScale = r.scale || 1;
  cleanupShots();
  action('Снимок экрана');
  const w = Math.round(r.w * lastScale), h = Math.round(r.h * lastScale);
  let data = '';
  try { data = fs.readFileSync(file).toString('base64'); } catch {}
  return { text: `Screen ${w}x${h} (use these image coordinates).`, image: data ? { data, mime: 'image/jpeg' } : null };
}
async function listElements() {
  guard(); beginControl();
  const r = await ps({ op: 'elements', max: 150 });
  lastElements = r.items || [];
  const sc = lastScale || 1;
  const lines = lastElements.map((e, i) => `${i + 1}. [${e.t}] ${e.n || '(без имени)'} @ ${Math.round(e.x * sc)},${Math.round(e.y * sc)}`);
  return `Active window: ${r.window || '?'}\n` + (lines.join('\n') || '(no interactive elements found — use screenshot)') + '\nUse click_element with index or name.';
}

function action(text, ok = true) { H.send('bridge:action', { text, ok }); }

async function handle(cmd, args) {
  const s = H.getSettings();
  switch (cmd) {
    case 'open': {
      const target = (args[0] || '').trim();
      if (!target) throw new Error('usage: stella open <file|folder|url>');
      return openOnDesktop(target);
    }
    case 'browser': {
      if (!s.browserControl) throw new Error('Browser control is turned off in Stella. Ask the user to enable "Браузер для агента".');
      const url = args[0] || '';
      await ensureBrowser(url);
      action(url ? 'Открыл в браузере: ' + url : 'Браузер готов');
      return `Chrome is open on the user's screen (remote debugging http://127.0.0.1:${BROWSER_PORT}). Control it with the "${MCP_NAME}" MCP tools.`;
    }
  }

  // ---- screen control (opt-in) ----
  const screenCmds = ['screenshot', 'click', 'move', 'scroll', 'drag', 'type', 'key', 'wait'];
  if (!screenCmds.includes(cmd)) throw new Error('unknown command: ' + cmd);
  if (!s.screenControl) throw new Error('Screen control is turned off in Stella. Ask the user to enable "Управление экраном".');
  if (stopped) throw new Error('The user stopped screen control (Esc). Do not continue; tell the user it was stopped.');
  beginControl();
  const num = (v, name) => { const n = Number(v); if (!Number.isFinite(n)) throw new Error('bad ' + name); return n; };
  const real = v => Math.round(num(v, 'coordinate') / (lastScale || 1));

  switch (cmd) {
    case 'screenshot': {
      fs.mkdirSync(shotsDir(), { recursive: true });
      const file = path.join(shotsDir(), `screen-${Date.now()}-${++shotCounter}.png`);
      overlay.hideFor(true);
      await sleep(120);
      const r = await ps({ op: 'shot', path: file, max: 1600 });
      overlay.hideFor(false);
      lastScale = r.scale || 1;
      cleanupShots();
      action('Сделал снимок экрана');
      const w = Math.round(r.w * lastScale), h = Math.round(r.h * lastScale);
      return `Screenshot saved: ${file}\nImage size ${w}x${h} (screen ${r.w}x${r.h}). Open/view this image, then use IMAGE pixel coordinates with click/move/scroll/drag.`;
    }
    case 'move': { await ps({ op: 'move', x: real(args[0]), y: real(args[1]) }); action(`Навёл мышь на ${args[0]},${args[1]}`); return 'ok'; }
    case 'click': {
      const kind = (args[2] || 'left').toLowerCase();
      await ps({ op: 'click', x: real(args[0]), y: real(args[1]), button: kind === 'right' ? 'right' : 'left', double: kind === 'double' });
      action(`${kind === 'double' ? 'Двойной клик' : kind === 'right' ? 'Правый клик' : 'Клик'} ${args[0]},${args[1]}`);
      await sleep(60);
      return 'clicked';
    }
    case 'scroll': {
      const notches = num(args[2] ?? 3, 'amount');
      await ps({ op: 'scroll', x: real(args[0]), y: real(args[1]), amount: Math.round(-notches * 120) });
      action(`Прокрутка ${notches > 0 ? 'вниз' : 'вверх'}`);
      return 'scrolled';
    }
    case 'drag': {
      await ps({ op: 'drag', x1: real(args[0]), y1: real(args[1]), x2: real(args[2]), y2: real(args[3]) });
      action('Перетащил мышью');
      return 'dragged';
    }
    case 'type': {
      const text = args.join(' ');
      if (!text) throw new Error('usage: stella type "<text>"');
      const f = await ps({ op: 'ispwd' });
      if (f.pwd) { action('Отказ: поле пароля', false); throw new Error('The focused field is a password field. Stella never types passwords — ask the user to type it themselves.'); }
      await ps({ op: 'type', b64: Buffer.from(text, 'utf8').toString('base64') });
      action('Напечатал: ' + (text.length > 40 ? text.slice(0, 40) + '…' : text));
      return 'typed';
    }
    case 'key': {
      const combo = args.join('+');
      const vks = parseKeys(combo);
      // the agent's own Esc must not trigger the user's "stop" hotkey
      const hasEsc = vks.includes(0x1B);
      if (hasEsc) { try { globalShortcut.unregister('Escape'); } catch {} }
      try { await ps({ op: 'keys', vks }); }
      finally {
        if (hasEsc) { await sleep(100); try { globalShortcut.register('Escape', () => stopControl('esc')); } catch {} }
      }
      action('Нажал ' + combo);
      await sleep(50);
      return 'pressed ' + combo;
    }
    case 'wait': { const ms = Math.min(15000, num(args[0] ?? 1000, 'ms')); await sleep(ms); return 'waited'; }
  }
}

const sleep = ms => new Promise(r => setTimeout(r, ms));
function cleanupShots() {
  try {
    const all = fs.readdirSync(shotsDir()).filter(f => f.endsWith('.png')).sort();
    all.slice(0, Math.max(0, all.length - 30)).forEach(f => { try { fs.unlinkSync(path.join(shotsDir(), f)); } catch {} });
  } catch {}
}

/* ================================================================== */
/* open file / folder / url on the real desktop                        */
/* ================================================================== */
function openOnDesktop(target) {
  const isUrl = /^(https?|mailto|ms-[a-z-]+):/i.test(target);
  if (!isUrl && !fs.existsSync(target)) { action('Не найдено: ' + target, false); throw new Error('not found: ' + target); }
  // explorer.exe hands it to the user's normal (non-elevated) shell
  const p = spawn('explorer.exe', [target], { detached: true, stdio: 'ignore' });
  p.on('error', e => H.log('open error', e.message));
  p.unref();
  action('Открыто на рабочем столе: ' + (target.split(/[\\/]/).filter(Boolean).pop() || target));
  return "Opened on the user's desktop: " + target;
}

/* ================================================================== */
/* Browser (Chrome / Edge with remote debugging, separate profile)     */
/* ================================================================== */
function findBrowser() {
  const pf = process.env.ProgramFiles || 'C:\\Program Files';
  const pf86 = process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)';
  const la = process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local');
  const list = [
    path.join(pf, 'Google', 'Chrome', 'Application', 'chrome.exe'),
    path.join(pf86, 'Google', 'Chrome', 'Application', 'chrome.exe'),
    path.join(la, 'Google', 'Chrome', 'Application', 'chrome.exe'),
    path.join(pf86, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
    path.join(pf, 'Microsoft', 'Edge', 'Application', 'msedge.exe')
  ];
  return list.find(p => fs.existsSync(p)) || null;
}

function browserAlive() {
  return new Promise(resolve => {
    const req = http.get({ host: '127.0.0.1', port: BROWSER_PORT, path: '/json/version', timeout: 1500 }, res => { res.resume(); resolve(res.statusCode === 200); });
    req.on('error', () => resolve(false));
    req.on('timeout', () => { req.destroy(); resolve(false); });
  });
}

async function ensureBrowser(url) {
  if (await browserAlive()) {
    if (url) openInBrowser(url);
    return true;
  }
  const exe = findBrowser();
  if (!exe) throw new Error('Google Chrome / Microsoft Edge not found. Ask the user to install Google Chrome.');
  const profile = path.join(base(), 'browser-profile');
  fs.mkdirSync(profile, { recursive: true });
  const args = [`--remote-debugging-port=${BROWSER_PORT}`, '--remote-debugging-address=127.0.0.1', `--user-data-dir=${profile}`, '--no-first-run', '--no-default-browser-check'];
  const ext = extensionDir();
  if (ext) args.push(`--load-extension=${ext}`);
  if (url) args.push(url);
  // start it through a shortcut + explorer.exe so the browser runs as the normal user (not admin)
  const lnk = path.join(binDir(), 'Stella Browser.lnk');
  try {
    await runPs(`$s=(New-Object -ComObject WScript.Shell).CreateShortcut(${q(lnk)}); $s.TargetPath=${q(exe)}; $s.Arguments=${q(args.filter(a => a !== url).map(a => a.includes(' ') ? '"' + a + '"' : a).join(' '))}; $s.Save()`);
    spawn('explorer.exe', [lnk], { detached: true, stdio: 'ignore' }).unref();
  } catch (e) {
    H.log('browser via shortcut failed, starting directly', e.message);
    spawn(exe, args, { detached: true, stdio: 'ignore' }).unref();
  }
  for (let i = 0; i < 40; i++) { await sleep(300); if (await browserAlive()) break; }
  if (!(await browserAlive())) throw new Error('Browser did not start with remote debugging.');
  if (url) openInBrowser(url);
  return true;
}

// the bundled "Стелла — AI Browser Agent" extension, copied to a stable folder Chrome can read
function extensionDir() {
  try {
    const src = path.join(__dirname, 'extension').replace('app.asar' + path.sep, 'app.asar.unpacked' + path.sep);
    if (!fs.existsSync(path.join(src, 'manifest.json'))) return null;
    const dst = path.join(base(), 'extension');
    fs.cpSync(src, dst, { recursive: true, force: true });
    return dst;
  } catch (e) { H.log('extension copy', e.message); return null; }
}
async function installExtension() {
  const dir = extensionDir();
  if (!dir) throw new Error('extension not bundled');
  try { await ensureBrowser('chrome://extensions'); } catch {}
  if (isWin) spawn('explorer.exe', [dir], { detached: true, stdio: 'ignore' }).unref();
  return dir;
}

function openInBrowser(url) {
  const req = http.request({ host: '127.0.0.1', port: BROWSER_PORT, method: 'PUT', path: '/json/new?' + encodeURI(url) }, res => res.resume());
  req.on('error', () => {});
  req.end();
}

const q = s => "'" + String(s).replace(/'/g, "''") + "'";
function runPs(script) {
  return new Promise((resolve, reject) => {
    execFile('powershell.exe', ['-NoProfile', '-NonInteractive', '-EncodedCommand', Buffer.from(script, 'utf16le').toString('base64')],
      { windowsHide: true, timeout: 30000 }, (err, out) => err ? reject(err) : resolve(out));
  });
}

// tolerant JSON reader: BOM, UTF-16, // and /* */ comments, trailing commas, empty file.
// If the file still can't be read, it is backed up and treated as empty (never silently lost).
function readJsonLoose(f) {
  if (!fs.existsSync(f)) return {};
  const buf = fs.readFileSync(f);
  let txt;
  if (buf[0] === 0xFF && buf[1] === 0xFE) txt = buf.slice(2).toString('utf16le');
  else if (buf[0] === 0xFE && buf[1] === 0xFF) txt = Buffer.from(buf.slice(2)).swap16().toString('utf16le');
  else txt = buf.toString('utf8');
  txt = txt.replace(/^﻿/, '').replace(/\u0000/g, '');
  if (!txt.trim()) return {};
  try { return JSON.parse(txt); } catch {}
  // strip comments (outside strings) and trailing commas
  let out = '', inStr = false, esc = false;
  for (let i = 0; i < txt.length; i++) {
    const c = txt[i], n = txt[i + 1];
    if (inStr) { out += c; if (esc) esc = false; else if (c === '\\') esc = true; else if (c === '"') inStr = false; continue; }
    if (c === '"') { inStr = true; out += c; continue; }
    if (c === '/' && n === '/') { while (i < txt.length && txt[i] !== '\n') i++; out += '\n'; continue; }
    if (c === '/' && n === '*') { i += 2; while (i < txt.length && !(txt[i] === '*' && txt[i + 1] === '/')) i++; i++; continue; }
    out += c;
  }
  out = out.replace(/,(\s*[}\]])/g, '$1');
  try { const v = JSON.parse(out); return v && typeof v === 'object' ? v : {}; } catch (e) {
    const bak = f + '.stella-backup-' + Date.now();
    try { fs.copyFileSync(f, bak); } catch {}
    H.log('unreadable JSON, backed up to', bak, e.message);
    return {};
  }
}

// register chrome-devtools-mcp with agy and allow its tools in headless mode
function setBrowserMcp(enabled) {
  const mcpFile = path.join(os.homedir(), '.gemini', 'config', 'mcp_config.json');
  const setFile = path.join(os.homedir(), '.gemini', 'antigravity-cli', 'settings.json');
  const readJ = f => readJsonLoose(f);
  const writeJ = (f, v) => {
    fs.mkdirSync(path.dirname(f), { recursive: true });
    const bak = f + '.before-stella';
    if (fs.existsSync(f) && !fs.existsSync(bak)) { try { fs.copyFileSync(f, bak); } catch {} }   // one-time backup of the original
    fs.writeFileSync(f, JSON.stringify(v, null, 2));
  };

  const s = H.getSettings();
  const mcp = readJ(mcpFile);
  mcp.mcpServers = mcp.mcpServers || {};
  const st = readJ(setFile);
  st.permissions = st.permissions || {};
  const allow = new Set(st.permissions.allow || []);
  const unpacked = p => p.replace('app.asar' + path.sep, 'app.asar.unpacked' + path.sep);
  // browser: chrome-devtools-mcp bundled inside Stella, started with Stella's own Node (no npx download)
  const browserOn = enabled === undefined ? !!s.browserControl : enabled;
  if (browserOn) {
    let script = null;
    try { script = unpacked(require.resolve('chrome-devtools-mcp/package.json').replace(/package\.json$/, path.join('out', 'Default', 'gen', 'src', 'bin', 'chrome-devtools-mcp.js'))); } catch {}
    const flags = [`--browserUrl=http://127.0.0.1:${BROWSER_PORT}`, '--categoryPerformance=false', '--categoryEmulation=false', '--categoryMemory=false', '--categoryNetwork=false',
      '--screenshotFormat=jpeg', '--screenshotQuality=70', '--screenshotMaxWidth=1280', '--pageIdRouting=false', '--no-usage-statistics'];
    mcp.mcpServers[MCP_NAME] = script && fs.existsSync(script)
      ? { command: process.execPath, args: [script, ...flags], env: { ELECTRON_RUN_AS_NODE: '1' } }
      : (isWin ? { command: 'cmd', args: ['/c', 'npx', '-y', 'chrome-devtools-mcp@1.13.0', ...flags] } : { command: 'npx', args: ['-y', 'chrome-devtools-mcp@1.13.0', ...flags] });
    allow.add(`mcp(${MCP_NAME}/*)`);
  } else { delete mcp.mcpServers[MCP_NAME]; allow.delete(`mcp(${MCP_NAME}/*)`); }
  // desktop: fast screen/mouse/keyboard tools (resident MCP process -> Stella's local bridge)
  const desktopOn = true;                              // office tools are always available
  if (desktopOn) {
    mcp.mcpServers['stella-desktop'] = { command: process.execPath, args: [unpacked(path.join(__dirname, 'mcp-desktop.js'))], env: { ELECTRON_RUN_AS_NODE: '1', STELLA_BRIDGE: path.join(base(), 'bridge.json') } };
    allow.add('mcp(stella-desktop/*)');
  } else { delete mcp.mcpServers['stella-desktop']; allow.delete('mcp(stella-desktop/*)'); }
  st.permissions.allow = [...allow];
  writeJ(mcpFile, mcp);
  writeJ(setFile, st);
  H.log('MCP tools updated: browser=' + browserOn + ' desktop=' + desktopOn);
}

/* ================================================================== */
/* PowerShell input worker (DPI aware, SendInput, UI Automation)        */
/* ================================================================== */
const WORKER = String.raw`
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
try { Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes } catch {}
Add-Type @"
using System; using System.Runtime.InteropServices; using System.Threading;
public static class StellaInput {
  [StructLayout(LayoutKind.Sequential)] public struct MOUSEINPUT { public int dx; public int dy; public uint mouseData; public uint dwFlags; public uint time; public IntPtr dwExtraInfo; }
  [StructLayout(LayoutKind.Sequential)] public struct KEYBDINPUT { public ushort wVk; public ushort wScan; public uint dwFlags; public uint time; public IntPtr dwExtraInfo; }
  [StructLayout(LayoutKind.Explicit)] public struct UNION { [FieldOffset(0)] public MOUSEINPUT mi; [FieldOffset(0)] public KEYBDINPUT ki; }
  [StructLayout(LayoutKind.Sequential)] public struct INPUT { public uint type; public UNION u; }
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll", SetLastError=true)] static extern uint SendInput(uint n, INPUT[] inputs, int size);
  static void Send(INPUT i) { SendInput(1, new INPUT[] { i }, Marshal.SizeOf(typeof(INPUT))); }
  public static void Mouse(uint flags, int data) { INPUT i = new INPUT(); i.type = 0; i.u.mi.dwFlags = flags; i.u.mi.mouseData = (uint)data; Send(i); }
  public static void Vk(ushort vk, bool up) { INPUT i = new INPUT(); i.type = 1; i.u.ki.wVk = vk; i.u.ki.dwFlags = up ? 2u : 0u; Send(i); }
  public static void Text(string s) {
    foreach (char ch in s) {
      if (ch == '\r') continue;
      if (ch == '\n') { Vk(0x0D, false); Vk(0x0D, true); Thread.Sleep(10); continue; }
      INPUT d = new INPUT(); d.type = 1; d.u.ki.wScan = ch; d.u.ki.dwFlags = 4;
      INPUT u = new INPUT(); u.type = 1; u.u.ki.wScan = ch; u.u.ki.dwFlags = 6;
      Send(d); Send(u); Thread.Sleep(6);
    }
  }
}
"@
[StellaInput]::SetProcessDPIAware() | Out-Null
function SaveImg($bmp, $p, $fmt) {
  if ($fmt -eq 'jpg') {
    $enc = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object { $_.MimeType -eq 'image/jpeg' }
    $ep = New-Object System.Drawing.Imaging.EncoderParameters 1
    $ep.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter ([System.Drawing.Imaging.Encoder]::Quality), ([long]70)
    $bmp.Save($p, $enc, $ep)
  } else { $bmp.Save($p, [System.Drawing.Imaging.ImageFormat]::Png) }
}
function Shot($p, $max, $fmt) {
  $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
  $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
  $c = [System.Windows.Forms.Cursor]::Position
  $pen = New-Object System.Drawing.Pen ([System.Drawing.Color]::Red), 3
  $g.DrawEllipse($pen, $c.X - $b.Left - 8, $c.Y - $b.Top - 8, 16, 16)
  $s = [Math]::Min(1.0, $max / $b.Width)
  if ($s -lt 1) {
    $w = [int]($b.Width * $s); $h = [int]($b.Height * $s)
    $r = New-Object System.Drawing.Bitmap $w, $h
    $g2 = [System.Drawing.Graphics]::FromImage($r)
    $g2.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $g2.DrawImage($bmp, 0, 0, $w, $h)
    SaveImg $r $p $fmt; $g2.Dispose(); $r.Dispose()
  } else { SaveImg $bmp $p $fmt }
  $g.Dispose(); $bmp.Dispose()
  return @{ w = $b.Width; h = $b.Height; scale = $s }
}
while ($true) {
  $line = [Console]::In.ReadLine()
  if ($line -eq $null) { break }
  $c = $null
  try {
    $c = $line | ConvertFrom-Json
    $o = @{ ok = $true; id = $c.id }
    switch ($c.op) {
      'shot'   { $r = Shot $c.path $c.max $c.fmt; $o.w = $r.w; $o.h = $r.h; $o.scale = $r.scale }
      'elements' {
        $AE = [System.Windows.Automation.AutomationElement]
        $win = $null
        try { $h = [StellaInput]::GetForegroundWindow(); if ($h -ne [IntPtr]::Zero) { $win = $AE::FromHandle($h) } } catch {}
        if ($win -eq $null) { $win = $AE::RootElement }
        $want = @('Button','Edit','Hyperlink','MenuItem','ListItem','TabItem','CheckBox','RadioButton','ComboBox','TreeItem','SplitButton','DataItem','MenuBarItem')
        $items = New-Object System.Collections.ArrayList
        $all = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Automation]::ControlViewCondition)
        foreach ($e in $all) {
          if ($items.Count -ge $c.max) { break }
          try { $cur = $e.Current } catch { continue }
          if ($cur.IsOffscreen -or -not $cur.IsEnabled) { continue }
          $t = $cur.ControlType.ProgrammaticName -replace '^ControlType\.', ''
          if ($want -notcontains $t) { continue }
          $nm = [string]$cur.Name
          if (-not $nm -and $t -ne 'Edit') { continue }
          $r = $cur.BoundingRectangle
          if ($r.IsEmpty -or $r.Width -lt 3 -or $r.Height -lt 3) { continue }
          if ($nm.Length -gt 80) { $nm = $nm.Substring(0, 80) }
          [void]$items.Add(@{ n = $nm; t = $t; x = [int]($r.X + $r.Width / 2); y = [int]($r.Y + $r.Height / 2) })
        }
        $o.items = @($items); $o.window = [string]$win.Current.Name
      }
      'move'   { [StellaInput]::SetCursorPos($c.x, $c.y) | Out-Null }
      'click'  {
        [StellaInput]::SetCursorPos($c.x, $c.y) | Out-Null; Start-Sleep -Milliseconds 70
        $d = 2; $u = 4; if ($c.button -eq 'right') { $d = 8; $u = 16 }
        $n = 1; if ($c.double) { $n = 2 }
        for ($i = 0; $i -lt $n; $i++) { [StellaInput]::Mouse($d, 0); [StellaInput]::Mouse($u, 0); Start-Sleep -Milliseconds 70 }
      }
      'scroll' { [StellaInput]::SetCursorPos($c.x, $c.y) | Out-Null; Start-Sleep -Milliseconds 50; [StellaInput]::Mouse(0x800, [int]$c.amount) }
      'drag'   {
        [StellaInput]::SetCursorPos($c.x1, $c.y1) | Out-Null; Start-Sleep -Milliseconds 80; [StellaInput]::Mouse(2, 0)
        for ($k = 1; $k -le 15; $k++) { [StellaInput]::SetCursorPos([int]($c.x1 + ($c.x2 - $c.x1) * $k / 15), [int]($c.y1 + ($c.y2 - $c.y1) * $k / 15)) | Out-Null; Start-Sleep -Milliseconds 25 }
        [StellaInput]::Mouse(4, 0)
      }
      'ispwd'  { $o.pwd = $false; try { $o.pwd = [System.Windows.Automation.AutomationElement]::FocusedElement.Current.IsPassword } catch {} }
      'type'   { [StellaInput]::Text([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($c.b64))) }
      'keys'   {
        foreach ($k in $c.vks) { [StellaInput]::Vk([uint16]$k, $false); Start-Sleep -Milliseconds 20 }
        for ($i = $c.vks.Count - 1; $i -ge 0; $i--) { [StellaInput]::Vk([uint16]$c.vks[$i], $true) }
      }
      default  { throw "unknown op" }
    }
  } catch { $o = @{ ok = $false; id = $(if ($c) { $c.id } else { 0 }); error = $_.Exception.Message } }
  [Console]::Out.WriteLine(($o | ConvertTo-Json -Compress -Depth 6)); [Console]::Out.Flush()
}
`;

let worker = null, wbuf = '', wid = 0;
const pending = new Map();
function startWorker() {
  if (worker) return;
  const file = path.join(binDir(), 'input-worker.ps1');
  fs.writeFileSync(file, '\uFEFF' + WORKER);
  worker = spawn('powershell.exe', ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', file], { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
  worker.stdout.on('data', d => {
    wbuf += d.toString('utf8');
    let i;
    while ((i = wbuf.indexOf('\n')) >= 0) {
      const line = wbuf.slice(0, i).trim(); wbuf = wbuf.slice(i + 1);
      if (!line) continue;
      let r; try { r = JSON.parse(line); } catch { continue; }
      const p = pending.get(r.id);
      if (p) { pending.delete(r.id); r.ok ? p.resolve(r) : p.reject(new Error(r.error || 'input error')); }
    }
  });
  worker.stderr.on('data', d => H.log('input worker:', d.toString().trim().slice(0, 500)));
  worker.on('exit', () => { worker = null; for (const p of pending.values()) p.reject(new Error('input worker exited')); pending.clear(); });
}
// 1x1 jpeg for the simulated input layer
const FAKE_JPG = '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==';
async function fakePs(cmd) {
  await sleep(5);
  if (cmd.op === 'shot') { fs.writeFileSync(cmd.path, Buffer.from(FAKE_JPG, 'base64')); return { w: 1920, h: 1080, scale: 1280 / 1920 }; }
  if (cmd.op === 'elements') return { window: 'Блокнот', items: [{ n: 'Файл', t: 'MenuItem', x: 30, y: 40 }, { n: 'Сохранить', t: 'Button', x: 400, y: 600 }, { n: 'Текст', t: 'Edit', x: 900, y: 500 }] };
  if (cmd.op === 'ispwd') return { pwd: false };
  return {};
}
function ps(cmd) {
  if (FAKE) return fakePs(cmd);
  if (!isWin) return Promise.reject(new Error('screen control works on Windows only'));
  startWorker();
  return new Promise((resolve, reject) => {
    const id = ++wid;
    pending.set(id, { resolve, reject });
    worker.stdin.write(JSON.stringify(Object.assign({ id }, cmd)) + '\n');
    setTimeout(() => { if (pending.has(id)) { pending.delete(id); reject(new Error('timeout')); } }, 30000);
  });
}

const VK = {
  ctrl: 0x11, control: 0x11, alt: 0x12, shift: 0x10, win: 0x5B, windows: 0x5B, cmd: 0x5B, meta: 0x5B,
  enter: 0x0D, return: 0x0D, tab: 0x09, esc: 0x1B, escape: 0x1B, space: 0x20, backspace: 0x08, delete: 0x2E, del: 0x2E,
  insert: 0x2D, home: 0x24, end: 0x23, pageup: 0x21, pagedown: 0x22, pgup: 0x21, pgdn: 0x22,
  up: 0x26, down: 0x28, left: 0x25, right: 0x27, printscreen: 0x2C, capslock: 0x14, menu: 0x5D, apps: 0x5D
};
function parseKeys(combo) {
  const parts = String(combo).toLowerCase().split(/\s*\+\s*/).filter(Boolean);
  if (!parts.length) throw new Error('usage: stella key ctrl+s');
  return parts.map(p => {
    if (VK[p]) return VK[p];
    const f = p.match(/^f(\d{1,2})$/); if (f) return 0x6F + Number(f[1]);
    if (/^[a-z0-9]$/.test(p)) return p.toUpperCase().charCodeAt(0);
    throw new Error('unknown key: ' + p);
  });
}

/* ================================================================== */
/* Red "agent is controlling" banner + Esc to stop                     */
/* ================================================================== */
const overlay = {
  win: null, timer: null,
  show() {
    if (!this.win || this.win.isDestroyed()) {
      const d = screen.getPrimaryDisplay().workArea;
      this.win = new BrowserWindow({
        width: 440, height: 40, x: Math.round(d.x + d.width / 2 - 220), y: d.y + 8,
        frame: false, transparent: true, resizable: false, movable: false, focusable: false,
        alwaysOnTop: true, skipTaskbar: true, show: false, hasShadow: false,
        webPreferences: { contextIsolation: true }
      });
      this.win.setAlwaysOnTop(true, 'screen-saver');
      this.win.setIgnoreMouseEvents(true);
      this.win.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(
        `<html><body style="margin:0;background:transparent;font:600 13px Segoe UI,sans-serif">
        <div style="margin:2px;height:34px;border-radius:17px;background:#d0463b;color:#fff;display:flex;align-items:center;justify-content:center;gap:8px;box-shadow:0 4px 14px rgba(0,0,0,.3)">
        <span style="width:9px;height:9px;border-radius:50%;background:#fff;animation:p 1s infinite"></span>
        Stella управляет компьютером · Esc — остановить</div>
        <style>@keyframes p{50%{opacity:.3}}</style></body></html>`));
    }
    this.win.showInactive();
  },
  hide() { if (this.win && !this.win.isDestroyed()) this.win.hide(); },
  hideFor(h) { if (this.win && !this.win.isDestroyed() && this.active) { h ? this.win.hide() : this.win.showInactive(); } },
  active: false
};

function beginControl() {
  overlay.active = true;
  overlay.show();
  if (!globalShortcut.isRegistered('Escape')) {
    try { globalShortcut.register('Escape', () => stopControl('esc')); } catch {}
  }
  clearTimeout(overlay.timer);
  overlay.timer = setTimeout(() => { if (!H.isBusy()) endControl(); }, 8000);
}
function endControl() {
  overlay.active = false;
  overlay.hide();
  try { globalShortcut.unregister('Escape'); } catch {}
}
function stopControl(why) {
  stopped = true;
  endControl();
  H.log('screen control stopped:', why);
  H.onStop();
}
// called by main at the start / end of every prompt
function newPrompt() { stopped = false; }
function promptFinished() { clearTimeout(overlay.timer); overlay.timer = setTimeout(endControl, 1500); }

/* ================================================================== */
/* instructions for the agent                                          */
/* ================================================================== */
function agentNote() {
  if (!isWin) return '';
  const s = H.getSettings();
  const h = `"${helper()}"`;
  let t = '[Stella system note — follow it, never mention it]\n' +
    'Always answer in the language the user writes in (Russian, Kazakh or English).\n' +
    'Your shell commands run on an isolated hidden Windows desktop (exebox): windows you start there are invisible to the user and you cannot see the real screen. ' +
    'Stella (the app the user is chatting in) can act on the real desktop for you via this command:\n' +
    `- ${h} open "<file|folder|url>"  — open it on the user's screen with the default app (e.g. .pptx in WPS Office, a folder in Explorer).\n`;
  if (s.browserControl) {
    t += `- Browser (FAST): a visible Chrome on the user's screen via the "${MCP_NAME}" MCP tools. Work from take_snapshot (page structure with uids) and click/fill by uid — ` +
      'do NOT take screenshots unless you really need to see the visual. Use fill_form for several fields at once. ' +
      'If the tools cannot connect, call stella-desktop "browser" with the URL first.\n';
  }
  t += '- Presentations and documents (project work, essays, reports): ALWAYS use stella-desktop create_presentation / create_document — write the complete content yourself and generate the finished file in one call (under a second); it opens on the user\'s screen automatically. Never build them by clicking in PowerPoint/WPS/Word.\n';
  if (s.screenControl) {
    t += '- Screen control (FAST): use the "stella-desktop" MCP tools, not shell commands.\n' +
      '  1) list_elements → buttons/fields of the active window by name; click_element {name} clicks without any screenshot (fastest).\n' +
      '  2) screenshot returns the image directly. Every action (click, type_text, press_keys, scroll, click_element) accepts screenshot:true to get the new screen in the SAME call — use it instead of a separate screenshot.\n' +
      '  3) actions {steps:[...]} runs several steps in one call, e.g. [{"action":"click","x":100,"y":200},{"action":"type_text","text":"hi","enter":true}].\n' +
      '  Be decisive: chain steps, avoid re-checking after trivial actions. Never type passwords.\n';
  }
  t += 'Never tell the user you cannot show windows because of isolation — use these commands.\n\n';
  return t;
}

module.exports = { installExtension, readJsonLoose, init, agentNote, setBrowserMcp, ensureBrowser, newPrompt, promptFinished, stopControl, findBrowser, BROWSER_PORT };

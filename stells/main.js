// STELLS — главный процесс Electron.
// Отвечает за: окно, автозапуск, хранение профиля, проверку SLT-ключа,
// загрузки (прошивка / модели / машинное зрение), обнаружение плат в сети,
// Wake-on-LAN, терминал, запуск коннекторов на любом языке и локального
// сервера машинного зрения.
'use strict';

const { app, BrowserWindow, ipcMain, shell, dialog, session } = require('electron');
const path = require('path');
const fs = require('fs');
const os = require('os');
const crypto = require('crypto');
const dgram = require('dgram');
const { spawn, spawnSync } = require('child_process');
const AdmZip = require('adm-zip');

const APP_DIR = __dirname;
if (process.env.STELLS_USER_DATA) app.setPath('userData', process.env.STELLS_USER_DATA);
const USER_DIR = app.getPath('userData');
const CONFIG_FILE = path.join(USER_DIR, 'stells-config.json');
const WORK_DIR = path.join(USER_DIR, 'workspace');
const MODELS_DIR = path.join(USER_DIR, 'models');
const VISION_DIR = path.join(USER_DIR, 'vision');
const CONNECTORS_DIR = path.join(USER_DIR, 'connectors');
for (const d of [USER_DIR, WORK_DIR, MODELS_DIR, VISION_DIR, CONNECTORS_DIR]) fs.mkdirSync(d, { recursive: true });

// ---------------------------------------------------------------- конфиг
const DEFAULT_CONFIG = {
  registered: false,
  user: { name: '', phone: '' },
  board: null,
  os: null,
  model: null,
  sltKey: '',
  firmwareDownloaded: false,
  visionMode: null,         // 'local' | 'server'
  visionServer: '',         // адрес своего сервера
  visionInstalled: false,
  usage: null,              // 'cars' | 'robots' | 'drones' | 'cameras' | 'wol'
  autostart: true,
  autoVision: true,
  voice: true,
  downloadServer: '',       // базовый URL своего хранилища (необязательно)
  devices: [],              // сохранённые платы {name, host, port}
  wol: [],                  // устройства Wake-on-LAN
};

function readConfig() {
  try { return { ...DEFAULT_CONFIG, ...JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf8')) }; }
  catch { return { ...DEFAULT_CONFIG }; }
}
function writeConfig(patch) {
  const cfg = { ...readConfig(), ...patch };
  fs.writeFileSync(CONFIG_FILE, JSON.stringify(cfg, null, 2));
  return cfg;
}

// ---------------------------------------------------------------- SLT-ключ
// Формат: SLT-XXXX-XXXX-XXXX-XXXX (base32). Первые 12 символов — случайная часть,
// последние 4 — подпись HMAC. Ключи выпускает разработчик: npm run keygen.
// ВАЖНО: перед публикацией задайте свой секрет в файле key-secret.json (строка JSON,
// например "мой-секрет") — его же читает tools/keygen.js. Файл не попадает в git.
function loadKeySecret() {
  try { const v = JSON.parse(fs.readFileSync(path.join(APP_DIR, 'key-secret.json'), 'utf8')); if (v) return String(v); } catch { /* нет файла */ }
  return process.env.STELLS_KEY_SECRET || 'stells-l3xn0-change-me';
}
const KEY_SECRET = loadKeySecret();
const B32 = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
function keySignature(payload) {
  const h = crypto.createHmac('sha256', KEY_SECRET).update(payload).digest();
  let s = '';
  for (let i = 0; i < 4; i++) s += B32[h[i] % 32];
  return s;
}
function validateKey(raw) {
  const k = String(raw || '').toUpperCase().replace(/\s+/g, '');
  const m = k.match(/^SLT-([A-Z2-9]{4})-([A-Z2-9]{4})-([A-Z2-9]{4})-([A-Z2-9]{4})$/);
  if (!m) return { ok: false, reason: 'Неверный формат. Ожидается SLT-XXXX-XXXX-XXXX-XXXX' };
  const payload = m[1] + m[2] + m[3];
  if (keySignature(payload) !== m[4]) return { ok: false, reason: 'Ключ не прошёл проверку. Получите ключ у разработчика.' };
  return { ok: true, key: k };
}

// ---------------------------------------------------------------- окно
let win = null;
function createWindow() {
  win = new BrowserWindow({
    width: 1360, height: 860, minWidth: 1100, minHeight: 700,
    frame: false, backgroundColor: '#05060d', show: false,
    title: 'STELLS',
    icon: path.join(APP_DIR, 'build', 'icon.png'),
    webPreferences: {
      preload: path.join(APP_DIR, 'preload.js'),
      contextIsolation: true, nodeIntegration: false, sandbox: false,
    },
  });
  win.loadFile(path.join(APP_DIR, 'renderer', 'index.html'));
  win.once('ready-to-show', () => win.show());
  win.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: 'deny' }; });
}

function setupPermissions() {
  const ses = session.defaultSession;
  // камера/микрофон для машинного зрения, Web Serial для Arduino, геймпад.
  ses.setPermissionRequestHandler((_wc, perm, cb) => cb(['media', 'serial', 'notifications', 'fullscreen'].includes(perm)));
  ses.setPermissionCheckHandler((_wc, perm) => ['media', 'serial', 'notifications', 'fullscreen'].includes(perm));
  ses.setDevicePermissionHandler((d) => d.deviceType === 'serial');
  ses.on('select-serial-port', (event, ports, _wc, callback) => {
    event.preventDefault();
    const known = ['2341', '2a03', '1a86', '10c4', '0403', '303a', '239a']; // Arduino, CH340, CP210x, FTDI, Espressif, Adafruit
    const pick = ports.find((p) => known.includes((p.vendorId || '').toLowerCase().replace(/^0x/, ''))) || ports[0];
    callback(pick ? pick.portId : '');
  });
}

// ---------------------------------------------------------------- автозапуск
function applyAutostart(enabled) {
  try {
    if (process.platform === 'linux') {
      const dir = path.join(os.homedir(), '.config', 'autostart');
      const file = path.join(dir, 'stells.desktop');
      if (enabled) {
        fs.mkdirSync(dir, { recursive: true });
        const exec = process.env.APPIMAGE || (app.isPackaged ? process.execPath : `${process.execPath} ${APP_DIR}`);
        fs.writeFileSync(file, `[Desktop Entry]\nType=Application\nName=STELLS\nExec=${exec} --autostart\nX-GNOME-Autostart-enabled=true\nComment=STELLS AI\n`);
      } else if (fs.existsSync(file)) fs.unlinkSync(file);
    } else {
      const args = app.isPackaged ? ['--autostart'] : [APP_DIR, '--autostart'];
      app.setLoginItemSettings({ openAtLogin: enabled, path: process.execPath, args });
    }
    return true;
  } catch (e) { return false; }
}

// ---------------------------------------------------------------- загрузки
function downloadsDir() {
  const d = path.join(app.getPath('downloads'), 'STELLS');
  fs.mkdirSync(d, { recursive: true });
  return d;
}

// Скачивание файла по HTTP(S) с прогрессом. Возвращает путь к файлу.
async function httpDownload(url, dest, onProgress) {
  const res = await fetch(url, { redirect: 'follow' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const total = Number(res.headers.get('content-length')) || 0;
  const out = fs.createWriteStream(dest + '.part');
  let got = 0;
  const reader = res.body.getReader();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    got += value.length;
    if (!out.write(Buffer.from(value))) await new Promise((r) => out.once('drain', r));
    onProgress && onProgress(got, total);
  }
  await new Promise((r) => out.end(r));
  fs.renameSync(dest + '.part', dest);
  return dest;
}

function addDirToZip(zip, dir, zipPath) {
  if (!fs.existsSync(dir)) return;
  for (const name of fs.readdirSync(dir)) {
    const full = path.join(dir, name);
    if (fs.statSync(full).isDirectory()) addDirToZip(zip, full, path.posix.join(zipPath, name));
    else zip.addLocalFile(full, zipPath);
  }
}

// Собирает архив «прошивки» под выбранную плату: агент для Linux-плат
// или скетч для микроконтроллеров + конфиг + инструкция.
function buildFirmwarePackage(cfg) {
  const board = cfg.board || {};
  const zip = new AdmZip();
  const fw = path.join(APP_DIR, 'firmware');
  if (board.kind === 'mcu') {
    addDirToZip(zip, path.join(fw, 'arduino'), 'stells-firmware/arduino');
  } else {
    addDirToZip(zip, path.join(fw, 'agent'), 'stells-firmware/agent');
  }
  addDirToZip(zip, path.join(fw, 'connectors'), 'stells-firmware/connectors');
  const config = {
    product: 'STELLS', version: app.getVersion(),
    board: board.name, boardKind: board.kind, os: cfg.os && cfg.os.name,
    model: cfg.model && cfg.model.id, owner: cfg.user.name,
    agent: { port: 8765, streamPort: 8766, discoveryPort: 48765 },
    created: new Date().toISOString(),
  };
  zip.addFile('stells-firmware/stells-config.json', Buffer.from(JSON.stringify(config, null, 2)));
  zip.addLocalFile(path.join(fw, 'README-RU.md'), 'stells-firmware');
  const name = `STELLS-firmware-${(board.name || 'board').replace(/[^\w.+-]+/g, '_')}.zip`;
  const dest = path.join(downloadsDir(), name);
  zip.writeZip(dest);
  return dest;
}

function findPython() {
  const cands = process.platform === 'win32' ? ['py', 'python', 'python3'] : ['python3', 'python'];
  for (const c of cands) {
    try {
      const r = spawnSync(c, ['--version'], { encoding: 'utf8', timeout: 5000 });
      if (r.status === 0) return c;
    } catch { /* нет */ }
  }
  return null;
}

function venvPython() {
  return process.platform === 'win32'
    ? path.join(VISION_DIR, 'venv', 'Scripts', 'python.exe')
    : path.join(VISION_DIR, 'venv', 'bin', 'python');
}

function runStep(cmd, args, log, opts = {}) {
  return new Promise((resolve) => {
    log(`$ ${cmd} ${args.join(' ')}`);
    const p = spawn(cmd, args, { ...opts, shell: false });
    p.stdout.on('data', (d) => log(d.toString()));
    p.stderr.on('data', (d) => log(d.toString()));
    p.on('error', (e) => { log('Ошибка: ' + e.message); resolve(1); });
    p.on('close', (code) => resolve(code));
  });
}

// Установка локального машинного зрения на компьютер:
// копирование модуля + виртуальное окружение Python + opencv/numpy.
let installing = null;
function installVision(send) {
  if (!installing) installing = doInstallVision(send).finally(() => { installing = null; });
  return installing;
}
async function doInstallVision(send) {
  const log = (t) => send('vision:log', t);
  const src = path.join(APP_DIR, 'vision');
  for (const f of fs.readdirSync(src)) fs.copyFileSync(path.join(src, f), path.join(VISION_DIR, f));
  send('vision:progress', 15);
  log('Модуль машинного зрения скопирован в ' + VISION_DIR);
  const py = findPython();
  if (!py) {
    log('Python не найден. Встроенное зрение (в приложении) уже работает.\nДля полного режима установите Python 3.10+ с python.org и нажмите «Переустановить».');
    send('vision:progress', 100);
    return { ok: true, python: false };
  }
  if (!fs.existsSync(venvPython())) {
    const code = await runStep(py, ['-m', 'venv', path.join(VISION_DIR, 'venv')], log);
    if (code !== 0) { log('Не удалось создать venv'); return { ok: true, python: false }; }
  }
  send('vision:progress', 35);
  await runStep(venvPython(), ['-m', 'pip', 'install', '--disable-pip-version-check', '--timeout', '30', '--upgrade', 'pip'], log);
  send('vision:progress', 50);
  const code = await runStep(venvPython(), ['-m', 'pip', 'install', '--disable-pip-version-check', '--timeout', '30', '-r', path.join(VISION_DIR, 'requirements.txt')], log);
  send('vision:progress', 100);
  return { ok: code === 0, python: code === 0 };
}

let visionProc = null;
function startVision(source) {
  if (visionProc) return { ok: true, already: true };
  const script = path.join(VISION_DIR, 'stells_vision.py');
  const py = fs.existsSync(venvPython()) ? venvPython() : null;
  if (!py || !fs.existsSync(script)) return { ok: false, reason: 'Python-модуль не установлен — используется встроенное зрение.' };
  const args = [script, '--port', '8090', '--models', MODELS_DIR];
  if (source) args.push('--source', String(source));
  visionProc = spawn(py, args, { cwd: VISION_DIR });
  const fwd = (d) => win && win.webContents.send('vision:log', d.toString());
  visionProc.stdout.on('data', fwd);
  visionProc.stderr.on('data', fwd);
  visionProc.on('close', (c) => { win && win.webContents.send('vision:stopped', c); visionProc = null; });
  return { ok: true, url: 'http://127.0.0.1:8090' };
}
function stopVision() { if (visionProc) { visionProc.kill(); visionProc = null; } return true; }

// ---------------------------------------------------------------- сеть
// Поиск агентов STELLS в локальной сети (UDP broadcast).
function discoverBoards(timeout = 1800) {
  return new Promise((resolve) => {
    const found = new Map();
    const sock = dgram.createSocket({ type: 'udp4', reuseAddr: true });
    sock.on('message', (msg, rinfo) => {
      try {
        const info = JSON.parse(msg.toString());
        if (info.stells) found.set(rinfo.address, { ...info, host: rinfo.address });
      } catch { /* мусор */ }
    });
    sock.on('error', () => { try { sock.close(); } catch {} resolve([...found.values()]); });
    sock.bind(() => {
      sock.setBroadcast(true);
      const msg = Buffer.from('STELLS_DISCOVER');
      const targets = new Set(['255.255.255.255']);
      for (const list of Object.values(os.networkInterfaces())) {
        for (const a of list || []) {
          if (a.family === 'IPv4' && !a.internal) {
            const ip = a.address.split('.').map(Number), mask = a.netmask.split('.').map(Number);
            targets.add(ip.map((o, i) => (o & mask[i]) | (~mask[i] & 255)).join('.'));
          }
        }
      }
      for (const t of targets) sock.send(msg, 48765, t, () => {});
      setTimeout(() => { try { sock.close(); } catch {} resolve([...found.values()]); }, timeout);
    });
  });
}

function sendWol(mac, broadcast = '255.255.255.255', port = 9) {
  return new Promise((resolve) => {
    const hex = String(mac).replace(/[^0-9a-fA-F]/g, '');
    if (hex.length !== 12) return resolve({ ok: false, reason: 'MAC-адрес должен содержать 12 hex-символов' });
    const macBuf = Buffer.from(hex, 'hex');
    const pkt = Buffer.alloc(6 + 16 * 6, 0xff);
    for (let i = 0; i < 16; i++) macBuf.copy(pkt, 6 + i * 6);
    const sock = dgram.createSocket('udp4');
    sock.bind(() => {
      sock.setBroadcast(true);
      sock.send(pkt, port, broadcast, (err) => {
        sock.close();
        resolve(err ? { ok: false, reason: err.message } : { ok: true });
      });
    });
  });
}

// ---------------------------------------------------------------- терминал
const terms = new Map();
let termSeq = 0;
function termStart(cwd) {
  const id = ++termSeq;
  const isWin = process.platform === 'win32';
  const shellCmd = isWin ? 'powershell.exe' : (process.env.SHELL || '/bin/bash');
  const args = isWin ? ['-NoLogo', '-NoProfile', '-Command', '-'] : ['--noprofile', '--norc'];
  const p = spawn(shellCmd, args, {
    cwd: cwd || WORK_DIR,
    env: { ...process.env, TERM: 'dumb', PS1: 'stells$ ', STELLS_WORKSPACE: WORK_DIR },
  });
  const fwd = (d) => win && win.webContents.send('term:data', { id, data: d.toString() });
  p.stdout.on('data', fwd);
  p.stderr.on('data', fwd);
  p.on('close', (code) => { terms.delete(id); win && win.webContents.send('term:exit', { id, code }); });
  p.on('error', (e) => fwd('Ошибка запуска оболочки: ' + e.message + '\n'));
  terms.set(id, p);
  return { id, shell: shellCmd, cwd: cwd || WORK_DIR };
}

// ---------------------------------------------------------------- коннекторы
// Коннектор — программа на любом языке. Пульт шлёт ей команды JSON
// построчно в stdin, она отвечает телеметрией JSON построчно в stdout.
const LANGS = {
  python: { ext: 'py', run: (f) => [findPython() || 'python3', ['-u', f]] },
  javascript: { ext: 'js', run: (f) => [process.execPath, [f], { ELECTRON_RUN_AS_NODE: '1' }] },
  typescript: { ext: 'ts', run: (f) => ['npx', ['--yes', 'tsx', f]] },
  bash: { ext: 'sh', run: (f) => ['bash', [f]] },
  powershell: { ext: 'ps1', run: (f) => ['powershell', ['-ExecutionPolicy', 'Bypass', '-File', f]] },
  lua: { ext: 'lua', run: (f) => ['lua', [f]] },
  ruby: { ext: 'rb', run: (f) => ['ruby', [f]] },
  php: { ext: 'php', run: (f) => ['php', [f]] },
  perl: { ext: 'pl', run: (f) => ['perl', [f]] },
  go: { ext: 'go', run: (f) => ['go', ['run', f]] },
  java: { ext: 'java', run: (f) => ['java', [f]] },
  kotlin: { ext: 'kts', run: (f) => ['kotlin', [f]] },
  csharp: { ext: 'csx', run: (f) => ['dotnet', ['script', f]] },
  c: { ext: 'c', compile: (f, o) => ['gcc', [f, '-O2', '-o', o, '-lm']] },
  cpp: { ext: 'cpp', compile: (f, o) => ['g++', [f, '-O2', '-std=c++17', '-o', o]] },
  rust: { ext: 'rs', compile: (f, o) => ['rustc', ['-O', f, '-o', o]] },
};

let connector = null;
async function connectorStart(lang, code) {
  connectorStop();
  const L = LANGS[lang];
  if (!L) return { ok: false, reason: 'Неизвестный язык: ' + lang };
  const file = path.join(CONNECTORS_DIR, `connector.${L.ext}`);
  fs.writeFileSync(file, code);
  const send = (t) => win && win.webContents.send('connector:data', t);
  let cmd, args, env = {};
  if (L.compile) {
    const out = path.join(CONNECTORS_DIR, process.platform === 'win32' ? 'connector.exe' : 'connector.bin');
    const [cc, cargs] = L.compile(file, out);
    send(`[STELLS] Компиляция: ${cc} ${cargs.join(' ')}\n`);
    const r = spawnSync(cc, cargs, { encoding: 'utf8' });
    if (r.error || r.status !== 0) return { ok: false, reason: (r.error && r.error.message) || r.stderr || 'Ошибка компиляции' };
    cmd = out; args = [];
  } else {
    [cmd, args, env] = L.run(file);
  }
  const p = spawn(cmd, args, { cwd: CONNECTORS_DIR, env: { ...process.env, ...(env || {}) } });
  connector = p;
  let buf = '';
  p.stdout.on('data', (d) => {
    buf += d.toString();
    let i;
    while ((i = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, i); buf = buf.slice(i + 1);
      let j = null;
      try { j = JSON.parse(line); } catch { /* обычный текст */ }
      if (j) win && win.webContents.send('connector:telemetry', j);
      if (!j || j.type !== 'telemetry') send((j && j.type === 'log' ? j.text : line) + '\n');
    }
  });
  p.stderr.on('data', (d) => send(d.toString()));
  p.on('error', (e) => send(`[STELLS] Не удалось запустить «${cmd}»: ${e.message}. Установите компилятор/интерпретатор языка.\n`));
  p.on('close', (c) => { send(`[STELLS] Коннектор завершён (код ${c})\n`); if (connector === p) connector = null; win && win.webContents.send('connector:closed', c); });
  return { ok: true, file };
}
function connectorSend(obj) {
  if (!connector) return false;
  try { connector.stdin.write(JSON.stringify(obj) + '\n'); return true; } catch { return false; }
}
function connectorStop() { if (connector) { try { connector.kill(); } catch {} connector = null; } return true; }

// ---------------------------------------------------------------- IPC
function registerIpc() {
  const send = (ch, data) => win && !win.isDestroyed() && win.webContents.send(ch, data);

  ipcMain.handle('app:info', () => ({
    version: app.getVersion(), platform: process.platform, arch: process.arch,
    osRelease: os.release(), hostname: os.hostname(), cpus: os.cpus().length,
    totalMem: os.totalmem(), autostartLaunch: process.argv.includes('--autostart'),
    paths: { userData: USER_DIR, models: MODELS_DIR, workspace: WORK_DIR, downloads: downloadsDir() },
  }));
  ipcMain.handle('config:get', () => readConfig());
  ipcMain.handle('config:set', (_e, patch) => {
    const cfg = writeConfig(patch);
    if ('autostart' in patch) applyAutostart(!!patch.autostart);
    return cfg;
  });
  ipcMain.handle('config:reset', () => { fs.writeFileSync(CONFIG_FILE, JSON.stringify(DEFAULT_CONFIG)); applyAutostart(false); return readConfig(); });
  ipcMain.handle('key:validate', (_e, k) => validateKey(k));

  ipcMain.on('win:min', () => win.minimize());
  ipcMain.on('win:max', () => (win.isMaximized() ? win.unmaximize() : win.maximize()));
  ipcMain.on('win:close', () => win.close());
  ipcMain.handle('open:external', (_e, url) => shell.openExternal(url));
  ipcMain.handle('open:path', (_e, p) => shell.openPath(p));
  ipcMain.handle('show:item', (_e, p) => shell.showItemInFolder(p));

  ipcMain.handle('models:manifest', () => JSON.parse(fs.readFileSync(path.join(APP_DIR, 'models.json'), 'utf8')));
  ipcMain.handle('models:installed', () => fs.readdirSync(MODELS_DIR).map((f) => ({ file: f, size: fs.statSync(path.join(MODELS_DIR, f)).size })));
  ipcMain.handle('models:download', async (_e, { url, file }) => {
    const dest = path.join(MODELS_DIR, path.basename(file));
    try {
      await httpDownload(url, dest, (g, t) => send('dl:progress', { id: file, got: g, total: t }));
      return { ok: true, path: dest };
    } catch (e) { return { ok: false, reason: e.message }; }
  });
  ipcMain.handle('models:import', async () => {
    const r = await dialog.showOpenDialog(win, { title: 'Подключить модель', properties: ['openFile', 'multiSelections'],
      filters: [{ name: 'Модели', extensions: ['onnx', 'tflite', 'gguf', 'pt', 'bin', 'safetensors', 'engine', 'rknn', 'hef'] }, { name: 'Все', extensions: ['*'] }] });
    if (r.canceled) return [];
    return r.filePaths.map((f) => { const d = path.join(MODELS_DIR, path.basename(f)); fs.copyFileSync(f, d); return d; });
  });
  ipcMain.handle('models:remove', (_e, file) => { fs.unlinkSync(path.join(MODELS_DIR, path.basename(file))); return true; });

  ipcMain.handle('firmware:download', async () => {
    const cfg = readConfig();
    const base = cfg.downloadServer && cfg.downloadServer.replace(/\/+$/, '');
    // 1) своё хранилище, если указано; 2) иначе сборка пакета прямо в приложении.
    if (base && cfg.board) {
      const name = `STELLS-firmware-${cfg.board.id}.zip`;
      try {
        const dest = await httpDownload(`${base}/firmware/${cfg.board.id}.zip`, path.join(downloadsDir(), name),
          (g, t) => send('dl:progress', { id: 'firmware', got: g, total: t }));
        writeConfig({ firmwareDownloaded: true });
        return { ok: true, path: dest, source: 'server' };
      } catch (e) { send('dl:progress', { id: 'firmware', note: `Хранилище недоступно (${e.message}), собираю локально…` }); }
    }
    try {
      const dest = buildFirmwarePackage(cfg);
      writeConfig({ firmwareDownloaded: true });
      return { ok: true, path: dest, source: 'local' };
    } catch (e) { return { ok: false, reason: e.message }; }
  });
  ipcMain.handle('firmware:saveAs', async (_e, src) => {
    const r = await dialog.showSaveDialog(win, { defaultPath: path.basename(src) });
    if (r.canceled) return null;
    fs.copyFileSync(src, r.filePath);
    return r.filePath;
  });

  ipcMain.handle('vision:install', async () => {
    const r = await installVision(send);
    writeConfig({ visionInstalled: true });
    return r;
  });
  ipcMain.handle('vision:start', (_e, src) => startVision(src));
  ipcMain.handle('vision:stop', () => stopVision());
  ipcMain.handle('vision:status', () => ({ running: !!visionProc, python: fs.existsSync(venvPython()) }));

  ipcMain.handle('net:discover', () => discoverBoards());
  ipcMain.handle('net:wol', (_e, { mac, broadcast, port }) => sendWol(mac, broadcast, port));
  ipcMain.handle('net:interfaces', () => Object.entries(os.networkInterfaces())
    .flatMap(([n, l]) => (l || []).filter((a) => a.family === 'IPv4' && !a.internal).map((a) => ({ name: n, address: a.address, mac: a.mac }))));

  ipcMain.handle('term:start', (_e, cwd) => termStart(cwd));
  ipcMain.on('term:write', (_e, { id, data }) => { const p = terms.get(id); if (p) p.stdin.write(data); });
  ipcMain.on('term:kill', (_e, id) => { const p = terms.get(id); if (p) p.kill(); });

  ipcMain.handle('connector:start', (_e, { lang, code }) => connectorStart(lang, code));
  ipcMain.on('connector:send', (_e, obj) => connectorSend(obj));
  ipcMain.handle('connector:stop', () => connectorStop());
  ipcMain.handle('connector:template', (_e, lang) => {
    const f = path.join(APP_DIR, 'firmware', 'connectors', `connector.${(LANGS[lang] || {}).ext}`);
    return fs.existsSync(f) ? fs.readFileSync(f, 'utf8') : null;
  });
  ipcMain.handle('file:save', async (_e, { name, content }) => {
    const r = await dialog.showSaveDialog(win, { defaultPath: path.join(WORK_DIR, name) });
    if (r.canceled) return null;
    fs.writeFileSync(r.filePath, content);
    return r.filePath;
  });
  ipcMain.handle('file:open', async () => {
    const r = await dialog.showOpenDialog(win, { defaultPath: WORK_DIR, properties: ['openFile'] });
    if (r.canceled) return null;
    return { path: r.filePaths[0], content: fs.readFileSync(r.filePaths[0], 'utf8') };
  });
}

// ---------------------------------------------------------------- старт
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
  app.whenReady().then(() => {
    setupPermissions();
    registerIpc();
    const cfg = readConfig();
    if (cfg.registered) applyAutostart(cfg.autostart);
    createWindow();
  });
  app.on('window-all-closed', () => { stopVision(); connectorStop(); for (const p of terms.values()) p.kill(); app.quit(); });
}

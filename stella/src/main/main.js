'use strict';
const { app, BrowserWindow, ipcMain, shell, clipboard, Notification, desktopCapturer, screen, safeStorage, powerMonitor, dialog, Tray, Menu, nativeImage, globalShortcut } = require('electron');
const path = require('path');
const fs = require('fs');
const fsp = require('fs/promises');
const { Store } = require('./store');
const { Accounts } = require('./accounts');
const { PERSONAS, buildSystemPrompt } = require('./persona');
const llm = require('./llm');
const voice = require('./voice');
const { TOOL_DEFS, LABELS, createExecutor } = require('./computer/tools');
const { classify, needsConfirmation } = require('./computer/safety');
const platform = require('./platform');

const isDev = process.argv.includes('--dev');
const ROOT = path.join(__dirname, '..', '..');

if (process.env.STELLA_DATA_DIR) app.setPath('userData', process.env.STELLA_DATA_DIR);
app.commandLine.appendSwitch('enable-features', 'SharedArrayBuffer');
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');

let mainWin = null, companionWin = null, tray = null;
let store, accounts, executor;
const pendingConfirms = new Map();
let currentAbort = null;
let ignoreMoveUntil = 0;
const game = { follow: false, timer: null, commentTimer: null, agentAbort: null, lastKind: null, vx: 0 };

// ---------- Режим игры: компаньон бегает за курсором поверх игры ----------
function startFollow({ comment = true, commentSec = 60 } = {}) {
  createCompanionWindow();
  game.follow = true;
  companionWin.setIgnoreMouseEvents(true, { forward: true });
  companionWin.setAlwaysOnTop(true, 'screen-saver');
  companionWin.webContents.send('companion:game', { on: true });
  clearInterval(game.timer);
  game.timer = setInterval(() => {
    if (!companionWin || companionWin.isDestroyed()) return stopFollow();
    const c = screen.getCursorScreenPoint();
    const d = screen.getDisplayNearestPoint(c).bounds;
    const b = companionWin.getBounds();
    const center = b.x + b.width / 2;
    const gap = b.width * 0.55; // держимся чуть позади курсора
    const target = c.x > center ? c.x - gap : c.x + gap;
    const diff = target - center;
    const want = Math.abs(diff) < 12 ? 0 : Math.sign(diff) * Math.min(26, Math.abs(diff) * 0.09 + 3);
    game.vx += (want - game.vx) * 0.25;
    let x = Math.round(b.x + game.vx);
    x = Math.max(d.x - b.width * 0.2, Math.min(d.x + d.width - b.width * 0.8, x));
    const y = Math.round(d.y + d.height - b.height);
    ignoreMoveUntil = Date.now() + 200;
    companionWin.setPosition(x, y);
    const speed = Math.abs(game.vx);
    const kind = speed > 11 ? 'run' : speed > 1.2 ? 'walk' : null;
    const dir = Math.sign(game.vx);
    const key = kind + ':' + dir;
    if (key !== game.lastKind) { game.lastKind = key; companionWin.webContents.send('companion:move', { kind, dir }); }
  }, 33);
  clearInterval(game.commentTimer);
  if (comment) game.commentTimer = setInterval(() => gameComment().catch(() => {}), Math.max(20, commentSec) * 1000);
  try { globalShortcut.register('CommandOrControl+Shift+F10', stopAllGame); } catch { /* */ }
}

function stopFollow() {
  game.follow = false;
  clearInterval(game.timer); clearInterval(game.commentTimer);
  game.timer = game.commentTimer = null;
  if (companionWin && !companionWin.isDestroyed()) {
    companionWin.setIgnoreMouseEvents(false);
    companionWin.setAlwaysOnTop(true, 'floating');
    companionWin.webContents.send('companion:game', { on: false });
    companionWin.webContents.send('companion:move', { kind: null, dir: 0 });
  }
}

function stopAllGame() { stopFollow(); game.agentAbort?.abort(); send('game:state', gameState()); }
function gameState() { return { follow: game.follow, agent: !!game.agentAbort }; }

async function gameComment() {
  const c = aiConn();
  if (!c.apiKey) return;
  const shot = await captureScreen(0);
  const r = await llm.streamChat({ apiKey: c.apiKey, baseUrl: c.baseUrl, provider: c.provider, model: c.s.model, maxTokens: 80, temperature: 1,
    messages: [{ role: 'system', content: buildSystemPrompt({ persona: c.s.persona, computerControl: false }) },
      { role: 'user', content: [{ type: 'text', text: 'Ты стоишь рядом и смотришь, как пользователь играет (скриншот экрана). Коротко прокомментируй происходящее (до 12 слов): поддержи, пошути или подскажи. Начни с тега эмоции.' }, { type: 'image_url', image_url: { url: shot.dataUrl } }] }] });
  if (r.content) send('assistant:say', { text: r.content });
}

const GAME_TOOLS = ['take_screenshot', 'press_keys', 'hold_keys', 'type_text', 'mouse_click', 'mouse_move', 'mouse_move_relative', 'mouse_scroll', 'mouse_drag', 'wait', 'focus_window', 'play_animation'];

async function runGameAgent({ goal, windowTitle, maxSteps = 40 }) {
  if (game.agentAbort) throw new Error('Агент уже играет');
  const c = aiConn();
  if (!c.apiKey) throw new Error('Нужен ключ OpenRouter или вход в Stella Cloud');
  game.agentAbort = new AbortController();
  send('game:state', gameState());
  try { globalShortcut.register('CommandOrControl+Shift+F10', stopAllGame); } catch { /* */ }
  const tools = TOOL_DEFS.filter((t) => GAME_TOOLS.includes(t.function.name));
  const sys = buildSystemPrompt({ persona: c.s.persona, computerControl: true }) + `\n\nРЕЖИМ ИГРЫ. Ты играешь в компьютерную игру за пользователя. Цель: ${goal}.
Цикл: take_screenshot → оцени ситуацию → 1–3 действия (hold_keys для движения, press_keys, mouse_click, mouse_move_relative для камеры) → снова скриншот.
Действуй быстро, коротко комментируй (1 фраза). Не открывай другие программы, не трогай файлы. Остановись, когда цель достигнута.`;
  try {
    if (windowTitle) await executor.execute('focus_window', { title: windowTitle });
    const result = await llm.runAgent({
      apiKey: c.apiKey, baseUrl: c.baseUrl, provider: c.provider, model: c.s.model, temperature: 0.4, maxTokens: 400, maxSteps: Math.min(200, Math.max(5, maxSteps)),
      systemPrompt: sys, history: [{ role: 'user', content: `Начинай играть. Цель: ${goal}` }], tools, signal: game.agentAbort.signal,
      executeTool: async ({ name, args }) => {
        const res = await executor.execute(name, args); // действия в игре одобрены запуском режима
        store.logAction({ name, label: LABELS[name] || name, args, ok: res.ok, output: String(res.output || '').slice(0, 500), level: 'game' });
        send('game:log', { name, label: LABELS[name] || name, args, ok: res.ok, output: String(res.output || '').slice(0, 200) });
        return res;
      },
      onToken: () => {},
      onStep: (i) => send('game:log', { step: i + 1 }),
    });
    send('game:log', { done: true, text: result.text });
    if (result.text) send('assistant:say', { text: result.text });
    return result.text;
  } finally {
    game.agentAbort = null;
    send('game:state', gameState());
  }
}

function initStore() {
  const crypto = safeStorage.isEncryptionAvailable()
    ? { encrypt: (s) => safeStorage.encryptString(s).toString('base64'), decrypt: (s) => safeStorage.decryptString(Buffer.from(s, 'base64')) }
    : {};
  store = new Store(app.getPath('userData'), crypto);
  accounts = new Accounts(store);
}

/** Куда отправлять запросы ИИ: свой ключ или сервер Stella Cloud. */
function aiConn() {
  const s = store.getSettings();
  if (s.cloudEnabled && s.cloudToken && s.cloudUrl) return { apiKey: s.cloudToken, baseUrl: s.cloudUrl.replace(/\/$/, '') + '/api', provider: 'cloud', cloud: true, s };
  return { apiKey: s.openrouterKey, baseUrl: undefined, provider: 'openrouter', cloud: false, s };
}

function defaultCloudUrl() {
  try { return JSON.parse(fs.readFileSync(path.join(ROOT, 'assets', 'cloud.json'), 'utf8')).url || ''; } catch { return ''; }
}

async function cloudFetch(url, pathName, { method = 'GET', body, token } = {}) {
  const base = String(url || '').trim().replace(/\/$/, '');
  if (!/^https?:\/\//.test(base)) throw new Error('Адрес сервера должен начинаться с http:// или https://');
  let res;
  try {
    res = await fetch(base + pathName, { method, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) }, body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(15000) });
  } catch (e) { throw new Error(`Сервер ${base} недоступен: ${e.cause?.code || e.message}`); }
  const j = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(j.error?.message || `Ошибка сервера (${res.status})`);
  return j;
}

function send(channel, payload) {
  for (const w of [mainWin, companionWin]) if (w && !w.isDestroyed()) w.webContents.send(channel, payload);
}

function createMainWindow() {
  mainWin = new BrowserWindow({
    width: 1360, height: 860, minWidth: 980, minHeight: 640,
    frame: false, titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'hidden',
    backgroundColor: '#fbfbfa', show: false,
    icon: path.join(ROOT, 'assets', 'icons', 'icon.png'),
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false, sandbox: false, backgroundThrottling: false },
  });
  mainWin.loadFile(path.join(ROOT, 'src', 'renderer', 'index.html'));
  mainWin.once('ready-to-show', () => mainWin.show());
  mainWin.on('maximize', () => send('window:state', { maximized: true }));
  mainWin.on('unmaximize', () => send('window:state', { maximized: false }));
  mainWin.on('focus', () => send('app:focus', { focused: true }));
  mainWin.on('blur', () => send('app:focus', { focused: false }));
  mainWin.webContents.setWindowOpenHandler(({ url }) => { if (/^https?:/.test(url)) shell.openExternal(url); return { action: 'deny' }; });
  mainWin.webContents.on('will-navigate', (e, url) => { if (!url.startsWith('file:')) { e.preventDefault(); if (/^https?:/.test(url)) shell.openExternal(url); } });
  mainWin.on('closed', () => { mainWin = null; if (companionWin && !companionWin.isDestroyed()) companionWin.close(); });
  if (isDev) mainWin.webContents.openDevTools({ mode: 'detach' });
}

function createCompanionWindow() {
  if (companionWin && !companionWin.isDestroyed()) { companionWin.show(); return; }
  const { workArea } = screen.getPrimaryDisplay();
  companionWin = new BrowserWindow({
    width: 340, height: 520, x: workArea.x + workArea.width - 360, y: workArea.y + workArea.height - 540,
    frame: false, transparent: true, alwaysOnTop: true, resizable: true, skipTaskbar: true, hasShadow: false,
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false, sandbox: false },
  });
  companionWin.loadFile(path.join(ROOT, 'src', 'renderer', 'index.html'), { query: { mode: 'companion' } });
  companionWin.setAlwaysOnTop(true, 'floating');
  companionWin.on('moved', () => {
    if (!companionWin || game.follow || Date.now() < ignoreMoveUntil) return;
    const b = companionWin.getBounds();
    const wa = screen.getDisplayMatching(b).workArea;
    const bottom = wa.y + wa.height;
    // окно опустили к панели задач — садимся на неё
    companionWin.webContents.send('companion:perch', { sit: b.y + b.height > bottom - 140, bottom, winY: b.y });
  });
  companionWin.on('closed', () => { companionWin = null; stopFollow(); });
}

function createTray() {
  try {
    const iconPath = path.join(ROOT, 'assets', 'icons', 'icon.png');
    const img = fs.existsSync(iconPath) ? nativeImage.createFromPath(iconPath).resize({ width: 18, height: 18 }) : nativeImage.createEmpty();
    tray = new Tray(img);
    const persona = () => PERSONAS[store.getSettings().persona] || PERSONAS.stella;
    const menu = () => Menu.buildFromTemplate([
      { label: `Открыть ${persona().name}`, click: () => { if (!mainWin) createMainWindow(); mainWin.show(); mainWin.focus(); } },
      { label: 'Режим компаньона', type: 'checkbox', checked: !!companionWin, click: (i) => { if (i.checked) createCompanionWindow(); else companionWin?.close(); } },
      { type: 'separator' },
      { label: 'Выход', click: () => app.quit() },
    ]);
    tray.setToolTip('Stella Assistant');
    tray.setContextMenu(menu());
    tray.on('click', () => { if (!mainWin) createMainWindow(); mainWin.show(); mainWin.focus(); });
  } catch { /* трей необязателен */ }
}

async function captureScreen(index = 0) {
  const displays = screen.getAllDisplays();
  const d = displays[index] || screen.getPrimaryDisplay();
  const phys = { width: Math.round(d.size.width * d.scaleFactor), height: Math.round(d.size.height * d.scaleFactor) };
  const sources = await desktopCapturer.getSources({ types: ['screen'], thumbnailSize: phys });
  const src = sources.find((s) => String(s.display_id) === String(d.id)) || sources[index] || sources[0];
  if (!src) throw new Error('Не удалось получить изображение экрана (проверьте разрешение на запись экрана)');
  let img = src.thumbnail;
  const maxW = 1366;
  if (img.getSize().width > maxW) img = img.resize({ width: maxW, quality: 'good' });
  const { width, height } = img.getSize();
  return { dataUrl: 'data:image/jpeg;base64,' + img.toJPEG(72).toString('base64'), width, height, bounds: d.bounds, scaleFactor: d.scaleFactor };
}

function initExecutor() {
  executor = createExecutor({
    platform: process.platform,
    fs: fsp,
    exec: platform.exec,
    runShell: platform.runShell,
    spawnDetached: platform.spawnDetached,
    shell: { openExternal: (u) => shell.openExternal(u), openPath: (p) => shell.openPath(p), trashItem: (p) => shell.trashItem(p) },
    clipboard,
    notify: (title, body) => new Notification({ title, body, silent: false }).show(),
    screenshot: captureScreen,
    screenInfo: async () => screen.getAllDisplays().map((d) => ({ bounds: d.bounds, scaleFactor: d.scaleFactor, primary: d.id === screen.getPrimaryDisplay().id })),
    cursorPosition: async () => screen.getCursorScreenPoint(),
    killPid: (pid) => process.kill(pid),
    store,
    getSettings: () => store.getSettings(),
    onTimer: (message) => {
      const p = PERSONAS[store.getSettings().persona] || PERSONAS.stella;
      new Notification({ title: `⏰ ${p.name}`, body: message }).show();
      send('assistant:timer', { message });
    },
    onMemory: () => send('memory:changed', store.getMemories()),
    avatar: (cmd) => send('avatar:command', cmd),
  });
}

/** Спрашивает подтверждение у пользователя через интерфейс. */
function askConfirm(info) {
  return new Promise((resolve) => {
    const id = 'q' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    pendingConfirms.set(id, resolve);
    send('tool:confirm', { id, ...info });
    if (mainWin) { if (mainWin.isMinimized()) mainWin.restore(); mainWin.show(); mainWin.focus(); }
  });
}

async function executeToolWithPolicy({ id, name, args }) {
  const s = store.getSettings();
  if (!s.computerControl && !['play_animation', 'remember_fact', 'get_datetime', 'set_timer', 'notify'].includes(name)) {
    return { ok: false, output: 'Управление компьютером выключено пользователем в настройках.' };
  }
  const risk = classify(name, args);
  if (needsConfirmation(risk.level, s.permissionMode, name)) {
    const ok = await askConfirm({ callId: id, name, label: LABELS[name] || name, args, level: risk.level, reason: risk.reason });
    if (!ok) {
      store.logAction({ name, label: LABELS[name] || name, args, ok: false, output: 'Отклонено пользователем', level: risk.level });
      return { ok: false, output: 'Пользователь отклонил это действие. Не повторяй его без новой просьбы.' };
    }
  }
  const res = await executor.execute(name, args);
  store.logAction({ name, label: LABELS[name] || name, args: redactArgs(args), ok: res.ok, output: String(res.output || '').slice(0, 2000), level: risk.level });
  send('actions:changed');
  return res;
}

function redactArgs(args) {
  const a = { ...(args || {}) };
  if (typeof a.content === 'string' && a.content.length > 300) a.content = a.content.slice(0, 300) + '…';
  return a;
}

// ---------- IPC ----------
function handle(channel, fn) {
  ipcMain.handle(channel, async (event, ...args) => {
    try { return { ok: true, data: await fn(event, ...args) }; } catch (e) { return { ok: false, error: e.message || String(e) }; }
  });
}

function registerIpc() {
  // окно
  ipcMain.on('window:minimize', (e) => BrowserWindow.fromWebContents(e.sender)?.minimize());
  ipcMain.on('window:maximize', (e) => { const w = BrowserWindow.fromWebContents(e.sender); if (!w) return; w.isMaximized() ? w.unmaximize() : w.maximize(); });
  ipcMain.on('window:close', (e) => BrowserWindow.fromWebContents(e.sender)?.close());

  handle('app:info', () => ({
    version: app.getVersion(), platform: process.platform, electron: process.versions.electron,
    modelsDir: path.join(ROOT, 'assets', 'models'), userData: app.getPath('userData'),
    personas: Object.fromEntries(Object.entries(PERSONAS).map(([k, p]) => [k, { id: p.id, name: p.name, color: p.color, tagline: p.tagline, greeting: p.greeting, wakeWords: p.wakeWords, gender: p.gender }])),
  }));
  handle('model:path', (_e, persona) => pathToFileUrl(modelFile(persona)));
  handle('model:pick', async (_e, persona) => {
    const r = await dialog.showOpenDialog(mainWin, { title: 'Выберите VRM-модель', filters: [{ name: 'VRM', extensions: ['vrm', 'glb'] }], properties: ['openFile'] });
    if (r.canceled || !r.filePaths[0]) return null;
    store.updateSettings({ [persona === 'mark' ? 'customModelMark' : 'customModelStella']: r.filePaths[0] });
    return r.filePaths[0];
  });

  // настройки
  handle('settings:get', () => store.getPublicSettings());
  handle('settings:set', (_e, patch) => {
    const before = store.getSettings();
    const s = store.updateSettings(patch);
    if ('launchAtStartup' in patch) { try { app.setLoginItemSettings({ openAtLogin: !!patch.launchAtStartup }); } catch { /* */ } }
    if ('companionMode' in patch) { if (patch.companionMode) createCompanionWindow(); else companionWin?.close(); }
    if (before.persona !== s.persona || 'customModelStella' in patch || 'customModelMark' in patch || 'markModel' in patch) { send('persona:changed', s.persona); arServer?.broadcast({ type: 'model', ...arServer && { persona: s.persona } }); }
    send('settings:changed', s);
    return s;
  });
  handle('settings:reset', () => { store.resetAll(); send('settings:changed', store.getPublicSettings()); return true; });

  // аккаунты
  handle('account:current', () => accounts.current());
  handle('account:list', () => accounts.list());
  handle('account:register', (_e, data) => { const a = accounts.register(data); send('persona:changed', a.persona); return a; });
  handle('account:login', (_e, { username, password }) => { const a = accounts.login(username, password); send('persona:changed', a.persona); return a; });
  handle('account:logout', () => { accounts.logout(); return true; });
  handle('account:update', (_e, patch) => { const a = accounts.update(patch); if (patch.persona) send('persona:changed', a.persona); return a; });
  handle('account:delete', () => { const u = store.data.currentAccount; return accounts.remove(u); });
  handle('account:stats', () => ({ ...store.getStats(), memories: store.getMemories().length, conversations: store.listConversations().length }));

  // чаты
  handle('chat:list', () => store.listConversations());
  handle('chat:get', (_e, id) => store.getConversation(id));
  handle('chat:create', () => store.createConversation());
  handle('chat:delete', (_e, id) => { store.deleteConversation(id); return true; });
  handle('chat:rename', (_e, id, title) => store.renameConversation(id, title));
  handle('chat:abort', () => { currentAbort?.abort(); return true; });
  handle('chat:send', async (_e, { conversationId, text, attachments }) => {
    const s = store.getSettings();
    let conv = conversationId ? store.getConversation(conversationId) : null;
    if (!conv) conv = store.createConversation();
    const userMsg = { role: 'user', content: String(text || '') };
    store.appendMessage(conv.id, userMsg);
    const acc = accounts.current();
    const systemPrompt = buildSystemPrompt({ persona: s.persona, userName: acc?.displayName, memories: store.getMemories(), customInstructions: s.customInstructions, computerControl: s.computerControl });
    const history = llm.trimHistory(conv.messages.map(({ role, content, tool_calls, tool_call_id }) => {
      const m = { role, content: content ?? '' };
      if (tool_calls) m.tool_calls = tool_calls;
      if (tool_call_id) m.tool_call_id = tool_call_id;
      return m;
    }), 40);
    if (attachments?.length && history.length) {
      history[history.length - 1] = { role: 'user', content: [{ type: 'text', text: userMsg.content }, ...attachments.map((url) => ({ type: 'image_url', image_url: { url } }))] };
    }
    currentAbort = new AbortController();
    const reqId = 'r' + Date.now().toString(36);
    send('chat:start', { reqId, conversationId: conv.id });
    try {
      const conn = aiConn();
      const result = await llm.runAgent({
        apiKey: conn.apiKey, baseUrl: conn.baseUrl, provider: conn.provider, model: s.model, temperature: s.temperature, maxTokens: s.maxTokens,
        systemPrompt, history, tools: s.computerControl ? TOOL_DEFS.filter((t) => s.agentsEnabled || t.function.name !== 'agent_task') : TOOL_DEFS.filter((t) => ['play_animation', 'remember_fact', 'get_datetime', 'set_timer'].includes(t.function.name)),
        signal: currentAbort.signal,
        executeTool: executeToolWithPolicy,
        onToken: (t) => send('chat:token', { reqId, token: t }),
        onToolStart: (t) => send('chat:tool', { reqId, phase: 'start', label: LABELS[t.name] || t.name, ...t }),
        onToolEnd: (t) => send('chat:tool', { reqId, phase: 'end', label: LABELS[t.name] || t.name, id: t.id, name: t.name, ok: t.ok, output: String(t.output || '').slice(0, 1500), image: t.image }),
        onWarning: (w) => send('chat:warning', { reqId, message: w }),
      });
      for (const m of result.newMessages) store.appendMessage(conv.id, m);
      send('chat:done', { reqId, text: result.text, conversationId: conv.id });
      return { conversationId: conv.id, text: result.text };
    } catch (e) {
      const aborted = e.name === 'AbortError';
      send('chat:error', { reqId, message: aborted ? 'Остановлено' : e.message, aborted });
      if (aborted) return { conversationId: conv.id, text: '', aborted: true };
      throw e;
    } finally { currentAbort = null; }
  });
  handle('llm:models', () => { const c = aiConn(); return llm.listModels(c.cloud ? { baseUrl: c.baseUrl, apiKey: c.apiKey } : {}); });
  handle('llm:test', async () => {
    const c = aiConn();
    const r = await llm.streamChat({ apiKey: c.apiKey, baseUrl: c.baseUrl, provider: c.provider, model: c.s.model, messages: [{ role: 'user', content: 'Ответь одним словом: работает?' }], maxTokens: 20, temperature: 0 });
    return r.content || '(пустой ответ)';
  });
  handle('llm:quick', async (_e, prompt) => {
    // короткая реплика для проактивности/реакций без истории и инструментов
    const c = aiConn(); const s = c.s;
    if (!c.apiKey) return null;
    const acc = accounts.current();
    const content = typeof prompt === 'string' ? prompt : [{ type: 'text', text: prompt.text }, ...(prompt.image ? [{ type: 'image_url', image_url: { url: prompt.image } }] : [])];
    const r = await llm.streamChat({ apiKey: c.apiKey, baseUrl: c.baseUrl, provider: c.provider, model: s.model, maxTokens: 120, temperature: 1,
      messages: [{ role: 'system', content: buildSystemPrompt({ persona: s.persona, userName: acc?.displayName, memories: store.getMemories(), computerControl: false }) }, { role: 'user', content }] });
    return r.content;
  });

  // голос
  handle('tts:speak', async (_e, text) => {
    const s = store.getSettings();
    const c = aiConn();
    const voiceId = s.persona === 'mark' ? s.voiceMark : s.voiceStella;
    if (c.cloud && !s.elevenlabsKey) {
      const b = await voice.cloudSynthesize({ base: s.cloudUrl, token: s.cloudToken, voiceId, text, modelId: s.elevenModel, stability: s.voiceStability, similarity: s.voiceSimilarity, style: s.voiceStyle, speed: s.voiceSpeed });
      return b ? b.toString('base64') : null;
    }
    const buf = await voice.synthesize({ apiKey: s.elevenlabsKey, voiceId: s.persona === 'mark' ? s.voiceMark : s.voiceStella, text, modelId: s.elevenModel, stability: s.voiceStability, similarity: s.voiceSimilarity, style: s.voiceStyle, speed: s.voiceSpeed });
    return buf ? buf.toString('base64') : null;
  });
  handle('tts:voices', () => { const s = store.getSettings(); return aiConn().cloud && !s.elevenlabsKey ? voice.cloudVoices({ base: s.cloudUrl, token: s.cloudToken }) : voice.listVoices({ apiKey: s.elevenlabsKey }); });
  handle('tts:check', () => { const s = store.getSettings(); return voice.checkKey({ apiKey: s.elevenlabsKey, voiceId: s.persona === 'mark' ? s.voiceMark : s.voiceStella, modelId: s.elevenModel }); });
  handle('tts:subscription', () => voice.getSubscription({ apiKey: store.getSettings().elevenlabsKey }));
  handle('stt:transcribe', async (_e, { base64, mime }) => {
    const s = store.getSettings();
    if (aiConn().cloud && !s.elevenlabsKey) return voice.cloudTranscribe({ base: s.cloudUrl, token: s.cloudToken, audio: Buffer.from(base64, 'base64'), mime, language: s.sttLanguage });
    return voice.transcribe({ apiKey: s.elevenlabsKey, audio: Buffer.from(base64, 'base64'), mime, language: s.sttLanguage });
  });

  // компьютер
  handle('tool:respond', (_e, { id, approved }) => { const r = pendingConfirms.get(id); if (r) { pendingConfirms.delete(id); r(!!approved); } return true; });
  handle('tool:run', (_e, { name, args }) => executeToolWithPolicy({ id: 'manual', name, args }));
  handle('tool:defs', () => TOOL_DEFS.map((t) => ({ name: t.function.name, label: LABELS[t.function.name], description: t.function.description, risk: classify(t.function.name, {}).level })));
  handle('actions:list', () => store.getActionLog());
  handle('actions:clear', () => { store.clearActionLog(); return true; });

  // Stella Cloud
  handle('cloud:info', async () => {
    const s = store.getSettings();
    const url = s.cloudUrl || defaultCloudUrl();
    return { url, user: s.cloudUser, enabled: s.cloudEnabled, connected: !!s.cloudToken };
  });
  handle('cloud:health', (_e, url) => cloudFetch(url, '/api/health'));
  handle('cloud:plans', (_e, url) => cloudFetch(url || store.getSettings().cloudUrl, '/api/plans'));
  handle('cloud:auth', async (_e, { url, username, password, email, mode }) => {
    const r = await cloudFetch(url, mode === 'register' ? '/api/auth/register' : '/api/auth/login', { method: 'POST', body: { username, password, email } });
    store.updateSettings({ cloudUrl: url.trim().replace(/\/$/, ''), cloudToken: r.token, cloudUser: r.user.username, cloudEnabled: true });
    send('settings:changed', store.getPublicSettings());
    return r.user;
  });
  handle('cloud:me', async () => { const s = store.getSettings(); if (!s.cloudToken) return null; return cloudFetch(s.cloudUrl, '/api/me', { token: s.cloudToken }); });
  handle('cloud:redeem', async (_e, code) => { const s = store.getSettings(); return cloudFetch(s.cloudUrl, '/api/redeem', { method: 'POST', body: { code }, token: s.cloudToken }); });
  handle('cloud:logout', async () => {
    const s = store.getSettings();
    if (s.cloudToken) cloudFetch(s.cloudUrl, '/api/auth/logout', { method: 'POST', token: s.cloudToken }).catch(() => {});
    store.data.settings.cloudToken = ''; store.updateSettings({ cloudUser: '', cloudEnabled: false });
    send('settings:changed', store.getPublicSettings());
    return true;
  });

  // пользовательские команды
  handle('commands:list', () => store.listCommands());
  handle('commands:save', (_e, cmd) => store.saveCommand(cmd));
  handle('commands:delete', (_e, id) => { store.deleteCommand(id); return true; });
  handle('commands:export', async () => {
    const r = await dialog.showSaveDialog(mainWin, { title: 'Экспорт команд', defaultPath: 'stella-commands.json', filters: [{ name: 'JSON', extensions: ['json'] }] });
    if (r.canceled || !r.filePath) return null;
    await fsp.writeFile(r.filePath, JSON.stringify(store.listCommands(), null, 2));
    return r.filePath;
  });
  handle('commands:import', async () => {
    const r = await dialog.showOpenDialog(mainWin, { title: 'Импорт команд', filters: [{ name: 'JSON', extensions: ['json'] }], properties: ['openFile'] });
    if (r.canceled || !r.filePaths[0]) return null;
    return store.importCommands(JSON.parse(await fsp.readFile(r.filePaths[0], 'utf8')));
  });

  // память
  handle('memory:list', () => store.getMemories());
  handle('memory:add', (_e, text) => store.addMemory(text));
  handle('memory:remove', (_e, id) => { store.removeMemory(id); return store.getMemories(); });

  // система
  handle('system:idle', () => powerMonitor.getSystemIdleTime());
  handle('system:cursor', () => {
    const p = screen.getCursorScreenPoint();
    const w = BrowserWindow.getFocusedWindow() || mainWin;
    const b = w ? w.getContentBounds() : { x: 0, y: 0, width: 1, height: 1 };
    return { x: p.x, y: p.y, win: b };
  });
  handle('system:notify', (_e, { title, body }) => { new Notification({ title, body }).show(); return true; });
  handle('companion:toggle', (_e, on) => { if (on) createCompanionWindow(); else companionWin?.close(); store.updateSettings({ companionMode: !!on }); return !!on; });
  handle('ar:start', async () => {
    const srv = getArServer();
    const r = await srv.start(Number(process.env.STELLA_AR_PORT) || 8790);
    const qr = await require('qrcode').toString(r.url, { type: 'svg', margin: 1, errorCorrectionLevel: 'M' });
    return { url: r.url, ips: r.ips, qr, clients: srv.clients };
  });
  handle('ar:stop', async () => { await arServer?.stop(); return true; });
  handle('ar:status', () => ({ running: !!arServer?.url, url: arServer?.url || '', clients: arServer?.clients || 0 }));
  handle('ar:broadcast', (_e, ev) => arServer?.broadcast(ev) || 0);
  handle('companion:sitAt', (_e, { y }) => {
    if (!companionWin) return false;
    const b = companionWin.getBounds();
    ignoreMoveUntil = Date.now() + 400;
    companionWin.setPosition(b.x, Math.round(y));
    return true;
  });
  handle('game:follow', (_e, opts) => { if (opts?.on) startFollow(opts); else stopFollow(); send('game:state', gameState()); return gameState(); });
  handle('game:agent', (_e, opts) => runGameAgent(opts || {}));
  handle('game:stop', () => { stopAllGame(); return gameState(); });
  handle('game:state', () => gameState());
  handle('companion:focusMain', () => { if (!mainWin) createMainWindow(); mainWin.show(); mainWin.focus(); return true; });
  handle('data:export', async () => {
    const r = await dialog.showSaveDialog(mainWin, { title: 'Экспорт данных', defaultPath: 'stella-export.json' });
    if (r.canceled || !r.filePath) return null;
    const out = { exportedAt: new Date().toISOString(), account: accounts.current(), conversations: store.listConversations().map((c) => store.getConversation(c.id)), memories: store.getMemories() };
    await fsp.writeFile(r.filePath, JSON.stringify(out, null, 2));
    return r.filePath;
  });
}

/** Файл VRM-модели персонажа (своя модель → встроенная → запасная). */
function modelFile(persona) {
  const s = store.getSettings();
  const custom = persona === 'mark' ? s.customModelMark : s.customModelStella;
  if (custom && fs.existsSync(custom)) return custom;
  const dir = path.join(ROOT, 'assets', 'models');
  const has = (f) => fs.existsSync(path.join(dir, f));
  // модели с ограниченной лицензией могут отсутствовать (не входят в публичный репозиторий) — берём доступную
  const order = persona === 'mark'
    ? (s.markModel === 'classic' ? ['mark.vrm', 'nick.vrm'] : ['nick.vrm', 'mark.vrm'])
    : ['stella.vrm', 'mark.vrm'];
  return path.join(dir, order.find(has) || 'mark.vrm');
}

// ---------- AR на телефоне ----------
let arServer = null;
function getArServer() {
  if (arServer) return arServer;
  const { createArServer } = require('./ar-server');
  arServer = createArServer({
    rendererDir: path.join(ROOT, 'src', 'renderer'),
    nodeModules: path.join(ROOT, 'node_modules'),
    certDir: app.getPath('userData'),
    insecure: process.env.STELLA_AR_INSECURE === '1',
    getModelFile: () => modelFile(store.getSettings().persona),
    getInfo: () => { const s = store.getSettings(); const p = PERSONAS[s.persona] || PERSONAS.stella; return { persona: p.id, name: p.name, color: p.color, model: '/model?v=' + encodeURIComponent(modelFile(s.persona) + (fs.existsSync(modelFile(s.persona)) ? fs.statSync(modelFile(s.persona)).mtimeMs : '')) }; },
    onMessage: (text) => { if (mainWin && !mainWin.isDestroyed()) mainWin.webContents.send('ar:message', { text }); },
    onClients: (n) => send('ar:clients', { count: n }),
  });
  return arServer;
}

function pathToFileUrl(p) { return require('url').pathToFileURL(p).href; }

app.whenReady().then(() => {
  initStore();
  initExecutor();
  registerIpc();
  createMainWindow();
  createTray();
  if (store.getSettings().companionMode) createCompanionWindow();
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createMainWindow(); });
});

app.on('will-quit', () => { try { globalShortcut.unregisterAll(); } catch { /* */ } arServer?.stop(); });
app.on('window-all-closed', () => { executor?.cancelTimers(); if (process.platform !== 'darwin') app.quit(); });

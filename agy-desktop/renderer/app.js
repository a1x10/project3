/* Stella — renderer */
const $ = s => document.querySelector(s);
const api = window.agy;

// show any error on screen instead of a blank window
function fatal(msg) {
  document.querySelectorAll('.screen').forEach(x => x.classList.toggle('active', x.id === 'boot'));
  const box = document.getElementById('boot-error');
  box.querySelector('p').textContent = 'Ошибка: ' + msg;
  box.classList.remove('hidden');
}
window.addEventListener('error', e => fatal(e.message + (e.filename ? ' (' + e.filename.split('/').pop() + ':' + e.lineno + ')' : '')));
window.addEventListener('unhandledrejection', e => fatal(String(e.reason && e.reason.stack || e.reason)));
if (!api) setTimeout(() => fatal('preload.js не загрузился — переустановите (install.bat)'), 0);
if (typeof Terminal === 'undefined') setTimeout(() => fatal('Не найдены файлы терминала (node_modules/@xterm). Запустите install.bat'), 0);

const state = {
  settings: null,
  info: null,
  chats: [],
  current: null,      // chat id
  busy: null,         // reqId in progress
  voice: false,
  attachments: [],
  lastChatUsed: null
};

/* ================================================================== */
/* Screens                                                             */
/* ================================================================== */
function show(id) {
  document.querySelectorAll('.screen').forEach(s => s.classList.toggle('active', s.id === id));
}
function step(id, cls, note = '') {
  const el = $('#' + id);
  el.classList.remove('hidden', 'run', 'ok', 'warn', 'fail');
  if (cls) el.classList.add(cls);
  el.querySelector('em').textContent = note;
}
function bootError(msg) {
  const box = $('#boot-error');
  box.querySelector('p').textContent = msg;
  box.classList.remove('hidden');
}

/* ================================================================== */
/* Boot: admin → CLI check → install → terminal                        */
/* ================================================================== */
async function boot() {
  $('#boot-error').classList.add('hidden');
  state.info = await api.info();
  state.settings = await api.getSettings();

  step('st-admin', 'run');
  await sleep(250);
  if (state.info.admin) step('st-admin', 'ok', 'Администратор');
  else step('st-admin', state.info.platform === 'win32' ? 'warn' : 'ok', state.info.platform === 'win32' ? 'нет прав (UAC отклонён)' : 'не требуется');
  $('#admin-chip').classList.toggle('off', !state.info.admin);
  $('#admin-chip').textContent = state.info.admin ? '🛡 Admin' : '⚠ Без прав администратора';

  step('st-cli', 'run');
  let cli = await api.check();
  if (cli.installed) {
    step('st-cli', 'ok', cli.version || 'найден');
  } else {
    step('st-cli', 'warn', 'не найден');
    step('st-install', 'run');
    const log = $('#install-log');
    log.classList.remove('hidden');
    log.textContent = '';
    const off = api.onInstallLog(t => { log.textContent += t; log.scrollTop = log.scrollHeight; });
    const r = await api.install();
    off();
    if (!r.ok) {
      step('st-install', 'fail', 'ошибка');
      bootError('Не удалось установить системные файлы. Проверьте интернет и нажмите «Повторить».');
      return;
    }
    step('st-install', 'ok', 'готово');
    cli = await api.check();
    step('st-cli', 'ok', cli.version || 'установлен');
  }

  step('st-term', 'run');
  initTerminals();
  await sleep(300);
  step('st-term', state.info.pty ? 'ok' : 'warn', state.info.pty ? 'pty' : 'без node-pty');
  setStatus('on', 'Stella готова');
  await sleep(350);
  show('login');
}
$('#boot-retry').onclick = () => boot().catch(e => fatal(e.stack || e));

/* ================================================================== */
/* Terminals (xterm.js) — hidden terminal + login terminal             */
/* ================================================================== */
let xMain = null, fitMain = null, xLogin = null, fitLogin = null;
const termTheme = { background: '#0f0f0f', foreground: '#e6e6e6', cursor: '#d97757', selectionBackground: '#d9775755' };

function initTerminals() {
  if (xMain) return;
  xMain = new Terminal({ fontFamily: 'Cascadia Code, Consolas, monospace', fontSize: 13, theme: termTheme, cursorBlink: true, scrollback: 5000, allowProposedApi: true });
  fitMain = new FitAddon.FitAddon();
  xMain.loadAddon(fitMain);
  xMain.open($('#term'));
  xMain.onData(d => api.termWrite(d));

  let voiceLine = '';
  api.onTermData(d => {
    xMain.write(d);
    if (xLogin) xLogin.write(d);
    if (state.voice) {
      voiceLine += stripAnsi(d);
      const lines = voiceLine.split(/\r?\n/).map(s => s.trim()).filter(s => s && !/^[─━═│┃╭╮╰╯\s]+$/.test(s));
      if (lines.length) $('#voice-transcript').textContent = lines[lines.length - 1].slice(0, 200);
      voiceLine = voiceLine.slice(-2000);
    }
  });
  api.onTermExit(code => {
    xMain.write(`\r\n\x1b[90m[agy завершился, код ${code}]\x1b[0m\r\n`);
    if (state.voice) setVoice(false);
  });
  api.onAuthUrl(url => {
    const a = $('#auth-link');
    a.classList.remove('hidden');
    a.onclick = e => { e.preventDefault(); api.openExternal(url); };
  });
  api.onMaybeLoggedIn(() => { if ($('#login').classList.contains('active')) verifyLogin(true); });
  window.addEventListener('resize', fitAll);
}
function fitAll() {
  try {
    if (!$('#term-drawer').classList.contains('hidden')) { fitMain.fit(); api.termResize(xMain.cols, xMain.rows); }
    if (xLogin && !$('#login-term-wrap').classList.contains('hidden')) { fitLogin.fit(); api.termResize(xLogin.cols, xLogin.rows); }
  } catch {}
}
function toggleDrawer(force) {
  const d = $('#term-drawer');
  const open = force ?? d.classList.contains('hidden');
  d.classList.toggle('hidden', !open);
  if (open) { api.termStart(); setTimeout(() => { fitAll(); xMain.focus(); }, 30); }
}
$('#toggle-term').onclick = () => toggleDrawer();
$('#term-close').onclick = () => toggleDrawer(false);
$('#term-restart').onclick = () => { xMain.clear(); api.termRestart(); };

/* ================================================================== */
/* Login                                                               */
/* ================================================================== */
$('#login-btn').onclick = async () => {
  const st = $('#login-status');
  if (state.settings.loggedIn) {
    st.textContent = 'Вход выполнен ранее — открываю…';
    api.termStart();
    enterApp();
    return;
  }
  st.textContent = 'Запускаю Stella… Откроется окно входа Google.';
  $('#login-term-wrap').classList.remove('hidden');
  if (!xLogin) {
    xLogin = new Terminal({ fontFamily: 'Cascadia Code, Consolas, monospace', fontSize: 12, theme: termTheme, cursorBlink: true });
    fitLogin = new FitAddon.FitAddon();
    xLogin.loadAddon(fitLogin);
    xLogin.open($('#login-term'));
    xLogin.onData(d => api.termWrite(d));
    const buf = await api.termBuffer();
    if (buf) xLogin.write(buf);
  }
  setTimeout(fitAll, 30);
  const r = await api.termStart();
  if (!r.ok) st.textContent = 'Ошибка запуска: ' + r.error;
};
$('#login-check').onclick = () => verifyLogin(false);

let verifying = false;
async function verifyLogin(silent) {
  if (verifying) return;
  verifying = true;
  const st = $('#login-status');
  if (!silent) st.textContent = 'Проверяю вход…';
  const r = await api.verifyLogin();
  verifying = false;
  if (r.ok) {
    state.settings.loggedIn = true;
    st.textContent = 'Готово!';
    enterApp();
  } else if (!silent) {
    st.textContent = 'Пока не получилось войти. ' + (r.error ? r.error.split('\n').slice(-2).join(' ') : 'Завершите вход в браузере.');
  }
}

async function enterApp() {
  show('app');
  if (xLogin) { xLogin.dispose(); xLogin = null; $('#login-term-wrap').classList.add('hidden'); }
  await loadChats();
  renderWorkspace();
  renderMode();
  loadModels();
  $('#input').focus();
}

/* ================================================================== */
/* Chats                                                               */
/* ================================================================== */
const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
const chat = () => state.chats.find(c => c.id === state.current);

async function loadChats() {
  state.chats = await api.loadChats();
  if (!Array.isArray(state.chats)) state.chats = [];
  state.chats.forEach(c => c.messages.forEach(m => { delete m._view; if (m.busy) m.busy = false; }));
  state.lastChatUsed = state.settings.lastChatId || null;
  if (state.chats.length) state.current = state.chats[0].id; else newChat();
  renderChatList(); renderMessages();
}
let saveT = null;
function saveChats() { clearTimeout(saveT); saveT = setTimeout(() => api.saveChats(JSON.parse(JSON.stringify(state.chats.slice(0, 200), (k, v) => k === '_view' ? undefined : v))), 300); }

function newChat() {
  const existing = state.chats.find(c => !c.messages.length);
  if (existing) { state.current = existing.id; }
  else { const c = { id: uid(), title: 'Новый чат', convId: null, messages: [], created: Date.now() }; state.chats.unshift(c); state.current = c.id; }
  renderChatList(); renderMessages(); saveChats();
  $('#input').focus();
}
$('#new-chat').onclick = newChat;

function renderChatList() {
  const ul = $('#chat-list'); ul.innerHTML = '';
  for (const c of state.chats) {
    const li = document.createElement('li');
    li.className = c.id === state.current ? 'active' : '';
    li.innerHTML = `<span></span><button class="icon-btn del" title="Удалить"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg></button>`;
    li.querySelector('span').textContent = c.title;
    li.onclick = () => { if (state.busy) return; state.current = c.id; renderChatList(); renderMessages(); };
    li.querySelector('.del').onclick = e => {
      e.stopPropagation();
      if (state.busy && c.id === state.current) return;
      state.chats = state.chats.filter(x => x.id !== c.id);
      if (state.current === c.id) { state.current = state.chats[0]?.id; if (!state.current) return newChat(); }
      renderChatList(); renderMessages(); saveChats();
    };
    ul.appendChild(li);
  }
  $('#chat-title').textContent = chat()?.title || 'Новый чат';
}

function renderMessages() {
  const box = $('#messages');
  box.querySelectorAll('.msg').forEach(n => n.remove());
  const c = chat();
  $('#empty').classList.toggle('hidden', !!(c && c.messages.length));
  if (!c) return;
  for (const m of c.messages) box.appendChild(msgEl(m));
  scrollDown(true);
}

function msgEl(m) {
  const el = document.createElement('div');
  el.className = 'msg ' + (m.role === 'user' ? 'user' : 'agent') + (m.busy ? ' busy' : '');
  el.dataset.id = m.id;
  if (m.role === 'user') {
    el.innerHTML = '<div class="bubble"></div>';
    el.querySelector('.bubble').textContent = m.text;
  } else {
    el.innerHTML = `<div class="who"><span class="logo-mark">✳</span> Stella</div><div class="extras"></div><div class="body"></div>`;
    fillAgent(el, m);
  }
  return el;
}

function fillAgent(el, m) {
  el.classList.toggle('busy', !!m.busy);
  const ex = el.querySelector('.extras');
  ex.innerHTML = '';
  if (m.thinking) { const t = document.createElement('div'); t.className = 'thinking'; t.textContent = m.thinking.slice(-1500); ex.appendChild(t); }
  for (const t of (m.tools || []).slice(-12)) {
    const d = document.createElement('div'); d.className = 'tool';
    d.innerHTML = '<b></b><span></span>';
    d.querySelector('b').textContent = '⚙ ' + t.name;
    d.querySelector('span').textContent = t.detail || '';
    ex.appendChild(d);
  }
  const body = el.querySelector('.body');
  const typingNow = m._view != null;
  const visible = typingNow ? m.text.slice(0, m._view) : m.text;
  if (visible) body.innerHTML = renderMarkdown(visible);
  else if (m.busy && !typingNow) body.innerHTML = '<span class="typing"><i></i><i></i><i></i></span>';
  else body.innerHTML = '';
  if (typingNow && (m.busy || m._view < m.text.length)) {
    const caret = document.createElement('span'); caret.className = 'caret';
    const last = body.lastElementChild;
    const host = last && /^(P|LI|H\d)$/.test(last.tagName) ? last : (last && last.tagName === 'UL' || last && last.tagName === 'OL') ? last.lastElementChild : (last && last.tagName === 'PRE' ? last.querySelector('code') : body);
    (host || body).appendChild(caret);
  }
  if (m.error) { const e = document.createElement('div'); e.className = 'err'; e.textContent = m.error; body.appendChild(e); }
  if (m.authRequired) {
    const b = document.createElement('button'); b.className = 'btn'; b.textContent = 'Войти в Stella';
    b.onclick = () => { state.settings.loggedIn = false; api.setSettings({ loggedIn: false }); show('login'); };
    body.appendChild(b);
  }
  body.querySelectorAll('pre .copy').forEach(btn => btn.onclick = () => {
    navigator.clipboard.writeText(btn.nextElementSibling.textContent); btn.textContent = 'скопировано'; setTimeout(() => btn.textContent = 'copy', 1200);
  });
}

/* ---------- letter-by-letter typing ---------- */
const typingMsgs = new Set();
let typingRaf = false;
function startTyping(m) {
  if (m._view == null) m._view = 0;
  typingMsgs.add(m);
  if (!typingRaf) { typingRaf = true; requestAnimationFrame(typeTick); }
}
function typeTick() {
  for (const m of typingMsgs) {
    const len = m.text.length;
    if (m._view > len) m._view = len;
    if (m._view < len) {
      const behind = len - m._view;
      // ~2 letters per frame, faster when far behind so the text never lags much
      m._view = Math.min(len, m._view + Math.max(2, Math.ceil(behind / 25)));
      updateMsg(m);
    } else if (!m.busy) {
      delete m._view;
      typingMsgs.delete(m);
      updateMsg(m);
    }
  }
  if (typingMsgs.size) requestAnimationFrame(typeTick); else typingRaf = false;
}

function updateMsg(m) {
  const el = $(`.msg[data-id="${m.id}"]`);
  if (el) fillAgent(el, m);
  scrollDown();
}
function scrollDown(force) {
  const b = $('#messages');
  if (force || b.scrollHeight - b.scrollTop - b.clientHeight < 200) b.scrollTop = b.scrollHeight;
}

/* ================================================================== */
/* Sending                                                             */
/* ================================================================== */
function sendText(raw) {
  let text = (raw ?? $('#input').value).trim();
  if (!text && !state.attachments.length) return;
  if (state.busy) return;

  // slash commands go straight into the hidden agy terminal
  if (text.startsWith('/')) {
    api.termStart().then(r => {
      setTimeout(() => api.termWrite(text + '\r'), r && r.fresh ? 2500 : 50);
    });
    if (/^\/voice\s+live/i.test(text)) setVoice(true, true);
    else toggleDrawer(true);
    $('#input').value = ''; autoGrow(); updateSendBtn();
    return;
  }

  const c = chat();
  if (state.attachments.length) text = state.attachments.map(p => '@' + (p.includes(' ') ? `"${p}"` : p)).join(' ') + '\n' + text;
  state.attachments = []; renderAttachments();

  const user = { id: uid(), role: 'user', text };
  const agent = { id: uid(), role: 'agent', text: '', tools: [], busy: true };
  c.messages.push(user, agent);
  if (c.title === 'Новый чат') c.title = text.replace(/^@\S+\s*/gm, '').split('\n')[0].slice(0, 48) || 'Чат';
  $('#input').value = ''; autoGrow();
  renderChatList(); renderMessages();

  const reqId = uid();
  state.busy = { reqId, chatId: c.id, msg: agent, gotDelta: false };
  setStatus('busy', 'агент работает…');
  updateSendBtn();
  api.send({
    reqId, prompt: text,
    conversationId: c.convId || null,
    continueLast: !c.convId && c.messages.length > 2 && state.lastChatUsed === c.id
  });
  state.lastChatUsed = c.id;
  api.setSettings({ lastChatId: c.id });
  saveChats();
}

api.onEvent(ev => {
  const b = state.busy;
  if (!b || ev.reqId !== b.reqId) return;
  const m = b.msg;
  const c = state.chats.find(x => x.id === b.chatId);
  switch (ev.type) {
    case 'delta': b.gotDelta = true; m.text += ev.text; startTyping(m); break;
    case 'raw': if (!b.gotDelta) { m.text += ev.text; startTyping(m); } break;
    case 'final': if (!m.text || !b.gotDelta || ev.text.length >= m.text.length) { if (!ev.text.startsWith(m.text.slice(0, m._view || 0))) m._view = 0; m.text = ev.text; startTyping(m); } break;
    case 'thinking': m.thinking = (m.thinking || '') + ev.text; break;
    case 'tool': m.tools.push({ name: ev.name, detail: ev.detail }); break;
    case 'error': m.error = (m.error ? m.error + '\n' : '') + ev.text; break;
    case 'conversation': if (c) c.convId = ev.id; break;
    case 'auth-required': m.authRequired = true; break;
  }
  updateMsg(m);
});

api.onDone(({ reqId, code }) => {
  const b = state.busy;
  if (!b || b.reqId !== reqId) return;
  b.msg.busy = false;
  if (!b.msg.text && !b.msg.error && code !== 0) b.msg.error = 'Stella не смогла ответить (код ' + code + '). Откройте «Терминал» для подробностей.';
  updateMsg(b.msg);
  state.busy = null;
  setStatus('on', 'готов');
  updateSendBtn();
  saveChats();
  $('#input').focus();
});

/* ================================================================== */
/* Composer                                                            */
/* ================================================================== */
const input = $('#input');
function autoGrow() { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 240) + 'px'; }
input.addEventListener('input', () => { autoGrow(); updateSendBtn(); });
input.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendText(); }
});

function updateSendBtn() {
  const btn = $('#voice-btn');
  btn.classList.remove('send', 'stop');
  if (state.busy) { btn.classList.add('stop'); btn.title = 'Остановить'; }
  else if (input.value.trim() || state.attachments.length) { btn.classList.add('send'); btn.title = 'Отправить'; }
  else btn.title = state.voice ? 'Выключить голосовой режим' : 'Голосовой режим — /voice live';
}

// The black button: send / stop / voice live
$('#voice-btn').onclick = () => {
  if (state.busy) { api.stop(state.busy.reqId); return; }
  if (input.value.trim() || state.attachments.length) return sendText();
  setVoice(!state.voice);
};
$('#voice-end').onclick = () => setVoice(false);

async function setVoice(on, alreadySent) {
  if (on) {
    if (!alreadySent) {
      const r = await api.voiceStart();
      if (!r.ok) { alert('Не удалось запустить голосовой режим: ' + (r.error || '')); return; }
    }
    state.voice = true;
    $('#voice-transcript').textContent = 'Слушаю… говорите';
    $('#voice-panel').classList.remove('hidden');
    $('#voice-btn').classList.add('live');
    setStatus('busy', 'голосовой режим');
  } else {
    if (state.voice) await api.voiceStop();
    state.voice = false;
    $('#voice-panel').classList.add('hidden');
    $('#voice-btn').classList.remove('live');
    setStatus('on', 'готов');
  }
  updateSendBtn();
}

// mic = dictation through agy's /voice command
$('#mic').onclick = async () => {
  const r = await api.termStart();
  setTimeout(() => api.termWrite('/voice\r'), r && r.fresh ? 2500 : 50);
  toggleDrawer(true);
};

// attachments (+)
$('#attach').onclick = async () => {
  const files = await api.pickFiles();
  if (files.length) { state.attachments.push(...files); renderAttachments(); updateSendBtn(); }
};
function renderAttachments() {
  const box = $('#attachments'); box.innerHTML = '';
  state.attachments.forEach((p, i) => {
    const s = document.createElement('span'); s.className = 'att';
    s.innerHTML = '<span></span><button>✕</button>';
    s.firstChild.textContent = '@' + p.split(/[\\/]/).pop();
    s.lastChild.onclick = () => { state.attachments.splice(i, 1); renderAttachments(); updateSendBtn(); };
    box.appendChild(s);
  });
}

document.querySelectorAll('.sugg').forEach(b => b.onclick = () => {
  if (b.textContent.endsWith('…')) { input.value = b.textContent.replace('…', ' '); input.focus(); autoGrow(); updateSendBtn(); }
  else sendText(b.textContent);
});

/* ---------- dropdowns ---------- */
function bindDropdown(dd, btn) {
  $(btn).onclick = e => { e.stopPropagation(); document.querySelectorAll('.dropdown.open').forEach(d => d !== $(dd) && d.classList.remove('open')); $(dd).classList.toggle('open'); };
}
bindDropdown('#model-dd', '#model-btn');
bindDropdown('#mode-dd', '#mode-btn');
document.addEventListener('click', () => document.querySelectorAll('.dropdown.open').forEach(d => d.classList.remove('open')));

async function loadModels() {
  const models = await api.models();
  const menu = $('#model-menu'); menu.innerHTML = '';
  const list = [''].concat(models);
  if (state.settings.model && !list.includes(state.settings.model)) list.push(state.settings.model);
  for (const m of list) {
    const b = document.createElement('button');
    b.textContent = m || 'Default model';
    b.classList.toggle('sel', m === state.settings.model);
    b.onclick = async () => { state.settings = await api.setSettings({ model: m }); $('#model-label').textContent = m || 'Default model'; loadModels(); };
    menu.appendChild(b);
  }
  $('#model-label').textContent = state.settings.model || 'Default model';
}

function renderMode() {
  document.querySelectorAll('#mode-menu button').forEach(b => {
    b.classList.toggle('sel', b.dataset.mode === state.settings.mode);
    b.onclick = async () => {
      if (b.dataset.mode === 'yolo' && !confirm('Полный автомат: агент будет выполнять команды и менять файлы БЕЗ подтверждения (с правами администратора). Включить?')) return;
      state.settings = await api.setSettings({ mode: b.dataset.mode });
      renderMode();
    };
  });
  $('#mode-btn').classList.toggle('danger', state.settings.mode === 'yolo');
  $('#mode-btn').classList.toggle('active', state.settings.mode === 'accept-edits' || state.settings.mode === 'plan');
}

/* ---------- workspace ---------- */
function renderWorkspace() {
  const ws = state.settings.workspace || '';
  $('#workspace-name').textContent = ws.split(/[\\/]/).filter(Boolean).pop() || ws;
  $('#workspace').title = 'Рабочая папка агента: ' + ws;
}
$('#workspace').onclick = async () => {
  const p = await api.pickFolder();
  if (p) { state.settings = await api.setSettings({ workspace: p }); renderWorkspace(); }
};

/* ---------- misc ---------- */
function setStatus(kind, text) {
  $('#status-dot').className = 'dot ' + (kind || '');
  $('#status-text').textContent = text;
}
function stripAnsi(s) {
  return s.replace(/\x1b\[[0-9;?]*[ -\/]*[@-~]/g, '').replace(/\x1b\][^\x07]*(\x07|\x1b\\)/g, '').replace(/\x1b[@-_]/g, '');
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

document.addEventListener('keydown', e => {
  if (!$('#app').classList.contains('active')) return;
  if (e.ctrlKey && e.key.toLowerCase() === 'n') { e.preventDefault(); newChat(); }
  if (e.ctrlKey && e.key === '`') { e.preventDefault(); toggleDrawer(); }
  if (e.key === 'Escape' && state.voice) setVoice(false);
});

if (api) boot().catch(e => fatal(e.stack || e));

/* Stella phone app (PWA) */
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const S = {
  token: localStorage.getItem('stella.token') || '',
  user: null, ws: null, tab: 'server', retry: 0,
  lists: { server: [], pc: [] },
  open: null,                // { where, chat }
  pcOnline: false, wa: { status: 'off', chats: [], autoLog: [] },
  agy: true, settings: { mode: 'yolo' }
};

function show(id) { document.querySelectorAll('.screen').forEach(x => x.classList.toggle('active', x.id === id)); if (id === 'auth' && typeof renderCaptcha === 'function') setTimeout(() => renderCaptcha(), 0); }
function toast(t, ms = 3500) { const el = $('#toast'); el.textContent = t; el.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => el.hidden = true, ms); }
const initial = t => { const m = String(t || '').match(/\p{L}|\p{N}/u); return m ? m[0].toUpperCase() : '•'; };
const plainText = t => String(t || '').replace(/[*_`#>]+/g, '').replace(/\s+/g, ' ').trim();
const ago = ts => { if (!ts) return ''; const d = (Date.now() - ts) / 1000; if (d < 60) return 'сейчас'; if (d < 3600) return Math.floor(d / 60) + ' мин'; if (d < 86400) return Math.floor(d / 3600) + ' ч'; return new Date(ts).toLocaleDateString(); };

/* ================================================================== */
/* auth                                                                */
/* ================================================================== */
let authMode = 'login';
document.querySelectorAll('#auth-seg button').forEach(b => b.onclick = () => {
  authMode = b.dataset.mode;
  document.querySelectorAll('#auth-seg button').forEach(x => x.classList.toggle('on', x === b));
  $('#auth-btn').textContent = authMode === 'login' ? 'Войти' : 'Создать аккаунт';
  $('#auth-pass').autocomplete = authMode === 'login' ? 'current-password' : 'new-password';
  $('#auth-pass').placeholder = authMode === 'login' ? 'Пароль' : 'Пароль (мин. 10 символов, не только цифры)';
  $('#auth-note').textContent = authMode === 'register' ? 'Для аккаунта на сервере создаётся отдельное рабочее место со своим агентом.' : '';
  $('#auth-invite').hidden = !(authMode === 'register' && S.signup === 'invite');
});
$('#auth-form').onsubmit = async e => {
  e.preventDefault();
  $('#auth-err').textContent = '';
  $('#auth-btn').disabled = true;
  try {
    const r = await fetch('/api/' + authMode, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ username: $('#auth-user').value, password: $('#auth-pass').value, invite: $('#auth-invite').value, totp: $('#auth-totp').value, captcha: captchaToken() }) });
    const j = await r.json();
    if (j.need2fa) { $('#auth-totp').hidden = false; $('#auth-totp').focus(); }
    if (!r.ok || j.error) { resetCaptcha(); throw new Error(j.error || 'Ошибка'); }
    S.token = j.token; localStorage.setItem('stella.token', j.token);
    start();
  } catch (err) { $('#auth-err').textContent = err.message; }
  $('#auth-btn').disabled = false;
};

/* ================================================================== */
/* websocket                                                           */
/* ================================================================== */
function connect() {
  const ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws');
  S.ws = ws;
  ws.onopen = () => { S.retry = 0; ws.send(JSON.stringify({ t: 'auth', token: S.token, device: 'phone', label: navigator.userAgent.slice(0, 60) })); };
  ws.onmessage = e => { try { onMsg(JSON.parse(e.data)); } catch (err) { console.error(err); } };
  ws.onclose = () => { if (S.ws !== ws) return; setTimeout(connect, Math.min(10000, 800 * 2 ** S.retry++)); };
}
const send = m => { if (S.ws && S.ws.readyState === 1) S.ws.send(JSON.stringify(m)); else toast('Нет связи с сервером…'); };

function onMsg(m) {
  switch (m.t) {
    case 'auth.error': localStorage.removeItem('stella.token'); S.token = ''; show('auth'); break;
    case 'hello':
      S.user = m.user; S.agy = m.agy; S.pcOnline = m.pcOnline; S.settings = m.settings || S.settings;
      S.lists.server = m.serverChats; S.lists.pc = m.pcChats; S.wa = m.wa;
      $('#acc-name').textContent = 'Аккаунт: ' + m.user.name + (m.user.admin ? ' (администратор)' : '');
      $('#admin-card').hidden = !m.user.admin;
      send({ t: 'security.get' });
      S.profile = m.profile || {}; S.services = m.services || {};
      renderAbout(); renderServices();
      if (!S.profile.name && !localStorage.getItem('stella.onboard.skip')) openOnboarding();
      if (m.user.admin) send({ t: 'admin.list' });
      $('#shared-key-note').hidden = !m.sharedKey; $('#google-note').hidden = !!m.sharedKey;
      $('#mode-select').value = S.settings.mode || 'yolo';
      renderAll();
      if (S.open) send({ t: S.open.where + '.chat.get', chatId: S.open.chat.id });
      break;
    case 'chats': S.lists[m.where] = m.list; renderList(m.where); break;
    case 'chat': {
      upsertSummary(m.where, m.chat);
      if (S.open && S.open.where === m.where && (S.open.chat.id === m.chat.id || S.open.pendingNew)) { S.open = { where: m.where, chat: m.chat }; renderChat(); }
      break;
    }
    case 'chat.deleted': S.lists[m.where] = S.lists[m.where].filter(c => c.id !== m.chatId); renderList(m.where); break;
    case 'ev': onEv(m); break;
    case 'pc.online': S.pcOnline = m.online; renderPcState(); renderServices(); if (m.online) toast('Компьютер в сети'); break;
    case 'settings': S.settings = m.settings; break;
    case 'notify': notify(m.title, m.body); break;
    case 'term.data': if (xterm) xterm.write(m.data); break;
    case 'wa.status': Object.assign(S.wa, { status: m.status, qr: m.qr, me: m.me, error: m.error }); renderWa(); if (m.status === 'connected') send({ t: 'wa.overview' }); break;
    case 'wa.overview': S.wa = m; renderWa(); break;
    case 'wa.chats': S.wa.chats = m.list; renderWaList(); break;
    case 'wa.autoChanged': { const c = S.wa.chats.find(x => x.jid === m.jid); if (c) c.auto = m.on; renderWaList(); break; }
    case 'wa.auto': S.wa.autoLog = [m.entry].concat(S.wa.autoLog || []).slice(0, 40); renderWaLog(); break;
    case 'wa.reply': toast(`📩 ${m.name}: ${m.text.slice(0, 80)}`, 6000); break;
    case 'wa.sent': if (!m.auto) toast(`Отправлено ${m.name}: ${m.text.slice(0, 60)}`); break;
    case 'admin.state': renderAdmin(m); break;
    case 'security': renderSecurity(m); break;
    case 'grading.list': G.list = m.list || []; if (!$('#grading').hidden && !G.cur) renderGradingList(); break;
    case 'grading': {
      const i = G.list.findIndex(x => x.id === m.batch.id); const sum = Object.assign({}, m.batch); delete sum.works;
      if (i >= 0) G.list[i] = sum; else G.list.unshift(sum);
      if (!$('#grading').hidden && (!G.cur || G.cur.id === m.batch.id) && !document.getElementById('gw-save')) renderBatch(m.batch);
      else if (!$('#grading').hidden && !G.cur) renderGradingList();
      break;
    }
    case 'profile': S.profile = m.profile || {}; renderAbout(); renderHome(); break;
    case 'team': {
      if (S.open && S.open.where === 'server' && S.open.chat.id === m.chatId) {
        const msg = S.open.chat.messages.find(x => x.id === m.msgId);
        if (msg) { msg.team = m.team; msg.busy = !['done', 'failed', 'stopped'].includes(m.team.status); updateMsg(msg); updateComposer(); }
      }
      break;
    }
    case 'services': S.services = m.list || {}; renderServices(); break;
    case 'security.2fa.qr': $('#sec-2fa-setup').hidden = false; $('#sec-qr').src = m.qr; $('#sec-secret').textContent = m.secret; $('#sec-code').focus(); break;
    case 'error': toast(m.text, 5000); if (S.open) { S.open.pendingNew = false; } break;
  }
}

function upsertSummary(where, chat) {
  const l = S.lists[where];
  const sum = { id: chat.id, title: chat.title, busy: !!chat.busy || chat.messages?.some(x => x.busy), updated: chat.updated || Date.now(), last: (chat.messages?.[chat.messages.length - 1]?.text || '').slice(0, 120), origin: chat.origin };
  const i = l.findIndex(c => c.id === chat.id);
  if (i >= 0) l[i] = sum; else l.unshift(sum);
  l.sort((a, b) => (b.updated || 0) - (a.updated || 0));
  renderList(where);
}

function onEv(m) {
  const sum = S.lists[m.where].find(c => c.id === m.chatId);
  if (sum) { sum.busy = m.type !== 'done'; sum.updated = Date.now(); if (m.type === 'done') renderList(m.where); }
  if (!S.open || S.open.where !== m.where || S.open.chat.id !== m.chatId) { if (!sum && m.type === 'start') send({ t: m.where + '.chat.get', chatId: m.chatId }); return; }
  const c = S.open.chat;
  if (m.type === 'start' && m.messages) { c.messages.push(...m.messages); c.busy = true; renderChat(); return; }
  const msg = c.messages.find(x => x.id === m.msgId) || (m.where === 'pc' ? c.messages.filter(x => x.role === 'agent').pop() : null);
  if (!msg) { send({ t: m.where + '.chat.get', chatId: c.id }); return; }
  switch (m.type) {
    case 'delta': msg.text = (msg.text || '') + m.text; msg.status = 'Пишет ответ…'; break;
    case 'final': msg.text = m.text; break;
    case 'activity': msg.status = m.text; break;
    case 'log': msg.log = ((msg.log || '') + m.text).slice(-20000); break;
    case 'tool': (msg.tools = msg.tools || []).push({ name: m.name, detail: m.detail, error: m.error }); break;
    case 'error': msg.error = (msg.error ? msg.error + '\n' : '') + m.text; break;
    case 'done': msg.busy = false; msg.duration = m.duration ?? Math.round((Date.now() - (msg.started || Date.now())) / 1000); c.busy = false; break;
  }
  updateMsg(msg);
  updateComposer();
}

/* ================================================================== */
/* lists                                                               */
/* ================================================================== */
function renderAll() {
  show('app'); renderList('server'); renderList('pc'); renderPcState(); renderWa(); renderHome();
  $('#agy-missing').hidden = S.agy;
}
function renderList(where) {
  const ul = $('#' + where + '-list'); ul.innerHTML = '';
  for (const c of S.lists[where]) {
    const li = document.createElement('li');
    li.innerHTML = `<div class="ico ${c.busy ? 'busy' : ''}">${c.busy ? '' : esc(initial(c.title))}</div><div class="txt"><div class="t1">${esc(c.title)}${c.origin === 'pc' && where === 'server' ? ' <span class="small muted">с ПК</span>' : ''}</div><div class="t2">${c.busy ? 'Агент работает…' : esc(plainText(c.last))}</div></div><div class="when">${ago(c.updated)}</div>`;
    li.onclick = () => openChat(where, c.id);
    ul.appendChild(li);
  }
  if (where === 'server') { $('#server-empty').hidden = S.lists.server.length > 0; renderHome(); }
  const busy = S.lists.server.filter(c => c.busy).length;
  $('#b-server').textContent = busy ? busy : '';
}
function renderPcState() {
  $('#pc-pill').textContent = S.pcOnline ? 'в сети' : 'не в сети';
  $('#pc-pill').classList.toggle('on', S.pcOnline);
  $('#b-pc').classList.toggle('on', S.pcOnline);
  $('#pc-offline').hidden = S.pcOnline;
  $('#new-pc-chat').hidden = !S.pcOnline;
}

/* ================================================================== */
/* chat view                                                           */
/* ================================================================== */
function openChat(where, id) {
  const sum = S.lists[where].find(c => c.id === id);
  S.open = { where, chat: { id, title: sum ? sum.title : 'Чат', messages: [] } };
  $('#chat').hidden = false;
  renderChat();
  send({ t: where + '.chat.get', chatId: id });
}
function openNew(where) {
  if (where === 'pc' && !S.pcOnline) return toast('Компьютер не в сети');
  S.open = { where, chat: { id: null, title: 'Новая задача', messages: [] }, pendingNew: true };
  $('#chat').hidden = false;
  renderChat();
  $('#input').focus();
}
$('#new-server-chat').onclick = () => openNew('server');
$('#new-pc-chat').onclick = () => openNew('pc');
$('#chat-back').onclick = () => { $('#chat').hidden = true; S.open = null; };

function renderChat() {
  const { where, chat } = S.open;
  $('#chat-title').textContent = chat.title;
  $('#chat-where').textContent = where === 'server' ? 'На сервере' : (S.pcOnline ? 'На компьютере' : 'На компьютере · не в сети');
  $('#chat-transfer').textContent = where === 'server' ? '→ Компьютер' : '→ Сервер';
  $('#chat-transfer').hidden = !chat.id;
  renderTeamBtn();
  const box = $('#messages'); box.innerHTML = '';
  for (const m of chat.messages) box.appendChild(msgEl(m));
  box.scrollTop = box.scrollHeight;
  updateComposer();
}
function msgEl(m) {
  const el = document.createElement('div');
  el.className = 'msg ' + (m.role === 'user' ? 'user' : 'agent') + (m.note ? ' note' : '');
  el.dataset.id = m.id;
  fillMsg(el, m);
  return el;
}
function fillMsg(el, m) {
  if (m.role === 'user') { el.innerHTML = '<div class="bubble"></div>'; el.firstChild.textContent = m.text; return; }
  const steps = (m.tools || []).slice(-6).map(t => `<div class="step ${t.error ? 'failed' : ''}"><i>${t.error ? '✗' : '✓'}</i><span>${esc(t.detail || t.name)}</span></div>`).join('');
  const secs = m.busy ? Math.floor((Date.now() - (m.started || Date.now())) / 1000) : (m.duration ?? null);
  const act = !m.team && (m.busy || m.duration != null) ? `<div class="activity" data-act>${m.busy ? '<span class="sp"></span>' : '<span class="done"></span>'}<span class="tx">${esc(m.busy ? (m.status || 'Думает…') : (m.error ? 'Ошибка' : 'Выполнено'))}</span><span class="tm">${secs != null ? secs + 's' : ''}</span><span>›</span></div>${m._open ? `<pre class="act-log">${esc((m.log || '').trim() || 'Пока пусто')}</pre>` : ''}` : '';
  const teamCard = m.team ? renderTeam(m.team) : '';
  el.innerHTML = `<div class="who"><b>✳</b> Stella${m.team ? ' · команда' : ''}</div>${teamCard}${steps}<div class="body">${m.text ? renderMarkdown(m.text) : ''}${m.error ? `<div class="err">${esc(m.error)}</div>` : ''}</div>${act}`;
  el.querySelectorAll('[data-open-chat]').forEach(r => r.onclick = () => { const [w, id] = r.dataset.openChat.split(':'); if (id) openChat(w, id); });
  const stopT = el.querySelector('[data-team-stop]'); if (stopT) stopT.onclick = () => { if (confirm('Остановить всех агентов команды?')) send({ t: 'team.stop', teamId: stopT.dataset.teamStop }); };
  const a = el.querySelector('[data-act]');
  if (a) a.onclick = () => { m._open = !m._open; fillMsg(el, m); };
}
function renderTeam(t) {
  const icon = st => st === 'running' ? '<span class="st run"></span>' : `<span class="st">${{ waiting: '⏳', done: '✅', failed: '⚠️', stopped: '⏹' }[st] || '•'}</span>`;
  const secs = a => a.started ? Math.round(((a.finished || Date.now()) - a.started) / 1000) + 's' : '';
  const head = { planning: 'Составляю план…', running: 'Агенты работают', summarizing: 'Собираю отчёт…', done: 'Готово', failed: 'Не получилось', stopped: 'Остановлено' }[t.status] || t.status;
  const rows = (t.agents || []).map(a => `<div class="team-row" data-open-chat="${a.where === 'pc' ? 'pc' : 'server'}:${esc(a.chatId || '')}">${icon(a.status)}<div class="tt"><b>${esc(a.title)}</b><span>${esc(a.summary || (a.status === 'waiting' ? 'ждёт результатов других агентов' : a.status === 'running' ? 'работает…' : ''))}</span></div><span class="wh">${a.where === 'pc' ? 'ПК' : 'сервер'}</span><span class="tm">${secs(a)}</span></div>`).join('');
  const running = ['planning', 'running', 'summarizing'].includes(t.status);
  return `<div class="team-card"><h4>👥 ${esc(t.title || 'Команда агентов')}<span class="spacer"></span><span class="small muted">${head}</span></h4>${rows || '<div class="small muted">Планировщик раскладывает задачу на части…</div>'}${running && t.status !== 'planning' ? `<button class="btn tiny" data-team-stop="${esc(t.id)}">Остановить</button>` : ''}</div>`;
}

function updateMsg(m) {
  const el = document.querySelector(`.msg[data-id="${CSS.escape(m.id)}"]`);
  if (!el) return renderChat();
  const box = $('#messages'); const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 120;
  fillMsg(el, m);
  if (atBottom) box.scrollTop = box.scrollHeight;
}
setInterval(() => { if (!S.open) return; S.open.chat.messages.filter(m => m.busy).forEach(updateMsg); }, 1000);

function busyNow() { return !!(S.open && S.open.chat.messages.some(m => m.busy)); }
function updateComposer() { $('#send-btn').classList.toggle('stop', busyNow()); }

const input = $('#input');
input.addEventListener('input', () => { input.style.height = 'auto'; input.style.height = Math.min(160, input.scrollHeight) + 'px'; });
$('#composer').onsubmit = e => {
  e.preventDefault();
  if (!S.open) return;
  const { where, chat } = S.open;
  if (busyNow()) { send({ t: where + '.stop', chatId: chat.id }); return; }
  const text = input.value.trim(); if (!text) return;
  input.value = ''; input.style.height = 'auto';
  if (!chat.id) S.open.pendingNew = true;
  if (where === 'server' && S.teamMode && !chat.id) { send({ t: 'team.start', text }); S.teamMode = false; renderTeamBtn(); }
  else if (where === 'server') send({ t: 'server.send', chatId: chat.id, text });
  else { send({ t: 'pc.send', chatId: chat.id, text }); toast('Отправлено на компьютер'); }
};
input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && window.matchMedia('(pointer:fine)').matches) { e.preventDefault(); $('#composer').requestSubmit(); } });

/* ---------- team mode ---------- */
function renderTeamBtn() {
  const can = S.open && S.open.where === 'server' && !S.open.chat.id;
  $('#team-btn').hidden = !can;
  $('#team-btn').classList.toggle('on', !!S.teamMode && can);
  $('#team-hint').hidden = !(S.teamMode && can);
}
$('#team-btn').onclick = () => { S.teamMode = !S.teamMode; renderTeamBtn(); $('#input').focus(); };

/* ---------- voice: «просто скажи» (ru / kk / en) ---------- */
const LANGS = [['RU', 'ru-RU'], ['KZ', 'kk-KZ'], ['EN', 'en-US']];
let langIdx = Math.max(0, LANGS.findIndex(l => l[0] === localStorage.getItem('stella.voiceLang')));
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null;
function renderLang() { $('#lang-btn').textContent = LANGS[langIdx][0]; }
renderLang();
$('#lang-btn').onclick = () => { langIdx = (langIdx + 1) % LANGS.length; localStorage.setItem('stella.voiceLang', LANGS[langIdx][0]); renderLang(); };
if (!SR) { $('#mic-btn').hidden = true; $('#lang-btn').hidden = true; }
$('#mic-btn').onclick = () => {
  if (rec) { rec.stop(); return; }
  rec = new SR(); rec.lang = LANGS[langIdx][1]; rec.interimResults = true; rec.continuous = false;
  const base = input.value ? input.value.trimEnd() + ' ' : '';
  rec.onresult = e => { let t = ''; for (const r of e.results) t += r[0].transcript; input.value = base + t; input.dispatchEvent(new Event('input')); };
  rec.onend = () => { rec = null; $('#mic-btn').classList.remove('rec'); if (input.value.trim() && localStorage.getItem('stella.voiceAutoSend') !== '0') $('#composer').requestSubmit(); };
  rec.onerror = e => { if (e.error === 'not-allowed') toast('Разрешите доступ к микрофону в настройках браузера'); else if (e.error !== 'no-speech' && e.error !== 'aborted') toast('Голос: ' + e.error); };
  $('#mic-btn').classList.add('rec');
  try { rec.start(); } catch { rec = null; $('#mic-btn').classList.remove('rec'); }
};

$('#chat-transfer').onclick = () => {
  const { where, chat } = S.open;
  if (where === 'pc') {
    if (!confirm('Перенести эту задачу на сервер? Агент на сервере продолжит работу, даже если компьютер выключат.')) return;
    send({ t: 'transfer.toServer', chatId: chat.id });
    toast('Переношу на сервер…'); $('#chat').hidden = true; S.open = null; setTab('server');
  } else {
    if (!S.pcOnline) return toast('Компьютер не в сети');
    if (!confirm('Продолжить эту задачу на компьютере?')) return;
    send({ t: 'transfer.toPc', chatId: chat.id });
    toast('Отправлено на компьютер'); $('#chat').hidden = true; S.open = null; setTab('pc');
  }
};

/* ================================================================== */
/* WhatsApp                                                            */
/* ================================================================== */
function renderWa() {
  const st = S.wa.status;
  const label = { off: 'отключён', connecting: 'подключение…', qr: 'ждёт QR', connected: 'подключён', reconnecting: 'переподключение…', logged_out: 'отвязан', error: 'ошибка' }[st] || st;
  $('#wa-pill').textContent = label; $('#wa-pill').classList.toggle('on', st === 'connected');
  $('#wa-connect').hidden = st === 'connected';
  $('#wa-main').hidden = st !== 'connected';
  $('#wa-qr').hidden = st !== 'qr' || !S.wa.qr;
  if (S.wa.qr) $('#wa-qr-img').src = S.wa.qr;
  $('#wa-start').hidden = st === 'qr' || st === 'connecting';
  $('#wa-start').textContent = st === 'error' ? 'Попробовать снова' : 'Подключить по QR-коду';
  $('#wa-error').hidden = !S.wa.error; $('#wa-error').textContent = S.wa.error || '';
  renderWaList(); renderWaLog();
}
function renderWaList() {
  const ul = $('#wa-list'); ul.innerHTML = '';
  for (const c of (S.wa.chats || []).filter(c => !c.group)) {
    const li = document.createElement('li');
    li.innerHTML = `<div class="ico">${esc(initial(c.name))}</div><div class="txt"><div class="t1">${esc(c.name)}</div><div class="t2">${esc(c.last)}</div></div><label class="switch" title="Автоответчик"><input type="checkbox" ${c.auto ? 'checked' : ''}><i></i></label>`;
    const cb = li.querySelector('input');
    cb.onchange = () => {
      if (cb.checked && !confirm(`Включить автоответчик для «${c.name}»?\n\nАгент будет сам отвечать этому человеку в вашем стиле, без вашего подтверждения. Собеседник не узнает, что отвечает не вы.`)) { cb.checked = false; return; }
      send({ t: 'wa.auto', jid: c.jid, on: cb.checked });
    };
    ul.appendChild(li);
  }
}
function renderWaLog() {
  const ul = $('#wa-log'); ul.innerHTML = '';
  for (const e of (S.wa.autoLog || []).slice(0, 30)) {
    const li = document.createElement('li');
    li.innerHTML = `<b>${esc(e.name)}</b> · <span class="muted">${new Date(e.ts).toLocaleTimeString().slice(0, 5)} · ${esc(e.status)}</span>${e.text ? `<div>${esc(e.text)}</div>` : ''}`;
    ul.appendChild(li);
  }
  if (!ul.children.length) ul.innerHTML = '<li class="muted">Пока пусто</li>';
}
$('#wa-start').onclick = () => { send({ t: 'wa.connect' }); S.wa.status = 'connecting'; renderWa(); };
$('#wa-logout').onclick = () => { if (confirm('Отвязать WhatsApp от Stella?')) send({ t: 'wa.logout' }); };
let waSearchT = null;
$('#wa-search').oninput = e => { clearTimeout(waSearchT); waSearchT = setTimeout(() => send({ t: 'wa.search', query: e.target.value }), 250); };

/* ================================================================== */
/* terminal                                                            */
/* ================================================================== */
let xterm = null, fit = null;
$('#open-term').onclick = () => {
  $('#term-view').hidden = false;
  if (!xterm) {
    xterm = new Terminal({ fontSize: 13, fontFamily: 'ui-monospace, Menlo, Consolas, monospace', theme: { background: '#0f0f0f' }, cursorBlink: true, scrollback: 3000 });
    fit = new FitAddon.FitAddon(); xterm.loadAddon(fit); xterm.open($('#term'));
    xterm.onData(d => send({ t: 'term.input', data: d }));
    // links (sign-in URL) open in the browser
    xterm.onSelectionChange(() => {});
  } else xterm.clear();
  setTimeout(() => { fit.fit(); send({ t: 'term.resize', cols: xterm.cols, rows: xterm.rows }); send({ t: 'term.open' }); xterm.focus(); }, 50);
};
$('#term-back').onclick = () => { $('#term-view').hidden = true; };
$('#term-restart').onclick = () => { xterm.clear(); send({ t: 'term.restart' }); };
document.querySelectorAll('.term-keys button[data-k]').forEach(b => b.onclick = () => send({ t: 'term.input', data: b.dataset.k.replace(/\\r/g, '\r').replace(/\\t/g, '\t').replace(/\\x1b/g, '\x1b') }));
$('#term-paste').onclick = async () => { try { const t = await navigator.clipboard.readText(); send({ t: 'term.input', data: t }); } catch { const t = prompt('Вставьте текст (код входа):'); if (t) send({ t: 'term.input', data: t }); } };
window.addEventListener('resize', () => { if (xterm && !$('#term-view').hidden) { fit.fit(); send({ t: 'term.resize', cols: xterm.cols, rows: xterm.rows }); } });

/* ================================================================== */
/* tabs, settings, notifications                                       */
/* ================================================================== */
function setTab(t) {
  S.tab = t;
  document.querySelectorAll('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === t));
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('on', v.id === 'v-' + t));
  if (t === 'wa' && S.wa.status === 'connected') send({ t: 'wa.overview' });
}
document.querySelectorAll('#tabs button').forEach(b => b.onclick = () => setTab(b.dataset.tab));
$('#mode-select').onchange = e => send({ t: 'settings.set', mode: e.target.value });
$('#logout').onclick = async () => { await fetch('/api/logout', { method: 'POST', headers: { authorization: 'Bearer ' + S.token } }).catch(() => {}); localStorage.removeItem('stella.token'); location.reload(); };
$('#notif-btn').onclick = async () => { const r = await Notification.requestPermission(); toast(r === 'granted' ? 'Уведомления включены' : 'Уведомления не разрешены'); };
async function notify(title, body) {
  body = plainText(body);
  if (document.visibilityState === 'visible') { toast(title + (body ? ': ' + body : ''), 5000); return; }
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  try { const reg = await navigator.serviceWorker.ready; reg.showNotification(title, { body, icon: '/icon.png', badge: '/icon.png' }); } catch { new Notification(title, { body }); }
}

/* ================================================================== */
/* admin: invites + accounts                                           */
/* ================================================================== */
function inviteLink(code) { return location.origin + '/#invite=' + encodeURIComponent(code); }
let lastInviteCount = null;
function renderAdmin(st) {
  const inv = $('#inv-list'); inv.innerHTML = '';
  for (const i of st.invites.slice(0, 20)) {
    const used = (i.uses || 0) >= (i.maxUses || 1);
    const li = document.createElement('li');
    li.innerHTML = `<div class="acc-row"><code>${esc(i.code)}</code> <span>${esc(i.note || '')}</span><span class="spacer"></span><span class="muted">${i.revoked ? 'отозван' : used ? 'использован: ' + esc((i.usedBy || []).join(', ')) : 'ждёт'}</span>${!i.revoked && !used ? '<button class="btn" data-copy>Ссылка</button><button class="btn" data-revoke>Отозвать</button>' : ''}</div>`;
    const c = li.querySelector('[data-copy]'); if (c) c.onclick = () => shareLink(inviteLink(i.code), i.note);
    const r = li.querySelector('[data-revoke]'); if (r) r.onclick = () => send({ t: 'admin.revoke', code: i.code });
    inv.appendChild(li);
  }
  if (!inv.children.length) inv.innerHTML = '<li class="muted">Пока нет</li>';
  // show the newest invite right after creating it
  if (lastInviteCount !== null && st.invites.length > lastInviteCount) { $('#inv-new').hidden = false; $('#inv-link').textContent = inviteLink(st.invites[0].code); }
  lastInviteCount = st.invites.length;
  const acc = $('#acc-list'); acc.innerHTML = '';
  for (const u of st.users) {
    const li = document.createElement('li');
    const online = u.online.length ? '🟢 ' + [...new Set(u.online)].map(d => d === 'pc' ? 'ПК' : 'телефон').join(', ') : (u.seen ? 'был ' + ago(u.seen) : 'не заходил');
    li.innerHTML = `<div class="acc-row"><b>${esc(u.name)}</b>${u.admin ? ' <span class="pill">админ</span>' : ''}${u.disabled ? ' <span class="pill">заблокирован</span>' : ''}<span class="muted">${esc(u.note || '')}</span><span class="spacer"></span><span class="muted">${online}${u.running ? ' · задач: ' + u.running : ''}</span>${u.admin ? '' : `<button class="btn" data-dis>${u.disabled ? 'Разблокировать' : 'Блок'}</button><button class="btn" data-del>Удалить</button>`}</div>`;
    const d = li.querySelector('[data-dis]'); if (d) d.onclick = () => send({ t: 'admin.disable', name: u.name, on: !u.disabled });
    const x = li.querySelector('[data-del]'); if (x) x.onclick = () => { if (confirm(`Удалить аккаунт «${u.name}» вместе с его файлами, чатами и WhatsApp на сервере? Это нельзя отменить.`)) send({ t: 'admin.delete', name: u.name }); };
    acc.appendChild(li);
  }
}
$('#inv-create').onclick = () => { send({ t: 'admin.invite', note: $('#inv-note').value }); $('#inv-note').value = ''; };
$('#inv-share').onclick = () => shareLink($('#inv-link').textContent);
async function shareLink(url, note) {
  const text = 'Приглашение в Stella' + (note ? ' (' + note + ')' : '') + ': ' + url;
  try { if (navigator.share) { await navigator.share({ title: 'Stella', text, url }); return; } } catch {}
  try { await navigator.clipboard.writeText(url); toast('Ссылка скопирована'); } catch { prompt('Скопируйте ссылку:', url); }
}

/* links: #invite=CODE (register) and #pair=CODE (sign in from the PC's QR) */
async function handleHash() {
  const h = new URLSearchParams(location.hash.slice(1));
  if (h.get('invite')) {
    history.replaceState(null, '', '/');
    if (!S.token) { document.querySelector('#auth-seg button[data-mode=register]').click(); $('#auth-invite').hidden = false; $('#auth-invite').value = h.get('invite'); }
  }
  if (h.get('pair')) {
    history.replaceState(null, '', '/');
    try {
      const r = await fetch('/api/pair/claim', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ code: h.get('pair') }) });
      const j = await r.json(); if (!r.ok || j.error) throw new Error(j.error);
      S.token = j.token; localStorage.setItem('stella.token', j.token);
      if (S.ws) { const old = S.ws; S.ws = null; old.close(); }
      toast('Телефон привязан к аккаунту ' + j.user.name);
      return true;
    } catch (e) { toast('Привязка не удалась: ' + e.message, 6000); }
  }
  return false;
}

/* ================================================================== */
/* security: 2FA, sessions, password                                   */
/* ================================================================== */
function deviceName(s) {
  const ua = s.ua || '';
  const d = /Electron|Stella/i.test(ua) || s.kind === 'pc' ? 'Компьютер (Stella)' : /iPhone|iPad/.test(ua) ? 'iPhone' : /Android/.test(ua) ? 'Android' : /Windows/.test(ua) ? 'Windows' : /Mac/.test(ua) ? 'Mac' : 'Устройство';
  return d + (s.kind === 'qr' ? ' · по QR' : '');
}
function renderSecurity(m) {
  const box = $('#sec-2fa');
  if (m.twofa) {
    box.innerHTML = '<p class="small">✅ Двухфакторная защита <b>включена</b>. Без кода из приложения войти нельзя.</p><button class="btn wide" id="sec-off">Отключить 2FA</button>';
    $('#sec-off').onclick = () => { const pw = prompt('Пароль от аккаунта:'); if (!pw) return; const code = prompt('Код из приложения-аутентификатора:'); if (code) send({ t: 'security.2fa.disable', password: pw, code }); };
    $('#sec-2fa-setup').hidden = true;
  } else {
    box.innerHTML = '<p class="small warn-text">⚠️ Двухфакторная защита выключена. Включите её — тогда даже узнав пароль, войти в аккаунт не смогут.</p><button class="btn primary wide" id="sec-on">Включить двухфакторную защиту</button>';
    $('#sec-on').onclick = () => send({ t: 'security.2fa.setup' });
  }
  const ul = $('#sec-sessions'); ul.innerHTML = '';
  for (const s of m.sessions || []) {
    const li = document.createElement('li');
    li.innerHTML = `<div class="acc-row"><b>${esc(deviceName(s))}</b>${s.current ? ' <span class="pill on">это устройство</span>' : ''}<span class="spacer"></span><span class="muted">${esc(s.ip || '')} · ${ago(s.last)}</span>${s.current ? '' : '<button class="btn">Выйти</button>'}</div>`;
    const b = li.querySelector('button'); if (b) b.onclick = () => send({ t: 'security.revoke', id: s.id });
    ul.appendChild(li);
  }
}
$('#sec-enable').onclick = () => send({ t: 'security.2fa.enable', code: $('#sec-code').value.trim() });
$('#sec-revoke-all').onclick = () => { if (confirm('Выйти из аккаунта на всех других устройствах?')) send({ t: 'security.revokeOthers' }); };
$('#pw-change').onclick = () => { send({ t: 'security.password', old: $('#pw-old').value, new: $('#pw-new').value }); $('#pw-old').value = ''; $('#pw-new').value = ''; };

/* ================================================================== */
/* onboarding / "about me"                                             */
/* ================================================================== */
const OB = ['name', 'address', 'role', 'city', 'language', 'style', 'tasks', 'about'];
function openOnboarding() {
  for (const k of OB) $('#ob-' + k).value = (S.profile || {})[k] || '';
  $('#ob-wa').hidden = S.wa && S.wa.status === 'connected';
  $('#onboard').hidden = false;
  $('#onboard').scrollTop = 0;
}
$('#ob-save').onclick = () => {
  const p = {}; for (const k of OB) p[k] = $('#ob-' + k).value.trim();
  if (!p.name) { toast('Напишите, как вас зовут'); return; }
  send({ t: 'profile.set', profile: p });
  $('#onboard').hidden = true; toast('Агент запомнил. Спасибо, ' + p.name + '!');
};
$('#ob-skip').onclick = () => { localStorage.setItem('stella.onboard.skip', '1'); $('#onboard').hidden = true; };
$('#ob-wa-go').onclick = () => { $('#ob-save').click(); if ($('#onboard').hidden) { setTab('wa'); send({ t: 'wa.connect' }); } };
$('#about-open').onclick = openOnboarding;
function renderAbout() {
  const p = S.profile || {};
  $('#about-summary').textContent = p.name ? `${p.name}${p.role ? ' · ' + p.role : ''}${p.city ? ' · ' + p.city : ''}` : 'Агент ещё не знает вас.';
  $('#about-open').textContent = p.name ? 'Изменить' : 'Рассказать о себе агенту';
}

/* ================================================================== */
/* services                                                            */
/* ================================================================== */
function renderServices() {
  const sv = S.services || {};
  $('#svc-bc-state').textContent = sv.bilimclass ? 'подключён · ' + sv.bilimclass.login : 'не подключён';
  $('#svc-bc-state').className = 'small ' + (sv.bilimclass ? 'ok-text' : 'muted');
  $('#bc-del').hidden = !sv.bilimclass; if (sv.bilimclass) $('#bc-login').value = sv.bilimclass.login;
  $('#svc-mail-state').textContent = sv.email ? 'подключена · ' + sv.email.address : 'не подключена';
  $('#svc-mail-state').className = 'small ' + (sv.email ? 'ok-text' : 'muted');
  $('#mail-del').hidden = !sv.email; if (sv.email) $('#mail-addr').value = sv.email.address;
  $('#svc-wa-state').textContent = S.wa && S.wa.status === 'connected' ? 'подключён' : 'не подключён';
  $('#svc-pc-state').textContent = S.pcOnline ? 'в сети' : 'не в сети';
}
$('#bc-save').onclick = () => { send({ t: 'services.set', name: 'bilimclass', data: { login: $('#bc-login').value, password: $('#bc-pass').value } }); $('#bc-pass').value = ''; toast('BilimClass сохранён'); };
$('#bc-del').onclick = () => { if (confirm('Отключить BilimClass и удалить сохранённый пароль?')) send({ t: 'services.remove', name: 'bilimclass' }); };
$('#mail-save').onclick = () => { send({ t: 'services.set', name: 'email', data: { address: $('#mail-addr').value, password: $('#mail-pass').value, imap: $('#mail-imap').value, smtp: $('#mail-smtp').value } }); $('#mail-pass').value = ''; toast('Проверяю почту…'); };
$('#mail-del').onclick = () => { if (confirm('Отключить почту и удалить сохранённый пароль?')) send({ t: 'services.remove', name: 'email' }); };
$('#svc-wa-go').onclick = () => setTab('wa');

/* ================================================================== */
/* HOME                                                                */
/* ================================================================== */
let homeTeam = true;
function hello() { const h = new Date().getHours(); return h < 5 ? 'Доброй ночи' : h < 12 ? 'Доброе утро' : h < 18 ? 'Добрый день' : 'Добрый вечер'; }
function renderHome() {
  const n = (S.profile && S.profile.name) || (S.user && S.user.name) || '';
  $('#home-hello').textContent = `${hello()}${n ? ', ' + n : ''} 👋`;
  const chips = [[S.pcOnline, S.pcOnline ? 'ПК в сети' : 'ПК не в сети'], [S.wa && S.wa.status === 'connected', 'WhatsApp'], [!!(S.services && S.services.bilimclass), 'BilimClass'], [!!(S.services && S.services.email), 'Почта']];
  $('#home-chips').innerHTML = chips.map(([on, t]) => `<span class="${on ? 'on' : ''}">${on ? '● ' : '○ '}${esc(t)}</span>`).join('');
  const ul = $('#home-recent'); ul.innerHTML = '';
  for (const c of S.lists.server.slice(0, 4)) {
    const li = document.createElement('li');
    li.innerHTML = `<div class="ico ${c.busy ? 'busy' : ''}">${c.busy ? '' : esc(initial(c.title))}</div><div class="txt"><div class="t1">${esc(c.title)}</div><div class="t2">${c.busy ? 'Агент работает…' : esc(plainText(c.last))}</div></div><div class="when">${ago(c.updated)}</div>`;
    li.onclick = () => openChat('server', c.id); ul.appendChild(li);
  }
  if (!ul.children.length) ul.innerHTML = '<li class="muted small" style="padding:8px 16px">Здесь появятся ваши задачи</li>';
}
$('#home-team').onclick = () => { homeTeam = !homeTeam; $('#home-team').classList.toggle('on', homeTeam); };
function homeSend(text) {
  text = (text ?? $('#home-input').value).trim(); if (!text) { $('#home-input').focus(); return; }
  $('#home-input').value = '';
  S.open = { where: 'server', chat: { id: null, title: homeTeam ? '👥 ' + text.slice(0, 40) : 'Новая задача', messages: [] }, pendingNew: true };
  $('#chat').hidden = false; renderChat();
  if (homeTeam) send({ t: 'team.start', text }); else send({ t: 'server.send', chatId: null, text });
}
$('#home-go').onclick = () => homeSend();
$('#home-input').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && matchMedia('(pointer:fine)').matches) { e.preventDefault(); homeSend(); } });
$('#home-mic').onclick = () => {
  if (!SR) return toast('Голосовой ввод не поддерживается этим браузером');
  if (rec) { rec.stop(); return; }
  rec = new SR(); rec.lang = LANGS[langIdx][1]; rec.interimResults = true;
  const inp = $('#home-input'); const base = inp.value ? inp.value.trimEnd() + ' ' : '';
  rec.onresult = e => { let t = ''; for (const r of e.results) t += r[0].transcript; inp.value = base + t; };
  rec.onend = () => { rec = null; $('#home-mic').classList.remove('rec'); if (inp.value.trim()) homeSend(); };
  rec.onerror = e => { if (e.error === 'not-allowed') toast('Разрешите доступ к микрофону'); };
  $('#home-mic').classList.add('rec'); try { rec.start(); } catch { rec = null; $('#home-mic').classList.remove('rec'); }
};
const QA = {
  team: () => { $('#home-input').focus(); homeTeam = true; $('#home-team').classList.add('on'); toast('Опишите сразу несколько задач — агенты сделают их параллельно'); },
  pptx: () => { $('#home-input').value = 'Сделай презентацию на тему «', homeTeam = false; $('#home-team').classList.remove('on'); $('#home-input').focus(); },
  docx: () => { $('#home-input').value = 'Напиши проектную работу на тему «», 9 класс, с введением, 2 главами, заключением и литературой'; homeTeam = false; $('#home-team').classList.remove('on'); $('#home-input').focus(); },
  wa: () => { if (S.wa && S.wa.status === 'connected') { $('#home-input').value = 'Напиши в WhatsApp '; homeTeam = false; $('#home-team').classList.remove('on'); $('#home-input').focus(); } else setTab('wa'); },
  mail: () => homeSend('Разбери мою почту за сегодня: что важно, на что нужно ответить, и предложи ответы'),
  grading: () => openGrading()
};
document.querySelectorAll('[data-qa]').forEach(b => b.onclick = () => QA[b.dataset.qa]());

/* ================================================================== */
/* GRADING: photos of student work -> grades                           */
/* ================================================================== */
const G = { list: [], cur: null, uploading: 0, uploadTotal: 0 };
function openGrading(id) { $('#grading').hidden = false; if (id) send({ t: 'grading.get', id }); else { G.cur = null; renderGradingList(); } send({ t: 'grading.list' }); }
$('#gr-back').onclick = () => { if (G.cur) { G.cur = null; renderGradingList(); } else $('#grading').hidden = true; };
function renderGradingList() {
  $('#gr-title').textContent = 'Проверка работ'; $('#gr-sub').textContent = 'СОР, СОЧ, контрольные — по фото';
  const items = G.list.map(b => `<div class="gr-item" data-open="${esc(b.id)}"><div class="gr-grade">📝</div><div class="tt"><b>${esc(b.title)}</b><span>${esc([b.subject, b.klass].filter(Boolean).join(' · '))} · ${b.counts.done}/${b.counts.total || b.counts.uploaded} · ${{ uploading: 'загрузка фото', checking: 'проверяется…', done: 'готово', paused: 'пауза' }[b.status] || b.status}</span></div>${b.counts.review ? `<span class="gr-flag">⚠ ${b.counts.review}</span>` : ''}</div>`).join('');
  $('#gr-body').innerHTML = `
    <div class="gr-card"><h3>Новая проверка</h3>
      <label>Название<input id="gn-title" placeholder="СОЧ за 2 четверть"></label>
      <label>Предмет<input id="gn-subject" placeholder="Математика"></label>
      <label>Класс<input id="gn-klass" placeholder="9А"></label>
      <label>Ключ ответов / критерии (можно коротко: «1) 12  2) x=3  3) …», баллы за задания)<textarea id="gn-key" rows="4"></textarea></label>
      <label>Максимальный балл<input id="gn-max" inputmode="numeric" placeholder="20"></label>
      <label>Шкала оценок<textarea id="gn-scale" rows="2">85–100% → 5, 65–84% → 4, 40–64% → 3, 0–39% → 2</textarea></label>
      <label>Страниц в одной работе<select id="gn-pages"><option>1</option><option>2</option><option>3</option><option>4</option></select></label>
      <label>Список класса (необязательно — помогает узнать фамилии)<textarea id="gn-roster" rows="2" placeholder="Абаев Тимур, Ахметова Алина, …"></textarea></label>
      <button class="btn primary wide" id="gn-create" style="margin-top:10px">Создать и загрузить фото</button>
    </div>
    ${items ? '<h3 class="sub">Мои проверки</h3><div class="gr-list">' + items + '</div>' : ''}`;
  $('#gn-create').onclick = () => send({ t: 'grading.create', spec: { title: $('#gn-title').value || 'Проверка', subject: $('#gn-subject').value, klass: $('#gn-klass').value, key: $('#gn-key').value, maxScore: $('#gn-max').value, scale: $('#gn-scale').value, pagesPerWork: $('#gn-pages').value, roster: $('#gn-roster').value } });
  $('#gr-body').querySelectorAll('[data-open]').forEach(el => el.onclick = () => send({ t: 'grading.get', id: el.dataset.open }));
}
const gradeClass = g => { const n = parseInt(g, 10); return n >= 2 && n <= 5 ? 'g' + n : ''; };
function finalOf(w) { const r = w.result || {}, e = w.edited || {}; return { student: e.student || r.student || 'Без имени', total: e.total ?? r.total, max: r.max_total, grade: e.grade || r.grade || '—', review: !w.edited && r.needs_review, r }; }
function renderBatch(b) {
  G.cur = b;
  $('#gr-title').textContent = b.title; $('#gr-sub').textContent = [b.subject, b.klass].filter(Boolean).join(' · ') || 'Проверка работ';
  const c = b.counts, pct = c.total ? Math.round(c.done / c.total * 100) : 0;
  const rows = b.works.map(w => {
    const f = finalOf(w);
    const sub = w.status === 'done' ? `${f.total ?? '?'}/${f.max ?? '?'} баллов · ${{ clear: 'разборчиво', hard: 'трудный почерк', unreadable: 'неразборчиво' }[f.r.legibility] || ''}${w.edited ? ' · ✍ исправлено учителем' : ''}` : w.status === 'failed' ? 'ошибка: ' + esc(w.error || '') : w.status === 'checking' ? 'проверяется…' : 'в очереди';
    return `<div class="gr-item" data-work="${esc(w.id)}"><div class="gr-grade ${gradeClass(f.grade)}">${w.status === 'done' ? esc(String(f.grade)) : w.status === 'checking' ? '…' : w.status === 'failed' ? '!' : '·'}</div><div class="tt"><b>${esc(w.status === 'done' ? f.student : 'Работа ' + w.files.join(', '))}</b><span>${sub}</span></div>${f.review && w.status === 'done' ? '<span class="gr-flag">⚠ проверить</span>' : ''}</div>`;
  }).join('');
  $('#gr-body').innerHTML = `
    <div class="gr-card">
      <div class="gr-stats"><span>📷 фото: ${c.uploaded}</span><span>📝 работ: ${c.total || Math.ceil(c.uploaded / (b.pagesPerWork || 1))}</span><span>✅ ${c.done}</span>${c.review ? `<span>⚠ проверить: ${c.review}</span>` : ''}${c.failed ? `<span>❗ ошибки: ${c.failed}</span>` : ''}</div>
      ${b.status === 'checking' || c.done ? `<div class="gr-progress"><i style="width:${pct}%"></i></div>` : ''}
      <div id="gr-up-status" class="small muted"></div>
      <div class="gr-actions">
        <label class="btn">📷 Добавить фото<input type="file" id="gr-files" accept="image/*" multiple hidden></label>
        <label class="btn">🔑 Фото ключа<input type="file" id="gr-keyfile" accept="image/*" hidden></label>
        ${b.status === 'checking' ? '<button class="btn" id="gr-pause">⏸ Пауза</button>' : `<button class="btn primary" id="gr-start">▶ ${c.done ? 'Продолжить' : 'Начать проверку'}</button>`}
        ${c.done ? '<button class="btn" id="gr-xlsx">⬇ Excel</button><button class="btn" id="gr-bc">🎓 Выставить в BilimClass</button>' : ''}
        <button class="btn danger-outline" id="gr-del">Удалить</button>
      </div>
      <p class="small muted">Сложные и неразборчивые работы агент не угадывает — помечает «⚠ проверить». Перед выставлением в журнал посмотрите их.</p>
    </div>
    <div class="gr-list">${rows || '<p class="muted small">Загрузите фото работ — по одному листу или камерой подряд.</p>'}</div>`;
  const up = (input, kind) => input.onchange = () => uploadPhotos(b.id, [...input.files], kind);
  up($('#gr-files'), 'work'); up($('#gr-keyfile'), 'key');
  const on = (id, fn) => { const el = $('#' + id); if (el) el.onclick = fn; };
  on('gr-start', () => send({ t: 'grading.start', id: b.id }));
  on('gr-pause', () => send({ t: 'grading.stop', id: b.id }));
  on('gr-xlsx', () => downloadXlsx(b));
  on('gr-bc', () => { if (b.counts.review && !confirm(`${b.counts.review} работ помечены «проверить». Выставить остальные?`)) return; if (confirm('Агент на компьютере откроет BilimClass и выставит оценки по таблице. Продолжить?')) send({ t: 'grading.toBilimclass', id: b.id }); });
  on('gr-del', () => { if (confirm('Удалить проверку вместе с фото?')) { send({ t: 'grading.delete', id: b.id }); G.cur = null; renderGradingList(); } });
  $('#gr-body').querySelectorAll('[data-work]').forEach(el => el.onclick = () => openWork(b, b.works.find(w => w.id === el.dataset.work)));
}
async function compress(file) {
  try {
    const bmp = await createImageBitmap(file);
    const k = Math.min(1, 2000 / Math.max(bmp.width, bmp.height));
    const c = document.createElement('canvas'); c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
    c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height);
    return await new Promise(r => c.toBlob(r, 'image/jpeg', 0.85));
  } catch { return file; }
}
async function uploadPhotos(id, files, kind) {
  G.uploadTotal += files.length;
  const status = () => { const el = $('#gr-up-status'); if (el) el.textContent = G.uploading ? `Загружаю фото: ${G.uploadTotal - G.uploading}/${G.uploadTotal}…` : ''; };
  G.uploading += files.length; status();
  let i = 0;
  const worker = async () => { while (i < files.length) { const f = files[i++]; try { const blob = await compress(f); await fetch(`/api/grading/${id}/upload?kind=${kind}&name=${encodeURIComponent((f.name || 'photo').replace(/\.[^.]+$/, '') + '.jpg')}`, { method: 'POST', headers: { authorization: 'Bearer ' + S.token, 'content-type': 'image/jpeg' }, body: blob }); } catch (e) { toast('Фото не загрузилось: ' + e.message); } G.uploading--; status(); } };
  await Promise.all([worker(), worker(), worker()]);
  G.uploadTotal = 0; status();
  send({ t: 'grading.get', id });
  toast(kind === 'key' ? 'Фото ключа загружено' : `Загружено фото: ${files.length}`);
}
async function downloadXlsx(b) {
  const r = await fetch(`/api/grading/${b.id}/export`, { headers: { authorization: 'Bearer ' + S.token } });
  if (!r.ok) return toast('Не удалось выгрузить');
  const url = URL.createObjectURL(await r.blob()); const a = document.createElement('a'); a.href = url; a.download = (b.title || 'Оценки') + '.xlsx'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 5000);
}
async function openWork(b, w) {
  const f = finalOf(w), r = f.r;
  const ans = (r.answers || []).map(a => `<div class="gr-ans ${a.uncertain ? 'unc' : ''}"><b>${esc(a.task || '')}</b> ${a.correct ? '✅' : '❌'} ${a.points ?? ''}/${a.max ?? ''} — «${esc(a.read_as || '')}» ${a.uncertain ? '⚠ не уверен' : ''}${a.comment ? '<br><span class="muted">' + esc(a.comment) + '</span>' : ''}</div>`).join('');
  $('#gr-body').innerHTML = `
    <div class="gr-card"><h3>${esc(f.student)}</h3>
      <div class="gr-stats"><span>Оценка: <b>${esc(String(f.grade))}</b></span><span>${f.total ?? '?'}/${f.max ?? '?'} баллов</span><span>уверенность ${r.confidence != null ? Math.round(r.confidence * 100) + '%' : '—'}</span></div>
      ${f.review ? `<p class="warn-text small">⚠ ${esc(r.review_reason || 'Нужно проверить')}</p>` : ''}
      <div id="gr-photos"></div>
      ${ans}
      ${r.feedback ? `<p class="small"><b>Комментарий ученику:</b> ${esc(r.feedback)}</p>` : ''}
      <label>Имя ученика<input id="gw-name" value="${esc(f.student)}"></label>
      <label>Баллы<input id="gw-total" inputmode="decimal" value="${esc(String(f.total ?? ''))}"></label>
      <label>Оценка<input id="gw-grade" value="${esc(String(f.grade))}"></label>
      <div class="gr-actions"><button class="btn primary" id="gw-save">Сохранить</button><button class="btn" id="gw-recheck">↻ Перепроверить</button><button class="btn" id="gw-back">← К списку</button></div>
    </div>`;
  for (const name of w.files) {
    const res = await fetch(`/api/grading/${b.id}/photo?name=${encodeURIComponent(name)}`, { headers: { authorization: 'Bearer ' + S.token } });
    if (res.ok) { const img = document.createElement('img'); img.className = 'gr-photo'; img.src = URL.createObjectURL(await res.blob()); const box = $('#gr-photos'); if (box) box.appendChild(img); }
  }
  $('#gw-save').onclick = () => { send({ t: 'grading.edit', id: b.id, workId: w.id, patch: { student: $('#gw-name').value.trim(), total: $('#gw-total').value === '' ? undefined : Number($('#gw-total').value), grade: $('#gw-grade').value.trim() } }); toast('Сохранено'); };
  $('#gw-recheck').onclick = () => { send({ t: 'grading.recheck', id: b.id, workId: w.id }); toast('Отправлено на повторную проверку'); };
  $('#gw-back').onclick = () => renderBatch(G.cur);
}

/* ---------- app updates (new service worker -> reload) ---------- */
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.addEventListener('controllerchange', () => { if (window.__stellaLoaded) $('#update-bar').hidden = false; });
  setTimeout(() => { window.__stellaLoaded = true; }, 3000);
  setInterval(() => navigator.serviceWorker.getRegistration().then(r => r && r.update()).catch(() => {}), 30 * 60 * 1000);
}
$('#update-go').onclick = () => location.reload();

function start() { setTab('home'); connect(); }
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
/* ---------- Cloudflare Turnstile ---------- */
let tsWidget = null;
function loadCaptcha(sitekey) {
  if (!sitekey || window.turnstile) return renderCaptcha(sitekey);
  const sc = document.createElement('script');
  sc.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
  sc.async = true; sc.onload = () => renderCaptcha(sitekey);
  document.head.appendChild(sc);
}
let tsKey = null;
function renderCaptcha(sitekey) {
  tsKey = sitekey || tsKey;
  if (!window.turnstile || tsWidget !== null || !tsKey) return;
  if (!$('#auth').classList.contains('active')) return;          // render only on the visible login screen
  tsWidget = turnstile.render('#captcha-box', { sitekey: tsKey, theme: matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light', language: 'ru',
    'error-callback': () => { $('#auth-err').textContent = 'Проверка Cloudflare не загрузилась. Обновите страницу или отключите блокировщик рекламы / VPN.'; } });
  // Turnstile renders inside a closed shadow root: just check that it put something into the box
  setTimeout(() => { if (!$('#captcha-box').firstElementChild) $('#auth-err').textContent = 'Проверка Cloudflare не загрузилась. Обновите страницу или отключите блокировщик рекламы / VPN.'; }, 8000);
}
function captchaToken() { try { return tsWidget !== null ? turnstile.getResponse(tsWidget) : ''; } catch { return ''; } }
function resetCaptcha() { try { if (tsWidget !== null) turnstile.reset(tsWidget); } catch {} }

(async () => {
  try { const j = await fetch('/api/info').then(r => r.json()); S.signup = j.signup; if (j.turnstile) loadCaptcha(j.turnstile); } catch {}
  await handleHash();
  if (S.token) start(); else show('auth');
})();
window.addEventListener('hashchange', () => handleHash().then(ok => { if (ok) start(); }));

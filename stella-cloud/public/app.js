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

function show(id) { document.querySelectorAll('.screen').forEach(x => x.classList.toggle('active', x.id === id)); }
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
    case 'pc.online': S.pcOnline = m.online; renderPcState(); if (m.online) toast('Компьютер в сети'); break;
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
  show('app'); renderList('server'); renderList('pc'); renderPcState(); renderWa();
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
  if (where === 'server') $('#server-empty').hidden = S.lists.server.length > 0;
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
  const act = (m.busy || m.duration != null) ? `<div class="activity" data-act>${m.busy ? '<span class="sp"></span>' : '<span class="done"></span>'}<span class="tx">${esc(m.busy ? (m.status || 'Думает…') : (m.error ? 'Ошибка' : 'Выполнено'))}</span><span class="tm">${secs != null ? secs + 's' : ''}</span><span>›</span></div>${m._open ? `<pre class="act-log">${esc((m.log || '').trim() || 'Пока пусто')}</pre>` : ''}` : '';
  el.innerHTML = `<div class="who"><b>✳</b> Stella</div>${steps}<div class="body">${m.text ? renderMarkdown(m.text) : ''}${m.error ? `<div class="err">${esc(m.error)}</div>` : ''}</div>${act}`;
  const a = el.querySelector('[data-act]');
  if (a) a.onclick = () => { m._open = !m._open; fillMsg(el, m); };
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
  if (where === 'server') send({ t: 'server.send', chatId: chat.id, text });
  else { send({ t: 'pc.send', chatId: chat.id, text }); toast('Отправлено на компьютер'); }
};
input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && window.matchMedia('(pointer:fine)').matches) { e.preventDefault(); $('#composer').requestSubmit(); } });

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

function start() { setTab('server'); connect(); }
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
function renderCaptcha(sitekey) {
  if (!window.turnstile || tsWidget !== null) return;
  tsWidget = turnstile.render('#captcha-box', { sitekey, theme: matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light', language: 'ru' });
}
function captchaToken() { try { return tsWidget !== null ? turnstile.getResponse(tsWidget) : ''; } catch { return ''; } }
function resetCaptcha() { try { if (tsWidget !== null) turnstile.reset(tsWidget); } catch {} }

(async () => {
  try { const j = await fetch('/api/info').then(r => r.json()); S.signup = j.signup; if (j.turnstile) loadCaptcha(j.turnstile); } catch {}
  await handleHash();
  if (S.token) start(); else show('auth');
})();
window.addEventListener('hashchange', () => handleHash().then(ok => { if (ok) start(); }));

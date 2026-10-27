const ICONS = {
  computer: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
  phone: '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',
  tv: '<rect x="2" y="5" width="20" height="13" rx="2"/><path d="M8 21h8"/>',
  router: '<rect x="3" y="14" width="18" height="6" rx="2"/><path d="M7 17h.01M11 17h.01M8 10a6 6 0 0 1 8 0M5.5 7.5a10 10 0 0 1 13 0"/>',
  speaker: '<rect x="6" y="2" width="12" height="20" rx="3"/><circle cx="12" cy="15" r="3"/><circle cx="12" cy="7" r="1"/>',
  appliance: '<rect x="4" y="2" width="16" height="20" rx="2"/><circle cx="12" cy="14" r="4"/><path d="M8 6h.01M11 6h2"/>',
  iot: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 10h.01M12 10h.01M16 10h.01M8 20h8M12 16v4"/>',
  unknown: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 10h.01M12 10h.01M16 10h.01M8 20h8M12 16v4"/>',
};
const TYPE_LABEL = {computer: 'Компьютер', phone: 'Телефон', tv: 'Телевизор', router: 'Роутер',
  speaker: 'Умная колонка', appliance: 'Бытовая техника', iot: 'Умное устройство', unknown: 'Неизвестное устройство'};
const REASON = {ads: 'реклама', trackers: 'трекер', malware: 'вирус', phishing: 'фишинг', adult: '18+',
  doh: 'обход DoH', suspicious_tld: 'подозрительная зона'};

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const api = async (url, opts) => {
  const r = await fetch(url, opts);
  if (r.status === 401 && !url.startsWith('/api/auth/')) { showLogin(); throw new Error(JSON.stringify({detail: 'Нужно войти'})); }
  if (!r.ok) throw new Error(await r.text());
  return r.json();
};
let devices = [];
let tab = 'overview';

const PAGES = {
  overview: ['Обзор', 'Живая карта сети и главное за сутки'],
  devices: ['Устройства', 'Всё, что подключено к домашней сети'],
  log: ['Журнал', 'Какие сайты открывают устройства'],
  protection: ['Защита', 'Насколько строго фильтровать интернет'],
  av: ['Антивирус', 'Проверка ссылок и файлов'],
  vpn: ['VPN', 'Зашифрованный туннель для всего дома'],
  tv: ['Телевизоры', 'Sony Bravia'],
  home: ['Умный дом', 'Устройства Xiaomi'],
  speakers: ['Колонки', 'Яндекс Станция через Home Assistant'],
  stats: ['Статистика', 'Цифры за 24 часа'],
  settings: ['Настройки', 'Профиль, пользователи, ключи'],
};
function go(t) {
  tab = t;
  document.querySelectorAll('#tabs button').forEach((x) => x.classList.toggle('active', x.dataset.tab === t));
  document.querySelectorAll('main > section').forEach((s) => s.hidden = s.id !== 'tab-' + t);
  $('#pageTitle').textContent = PAGES[t][0];
  $('#pageSub').textContent = PAGES[t][1];
  if (scene) { scene.setDim(t === 'overview' ? 0 : 1); scene.setFocus(t === 'overview' ? $('#heroStage') : null); }
  $('#nodeLabels').hidden = t !== 'overview';
  scrollTo({top: 0, behavior: 'smooth'});
  refresh();
}
document.querySelectorAll('#tabs button').forEach((b) => b.onclick = () => go(b.dataset.tab));
document.addEventListener('click', (e) => { const g = e.target.closest('[data-goto]'); if (g) go(g.dataset.goto); });
const toast = (msg) => { const t = $('#toast'); t.textContent = msg; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => t.hidden = true, 3200); };

const TYPE_HEX = {router: '#3cf2b0', computer: '#4cc9ff', phone: '#8b5cff', tv: '#ffc24c', speaker: '#ff7ad9',
  appliance: '#7affd4', iot: '#9aa4ff', unknown: '#8a90ad'};
function iconSvg(type, self) {
  const badge = self ? '<span class="badge"><svg viewBox="0 0 24 24"><path d="m5 12 5 5 9-10"/></svg></span>' : '';
  return `<div class="ico"><svg viewBox="0 0 24 24">${ICONS[type] || ICONS.unknown}</svg>${badge}</div>`;
}

async function loadDevices() {
  devices = await api('/api/devices');
  const on = devices.filter((d) => d.online).length;
  $('#devSummary').textContent = `В сети: ${on} из ${devices.length}`;
  $('#devGrid').innerHTML = devices.map((d) => `
    <div class="card ${d.online ? 'on' : ''}" data-mac="${esc(d.mac)}" style="--c:${TYPE_HEX[d.type] || TYPE_HEX.unknown}">
      <div class="status"><span class="dot"></span>${d.online ? 'В сети' : 'Не в сети'}</div>
      ${iconSvg(d.type, d.is_self)}
      <div class="name">${esc(d.display_name)}</div>
      <div class="sub">${d.is_self ? 'Это устройство' : TYPE_LABEL[d.type] || ''}</div>
      <div class="ip">${esc(d.ip || '')}${d.vendor ? ' · ' + esc(d.vendor) : ''}</div>
    </div>`).join('') || '<p class="muted">Устройства ещё не найдены — нажми «Сканировать сеть».</p>';
  const sel = $('#logDevice'), cur = sel.value;
  sel.innerHTML = '<option value="">Все устройства</option>' +
    devices.filter((d) => d.ip).map((d) => `<option value="${esc(d.ip)}">${esc(d.display_name)}</option>`).join('');
  sel.value = cur;
  if (scene) scene.setDevices(devices);
}
// наклон карточек за курсором
$('#devGrid').addEventListener('pointermove', (e) => {
  const c = e.target.closest('.card'); if (!c) return;
  const r = c.getBoundingClientRect(), x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
  c.style.transform = `rotateY(${(x - .5) * 14}deg) rotateX(${(.5 - y) * 14}deg) translateZ(6px)`;
  c.style.setProperty('--mx', x * 100 + '%'); c.style.setProperty('--my', y * 100 + '%');
});
$('#devGrid').addEventListener('pointerout', (e) => { const c = e.target.closest('.card'); if (c && !c.contains(e.relatedTarget)) c.style.transform = ''; });

$('#devGrid').onclick = (e) => {
  const card = e.target.closest('.card');
  if (!card) return;
  const d = devices.find((x) => x.mac === card.dataset.mac);
  $('#mTitle').textContent = d.display_name;
  $('#mInfo').textContent = `${d.ip || ''} · ${d.mac}`;
  $('#mName').value = d.name || '';
  $('#mName').placeholder = d.hostname || '';
  $('#mType').innerHTML = Object.entries(TYPE_LABEL).map(([k, v]) => `<option value="${k}" ${k === d.type ? 'selected' : ''}>${v}</option>`).join('');
  $('#modal').hidden = false;
  $('#modal').dataset.mac = d.mac;
};
$('#mCancel').onclick = () => $('#modal').hidden = true;
$('#mSave').onclick = async () => {
  await api('/api/devices/' + encodeURIComponent($('#modal').dataset.mac), {
    method: 'PATCH', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: $('#mName').value, type: $('#mType').value})});
  $('#modal').hidden = true;
  loadDevices();
};
$('#scanBtn').onclick = async (e) => {
  e.target.disabled = true; e.target.textContent = 'Сканирую…';
  try { await api('/api/scan', {method: 'POST'}); } finally { e.target.disabled = false; e.target.textContent = 'Сканировать сеть'; }
  loadDevices();
};

const fmtTime = (ts) => new Date(ts * 1000).toLocaleTimeString('ru-RU', {hour: '2-digit', minute: '2-digit', second: '2-digit'});
async function loadLog() {
  const p = new URLSearchParams({limit: 300});
  if ($('#logBlocked').checked) p.set('blocked', 'true');
  if ($('#logDevice').value) p.set('ip', $('#logDevice').value);
  if ($('#logSearch').value.trim()) p.set('q', $('#logSearch').value.trim());
  const rows = await api('/api/queries?' + p);
  $('#logBody').innerHTML = rows.map((r) => `<tr>
    <td>${fmtTime(r.ts)}</td><td>${esc(r.device)}</td><td class="dom">${esc(r.domain)}</td>
    <td>${r.action === 'blocked' ? `<span class="tag blocked">заблокировано · ${esc(REASON[r.reason] || r.reason || '')}</span>`
       : r.action === 'error' ? '<span class="tag blocked">ошибка</span>' : '<span class="tag">разрешено</span>'}</td></tr>`).join('')
    || '<tr><td colspan="4" class="muted">Пока пусто</td></tr>';
}
['#logBlocked', '#logDevice'].forEach((s) => $(s).onchange = loadLog);
$('#logSearch').oninput = loadLog;

const LEVEL_STYLE = {off: {c: '#8e94b8', n: 0}, basic: {c: '#4cc9ff', n: 1}, medium: {c: '#3cf2b0', n: 2}, strict: {c: '#8b5cff', n: 3}};
async function loadProtection() {
  const s = await api('/api/settings');
  $('#levels').innerHTML = Object.entries(s.levels).map(([k, v]) => `
    <div class="level ${k === s.level ? 'active' : ''}" data-level="${k}" style="--lc:${LEVEL_STYLE[k].c}">
      <div class="lvl-ico"><svg><use href="#${k === 'off' ? 'i-protect' : 'i-shield'}"/></svg></div>
      <h3>${esc(v.title)}</h3><p>${esc(v.description)}</p>
      <div class="meter">${[1, 2, 3].map((i) => `<i class="${i <= LEVEL_STYLE[k].n ? 'f' : ''}"></i>`).join('')}</div></div>`).join('');
}
$('#levels').onclick = async (e) => {
  const el = e.target.closest('.level');
  if (!el) return;
  await api('/api/settings', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({level: el.dataset.level})});
  toast('Уровень защиты: ' + el.querySelector('h3').textContent);
  loadProtection();
};

async function loadStats() {
  const s = await api('/api/stats');
  $('#statTiles').innerHTML = kpi(s.queries_24h, 'запросов за 24 ч', 'i-log', '#4cc9ff') + kpi(s.blocked_24h, 'заблокировано', 'i-protect', '#ff4d6d') +
    kpi(`${s.devices_online}/${s.devices_total}`, 'устройств в сети', 'i-devices', '#3cf2b0') +
    kpi(s.queries_24h ? Math.round(100 * s.blocked_24h / s.queries_24h) + '%' : '0%', 'доля блокировок', 'i-stats', '#8b5cff');
  countUpAll($('#statTiles'));
  const bars = (arr, extra) => { const mx = Math.max(1, ...arr.map((r) => r.n)); return arr.map((r) => `<div class="bar ${extra ? 'red' : ''}" style="--w:${Math.round(100 * r.n / mx)}%"><span>${esc(r.domain)}${extra ? ' <span class="muted">' + esc(REASON[r.reason] || '') + '</span>' : ''}</span><b>${r.n}</b></div>`).join('') || '<span class="muted">Нет данных</span>'; };
  $('#topDomains').innerHTML = bars(s.top_domains);
  $('#topBlocked').innerHTML = bars(s.top_blocked, true);
  $('#listSizes').textContent = Object.entries(s.list_sizes).map(([k, n]) => `${k}: ${n}`).join(' · ') || 'Списки не загружены';
}

const COUNTRY_CODES = {NL: 'Нидерланды', DE: 'Германия', FI: 'Финляндия', SE: 'Швеция', US: 'США', GB: 'Великобритания',
  FR: 'Франция', PL: 'Польша', KZ: 'Казахстан', TR: 'Турция', AE: 'ОАЭ', JP: 'Япония', SG: 'Сингапур',
  CH: 'Швейцария', LV: 'Латвия', EE: 'Эстония', RU: 'Россия'};
$('#vCountry').innerHTML += Object.entries(COUNTRY_CODES).map(([k, v]) => `<option value="${k}">${v}</option>`).join('');
let vpn = null;

async function loadVpn() {
  vpn = await api('/api/vpn');
  const act = vpn.profiles.find((p) => p.id === vpn.active);
  const b = $('#vpnBanner');
  if (vpn.state === 'connected') {
    b.className = 'banner ok';
    b.innerHTML = `<span class="big">🛡 VPN включён</span><span class="eq"><i></i><i></i><i></i></span><span>${esc(act ? act.flag + ' ' + act.name : '')}</span><span class="muted" id="vpnIp"></span>`;
    api('/api/vpn/ip').then((r) => { const el = $('#vpnIp'); if (el && r.ip) el.textContent = 'внешний IP: ' + r.ip; }).catch(() => {});
  } else if (vpn.state === 'down') {
    b.className = 'banner bad';
    b.innerHTML = `<span class="big">⚠ Туннель упал</span><span>${vpn.kill_switch ? 'Kill switch держит интернет закрытым' : 'Трафик идёт напрямую!'}</span>`;
  } else {
    b.className = 'banner';
    b.innerHTML = '<span class="big">VPN выключен</span><span class="muted">Трафик идёт напрямую</span>';
  }
  if (vpn.dry_run) b.innerHTML += '<span class="tag">демо: команды не выполняются</span>';
  if (vpn.error) b.innerHTML += `<span class="err">${esc(vpn.error)}</span>`;
  $('#vpnKill').checked = vpn.kill_switch;
  $('#vpnOff').hidden = !vpn.active;
  $('#vpnGrid').innerHTML = vpn.profiles.map((p) => `
    <div class="vcard ${p.id === vpn.active ? 'active' : ''}" data-id="${esc(p.id)}">
      <div class="flag">${p.flag}</div>
      <div class="name">${esc(p.name)}</div>
      <div class="sub">${esc(p.country_name || 'страна не указана')} · ${p.kind === 'wireguard' ? 'WireGuard' : 'OpenVPN'}</div>
      <div class="btns">
        ${p.id === vpn.active ? '<button class="btn ghost" data-act="off">Отключить</button>'
          : '<button class="btn" data-act="on">Подключить</button>'}
        <button class="btn danger" data-act="del" title="Удалить">✕</button>
      </div>
    </div>`).join('') || '<p class="muted">Серверов пока нет — нажми «Добавить сервер».</p>';
}
$('#vpnGrid').onclick = async (e) => {
  const btn = e.target.closest('button');
  if (!btn) return;
  const id = btn.closest('.vcard').dataset.id;
  const act = btn.dataset.act;
  btn.disabled = true;
  try {
    if (act === 'on') { btn.textContent = 'Подключаю…'; await api('/api/vpn/connect', jsonReq('POST', {id})); }
    else if (act === 'off') await api('/api/vpn/disconnect', {method: 'POST'});
    else if (act === 'del' && confirm('Удалить этот сервер?')) await api('/api/vpn/profiles/' + id, {method: 'DELETE'});
  } catch (err) { alert(errText(err)); }
  loadVpn();
};
const jsonReq = (method, body) => ({method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
const errText = (e) => { try { return JSON.parse(e.message).detail; } catch { return e.message; } };
$('#vpnOff').onclick = async () => { await api('/api/vpn/disconnect', {method: 'POST'}); loadVpn(); };
$('#vpnKill').onchange = async (e) => { await api('/api/vpn/settings', jsonReq('PUT', {kill_switch: e.target.checked})); loadVpn(); };
$('#vpnAddBtn').onclick = () => { $('#vErr').textContent = ''; $('#vpnModal').hidden = false; };
$('#vCancel').onclick = () => $('#vpnModal').hidden = true;
$('#vFile').onchange = async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  $('#vText').value = await f.text();
  if (!$('#vName').value) $('#vName').value = f.name.replace(/\.(conf|ovpn|txt)$/i, '');
};
$('#vSave').onclick = async () => {
  try {
    await api('/api/vpn/profiles', jsonReq('POST', {name: $('#vName').value, content: $('#vText').value,
      country: $('#vCountry').value || null, username: $('#vUser').value || null, password: $('#vPass').value || null}));
    $('#vpnModal').hidden = true;
    ['#vName', '#vText', '#vUser', '#vPass', '#vFile'].forEach((s) => $(s).value = '');
    loadVpn();
  } catch (err) { $('#vErr').textContent = errText(err); }
};

// ---------- Телевизоры ----------
const PAD = [['', 'e'], ['▲', 'Up'], ['', 'e'], ['◀', 'Left'], ['OK', 'Confirm'], ['▶', 'Right'], ['', 'e'], ['▼', 'Down'], ['', 'e']];
let tvs = [], tvCache = {};

async function loadTv() {
  tvs = await api('/api/tvs');
  $('#tvHint').textContent = tvs.length ? '' : 'Телевизоров пока нет';
  const known = new Set(tvs.map((t) => t.id));
  for (const t of tvs) {
    let el = document.getElementById('tv-' + t.id);
    if (!el) {
      el = document.createElement('div');
      el.id = 'tv-' + t.id; el.className = 'tv';
      $('#tvList').appendChild(el);
      tvStatic(t, el);
    }
    tvState(t, el);
  }
  document.querySelectorAll('#tvList .tv').forEach((el) => { if (!known.has(el.id.slice(3))) el.remove(); });
}

function tvStatic(t, el) {
  el.innerHTML = `
    <div class="tv-head"><div><h3>${esc(t.name)}</h3><div class="sub">${esc(t.ip)} · <span data-r="status">…</span></div></div>
      <button class="powerbtn" data-c="power" title="Питание">⏻</button></div>
    <div class="tverr" data-r="err"></div>
    <div data-r="body" hidden>
      <div class="lbl">Громкость</div>
      <div class="vol"><button class="ib" data-c="voldown">−</button>
        <input type="range" min="0" max="100" data-c="vol"><b data-r="vol">0</b>
        <button class="ib" data-c="volup">+</button><button class="ib" data-c="mute" data-r="mute">🔇</button></div>
      <div class="lbl" style="margin-top:14px">Вход</div><div class="chips" data-r="inputs"></div>
      <div class="lbl" style="margin-top:14px">Приложения</div><div class="chips" data-r="apps"></div>
      <div class="lbl" style="margin-top:14px">Пульт</div>
      <div class="pad">${PAD.map(([l, b]) => b === 'e' ? '<span class="e"></span>' : `<button class="ib" data-b="${b}">${l}</button>`).join('')}</div>
      <div class="row2" style="margin-top:8px"><button class="ib" data-b="Return">↩ Назад</button><button class="ib" data-b="Home">⌂ Домой</button><button class="ib" data-b="Options">⋯ Опции</button></div>
    </div>
    <button class="del" data-c="del">Удалить телевизор</button>`;
  const r = (k) => el.querySelector(`[data-r=${k}]`);
  const send = async (action, body) => {
    try { await api(`/api/tvs/${t.id}/${action}`, jsonReq('POST', body)); r('err').textContent = ''; }
    catch (e) { r('err').textContent = errText(e); }
    tvState(t, el);
  };
  el.onclick = async (e) => {
    const b = e.target.closest('button'); if (!b) return;
    const st = tvCache[t.id] || {};
    if (b.dataset.b) return send('press', {button: b.dataset.b});
    if (b.dataset.u) return send(b.dataset.k, {uri: b.dataset.u});
    switch (b.dataset.c) {
      case 'power': return send('power', {on: !st.power});
      case 'voldown': return send('volume', {level: Math.max(0, (st.audio?.volume ?? 0) - 2)});
      case 'volup': return send('volume', {level: Math.min(100, (st.audio?.volume ?? 0) + 2)});
      case 'mute': return send('mute', {mute: !st.audio?.mute});
      case 'del': if (confirm('Удалить телевизор из панели?')) { await api('/api/tvs/' + t.id, {method: 'DELETE'}); el.remove(); }
    }
  };
  el.querySelector('[data-c=vol]').onchange = (e) => send('volume', {level: +e.target.value});
  el.querySelector('[data-c=vol]').oninput = (e) => r('vol').textContent = e.target.value;
}

async function tvState(t, el) {
  const r = (k) => el.querySelector(`[data-r=${k}]`);
  try {
    const st = await api(`/api/tvs/${t.id}/state`);
    tvCache[t.id] = st;
    el.classList.toggle('on', st.power);
    r('err').textContent = '';
    r('status').textContent = st.power ? (st.playing?.title || 'включён') : 'в режиме ожидания';
    r('body').hidden = !st.power;
    if (st.power) {
      const slider = el.querySelector('[data-c=vol]');
      if (document.activeElement !== slider) { slider.value = st.audio.volume; r('vol').textContent = st.audio.volume; }
      r('mute').style.outline = st.audio.mute ? '2px solid var(--red)' : '';
      if (!el.dataset.loaded) {
        el.dataset.loaded = '1';
        const chip = (k, a) => `<button class="ib" data-k="${k}" data-u="${esc(a.uri)}">${esc(a.title)}</button>`;
        api(`/api/tvs/${t.id}/inputs`).then((l) => r('inputs').innerHTML = l.map((a) => chip('input', a)).join('')).catch(() => {});
        api(`/api/tvs/${t.id}/apps`).then((l) => r('apps').innerHTML = l.slice(0, 12).map((a) => chip('app', a)).join('')).catch(() => {});
      }
    }
  } catch (e) {
    el.classList.remove('on'); r('body').hidden = true; r('status').textContent = 'нет связи';
    r('err').textContent = errText(e);
  }
}

$('#tvAddBtn').onclick = () => {
  $('#tErr').textContent = '';
  $('#tvIps').innerHTML = devices.filter((d) => d.ip && (d.type === 'tv' || d.type === 'unknown'))
    .map((d) => `<option value="${esc(d.ip)}">${esc(d.display_name)}</option>`).join('');
  $('#tvModal').hidden = false;
};
$('#tCancel').onclick = () => $('#tvModal').hidden = true;
$('#tSave').onclick = async () => {
  try {
    await api('/api/tvs', jsonReq('POST', {name: $('#tName').value, ip: $('#tIp').value, psk: $('#tPsk').value}));
    $('#tvModal').hidden = true;
    ['#tName', '#tIp', '#tPsk'].forEach((s) => $(s).value = '');
    loadTv();
  } catch (err) { $('#tErr').textContent = errText(err); }
};

// ---------- Умный дом (Xiaomi MIoT) ----------
const homeSpec = {};

async function loadHome() {
  const list = await api('/api/home');
  $('#homeHint').textContent = list.length ? '' : 'Устройств пока нет';
  const known = new Set(list.map((d) => d.id));
  for (const d of list) {
    let el = document.getElementById('hm-' + d.id);
    if (!el) {
      el = document.createElement('div'); el.id = 'hm-' + d.id; el.className = 'hm';
      $('#homeList').appendChild(el);
      try { homeSpec[d.id] = await api(`/api/home/${d.id}/spec`); } catch (e) { el.textContent = errText(e); continue; }
      homeBuild(d, el);
    }
    homeUpdate(d, el);
  }
  document.querySelectorAll('#homeList .hm').forEach((el) => { if (!known.has(el.id.slice(3))) el.remove(); });
}

const fmtVal = (p, v) => {
  if (v === undefined || v === null) return '—';
  if (p.format === 'bool') return v ? 'Вкл' : 'Выкл';
  const hit = p.values?.find((x) => x.value === v);
  const u = {minutes: 'мин', hours: 'ч', seconds: 'с', percentage: '%'}[p.unit] || p.unit;
  return (hit ? hit.label : v) + (u && !hit && !p.label.includes(',') && p.unit !== 'celsius' ? ' ' + u : '');
};

function homeBuild(d, el) {
  const spec = homeSpec[d.id];
  const key = (p) => `${p.siid}.${p.piid}`;
  const ctl = (p) => {
    if (!p.writable) return `<span class="val" data-v="${key(p)}">—</span>`;
    if (p.format === 'bool') return `<label class="switch"><input type="checkbox" data-set="${key(p)}"><span></span></label>`;
    if (p.values) return `<select data-set="${key(p)}">${p.values.map((v) => `<option value="${v.value}">${esc(v.label)}</option>`).join('')}</select>`;
    if (p.range) return `<input type="number" data-set="${key(p)}" min="${p.range[0]}" max="${p.range[1]}" step="${p.range[2] || 1}">`;
    return `<span class="val" data-v="${key(p)}">—</span>`;
  };
  const rows = (arr) => arr.map((p) => `<div class="ctl" data-row="${key(p)}"><span>${esc(p.label)}</span>${ctl(p)}</div>`).join('');
  const readable = spec.properties.filter((p) => p.readable);
  const settings = readable.filter((p) => p.writable && p.name !== 'on');
  const info = readable.filter((p) => !p.writable);
  el.innerHTML = `
    <div><h3>${esc(d.name)}</h3><div class="sub">${esc(d.model)} · ${esc(d.ip)}</div></div>
    <div><div class="big" data-r="headline">…</div><div class="sub" data-r="subline"></div></div>
    <div class="tverr" data-r="err"></div>
    <div class="acts">${spec.actions.filter((a) => !a.args.length && a.label !== a.name).map((a) =>
      `<button class="btn ${a.confirm ? '' : 'ghost'}" data-act="${a.siid}.${a.aiid}" data-confirm="${a.confirm ? 1 : ''}">${esc(a.label)}</button>`).join('')}</div>
    ${settings.length ? `<div><div class="sec">Настройки</div>${rows(settings)}</div>` : ''}
    ${info.length ? `<div><div class="sec">Состояние</div>${rows(info)}</div>` : ''}
    <button class="del" data-del="1">Удалить устройство</button>`;
  const err = (m) => el.querySelector('[data-r=err]').textContent = m;
  const find = (k) => spec.properties.find((p) => key(p) === k);
  const setProp = async (k, value) => {
    const p = find(k);
    try { await api(`/api/home/${d.id}/set`, jsonReq('POST', {siid: p.siid, piid: p.piid, value})); err(''); }
    catch (e) { err(errText(e)); }
    homeUpdate(d, el);
  };
  el.onchange = (e) => {
    const t = e.target, k = t.dataset.set; if (!k) return;
    const p = find(k);
    setProp(k, p.format === 'bool' ? t.checked : Number(t.value));
  };
  el.onclick = async (e) => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.del) { if (confirm('Удалить устройство из панели?')) { await api('/api/home/' + d.id, {method: 'DELETE'}); el.remove(); } return; }
    if (b.dataset.act) {
      if (b.dataset.confirm && !confirm(`${b.textContent.trim()} — выполнить на устройстве?`)) return;
      const [siid, aiid] = b.dataset.act.split('.').map(Number);
      try { await api(`/api/home/${d.id}/action`, jsonReq('POST', {siid, aiid})); err(''); } catch (e2) { err(errText(e2)); }
      homeUpdate(d, el);
    }
  };
}

async function homeUpdate(d, el) {
  const spec = homeSpec[d.id];
  const r = (k) => el.querySelector(`[data-r=${k}]`);
  try {
    const st = await api(`/api/home/${d.id}/state`);
    r('err').textContent = '';
    const by = Object.fromEntries(spec.properties.map((p) => [p.name, p]));
    const val = (n) => by[n] ? st[`${by[n].siid}.${by[n].piid}`] : undefined;
    const on = val('on');
    el.classList.toggle('on', on === true && val('status') !== 0);
    r('headline').textContent = by.status ? fmtVal(by.status, val('status')) : (on ? 'Включено' : 'Выключено');
    const bits = [];
    if (by['left-time'] && val('left-time')) bits.push(`осталось ${val('left-time')} мин`);
    if (by.mode && val('mode') !== undefined) bits.push(fmtVal(by.mode, val('mode')));
    if (by['door-state'] && val('door-state') === 1) bits.push('дверца открыта');
    r('subline').textContent = bits.join(' · ');
    const f = by.fault && val('fault');
    if (f) { r('headline').classList.add('fault'); r('subline').textContent = fmtVal(by.fault, f); } else r('headline').classList.remove('fault');
    el.querySelectorAll('[data-row]').forEach((row) => {
      const k = row.dataset.row, v = st[k], p = spec.properties.find((x) => `${x.siid}.${x.piid}` === k);
      const inp = row.querySelector('[data-set]');
      if (inp) {
        if (document.activeElement === inp) return;
        if (p.format === 'bool') inp.checked = !!v; else if (v !== undefined) inp.value = v;
      } else row.querySelector('[data-v]').textContent = fmtVal(p, v);
    });
  } catch (e) {
    el.classList.remove('on'); r('headline').textContent = 'нет связи'; r('subline').textContent = '';
    r('err').textContent = errText(e);
  }
}

$('#homeAddBtn').onclick = () => {
  $('#hErr').textContent = '';
  $('#homeIps').innerHTML = devices.filter((d) => d.ip && d.vendor === 'Xiaomi' || d.type === 'appliance')
    .map((d) => `<option value="${esc(d.ip)}">${esc(d.display_name)}</option>`).join('');
  $('#homeModal').hidden = false;
};
$('#hCancel').onclick = () => $('#homeModal').hidden = true;
$('#hSave').onclick = async (e) => {
  e.target.disabled = true; e.target.textContent = 'Подключаю…';
  try {
    await api('/api/home', jsonReq('POST', {name: $('#hName').value, ip: $('#hIp').value, token: $('#hToken').value, model: $('#hModel').value}));
    $('#homeModal').hidden = true;
    ['#hName', '#hIp', '#hToken', '#hModel'].forEach((s) => $(s).value = '');
    loadHome();
  } catch (err) { $('#hErr').textContent = errText(err); }
  finally { e.target.disabled = false; e.target.textContent = 'Подключить'; }
};

// ---------- Колонки (Яндекс Станция через Home Assistant) ----------
const SP_STATE = {playing: 'играет', paused: 'пауза', idle: 'ожидание', off: 'выключена', on: 'включена',
  unavailable: 'недоступна', standby: 'ожидание', buffering: 'загрузка'};

async function loadSpeakers() {
  const st = await api('/api/ha');
  $('#haSetup').hidden = st.configured;
  $('#haMain').hidden = !st.configured;
  if (!st.configured) { if (!$('#haUrl').value) $('#haUrl').value = st.url || ''; return; }
  let players;
  try { players = await api('/api/ha/players'); $('#haHint').textContent = ''; }
  catch (e) { $('#haHint').textContent = errText(e); return; }
  $('#haHint').textContent = players.length ? '' : 'Колонок в Home Assistant пока нет';
  const known = new Set(players.map((p) => p.entity_id));
  for (const p of players) {
    let el = document.getElementById('sp-' + p.entity_id);
    if (!el) {
      el = document.createElement('div'); el.id = 'sp-' + p.entity_id; el.className = 'sp';
      $('#spList').appendChild(el);
      spBuild(p, el);
    }
    spUpdate(p, el);
  }
  document.querySelectorAll('#spList .sp').forEach((el) => { if (!known.has(el.id.slice(3))) el.remove(); });
}

function spBuild(p, el) {
  el.innerHTML = `
    <div><h3>${esc(p.name)}</h3><div class="sub muted" style="font-size:13px"><span data-r="state"></span>${p.yandex ? ' · Яндекс' : ''}</div></div>
    <div class="now" data-r="now"></div>
    <div class="tverr" data-r="err"></div>
    <div class="ctrls">
      <button class="ib" data-a="prev">⏮</button><button class="ib" data-a="play">▶</button>
      <button class="ib" data-a="pause">⏸</button><button class="ib" data-a="next">⏭</button>
      <button class="ib" data-a="mute" data-r="mute">🔇</button></div>
    <div class="vol"><span>🔈</span><input type="range" min="0" max="100" data-vol><b data-r="vol">0</b></div>
    <div class="say"><input data-say placeholder="Скажи Алисе: включи музыку / какая погода…">
      <button class="btn" data-a="command">Команда</button><button class="btn ghost" data-a="tts">Произнести</button></div>`;
  const send = async (action, value) => {
    try { await api(`/api/ha/players/${p.entity_id}/${action}`, jsonReq('POST', {value})); el.querySelector('[data-r=err]').textContent = ''; }
    catch (e) { el.querySelector('[data-r=err]').textContent = errText(e); }
    setTimeout(loadSpeakers, 600);
  };
  el.onclick = (e) => {
    const b = e.target.closest('button[data-a]'); if (!b) return;
    const a = b.dataset.a;
    if (a === 'mute') return send('mute', !(el._muted));
    if (a === 'command' || a === 'tts') {
      const inp = el.querySelector('[data-say]'); if (!inp.value.trim()) return;
      send(a, inp.value).then(() => inp.value = ''); return;
    }
    send(a, null);
  };
  el.querySelector('[data-vol]').onchange = (e) => send('volume', e.target.value / 100);
  el.querySelector('[data-vol]').oninput = (e) => el.querySelector('[data-r=vol]').textContent = e.target.value;
  el.querySelector('[data-say]').onkeydown = (e) => { if (e.key === 'Enter') el.querySelector('[data-a=command]').click(); };
}

function spUpdate(p, el) {
  const r = (k) => el.querySelector(`[data-r=${k}]`);
  el.classList.toggle('on', p.state === 'playing');
  r('state').innerHTML = esc(SP_STATE[p.state] || p.state) + (p.state === 'playing' ? '<span class="eq"><i></i><i></i><i></i></span>' : '');
  r('now').textContent = p.title ? [p.title, p.artist].filter(Boolean).join(' — ') : '';
  el._muted = !!p.muted;
  r('mute').style.outline = p.muted ? '2px solid var(--red)' : '';
  const vol = el.querySelector('[data-vol]');
  if (p.volume != null && document.activeElement !== vol) { vol.value = Math.round(p.volume * 100); r('vol').textContent = vol.value; }
}

$('#haSave').onclick = async (e) => {
  e.target.disabled = true; e.target.textContent = 'Проверяю…';
  try {
    await api('/api/ha', jsonReq('PUT', {url: $('#haUrl').value, token: $('#haToken').value}));
    $('#haToken').value = ''; $('#haErr').textContent = '';
    loadSpeakers();
  } catch (err) { $('#haErr').textContent = errText(err); }
  finally { e.target.disabled = false; e.target.textContent = 'Подключить'; }
};
$('#haDisc').onclick = async () => {
  if (!confirm('Отключить Home Assistant от панели? Токен будет удалён.')) return;
  await api('/api/ha', {method: 'DELETE'});
  $('#spList').innerHTML = '';
  loadSpeakers();
};

function refresh() {
  if (!me) return;
  ({overview: loadOverview, devices: loadDevices, log: loadLog, protection: loadProtection, av: loadAv, vpn: loadVpn,
    tv: loadTv, home: loadHome, speakers: loadSpeakers, stats: loadStats, settings: loadSettings})[tab]().catch(console.error);
}
setInterval(() => {
  if (!me) return; if (!$('#modal').hidden || !$('#vpnModal').hidden || !$('#tvModal').hidden || !$('#homeModal').hidden || document.activeElement === $('#logSearch') || document.activeElement?.matches?.('[data-say]')) return; refresh(); }, 5000);

// =====================================================================
//  Общие помощники
// =====================================================================
let me = null;       // текущий пользователь
let scene = null;    // 3D-сцена
let authState = null;

function kpi(v, l, icon, c) {
  return `<div class="kpi glass" style="--c:${c}"><span class="ico"><svg><use href="#${icon}"/></svg></span>
    <div class="v" data-count="${esc(v)}">${esc(v)}</div><div class="l">${esc(l)}</div></div>`;
}
function countUpAll(root) {
  root.querySelectorAll('[data-count]').forEach((el) => {
    const raw = el.dataset.count, m = raw.match(/^(\d+)(.*)$/);
    if (!m || el.dataset.done === raw) return;
    const to = +m[1], from = +(el.dataset.done?.match(/^\d+/)?.[0] || 0), t0 = performance.now();
    el.dataset.done = raw;
    const step = (t) => {
      const k = Math.min(1, (t - t0) / 900), e = 1 - Math.pow(1 - k, 3);
      el.textContent = Math.round(from + (to - from) * e) + m[2];
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}
const ago = (ts) => {
  const s = Math.max(0, Date.now() / 1000 - ts);
  return s < 60 ? 'только что' : s < 3600 ? `${Math.floor(s / 60)} мин назад` : s < 86400 ? `${Math.floor(s / 3600)} ч назад` : new Date(ts * 1000).toLocaleDateString('ru-RU');
};

// =====================================================================
//  Обзор: живая карта + главное
// =====================================================================
let lastQueryId = 0;
async function loadOverview() {
  const [st, devs, threats, settings, v] = await Promise.all([
    api('/api/stats'), api('/api/devices'), api('/api/queries?blocked=true&limit=40'), api('/api/settings'), api('/api/vpn')]);
  devices = devs;
  if (scene) scene.setDevices(devs);
  vpn = v;
  const lvl = settings.levels[settings.level];
  const vpnAct = v.profiles.find((p) => p.id === v.active);
  const h = new Date().getHours();
  $('#heroHello').textContent = (h < 6 ? 'Доброй ночи' : h < 12 ? 'Доброе утро' : h < 18 ? 'Добрый день' : 'Добрый вечер') + (me ? ', ' + me.name.split(' ')[0] : '');
  const bad = v.state === 'down' || settings.level === 'off';
  $('#heroTitle').textContent = v.state === 'down' ? 'VPN упал' : settings.level === 'off' ? 'Защита выключена' : 'Сеть под защитой';
  $('#heroTitle').className = 'hero-title ' + (bad ? 'bad' : 'ok');
  $('#heroSub').textContent = `За сутки остановлено ${st.threats_24h} угроз и ${Math.max(0, st.blocked_24h - st.threats_24h)} реклам и трекеров.`;
  $('#heroChips').innerHTML = `
    <span class="chip ${settings.level === 'off' ? 'red' : 'ok'}"><svg><use href="#i-shield"/></svg>${esc(lvl.title)}</span>
    <span class="chip ${v.state === 'down' ? 'red' : v.state === 'connected' ? 'ok' : ''}"><svg><use href="#i-vpn"/></svg>${v.state === 'connected' && vpnAct ? esc(vpnAct.flag + ' ' + vpnAct.name) : v.state === 'down' ? 'VPN упал' : 'VPN выкл'}</span>
    <span class="chip"><svg><use href="#i-devices"/></svg>${st.devices_online} в сети</span>`;
  $('#kpis').innerHTML = kpi(st.devices_online, 'устройств онлайн', 'i-devices', '#3cf2b0') + kpi(st.queries_24h, 'запросов за сутки', 'i-log', '#4cc9ff')
    + kpi(st.blocked_24h, 'заблокировано', 'i-protect', '#8b5cff') + kpi(st.threats_24h, 'угроз остановлено', 'i-av', '#ff4d6d');
  countUpAll($('#kpis'));
  // группируем одинаковые домены: «сайт · 3 устройства · ×12»
  const groups = new Map();
  for (const q of threats) {
    const g = groups.get(q.domain) || {...q, n: 0, devs: new Set()};
    g.n++; g.devs.add(q.device); g.ts = Math.max(g.ts, q.ts);
    groups.set(q.domain, g);
  }
  const danger = (q) => q.reason === 'malware' || q.reason === 'phishing';
  const list = [...groups.values()].sort((a, b) => danger(b) - danger(a) || b.ts - a.ts).slice(0, 7);
  $('#threatFeed').innerHTML = list.map((q) => `<div class="feed-item"><span class="dotx ${danger(q) ? '' : 'sus'}"></span>
    <div class="t"><b>${esc(q.domain)}</b><span>${esc(REASON[q.reason] || q.reason || '')} · ${q.devs.size === 1 ? esc([...q.devs][0]) : q.devs.size + ' устройства'}${q.n > 1 ? ' · ×' + q.n : ''}</span></div><time>${ago(q.ts)}</time></div>`).join('')
    || '<div class="empty">Угроз не было — тишина 🛡</div>';
  $('#quickLevel').innerHTML = Object.entries(settings.levels).map(([k, x]) => `<button data-lvl="${k}" class="${k === settings.level ? 'on' : ''}">${esc(x.title)}</button>`).join('');
  $('#quickVpn').innerHTML = v.profiles.length
    ? `<select id="qvSel">${v.profiles.map((p) => `<option value="${esc(p.id)}" ${p.id === v.active ? 'selected' : ''}>${p.flag} ${esc(p.name)}</option>`).join('')}</select>
       ${v.active ? '<button class="btn ghost" id="qvOff">Выключить</button>' : '<button class="btn primary" id="qvOn">Включить</button>'}`
    : '<span class="muted">Серверов нет —</span> <button class="link" data-goto="vpn">добавить</button>';
  liveTraffic();
}
$('#quickLevel').onclick = async (e) => {
  const b = e.target.closest('[data-lvl]'); if (!b) return;
  await api('/api/settings', jsonReq('PUT', {level: b.dataset.lvl}));
  toast('Уровень защиты: ' + b.textContent);
  loadOverview();
};
$('#quickVpn').onclick = async (e) => {
  try {
    if (e.target.id === 'qvOn') { e.target.disabled = true; await api('/api/vpn/connect', jsonReq('POST', {id: $('#qvSel').value})); toast('VPN включён'); }
    if (e.target.id === 'qvOff') { await api('/api/vpn/disconnect', {method: 'POST'}); toast('VPN выключен'); }
  } catch (err) { toast(errText(err)); }
  if (e.target.id === 'qvOn' || e.target.id === 'qvOff') loadOverview();
};
$('#quickVpn').onchange = async (e) => {
  if (e.target.id !== 'qvSel' || !vpn.active) return;
  try { await api('/api/vpn/connect', jsonReq('POST', {id: e.target.value})); toast('Сервер VPN сменён'); } catch (err) { toast(errText(err)); }
  loadOverview();
};
$('#quickCheck').onsubmit = async (e) => {
  e.preventDefault();
  const u = $('#quickUrl').value.trim(); if (!u) return;
  $('#quickResult').innerHTML = '<div class="wait"><span class="spinner"></span>Проверяю…</div>';
  try { renderVerdict($('#quickResult'), await api('/api/av/url', jsonReq('POST', {url: u})), true); } catch (err) { $('#quickResult').innerHTML = `<p class="err">${esc(errText(err))}</p>`; }
};

// живой трафик: новые DNS-запросы превращаются в пакеты на 3D-карте
async function liveTraffic() {
  if (!scene) return;
  const rows = await api('/api/queries?limit=60').catch(() => []);
  const fresh = rows.filter((r) => r.id > lastQueryId).reverse();
  const first = lastQueryId === 0;
  if (rows.length) lastQueryId = Math.max(lastQueryId, rows[0].id);
  if (first) return;
  fresh.slice(-40).forEach((r, i) => setTimeout(() => {
    if (r.action === 'blocked' && (r.reason === 'malware' || r.reason === 'phishing')) scene.threat(r.client_ip);
    else scene.packet(r.client_ip, false);
  }, (i / Math.max(fresh.length, 1)) * 4800));
}
// фоновая «жизнь» на демо-данных, чтобы карта не была пустой между запросами
setInterval(() => { if (scene && tab === 'overview' && me && Math.random() < 0.6) scene.packet(null, false); }, 700);

// подписи устройств на карте
function labelsLoop() {
  if (scene && tab === 'overview' && me) {
    const pts = scene.screenPositions();
    const box = $('#nodeLabels');
    const key = (k) => 'nl-' + k.replace(/[^a-z0-9]/gi, '_');
    const seen = new Set();
    for (const p of pts) {
      const id = key(p.key); seen.add(id);
      let el = document.getElementById(id);
      if (!el) { el = document.createElement('div'); el.id = id; el.className = 'nlabel'; box.appendChild(el); }
      el.textContent = p.data.display_name || p.data.ip;
      el.classList.toggle('off', p.data.online === false);
      el.style.left = p.x + 'px'; el.style.top = p.y + 'px';
      el.style.opacity = p.hovered ? 1 : '';
    }
    box.querySelectorAll('.nlabel').forEach((el) => { if (!seen.has(el.id)) el.remove(); });
    const hv = scene.hovered, tip = $('#nodeTip');
    if (hv) {
      const d = hv.data;
      tip.innerHTML = `<b>${esc(d.display_name)}</b><br><span class="muted">${esc(TYPE_LABEL[d.type] || '')}</span><br>${esc(d.ip || '')}${d.vendor ? ' · ' + esc(d.vendor) : ''}<br>${d.online ? '🟢 в сети' : '⚪ не в сети'}`;
      tip.hidden = false;
    } else tip.hidden = true;
  }
  setTimeout(() => requestAnimationFrame(labelsLoop), 50);
}
addEventListener('pointermove', (e) => { const t = $('#nodeTip'); t.style.left = e.clientX + 'px'; t.style.top = e.clientY + 'px'; }, {passive: true});
$('#heroStage').addEventListener('click', () => { if (scene?.hovered) { go('devices'); } });

// =====================================================================
//  Антивирус
// =====================================================================
const VERDICT = {
  safe: ['✅', 'Безопасно', 'Угроз не найдено.'],
  suspicious: ['⚠️', 'Подозрительно', 'Будь осторожен: не вводи пароли и коды.'],
  danger: ['⛔', 'Опасно!', 'Не открывай и ничего не вводи.'],
  unknown: ['❔', 'Неизвестно', 'Не удалось проверить.'],
};
function renderVerdict(box, r, compact = false) {
  const [ico, title, sub] = VERDICT[r.verdict] || VERDICT.unknown;
  const findings = r.findings.filter((f) => f.level !== 'unknown' || r.verdict === 'unknown');
  box.innerHTML = `<div class="verdict glass ${r.verdict}" style="${compact ? 'margin-top:12px;padding:16px;gap:14px' : ''}">
    ${r.verdict === 'danger' && !compact ? '<video src="/static/blocked.mp4" autoplay muted loop playsinline></video>' : `<div class="vbadge" style="${compact ? 'width:56px;height:56px;font-size:26px;border-radius:18px' : ''}">${ico}</div>`}
    <div><h3>${title}</h3><div class="target">${esc(r.target)}${r.sha256 ? ' · sha256 ' + r.sha256.slice(0, 16) + '…' : ''}</div>
    ${findings.length ? `<ul>${findings.map((f) => `<li><b>${esc(f.source)}</b><span>${esc(f.text)}</span></li>`).join('')}</ul>` : `<span class="muted">${sub}</span>`}</div></div>`;
}
async function loadAv() {
  const [hist, keys] = await Promise.all([api('/api/av/history?limit=30'), api('/api/av/keys')]);
  $('#avHistory').innerHTML = hist.filter((h) => h.kind !== 'domain' || h.verdict === 'danger').map((h) => `<div class="feed-item">
    <span class="dotx ${h.verdict === 'danger' ? '' : h.verdict === 'suspicious' ? 'sus' : 'ok'}"></span>
    <div class="t"><b>${esc(h.target)}</b><span>${{url: 'ссылка', file: 'файл', domain: 'сторож DNS'}[h.kind]} · ${esc(VERDICT[h.verdict][1])}</span></div><time>${ago(h.ts)}</time></div>`).join('')
    || '<div class="empty">Проверок ещё не было</div>';
  const eng = (name, on, note) => `<div class="engine"><div><b>${name}</b><div class="muted small">${note}</div></div><span class="tag ${on ? '' : 'sus'}">${on ? 'активен' : 'не подключён'}</span></div>`;
  $('#avEngines').innerHTML = eng('Базы и эвристики HomeGuard', true, 'подделки банков, punycode, двойные расширения')
    + eng('Google Safe Browsing', keys.gsb, 'ссылки + сторож всех новых сайтов в сети')
    + eng('VirusTotal', keys.vt, '70+ антивирусов, файлы по хэшу')
    + eng('ClamAV', keys.clamav, 'локальная проверка файлов')
    + (me?.role === 'owner' ? '<p class="muted small" style="margin-top:12px">Ключи — в <button class="link" data-goto="settings">Настройках</button>.</p>' : '');
}
$('#avUrlForm').onsubmit = async (e) => {
  e.preventDefault();
  const u = $('#avUrl').value.trim(); if (!u) return;
  $('#avResult').innerHTML = '<div class="verdict glass"><div class="vbadge"><span class="spinner"></span></div><div><h3>Проверяю…</h3><div class="target">' + esc(u) + '</div></div></div>';
  try { renderVerdict($('#avResult'), await api('/api/av/url', jsonReq('POST', {url: u}))); } catch (err) { $('#avResult').innerHTML = `<p class="err">${esc(errText(err))}</p>`; }
  loadAv();
};
async function checkFile(f) {
  if (!f) return;
  if (f.size > 32 * 1024 * 1024) return toast('Файл больше 32 МБ');
  $('#avResult').innerHTML = `<div class="verdict glass"><div class="vbadge"><span class="spinner"></span></div><div><h3>Сканирую файл…</h3><div class="target">${esc(f.name)}</div></div></div>`;
  try {
    renderVerdict($('#avResult'), await api('/api/av/file', {method: 'POST', body: f, headers: {'X-Filename': encodeURIComponent(f.name)}}));
  } catch (err) { $('#avResult').innerHTML = `<p class="err">${esc(errText(err))}</p>`; }
  loadAv();
}
$('#avFile').onchange = (e) => checkFile(e.target.files[0]);
['dragenter', 'dragover'].forEach((ev) => $('#avDrop').addEventListener(ev, (e) => { e.preventDefault(); $('#avDrop').classList.add('over'); }));
['dragleave', 'drop'].forEach((ev) => $('#avDrop').addEventListener(ev, (e) => { e.preventDefault(); $('#avDrop').classList.remove('over'); }));
$('#avDrop').addEventListener('drop', (e) => checkFile(e.dataTransfer.files[0]));

// =====================================================================
//  Настройки
// =====================================================================
const ROLE = {owner: 'Владелец сети 👑', member: 'Участник', pending: 'Ждёт подтверждения'};
async function loadSettings() {
  $('#profName').textContent = me.name;
  $('#profRole').textContent = ROLE[me.role] + (me.username ? ' · @' + me.username : '');
  $('#profAvatar').textContent = (me.name || '?')[0].toUpperCase();
  const st = await api('/api/auth/state');
  $('#botInfo').innerHTML = st.bot_username ? `Бот: <a href="https://t.me/${esc(st.bot_username)}" target="_blank" rel="noopener">@${esc(st.bot_username)}</a> — присылает тревоги и пускает в панель.` : 'Бот не настроен';
  document.querySelectorAll('.owner-only').forEach((el) => el.hidden = me.role !== 'owner');
  if (me.role !== 'owner') return;
  const users = await api('/api/users');
  $('#usersList').innerHTML = users.map((u) => `<div class="user-row" data-id="${u.tg_id}"><span class="avatar">${esc((u.name || '?')[0].toUpperCase())}</span>
    <div class="t"><b>${esc(u.name)}</b><small>${u.username ? '@' + esc(u.username) + ' · ' : ''}${ROLE[u.role]}</small></div>
    ${u.role === 'owner' ? '' : `<button class="btn danger" data-del="${u.tg_id}">Удалить</button>`}</div>`).join('');
}
$('#usersList').onclick = async (e) => {
  const b = e.target.closest('[data-del]'); if (!b || !confirm('Удалить пользователя? Его сессии закроются.')) return;
  await api('/api/users/' + b.dataset.del, {method: 'DELETE'});
  loadSettings();
};
$('#avKeys').onsubmit = async (e) => {
  e.preventDefault();
  const body = {};
  if ($('#gsbKey').value.trim()) body.gsb = $('#gsbKey').value.trim();
  if ($('#vtKey').value.trim()) body.vt = $('#vtKey').value.trim();
  const k = await api('/api/av/keys', jsonReq('PUT', body));
  $('#gsbKey').value = $('#vtKey').value = '';
  $('#avKeysMsg').textContent = `Safe Browsing: ${k.gsb ? '✓' : '—'} · VirusTotal: ${k.vt ? '✓' : '—'}`;
};
$('#logoutBtn').onclick = async () => { await api('/api/auth/logout', {method: 'POST'}); location.reload(); };

// =====================================================================
//  Знакомство и вход через Telegram
// =====================================================================
const STEPS = document.querySelectorAll('.onb-step');
let step = 0, pollTimer = null;

function splitText(el) {
  let i = 0;
  const walk = (node, cls) => {
    [...node.childNodes].forEach((n) => {
      if (n.nodeType === 3) {
        const frag = document.createDocumentFragment();
        for (const word of n.textContent.split(/(\s+)/)) {
          if (!word) continue;
          if (/^\s+$/.test(word)) { frag.append(word); continue; }
          const w = document.createElement('span'); w.style.whiteSpace = 'nowrap'; w.style.display = 'inline-block';
          for (const ch of word) { const s = document.createElement('span'); s.className = 'ch ' + cls; s.style.setProperty('--i', i++); s.textContent = ch; w.append(s); }
          frag.append(w);
        }
        n.replaceWith(frag);
      } else if (n.nodeType === 1 && n.tagName !== 'BR') {
        const c = [...n.classList].filter((x) => x.startsWith('grad')).join(' ');
        if (c) { n.classList.remove(...c.split(' ')); }
        walk(n, c || cls);
      }
    });
  };
  walk(el, '');
}
document.querySelectorAll('[data-split]').forEach(splitText);
$('#onbDots').innerHTML = [...STEPS].map((_, i) => `<i data-i="${i}"></i>`).join('');
$('#onbDots').onclick = (e) => { const d = e.target.closest('[data-i]'); if (d) showStep(+d.dataset.i); };

function showStep(i) {
  step = Math.max(0, Math.min(STEPS.length - 1, i));
  STEPS.forEach((s, k) => {
    s.classList.toggle('on', k === step);
    // перезапуск анимации букв
    if (k === step) s.querySelectorAll('.ch').forEach((c) => { c.style.animation = 'none'; c.offsetWidth; c.style.animation = ''; });
  });
  document.querySelectorAll('#onbDots i').forEach((d, k) => d.classList.toggle('on', k === step));
  $('#onbBack').style.visibility = step === 0 || step === STEPS.length - 1 && authState?.has_owner ? 'hidden' : 'visible';
  $('#onbNext').hidden = step === STEPS.length - 1;
  $('#onbNext').innerHTML = (step === 0 ? 'Начать' : 'Дальше') + ' <svg><use href="#i-arrow"/></svg>';
  $('#onbSkip').hidden = step === STEPS.length - 1;
  const v = STEPS[2].querySelector('video');
  if (step === 2) v.play().catch(() => {}); else v.pause();
  if (scene) { scene.setMode('intro'); scene.setStep(step); scene.setFocus($('#onbStage')); scene.setDim(0); }
  if (step === STEPS.length - 1) { try { localStorage.setItem('hg_intro_seen', '1'); } catch {} prepareLogin(); }
}
$('#onbNext').onclick = () => showStep(step + 1);
$('#onbBack').onclick = () => showStep(step - 1);
$('#onbSkip').onclick = () => showStep(STEPS.length - 1);
addEventListener('keydown', (e) => {
  if ($('#onb').hidden || e.target.matches('input,textarea')) return;
  if (e.key === 'ArrowRight' || e.key === 'Enter') showStep(step + 1);
  if (e.key === 'ArrowLeft') showStep(step - 1);
});

async function prepareLogin() {
  clearInterval(pollTimer);
  authState = await api('/api/auth/state');
  $('#loginEyebrow').textContent = authState.has_owner ? 'Вход' : '05 · Последний шаг';
  $('#welcome').hidden = true;
  if (!authState.bot_configured) {
    $('#botSetup').hidden = false; $('#loginBox').hidden = true;
    if (authState.has_owner) $('#botErr').textContent = 'Бот не настроен на сервере — проверь HG_TG_TOKEN.';
    return;
  }
  $('#botSetup').hidden = true; $('#loginBox').hidden = false;
  $('#loginText').innerHTML = authState.has_owner
    ? 'Нажми кнопку — откроется бот. Жми <b>Start</b>. Если ты здесь впервые, владелец сети получит запрос.'
    : 'Нажми кнопку — откроется бот. Жми <b>Start</b>: первый вошедший становится <b>владельцем сети</b>.';
  $('#loginErr').textContent = ''; $('#loginWait').hidden = true;
  let r;
  try { r = await api('/api/auth/start', jsonReq('POST', {kind: 'web'})); } catch (e) { $('#loginErr').textContent = errText(e); return; }
  $('#tgLink').href = r.link;
  try {
    const qr = qrcode(0, 'M'); qr.addData(r.link); qr.make();
    $('#qr').innerHTML = qr.createSvgTag({cellSize: 4, margin: 0, scalable: true});
  } catch { $('#qr').innerHTML = ''; }
  pollTimer = setInterval(async () => {
    let p;
    try { p = await api('/api/auth/poll?nonce=' + encodeURIComponent(r.nonce)); } catch { return; }
    if (p.status === 'pending_owner') { $('#loginWait').hidden = false; $('#loginWaitText').textContent = 'Владелец сети получил запрос в Telegram — ждём…'; }
    if (p.status === 'denied') { clearInterval(pollTimer); $('#loginWait').hidden = true; $('#loginErr').textContent = 'Владелец отклонил вход.'; }
    if (p.status === 'expired') { prepareLogin(); }
    if (p.status === 'approved') {
      clearInterval(pollTimer);
      const st = await api('/api/auth/state');
      $('#loginBox').hidden = true; $('#welcome').hidden = false;
      $('#welcomeName').textContent = st.user.name.split(' ')[0];
      if (scene) scene.celebrate();
      setTimeout(() => enterApp(st.user), 1900);
    }
  }, 1500);
}
$('#tgLink').addEventListener('click', () => { $('#loginWait').hidden = false; $('#loginWaitText').textContent = 'Ждём, когда нажмёшь Start в боте…'; });
$('#botSave').onclick = async (e) => {
  e.target.disabled = true; $('#botErr').textContent = '';
  try { await api('/api/auth/bot', jsonReq('PUT', {token: $('#botToken').value})); $('#botToken').value = ''; toast('Бот подключён'); prepareLogin(); }
  catch (err) { $('#botErr').textContent = errText(err); }
  e.target.disabled = false;
};

function showLogin() {
  if (!$('#onb').hidden) return;
  me = null;
  $('#app').hidden = true; $('#onb').hidden = false;
  let seen = false; try { seen = localStorage.getItem('hg_intro_seen') === '1'; } catch {}
  showStep(seen ? STEPS.length - 1 : 0);
}

function enterApp(user) {
  me = user;
  clearInterval(pollTimer);
  $('#onb').hidden = true; $('#app').hidden = false;
  $('#meName').textContent = user.name; $('#meRole').textContent = ROLE[user.role] || '';
  $('#meAvatar').textContent = (user.name || '?')[0].toUpperCase();
  if (scene) scene.setMode('dash');
  go('overview');
  api('/api/devices').then((d) => { devices = d; if (scene) scene.setDevices(d); }).catch(() => {});
}

async function boot() {
  try {
    if (!window.HGScene) await new Promise((res) => { addEventListener('hg-scene-ready', res, {once: true}); setTimeout(res, 4000); });
    if (window.HGScene) scene = window.HGScene.createScene($('#bg3d'));
  } catch (e) { console.warn('3D недоступно:', e); }
  if (scene) scene.setFocus($('#onbStage'));
  labelsLoop();
  authState = await api('/api/auth/state');
  if (authState.user) enterApp(authState.user); else showLogin();
}
boot();

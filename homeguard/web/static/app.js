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
  if (!r.ok) throw new Error(await r.text());
  return r.json();
};
let devices = [];
let tab = 'devices';

document.querySelectorAll('#tabs button').forEach((b) => b.onclick = () => {
  tab = b.dataset.tab;
  document.querySelectorAll('#tabs button').forEach((x) => x.classList.toggle('active', x === b));
  document.querySelectorAll('main > section').forEach((s) => s.hidden = s.id !== 'tab-' + tab);
  refresh();
});

function iconSvg(type, self) {
  const badge = self ? '<span class="badge"><svg viewBox="0 0 24 24" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12 5 5 9-10"/></svg></span>' : '';
  return `<div class="ico"><svg viewBox="0 0 24 24">${ICONS[type] || ICONS.unknown}</svg>${badge}</div>`;
}

async function loadDevices() {
  devices = await api('/api/devices');
  const on = devices.filter((d) => d.online).length;
  $('#devSummary').textContent = `В сети: ${on} из ${devices.length}`;
  $('#devGrid').innerHTML = devices.map((d) => `
    <div class="card ${d.online ? 'on' : ''}" data-mac="${esc(d.mac)}">
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
}

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

async function loadProtection() {
  const s = await api('/api/settings');
  $('#levels').innerHTML = Object.entries(s.levels).map(([k, v]) => `
    <div class="level ${k === s.level ? 'active' : ''}" data-level="${k}"><h3>${esc(v.title)}</h3><p>${esc(v.description)}</p></div>`).join('');
}
$('#levels').onclick = async (e) => {
  const el = e.target.closest('.level');
  if (!el) return;
  await api('/api/settings', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({level: el.dataset.level})});
  loadProtection();
};

async function loadStats() {
  const s = await api('/api/stats');
  const tile = (v, l) => `<div class="tile"><div class="v">${v}</div><div class="l">${l}</div></div>`;
  $('#statTiles').innerHTML = tile(s.queries_24h, 'запросов за 24 ч') + tile(s.blocked_24h, 'заблокировано') +
    tile(`${s.devices_online}/${s.devices_total}`, 'устройств в сети') +
    tile(s.queries_24h ? Math.round(100 * s.blocked_24h / s.queries_24h) + '%' : '0%', 'доля блокировок');
  const bars = (arr, extra) => arr.map((r) => `<div class="bar"><span>${esc(r.domain)}${extra ? ' <span class="muted">' + esc(REASON[r.reason] || '') + '</span>' : ''}</span><b>${r.n}</b></div>`).join('') || '<span class="muted">Нет данных</span>';
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
    b.innerHTML = `<span class="big">🛡 VPN включён</span><span>${esc(act ? act.flag + ' ' + act.name : '')}</span><span class="muted" id="vpnIp"></span>`;
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

function refresh() {
  ({devices: loadDevices, log: loadLog, protection: loadProtection, vpn: loadVpn, tv: loadTv, stats: loadStats})[tab]().catch(console.error);
}
refresh();
setInterval(() => { if (!$('#modal').hidden || !$('#vpnModal').hidden || !$('#tvModal').hidden || document.activeElement === $('#logSearch')) return; refresh(); }, 5000);

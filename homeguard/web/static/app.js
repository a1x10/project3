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

function refresh() {
  ({devices: loadDevices, log: loadLog, protection: loadProtection, stats: loadStats})[tab]().catch(console.error);
}
refresh();
setInterval(() => { if (!$('#modal').hidden || document.activeElement === $('#logSearch')) return; refresh(); }, 5000);

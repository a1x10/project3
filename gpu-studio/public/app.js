const $ = s => document.querySelector(s);
const api = async (url, body) => {
  const r = await fetch(url, body === undefined ? {} : { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || 'Ошибка ' + r.status);
  return j;
};
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

let mode = 'register', kind = 'video', timer = null, lastJobsKey = '';

// ---------- вход / регистрация ----------
document.querySelectorAll('.tab').forEach(b => b.onclick = () => {
  mode = b.dataset.tab;
  document.querySelectorAll('.tab').forEach(x => x.classList.toggle('active', x === b));
  $('#authBtn').textContent = mode === 'register' ? 'Создать аккаунт' : 'Войти';
  $('#adultRow').classList.toggle('hidden', mode !== 'register');
  $('#inviteRow').classList.toggle('hidden', mode !== 'register' || !window.inviteRequired);
  $('#authErr').textContent = '';
});
$('#authForm').onsubmit = async e => {
  e.preventDefault();
  const f = new FormData(e.target);
  try {
    const body = { username: f.get('username'), password: f.get('password'), invite: f.get('invite'), adult: f.get('adult') === 'on' };
    const { user } = await api('/api/' + mode, body);
    showApp(user);
  } catch (err) { $('#authErr').textContent = err.message; }
};
$('#logout').onclick = async () => { await api('/api/logout', {}); location.reload(); };

// ---------- генерация ----------
document.querySelectorAll('.kindBtn').forEach(b => b.onclick = () => {
  kind = b.dataset.kind;
  document.querySelectorAll('.kindBtn').forEach(x => x.classList.toggle('active', x === b));
  $('#prompt').placeholder = kind === 'video' ? 'Введите промт для генерации видео…' : 'Введите промт для генерации фото…';
});
$('#genForm').onsubmit = async e => {
  e.preventDefault();
  $('#genErr').textContent = '';
  $('#genBtn').disabled = true;
  try {
    await api('/api/jobs', { kind, prompt: $('#prompt').value });
    $('#prompt').value = '';
    refresh();
  } catch (err) { $('#genErr').textContent = err.message; }
  $('#genBtn').disabled = false;
};
$('#startBtn').onclick = async () => {
  $('#startBtn').disabled = true;
  try { await api('/api/start', {}); } catch (err) { $('#genErr').textContent = err.message; }
  refresh();
};

const PHASE = {
  off: ['Сервер выключен', 'off'], starting: ['Запуск сервера', 'busy'], loading: ['Загрузка модели', 'busy'],
  ready: ['Сервер готов', 'on'], generating: ['Идёт генерация', 'busy'], stopping: ['Выключение', 'busy'],
};

function renderStatus(s) {
  const [title, cls] = PHASE[s.phase] || [s.phase, 'busy'];
  $('#phase').textContent = title;
  $('#statusMsg').textContent = s.error && s.phase === 'off' ? s.message : s.message;
  $('#dot').className = 'dot ' + (s.error && s.phase === 'off' ? 'err' : cls);
  $('#progress').classList.toggle('hidden', cls !== 'busy');
  $('#startBtn').classList.toggle('hidden', s.phase !== 'off');
  $('#startBtn').disabled = false;
  const parts = [`GPU: ${s.gpu}`, `${s.creditsPerHour} кр/час`];
  if (s.model) parts.push('модель: ' + s.model);
  if (s.queueLength) parts.push(`в очереди: ${s.queueLength}`);
  if (s.idleLeft !== null) parts.push(`выключится через ${s.idleLeft} с без запросов`);
  if (s.phase === 'off') parts.push('сервер запустится сам, когда вы отправите промт');
  if (s.mock) parts.push('ТЕСТОВЫЙ РЕЖИМ');
  $('#meta').textContent = parts.join(' · ');
}

function jobCard(j) {
  let media, badge;
  if (j.status === 'done') {
    const u = j.urls[0];
    const isVideo = j.kind === 'video' || /\.(mp4|webm|mov)(\?|$)/i.test(u);
    media = isVideo ? `<video src="${esc(u)}" controls loop playsinline></video>` : `<img src="${esc(u)}" alt="">`;
    badge = '<span class="badge done">Генерация завершена</span>';
  } else if (j.status === 'failed') {
    media = `<div>⚠️<br>${esc(j.error || 'Ошибка')}</div>`;
    badge = '<span class="badge failed">Ошибка</span>';
  } else if (j.status === 'running') {
    media = '<div><div class="spinner"></div>Генерируется…</div>';
    badge = '<span class="badge running">Генерация</span>';
  } else {
    media = `<div><div class="spinner"></div>Очередь: ${j.position ?? '…'}</div>`;
    badge = `<span class="badge">В очереди #${j.position ?? '…'}</span>`;
  }
  const links = j.status === 'done' ? j.urls.map((u, i) => `<a href="${esc(u)}" target="_blank" rel="noopener" download>Скачать${j.urls.length > 1 ? ' ' + (i + 1) : ''}</a>`).join(' ') : '';
  return `<div class="job"><div class="media">${media}</div><div class="body">${badge} ${j.kind === 'video' ? '🎬' : '🖼'}<div class="p">${esc(j.prompt)}</div>${links}</div></div>`;
}

async function refresh() {
  try {
    const [s, { jobs }] = await Promise.all([api('/api/status'), api('/api/jobs')]);
    renderStatus(s);
    const key = JSON.stringify(jobs.map(j => [j.id, j.status, j.position]));
    if (key !== lastJobsKey) {   // перерисовываем только при изменениях, чтобы видео не сбрасывалось
      lastJobsKey = key;
      $('#jobs').innerHTML = jobs.length ? jobs.map(jobCard).join('') : '<p class="rules">Пока пусто. Напишите промт выше.</p>';
    }
  } catch (e) { if (/Войдите/.test(e.message)) location.reload(); }
}

function showApp(user) {
  $('#auth').classList.add('hidden');
  $('#app').classList.remove('hidden');
  $('#who').classList.remove('hidden');
  $('#uname').textContent = user.username;
  refresh();
  clearInterval(timer); timer = setInterval(refresh, 2000);
}

(async () => {
  const [{ user }, cfg] = await Promise.all([api('/api/me'), api('/api/config')]);
  window.inviteRequired = cfg.inviteRequired;
  $('#inviteRow').classList.toggle('hidden', !cfg.inviteRequired);
  user ? showApp(user) : $('#auth').classList.remove('hidden');
})();

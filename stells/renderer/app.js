// STELLS — интерфейс приложения: заставка, регистрация, мастер настройки, панель управления.
import { BOARDS, FAMILY_FILTERS, OS_LIST, MODEL_TYPES, USAGES, SUPPORT } from './data.js';
import { link } from './link.js';
import { vision } from './vision.js';
import { openIDE } from './ide.js';
import { icon } from './icons.js';
import { logo, wordmark } from './brand.js';
import { h, toast, modal, mountDrone, mountCar, mountRobot, mountCameras, mountWol } from './panels.js';

const api = window.stells;
const app = document.getElementById('app');
let cfg = {};
let info = {};
let scene3d = null;
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const save = async (p) => (cfg = await api.config.set(p));

// ---------------------------------------------------------------- оболочка
document.getElementById('tbBrand').insertAdjacentHTML('afterbegin', logo(20));
document.querySelectorAll('[data-win]').forEach((b) => (b.onclick = () => api.win[b.dataset.win]()));
const EXT = { wa: SUPPORT.whatsappUrl, tg: SUPPORT.telegramUrl, creator: SUPPORT.creatorUrl };
document.addEventListener('click', (e) => { const a = e.target.closest('[data-ext]'); if (a) { e.preventDefault(); api.openExternal(EXT[a.dataset.ext] || a.dataset.ext); } });

function updateStatus() {
  const s = document.getElementById('tbStatus');
  if (!cfg.registered) { s.innerHTML = ''; return; }
  s.innerHTML = `<span class="tchip">${icon('cpu', 13)}<span class="dot ${link.state === 'online' ? 'on' : link.state === 'connecting' ? 'wait' : ''}"></span>${esc(link.label())}</span>
    <span class="tchip">${icon('scan-eye', 13)}<span class="dot ${vision.source ? 'on' : ''}"></span>${vision.source ? vision.fps + ' FPS' : 'Зрение выкл'}</span>
    <button class="tchip kbd-btn" id="cmdkBtn" title="Командная палитра">${icon('command', 13)} K</button>`;
  s.querySelector('#cmdkBtn').onclick = openPalette;
}
link.addEventListener('state', updateStatus);
vision.addEventListener('stopped', updateStatus);
vision.addEventListener('started', updateStatus);

let current = null;
function show(el) {
  const old = current;
  if (old) { old.classList.add('leave'); setTimeout(() => old.remove(), 450); }
  app.appendChild(el);
  current = el;
  updateStatus();
  return el;
}
const STEP_NAMES = ['Старт', 'Профиль', 'Плата', 'ОС', 'Модель', 'Установка', 'Зрение', 'Режим'];
function stepsBar(n) {
  return `<ol class="stepper">${STEP_NAMES.map((t, i) => `<li class="${i < n ? 'done' : i === n ? 'cur' : ''}"><span class="sn">${i < n ? icon('check', 12) : i + 1}</span><span class="st">${t}</span></li>`).join('')}</ol>`;
}

function greeting() {
  const hr = new Date().getHours();
  return hr >= 5 && hr < 12 ? 'Доброе утро' : hr >= 12 && hr < 17 ? 'Добрый день' : hr >= 17 && hr < 23 ? 'Добрый вечер' : 'Доброй ночи';
}
function speak(text) {
  if (!cfg.voice || !('speechSynthesis' in window)) return;
  try {
    const u = new SpeechSynthesisUtterance(text);
    u.lang = 'ru-RU'; u.rate = 1; u.pitch = 1;
    const v = speechSynthesis.getVoices().find((x) => x.lang?.startsWith('ru'));
    if (v) u.voice = v;
    speechSynthesis.speak(u);
  } catch { /* без голоса */ }
}

// ---------------------------------------------------------------- 0. заставка (каждый запуск, 5 секунд)
async function splash() {
  scene3d?.setMode('splash');
  const name = cfg.registered ? cfg.user.name : '';
  const g = name ? `${greeting()}, ${esc(name)}!` : 'Добро пожаловать';
  const el = show(h(`<section class="screen splash">
    <div class="splash-mark">${logo(112, { animated: true })}</div>
    ${wordmark('xl')}
    <div class="greet">${g}</div>
    <div class="sub">Передовые ИИ-модели и машинное зрение для ваших плат</div>
    <div class="loader"><div class="bar"><i></i></div><div class="lt"><span id="lt">Загрузка ядра…</span><span id="lp">0%</span></div></div>
    <div class="splash-foot">v${esc(info.version)} · проект Алексея · ${esc({ win32: 'Windows', darwin: 'macOS', linux: 'Linux' }[info.platform] || info.platform)}</div>
  </section>`));
  if (name) speak(`${greeting()}, ${name}. Добро пожаловать в Стеллс.`);
  const stages = ['Загрузка ядра…', 'Инициализация 3D-движка…', 'Проверка SLT-ключа…', 'Запуск машинного зрения…', 'Подключение к плате…', 'Готово'];
  const bar = el.querySelector('.bar i'), lt = el.querySelector('#lt'), lp = el.querySelector('#lp');
  const T = 5000, t0 = performance.now();
  await new Promise((res) => {
    const f = () => {
      const k = Math.min(1, (performance.now() - t0) / T), e = 1 - Math.pow(1 - k, 2);
      bar.style.width = e * 100 + '%'; lp.textContent = Math.round(e * 100) + '%';
      lt.textContent = stages[Math.min(stages.length - 1, Math.floor(e * stages.length))];
      k < 1 ? requestAnimationFrame(f) : res();
    };
    f();
  });
}

// ---------------------------------------------------------------- 1. приветствие
function welcome() {
  scene3d?.setMode('core');
  document.body.classList.remove('in-dash');
  const el = show(h(`<section class="screen"><div class="card glass hero">
    ${stepsBar(0)}
    <div class="hero-grid"><div class="hero-l">
    <span class="pill">${icon('sparkles', 14)} Проект STELLS</span>
    <h1>Пройдите регистрацию для получения доступа к нашим <span class="grad">передовым моделям</span></h1>
    <p class="lead">от проекта STELLS, разработанным Алексеем. LLM, VLM, машинное зрение и управление платами — в одном приложении.</p>
    <div class="hero-cta"><button class="btn primary xl" id="go">Продолжить ${icon('arrow-right', 18)}</button><span class="muted small">Регистрация занимает меньше минуты</span></div>
    </div>
    <div class="feats">
      <div class="feat"><i class="fi">${icon('brain-circuit', 20)}</i><b>6 типов моделей</b><span>LLM, LM, CV, VLM, SLM, LMM</span></div>
      <div class="feat"><i class="fi">${icon('circuit-board', 20)}</i><b>180+ плат</b><span>Raspberry Pi, Banana Pi, ODROID, Arduino, NanoPi, Jetson…</span></div>
      <div class="feat"><i class="fi">${icon('scan-eye', 20)}</i><b>Машинное зрение</b><span>Локально на ПК и на плате</span></div>
      <div class="feat"><i class="fi">${icon('gamepad-2', 20)}</i><b>Пульты управления</b><span>Дроны, машины, роботы, камеры, WOL</span></div>
    </div></div>
  </div></section>`));
  el.querySelector('#go').onclick = () => { scene3d?.pulse(); register(); };
}

// ---------------------------------------------------------------- 2. регистрация
function register() {
  const el = show(h(`<section class="screen"><div class="card narrow glass">
    ${stepsBar(1)}
    <div class="eyebrow">Регистрация</div>
    <h2>Как к вам обращаться?</h2>
    <p class="lead">Имя и номер нужны для доступа к моделям и для связи службы поддержки.</p>
    <div class="field"><label>Имя</label><input class="input" id="rName" placeholder="Алексей" autocomplete="given-name" value="${esc(cfg.user?.name)}"></div>
    <div class="field"><label>Номер телефона</label><input class="input" id="rPhone" placeholder="+7 7__ ___ __ __" inputmode="tel" value="${esc(cfg.user?.phone)}"></div>
    <label class="check"><input type="checkbox" id="rAuto" checked> Запускать STELLS при включении компьютера</label>
    <div class="actions"><button class="btn ghost" id="back">Назад</button><span class="spacer"></span><button class="btn primary" id="go">Продолжить<span class="shine"></span></button></div>
  </div></section>`));
  const ph = el.querySelector('#rPhone');
  ph.addEventListener('input', () => {
    let d = ph.value.replace(/\D/g, '');
    if (d.startsWith('8')) d = '7' + d.slice(1);
    if (d && !d.startsWith('7') && d.length <= 10) d = '7' + d;
    d = d.slice(0, 11);
    const p = [d.slice(0, 1), d.slice(1, 4), d.slice(4, 7), d.slice(7, 9), d.slice(9, 11)];
    ph.value = d ? `+${p[0]}${p[1] ? ' ' + p[1] : ''}${p[2] ? ' ' + p[2] : ''}${p[3] ? ' ' + p[3] : ''}${p[4] ? ' ' + p[4] : ''}` : '';
  });
  el.querySelector('#back').onclick = welcome;
  el.querySelector('#go').onclick = async () => {
    const name = el.querySelector('#rName').value.trim(), phone = ph.value.trim();
    el.querySelector('#rName').classList.toggle('err', name.length < 2);
    ph.classList.toggle('err', phone.replace(/\D/g, '').length < 10);
    if (name.length < 2 || phone.replace(/\D/g, '').length < 10) return toast('Введите имя и полный номер телефона', 'err');
    await save({ user: { name, phone }, autostart: el.querySelector('#rAuto').checked });
    toast(`Приятно познакомиться, ${name}!`, 'ok');
    boardStep();
  };
  el.querySelector('#rName').focus();
}

// ---------------------------------------------------------------- 3. выбор платы
function boardStep() {
  scene3d?.setMode('board');
  document.body.classList.remove('in-dash');
  let fam = 'Все', q = '', sel = cfg.board?.id || null;
  const el = show(h(`<section class="screen"><div class="card glass" style="height:100%">
    ${stepsBar(2)}
    <div class="row"><div><div class="eyebrow">Шаг 1 из 4</div><h2>Выберите плату</h2></div><span class="spacer"></span>
      <label class="search">${icon('search', 16)}<input class="input" id="bq" placeholder="Поиск: Raspberry Pi 5, ODROID-N2+, Nano ESP32…"></label></div>
    <div class="chips" id="chips">${FAMILY_FILTERS.map((f) => `<button class="chip ${f === 'Все' ? 'on' : ''}" data-f="${esc(f)}">${f === 'Все' ? 'No filtering — показать все' : esc(f)}</button>`).join('')}</div>
    <div class="list" id="blist"></div>
    <div class="sel-bar"><div class="what" id="bwhat">Плата не выбрана</div><span class="spacer"></span>
      <button class="btn ghost" id="back">Назад</button><button class="btn primary" id="go" disabled>Продолжить<span class="shine"></span></button></div>
  </div></section>`));
  const list = el.querySelector('#blist');
  const KIND = { linux: 'LINUX', mcu: 'MCU', x86: 'x86', router: 'ROUTER' };
  const render = () => {
    const ql = q.toLowerCase();
    const items = BOARDS.filter((b) => (fam === 'Все' || b.family === fam) && (!ql || (b.name + ' ' + b.note + ' ' + b.group).toLowerCase().includes(ql)));
    const groups = new Map();
    for (const b of items) { const k = /^\d — /.test(b.group) ? `${b.family} · ${b.group.replace(/^\d — /, '')}` : b.family; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(b); }
    list.innerHTML = items.length ? '' : '<p class="muted">Ничего не найдено. Если вашей платы нет — напишите в поддержку.</p>';
    for (const [k, arr] of groups) {
      list.appendChild(h(`<div class="group-title">${esc(k)}</div>`));
      const grid = h('<div class="grid"></div>');
      for (const b of arr) {
        const o = h(`<button class="opt ${b.id === sel ? 'on' : ''}"><span class="tag">${KIND[b.kind]}</span><b>${esc(b.name)}</b><span>${esc(b.note || b.group)}</span></button>`);
        o.onclick = () => { sel = b.id; scene3d?.pulse(); render(); upd(); };
        o.ondblclick = () => el.querySelector('#go').click();
        grid.appendChild(o);
      }
      list.appendChild(grid);
    }
  };
  const upd = () => {
    const b = BOARDS.find((x) => x.id === sel);
    el.querySelector('#bwhat').innerHTML = b ? `Выбрано: <b>${esc(b.name)}</b> · ${esc(b.family)} · ${b.kind === 'mcu' ? 'микроконтроллер (прошивка по USB)' : 'агент STELLS по сети'}` : 'Плата не выбрана';
    el.querySelector('#go').disabled = !b;
  };
  el.querySelectorAll('.chip').forEach((c) => (c.onclick = () => { fam = c.dataset.f; el.querySelectorAll('.chip').forEach((x) => x.classList.toggle('on', x === c)); render(); }));
  el.querySelector('#bq').oninput = (e) => { q = e.target.value; render(); };
  el.querySelector('#back').onclick = register;
  el.querySelector('#go').onclick = async () => { await save({ board: BOARDS.find((x) => x.id === sel) }); osStep(); };
  render(); upd();
}

// ---------------------------------------------------------------- 4. выбор ОС
function osStep() {
  scene3d?.setMode('core');
  const kind = cfg.board?.kind || 'linux';
  let all = false, sel = cfg.os?.name || null;
  const hostOs = { win32: 'Windows', darwin: 'macOS', linux: 'Linux' }[info.platform] || info.platform;
  const el = show(h(`<section class="screen"><div class="card glass" style="height:100%">
    ${stepsBar(3)}
    <div class="row"><div><div class="eyebrow">Шаг 2 из 4 · ${esc(cfg.board?.name)}</div><h2>Выберите операционную систему, на которой работает плата</h2></div></div>
    <p class="muted small" style="margin:0 0 10px">Компьютер: <b style="color:var(--text)">${esc(hostOs)} ${esc(info.osRelease)} (${esc(info.arch)})</b> — определено автоматически. Показаны ОС, подходящие для вашей платы.
      <label class="check" style="display:inline-flex;margin-left:12px"><input type="checkbox" id="allOs"> Показать все ОС</label></p>
    <label class="search" style="margin-bottom:6px">${icon('search', 16)}<input class="input" id="oq" placeholder="Поиск операционной системы"></label>
    <div class="list" id="olist"></div>
    <div class="sel-bar"><div class="what" id="owhat"></div><span class="spacer"></span>
      <button class="btn ghost" id="back">Назад</button><button class="btn primary" id="go" disabled>Продолжить<span class="shine"></span></button></div>
  </div></section>`));
  let q = '';
  const render = () => {
    const list = el.querySelector('#olist'); list.innerHTML = '';
    for (const c of OS_LIST) {
      if (!all && !c.for.includes(kind)) continue;
      const items = c.items.filter((i) => !q || i.toLowerCase().includes(q.toLowerCase()));
      if (!items.length) continue;
      list.appendChild(h(`<div class="group-title">${esc(c.cat)}</div>`));
      const grid = h('<div class="grid"></div>');
      for (const name of items) {
        const o = h(`<button class="opt ${name === sel ? 'on' : ''}"><b>${esc(name)}</b><span>${esc(c.cat)}</span></button>`);
        o.onclick = () => { sel = name; render(); upd(); };
        o.ondblclick = () => el.querySelector('#go').click();
        grid.appendChild(o);
      }
      list.appendChild(grid);
    }
  };
  const upd = () => { el.querySelector('#owhat').innerHTML = sel ? `ОС платы: <b>${esc(sel)}</b>` : 'ОС не выбрана'; el.querySelector('#go').disabled = !sel; };
  el.querySelector('#allOs').onchange = (e) => { all = e.target.checked; render(); };
  el.querySelector('#oq').oninput = (e) => { q = e.target.value; render(); };
  el.querySelector('#back').onclick = boardStep;
  el.querySelector('#go').onclick = async () => { await save({ os: { name: sel, host: hostOs } }); modelStep(); };
  render(); upd();
}

// ---------------------------------------------------------------- 5. выбор модели + SLT-ключ
function modelStep() {
  let sel = cfg.model?.type || null, keyOk = false;
  const el = show(h(`<section class="screen"><div class="card glass">
    ${stepsBar(4)}
    <div class="eyebrow">Шаг 3 из 4</div>
    <h2>Выберите вариант нашей модели для вас</h2>
    <div class="models" id="mlist"></div>
    <div class="warn"><i class="wi">${icon('triangle-alert', 18)}</i><div><b>Предупреждение:</b> скачивать только на мощное железо, и без <b>SLT key</b> программу невозможно будет запустить.<br>
      Ключ можно получить у разработчика: служба поддержки WhatsApp <a data-ext="wa">+7 702 538 97 49</a>, Telegram <a data-ext="tg">@Stells_help</a>, создатель <a data-ext="creator">@l3xn0</a>.</div></div>
    <div class="keyrow"><input class="input" id="key" placeholder="SLT-XXXX-XXXX-XXXX-XXXX" maxlength="26" value="${esc(cfg.sltKey)}"><button class="btn" id="check">Проверить ключ</button></div>
    <div class="keymsg" id="kmsg"></div>
    <div class="actions"><button class="btn ghost" id="back">Назад</button><span class="spacer"></span><button class="btn primary" id="go" disabled>Скачать и установить<span class="shine"></span></button></div>
  </div></section>`));
  const ml = el.querySelector('#mlist');
  const render = () => {
    ml.innerHTML = '';
    for (const m of MODEL_TYPES) {
      const c = h(`<div class="model ${m.type === sel ? 'on' : ''}"><div class="mt">${esc(m.title)}</div><div class="ms">${esc(m.sub)}</div><p>${esc(m.desc)}</p>
        <div class="heavy">Требования к железу ${[1, 2, 3].map((i) => `<i class="${i <= m.heavy ? 'f' : ''}"></i>`).join('')}</div></div>`);
      c.onclick = () => { sel = m.type; render(); upd(); };
      ml.appendChild(c);
    }
  };
  const upd = () => (el.querySelector('#go').disabled = !(sel && keyOk));
  const key = el.querySelector('#key'), msg = el.querySelector('#kmsg');
  const normalize = () => {
    let v = key.value.toUpperCase().replace(/[^A-Z0-9]/g, '');
    if (v.length === 19 && v.startsWith('SLT')) v = v.slice(3);
    if (v.length === 16) key.value = 'SLT-' + v.match(/.{4}/g).join('-');
  };
  key.addEventListener('input', () => {
    const pos = key.selectionStart;
    key.value = key.value.toUpperCase();
    key.setSelectionRange(pos, pos);
    keyOk = false; msg.textContent = ''; msg.className = 'keymsg'; key.classList.remove('err'); upd();
  });
  key.addEventListener('blur', normalize);
  key.addEventListener('paste', () => setTimeout(normalize));
  const check = async () => {
    normalize();
    const r = await api.validateKey(key.value);
    keyOk = r.ok;
    msg.innerHTML = (r.ok ? icon('shield-check', 15) + ' Ключ действителен. Доступ к моделям открыт.' : icon('shield-alert', 15) + ' ' + esc(r.reason));
    msg.className = 'keymsg ' + (r.ok ? 'ok' : 'bad');
    key.classList.toggle('err', !r.ok);
    upd();
    return r.ok;
  };
  el.querySelector('#check').onclick = check;
  key.addEventListener('keydown', (e) => e.key === 'Enter' && check());
  el.querySelector('#back').onclick = osStep;
  el.querySelector('#go').onclick = async () => {
    if (!(await check())) return;
    const manifest = await api.models.manifest();
    const m = manifest.models.find((x) => x.type === sel) || { type: sel };
    await save({ model: m, sltKey: key.value });
    installStep();
  };
  if (cfg.sltKey) check();
  render(); upd();
}

// ---------------------------------------------------------------- 6. установка: модель + прошивка
function installStep() {
  const b = cfg.board, m = cfg.model;
  const mcu = b.kind === 'mcu';
  const el = show(h(`<section class="screen"><div class="card glass">
    ${stepsBar(5)}
    <div class="eyebrow">Шаг 4 из 4 · ${esc(b.name)} · ${esc(cfg.os.name)} · ${esc(m.name || m.type)}</div>
    <h2>Загрузка и установка</h2>
    <div class="box" style="background:rgba(255,255,255,.03);border-radius:14px">
      <div class="row"><b>Модель ${esc(m.name || m.type)}</b><span class="spacer"></span><span id="mstate" class="badge">ожидание</span></div>
      <div class="prog"><div class="bar"><i id="mbar"></i></div><div class="pt"><span id="mtxt">—</span><span id="mpct">0%</span></div></div>
    </div>
    <h3 style="margin-top:16px">Как пользоваться</h3>
    <div class="howto">
      ${mcu ? `
      <div class="step"><span class="num">1</span><b>Прошивка</b>Откройте <code>arduino/stells_arduino.ino</code> из архива в Arduino IDE, выберите плату и порт → «Загрузить».</div>
      <div class="step"><span class="num">2</span><b>Подключение</b>Подключите плату к компьютеру USB-кабелем.</div>
      <div class="step"><span class="num">3</span><b>Связь</b>В разделе «Плата» нажмите «USB / Serial» — приложение найдёт плату само.</div>
      <div class="step"><span class="num">4</span><b>Управление</b>Машинное зрение работает на компьютере, команды идут на плату по USB.</div>` : `
      <div class="step"><span class="num">1</span><b>Скопируйте архив на плату</b>Флешкой или командой <code>scp -r stells-firmware pi@IP:~/</code></div>
      <div class="step"><span class="num">2</span><b>Установите</b>На плате: <code>cd stells-firmware/agent && sudo bash install.sh</code></div>
      <div class="step"><span class="num">3</span><b>Подключите</b>В приложении «Плата» → «Найти в сети». Агент стартует сам при включении платы.</div>
      <div class="step"><span class="num">4</span><b>Модели</b>Положите модели в «Модели» — они передаются на плату и в локальное зрение.</div>`}
    </div>
    <div class="box" style="background:linear-gradient(135deg,rgba(56,225,255,.08),rgba(138,92,255,.1));border-radius:14px;box-shadow:0 0 0 1px var(--line-2) inset">
      <div class="row"><div><b>Скачать управление моделью в плате с компьютера удалённо</b><div class="muted small">Нажмите на кнопку «Скачать» — скачается архив прошивки для ${esc(b.name)}</div></div>
        <span class="spacer"></span><button class="btn primary" id="dl">${icon('download', 16)} Скачать</button></div>
      <div class="prog" id="fwprog" hidden><div class="bar"><i id="fbar"></i></div><div class="pt"><span id="ftxt">—</span><span id="fpct"></span></div></div>
    </div>
    <div class="actions"><button class="btn ghost" id="back">Назад</button><span class="spacer"></span><button class="btn" id="next" disabled>Далее</button></div>
  </div></section>`));

  // модель: настоящая загрузка, если в каталоге есть url; иначе — слот готов для подключения позже
  (async () => {
    const set = (p, t, st) => { el.querySelector('#mbar').style.width = p + '%'; el.querySelector('#mpct').textContent = Math.round(p) + '%'; el.querySelector('#mtxt').textContent = t; if (st) el.querySelector('#mstate').textContent = st; };
    if (m.url) {
      set(0, 'Подключение к хранилищу…', 'загрузка');
      const off = api.onDownload((d) => { if (d.id === m.file && d.total) set(d.got / d.total * 100, `${(d.got / 1048576).toFixed(1)} / ${(d.total / 1048576).toFixed(1)} МБ`); });
      const r = await api.models.download({ url: m.url, file: m.file });
      off();
      r.ok ? set(100, 'Модель загружена: ' + r.path, 'готово') : set(0, 'Ошибка загрузки: ' + r.reason + ' — обратитесь в службу поддержки', 'ошибка');
    } else {
      set(100, 'Слот модели создан. Файлы модели будут подключены разработчиком — обновятся автоматически.', 'слот готов');
    }
  })();

  el.querySelector('#dl').onclick = async () => {
    const pr = el.querySelector('#fwprog'); pr.hidden = false;
    const fbar = el.querySelector('#fbar'), ftxt = el.querySelector('#ftxt');
    ftxt.textContent = 'Сборка прошивки под ' + b.name + '…'; fbar.style.width = '30%';
    const off = api.onDownload((d) => { if (d.id === 'firmware') { if (d.note) ftxt.textContent = d.note; else if (d.total) fbar.style.width = (d.got / d.total * 100) + '%'; } });
    const r = await api.firmware.download();
    off();
    if (!r.ok) { ftxt.textContent = 'Ошибка: ' + r.reason + '. Обратитесь в службу поддержки.'; return toast(r.reason, 'err'); }
    fbar.style.width = '100%';
    ftxt.innerHTML = `${icon('circle-check', 14)} Архив сохранён: <a id="showfw">${esc(r.path)}</a>`;
    el.querySelector('#showfw').onclick = () => api.showItem(r.path);
    el.querySelector('#next').disabled = false;
    el.querySelector('#next').classList.add('primary');
    toast('Прошивка скачана', 'ok');
    askVisionMode();
  };
  el.querySelector('#next').onclick = askVisionMode;
  el.querySelector('#back').onclick = modelStep;
}

function askVisionMode() {
  modal(`<div class="eyebrow">Машинное зрение</div>
    <h2>Запустить локально машинное зрение для платы на этом компьютере?</h2>
    <p class="lead">Компьютер будет анализировать видео с платы (или с веб-камеры) и передавать результаты в пульт. Это разгружает плату — подходит даже для Raspberry Pi Zero и Arduino.</p>
    <div class="actions" style="justify-content:stretch;flex-direction:column;align-items:stretch">
      <button class="btn primary xl" data-local>${icon('monitor', 20)} Запустить локально на этом компьютере<span class="shine"></span></button>
      <button class="btn" data-server style="margin-top:6px">${icon('server', 16)} Свой сервер</button>
    </div>`, (m) => {
    m.querySelector('[data-local]').onclick = async () => { m.close(); await save({ visionMode: 'local' }); visionStep(); };
    m.querySelector('[data-server]').onclick = async () => { m.close(); await save({ visionMode: 'server' }); visionStep(); };
  });
}

// ---------------------------------------------------------------- 7. загрузка машинного зрения на компьютер
function visionStep() {
  const local = cfg.visionMode === 'local';
  const el = show(h(`<section class="screen"><div class="card mid glass">
    ${stepsBar(6)}
    <div class="eyebrow">${local ? 'Локальный режим' : 'Свой сервер'}</div>
    <h2>${local ? 'Загрузка машинного зрения на компьютер' : 'Подключение своего сервера машинного зрения'}</h2>
    ${local ? `
      <p class="lead">Встроенное зрение уже готово. Сейчас устанавливается полный модуль (Python + OpenCV) для моделей ONNX/YOLO. Он будет запускаться при каждом старте STELLS.</p>
      <div class="prog"><div class="bar"><i id="vbar"></i></div><div class="pt"><span id="vtxt">Подготовка…</span><span id="vpct">0%</span></div></div>
      <div class="log" id="vlog"></div>` : `
      <p class="lead">Укажите адрес сервера, на котором запущен <code>stells_vision.py</code> (или совместимый API: <code>/stream</code> и <code>/detections</code>).</p>
      <div class="field"><label>Адрес сервера</label><input class="input" id="srv" placeholder="http://my-server:8090" value="${esc(cfg.visionServer)}"></div>
      <div class="row"><button class="btn" id="test">Проверить соединение</button><span id="tres" class="small"></span></div>
      <pre class="code">На сервере:\npip install opencv-python numpy\npython stells_vision.py --source http://IP_ПЛАТЫ:8766/stream --port 8090\n# откройте порт 8090 (или используйте Tailscale)</pre>`}
    <div class="actions"><button class="btn ghost" id="back">Назад</button><span class="spacer"></span><button class="btn primary" id="go" ${local ? 'disabled' : ''}>Далее<span class="shine"></span></button></div>
  </div></section>`));
  el.querySelector('#back').onclick = () => { installStep(); };
  el.querySelector('#go').onclick = async () => {
    if (!local) await save({ visionServer: el.querySelector('#srv').value.trim() });
    usageStep();
  };
  if (local) {
    const log = el.querySelector('#vlog');
    const offL = api.vision.onLog((t) => { log.textContent += t + (t.endsWith('\n') ? '' : '\n'); log.scrollTop = log.scrollHeight; });
    const offP = api.vision.onProgress((p) => {
      el.querySelector('#vbar').style.width = p + '%'; el.querySelector('#vpct').textContent = p + '%';
      if (p >= 15 && p < 100) { const g = el.querySelector('#go'); g.disabled = false; g.firstChild.textContent = 'Далее (установка продолжится в фоне)'; }
    });
    el.querySelector('#vtxt').textContent = 'Загрузка модуля машинного зрения…';
    api.vision.install().then((r) => {
      offL(); offP();
      if (!document.body.contains(el)) { toast(r.python ? 'Python-модуль машинного зрения установлен' : 'Встроенное зрение активно; Python-модуль можно доустановить в «Машинное зрение»', r.python ? 'ok' : 'warn'); return; }
      el.querySelector('#go').firstChild.textContent = 'Далее';
      el.querySelector('#vbar').style.width = '100%'; el.querySelector('#vpct').textContent = '100%';
      el.querySelector('#vtxt').textContent = r.python ? 'Машинное зрение установлено (Python + OpenCV)' : 'Встроенное машинное зрение готово (Python-модуль можно доустановить позже в «Настройках»)';
      el.querySelector('#go').disabled = false;
    });
  } else {
    el.querySelector('#test').onclick = async () => {
      const u = el.querySelector('#srv').value.trim().replace(/\/+$/, '');
      const t = el.querySelector('#tres');
      try { const r = await fetch(u + '/detections', { signal: AbortSignal.timeout(4000) }); const j = await r.json(); t.innerHTML = `<span style="color:var(--green)">${icon('circle-check', 14)} Сервер отвечает · ${j.fps ?? 0} FPS</span>`; }
      catch (e) { t.innerHTML = `<span style="color:var(--red)">${icon('circle-x', 14)} Нет ответа (${esc(e.message)}). Если что-то не получается — обратитесь в службу поддержки.</span>`; }
    };
  }
}

// ---------------------------------------------------------------- 8. способ использования
function usageStep() {
  document.body.classList.remove('in-dash');
  const el = show(h(`<section class="screen"><div class="card glass">
    ${stepsBar(7)}
    <div class="eyebrow">Машинное зрение готово</div>
    <h2>Выберите способ использования машинного зрения</h2>
    <div class="usages" id="ulist"></div>
    <div class="beta-note">${icon('lock', 15)} В закрытом тестировании. Если хотите купить — напишите создателю <a data-ext="creator"><b>@l3xn0</b></a></div>
  </div></section>`));
  const ul = el.querySelector('#ulist');
  for (const u of USAGES) {
    const c = h(`<button class="usage"><div class="n">0${u.n}</div><div class="ic">${icon(u.icon, 34)}</div><b>${esc(u.title)}</b><span>${esc(u.desc)}</span><div class="closed">${icon('lock', 11)} Закрытый тест</div></button>`);
    c.onclick = async () => { await save({ usage: u.id, registered: true }); await api.config.set({ autostart: cfg.autostart }); scene3d?.pulse(); dashboard('control'); };
    ul.appendChild(c);
  }
}

// ---------------------------------------------------------------- панель управления
let unmount = null;
const NAV = [
  ['home', 'house', 'Главная'], ['control', 'gamepad-2', 'Пульт'], ['vision', 'scan-eye', 'Машинное зрение'], ['board', 'cpu', 'Плата'],
  ['models', 'brain-circuit', 'Модели'], ['code', 'square-terminal', 'Коннектор и терминал'], ['guide', 'book-open', 'Инструкции'], ['settings', 'settings', 'Настройки'], ['support', 'life-buoy', 'Поддержка'],
];
function dashboard(page = 'home') {
  scene3d?.setMode('dash');
  document.body.classList.add('in-dash');
  const el = show(h(`<section class="dash">
    <aside class="side glass">
      <div class="me"><div class="avatar">${esc((cfg.user.name || '?')[0].toUpperCase())}</div><div class="me-t"><b>${esc(cfg.user.name)}</b><span>${esc(cfg.board?.name || '')}</span></div></div>
      <div class="nav-sec">Рабочее место</div>
      ${NAV.slice(0, 5).map(([id, ic, t]) => `<button class="nav" data-nav="${id}">${icon(ic, 17)}<span>${t}</span></button>`).join('')}
      <div class="nav-sec">Инструменты</div>
      ${NAV.slice(5).map(([id, ic, t]) => `<button class="nav" data-nav="${id}">${icon(ic, 17)}<span>${t}</span></button>`).join('')}
      <div class="foot"><div class="foot-brand">${logo(18)} STELLS <span>v${esc(info.version)}</span></div>Проект Алексея · <a data-ext="creator">@l3xn0</a></div>
    </aside>
    <div class="content" id="content"></div>
  </section>`));
  const content = el.querySelector('#content');
  const go = (p) => {
    if (p === 'code') { openIDE(); return; }
    unmount && unmount(); unmount = null;
    el.querySelectorAll('[data-nav]').forEach((n) => n.classList.toggle('on', n.dataset.nav === p));
    unmount = PAGES[p](content) || null;
  };
  el.querySelectorAll('[data-nav]').forEach((n) => (n.onclick = () => go(n.dataset.nav)));
  go(page);
}

const fmtUp = (s) => (s == null ? '—' : `${Math.floor(s / 3600)} ч ${Math.floor(s / 60) % 60} мин`);
const PAGES = {
  home(root) {
    const u = USAGES.find((x) => x.id === cfg.usage);
    root.innerHTML = '';
    const p = h(`<div class="page">
      <div class="page-head"><div><div class="eyebrow">${greeting()}</div><h2>${esc(cfg.user.name)}, всё готово к работе</h2></div><span class="spacer"></span>
        <button class="btn primary" data-go="control">${u ? icon(u.icon, 16) + ' Открыть пульт: ' + u.title : 'Открыть пульт'}</button></div>
      <div class="cols c4">
        <div class="stat glass"><div class="k">Плата</div><div class="v" id="hBoard">—</div></div>
        <div class="stat glass"><div class="k">Температура</div><div class="v" id="hTemp">— <small>°C</small></div></div>
        <div class="stat glass"><div class="k">Машинное зрение</div><div class="v" id="hVis">—</div></div>
        <div class="stat glass"><div class="k">Модель</div><div class="v" style="font-size:20px">${esc(cfg.model?.name || cfg.model?.type || '—')}</div></div>
      </div>
      <div class="cols main-side">
        <div class="box glass"><h3>${icon('scan-eye', 16)} Живое машинное зрение <span class="spacer"></span><span class="badge live" id="hFps">—</span></h3>
          <div class="video"><canvas></canvas><div class="empty" data-empty>Машинное зрение запускается автоматически при старте.<br>Разрешите доступ к камере или подключите плату.</div></div></div>
        <div class="box glass"><h3>Конфигурация</h3>
          <div class="kv">
            <span>Плата</span><span>${esc(cfg.board?.name)}</span><span>Семейство</span><span>${esc(cfg.board?.family)} · ${esc(cfg.board?.group)}</span>
            <span>ОС платы</span><span>${esc(cfg.os?.name)}</span><span>Компьютер</span><span>${esc(cfg.os?.host)} · ${esc(info.arch)} · ${info.cpus} ядер · ${(info.totalMem / 1073741824).toFixed(1)} ГБ</span>
            <span>Модель</span><span>${esc(cfg.model?.name || cfg.model?.type)}</span><span>Зрение</span><span>${cfg.visionMode === 'server' ? 'свой сервер ' + esc(cfg.visionServer) : 'локально на компьютере'}</span>
            <span>Режим</span><span>${u ? esc(u.title) : '—'}</span><span>SLT-ключ</span><span><code>${esc((cfg.sltKey || '').slice(0, 8))}••••</code></span>
            <span>Связь</span><span id="hLink">—</span><span>Аптайм платы</span><span id="hUp">—</span>
          </div>
          <div class="row wrap" style="margin-top:16px">
            <button class="btn sm" data-go="board">${icon('plug-zap', 15)} Подключить плату</button><button class="btn sm" data-go="models">${icon('brain-circuit', 15)} Модели</button>
            <button class="btn sm" data-go="usage">${icon('refresh-cw', 15)} Сменить режим</button></div>
        </div>
      </div>
    </div>`);
    root.appendChild(p);
    p.querySelectorAll('[data-go]').forEach((b) => (b.onclick = () => (b.dataset.go === 'usage' ? usageStep() : document.querySelector(`[data-nav=${b.dataset.go}]`).click())));
    const detach = vision.attach(p.querySelector('canvas'));
    const tick = () => {
      const s = link.telemetry.system || {};
      p.querySelector('#hBoard').innerHTML = link.state === 'online' ? '<span style="color:var(--green)">онлайн</span>' : '<span class="muted">офлайн</span>';
      p.querySelector('#hTemp').innerHTML = `${s.temp != null ? Number(s.temp).toFixed(1) : '—'} <small>°C</small>`;
      p.querySelector('#hVis').innerHTML = vision.source ? `<span style="color:var(--green)">${vision.fps} FPS</span>` : '<span class="muted">выкл</span>';
      p.querySelector('#hFps').textContent = vision.source ? `${vision.detections.length} объектов · ${vision.fps} FPS` : 'ожидание';
      p.querySelector('#hLink').textContent = link.label();
      p.querySelector('#hUp').textContent = fmtUp(s.uptime);
      p.querySelector('[data-empty]').style.display = vision.source ? 'none' : '';
    };
    const t = setInterval(tick, 500); tick();
    return () => { clearInterval(t); detach(); };
  },

  control(root) {
    const m = { drones: mountDrone, cars: mountCar, robots: mountRobot, cameras: mountCameras, wol: mountWol }[cfg.usage] || mountDrone;
    return m(root, cfg);
  },

  vision(root) {
    root.innerHTML = '';
    const p = h(`<div class="page">
      <div class="page-head"><h2>Машинное зрение</h2><span class="badge live" id="vStat">—</span></div>
      <div class="cols main-side">
        <div class="box glass">
          <div class="video"><canvas style="cursor:crosshair"></canvas><div class="empty" data-empty>Источник не выбран</div><div class="hud-tl" id="vHud"></div></div>
          <div class="row wrap" style="margin-top:10px">
            <button class="btn sm" data-s="webcam">${icon('camera', 15)} Камера компьютера</button><button class="btn sm" data-s="board">${icon('satellite-dish', 15)} Камера платы</button>
            <button class="btn sm" data-s="py">${icon('code', 15)} Python-модуль (ONNX)</button><button class="btn sm" data-s="srv">${icon('server', 15)} Свой сервер</button><button class="btn sm ghost" data-s="stop">${icon('circle-stop', 15)} Стоп</button>
          </div>
        </div>
        <div class="box glass">
          <h3>Анализ</h3>
          <label class="check"><input type="checkbox" id="oMotion" checked> Детектор движения</label>
          <label class="check" style="margin-top:8px"><input type="checkbox" id="oColor"> Трекинг цели по цвету (нажмите на объект в видео)</label>
          <div class="field" style="margin-top:12px"><label>Чувствительность</label><input type="range" class="slider" id="oSens" min="8" max="60" value="${68 - vision.opts.sensitivity}"></div>
          <h3>Объекты в кадре</h3>
          <div class="log" id="oDet" style="height:140px"></div>
          <h3 style="margin-top:12px">Python-модуль <span class="spacer"></span><span class="badge" id="pyStat">—</span></h3>
          <div class="row wrap"><button class="btn sm" id="pyStart">Запустить</button><button class="btn sm" id="pyStop">Остановить</button><button class="btn sm" id="pyInst">Переустановить</button></div>
          <div class="log" id="pyLog" style="height:110px;margin-top:8px"></div>
        </div>
      </div>
    </div>`);
    root.appendChild(p);
    const cv = p.querySelector('canvas');
    const detach = vision.attach(cv);
    cv.onclick = (e) => { const r = cv.getBoundingClientRect(); vision.pickColorAt((e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height); p.querySelector('#oColor').checked = true; toast('Цель захвачена', 'ok'); };
    p.querySelector('#oMotion').checked = vision.opts.motion;
    p.querySelector('#oMotion').onchange = (e) => (vision.opts.motion = e.target.checked);
    p.querySelector('#oColor').onchange = (e) => (vision.opts.color = e.target.checked);
    p.querySelector('#oSens').oninput = (e) => (vision.opts.sensitivity = 68 - Number(e.target.value));
    p.querySelectorAll('[data-s]').forEach((b) => (b.onclick = async () => {
      const s = b.dataset.s;
      if (s === 'webcam') { const r = await vision.startWebcam(); if (!r.ok) toast(r.reason, 'err'); }
      if (s === 'board') { const u = link.streamUrl(); u ? vision.startStream(u, 'Камера платы') : toast('Подключите плату по сети', 'warn'); }
      if (s === 'py') { const r = await api.vision.start(); if (!r.ok) return toast(r.reason, 'warn'); await sleep(1500); vision.startStream('http://127.0.0.1:8090/stream', 'STELLS Vision (Python)'); }
      if (s === 'srv') { if (!cfg.visionServer) return toast('Укажите адрес сервера в «Настройках»', 'warn'); vision.startStream(cfg.visionServer.replace(/\/+$/, '') + '/stream', 'Свой сервер'); }
      if (s === 'stop') vision.stop();
      updateStatus();
    }));
    const pyLog = p.querySelector('#pyLog');
    const offLog = api.vision.onLog((t) => { pyLog.textContent = (pyLog.textContent + t).slice(-20000); pyLog.scrollTop = pyLog.scrollHeight; });
    const pySt = async () => { const s = await api.vision.status(); p.querySelector('#pyStat').textContent = s.running ? 'работает' : s.python ? 'установлен' : 'не установлен'; };
    p.querySelector('#pyStart').onclick = async () => { const r = await api.vision.start(); toast(r.ok ? 'Python-зрение запущено: ' + (r.url || '') : r.reason, r.ok ? 'ok' : 'warn'); pySt(); };
    p.querySelector('#pyStop').onclick = async () => { await api.vision.stop(); pySt(); };
    p.querySelector('#pyInst').onclick = async () => { toast('Установка Python-модуля…'); const r = await api.vision.install(); toast(r.python ? 'Python-модуль установлен' : 'Встроенное зрение активно; для Python-модуля установите Python 3.10+', r.python ? 'ok' : 'warn'); pySt(); };
    pySt();
    const t = setInterval(() => {
      p.querySelector('[data-empty]').style.display = vision.source ? 'none' : '';
      p.querySelector('#vHud').textContent = vision.source ? `${vision.source.label} · ${vision.fps} FPS · свет ${vision.light}%` : '';
      p.querySelector('#vStat').textContent = vision.source ? 'активно' : 'выкл';
      p.querySelector('#oDet').textContent = vision.detections.map((d) => `${d.label.padEnd(10)} ${String(Math.round(d.score * 100)).padStart(3)}%  [${d.box.map((x) => x.toFixed(2)).join(', ')}]`).join('\n') || 'нет объектов';
    }, 300);
    return () => { clearInterval(t); detach(); offLog(); };
  },

  board(root) {
    root.innerHTML = '';
    const p = h(`<div class="page">
      <div class="page-head"><h2>Плата <span class="h-sub">${esc(cfg.board?.name)}</span></h2><span class="spacer"></span><span class="badge" id="bState">—</span></div>
      <div class="box glass">
        <h3>Подключение</h3>
        <div class="row wrap">
          <input class="input" id="bHost" placeholder="IP-адрес платы (192.168.x.x, 100.x.x.x для Tailscale)" style="flex:2;min-width:220px" value="${esc(cfg.devices?.[0]?.host || '')}">
          <input class="input" id="bToken" placeholder="Токен (если задан)" style="flex:1;min-width:140px">
          <button class="btn primary" id="bConn">Подключить</button><button class="btn" id="bFind">${icon('radar', 15)} Найти в сети</button>
          <button class="btn" id="bUsb">${icon('usb', 15)} USB / Serial</button><button class="btn ghost" id="bOff">Отключить</button>
        </div>
        <div id="bFound" class="row wrap" style="margin-top:10px"></div>
      </div>
      <div class="cols c4" id="bStats"></div>
      <div class="cols c2">
        <div class="box glass"><h3>Прошивка (управление моделью в плате)</h3>
          <p class="muted small">Архив содержит агент STELLS, установщик службы автозапуска, конфиг под вашу плату и примеры коннекторов.</p>
          <div class="row wrap"><button class="btn primary" id="bDl">${icon('download', 15)} Скачать прошивку</button><button class="btn" id="bDlAs">Сохранить как…</button></div>
          <div class="small muted" id="bDlRes" style="margin-top:8px"></div>
          <pre class="code">${cfg.board?.kind === 'mcu' ? 'Arduino IDE → открыть arduino/stells_arduino/stells_arduino.ino → Загрузить' : 'scp -r stells-firmware pi@IP:~/\nssh pi@IP\ncd stells-firmware/agent && sudo bash install.sh'}</pre>
        </div>
        <div class="box glass"><h3>Журнал платы</h3><div class="log" id="bLog"></div></div>
      </div>
    </div>`);
    root.appendChild(p);
    const log = p.querySelector('#bLog');
    const addLog = (t) => { log.textContent = `[${new Date().toLocaleTimeString()}] ${t}\n` + log.textContent.slice(0, 20000); };
    const st = () => { p.querySelector('#bState').textContent = link.label(); p.querySelector('#bState').className = 'badge ' + (link.state === 'online' ? 'live' : ''); };
    p.querySelector('#bConn').onclick = async () => {
      const host = p.querySelector('#bHost').value.trim();
      if (!host) return toast('Введите IP-адрес платы', 'warn');
      addLog('Подключение к ' + host + '…');
      const r = await link.connectWs(host, 8765, p.querySelector('#bToken').value.trim());
      if (r.ok) { addLog('Подключено: ' + r.info.name + ' (агент ' + r.info.version + ')'); await save({ devices: [{ host, name: r.info.name }] }); toast('Плата подключена', 'ok'); }
      else { addLog('Ошибка: ' + r.reason); toast(r.reason + '. Если что-то не получается — обратитесь в службу поддержки.', 'err'); }
    };
    p.querySelector('#bFind').onclick = async () => {
      addLog('Поиск плат STELLS в сети (UDP 48765)…');
      const list = await api.net.discover();
      const f = p.querySelector('#bFound'); f.innerHTML = '';
      if (!list.length) addLog('Платы не найдены. Убедитесь, что агент установлен и плата в той же сети.');
      for (const d of list) {
        addLog(`Найдена: ${d.name} — ${d.host}`);
        const b = h(`<button class="btn sm ok">${esc(d.name)} · ${esc(d.host)}</button>`);
        b.onclick = () => { p.querySelector('#bHost').value = d.host; p.querySelector('#bConn').click(); };
        f.appendChild(b);
      }
    };
    p.querySelector('#bUsb').onclick = async () => { const r = await link.connectSerial(); addLog(r.ok ? 'USB-плата подключена' : 'USB: ' + r.reason); };
    p.querySelector('#bOff').onclick = () => { link.disconnect(); addLog('Отключено'); };
    let fwPath = null;
    p.querySelector('#bDl').onclick = async () => { const r = await api.firmware.download(); if (r.ok) { fwPath = r.path; p.querySelector('#bDlRes').innerHTML = `${icon('circle-check', 14)} <a>${esc(r.path)}</a>`; p.querySelector('#bDlRes a').onclick = () => api.showItem(r.path); } else toast(r.reason, 'err'); };
    p.querySelector('#bDlAs').onclick = async () => { if (!fwPath) { const r = await api.firmware.download(); fwPath = r.path; } const d = await api.firmware.saveAs(fwPath); if (d) toast('Сохранено: ' + d, 'ok'); };
    const onLog = (e) => addLog(e.detail);
    const onTel = (e) => {
      const s = e.detail.system || {};
      p.querySelector('#bStats').innerHTML = [['Модель', s.model || s.host || '—', ''], ['Температура', s.temp != null ? Number(s.temp).toFixed(1) : '—', '°C'], ['Нагрузка', s.load ?? '—', ''], ['ОЗУ', s.memUsed != null ? `${s.memUsed}/${s.memTotal}` : '—', 'МБ']]
        .map(([k, v, u]) => `<div class="stat glass"><div class="k">${k}</div><div class="v" style="font-size:${String(v).length > 14 ? 15 : 24}px">${esc(v)} <small>${u}</small></div></div>`).join('');
    };
    link.addEventListener('log', onLog); link.addEventListener('telemetry', onTel); link.addEventListener('state', st);
    st(); onTel({ detail: link.telemetry });
    return () => { link.removeEventListener('log', onLog); link.removeEventListener('telemetry', onTel); link.removeEventListener('state', st); };
  },

  models(root) {
    root.innerHTML = '';
    const p = h(`<div class="page">
      <div class="page-head"><h2>Модели</h2><span class="spacer"></span><button class="btn primary" id="mImp">${icon('plus', 16)} Подключить файл модели</button></div>
      <div class="cols c3" id="mCat"></div>
      <div class="box glass"><h3>Установленные модели <span class="spacer"></span><a class="small" id="mFolder">открыть папку</a></h3><div id="mInst"></div>
        <p class="small muted">Поддерживаются: .onnx (YOLO — используется машинным зрением автоматически), .gguf (LLM/SLM/VLM через llama.cpp), .tflite, .rknn (Rockchip NPU), .hef (Hailo), .engine (TensorRT/Jetson), .safetensors, .pt.</p></div>
    </div>`);
    root.appendChild(p);
    const refresh = async () => {
      const inst = await api.models.installed();
      p.querySelector('#mInst').innerHTML = inst.length ? '' : '<p class="muted">Пока нет файлов моделей.</p>';
      for (const f of inst) {
        const r = h(`<div class="row" style="padding:10px;border-radius:10px;background:rgba(255,255,255,.03);margin-bottom:6px"><code></code><span class="spacer"></span><span class="small muted">${(f.size / 1048576).toFixed(1)} МБ</span><button class="btn sm ghost icon-only" title="Удалить">${icon('trash-2', 15)}</button></div>`);
        r.querySelector('code').textContent = f.file;
        r.querySelector('button').onclick = async () => { await api.models.remove(f.file); refresh(); };
        p.querySelector('#mInst').appendChild(r);
      }
      const man = await api.models.manifest();
      const cat = p.querySelector('#mCat'); cat.innerHTML = '';
      for (const m of man.models) {
        const have = inst.some((f) => f.file === m.file);
        const c = h(`<div class="box glass"><div class="row"><b style="font-size:20px">${esc(m.type)}</b><span class="spacer"></span><span class="badge ${have ? 'live' : ''}">${have ? 'установлена' : m.url ? 'доступна' : 'скоро'}</span></div>
          <div class="muted small" style="margin:6px 0 10px">${esc(m.name)} — ${esc(m.desc)}<br>Минимум ОЗУ: ${m.minRam} ГБ</div>
          <button class="btn sm ${m.url && !have ? 'primary' : ''}" ${m.url && !have ? '' : 'disabled'}>${have ? icon('check', 14) + ' Установлена' : m.url ? icon('download', 14) + ' Скачать' : 'Будет подключена разработчиком'}</button>
          <div class="prog" hidden><div class="bar"><i></i></div></div></div>`);
        c.querySelector('button').onclick = async () => {
          const pr = c.querySelector('.prog'); pr.hidden = false;
          const off = api.onDownload((d) => { if (d.id === m.file && d.total) pr.querySelector('i').style.width = (d.got / d.total * 100) + '%'; });
          const r = await api.models.download({ url: m.url, file: m.file }); off();
          toast(r.ok ? `${m.name} загружена` : 'Ошибка: ' + r.reason, r.ok ? 'ok' : 'err'); refresh();
        };
        cat.appendChild(c);
      }
    };
    p.querySelector('#mImp').onclick = async () => { const r = await api.models.import(); if (r.length) { toast(`Подключено файлов: ${r.length}`, 'ok'); refresh(); } };
    p.querySelector('#mFolder').onclick = () => api.openPath(info.paths.models);
    refresh();
  },

  guide(root) {
    root.innerHTML = '';
    root.appendChild(h(`<div class="page"><div class="page-head"><h2>Инструкции</h2></div>
      <div class="cols c2" style="font-size:14px;line-height:1.65;color:var(--muted)">
        <div class="box glass"><h3 style="color:var(--text)">1. Подготовка платы</h3>
          Запишите ОС на карту памяти (Raspberry Pi Imager / balenaEtcher), включите SSH и Wi-Fi. Подключите плату к той же сети, что и компьютер.
          Скачайте прошивку в разделе «Плата», скопируйте на плату и выполните <code>sudo bash install.sh</code>. Агент запускается автоматически при каждом включении.</div>
        <div class="box glass"><h3 style="color:var(--text)">2. Подключение</h3>
          «Плата» → «Найти в сети». Если не нашлось — введите IP (узнать: <code>hostname -I</code> на плате или в админке роутера).
          Arduino/ESP32 — кнопка «USB / Serial». Через интернет — Tailscale/ZeroTier (см. пульт дрона → «Удалённо»).</div>
        <div class="box glass"><h3 style="color:var(--text)">3. Машинное зрение</h3>
          Запускается само при каждом старте STELLS. Встроенное зрение (движение, трекинг цели) работает без установки.
          Для нейросетей положите <code>.onnx</code> (YOLOv5/v8) и <code>.txt</code> с классами в «Модели» — Python-модуль подхватит их автоматически.</div>
        <div class="box glass"><h3 style="color:var(--text)">4. Свой коннектор</h3>
          «Коннектор / Терминал» открывает редактор как VS Code с настоящим терминалом. Протокол простой: команды пульта — JSON-строки в stdin,
          телеметрия — JSON-строки в stdout. Поддерживаются Python, JS, TS, C, C++, Rust, Go, Java, Kotlin, C#, Lua, Ruby, PHP, Perl, Bash, PowerShell.</div>
        <div class="box glass"><h3 style="color:var(--text)">5. Автозапуск</h3>
          STELLS запускается вместе с компьютером, приветствует вас по имени и за 5 секунд загружает ядро, зрение и подключение к последней плате.
          Отключить — в «Настройках».</div>
        <div class="box glass"><h3 style="color:var(--text)">Если что-то не получается</h3>
          Обратитесь в службу поддержки: WhatsApp <a data-ext="wa">+7 702 538 97 49</a>, Telegram <a data-ext="tg">@Stells_help</a>.
          Создатель проекта — <a data-ext="creator">@l3xn0</a>. Приложите скриншот и журнал из раздела «Плата».</div>
      </div></div>`));
  },

  settings(root) {
    root.innerHTML = '';
    const p = h(`<div class="page"><div class="page-head"><h2>Настройки</h2></div>
      <div class="cols c2">
        <div class="box glass">
          <h3>Запуск</h3>
          <label class="check"><input type="checkbox" id="sAuto" ${cfg.autostart ? 'checked' : ''}> Запускать STELLS при включении компьютера</label>
          <label class="check" style="margin-top:10px"><input type="checkbox" id="sVis" ${cfg.autoVision ? 'checked' : ''}> Автоматически запускать машинное зрение</label>
          <label class="check" style="margin-top:10px"><input type="checkbox" id="sVoice" ${cfg.voice ? 'checked' : ''}> Голосовое приветствие</label>
          <h3 style="margin-top:18px">Профиль</h3>
          <div class="field"><label>Имя</label><input class="input" id="sName" value="${esc(cfg.user.name)}"></div>
          <div class="field"><label>Телефон</label><input class="input" id="sPhone" value="${esc(cfg.user.phone)}"></div>
          <div class="row wrap"><button class="btn primary" id="sSave">Сохранить</button><button class="btn" id="sRe">Пройти настройку заново</button></div>
        </div>
        <div class="box glass">
          <h3>Хранилище и серверы</h3>
          <div class="field"><label>Своё хранилище прошивок/моделей (необязательно)</label><input class="input" id="sDl" placeholder="https://github.com/USER/REPO/releases/download/v1" value="${esc(cfg.downloadServer)}"></div>
          <div class="field"><label>Свой сервер машинного зрения</label><input class="input" id="sSrv" placeholder="http://server:8090" value="${esc(cfg.visionServer)}"></div>
          <div class="field"><label>Режим машинного зрения</label><select class="input" id="sMode"><option value="local">Локально на этом компьютере</option><option value="server">Свой сервер</option></select></div>
          <div class="field"><label>Режим использования</label><select class="input" id="sUse">${USAGES.map((u) => `<option value="${u.id}">${u.n}. ${u.title}</option>`).join('')}</select></div>
          <div class="kv small"><span>Данные</span><span><a id="sData">${esc(info.paths.userData)}</a></span><span>SLT-ключ</span><span><code>${esc(cfg.sltKey)}</code></span></div>
          <button class="btn danger sm" id="sReset" style="margin-top:14px">Сбросить всё и выйти из аккаунта</button>
        </div>
      </div></div>`);
    root.appendChild(p);
    p.querySelector('#sMode').value = cfg.visionMode || 'local';
    p.querySelector('#sUse').value = cfg.usage || 'drones';
    p.querySelector('#sData').onclick = () => api.openPath(info.paths.userData);
    p.querySelector('#sSave').onclick = async () => {
      await save({
        autostart: p.querySelector('#sAuto').checked, autoVision: p.querySelector('#sVis').checked, voice: p.querySelector('#sVoice').checked,
        user: { name: p.querySelector('#sName').value.trim() || cfg.user.name, phone: p.querySelector('#sPhone').value.trim() || cfg.user.phone },
        downloadServer: p.querySelector('#sDl').value.trim(), visionServer: p.querySelector('#sSrv').value.trim(),
        visionMode: p.querySelector('#sMode').value, usage: p.querySelector('#sUse').value,
      });
      toast('Настройки сохранены', 'ok');
      document.querySelector('.side .me b').textContent = cfg.user.name;
    };
    p.querySelector('#sRe').onclick = () => { unmount && unmount(); unmount = null; boardStep(); };
    p.querySelector('#sReset').onclick = () => modal(`<h2>Сбросить STELLS?</h2><p class="lead">Профиль, ключ и настройки будут удалены. Модели и прошивки останутся на диске.</p>
      <div class="actions"><button class="btn" data-close>Отмена</button><button class="btn danger" data-yes>Сбросить</button></div>`,
      (m) => (m.querySelector('[data-yes]').onclick = async () => { m.close(); unmount && unmount(); unmount = null; await link.disconnect(); vision.stop(); cfg = await api.config.reset(); welcome(); }));
  },

  support(root) {
    root.innerHTML = '';
    root.appendChild(h(`<div class="page"><div class="page-head"><h2>Служба поддержки</h2></div>
      <div class="cols c3">
        <div class="box glass" style="text-align:center"><div class="big-ic">${icon('message-circle', 28)}</div><h3>WhatsApp</h3><p class="muted">${SUPPORT.whatsapp}</p><button class="btn primary" data-ext="wa">Написать</button></div>
        <div class="box glass" style="text-align:center"><div class="big-ic">${icon('send', 28)}</div><h3>Telegram</h3><p class="muted">${SUPPORT.telegram}</p><button class="btn primary" data-ext="tg">Написать</button></div>
        <div class="box glass" style="text-align:center"><div class="big-ic">${icon('user', 28)}</div><h3>Создатель</h3><p class="muted">${SUPPORT.creator} — покупка, ключи, закрытое тестирование</p><button class="btn primary" data-ext="creator">Написать</button></div>
      </div>
      <div class="box glass muted">Если что-то не получается — обратитесь в службу поддержки. Укажите плату (<b>${esc(cfg.board?.name)}</b>), ОС (<b>${esc(cfg.os?.name)}</b>), версию STELLS (<b>${esc(info.version)}</b>) и приложите скриншот.</div>
    </div>`));
  },
};

// ---------------------------------------------------------------- командная палитра (Ctrl+K)
function openPalette() {
  if (!cfg.registered || document.querySelector('.palette-bg')) return;
  const nav = (p) => () => { const b = document.querySelector(`[data-nav=${p}]`); b ? b.click() : dashboard(p); };
  const CMDS = [
    ...NAV.map(([id, ic, t]) => ({ ic, t, hint: 'Перейти', run: nav(id) })),
    { ic: 'camera', t: 'Запустить камеру компьютера', hint: 'Зрение', run: () => vision.startWebcam() },
    { ic: 'circle-stop', t: 'Остановить машинное зрение', hint: 'Зрение', run: () => vision.stop() },
    { ic: 'radar', t: 'Найти платы в сети', hint: 'Плата', run: async () => { const l = await api.net.discover(); toast(l.length ? 'Найдено: ' + l.map((d) => `${d.name} (${d.host})`).join(', ') : 'Платы не найдены', l.length ? 'ok' : 'warn'); } },
    { ic: 'orbit', t: 'Запустить симулятор', hint: 'Плата', run: () => { link.startSim(); toast('Симулятор запущен', 'ok'); } },
    { ic: 'unplug', t: 'Отключиться от платы', hint: 'Плата', run: () => link.disconnect() },
    { ic: 'download', t: 'Скачать прошивку для платы', hint: 'Плата', run: async () => { const r = await api.firmware.download(); r.ok ? api.showItem(r.path) : toast(r.reason, 'err'); } },
    { ic: 'refresh-cw', t: 'Сменить способ использования', hint: 'Режим', run: usageStep },
    { ic: 'folder-open', t: 'Открыть папку моделей', hint: 'Модели', run: () => api.openPath(info.paths.models) },
    { ic: 'message-circle', t: 'Написать в поддержку (WhatsApp)', hint: 'Поддержка', run: () => api.openExternal(SUPPORT.whatsappUrl) },
    { ic: 'send', t: 'Написать в поддержку (Telegram)', hint: 'Поддержка', run: () => api.openExternal(SUPPORT.telegramUrl) },
  ];
  const bg = h(`<div class="palette-bg"><div class="palette">
    <label class="pal-in">${icon('search', 18)}<input placeholder="Команда или раздел…" autofocus><kbd>Esc</kbd></label>
    <div class="pal-list"></div></div></div>`);
  document.body.appendChild(bg);
  const inp = bg.querySelector('input'), list = bg.querySelector('.pal-list');
  let sel = 0, items = CMDS;
  const close = () => bg.remove();
  const render = () => {
    const q = inp.value.toLowerCase().trim();
    items = CMDS.filter((c) => !q || (c.t + ' ' + c.hint).toLowerCase().includes(q));
    sel = Math.min(sel, Math.max(0, items.length - 1));
    list.innerHTML = items.length ? items.map((c, i) => `<div class="pal-item ${i === sel ? 'on' : ''}" data-i="${i}">${icon(c.ic, 16)}<span>${esc(c.t)}</span><em>${esc(c.hint)}</em></div>`).join('') : '<div class="pal-empty">Ничего не найдено</div>';
    list.querySelector('.on')?.scrollIntoView({ block: 'nearest' });
  };
  inp.oninput = () => { sel = 0; render(); };
  inp.onkeydown = (e) => {
    if (e.key === 'ArrowDown') { sel = (sel + 1) % items.length; render(); e.preventDefault(); }
    if (e.key === 'ArrowUp') { sel = (sel - 1 + items.length) % items.length; render(); e.preventDefault(); }
    if (e.key === 'Enter' && items[sel]) { close(); items[sel].run(); }
    if (e.key === 'Escape') close();
  };
  list.onclick = (e) => { const it = e.target.closest('.pal-item'); if (it) { close(); items[+it.dataset.i].run(); } };
  bg.onmousedown = (e) => { if (e.target === bg) close(); };
  render(); inp.focus();
}
addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openPalette(); }
  if ((e.ctrlKey || e.metaKey) && (e.key === '`' || e.key === '~' || e.code === 'Backquote') && cfg.registered) { e.preventDefault(); openIDE(); }
});
setInterval(() => { if (cfg.registered && vision.source) { const c = document.querySelector('#tbStatus .tchip:nth-child(2)'); if (c) c.lastChild.textContent = vision.fps + ' FPS'; } }, 1000);

// ---------------------------------------------------------------- автозапуск зрения и подключения
async function autoStartServices() {
  if (cfg.autoVision) {
    if (cfg.visionMode === 'server' && cfg.visionServer) vision.startStream(cfg.visionServer.replace(/\/+$/, '') + '/stream', 'Свой сервер');
    else {
      const py = await api.vision.start();               // Python-модуль (если установлен) — в фоне
      const r = await vision.startWebcam();             // встроенное зрение — сразу
      if (!r.ok && py.ok) { await sleep(1500); vision.startStream('http://127.0.0.1:8090/stream', 'STELLS Vision (Python)'); }
    }
  }
  const dev = cfg.devices?.[0];
  if (dev?.host) {
    const r = await link.connectWs(dev.host);
    if (r.ok && cfg.autoVision && !vision.source) vision.startStream(link.streamUrl(), 'Камера платы');
  }
  updateStatus();
}

// ---------------------------------------------------------------- старт
(async () => {
  [cfg, info] = await Promise.all([api.config.get(), api.info()]);
  try { const { Scene3D } = await import('./three-bg.js'); scene3d = new Scene3D(document.getElementById('bg')); }
  catch (e) { console.warn('3D недоступно', e); }
  if ('speechSynthesis' in window) speechSynthesis.getVoices();
  await splash();
  if (cfg.registered && cfg.sltKey && (await api.validateKey(cfg.sltKey)).ok) {
    dashboard('home');
    autoStartServices();
  } else if (cfg.registered) {
    toast('SLT-ключ отсутствует или недействителен — введите ключ', 'warn');
    modelStep();
  } else {
    welcome();
  }
})();

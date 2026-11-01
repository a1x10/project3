// Пульты управления: дроны, машины, роботы, камеры, Wake-on-LAN.
import { link } from './link.js';
import { vision, Vision } from './vision.js';
import { Drone3D } from './three-bg.js';
import { openIDE } from './ide.js';

const api = window.stells;
export const h = (html) => { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; };
export function toast(text, kind = '') {
  const el = h(`<div class="toast ${kind}"></div>`); el.textContent = text;
  document.getElementById('toasts').appendChild(el);
  setTimeout(() => { el.style.transition = '.4s'; el.style.opacity = '0'; setTimeout(() => el.remove(), 400); }, 4200);
}

// ---------------------------------------------------------------- общие элементы
function videoBox(id) {
  return `<div class="video" id="${id}">
    <canvas></canvas>
    <div class="empty" data-empty>Видео не запущено.<br>Выберите источник ниже: камера компьютера или камера платы.</div>
    <div class="hud-tl" data-hud-tl>—</div><div class="hud-tr" data-hud-tr></div>
  </div>`;
}
function mountVideo(root, id, { pick = false } = {}) {
  const box = root.querySelector('#' + id), cv = box.querySelector('canvas');
  const detach = vision.attach(cv);
  const upd = () => {
    box.querySelector('[data-empty]').style.display = vision.source ? 'none' : '';
    box.querySelector('[data-hud-tl]').textContent = vision.source ? `${vision.source.label} · ${vision.fps} FPS · свет ${vision.light}% · движение ${vision.motionLevel}%` : 'нет сигнала';
  };
  const t = setInterval(upd, 300); upd();
  if (pick) {
    cv.style.cursor = 'crosshair';
    cv.title = 'Нажмите на объект, чтобы система следила за ним по цвету';
    cv.addEventListener('click', (e) => {
      const r = cv.getBoundingClientRect();
      vision.pickColorAt((e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height);
      toast('Цель захвачена — машинное зрение отслеживает объект', 'ok');
    });
  }
  return () => { clearInterval(t); detach(); };
}
function sourceBar() {
  return `<div class="row wrap" style="margin-top:10px">
    <button class="btn sm" data-src="webcam">📷 Камера компьютера</button>
    <button class="btn sm" data-src="board">🛰 Камера платы</button>
    <button class="btn sm" data-src="py">🐍 Python-зрение</button>
    <button class="btn sm ghost" data-src="stop">■ Стоп</button>
  </div>`;
}
function bindSources(root) {
  root.querySelectorAll('[data-src]').forEach((b) => (b.onclick = async () => {
    const s = b.dataset.src;
    if (s === 'webcam') { const r = await vision.startWebcam(); if (!r.ok) toast(r.reason, 'err'); }
    if (s === 'board') { const u = link.streamUrl(); if (!u) return toast('Сначала подключите плату по сети (раздел «Плата»)', 'warn'); vision.startStream(u, 'Камера платы'); }
    if (s === 'py') {
      const st = await api.vision.status();
      if (!st.running) { const r = await api.vision.start(); if (!r.ok) return toast(r.reason, 'warn'); await new Promise((r) => setTimeout(r, 1500)); }
      vision.startStream('http://127.0.0.1:8090/stream', 'STELLS Vision (Python)');
    }
    if (s === 'stop') vision.stop();
  }));
}
function connBar(kind) {
  return `<div class="box glass">
    <h3><span class="dot" data-cdot></span> Подключение <span class="spacer"></span><span class="badge" data-clabel>—</span></h3>
    <div class="row wrap">
      <input class="input" style="flex:1;min-width:160px" placeholder="IP платы, напр. 192.168.1.50" data-host>
      <button class="btn sm primary" data-c="ws">Подключить</button>
      <button class="btn sm" data-c="find">🔍 Найти в сети</button>
      <button class="btn sm" data-c="usb">USB / Serial</button>
      ${kind === 'drone' ? '<button class="btn sm" data-c="ide">⌨ Свой коннектор</button>' : ''}
      <button class="btn sm" data-c="sim">Симулятор</button>
      <button class="btn sm ghost" data-c="off">Отключить</button>
    </div>
  </div>`;
}
function bindConn(root, cfg, onIde) {
  const host = root.querySelector('[data-host]');
  if (cfg.devices?.[0]) host.value = cfg.devices[0].host;
  const upd = () => {
    root.querySelector('[data-cdot]').className = 'dot ' + ({ online: 'on', connecting: 'wait', offline: '' }[link.state]);
    root.querySelector('[data-clabel]').textContent = link.label();
  };
  link.addEventListener('state', upd); upd();
  root.querySelectorAll('[data-c]').forEach((b) => (b.onclick = async () => {
    const c = b.dataset.c;
    if (c === 'ws') {
      if (!host.value.trim()) return toast('Введите IP-адрес платы или нажмите «Найти в сети»', 'warn');
      const r = await link.connectWs(host.value.trim());
      if (r.ok) { toast('Плата подключена: ' + (r.info.name || host.value), 'ok'); api.config.set({ devices: [{ host: host.value.trim(), name: r.info.name }] }); }
      else toast(r.reason + '. Если что-то не получается — обратитесь в службу поддержки.', 'err');
    }
    if (c === 'find') {
      toast('Ищу платы STELLS в локальной сети…');
      const list = await api.net.discover();
      if (!list.length) return toast('Платы не найдены. Проверьте, что агент установлен и плата в той же сети.', 'warn');
      host.value = list[0].host;
      toast(`Найдено: ${list.map((x) => `${x.name} (${x.host})`).join(', ')}`, 'ok');
    }
    if (c === 'usb') { const r = await link.connectSerial(); toast(r.ok ? 'USB-плата подключена' : r.reason, r.ok ? 'ok' : 'err'); }
    if (c === 'ide') onIde && onIde();
    if (c === 'sim') { link.startSim(); toast('Симулятор запущен — потренируйтесь без риска'); }
    if (c === 'off') link.disconnect();
  }));
  return () => link.removeEventListener('state', upd);
}

// виртуальный стик: возвращает {x,y} в диапазоне -1..1
function makeStick(el, { springY = true, onMove }) {
  const knob = el.querySelector('.knob');
  const v = { x: 0, y: springY ? 0 : -1 };
  const draw = () => { const r = el.clientWidth / 2 - 32; knob.style.transform = `translate(${v.x * r}px, ${v.y * r}px)`; };
  el.onpointerdown = (e) => {
    el.setPointerCapture(e.pointerId);
    const mv = (ev) => {
      const r = el.getBoundingClientRect(), R = r.width / 2 - 32;
      let x = (ev.clientX - r.left - r.width / 2) / R, y = (ev.clientY - r.top - r.height / 2) / R;
      const m = Math.hypot(x, y); if (m > 1) { x /= m; y /= m; }
      v.x = x; v.y = y; draw(); onMove(v);
    };
    mv(e);
    el.onpointermove = mv;
    el.onpointerup = el.onpointercancel = () => { el.onpointermove = null; v.x = 0; if (springY) v.y = 0; draw(); onMove(v); };
  };
  draw();
  return { v, set(x, y) { v.x = x; v.y = y; draw(); } };
}

// ---------------------------------------------------------------- ДРОН
export function mountDrone(root, cfg) {
  root.innerHTML = '';
  const page = h(`<div class="page">
    <div class="page-head"><h2>🛸 Пульт дрона</h2><span class="badge beta">закрытое тестирование</span><span class="spacer"></span>
      <span class="badge" id="dMode">—</span><span class="badge" id="dArm">DISARMED</span></div>
    ${connBar('drone')}
    <div class="cols main-side">
      <div class="box glass">
        ${videoBox('dVideo')}
        ${sourceBar()}
        <div class="row wrap" style="margin-top:10px">
          <label class="check"><input type="checkbox" id="aiPilot"> AI-пилот (бета): следовать за целью — нажмите на объект в видео</label>
        </div>
      </div>
      <div class="box glass" style="display:flex;flex-direction:column">
        <h3>3D-ориентация <span class="spacer"></span><span class="badge live" id="dLink">—</span></h3>
        <div id="d3d" style="flex:1;min-height:200px;border-radius:12px;overflow:hidden;background:radial-gradient(circle,#0e1440,#04050c)"></div>
        <div class="cols c3" style="margin-top:10px" id="dTel"></div>
      </div>
    </div>
    <div class="cols main-side">
      <div class="box glass">
        <h3>Управление <span class="spacer"></span><span class="muted small">клавиатура: W/S газ, A/D рыскание, стрелки — крен/тангаж · геймпад поддерживается</span></h3>
        <div class="sticks">
          <div><div class="stick" id="stL"><div class="knob"></div></div><div class="stick-label">Газ / Рыскание</div></div>
          <div style="display:flex;flex-direction:column;gap:8px;justify-content:center;min-width:220px">
            <div class="btngrid">
              <button class="btn sm ok" data-d="arm">ARM</button>
              <button class="btn sm danger" data-d="disarm">DISARM</button>
              <button class="btn sm" data-d="rtl">⌂ RTL</button>
              <button class="btn sm primary" data-d="takeoff">▲ Взлёт</button>
              <button class="btn sm" data-d="land">▼ Посадка</button>
              <button class="btn sm danger" data-d="kill">✋ СТОП</button>
            </div>
            <div class="row"><span class="small muted">Высота взлёта</span><input type="range" class="slider" id="toAlt" min="1" max="30" value="3"><b id="toAltV">3 м</b></div>
            <select class="input" id="dModeSel" style="padding:9px 12px">
              ${['STABILIZE', 'ALT_HOLD', 'LOITER', 'GUIDED', 'POSHOLD', 'AUTO', 'RTL', 'LAND'].map((m) => `<option>${m}</option>`).join('')}
            </select>
          </div>
          <div><div class="stick" id="stR"><div class="knob"></div></div><div class="stick-label">Тангаж / Крен</div></div>
        </div>
      </div>
      <div class="box glass">
        <div class="tabs"><button class="tab on" data-t="wire">Подключение</button><button class="tab" data-t="remote">Удалённо</button><button class="tab" data-t="use">Как пользоваться</button></div>
        <div id="dHelp" style="font-size:13px;line-height:1.6;color:var(--muted);max-height:300px;overflow:auto"></div>
      </div>
    </div>
    <div class="script-card" id="scriptCard">
      <div class="row"><h3 style="margin:0">⌨ Ни один вариант не подошёл? Напишите свой скрипт подключения</h3><span class="spacer"></span><span class="badge beta">наведите / нажмите</span></div>
      <div class="muted small" style="margin-top:6px">Откроется редактор как VS Code с настоящим терминалом. Пишите коннектор на любом языке (Python, C++, Rust, Go, JS, Lua…), нажмите «Подключить коннектор» — и пульт начнёт управлять вашим дроном через него.</div>
      <div class="code-peek">for line in sys.stdin:\n    cmd = json.loads(line)        # команды пульта\n    my_drone.send(cmd)             # ваш протокол\n    print(json.dumps(telemetry))   # телеметрия в пульт</div>
    </div>
  </div>`);
  root.appendChild(page);

  const HELP = {
    wire: `<b style="color:var(--text)">Плата + полётный контроллер (ArduPilot / PX4 / Betaflight через MSP→MAVLink)</b><br>
      1. Полётный контроллер <b>TELEM2 TX → RX платы</b> (Raspberry Pi GPIO15), <b>RX → TX</b> (GPIO14), <b>GND → GND</b>. Питание платы — отдельный BEC 5 В 3 А.<br>
      2. Raspberry Pi: <code>sudo raspi-config</code> → Interface → Serial: login shell — НЕТ, hardware — ДА. Порт: <code>/dev/serial0</code>.<br>
      3. В полётном контроллере: <code>SERIAL2_PROTOCOL = 2</code> (MAVLink2), <code>SERIAL2_BAUD = 57</code>.<br>
      4. Камера: CSI или USB-камера в плату — видео пойдёт в пульт автоматически.<br>
      5. Через USB: подключите контроллер к плате кабелем и укажите в <code>stells-config.json</code> → <code>"connection": "/dev/ttyACM0"</code>.<br>
      6. Установите прошивку на плату (<code>sudo bash install.sh</code>), затем «Найти в сети» → «Подключить».<br><br>
      <b style="color:var(--amber)">Безопасность:</b> первые тесты — без пропеллеров. Держите рядом обычный RC-пульт для перехвата управления.`,
    remote: `<b style="color:var(--text)">Управление дроном удалённо (не в одной Wi-Fi сети)</b><br>
      <b>Вариант 1 — Tailscale / ZeroTier (рекомендуется).</b> Установите на плату и на компьютер: <code>curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up</code>. В приложении введите IP плата из Tailscale (100.x.x.x).<br>
      <b>Вариант 2 — 4G/5G-модем</b> на дроне (USB-модем или HAT) + Tailscale. Дрон управляем из любой точки с интернетом.<br>
      <b>Вариант 3 — проброс портов</b> 8765 и 8766 на роутере к IP платы. Обязательно задайте <code>"token"</code> в <code>stells-config.json</code>.<br>
      <b>Вариант 4 — свой сервер:</b> агент и приложение подключаются к вашему VPS (WireGuard), а пульт — к IP в VPN.<br>
      <b>Вариант 5 — телеметрийный радиомодем</b> (SiK 433/915 МГц) в USB компьютера → свой коннектор с <code>pymavlink</code> на COM-порт.<br>
      Задержка видео растёт с расстоянием — снизьте разрешение камеры в конфиге платы.`,
    use: `1. Подключитесь (Плата / USB / Коннектор / Симулятор). Индикатор станет зелёным.<br>
      2. <b>ARM</b> — запуск моторов. <b>Взлёт</b> — авто-взлёт на высоту из ползунка (режим GUIDED).<br>
      3. Левый стик: вверх/вниз — газ, влево/вправо — поворот. Правый стик: наклон вперёд/назад и вбок.<br>
      4. <b>Посадка</b> — мягкая посадка на месте, <b>RTL</b> — возврат в точку взлёта.<br>
      5. <b>СТОП</b> — аварийное выключение моторов (дрон упадёт!).<br>
      6. AI-пилот: включите видео, отметьте флажок и нажмите на объект — дрон будет поворачиваться и держать цель в центре кадра.<br>
      Если связь теряется на 1,5 с — команды движения обнуляются (failsafe).`,
  };
  const help = page.querySelector('#dHelp');
  const setTab = (t) => { page.querySelectorAll('.tab').forEach((b) => b.classList.toggle('on', b.dataset.t === t)); help.innerHTML = HELP[t]; };
  page.querySelectorAll('.tab').forEach((b) => (b.onclick = () => setTab(b.dataset.t)));
  setTab('wire');

  const offConn = bindConn(page, cfg, () => openIDE({ onConnected: betaOffer }));
  bindSources(page);
  const offVideo = mountVideo(page, 'dVideo', { pick: true });
  let d3;
  try { d3 = new Drone3D(page.querySelector('#d3d')); }
  catch { d3 = { set() {}, dispose() {} }; page.querySelector('#d3d').innerHTML = '<div class="empty muted small" style="display:grid;place-items:center;height:100%">3D недоступно: обновите драйвер видеокарты</div>'; }

  // скрипт-карточка: открытие по наведению (с задержкой) или по клику
  const card = page.querySelector('#scriptCard');
  let hoverT;
  card.onmouseenter = () => { hoverT = setTimeout(() => openIDE({ onConnected: betaOffer }), 900); };
  card.onmouseleave = () => clearTimeout(hoverT);
  card.onclick = () => { clearTimeout(hoverT); openIDE({ onConnected: betaOffer }); };

  // команды
  const toAlt = page.querySelector('#toAlt');
  toAlt.oninput = () => (page.querySelector('#toAltV').textContent = toAlt.value + ' м');
  page.querySelectorAll('[data-d]').forEach((b) => (b.onclick = () => {
    const c = b.dataset.d;
    if (link.state !== 'online') return toast('Нет подключения к дрону', 'warn');
    if (c === 'kill') { link.send({ type: 'drone', cmd: 'disarm', force: true }); return toast('Аварийная остановка моторов', 'err'); }
    link.send({ type: 'drone', cmd: c, value: c === 'takeoff' ? Number(toAlt.value) : undefined });
    toast('Команда: ' + c.toUpperCase());
  }));
  page.querySelector('#dModeSel').onchange = (e) => link.send({ type: 'drone', cmd: 'mode', value: e.target.value });

  const rc = { roll: 0, pitch: 0, yaw: 0, throttle: 0 };
  const L = makeStick(page.querySelector('#stL'), { springY: false, onMove: (v) => { rc.yaw = v.x; rc.throttle = (1 - v.y) / 2; } });
  const R = makeStick(page.querySelector('#stR'), { onMove: (v) => { rc.roll = v.x; rc.pitch = -v.y; } });
  const keys = new Set();
  const kd = (e) => { if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return; keys.add(e.code); };
  const ku = (e) => keys.delete(e.code);
  addEventListener('keydown', kd); addEventListener('keyup', ku);

  const aiBox = page.querySelector('#aiPilot');
  const loop = setInterval(() => {
    // клавиатура
    if (keys.size) {
      if (keys.has('KeyW')) rc.throttle = Math.min(1, rc.throttle + 0.02);
      if (keys.has('KeyS')) rc.throttle = Math.max(0, rc.throttle - 0.02);
      rc.yaw = keys.has('KeyA') ? -0.6 : keys.has('KeyD') ? 0.6 : rc.yaw;
      rc.pitch = keys.has('ArrowUp') ? 0.6 : keys.has('ArrowDown') ? -0.6 : rc.pitch;
      rc.roll = keys.has('ArrowLeft') ? -0.6 : keys.has('ArrowRight') ? 0.6 : rc.roll;
      L.set(rc.yaw, 1 - rc.throttle * 2); R.set(rc.roll, -rc.pitch);
    }
    // геймпад (Mode 2)
    const gp = navigator.getGamepads?.()[0];
    if (gp) {
      const dz = (x) => (Math.abs(x) < 0.08 ? 0 : x);
      rc.yaw = dz(gp.axes[0]); rc.throttle = (1 - gp.axes[1]) / 2; rc.roll = dz(gp.axes[2]); rc.pitch = -dz(gp.axes[3]);
      L.set(rc.yaw, gp.axes[1]); R.set(rc.roll, -rc.pitch);
    }
    // AI-пилот: держим цель в центре кадра
    if (aiBox.checked && vision.target) {
      rc.yaw = Math.max(-1, Math.min(1, (vision.target.x - 0.5) * 2.2));
      rc.pitch = Math.max(-0.5, Math.min(0.5, (0.12 - vision.target.size) * 3));
    }
    if (link.state === 'online') link.send({ type: 'rc', ...rc });
  }, 50);

  const tel = page.querySelector('#dTel');
  const onTel = (e) => {
    const d = e.detail.drone || {};
    d3.set(d);
    page.querySelector('#dArm').textContent = d.armed ? 'ARMED' : 'DISARMED';
    page.querySelector('#dArm').className = 'badge ' + (d.armed ? 'live' : '');
    page.querySelector('#dMode').textContent = d.mode || '—';
    const items = [['Высота', d.alt, 'м'], ['Батарея', d.battery, '%'], ['Скорость', d.speed, 'м/с'], ['Крен', d.roll, '°'], ['Тангаж', d.pitch, '°'], ['Курс', d.yaw ?? d.heading, '°'], ['Спутники', d.sats, ''], ['Широта', d.lat?.toFixed?.(5), ''], ['Долгота', d.lon?.toFixed?.(5), '']];
    tel.innerHTML = items.map(([k, v, u]) => `<div class="stat" style="padding:8px 10px;background:rgba(255,255,255,.03);border-radius:10px"><div class="k" style="font-size:10px">${k}</div><div class="v" style="font-size:17px">${v ?? '—'} <small>${v != null ? u : ''}</small></div></div>`).join('');
  };
  link.addEventListener('telemetry', onTel);
  onTel({ detail: link.telemetry });
  const onState = () => (page.querySelector('#dLink').textContent = link.label());
  link.addEventListener('state', onState); onState();

  function betaOffer() {
    modal(`<h2>🎉 Коннектор подключён к дрону</h2>
      <p class="lead">Система предлагает <b>бета-тест программы управления дроном с ИИ</b>: AI-пилот использует машинное зрение,
      чтобы следовать за выбранным объектом и держать его в центре кадра.</p>
      <div class="howto">
        <div class="step"><span class="num">1</span><b>Видео</b>Включите «Камера платы» или «Камера компьютера» под видео.</div>
        <div class="step"><span class="num">2</span><b>Цель</b>Нажмите на объект в видео — он подсветится розовым прицелом.</div>
        <div class="step"><span class="num">3</span><b>Взлёт</b>ARM → «Взлёт». Убедитесь, что вокруг свободно 5+ метров.</div>
        <div class="step"><span class="num">4</span><b>AI-пилот</b>Включите флажок «AI-пилот». Ручные стики всегда имеют приоритет — отпустите флажок, чтобы перехватить.</div>
      </div>
      <div class="actions"><button class="btn" data-close>Позже</button><button class="btn primary" data-yes>Участвовать в бета-тесте<span class="shine"></span></button></div>`,
      (m) => { m.querySelector('[data-yes]').onclick = () => { aiBox.checked = true; toast('AI-пилот (бета) включён. Нажмите на цель в видео.', 'ok'); m.close(); }; });
  }

  return () => { offConn(); offVideo(); d3.dispose(); clearInterval(loop); removeEventListener('keydown', kd); removeEventListener('keyup', ku); link.removeEventListener('telemetry', onTel); link.removeEventListener('state', onState); };
}

// ---------------------------------------------------------------- МАШИНА
export function mountCar(root, cfg) {
  root.innerHTML = '';
  const page = h(`<div class="page">
    <div class="page-head"><h2>🚗 Пульт машины / ровера</h2><span class="badge beta">закрытое тестирование</span></div>
    ${connBar('car')}
    <div class="cols main-side">
      <div class="box glass">${videoBox('cVideo')}${sourceBar()}
        <label class="check" style="margin-top:10px"><input type="checkbox" id="cAuto"> Автопилот (бета): ехать за целью — нажмите на объект в видео</label></div>
      <div class="box glass">
        <h3>Руль и газ</h3>
        <div style="display:grid;place-items:center"><div class="stick" id="cStick" style="width:220px;height:220px"><div class="knob"></div></div></div>
        <div class="row" style="margin-top:14px"><span class="small muted">Макс. скорость</span><input type="range" class="slider" id="cSpeed" min="10" max="100" value="60"><b id="cSpeedV">60%</b></div>
        <div class="btngrid" style="margin-top:12px">
          <button class="btn sm" id="cLights">💡 Фары</button><button class="btn sm danger" id="cStop">■ Стоп</button><button class="btn sm" id="cHorn">📢 Сигнал</button>
        </div>
        <div class="kv" style="margin-top:14px" id="cTel"></div>
        <p class="small muted">Клавиатура: W/A/S/D или стрелки. Схема: L298N/TB6612, левый мотор GPIO 17/18, правый 22/23, фары GPIO 27 (меняется в stells-config.json).</p>
      </div>
    </div>
  </div>`);
  root.appendChild(page);
  const offConn = bindConn(page, cfg); bindSources(page);
  const offVideo = mountVideo(page, 'cVideo', { pick: true });
  const cmd = { x: 0, y: 0 };
  const st = makeStick(page.querySelector('#cStick'), { onMove: (v) => { cmd.x = v.x; cmd.y = -v.y; } });
  const sp = page.querySelector('#cSpeed'); sp.oninput = () => (page.querySelector('#cSpeedV').textContent = sp.value + '%');
  let lights = false;
  page.querySelector('#cLights').onclick = () => { lights = !lights; link.send({ type: 'lights', on: lights }); };
  page.querySelector('#cStop').onclick = () => { cmd.x = cmd.y = 0; st.set(0, 0); link.send({ type: 'stop' }); };
  page.querySelector('#cHorn').onclick = () => { link.send({ type: 'pin', pin: 24, value: 1 }); setTimeout(() => link.send({ type: 'pin', pin: 24, value: 0 }), 400); };
  const keys = new Set();
  const kd = (e) => { if (e.target.tagName !== 'INPUT') keys.add(e.code); }, ku = (e) => keys.delete(e.code);
  addEventListener('keydown', kd); addEventListener('keyup', ku);
  const auto = page.querySelector('#cAuto');
  const loop = setInterval(() => {
    if (keys.size) {
      cmd.y = (keys.has('KeyW') || keys.has('ArrowUp') ? 1 : 0) - (keys.has('KeyS') || keys.has('ArrowDown') ? 1 : 0);
      cmd.x = (keys.has('KeyD') || keys.has('ArrowRight') ? 1 : 0) - (keys.has('KeyA') || keys.has('ArrowLeft') ? 1 : 0);
      st.set(cmd.x * 0.7, -cmd.y * 0.7);
    }
    if (auto.checked && vision.target) { cmd.x = (vision.target.x - 0.5) * 2; cmd.y = Math.max(0, Math.min(0.8, (0.15 - vision.target.size) * 4)); }
    const k = sp.value / 100;
    if (link.state === 'online') link.send({ type: 'drive', x: +(cmd.x * k).toFixed(2), y: +(cmd.y * k).toFixed(2) });
  }, 80);
  const onTel = (e) => { const s = e.detail.system || {}; page.querySelector('#cTel').innerHTML = `<span>Плата</span><span>${s.host || s.model || '—'}</span><span>Температура</span><span>${s.temp ?? '—'} °C</span><span>Нагрузка</span><span>${s.load ?? '—'}</span>`; };
  link.addEventListener('telemetry', onTel); onTel({ detail: link.telemetry });
  return () => { offConn(); offVideo(); clearInterval(loop); removeEventListener('keydown', kd); removeEventListener('keyup', ku); link.removeEventListener('telemetry', onTel); };
}

// ---------------------------------------------------------------- РОБОТ
export function mountRobot(root, cfg) {
  root.innerHTML = '';
  const names = ['Основание', 'Плечо', 'Локоть', 'Захват'];
  const page = h(`<div class="page">
    <div class="page-head"><h2>🤖 Пульт робота</h2><span class="badge beta">закрытое тестирование</span></div>
    ${connBar('robot')}
    <div class="cols main-side">
      <div class="box glass">${videoBox('rVideo')}${sourceBar()}</div>
      <div class="box glass">
        <h3>Сервоприводы</h3>
        ${names.map((n, i) => `<div class="field"><label>${n} — <b id="sv${i}">0°</b></label><input type="range" class="slider" min="-90" max="90" value="0" data-servo="${i}"></div>`).join('')}
        <div class="btngrid">
          <button class="btn sm" data-pose="home">⌂ Домой</button><button class="btn sm" data-pose="grab">✊ Взять</button><button class="btn sm" data-pose="drop">✋ Отпустить</button>
          <button class="btn sm" data-pose="rec">● Запомнить</button><button class="btn sm" data-pose="play">▶ Повторить</button><button class="btn sm danger" data-pose="stop">■ Стоп</button>
        </div>
        <p class="small muted">Сервоприводы: GPIO 12, 13, 19, 26 (Linux-платы) или пины 3, 10, 11, 12 (Arduino).</p>
      </div>
    </div>
  </div>`);
  root.appendChild(page);
  const offConn = bindConn(page, cfg); bindSources(page);
  const offVideo = mountVideo(page, 'rVideo', { pick: true });
  const sliders = [...page.querySelectorAll('[data-servo]')];
  const setServo = (i, a) => { sliders[i].value = a; page.querySelector('#sv' + i).textContent = a + '°'; link.send({ type: 'servo', index: i, angle: Number(a) }); };
  sliders.forEach((s, i) => (s.oninput = () => setServo(i, s.value)));
  let recorded = [], playT = null;
  const POSES = { home: [0, 0, 0, 0], grab: [null, 30, -40, 60], drop: [null, null, null, -30] };
  page.querySelectorAll('[data-pose]').forEach((b) => (b.onclick = () => {
    const p = b.dataset.pose;
    if (POSES[p]) POSES[p].forEach((a, i) => a != null && setServo(i, a));
    if (p === 'rec') { recorded.push(sliders.map((s) => s.value)); toast(`Поза ${recorded.length} сохранена`, 'ok'); }
    if (p === 'play') { let k = 0; clearInterval(playT); if (!recorded.length) return toast('Сначала запомните позы', 'warn'); playT = setInterval(() => { recorded[k].forEach((a, i) => setServo(i, a)); if (++k >= recorded.length) clearInterval(playT); }, 900); }
    if (p === 'stop') { clearInterval(playT); link.send({ type: 'stop' }); }
  }));
  return () => { offConn(); offVideo(); clearInterval(playT); };
}

// ---------------------------------------------------------------- КАМЕРЫ
export function mountCameras(root, cfg) {
  root.innerHTML = '';
  const page = h(`<div class="page">
    <div class="page-head"><h2>📷 Камеры с ИИ</h2><span class="badge beta">закрытое тестирование</span><span class="spacer"></span>
      <button class="btn sm" id="camSnap">📸 Снимок</button><button class="btn sm" id="camRec">⏺ Запись</button></div>
    <div class="cols main-side">
      <div class="box glass">${videoBox('camMain')}${sourceBar()}
        <div class="row wrap" style="margin-top:10px">
          <select class="input" id="camList" style="flex:1;padding:9px 12px"></select>
          <label class="check"><input type="checkbox" id="camAlert" checked> Уведомлять о движении</label>
          <span class="small muted">Чувствительность</span><input type="range" class="slider" id="camSens" min="8" max="60" value="28" style="width:140px">
        </div>
      </div>
      <div class="box glass" style="display:flex;flex-direction:column">
        <h3>Камеры платы / IP-камеры</h3>
        <div class="row"><input class="input" id="camUrl" placeholder="http://192.168.1.50:8766/stream или RTSP через агент"><button class="btn sm primary" id="camAdd">+</button></div>
        <div id="camExtra" class="cols c2" style="margin-top:10px"></div>
        <h3 style="margin-top:14px">Журнал событий</h3>
        <div class="log" id="camLog" style="flex:1;min-height:140px"></div>
      </div>
    </div>
  </div>`);
  root.appendChild(page);
  bindSources(page);
  const offVideo = mountVideo(page, 'camMain', { pick: true });
  const list = page.querySelector('#camList');
  Vision.cameras().then((cams) => {
    list.innerHTML = cams.length ? cams.map((c, i) => `<option value="${c.deviceId}">${c.label || 'Камера ' + (i + 1)}</option>`).join('') : '<option>Камеры не найдены</option>';
  });
  list.onchange = () => vision.startWebcam(list.value);
  page.querySelector('#camSens').oninput = (e) => (vision.opts.sensitivity = 68 - Number(e.target.value));
  const log = page.querySelector('#camLog');
  let lastAlert = 0;
  const onFrame = (e) => {
    const m = e.detail.detections.filter((d) => d.kind !== 'target');
    if (m.length && page.querySelector('#camAlert').checked && Date.now() - lastAlert > 4000) {
      lastAlert = Date.now();
      log.textContent = `[${new Date().toLocaleTimeString()}] ${m.map((d) => d.label).join(', ')} (${m.length})\n` + log.textContent;
      if (Notification.permission === 'granted') new Notification('STELLS: обнаружено движение', { body: m.map((d) => d.label).join(', ') });
      else Notification.requestPermission();
    }
  };
  vision.addEventListener('frame', onFrame);
  const mainCanvas = page.querySelector('#camMain canvas');
  page.querySelector('#camSnap').onclick = () => {
    const a = document.createElement('a'); a.download = `stells-${Date.now()}.png`; a.href = mainCanvas.toDataURL('image/png'); a.click();
    toast('Снимок сохранён в «Загрузки»', 'ok');
  };
  let rec = null;
  page.querySelector('#camRec').onclick = (e) => {
    if (rec) { rec.stop(); return; }
    const chunks = [];
    rec = new MediaRecorder(mainCanvas.captureStream(25), { mimeType: 'video/webm' });
    rec.ondataavailable = (ev) => chunks.push(ev.data);
    rec.onstop = () => {
      const a = document.createElement('a'); a.download = `stells-${Date.now()}.webm`; a.href = URL.createObjectURL(new Blob(chunks, { type: 'video/webm' })); a.click();
      e.target.textContent = '⏺ Запись'; e.target.classList.remove('danger'); rec = null; toast('Видео сохранено', 'ok');
    };
    rec.start(); e.target.textContent = '■ Остановить'; e.target.classList.add('danger');
  };
  const extra = page.querySelector('#camExtra');
  const addCam = (url) => {
    const el = h(`<div class="video" style="aspect-ratio:4/3"><img alt=""><div class="hud-bl"></div></div>`);
    el.querySelector('img').src = url; el.querySelector('.hud-bl').textContent = url.replace(/^https?:\/\//, '');
    el.title = 'Нажмите, чтобы анализировать эту камеру ИИ'; el.style.cursor = 'pointer';
    el.onclick = () => vision.startStream(url, url);
    extra.appendChild(el);
  };
  if (link.streamUrl()) addCam(link.streamUrl());
  page.querySelector('#camAdd').onclick = () => { const u = page.querySelector('#camUrl').value.trim(); if (u) addCam(u); };
  return () => { offVideo(); vision.removeEventListener('frame', onFrame); if (rec) rec.stop(); };
}

// ---------------------------------------------------------------- WAKE-ON-LAN
export function mountWol(root, cfg) {
  root.innerHTML = '';
  const page = h(`<div class="page">
    <div class="page-head"><h2>⚡ Wake-on-LAN</h2><span class="badge beta">закрытое тестирование</span></div>
    <div class="cols main-side">
      <div class="box glass">
        <h3>Устройства</h3>
        <div id="wolList"></div>
        <div class="row wrap" style="margin-top:12px">
          <input class="input" id="wName" placeholder="Название (Рабочий ПК)" style="flex:1">
          <input class="input" id="wMac" placeholder="MAC: AA:BB:CC:DD:EE:FF" style="flex:1">
          <input class="input" id="wBc" placeholder="Broadcast (255.255.255.255)" style="flex:1">
          <button class="btn primary" id="wAdd">Добавить</button>
        </div>
      </div>
      <div class="box glass" style="font-size:13px;line-height:1.6;color:var(--muted)">
        <h3 style="color:var(--text)">Как настроить</h3>
        1. В BIOS/UEFI компьютера включите <b>Wake on LAN / Power On by PCI-E</b>.<br>
        2. Windows: Диспетчер устройств → сетевая карта → «Управление электропитанием» → «Разрешить этому устройству выводить компьютер из ждущего режима» + «Только магический пакет».<br>
        3. Linux: <code>sudo ethtool -s eth0 wol g</code>.<br>
        4. Узнайте MAC: <code>ipconfig /all</code> или <code>ip link</code>.<br>
        5. Через интернет: подключите плату STELLS в ту же сеть — команда «через плату» разбудит ПК даже удалённо (по Tailscale).<br><br>
        <b style="color:var(--text)">Сетевые интерфейсы этого компьютера:</b><div id="wIf"></div>
      </div>
    </div>
  </div>`);
  root.appendChild(page);
  let devices = [...(cfg.wol || [])];
  const save = () => api.config.set({ wol: devices });
  const render = () => {
    const l = page.querySelector('#wolList');
    l.innerHTML = devices.length ? '' : '<p class="muted">Добавьте компьютер, который нужно включать по сети.</p>';
    devices.forEach((d, i) => {
      const row = h(`<div class="row" style="padding:12px;border-radius:12px;background:rgba(255,255,255,.03);margin-bottom:8px">
        <div class="avatar" style="width:34px;height:34px;font-size:15px">⚡</div>
        <div style="flex:1"><b></b><div class="small muted"></div></div>
        <button class="btn sm primary" data-w="pc">Разбудить</button><button class="btn sm" data-w="board">Через плату</button><button class="btn sm ghost" data-w="del">✕</button></div>`);
      row.querySelector('b').textContent = d.name; row.querySelector('.small').textContent = `${d.mac} · ${d.broadcast}`;
      row.querySelector('[data-w=pc]').onclick = async () => { const r = await api.net.wol(d); toast(r.ok ? `Магический пакет отправлен на ${d.name}` : r.reason, r.ok ? 'ok' : 'err'); };
      row.querySelector('[data-w=board]').onclick = () => toast(link.send({ type: 'wol', mac: d.mac, broadcast: d.broadcast }) ? 'Команда отправлена через плату' : 'Плата не подключена', link.state === 'online' ? 'ok' : 'warn');
      row.querySelector('[data-w=del]').onclick = () => { devices.splice(i, 1); save(); render(); };
      l.appendChild(row);
    });
  };
  page.querySelector('#wAdd').onclick = () => {
    const mac = page.querySelector('#wMac').value.trim();
    if (mac.replace(/[^0-9a-f]/gi, '').length !== 12) return toast('MAC-адрес должен содержать 12 hex-символов', 'err');
    devices.push({ name: page.querySelector('#wName').value.trim() || 'Компьютер', mac, broadcast: page.querySelector('#wBc').value.trim() || '255.255.255.255' });
    save(); render();
  };
  api.net.interfaces().then((l) => (page.querySelector('#wIf').innerHTML = l.map((i) => `<div><code>${i.name}</code> ${i.address} · MAC ${i.mac}</div>`).join('')));
  render();
  return () => {};
}

// ---------------------------------------------------------------- модальное окно
export function modal(html, init) {
  const bg = h(`<div class="modal-bg"><div class="modal glass">${html}</div></div>`);
  document.getElementById('modalRoot').appendChild(bg);
  const m = bg.querySelector('.modal');
  m.close = () => { bg.style.transition = '.25s'; bg.style.opacity = '0'; setTimeout(() => bg.remove(), 250); };
  m.querySelectorAll('[data-close]').forEach((b) => (b.onclick = m.close));
  init && init(m);
  return m;
}

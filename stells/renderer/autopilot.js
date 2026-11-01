// ИИ-автопилот дрона STELLS:
//  * Mixer       — микшер 4 моторов (квадрокоптер X, ШИМ 1000–2000 мкс)
//  * Commander   — ИИ-командир: разбирает русский текст в пошаговый план полёта
//  * Autopilot   — выполняет план: взлёт, повороты, полёт, змейка, круг, слежение за целью
//  * Arena       — виртуальная 3D-арена с летающей красной мишенью (тест без дрона)
//  * selfCheck   — самодиагностика 4 узлов: зрение/FPS, микшер, командир, DISARM
import * as THREE from '../node_modules/three/build/three.module.js';
import { link } from './link.js';
import { vision } from './vision.js';

// ------------------------------------------------------------------ микшер
// Нумерация как в ArduPilot (Quad X): M1 передний правый, M2 задний левый,
// M3 передний левый, M4 задний правый. M1/M2 вращаются против часовой, M3/M4 — по часовой.
export const MOTORS = [
  { id: 'M1', pos: 'FR', name: 'передний правый' },
  { id: 'M2', pos: 'RL', name: 'задний левый' },
  { id: 'M3', pos: 'FL', name: 'передний левый' },
  { id: 'M4', pos: 'RR', name: 'задний правый' },
];
export const PWM_MIN = 1000, PWM_MAX = 2000, PWM_IDLE = 1100;

/** base — газ в мкс; roll/pitch/yaw — поправки в мкс (+pitch = вперёд, +roll = вправо, +yaw = по часовой). */
export function mixMotors(base, roll, pitch, yaw, armed = true) {
  if (!armed) return [PWM_MIN, PWM_MIN, PWM_MIN, PWM_MIN];
  const m = [
    base - pitch - roll + yaw, // M1 FR
    base + pitch + roll + yaw, // M2 RL
    base - pitch + roll - yaw, // M3 FL
    base + pitch - roll - yaw, // M4 RR
  ];
  return m.map((v) => Math.round(Math.max(PWM_IDLE, Math.min(PWM_MAX, v))));
}

/** Перевод команд пульта (-1..1, газ 0..1) в ШИМ моторов. */
export function rcToMotors(rc, armed) {
  return mixMotors(1000 + rc.throttle * 960, rc.roll * 200, rc.pitch * 200, rc.yaw * 150, armed);
}

// ------------------------------------------------------------------ ИИ-командир (русский текст)
const NUM_WORDS = {
  ноль: 0, один: 1, одна: 1, одну: 1, раз: 1, два: 2, две: 2, три: 3, четыре: 4, пять: 5, шесть: 6, семь: 7, восемь: 8, девять: 9,
  десять: 10, одиннадцать: 11, двенадцать: 12, тринадцать: 13, четырнадцать: 14, пятнадцать: 15, шестнадцать: 16, семнадцать: 17,
  восемнадцать: 18, девятнадцать: 19, двадцать: 20, тридцать: 30, сорок: 40, пятьдесят: 50, шестьдесят: 60, семьдесят: 70,
  восемьдесят: 80, девяносто: 90, сто: 100, двести: 200, триста: 300, полтора: 1.5, полторы: 1.5, пол: 0.5,
};
function wordsToDigits(t) {
  return t.replace(/(?:(?<![а-яa-z])(?:ноль|один|одна|одну|два|две|три|четыре|пять|шесть|семь|восемь|девять|десять|одиннадцать|двенадцать|тринадцать|четырнадцать|пятнадцать|шестнадцать|семнадцать|восемнадцать|девятнадцать|двадцать|тридцать|сорок|пятьдесят|шестьдесят|семьдесят|восемьдесят|девяносто|сто|двести|триста|полтора|полторы)(?![а-яa-z])\s*)+/g,
    (m) => ' ' + m.trim().split(/\s+/).reduce((a, w) => a + (NUM_WORDS[w] ?? 0), 0) + ' ');
}
const num = (s, re, def) => { const m = s.match(re); return m ? parseFloat(m[1].replace(',', '.')) : def; };
const METERS = /(\d+(?:[.,]\d+)?)\s*(?:м(?![а-я])|метр)/;
const SECONDS = /(\d+(?:[.,]\d+)?)\s*(?:с(?![а-я])|сек)/;
const DEGREES = /(\d+(?:[.,]\d+)?)\s*(?:°|град)/;

function parseClause(c) {
  const s = c.trim();
  if (!s) return null;
  if (/(стоп мотор|выключи мотор|заглуши|disarm|дизарм|аварийн)/.test(s)) return { kind: 'disarm', label: 'Аварийно выключить моторы' };
  if (/(взлет|взлёт|взлети|взлетай|подними(сь)? в воздух|старт)/.test(s)) { const h = num(s, METERS, 3); return { kind: 'takeoff', h, label: `Взлёт на ${h} м` }; }
  if (/(сядь|садись|приземл|посадк|сажай)/.test(s)) return { kind: 'land', label: 'Посадка' };
  if (/(домой|(?<![а-я])вернись|возврат|на базу|rtl)/.test(s)) return { kind: 'rtl', label: 'Возврат домой (RTL)' };
  if (/(сфотограф|снимок|фото|сними)/.test(s)) return { kind: 'photo', label: 'Сделать снимок' };
  if (/змейк/.test(s)) { const t = num(s, SECONDS, 6); return { kind: 'snake', t, label: `Полёт змейкой ${t} с` }; }
  if (/квадрат/.test(s)) { const t = num(s, SECONDS, 2); return { kind: 'square', t, label: `Облёт квадратом (сторона ${t} с)` }; }
  if (/(круг|облети|вокруг|орбит)/.test(s)) { const t = num(s, SECONDS, 8); return { kind: 'circle', t, label: `Полёт по кругу ${t} с` }; }
  if (/(найди|ищи|поиск)/.test(s)) {
    const what = /человек/.test(s) ? 'человека' : 'цель';
    const t = num(s, SECONDS, 12); return { kind: 'follow', search: true, t, label: `Найти ${what} и следить ${t} с` };
  }
  if (/(следи|следуй|преследуй|сопровожд|держи цель|захвати|лети за)/.test(s)) { const t = num(s, SECONDS, 10); return { kind: 'follow', t, label: `Следить за целью ${t} с` }; }
  if (/(поверни|повернись|развернись|разворот|поворот)/.test(s)) {
    const left = /(налево|влево|лев|против)/.test(s);
    const deg = num(s, DEGREES, /развер|разворот/.test(s) && !DEGREES.test(s) ? 180 : num(s, /(\d+)/, 90));
    return { kind: 'turn', deg: left ? -deg : deg, label: `Поворот ${left ? 'налево' : 'направо'} на ${deg}°` };
  }
  if (/(поднимись|подними|выше|набери высоту|вверх)/.test(s)) { const h = num(s, METERS, 1); return { kind: 'climb', dh: h, label: `Подняться на ${h} м` }; }
  if (/(опустись|снизься|ниже|вниз|спустись)/.test(s)) { const h = num(s, METERS, 1); return { kind: 'climb', dh: -h, label: `Опуститься на ${h} м` }; }
  if (/(зависни|повиси|жди|подожди|замри|паузa|пауза|зависание)/.test(s)) { const t = num(s, SECONDS, 3); return { kind: 'hover', t, label: `Зависнуть ${t} с` }; }
  if (/(лети|пролети|двигайся|сдвинься|полети|перелети|вперед|вперёд|назад|влево|вправо|налево|направо)/.test(s)) {
    const dir = /назад/.test(s) ? 'back' : /(влево|налево)/.test(s) ? 'left' : /(вправо|направо)/.test(s) ? 'right' : 'fwd';
    let t = num(s, SECONDS, null);
    const m = num(s, METERS, null);
    if (t == null) t = m != null ? +(m / 1.5).toFixed(1) : 2;
    const names = { fwd: 'вперёд', back: 'назад', left: 'влево', right: 'вправо' };
    return { kind: 'move', dir, t, label: `Лететь ${names[dir]} ${m != null ? m + ' м' : t + ' с'}` };
  }
  return { kind: 'unknown', label: `Не понял: «${s}»` };
}

export const commander = {
  enabled: false,
  /** Разбирает фразу в план. Если командир выключен — возвращает блокировку. */
  parse(text) {
    if (!this.enabled) return { ok: false, reason: 'ИИ-управление русским текстом выключено. Включите переключатель (клавиша G).' };
    let t = ' ' + String(text).toLowerCase().replace(/ё/g, 'е').replace(/[!?]/g, ' ') + ' ';
    t = wordsToDigits(t);
    const clauses = t.split(/,|;|\.(?!\d)|(?<![а-я])(?:затем|потом|после этого|далее|и|а)(?![а-я])/);
    const steps = clauses.map(parseClause).filter(Boolean);
    return { ok: steps.length > 0, steps, reason: steps.length ? '' : 'Команда пустая' };
  },
};

// ------------------------------------------------------------------ исполнитель плана
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const angDiff = (a, b) => ((a - b + 540) % 360) - 180;

export class Autopilot extends EventTarget {
  constructor() {
    super();
    this.active = false;
    this.rc = { roll: 0, pitch: 0, yaw: 0, throttle: 0.5 };
    this.plan = [];
    this.cur = -1;
    this.abortFlag = false;
  }
  log(t) { this.dispatchEvent(new CustomEvent('log', { detail: t })); }
  tel() { return link.telemetry.drone || {}; }
  setStep(i, state) { if (this.plan[i]) this.plan[i].state = state; this.dispatchEvent(new CustomEvent('plan', { detail: { plan: this.plan, cur: i } })); }
  abort() { this.abortFlag = true; }

  async run(steps) {
    if (this.active) { this.abort(); await sleep(150); }
    if (link.state !== 'online') { link.startSim(); await sleep(300); this.log('Нет связи с дроном — запущен симулятор.'); }
    this.plan = steps.map((s) => ({ ...s, state: s.kind === 'unknown' ? 'skip' : 'wait' }));
    this.abortFlag = false; this.active = true;
    this.rc = { roll: 0, pitch: 0, yaw: 0, throttle: 0.5 };
    this.dispatchEvent(new Event('start'));
    for (let i = 0; i < this.plan.length && !this.abortFlag; i++) {
      const st = this.plan[i];
      if (st.state === 'skip') continue;
      this.cur = i; this.setStep(i, 'run');
      this.log(`▸ Шаг ${i + 1}: ${st.label}`);
      try { await this.exec(st); this.setStep(i, this.abortFlag ? 'fail' : 'done'); }
      catch (e) { this.setStep(i, 'fail'); this.log('Ошибка: ' + e.message); break; }
    }
    this.rc = { roll: 0, pitch: 0, yaw: 0, throttle: 0.5 };
    this.active = false; this.cur = -1;
    this.log(this.abortFlag ? 'План остановлен.' : 'План выполнен.');
    this.dispatchEvent(new Event('end'));
  }

  // удержание высоты (П-регулятор поверх газа 0.5 = зависание)
  holdAlt(target) { const a = this.tel().alt || 0; return Math.max(0.15, Math.min(0.85, 0.5 + (target - a) * 0.35)); }

  async loop(seconds, fn) {
    const t0 = performance.now();
    while (!this.abortFlag && (performance.now() - t0) / 1000 < seconds) {
      const r = fn((performance.now() - t0) / 1000);
      if (r === true) break;
      await sleep(50);
    }
  }

  async exec(st) {
    const tel = () => this.tel();
    const alt0 = tel().alt || 0;
    switch (st.kind) {
      case 'takeoff':
        link.send({ type: 'drone', cmd: 'arm' });
        await sleep(300);
        link.send({ type: 'drone', cmd: 'takeoff', value: st.h });
        this.altTarget = st.h;
        await this.loop(20, () => { this.rc = { roll: 0, pitch: 0, yaw: 0, throttle: this.holdAlt(st.h) }; return (tel().alt || 0) >= st.h - 0.15; });
        break;
      case 'climb': {
        const target = Math.max(0.5, alt0 + st.dh); this.altTarget = target;
        await this.loop(15, () => { this.rc = { roll: 0, pitch: 0, yaw: 0, throttle: this.holdAlt(target) }; return Math.abs((tel().alt || 0) - target) < 0.15; });
        break;
      }
      case 'turn': {
        const target = (((tel().yaw ?? 0) + st.deg) % 360 + 360) % 360;
        await this.loop(15, () => {
          const d = angDiff(target, tel().yaw ?? 0);
          this.rc = { roll: 0, pitch: 0, yaw: Math.max(-1, Math.min(1, d / 40)), throttle: this.holdAlt(this.altTarget ?? alt0) };
          return Math.abs(d) < 4;
        });
        break;
      }
      case 'move': {
        const v = { fwd: [0, 0.6], back: [0, -0.6], left: [-0.6, 0], right: [0.6, 0] }[st.dir];
        await this.loop(st.t, () => { this.rc = { roll: v[0], pitch: v[1], yaw: 0, throttle: this.holdAlt(this.altTarget ?? alt0) }; });
        break;
      }
      case 'hover':
        await this.loop(st.t, () => { this.rc = { roll: 0, pitch: 0, yaw: 0, throttle: this.holdAlt(this.altTarget ?? alt0) }; });
        break;
      case 'snake':
        await this.loop(st.t, (s) => { this.rc = { roll: Math.sin(s * 2.2) * 0.7, pitch: 0.5, yaw: 0, throttle: this.holdAlt(this.altTarget ?? alt0) }; });
        break;
      case 'circle':
        await this.loop(st.t, () => { this.rc = { roll: 0.25, pitch: 0.5, yaw: 0.45, throttle: this.holdAlt(this.altTarget ?? alt0) }; });
        break;
      case 'square':
        for (let k = 0; k < 4 && !this.abortFlag; k++) {
          await this.exec({ kind: 'move', dir: 'fwd', t: st.t });
          await this.exec({ kind: 'turn', deg: 90 });
        }
        break;
      case 'follow': {
        if (!vision.trackColor) { vision.trackColor = [215, 35, 40]; vision.opts.color = true; this.log('Цель не выбрана — ищу красную цель.'); }
        vision.opts.color = true;
        let seen = 0;
        await this.loop(st.t, () => {
          const tg = vision.target;
          const thr = this.holdAlt(this.altTarget ?? alt0);
          if (!tg) { this.rc = { roll: 0, pitch: 0, yaw: st.search || seen ? 0.35 : 0, throttle: thr }; return; }
          seen++;
          this.rc = {
            roll: 0,
            yaw: Math.max(-1, Math.min(1, (tg.x - 0.5) * 2.4)),
            pitch: Math.max(-0.4, Math.min(0.6, (0.1 - tg.size) * 4)),
            throttle: Math.max(0.2, Math.min(0.8, thr + (0.5 - tg.y) * 0.3)),
          };
        });
        this.log(seen ? `Цель удерживалась ${Math.round(seen / 20)} с.` : 'Цель не найдена.');
        break;
      }
      case 'photo': this.dispatchEvent(new Event('photo')); break;
      case 'land':
        link.send({ type: 'drone', cmd: 'land' });
        await this.loop(30, () => { this.rc = { roll: 0, pitch: 0, yaw: 0, throttle: 0.3 }; return (tel().alt || 0) < 0.05 && !tel().armed; });
        break;
      case 'rtl':
        link.send({ type: 'drone', cmd: 'rtl' });
        await this.loop(40, () => { this.rc = { roll: 0, pitch: 0, yaw: 0, throttle: 0.4 }; return (tel().alt || 0) < 0.05 && !tel().armed; });
        break;
      case 'disarm':
        link.send({ type: 'drone', cmd: 'disarm', force: true });
        link.send({ type: 'motors', pwm: [PWM_MIN, PWM_MIN, PWM_MIN, PWM_MIN], armed: false });
        break;
    }
  }
}
export const autopilot = new Autopilot();

// ------------------------------------------------------------------ виртуальная 3D-арена
export class Arena {
  constructor() {
    this.canvas = document.createElement('canvas');
    this.canvas.width = 640; this.canvas.height = 400;
    this.r = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: true, preserveDrawingBuffer: true });
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x9cc4ec);
    this.scene.fog = new THREE.Fog(0x9cc4ec, 25, 90);
    this.cam = new THREE.PerspectiveCamera(70, 640 / 400, 0.1, 200);
    this.scene.add(new THREE.HemisphereLight(0xdfefff, 0x4a6a3a, 1.4));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6); sun.position.set(20, 40, 10); this.scene.add(sun);
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(300, 300), new THREE.MeshLambertMaterial({ color: 0x5f8f4a }));
    ground.rotation.x = -Math.PI / 2; this.scene.add(ground);
    const grid = new THREE.GridHelper(300, 150, 0x456c37, 0x527d41); grid.position.y = 0.01; this.scene.add(grid);
    const pad = new THREE.Mesh(new THREE.CircleGeometry(1.5, 32), new THREE.MeshLambertMaterial({ color: 0x2c2f38 }));
    pad.rotation.x = -Math.PI / 2; pad.position.y = 0.02; this.scene.add(pad);
    // постройки и деревья
    const rnd = (a) => (Math.sin(a * 999.7) * 0.5 + 0.5);
    for (let i = 0; i < 40; i++) {
      const ang = rnd(i) * Math.PI * 2, dist = 14 + rnd(i + 7) * 45;
      const x = Math.cos(ang) * dist, z = Math.sin(ang) * dist;
      if (i % 3) {
        const tr = new THREE.Mesh(new THREE.ConeGeometry(1.2, 4, 8), new THREE.MeshLambertMaterial({ color: 0x2f6b32 }));
        tr.position.set(x, 2, z); this.scene.add(tr);
      } else {
        const hgt = 3 + rnd(i + 3) * 8;
        const b = new THREE.Mesh(new THREE.BoxGeometry(4, hgt, 4), new THREE.MeshLambertMaterial({ color: 0xb8bcc8 }));
        b.position.set(x, hgt / 2, z); this.scene.add(b);
      }
    }
    // красная мишень
    this.target = new THREE.Group();
    const ball = new THREE.Mesh(new THREE.SphereGeometry(0.6, 24, 16), new THREE.MeshBasicMaterial({ color: 0xd8232a }));
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.9, 0.08, 8, 32), new THREE.MeshBasicMaterial({ color: 0xd8232a }));
    this.target.add(ball, ring); this.scene.add(this.target);
    this.t = 0; this.running = false;
  }
  start() {
    if (this.running) return;
    this.running = true;
    if (link.state !== 'online') link.startSim();
    vision.startCanvas(this.canvas, '3D-арена (симуляция камеры)');
    vision.trackColor = [215, 35, 40]; vision.opts.color = true;
    const tick = () => {
      if (!this.running) return;
      requestAnimationFrame(tick);
      this.t += 1 / 60;
      const s = link.sim?.s || { x: 0, y: 0, ...(link.telemetry.drone || {}) };
      const k = Math.PI / 180;
      this.target.position.set(Math.sin(this.t * 0.3) * 9, 2.2 + Math.sin(this.t * 0.7) * 1.2, -12 + Math.cos(this.t * 0.23) * 6);
      this.target.rotation.y += 0.03;
      this.cam.position.set(s.x || 0, Math.max(0.35, (s.alt || 0) + 0.35), s.y || 0);
      this.cam.rotation.order = 'YXZ';
      this.cam.rotation.set(-(s.pitch || 0) * k * 0.5 - 0.08, -(s.yaw || 0) * k, -(s.roll || 0) * k * 0.6);
      this.r.render(this.scene, this.cam);
    };
    tick();
  }
  stop() { this.running = false; if (vision.source?.kind === 'canvas') vision.stop(); }
}
let arenaInst = null;
export const arena = () => (arenaInst ||= new Arena());
export const arenaStop = () => { if (arenaInst?.running) arenaInst.stop(); };

// ------------------------------------------------------------------ самодиагностика
export async function selfCheck() {
  const res = [];
  // 1. ИИ-зрение и FPS
  {
    const cv = document.createElement('canvas'); cv.width = 640; cv.height = 400;
    const ctx = cv.getContext('2d');
    const saved = { tc: vision.trackColor, color: vision.opts.color, prev: vision.prev, ext: vision.external };
    vision.trackColor = [215, 35, 40]; vision.opts.color = true;
    const N = 120, t0 = performance.now();
    let hits = 0;
    for (let i = 0; i < N; i++) {
      ctx.fillStyle = '#7fa8d8'; ctx.fillRect(0, 0, 640, 400);
      ctx.fillStyle = '#d8232a'; ctx.beginPath(); ctx.arc(200 + i * 2, 200, 40, 0, Math.PI * 2); ctx.fill();
      vision._analyze(cv);
      if (vision.target) hits++;
    }
    const fps = Math.round(N / ((performance.now() - t0) / 1000));
    Object.assign(vision, { trackColor: saved.tc, prev: saved.prev, external: saved.ext }); vision.opts.color = saved.color;
    res.push({ name: 'ИИ-зрение и FPS компьютера', ok: hits > N * 0.9 && fps > 15, detail: `${fps} FPS анализа, цель захвачена в ${hits}/${N} кадрах` });
  }
  // 2. микшер 4 моторов: «вперёд 120»
  {
    const m = mixMotors(1480, 0, 120, 0);
    const ok = m[1] === 1600 && m[3] === 1600 && m[0] === 1360 && m[2] === 1360;
    res.push({ name: 'Микшер 4 моторов', ok, detail: `вперёд 120 → M1=${m[0]} M2=${m[1]} M3=${m[2]} M4=${m[3]} (задние быстрее передних)` });
  }
  // 3. ИИ-командир: выключен → блок, включён → план
  {
    const was = commander.enabled;
    commander.enabled = false; const off = commander.parse('взлети на 3 метра');
    commander.enabled = true; const on = commander.parse('взлети на 3 метра, поверни направо на 90 градусов, пролети вперед 2 секунды и следи за целью');
    commander.enabled = was;
    const kinds = on.steps?.map((s) => s.kind).join(',');
    const ok = !off.ok && on.ok && kinds === 'takeoff,turn,move,follow' && on.steps[0].h === 3 && on.steps[1].deg === 90 && on.steps[2].t === 2;
    res.push({ name: 'Переключатель ИИ-командира', ok, detail: `выкл: ${off.ok ? 'НЕ заблокирован' : 'заблокирован'}; вкл: ${on.steps?.length || 0} шага (${kinds})` });
  }
  // 4. драйвер платы и DISARM
  {
    const m = mixMotors(1700, 50, 80, 30, false);
    let detail = `DISARM → ${m.join(' / ')} мкс`, ok = m.every((v) => v === PWM_MIN);
    if (link.state === 'online' && link.via === 'ws') {
      link.send({ type: 'motors', pwm: m, armed: false, ack: true });
      const ack = await new Promise((r) => {
        const h = (e) => { if (e.detail.type === 'ack' && e.detail.motors) { link.removeEventListener('message', h); r(e.detail.motors); } };
        link.addEventListener('message', h); setTimeout(() => { link.removeEventListener('message', h); r(null); }, 1500);
      });
      detail += ack ? `; плата: драйвер ${ack.driver}, моторы ${ack.pwm.join('/')}` : '; плата не ответила';
      ok = ok && !!ack && ack.pwm.every((v) => v === PWM_MIN);
    } else detail += '; плата не подключена — проверен программный драйвер';
    res.push({ name: 'Драйвер платы и аварийный стоп', ok, detail });
  }
  return res;
}

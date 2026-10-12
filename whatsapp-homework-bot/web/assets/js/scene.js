// 3D-сцена сайта: телефон с чатом класса, электронный дневник, часы «после уроков», бумажный самолётик с ДЗ,
// ИИ-сфера, щит надёжности и плитки панели. Все модели собраны из примитивов Three.js — без внешних файлов.
// Сцена «играет» историю по мере прокрутки: progress = номер главы (0…7, дробный).
import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

const COLORS = { green: 0x25d366, cyan: 0x22d3ee, violet: 0x8b5cf6, ink: 0x0b0f17 };
const FONT = '"Noto Sans", system-ui, sans-serif';
const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const smooth = (t) => t * t * (3 - 2 * t);
const lerp = (a, b, t) => a + (b - a) * t;
const easeOut = (t) => 1 - (1 - clamp(t)) ** 3;

// Ключевые кадры по главам: [x, y, z, rotX, rotY, rotZ, scale]
function frameAt(frames, p) {
  const last = frames.length - 1;
  const i = Math.min(last, Math.max(0, Math.floor(p)));
  const j = Math.min(last, i + 1);
  const t = smooth(clamp(p - i));
  return frames[i].map((v, k) => lerp(v, frames[j][k], t));
}

function canvasTexture(width, height, draw) {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  draw?.(ctx, width, height);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 8;
  return { canvas, ctx, texture };
}

function wrapLines(ctx, text, maxWidth) {
  const words = text.split(' ');
  const lines = [];
  let line = '';
  for (const word of words) {
    const test = line ? `${line} ${word}` : word;
    if (ctx.measureText(test).width > maxWidth && line) {
      lines.push(line);
      line = word;
    } else line = test;
  }
  if (line) lines.push(line);
  return lines;
}

// --- экран телефона: чат класса в WhatsApp ---
class PhoneScreen {
  constructor() {
    this.w = 540;
    this.h = 1140;
    const { canvas, ctx, texture } = canvasTexture(this.w, this.h);
    this.canvas = canvas;
    this.ctx = ctx;
    this.texture = texture;
    this.state = '';
    this.stateSince = 0;
  }

  set(state, now) {
    if (state === this.state) return;
    this.state = state;
    this.stateSince = now;
  }

  bubble(y, { text, out = false, name = '', time = '', photo = false, width = 360, typing = false }) {
    const ctx = this.ctx;
    ctx.font = `400 25px ${FONT}`;
    const lines = typing ? [] : wrapLines(ctx, text, width - 40);
    const photoH = photo ? 210 : 0;
    const nameH = name ? 30 : 0;
    const h = typing ? 58 : 26 + nameH + photoH + lines.length * 33 + 24;
    const w = typing ? 110 : Math.min(width, Math.max(...lines.map((l) => ctx.measureText(l).width), name ? ctx.measureText(name).width : 0, photo ? 300 : 0) + 44);
    const x = out ? this.w - w - 22 : 22;
    ctx.fillStyle = out ? '#005c4b' : '#202c33';
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, 18);
    ctx.fill();
    let cy = y + 14;
    if (name) {
      ctx.font = `700 22px ${FONT}`;
      ctx.fillStyle = '#25d366';
      ctx.fillText(name, x + 18, cy + 20);
      cy += nameH;
    }
    if (photo) {
      // мини-«скриншот» дневника
      ctx.fillStyle = '#f6f8fb';
      ctx.beginPath();
      ctx.roundRect(x + 10, cy, w - 20, photoH - 12, 12);
      ctx.fill();
      ctx.fillStyle = '#0f172a';
      ctx.font = `700 19px ${FONT}`;
      ctx.fillText('Среда, 15 октября', x + 28, cy + 34);
      const rows = [['Алгебра', '№ 250–255'], ['Русский яз.', 'Упр. 312'], ['Физика', '§ 12, в. 1–4']];
      rows.forEach(([s, t], i) => {
        const ry = cy + 56 + i * 44;
        ctx.fillStyle = i === 2 ? 'rgba(37,211,102,0.16)' : '#eef1f6';
        ctx.beginPath();
        ctx.roundRect(x + 22, ry, w - 44, 36, 8);
        ctx.fill();
        ctx.fillStyle = '#0f172a';
        ctx.font = `700 17px ${FONT}`;
        ctx.fillText(s, x + 34, ry + 24);
        ctx.fillStyle = '#475569';
        ctx.font = `400 17px ${FONT}`;
        ctx.fillText(t, x + 160, ry + 24);
      });
      cy += photoH;
    }
    if (typing) {
      const t = performance.now() / 1000;
      for (let i = 0; i < 3; i += 1) {
        ctx.fillStyle = `rgba(134,150,160,${0.45 + 0.55 * Math.max(0, Math.sin(t * 6 - i * 0.8))})`;
        ctx.beginPath();
        ctx.arc(x + 32 + i * 24, y + 29 - 5 * Math.max(0, Math.sin(t * 6 - i * 0.8)), 7, 0, Math.PI * 2);
        ctx.fill();
      }
      return y + h;
    }
    ctx.font = `400 25px ${FONT}`;
    ctx.fillStyle = '#e9edef';
    lines.forEach((l, i) => ctx.fillText(l, x + 18, cy + 26 + i * 33));
    if (time) {
      ctx.font = `400 17px ${FONT}`;
      ctx.fillStyle = 'rgba(233,237,239,0.6)';
      ctx.fillText(time, x + w - 16 - ctx.measureText(time).width, y + h - 10);
    }
    return y + h;
  }

  // перерисовка: true — анимация ещё идёт
  draw(now) {
    const { ctx, w, h } = this;
    const age = (now - this.stateSince) / 1000;
    ctx.fillStyle = '#0b141a';
    ctx.fillRect(0, 0, w, h);
    // обои чата
    ctx.fillStyle = 'rgba(255,255,255,0.025)';
    for (let i = 0; i < 70; i += 1) {
      ctx.beginPath();
      ctx.arc((i * 97) % w, (i * 151) % h, 3 + (i % 4), 0, Math.PI * 2);
      ctx.fill();
    }
    // статус-бар и шапка группы
    ctx.fillStyle = '#1f2c34';
    ctx.fillRect(0, 0, w, 150);
    ctx.fillStyle = '#e9edef';
    ctx.font = `700 22px ${FONT}`;
    ctx.fillText('14:46', 36, 44);
    ctx.fillText('5G ▮▮▮ 87%', w - 170, 44);
    const grad = ctx.createLinearGradient(30, 70, 100, 140);
    grad.addColorStop(0, '#25d366');
    grad.addColorStop(1, '#8b5cf6');
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(70, 108, 32, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#06080d';
    ctx.font = `700 26px ${FONT}`;
    ctx.fillText('7В', 50, 117);
    ctx.fillStyle = '#e9edef';
    ctx.font = `700 28px ${FONT}`;
    ctx.fillText('7 «В» класс', 118, 102);
    ctx.fillStyle = '#8696a0';
    ctx.font = `400 20px ${FONT}`;
    ctx.fillText(this.state === 'ai' && age < 4.5 ? 'Бот ДЗ печатает…' : 'Бот ДЗ, Аня, Дамир, Алия…', 118, 132);

    let y = 180;
    let animating = false;
    const show = (delay) => age > delay;
    if (this.state === 'intro' || this.state === 'final') {
      y = this.bubble(y, { name: 'Бот ДЗ', text: '📚 Домашнее задание на завтра', photo: true, time: '14:46' }) + 16;
      y = this.bubble(y, { out: true, text: 'спасибо бот 🙏', time: '14:47' }) + 16;
      y = this.bubble(y, { name: 'Дамир', text: 'а по физике что задали?', time: '15:02' }) + 16;
      y = this.bubble(y, { name: 'Бот ДЗ', text: 'По физике: § 12, ответить на вопросы 1–4 😉', time: '15:02' }) + 16;
      if (this.state === 'final') {
        y = this.bubble(y, { name: 'Алия', text: 'лучший бот ❤️', time: '15:10' }) + 16;
      }
    } else if (this.state === 'digest') {
      y = this.bubble(y, { name: 'Аня', text: 'а что на завтра?', time: '14:31' }) + 16;
      if (show(0.5)) y = this.bubble(y, { name: 'Бот ДЗ', text: '📚 Домашнее задание на завтра', photo: true, time: '14:46' }) + 16;
      if (show(1.6)) y = this.bubble(y, { name: 'Бот ДЗ', text: '🆕 Новое: Физика. Вопросы — пишите сюда 👇', time: '14:46' }) + 16;
      if (show(2.6)) this.bubble(y, { out: true, text: 'спасибо бот 🙏', time: '14:47' });
      animating = age < 3;
    } else if (this.state === 'ai') {
      y = this.bubble(y, { out: true, text: 'как решить номер 250? 🥲', time: '19:20' }) + 16;
      if (age < 2.2) {
        this.bubble(y, { typing: true });
        animating = true;
      } else {
        const full = 'Смотри: это система. Выразим y из первого уравнения: y = 7 − 2x. Подставим во второе и найдём x 👇';
        const chars = Math.floor(clamp((age - 2.2) / 2.2) * full.length);
        y = this.bubble(y, { name: 'Бот ДЗ', text: full.slice(0, Math.max(1, chars)), time: '19:20' }) + 16;
        animating = chars < full.length;
        if (!animating && age > 5.2) this.bubble(y, { out: true, text: 'а, понял! спасибо 🔥', time: '19:21' });
        if (age < 5.6) animating = true;
      }
    }
    // поле ввода
    ctx.fillStyle = '#1f2c34';
    ctx.beginPath();
    ctx.roundRect(18, h - 92, w - 120, 70, 35);
    ctx.fill();
    ctx.fillStyle = '#8696a0';
    ctx.font = `400 24px ${FONT}`;
    ctx.fillText('Сообщение', 50, h - 48);
    ctx.fillStyle = '#25d366';
    ctx.beginPath();
    ctx.arc(w - 58, h - 57, 35, 0, Math.PI * 2);
    ctx.fill();
    this.texture.needsUpdate = true;
    return animating;
  }
}

export class StoryScene {
  constructor(canvas, { lowPower = false, reducedMotion = false } = {}) {
    this.canvas = canvas;
    this.lowPower = lowPower;
    this.reducedMotion = reducedMotion;
    this.progress = 0;
    this.target = 0;
    this.pointer = new THREE.Vector2();
    this.pointerSmooth = new THREE.Vector2();
    this.lastFrame = 0;
    this.time = 0;
    this.running = false;
    this.layout = { xScale: 1, yShift: 0, scale: 1 };
  }

  init(onStep = () => {}) {
    const renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: !this.lowPower, alpha: true, powerPreference: 'high-performance' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, this.lowPower ? 1.25 : 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    renderer.setClearColor(0x000000, 0);
    this.renderer = renderer;
    onStep(0.15);

    const scene = new THREE.Scene();
    scene.fog = new THREE.Fog(0x06080d, 14, 34);
    this.scene = scene;
    const pmrem = new THREE.PMREMGenerator(renderer);
    scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    pmrem.dispose();

    this.camera = new THREE.PerspectiveCamera(35, 1, 0.1, 100);
    this.camera.position.set(0, 0, 11);

    const key = new THREE.DirectionalLight(0xffffff, 1.6);
    key.position.set(4, 6, 8);
    scene.add(key);
    const rimGreen = new THREE.PointLight(COLORS.green, 40, 20, 2);
    rimGreen.position.set(-5, 2, 3);
    scene.add(rimGreen);
    const rimViolet = new THREE.PointLight(COLORS.violet, 45, 20, 2);
    rimViolet.position.set(6, -2, 2);
    scene.add(rimViolet);
    scene.add(new THREE.AmbientLight(0xffffff, 0.25));
    onStep(0.3);

    this.buildPhone();
    this.buildBubbles();
    onStep(0.45);
    this.buildBook();
    this.buildClock();
    onStep(0.6);
    this.buildPlane();
    this.buildOrb();
    onStep(0.75);
    this.buildShield();
    this.buildTiles();
    this.buildParticles();
    onStep(0.9);

    if (!this.lowPower) {
      const target = new THREE.WebGLRenderTarget(1, 1, { type: THREE.HalfFloatType, samples: 4 });
      this.composer = new EffectComposer(renderer, target);
      this.composer.addPass(new RenderPass(scene, this.camera));
      this.bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.5, 0.6, 0.9);
      this.composer.addPass(this.bloom);
      this.composer.addPass(new OutputPass());
    }
    this.resize();
    onStep(1);
  }

  // --- модели ---
  buildPhone() {
    const g = new THREE.Group();
    const body = new THREE.Mesh(
      new RoundedBoxGeometry(2.05, 4.2, 0.24, 8, 0.3),
      new THREE.MeshPhysicalMaterial({ color: 0x10141c, metalness: 0.75, roughness: 0.28, clearcoat: 1, clearcoatRoughness: 0.15 }),
    );
    g.add(body);
    const frame = new THREE.Mesh(
      new RoundedBoxGeometry(2.1, 4.25, 0.18, 8, 0.32),
      new THREE.MeshStandardMaterial({ color: 0x8b93a5, metalness: 1, roughness: 0.22 }),
    );
    g.add(frame);
    this.screen = new PhoneScreen();
    this.screen.set('intro', 0);
    this.screen.draw(0);
    const screen = new THREE.Mesh(new THREE.PlaneGeometry(1.86, 3.93), new THREE.MeshBasicMaterial({ map: this.screen.texture, toneMapped: false }));
    screen.position.z = 0.125;
    g.add(screen);
    const island = new THREE.Mesh(new RoundedBoxGeometry(0.3, 0.075, 0.02, 4, 0.035), new THREE.MeshBasicMaterial({ color: 0x000000 }));
    island.position.set(0, 1.875, 0.13);
    g.add(island);
    // светящийся контур экрана
    const glow = new THREE.Mesh(
      new THREE.PlaneGeometry(2.6, 4.7),
      new THREE.MeshBasicMaterial({ map: this.glowTexture(), transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false, opacity: 0.55 }),
    );
    glow.position.z = -0.2;
    g.add(glow);
    this.phoneGlow = glow;
    this.phone = g;
    this.scene.add(g);
    // [x, y, z, rx, ry, rz, s] по главам 0…7
    this.phoneFrames = [
      [2.7, 0.05, 0, 0.05, -0.42, 0.04, 1],
      [4.3, 0.7, -3.2, 0.05, -0.7, 0.04, 0.72],
      [3.6, 0.4, -3.6, 0.05, -0.6, 0, 0.6],
      [2.6, -0.05, 0, 0.02, -0.3, -0.02, 1],
      [-3.05, -0.1, 0, 0.02, 0.42, 0.02, 1],
      [-0.4, -0.6, -6, 0, 0.2, 0, 0.5],
      [0, 0.1, -3.4, 0.02, 0, 0, 0.62],
      [3.35, -0.15, -0.6, 0.02, -0.42, 0.03, 0.95],
    ];
  }

  glowTexture() {
    const { texture } = canvasTexture(256, 400, (ctx, w, h) => {
      const g = ctx.createRadialGradient(w / 2, h / 2, 10, w / 2, h / 2, h / 2);
      g.addColorStop(0, 'rgba(37,211,102,0.55)');
      g.addColorStop(0.45, 'rgba(34,211,238,0.22)');
      g.addColorStop(1, 'rgba(139,92,246,0)');
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, w, h);
    });
    return texture;
  }

  buildBubbles() {
    this.bubbles = [];
    const colors = [COLORS.green, 0x2a3942, COLORS.cyan, 0x2a3942, COLORS.violet, COLORS.green];
    for (let i = 0; i < 6; i += 1) {
      const mesh = new THREE.Mesh(
        new RoundedBoxGeometry(0.95, 0.42, 0.1, 4, 0.19),
        new THREE.MeshStandardMaterial({ color: colors[i], emissive: colors[i], emissiveIntensity: colors[i] === 0x2a3942 ? 0.05 : 0.55, metalness: 0.2, roughness: 0.35 }),
      );
      // «текст» внутри пузыря
      for (let k = 0; k < 2; k += 1) {
        const bar = new THREE.Mesh(new THREE.BoxGeometry(k ? 0.42 : 0.62, 0.05, 0.02), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.75 }));
        bar.position.set(k ? -0.1 : 0, k ? -0.07 : 0.07, 0.06);
        mesh.add(bar);
      }
      mesh.userData = { angle: (i / 6) * Math.PI * 2, radius: 2.1 + (i % 3) * 0.35, speed: 0.22 + (i % 2) * 0.08, tilt: (i % 3) - 1 };
      this.scene.add(mesh);
      this.bubbles.push(mesh);
    }
  }

  buildBook() {
    const g = new THREE.Group();
    const W = 2.3;
    const H = 3.0;
    const coverTex = canvasTexture(512, 668, (ctx, w, h) => {
      const grad = ctx.createLinearGradient(0, 0, w, h);
      grad.addColorStop(0, '#0f5132');
      grad.addColorStop(1, '#0b2e3a');
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, w, h);
      ctx.strokeStyle = 'rgba(255,255,255,0.18)';
      ctx.lineWidth = 6;
      ctx.strokeRect(28, 28, w - 56, h - 56);
      ctx.fillStyle = '#25d366';
      ctx.beginPath();
      ctx.roundRect(w / 2 - 60, 170, 120, 120, 28);
      ctx.fill();
      ctx.fillStyle = '#06080d';
      ctx.font = `700 72px ${FONT}`;
      ctx.textAlign = 'center';
      ctx.fillText('B', w / 2, 255);
      ctx.fillStyle = '#ffffff';
      ctx.font = `700 54px ${FONT}`;
      ctx.fillText('BilimClass', w / 2, 380);
      ctx.fillStyle = 'rgba(255,255,255,0.7)';
      ctx.font = `400 30px ${FONT}`;
      ctx.fillText('электронный дневник', w / 2, 430);
    }).texture;
    const coverMat = new THREE.MeshStandardMaterial({ map: coverTex, roughness: 0.55, metalness: 0.1 });
    const edgeMat = new THREE.MeshStandardMaterial({ color: 0x0f3d2c, roughness: 0.6 });
    const back = new THREE.Mesh(new RoundedBoxGeometry(W, H, 0.06, 3, 0.03), edgeMat);
    back.position.set(W / 2, 0, -0.16);
    g.add(back);

    this.pages = new PagesTexture();
    const pagesMat = new THREE.MeshStandardMaterial({ map: this.pages.texture, roughness: 0.9 });
    const block = new THREE.Mesh(new THREE.BoxGeometry(W - 0.12, H - 0.12, 0.26), [
      new THREE.MeshStandardMaterial({ color: 0xf1f1ea, roughness: 0.95 }),
      new THREE.MeshStandardMaterial({ color: 0xf1f1ea, roughness: 0.95 }),
      new THREE.MeshStandardMaterial({ color: 0xf1f1ea, roughness: 0.95 }),
      new THREE.MeshStandardMaterial({ color: 0xf1f1ea, roughness: 0.95 }),
      pagesMat,
      new THREE.MeshStandardMaterial({ color: 0xf1f1ea }),
    ]);
    block.position.set(W / 2, 0, 0);
    g.add(block);

    // обложка вращается вокруг корешка
    const hinge = new THREE.Group();
    const front = new THREE.Mesh(new RoundedBoxGeometry(W, H, 0.06, 3, 0.03), [edgeMat, edgeMat, edgeMat, edgeMat, coverMat, edgeMat]);
    front.position.set(W / 2, 0, 0);
    hinge.add(front);
    hinge.position.z = 0.16;
    g.add(hinge);
    this.bookHinge = hinge;
    // центр книги — в середине страниц
    const pivot = new THREE.Group();
    g.position.x = -W / 2;
    pivot.add(g);
    this.book = pivot;
    this.scene.add(pivot);
    this.bookFrames = [
      [-4, -2.6, -3, 0, 0.6, 0, 0],
      [3.05, -0.05, 0.1, -0.28, -0.42, 0.06, 0.9],
      [3.6, -0.9, -1.8, -0.2, -0.6, 0.1, 0.62],
      [-3.3, -0.7, -1.4, -0.1, 0.5, -0.12, 0.6],
      [-4.6, -1.5, -3, 0, 0.6, 0, 0],
      [-4.6, -1.5, -3, 0, 0.6, 0, 0],
      [-4.6, -1.5, -3, 0, 0.6, 0, 0],
      [-4.6, -1.5, -3, 0, 0.6, 0, 0],
    ];
  }

  buildClock() {
    const g = new THREE.Group();
    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(1.32, 0.09, 24, 96),
      new THREE.MeshStandardMaterial({ color: COLORS.green, emissive: COLORS.green, emissiveIntensity: 0.5, metalness: 0.6, roughness: 0.25 }),
    );
    g.add(ring);
    this.clockRing = ring;
    const face = new THREE.Mesh(
      new THREE.CircleGeometry(1.26, 64),
      new THREE.MeshPhysicalMaterial({ color: 0x0b1220, metalness: 0.2, roughness: 0.15, clearcoat: 1, transparent: true, opacity: 0.92 }),
    );
    face.position.z = -0.02;
    g.add(face);
    for (let i = 0; i < 12; i += 1) {
      const tick = new THREE.Mesh(new THREE.BoxGeometry(i % 3 ? 0.04 : 0.07, i % 3 ? 0.14 : 0.24, 0.03), new THREE.MeshBasicMaterial({ color: i % 3 ? 0x7d889b : 0xe9eef6 }));
      const a = (i / 12) * Math.PI * 2;
      tick.position.set(Math.sin(a) * 1.05, Math.cos(a) * 1.05, 0.02);
      tick.rotation.z = -a;
      g.add(tick);
    }
    const handMat = new THREE.MeshStandardMaterial({ color: 0xffffff, metalness: 0.3, roughness: 0.3 });
    const hourGeo = new THREE.BoxGeometry(0.09, 0.6, 0.04);
    hourGeo.translate(0, 0.27, 0);
    const minuteGeo = new THREE.BoxGeometry(0.06, 0.92, 0.04);
    minuteGeo.translate(0, 0.42, 0);
    this.hourHand = new THREE.Mesh(hourGeo, handMat);
    this.minuteHand = new THREE.Mesh(minuteGeo, new THREE.MeshStandardMaterial({ color: COLORS.green, emissive: COLORS.green, emissiveIntensity: 0.6 }));
    this.hourHand.position.z = 0.05;
    this.minuteHand.position.z = 0.08;
    g.add(this.hourHand, this.minuteHand);
    const cap = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.08, 0.06, 24), handMat);
    cap.rotation.x = Math.PI / 2;
    cap.position.z = 0.1;
    g.add(cap);
    // расходящиеся кольца «уроки закончились»
    this.clockWaves = [0, 1, 2].map((i) => {
      const wave = new THREE.Mesh(new THREE.RingGeometry(1.36, 1.42, 96), new THREE.MeshBasicMaterial({ color: COLORS.green, transparent: true, opacity: 0, side: THREE.DoubleSide, toneMapped: false }));
      wave.userData.offset = i / 3;
      g.add(wave);
      return wave;
    });
    this.clock3d = g;
    this.scene.add(g);
    this.clockFrames = [
      [-3, 2, -4, 0, 0, 0, 0],
      [-3.6, 1.8, -3, 0, 0.3, 0, 0],
      [-2.6, 0.15, 0, -0.06, 0.38, 0.04, 1],
      [-4.2, 1.6, -3, 0, 0.3, 0, 0],
      [-4.2, 1.6, -3, 0, 0.3, 0, 0],
      [-4.2, 1.6, -3, 0, 0.3, 0, 0],
      [-4.2, 1.6, -3, 0, 0.3, 0, 0],
      [-4.2, 1.6, -3, 0, 0.3, 0, 0],
    ];
  }

  buildPlane() {
    const geo = new THREE.BufferGeometry();
    const nose = [0, 0, 1.1];
    const left = [-0.85, 0.06, -0.55];
    const right = [0.85, 0.06, -0.55];
    const mid = [0, 0.02, -0.45];
    const keel = [0, -0.26, -0.5];
    const tris = [nose, left, mid, nose, mid, right, nose, mid, keel, nose, keel, mid].flat();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(tris, 3));
    geo.computeVertexNormals();
    const plane = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xbff7d5, emissiveIntensity: 0.35, roughness: 0.4, side: THREE.DoubleSide, flatShading: true }));
    plane.scale.setScalar(0.55);
    this.plane = plane;
    this.scene.add(plane);
    this.planePath = new THREE.CatmullRomCurve3([
      new THREE.Vector3(-3.1, -0.4, -1.0),
      new THREE.Vector3(-1.6, 1.6, 0.8),
      new THREE.Vector3(0.6, 1.2, 1.6),
      new THREE.Vector3(1.9, 0.5, 0.9),
      new THREE.Vector3(2.55, 0.15, 0.25),
    ]);
    // светящийся след
    const trailCount = 40;
    const trailGeo = new THREE.BufferGeometry();
    trailGeo.setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(trailCount * 3), 3));
    this.trail = new THREE.Points(trailGeo, new THREE.PointsMaterial({ color: COLORS.green, size: 0.07, transparent: true, opacity: 0.9, depthWrite: false, blending: THREE.AdditiveBlending, map: this.dotTexture(), toneMapped: false }));
    this.scene.add(this.trail);
  }

  buildOrb() {
    const g = new THREE.Group();
    const shell = new THREE.Mesh(
      new THREE.IcosahedronGeometry(0.95, 6),
      new THREE.MeshPhysicalMaterial({
        color: 0xffffff, metalness: 0, roughness: 0.08, transmission: 1, thickness: 1.4, ior: 1.45,
        iridescence: 1, iridescenceIOR: 1.6, iridescenceThicknessRange: [200, 800], clearcoat: 1, transparent: true,
      }),
    );
    g.add(shell);
    const core = new THREE.Mesh(new THREE.IcosahedronGeometry(0.42, 3), new THREE.MeshStandardMaterial({ color: COLORS.violet, emissive: COLORS.violet, emissiveIntensity: 1.6, roughness: 0.4, flatShading: true }));
    g.add(core);
    this.orbCore = core;
    this.electrons = [];
    for (let i = 0; i < 3; i += 1) {
      const orbit = new THREE.Group();
      orbit.rotation.set(Math.random() * Math.PI, Math.random() * Math.PI, 0);
      const path = new THREE.Mesh(new THREE.TorusGeometry(1.35, 0.008, 8, 128), new THREE.MeshBasicMaterial({ color: [COLORS.green, COLORS.cyan, COLORS.violet][i], transparent: true, opacity: 0.5, toneMapped: false }));
      orbit.add(path);
      const e = new THREE.Mesh(new THREE.SphereGeometry(0.07, 16, 16), new THREE.MeshBasicMaterial({ color: [COLORS.green, COLORS.cyan, COLORS.violet][i], toneMapped: false }));
      orbit.add(e);
      e.userData = { speed: 1.1 + i * 0.35, phase: i * 2 };
      g.add(orbit);
      this.electrons.push(e);
    }
    this.orb = g;
    this.scene.add(g);
    this.orbFrames = [
      [-3, 3, -6, 0, 0, 0, 0],
      [-3, 3, -6, 0, 0, 0, 0],
      [-3, 3, -6, 0, 0, 0, 0],
      [-1.2, 2.8, -3, 0, 0, 0, 0],
      [-1.2, 1.5, 0.9, 0, 0, 0, 0.85],
      [3.6, 2.6, -5, 0, 0, 0, 0],
      [3.6, 2.6, -5, 0, 0, 0, 0],
      [-3.4, 0.5, -0.8, 0, 0, 0, 0.75],
    ];
  }

  buildShield() {
    const s = new THREE.Shape();
    s.moveTo(0, 1.25);
    s.bezierCurveTo(0.55, 1.02, 0.95, 1.0, 1.1, 0.95);
    s.lineTo(1.1, 0.1);
    s.bezierCurveTo(1.1, -0.65, 0.5, -1.05, 0, -1.32);
    s.bezierCurveTo(-0.5, -1.05, -1.1, -0.65, -1.1, 0.1);
    s.lineTo(-1.1, 0.95);
    s.bezierCurveTo(-0.95, 1.0, -0.55, 1.02, 0, 1.25);
    const geo = new THREE.ExtrudeGeometry(s, { depth: 0.28, bevelEnabled: true, bevelThickness: 0.08, bevelSize: 0.07, bevelSegments: 8, curveSegments: 48 });
    geo.center();
    const g = new THREE.Group();
    const shield = new THREE.Mesh(geo, new THREE.MeshPhysicalMaterial({ color: 0x0e3b2a, metalness: 0.85, roughness: 0.22, clearcoat: 1, clearcoatRoughness: 0.1 }));
    g.add(shield);
    const inner = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: 0x1fb457, emissive: 0x0f7a3a, emissiveIntensity: 0.6, metalness: 0.65, roughness: 0.22 }));
    inner.scale.set(0.8, 0.8, 0.6);
    inner.position.z = 0.12;
    g.add(inner);
    const check = new THREE.Mesh(
      new THREE.TubeGeometry(new THREE.CatmullRomCurve3([new THREE.Vector3(-0.42, 0.02, 0), new THREE.Vector3(-0.1, -0.3, 0), new THREE.Vector3(0.48, 0.38, 0)], false, 'catmullrom', 0), 48, 0.1, 16),
      new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffffff, emissiveIntensity: 0.9 }),
    );
    check.position.z = 0.32;
    g.add(check);
    this.shieldWaves = [0, 1, 2].map((i) => {
      const wave = new THREE.Mesh(new THREE.TorusGeometry(1.5, 0.012, 8, 128), new THREE.MeshBasicMaterial({ color: COLORS.cyan, transparent: true, opacity: 0, toneMapped: false }));
      wave.userData.offset = i / 3;
      g.add(wave);
      return wave;
    });
    this.shield = g;
    this.scene.add(g);
    this.shieldFrames = [
      [4, -3, -5, 0, 0, 0, 0],
      [4, -3, -5, 0, 0, 0, 0],
      [4, -3, -5, 0, 0, 0, 0],
      [4, -3, -5, 0, 0, 0, 0],
      [4, -2.5, -4, 0, -0.6, 0, 0],
      [2.7, 0.05, 0, 0.08, -0.32, 0, 1.15],
      [4.5, 1.8, -5, 0, -0.5, 0, 0],
      [4.5, 1.8, -5, 0, -0.5, 0, 0],
    ];
  }

  buildTiles() {
    const items = [['🗓', 'График', '#25d366'], ['💬', 'Переписка', '#22d3ee'], ['🔑', 'Ключи', '#8b5cf6'], ['⌨️', 'Терминал', '#25d366'], ['🔔', 'Уведомления', '#f472b6'], ['🧠', 'ИИ', '#22d3ee']];
    this.tiles = items.map(([icon, label, color], i) => {
      const { texture } = canvasTexture(512, 320, (ctx, w, h) => {
        const grad = ctx.createLinearGradient(0, 0, w, h);
        grad.addColorStop(0, 'rgba(20,27,40,0.96)');
        grad.addColorStop(1, 'rgba(12,16,26,0.96)');
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.roundRect(0, 0, w, h, 40);
        ctx.fill();
        ctx.strokeStyle = color;
        ctx.globalAlpha = 0.6;
        ctx.lineWidth = 4;
        ctx.beginPath();
        ctx.roundRect(2, 2, w - 4, h - 4, 38);
        ctx.stroke();
        ctx.globalAlpha = 1;
        ctx.font = `90px ${FONT}`;
        ctx.fillText(icon, 44, 140);
        ctx.fillStyle = '#e9eef6';
        ctx.font = `700 52px ${FONT}`;
        ctx.fillText(label, 44, 230);
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.roundRect(44, 258, 120 + (i % 3) * 60, 12, 6);
        ctx.fill();
      });
      const mesh = new THREE.Mesh(new THREE.PlaneGeometry(1.6, 1.0), new THREE.MeshBasicMaterial({ map: texture, transparent: true, toneMapped: false, side: THREE.DoubleSide, depthWrite: false }));
      const a = (i / (items.length - 1) - 0.5) * 1.9;
      mesh.userData = { a, y: i % 2 ? 0.95 : -0.85, phase: i * 1.3 };
      this.scene.add(mesh);
      return mesh;
    });
  }

  dotTexture() {
    if (this.dot) return this.dot;
    const { texture } = canvasTexture(64, 64, (ctx) => {
      const g = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
      g.addColorStop(0, 'rgba(255,255,255,1)');
      g.addColorStop(0.35, 'rgba(255,255,255,0.65)');
      g.addColorStop(1, 'rgba(255,255,255,0)');
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, 64, 64);
    });
    this.dot = texture;
    return texture;
  }

  buildParticles() {
    const count = this.lowPower ? 600 : 1500;
    const positions = new Float32Array(count * 3);
    const colors = new Float32Array(count * 3);
    const palette = [new THREE.Color(COLORS.green), new THREE.Color(COLORS.cyan), new THREE.Color(COLORS.violet), new THREE.Color(0xffffff)];
    for (let i = 0; i < count; i += 1) {
      const r = 7 + Math.random() * 16;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      positions.set([r * Math.sin(phi) * Math.cos(theta), r * Math.sin(phi) * Math.sin(theta) * 0.6, r * Math.cos(phi) - 6], i * 3);
      const c = palette[i % 4].clone().multiplyScalar(0.55 + Math.random() * 0.45);
      colors.set([c.r, c.g, c.b], i * 3);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    this.particles = new THREE.Points(geo, new THREE.PointsMaterial({ size: 0.075, vertexColors: true, transparent: true, opacity: 0.85, depthWrite: false, blending: THREE.AdditiveBlending, map: this.dotTexture(), toneMapped: false }));
    this.scene.add(this.particles);
  }

  // --- управление ---
  setProgress(p) {
    this.target = p;
  }

  setPointer(x, y) {
    this.pointer.set(x, y);
  }

  resize() {
    const w = window.innerWidth;
    const h = window.innerHeight;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    // в портретной ориентации отодвигаем камеру, а объекты — в центр и выше текста
    const portrait = w / h < 0.85;
    // в портретной ориентации (телефон) объекты — в верхней трети экрана, текст — под ними
    this.layout = portrait ? { xScale: 0.12, yShift: 2.55, scale: 0.62 } : w < 1100 ? { xScale: 0.85, yShift: 0, scale: 0.9 } : { xScale: 1, yShift: 0, scale: 1 };
    this.camera.fov = portrait ? 46 : 35;
    this.camera.updateProjectionMatrix();
    this.composer?.setSize(w, h);
    this.bloom?.setSize(w, h);
  }

  place(obj, frames, p, extra = 0) {
    const [x, y, z, rx, ry, rz, s] = frameAt(frames, p);
    obj.position.set(x * this.layout.xScale, y + this.layout.yShift, z);
    obj.rotation.set(rx, ry + extra, rz);
    const scale = s * this.layout.scale;
    obj.scale.setScalar(Math.max(scale, 0.0001));
    obj.visible = scale > 0.01;
    return scale;
  }

  update(dt) {
    const t = (this.time += dt);
    const motion = this.reducedMotion ? 0 : 1;
    this.progress += (this.target - this.progress) * (1 - Math.exp(-dt * 5));
    const p = this.progress;
    this.pointerSmooth.lerp(this.pointer, 1 - Math.exp(-dt * 3));

    // камера: лёгкий параллакс от мыши
    this.camera.position.x = this.pointerSmooth.x * 0.5 * motion;
    this.camera.position.y = this.pointerSmooth.y * 0.3 * motion;
    this.camera.lookAt(0, this.layout.yShift * 0.35, 0);

    // телефон
    this.place(this.phone, this.phoneFrames, p);
    this.phone.position.y += Math.sin(t * 0.9) * 0.08 * motion;
    this.phone.rotation.y += Math.sin(t * 0.5) * 0.05 * motion;
    this.phoneGlow.material.opacity = 0.35 + 0.2 * Math.sin(t * 1.4);

    // экран: что показывает чат (перерисовываем, только когда что-то меняется, ~20 раз в секунду)
    const state = p < 2.55 ? 'intro' : p < 3.55 ? 'digest' : p < 5.2 ? 'ai' : 'final';
    const changed = state !== this.screen.state;
    this.screen.set(state, t);
    if (changed || (this.screenAnimating && t - (this.screenDrawnAt || 0) > 0.05)) {
      this.screenAnimating = this.screen.draw(t);
      this.screenDrawnAt = t;
    }

    // пузыри сообщений вокруг телефона в начале и в конце
    const bubbleVis = Math.max(smooth(clamp(1 - p * 1.4)), smooth(clamp((p - 6.4) / 0.6)));
    for (const b of this.bubbles) {
      const u = b.userData;
      const a = u.angle + t * u.speed * motion;
      b.position.set(this.phone.position.x + Math.cos(a) * u.radius * this.layout.scale, this.phone.position.y + Math.sin(a * 1.3) * 1.5 * this.layout.scale + u.tilt * 0.4, this.phone.position.z + Math.sin(a) * u.radius * 0.6);
      b.rotation.set(0, -a * 0.2, Math.sin(a) * 0.15);
      b.scale.setScalar(Math.max(0.0001, bubbleVis * this.layout.scale));
      b.visible = bubbleVis > 0.01;
    }

    // дневник: открывается в главе 1, на страницах «пишется» ДЗ
    this.place(this.book, this.bookFrames, p);
    this.book.position.y += Math.sin(t * 0.8 + 1) * 0.06 * motion;
    const open = smooth(clamp(1 - Math.abs(p - 1) * 1.6));
    this.bookHinge.rotation.y = -open * 2.55;
    this.pages.update(clamp((p - 0.55) / 0.4));

    // часы: стрелки бегут к 14:45, кольца расходятся
    const clockScale = this.place(this.clock3d, this.clockFrames, p);
    if (clockScale > 0.01) {
      const minutes = lerp(8 * 60, 14 * 60 + 45, easeOut((p - 1.35) / 0.6));
      this.minuteHand.rotation.z = -((minutes % 60) / 60) * Math.PI * 2;
      this.hourHand.rotation.z = -((minutes / 60) % 12 / 12) * Math.PI * 2;
      const done = clamp((p - 1.9) / 0.15);
      for (const wave of this.clockWaves) {
        const k = (t * 0.45 + wave.userData.offset) % 1;
        wave.scale.setScalar(1 + k * 0.9);
        wave.material.opacity = (1 - k) * 0.5 * done;
      }
      this.clockRing.material.emissiveIntensity = 0.4 + done * (0.5 + 0.3 * Math.sin(t * 4));
    }

    // самолётик с ДЗ: от дневника к телефону
    const fly = clamp((p - 2.5) / 0.6);
    const flying = fly > 0 && fly < 1;
    this.plane.visible = flying;
    this.trail.visible = flying;
    if (flying) {
      const k = easeOut(fly);
      const pos = this.planePath.getPointAt(k);
      const ahead = this.planePath.getPointAt(Math.min(1, k + 0.02));
      const fit = (v) => v.set(v.x * this.layout.xScale, v.y + this.layout.yShift, v.z);
      fit(pos);
      fit(ahead);
      this.plane.position.copy(pos);
      this.plane.lookAt(ahead);
      this.plane.rotateZ(Math.sin(t * 6) * 0.12);
      this.plane.scale.setScalar(0.55 * this.layout.scale * (1 - smooth(clamp((k - 0.85) / 0.15)) * 0.8));
      const arr = this.trail.geometry.attributes.position.array;
      for (let i = 0; i < arr.length / 3; i += 1) {
        const back = Math.max(0, k - i * 0.008);
        const pt = fit(this.planePath.getPointAt(back));
        arr[i * 3] = pt.x + (Math.random() - 0.5) * 0.04;
        arr[i * 3 + 1] = pt.y + (Math.random() - 0.5) * 0.04;
        arr[i * 3 + 2] = pt.z;
      }
      this.trail.geometry.attributes.position.needsUpdate = true;
    }

    // ИИ-сфера
    const orbScale = this.place(this.orb, this.orbFrames, p);
    if (orbScale > 0.01) {
      this.orb.position.y += Math.sin(t * 1.3) * 0.1 * motion;
      this.orb.rotation.y = t * 0.4 * motion;
      this.orbCore.rotation.set(t * 0.7 * motion, t * 0.9 * motion, 0);
      this.orbCore.material.emissiveIntensity = 1.3 + Math.sin(t * 3) * 0.4;
      for (const e of this.electrons) {
        const a = t * e.userData.speed + e.userData.phase;
        e.position.set(Math.cos(a) * 1.35, Math.sin(a) * 1.35, 0);
      }
    }

    // щит
    const shieldScale = this.place(this.shield, this.shieldFrames, p, Math.sin(t * 0.7) * 0.25 * motion);
    if (shieldScale > 0.01) {
      this.shield.position.y += Math.sin(t * 0.9) * 0.07 * motion;
      for (const wave of this.shieldWaves) {
        const k = (t * 0.35 + wave.userData.offset) % 1;
        wave.scale.setScalar(0.8 + k * 1.2);
        wave.material.opacity = (1 - k) * 0.6;
      }
    }

    // плитки панели: дуга за сеткой возможностей
    const tilesVis = smooth(clamp(1 - Math.abs(p - 6) * 1.25));
    this.tiles.forEach((tile, i) => {
      const u = tile.userData;
      const radius = 5.6;
      const a = u.a + Math.sin(t * 0.2) * 0.05 * motion;
      tile.position.set(Math.sin(a) * radius * Math.max(this.layout.xScale, 0.55), u.y + Math.sin(t * 0.8 + u.phase) * 0.12 * motion + this.layout.yShift * 0.5, -Math.cos(a) * radius + 1.2);
      tile.lookAt(0, tile.position.y, 6);
      const s = Math.max(0.0001, tilesVis * this.layout.scale * (0.85 + (i % 2) * 0.15));
      tile.scale.setScalar(s);
      tile.visible = tilesVis > 0.01;
      tile.material.opacity = tilesVis;
    });

    // звёздная пыль медленно вращается, в финале — закручивается
    this.particles.rotation.y = t * 0.02 * motion + p * 0.12;
    this.particles.rotation.x = Math.sin(t * 0.05) * 0.05 * motion;
  }

  frame() {
    if (!this.running) return;
    const now = performance.now();
    const dt = Math.min((now - this.lastFrame) / 1000, 0.05);
    this.lastFrame = now;
    this.update(dt);
    if (this.composer) this.composer.render(dt);
    else this.renderer.render(this.scene, this.camera);
    this.raf = requestAnimationFrame(() => this.frame());
  }

  start() {
    if (this.running) return;
    this.running = true;
    this.lastFrame = performance.now();
    this.frame();
  }

  stop() {
    this.running = false;
    cancelAnimationFrame(this.raf);
  }
}

// --- страницы дневника: ДЗ «пишется» строка за строкой ---
class PagesTexture {
  constructor() {
    const { canvas, ctx, texture } = canvasTexture(512, 660);
    this.canvas = canvas;
    this.ctx = ctx;
    this.texture = texture;
    this.lastK = -1;
    this.rows = [
      ['Алгебра', '№ 250–255, стр. 84'],
      ['Русский язык', 'Упр. 312, правило'],
      ['История', 'Параграф 5, даты'],
      ['Физика', '§ 12, вопросы 1–4'],
      ['Английский', 'Ex. 4 p. 37'],
    ];
  }

  update(k) {
    const key = Math.round(k * 60);
    if (key === this.lastK) return;
    this.lastK = key;
    const { ctx } = this;
    const w = 512;
    const h = 660;
    ctx.fillStyle = '#f7f6ef';
    ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = 'rgba(37,99,235,0.12)';
    ctx.lineWidth = 2;
    for (let y = 120; y < h; y += 44) {
      ctx.beginPath();
      ctx.moveTo(36, y);
      ctx.lineTo(w - 36, y);
      ctx.stroke();
    }
    ctx.fillStyle = '#0f5132';
    ctx.font = `700 34px ${FONT}`;
    ctx.fillText('Среда, 15 октября', 40, 76);
    const shown = k * this.rows.length;
    this.rows.forEach(([subject, task], i) => {
      const part = clamp(shown - i);
      if (part <= 0) return;
      const y = 150 + i * 92;
      ctx.globalAlpha = Math.min(1, part * 2);
      ctx.fillStyle = '#111827';
      ctx.font = `700 30px ${FONT}`;
      ctx.fillText(subject, 40, y);
      ctx.fillStyle = '#334155';
      ctx.font = `400 28px ${FONT}`;
      const text = task.slice(0, Math.ceil(task.length * part));
      ctx.fillText(text, 40, y + 40);
      if (i === 3 && part >= 1) {
        ctx.fillStyle = '#25d366';
        ctx.beginPath();
        ctx.roundRect(w - 150, y - 28, 110, 36, 10);
        ctx.fill();
        ctx.fillStyle = '#052e16';
        ctx.font = `700 20px ${FONT}`;
        ctx.fillText('НОВОЕ', w - 130, y - 3);
      }
      ctx.globalAlpha = 1;
    });
    this.texture.needsUpdate = true;
  }
}

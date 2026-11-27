// Процедурные анимации гуманоида. Все углы — Эйлер (рад) в соглашениях VRM 1.0
// (персонаж смотрит в +Z, левая рука вдоль +X). Для VRM 0.x углы x и z инвертируются в аниматоре.

export const BONES = [
  'hips', 'spine', 'chest', 'upperChest', 'neck', 'head',
  'leftShoulder', 'leftUpperArm', 'leftLowerArm', 'leftHand',
  'rightShoulder', 'rightUpperArm', 'rightLowerArm', 'rightHand',
  'leftUpperLeg', 'leftLowerLeg', 'leftFoot', 'rightUpperLeg', 'rightLowerLeg', 'rightFoot',
];
export const FINGERS = [];
for (const side of ['left', 'right']) for (const f of ['Index', 'Middle', 'Ring', 'Little']) for (const seg of ['Proximal', 'Intermediate', 'Distal']) FINGERS.push(side + f + seg);
for (const side of ['left', 'right']) for (const seg of ['Proximal', 'Intermediate']) FINGERS.push(side + 'Thumb' + seg);

const S = Math.sin, C = Math.cos, PI = Math.PI;
const ease = (x) => (x <= 0 ? 0 : x >= 1 ? 1 : x * x * (3 - 2 * x));
/** Огибающая 0→1→0 для одноразовых клипов. */
const env = (t, d, fi = 0.25, fo = 0.3) => Math.min(ease(t / fi), ease((d - t) / fo));

/** Отзеркалить поворот с правой стороны на левую. */
export const mirror = ([x, y, z]) => [x, -y, -z];

/** Базовая поза покоя: руки опущены вдоль тела. */
const FINGER_REST = {};
for (const b of FINGERS) {
  const left = b.startsWith('left');
  const thumb = b.includes('Thumb');
  const curl = thumb ? 0.15 : b.includes('Proximal') ? 0.25 : 0.35;
  FINGER_REST[b] = thumb ? [0, left ? -curl : curl, 0] : [0, 0, left ? -curl : curl];
}

export function restPose() {
  return {
    ...FINGER_REST,
    leftUpperArm: [0, 0, -1.22], rightUpperArm: [0, 0, 1.22],
    leftLowerArm: [0, -0.12, 0], rightLowerArm: [0, 0.12, 0],
    leftHand: [0, 0, -0.05], rightHand: [0, 0, 0.05],
  };
}

/** Сидячая поза: бёдра вперёд, голени вниз (сидит на краю панели). */
export function sitPose(t = 0) {
  const swing = Math.sin(t * 2.1) * 0.12;
  return {
    leftUpperLeg: [-1.5, 0.08, 0.05], rightUpperLeg: [-1.5, -0.08, -0.05],
    leftLowerLeg: [1.45 + swing, 0, 0], rightLowerLeg: [1.45 - swing, 0, 0],
    leftFoot: [-0.15, 0, 0], rightFoot: [-0.15, 0, 0],
    leftUpperArm: [0, -0.35, -1.25], rightUpperArm: [0, 0.35, 1.25],
    leftLowerArm: [0, -0.35, 0], rightLowerArm: [0, 0.35, 0],
    spine: [0.06, 0, 0],
  };
}
/** Клипы, которые нельзя проигрывать сидя (заменяются). */
export const SIT_SAFE = { dance: 'laugh', jump: 'victory', spin: 'shy', bow: 'nod', stretch: 'shy', walk: null, run: null };

/** Дыхание и лёгкое покачивание поверх позы покоя. */
export function idleLayer(t, intensity = 1) {
  const b = S(t * 1.7) * intensity;
  const sway = S(t * 0.45) * intensity;
  return {
    spine: [0.015 * b, 0, 0.012 * sway],
    chest: [0.02 * b, 0.01 * S(t * 0.3), 0],
    neck: [0, 0, -0.01 * sway],
    head: [0.02 * S(t * 0.6 + 1) * intensity, 0.04 * S(t * 0.23) * intensity, 0.015 * S(t * 0.37) * intensity],
    hips: [0, 0, -0.012 * sway],
    leftUpperArm: [0.02 * b, 0.03 * S(t * 0.5), -1.22 + 0.03 * b],
    rightUpperArm: [0.02 * b, -0.03 * S(t * 0.5 + 1), 1.22 - 0.03 * b],
    hipsPos: [0.004 * sway, 0, 0],
  };
}

// ---------- Клипы ----------
// Каждый клип: { duration, loop, fn(t) => поза }. Поза — частичная, остальное берётся из базы.

const wave = {
  duration: 2.6, loop: false,
  fn: (t) => {
    const w = S(t * 9) * 0.38;
    return {
      rightUpperArm: [0, 0.25, -0.15], rightLowerArm: [0, 0.2, -1.75 + w], rightHand: [0, 0, -0.1 + w * 0.3],
      head: [0.02, -0.12, 0.08], chest: [0, -0.06, 0.04], spine: [0, 0, 0.03],
    };
  },
};

function danceA(t) { // «качка» с поднятыми руками
  const beat = t * PI * 2 * 1.05; // ~126 BPM / 2
  const b = S(beat), b2 = S(beat * 2);
  return {
    hipsPos: [0.035 * b, -0.035 * Math.abs(b2), 0],
    hips: [0, 0.18 * b, -0.12 * b], spine: [0.05, -0.1 * b, 0.1 * b], chest: [0.03, -0.08 * b, 0.06 * b],
    head: [0.08 * b2, 0.15 * b, -0.1 * b],
    leftUpperArm: [0, 0.3, -0.35 + 0.35 * b], leftLowerArm: [0, -0.4, 1.1 + 0.4 * b2],
    rightUpperArm: [0, -0.3, 0.35 + 0.35 * b], rightLowerArm: [0, 0.4, -1.1 + 0.4 * b2],
    leftUpperLeg: [-0.15 * Math.max(0, b), 0, 0.05], rightUpperLeg: [-0.15 * Math.max(0, -b), 0, -0.05],
    leftLowerLeg: [0.3 * Math.max(0, b), 0, 0], rightLowerLeg: [0.3 * Math.max(0, -b), 0, 0],
  };
}

function danceB(t) { // волна руками над головой
  const beat = t * PI * 2 * 0.9;
  const b = S(beat);
  return {
    hipsPos: [0.05 * b, -0.02 * Math.abs(S(beat * 2)), 0],
    hips: [0, 0, 0.12 * b], spine: [0, 0, -0.1 * b], chest: [0, 0.1 * S(beat + 1), -0.08 * b],
    head: [0, 0.1 * S(beat + 2), 0.12 * b],
    leftUpperArm: [0, 0.1, 0.7 + 0.2 * S(beat + 0.5)], leftLowerArm: [0, 0, 0.4 * S(beat * 2)], leftHand: [0, 0, 0.5 * S(beat * 2 + 1)],
    rightUpperArm: [0, -0.1, -0.7 + 0.2 * S(beat + 0.5)], rightLowerArm: [0, 0, 0.4 * S(beat * 2 + PI)], rightHand: [0, 0, 0.5 * S(beat * 2 + 1 + PI)],
    leftUpperLeg: [0, 0, 0.06 + 0.05 * b], rightUpperLeg: [0, 0, -0.06 + 0.05 * b],
  };
}

function danceC(t) { // «робот» / рубленые движения
  t = Math.max(0, t);
  const step = Math.floor(t * 2.2) % 4;
  const k = ease((t * 2.2) % 1 * 3);
  const poses = [
    { leftUpperArm: [0, 0, 0], leftLowerArm: [0, 0, 1.4], rightUpperArm: [0, 0, 1.2], rightLowerArm: [0, 0.1, 0], head: [0, 0.35, 0], hips: [0, 0.15, 0] },
    { leftUpperArm: [0, 0, -1.2], leftLowerArm: [0, -0.1, 0], rightUpperArm: [0, 0, 0], rightLowerArm: [0, 0, -1.4], head: [0, -0.35, 0], hips: [0, -0.15, 0] },
    { leftUpperArm: [0, -0.6, -0.1], leftLowerArm: [0, -1.4, 0], rightUpperArm: [0, 0.6, 0.1], rightLowerArm: [0, 1.4, 0], head: [0.15, 0, 0], hips: [0, 0, 0] },
    { leftUpperArm: [0, 0, 0.3], leftLowerArm: [0, 0, 0.3], rightUpperArm: [0, 0, -0.3], rightLowerArm: [0, 0, -0.3], head: [-0.1, 0, 0], hips: [0, 0, 0] },
  ];
  const a = poses[(step + 3) % 4], b = poses[step];
  const out = {};
  for (const bone of Object.keys(b)) out[bone] = b[bone].map((v, i) => a[bone][i] + (v - a[bone][i]) * k);
  out.hipsPos = [0, -0.03 * Math.abs(S(t * PI * 2.2)), 0];
  return out;
}

const dance = { duration: 8, loop: false, variants: [danceA, danceB, danceC], fn: danceA };

const nod = { duration: 1.3, loop: false, fn: (t) => ({ head: [0.22 * Math.max(0, S(t * PI * 3)), 0, 0], neck: [0.08 * Math.max(0, S(t * PI * 3)), 0, 0] }) };
const shake = { duration: 1.4, loop: false, fn: (t) => ({ head: [0, 0.3 * S(t * PI * 4) * env(t, 1.4), 0], neck: [0, 0.1 * S(t * PI * 4), 0] }) };

const think = {
  duration: 3.2, loop: false,
  fn: (t) => ({
    rightUpperArm: [0, 1.05, 0.85], rightLowerArm: [0, 2.35, 0], rightHand: [0, 0, 0.3],
    leftUpperArm: [0, -0.6, -1.1], leftLowerArm: [0, -1.3, 0],
    head: [-0.12, 0.12 + 0.04 * S(t * 2), 0.14], spine: [0, 0.05, 0],
  }),
};

const jump = {
  duration: 1.2, loop: false,
  fn: (t) => {
    const p = t / 1.2;
    const crouch = p < 0.25 ? S(p / 0.25 * PI / 2) : p > 0.8 ? S((1 - p) / 0.2 * PI / 2) * 0.6 : 0;
    const air = p >= 0.25 && p <= 0.8 ? S((p - 0.25) / 0.55 * PI) : 0;
    return {
      hipsPos: [0, -0.12 * crouch + 0.25 * air, 0],
      leftUpperLeg: [-0.6 * crouch - 0.2 * air, 0, 0], rightUpperLeg: [-0.6 * crouch - 0.2 * air, 0, 0],
      leftLowerLeg: [1.1 * crouch + 0.4 * air, 0, 0], rightLowerLeg: [1.1 * crouch + 0.4 * air, 0, 0],
      leftFoot: [-0.4 * crouch, 0, 0], rightFoot: [-0.4 * crouch, 0, 0],
      leftUpperArm: [0, 0, -1.2 + 1.9 * air], rightUpperArm: [0, 0, 1.2 - 1.9 * air],
      spine: [0.2 * crouch, 0, 0], head: [-0.15 * air, 0, 0],
    };
  },
};

const bow = {
  duration: 2.2, loop: false,
  fn: (t) => { const k = env(t, 2.2, 0.5, 0.6); return { spine: [0.45 * k, 0, 0], chest: [0.2 * k, 0, 0], head: [0.2 * k, 0, 0], leftUpperArm: [0, -0.3 * k, -1.25], rightUpperArm: [0, 0.3 * k, 1.25], leftLowerArm: [0, -0.5 * k, 0], rightLowerArm: [0, 0.5 * k, 0] }; },
};

const clap = {
  duration: 2.4, loop: false,
  fn: (t) => {
    const c = Math.abs(S(t * PI * 4));
    return {
      leftUpperArm: [0, -1.0, -0.9], rightUpperArm: [0, 1.0, 0.9],
      leftLowerArm: [0, -0.9 - 0.35 * c, 0], rightLowerArm: [0, 0.9 + 0.35 * c, 0],
      leftHand: [0, -0.2, 0], rightHand: [0, 0.2, 0],
      head: [0.05, 0, 0.05 * S(t * 4)], hipsPos: [0, -0.01 * c, 0],
    };
  },
};

const stretch = {
  duration: 3, loop: false,
  fn: (t) => { const k = env(t, 3, 0.7, 0.7); return { leftUpperArm: [0, 0, -1.22 + 2.6 * k], rightUpperArm: [0, 0, 1.22 - 2.6 * k], leftLowerArm: [0, 0, 0.3 * k], rightLowerArm: [0, 0, -0.3 * k], spine: [-0.15 * k, 0, 0.1 * S(t * 2) * k], chest: [-0.1 * k, 0, 0], head: [-0.25 * k, 0, 0] }; },
};

const spin = { duration: 1.6, loop: false, fn: (t) => ({ hips: [0, ease(t / 1.6) * PI * 2, 0], leftUpperArm: [0, 0, -0.6], rightUpperArm: [0, 0, 0.6], head: [0, 0, 0.1] }) };

const point = { duration: 2.4, loop: false, fn: () => ({ rightUpperArm: [0, 1.35, 0.15], rightLowerArm: [0, 0.1, 0], rightHand: [0, 0, 0], head: [0, -0.15, 0], chest: [0, -0.12, 0] }) };

const heart = {
  duration: 2.8, loop: false,
  fn: (t) => ({
    leftUpperArm: [0, 0.2, 0.75], rightUpperArm: [0, -0.2, -0.75],
    leftLowerArm: [0, 0, 1.6], rightLowerArm: [0, 0, -1.6],
    leftHand: [0, 0, 0.4], rightHand: [0, 0, -0.4],
    head: [0, 0, 0.12 * S(t * 3)], hipsPos: [0, 0.01 * S(t * 6), 0],
  }),
};

const laugh = {
  duration: 2.2, loop: false,
  fn: (t) => { const s = S(t * 22) * env(t, 2.2); return { chest: [-0.06 + 0.03 * s, 0, 0], spine: [-0.03, 0, 0], head: [-0.18 + 0.05 * s, 0, 0.06], leftShoulder: [0, 0, 0.05 * s], rightShoulder: [0, 0, -0.05 * s], leftUpperArm: [0, -0.5, -1.1], leftLowerArm: [0, -1.4, 0], rightUpperArm: [0, 0.5, 1.1], rightLowerArm: [0, 1.4, 0] }; },
};

const shrug = {
  duration: 2, loop: false,
  fn: (t) => { const k = env(t, 2, 0.3, 0.4); return { leftShoulder: [0, 0, 0.2 * k], rightShoulder: [0, 0, -0.2 * k], leftUpperArm: [0, -0.3 * k, -1.2 + 0.2 * k], rightUpperArm: [0, 0.3 * k, 1.2 - 0.2 * k], leftLowerArm: [0, -1.2 * k, -0.4 * k], rightLowerArm: [0, 1.2 * k, 0.4 * k], head: [0.05, 0, 0.18 * k] }; },
};

const victory = {
  duration: 2.4, loop: false,
  fn: (t) => { const p = Math.abs(S(t * PI * 2.5)); return { rightUpperArm: [0, 0, -1.25 - 0.15 * p], rightLowerArm: [0, 0, -0.3 * p], leftUpperArm: [0, 0, -1.3], head: [-0.1, 0, 0.05], hipsPos: [0, 0.02 * p, 0], spine: [-0.05, 0, 0.05] }; },
};

const sleepy = {
  duration: 4, loop: false,
  fn: (t) => { const k = env(t, 4, 0.8, 0.8); return { head: [0.35 * k, 0, 0.2 * k * S(t * 0.8)], neck: [0.1 * k, 0, 0], spine: [0.08 * k, 0, 0], leftUpperArm: [0, 0, -1.3], rightUpperArm: [0, 0.4 * k, 1.1], rightLowerArm: [0, 2.0 * k, 0] }; },
};

const shy = {
  duration: 3, loop: false,
  fn: (t) => ({ leftUpperArm: [0, -0.55, -1.15], rightUpperArm: [0, 0.55, 1.15], leftLowerArm: [0, -0.9, 0], rightLowerArm: [0, 0.9, 0], head: [0.2, 0.15, 0.15 + 0.05 * S(t * 2)], spine: [0.05, 0, 0.05 * S(t * 1.5)] }),
};

const lookAround = {
  duration: 4, loop: false,
  fn: (t) => ({ head: [0.05, 0.45 * S(t * PI / 2) * env(t, 4, 0.6, 0.6), 0], chest: [0, 0.12 * S(t * PI / 2), 0] }),
};

const surprised = {
  duration: 1.4, loop: false,
  fn: (t) => { const k = env(t, 1.4, 0.1, 0.5); return { spine: [-0.1 * k, 0, 0], head: [-0.12 * k, 0, 0], leftUpperArm: [0, -0.4 * k, -1.0], rightUpperArm: [0, 0.4 * k, 1.0], leftLowerArm: [0, -1.0 * k, 0], rightLowerArm: [0, 1.0 * k, 0], hipsPos: [0, 0.015 * k, 0] }; },
};

const greet = { // приветствие при появлении: поклон + взмах
  duration: 3.2, loop: false,
  fn: (t) => (t < 1.0 ? bow.fn(t * 2.2 / 1.0 * 0.5) : wave.fn(t - 1.0)),
};

const walk = {
  duration: 1, loop: true,
  fn: (t) => {
    const p = t * PI * 2 * 1.6, a = S(p);
    return {
      leftUpperLeg: [-0.45 * a, 0, 0], rightUpperLeg: [0.45 * a, 0, 0],
      leftLowerLeg: [0.5 * Math.max(0, S(p + 1.2)), 0, 0], rightLowerLeg: [0.5 * Math.max(0, -S(p + 1.2)), 0, 0],
      leftUpperArm: [0, 0.35 * a, -1.25], rightUpperArm: [0, 0.35 * a, 1.25],
      spine: [0.04, 0.06 * a, 0], hipsPos: [0, 0.018 * Math.abs(S(p)), 0],
    };
  },
};
const run = {
  duration: 1, loop: true,
  fn: (t) => {
    const p = t * PI * 2 * 2.6, a = S(p);
    return {
      leftUpperLeg: [-0.85 * a - 0.2, 0, 0], rightUpperLeg: [0.85 * a - 0.2, 0, 0],
      leftLowerLeg: [0.9 + 0.6 * S(p + 1.4), 0, 0], rightLowerLeg: [0.9 - 0.6 * S(p + 1.4), 0, 0],
      leftUpperArm: [0, 0.8 * a, -1.15], rightUpperArm: [0, 0.8 * a, 1.15],
      leftLowerArm: [0, -1.3, 0], rightLowerArm: [0, 1.3, 0],
      spine: [0.22, 0.1 * a, 0], head: [-0.12, 0, 0], hipsPos: [0, 0.05 * Math.abs(S(p)), 0],
    };
  },
};

export const CLIPS = { walk, run, wave, dance, nod, shake, think, jump, bow, clap, stretch, spin, point, heart, laugh, shrug, victory, sleepy, shy, lookAround, surprised, greet };
export const CLIP_NAMES = Object.keys(CLIPS);

/** Возвращает позу клипа в момент t (поддерживает варианты танца). */
export function clipPose(name, t, variant = 0) {
  const c = CLIPS[name];
  if (!c) return {};
  const f = c.variants ? c.variants[variant % c.variants.length] : c.fn;
  const tt = Math.max(0, t);
  return f(c.loop ? tt % c.duration : Math.min(tt, c.duration));
}

/** Смешивание двух поз: a*(1-w) + b*w (по костям, которые есть хотя бы в одной из поз). */
export function blendPoses(a, b, w) {
  const out = { ...a };
  for (const k of Object.keys(b)) {
    const av = a[k] || [0, 0, 0], bv = b[k];
    out[k] = [av[0] + (bv[0] - av[0]) * w, av[1] + (bv[1] - av[1]) * w, av[2] + (bv[2] - av[2]) * w];
  }
  return out;
}

/** Сложение слоёв (для idle поверх отдыха — idle уже включает абсолютные руки). */
export function mergePoses(...poses) { return Object.assign({}, ...poses); }

/** Для VRM 0.x модель повёрнута на 180° — инвертируем x и z. */
export function toVrm0([x, y, z]) { return [-x, y, -z]; }

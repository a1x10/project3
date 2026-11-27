#!/usr/bin/env node
// Генератор VRM 1.0 модели «Марк» из процедурных примитивов.
// Запуск: node tools/generate-mark.mjs [путь_вывода]
import { writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { GLBBuilder } from './glb-writer.mjs';
import { superEllipsoid, capsule, lens, computeNormals, orientOutward } from './geometry.mjs';

const __dirname = dirname(fileURLToPath(import.meta.url));

export const MARK_EXPRESSIONS = ['aa', 'ih', 'ou', 'ee', 'oh', 'blink', 'blinkLeft', 'blinkRight', 'happy', 'angry', 'sad', 'relaxed', 'surprised'];

// Скелет в мировых координатах (Т-поза, вперёд = +Z, левая сторона персонажа = +X)
export const BONES = {
  hips: { parent: null, pos: [0, 0.95, 0] },
  spine: { parent: 'hips', pos: [0, 1.05, 0] },
  chest: { parent: 'spine', pos: [0, 1.2, 0] },
  neck: { parent: 'chest', pos: [0, 1.46, 0] },
  head: { parent: 'neck', pos: [0, 1.56, 0] },
  leftShoulder: { parent: 'chest', pos: [0.05, 1.41, 0] },
  leftUpperArm: { parent: 'leftShoulder', pos: [0.19, 1.41, 0] },
  leftLowerArm: { parent: 'leftUpperArm', pos: [0.45, 1.41, 0] },
  leftHand: { parent: 'leftLowerArm', pos: [0.68, 1.41, 0] },
  rightShoulder: { parent: 'chest', pos: [-0.05, 1.41, 0] },
  rightUpperArm: { parent: 'rightShoulder', pos: [-0.19, 1.41, 0] },
  rightLowerArm: { parent: 'rightUpperArm', pos: [-0.45, 1.41, 0] },
  rightHand: { parent: 'rightLowerArm', pos: [-0.68, 1.41, 0] },
  leftUpperLeg: { parent: 'hips', pos: [0.09, 0.9, 0] },
  leftLowerLeg: { parent: 'leftUpperLeg', pos: [0.09, 0.5, 0] },
  leftFoot: { parent: 'leftLowerLeg', pos: [0.09, 0.09, 0] },
  rightUpperLeg: { parent: 'hips', pos: [-0.09, 0.9, 0] },
  rightLowerLeg: { parent: 'rightUpperLeg', pos: [-0.09, 0.5, 0] },
  rightFoot: { parent: 'rightLowerLeg', pos: [-0.09, 0.09, 0] },
};

const MATERIALS = {
  skin: [0.96, 0.78, 0.66], hair: [0.2, 0.13, 0.09], jacket: [0.16, 0.22, 0.42], jacketDark: [0.1, 0.14, 0.28],
  shirt: [0.95, 0.95, 0.97], pants: [0.14, 0.14, 0.19], shoe: [0.96, 0.96, 0.96], sole: [0.55, 0.57, 0.65],
  eyeWhite: [1, 1, 1], iris: [0.18, 0.42, 0.78], pupil: [0.04, 0.04, 0.07], brow: [0.17, 0.11, 0.08],
  mouth: [0.32, 0.08, 0.1], highlight: [1, 1, 1], accent: [0.45, 0.85, 1.0],
};

const H = BONES.head.pos[1];
const head = (x, y, z) => [x, H + y, z];

function bodyParts() {
  const P = [];
  const add = (bone, mat, geom, opts = {}) => P.push({ bone, mat, geom: opts.flat ? geom : orientOutward(geom) });
  // Голова
  add('head', 'skin', superEllipsoid({ center: head(0, 0.11, 0), radii: [0.1, 0.124, 0.105], seg: 40, rings: 28 }));
  add('head', 'skin', superEllipsoid({ center: head(0, 0.0, 0.03), radii: [0.042, 0.03, 0.045], seg: 24, rings: 14 })); // подбородок
  add('head', 'skin', superEllipsoid({ center: head(0, 0.075, 0.104), radii: [0.012, 0.018, 0.013] })); // нос
  for (const s of [1, -1]) add('head', 'skin', superEllipsoid({ center: head(0.103 * s, 0.09, -0.005), radii: [0.016, 0.03, 0.017] })); // уши
  // Волосы: шапка с переменной линией роста + чёлка + хохолок
  const polarMax = (az) => {
    const front = Math.cos(az); // 1 спереди, -1 сзади
    return (front > 0 ? 1.15 - 0.15 * front : 1.75 - 0.6 * (1 + front)) + (1 - Math.abs(front)) * 0.55;
  };
  add('head', 'hair', superEllipsoid({ center: head(0, 0.118, -0.012), radii: [0.116, 0.13, 0.124], polarMax, seg: 40, rings: 20 }));
  add('head', 'hair', superEllipsoid({ center: head(0, 0.07, -0.05), radii: [0.104, 0.1, 0.085] })); // затылок
  const fringe = [[-0.07, 0.35, 0.17], [-0.04, 0.25, 0.16], [-0.008, 0.12, 0.155], [0.025, -0.05, 0.16], [0.055, -0.2, 0.165], [0.08, -0.35, 0.175]];
  for (const [x, rz, y] of fringe) {
    add('head', 'hair', superEllipsoid({ center: head(x, y + 0.02, 0.09), radii: [0.02, 0.048, 0.016], e1: 1.4, rot: [-0.45, 0, rz] }));
  }
  for (const [x, rz, rx] of [[0, 0, -0.3], [0.03, -0.4, -0.2], [-0.03, 0.4, -0.2]]) {
    add('head', 'hair', superEllipsoid({ center: head(x, 0.235, 0.03), radii: [0.03, 0.06, 0.035], rot: [rx, 0, rz] }));
  }
  for (const s of [1, -1]) add('head', 'hair', superEllipsoid({ center: head(0.1 * s, 0.14, 0.0), radii: [0.03, 0.06, 0.07], rot: [0.2, 0, 0.15 * s] })); // виски

  // Шея
  add('neck', 'skin', capsule([0, 1.43, 0], [0, 1.6, 0], 0.046, 0.044));
  // Торс
  add('hips', 'pants', superEllipsoid({ center: [0, 0.94, 0], radii: [0.158, 0.075, 0.103], e1: 0.6, e2: 0.8 }));
  add('hips', 'jacketDark', superEllipsoid({ center: [0, 0.99, 0], radii: [0.163, 0.025, 0.11], e1: 0.5, e2: 0.8 })); // ремень
  add('spine', 'jacket', superEllipsoid({ center: [0, 1.17, 0], radii: [0.158, 0.17, 0.103], e1: 0.9, e2: 0.8 }));
  add('chest', 'jacket', superEllipsoid({ center: [0, 1.31, 0], radii: [0.18, 0.15, 0.112], e1: 0.85, e2: 0.75 }));
  add('chest', 'shirt', superEllipsoid({ center: [0, 1.36, 0.075], radii: [0.05, 0.075, 0.04], e1: 1.2 })); // футболка в вырезе
  for (const s of [1, -1]) add('chest', 'jacketDark', capsule([0.04 * s, 1.43, 0.1], [0.012 * s, 1.07, 0.098], 0.008, 0.006)); // молния/лацканы
  add('chest', 'accent', superEllipsoid({ center: [0.09, 1.33, 0.105], radii: [0.016, 0.016, 0.004], rot: [-0.35, 0.5, 0] })); // значок
  add('chest', 'jacketDark', superEllipsoid({ center: [0, 1.45, -0.005], radii: [0.075, 0.04, 0.07], e1: 0.6 })); // воротник
  for (const s of [1, -1]) {
    // Плечи и руки
    add(s > 0 ? 'leftUpperArm' : 'rightUpperArm', 'jacket', superEllipsoid({ center: [0.2 * s, 1.41, 0], radii: [0.062, 0.06, 0.06] }));
    add(s > 0 ? 'leftUpperArm' : 'rightUpperArm', 'jacket', capsule([0.2 * s, 1.41, 0], [0.45 * s, 1.41, 0], 0.056, 0.048));
    add(s > 0 ? 'leftLowerArm' : 'rightLowerArm', 'jacket', capsule([0.45 * s, 1.41, 0], [0.64 * s, 1.41, 0], 0.048, 0.042));
    add(s > 0 ? 'leftLowerArm' : 'rightLowerArm', 'shirt', capsule([0.64 * s, 1.41, 0], [0.665 * s, 1.41, 0], 0.043, 0.043));
    const hand = s > 0 ? 'leftHand' : 'rightHand';
    add(hand, 'skin', superEllipsoid({ center: [0.73 * s, 1.405, 0], radii: [0.064, 0.027, 0.047], e1: 0.8, e2: 0.8 }));
    for (let f = 0; f < 4; f++) add(hand, 'skin', capsule([0.78 * s, 1.405, 0.03 - f * 0.02], [0.83 * s, 1.4, 0.032 - f * 0.021], 0.011, 0.009, 12, 5));
    add(hand, 'skin', capsule([0.7 * s, 1.405, 0.035], [0.745 * s, 1.4, 0.07], 0.014, 0.011, 12, 5));
    // Ноги
    add(s > 0 ? 'leftUpperLeg' : 'rightUpperLeg', 'pants', capsule([0.09 * s, 0.92, 0], [0.09 * s, 0.5, 0], 0.078, 0.062));
    add(s > 0 ? 'leftLowerLeg' : 'rightLowerLeg', 'pants', capsule([0.09 * s, 0.5, 0], [0.09 * s, 0.12, 0], 0.06, 0.048));
    const foot = s > 0 ? 'leftFoot' : 'rightFoot';
    add(foot, 'shoe', superEllipsoid({ center: [0.09 * s, 0.055, 0.035], radii: [0.056, 0.048, 0.118], e1: 0.6, e2: 0.7 }));
    add(foot, 'sole', superEllipsoid({ center: [0.09 * s, 0.014, 0.035], radii: [0.059, 0.014, 0.122], e1: 0.4, e2: 0.7 }));
    add(foot, 'accent', superEllipsoid({ center: [0.135 * s, 0.06, 0.03], radii: [0.006, 0.018, 0.05] }));
  }
  return P;
}

// --- Лицо с морф-таргетами ---
function faceParts() {
  const F = [];
  const eyeY = 0.088, eyeZ = 0.094;
  for (const side of ['L', 'R']) {
    const s = side === 'L' ? 1 : -1, x = 0.041 * s;
    const c = head(x, eyeY, eyeZ);
    F.push({ tag: 'eye' + side, mat: 'eyeWhite', center: c, geom: orientOutward(superEllipsoid({ center: c, radii: [0.022, 0.026, 0.009] })) });
    const ci = head(x, eyeY - 0.002, eyeZ + 0.0055);
    F.push({ tag: 'eye' + side, mat: 'iris', center: c, geom: orientOutward(superEllipsoid({ center: ci, radii: [0.0145, 0.0175, 0.0045] })) });
    const cp = head(x, eyeY - 0.002, eyeZ + 0.0085);
    F.push({ tag: 'eye' + side, mat: 'pupil', center: c, geom: orientOutward(superEllipsoid({ center: cp, radii: [0.0075, 0.009, 0.0025] })) });
    const chl = head(x + 0.005, eyeY + 0.006, eyeZ + 0.0105);
    F.push({ tag: 'eye' + side, mat: 'highlight', center: c, geom: orientOutward(superEllipsoid({ center: chl, radii: [0.004, 0.0045, 0.0015], seg: 12, rings: 8 })) });
    const cb = head(0.043 * s, 0.128, 0.097);
    F.push({ tag: 'brow' + side, mat: 'brow', center: cb, side: s, geom: orientOutward(superEllipsoid({ center: cb, radii: [0.024, 0.0055, 0.006], rot: [0, 0, 0.08 * s] })) });
  }
  const mc = head(0, 0.034, 0.0842);
  F.push({ tag: 'mouth', mat: 'mouth', center: mc, geom: lens({ center: mc, width: 0.021, height: 0.0032, curve: 0.006 }) });
  return F;
}

function faceTargetDelta(target, part, x, y, z, uv) {
  const [cx, cy] = part.center;
  const dx = x - cx, dy = y - cy;
  const zero = [0, 0, 0];
  if (part.tag === 'mouth') {
    const [u, v] = uv; const env = Math.sqrt(Math.max(0, 1 - u * u));
    const shape = (wScale, h, drop = 0) => [dx * (wScale - 1), v * h * env - dy + (v < 0 ? -drop * env : 0) - drop * 0.3 * env, 0];
    switch (target) {
      case 'aa': return shape(1.0, 0.016, 0.006);
      case 'ih': return shape(1.3, 0.006);
      case 'ou': return shape(0.55, 0.011, 0.002);
      case 'ee': return shape(1.2, 0.009, 0.002);
      case 'oh': return shape(0.75, 0.015, 0.004);
      case 'happy': return [dx * 0.15, 0.007 * u * u + v * 0.003 * env, 0];
      case 'relaxed': return [0, 0.004 * u * u, 0];
      case 'sad': return [0, -0.007 * u * u, 0];
      case 'angry': return [dx * -0.1, -0.004 * u * u, 0];
      case 'surprised': return shape(0.6, 0.013, 0.003);
      default: return zero;
    }
  }
  if (part.tag.startsWith('eye')) {
    const side = part.tag.endsWith('L') ? 'Left' : 'Right';
    const close = (k) => [0, -dy * k + (dy < 0 ? 0 : 0), 0];
    if (target === 'blink' || target === 'blink' + side) return [0, -dy * 0.92 - 0.004, 0];
    if (target === 'happy') return [0, -dy * 0.6 + 0.002, 0];
    if (target === 'relaxed') return close(0.35);
    if (target === 'surprised') return [dx * 0.15, dy * 0.2, 0];
    if (target === 'angry') return [0, dy > 0 ? -dy * 0.3 : 0, 0];
    if (target === 'sad') return [0, dy > 0 ? -dy * 0.2 : 0, 0];
    return zero;
  }
  if (part.tag.startsWith('brow')) {
    const inner = -dx * part.side; // >0 ближе к центру лица
    switch (target) {
      case 'angry': return [0, -0.007 + -inner * 0.25, 0];
      case 'sad': return [0, 0.002 + inner * 0.3, 0];
      case 'surprised': return [0, 0.009, 0];
      case 'happy': return [0, 0.004, 0];
      default: return zero;
    }
  }
  return zero;
}

export function buildMark() {
  const g = new GLBBuilder();
  const matIndex = {};
  for (const [name, c] of Object.entries(MATERIALS)) {
    const m = { name, pbrMetallicRoughness: { baseColorFactor: [...c, 1], metallicFactor: 0, roughnessFactor: name === 'eyeWhite' || name === 'iris' || name === 'pupil' ? 0.25 : 0.75 } };
    if (name === 'highlight' || name === 'accent') m.emissiveFactor = name === 'highlight' ? [1, 1, 1] : [0.25, 0.55, 0.7];
    if (name === 'mouth') m.doubleSided = true;
    matIndex[name] = g.addMaterial(m);
  }
  // Ноды костей
  const boneNode = {};
  const order = Object.keys(BONES);
  for (const name of order) {
    const b = BONES[name];
    const pp = b.parent ? BONES[b.parent].pos : [0, 0, 0];
    boneNode[name] = g.addNode({ name, translation: [b.pos[0] - pp[0], b.pos[1] - pp[1], b.pos[2] - pp[2]], children: [] });
  }
  for (const name of order) {
    const b = BONES[name];
    if (b.parent) g.json.nodes[boneNode[b.parent]].children.push(boneNode[name]);
  }
  const root = g.addNode({ name: 'Mark', children: [boneNode.hips] });
  g.json.scenes[0].nodes.push(root);

  const prim = (positions, normals, indices, mat, targets) => {
    const p = { attributes: {}, material: matIndex[mat], mode: 4 };
    p.attributes.POSITION = g.addAccessor(positions, 'VEC3', { target: 34962, minmax: true });
    p.attributes.NORMAL = g.addAccessor(normals, 'VEC3', { target: 34962 });
    const idxArr = positions.length / 3 > 65535 ? new Uint32Array(indices) : new Uint16Array(indices);
    p.indices = g.addAccessor(idxArr, 'SCALAR', { target: 34963 });
    if (targets) p.targets = targets.map((t) => ({ POSITION: g.addAccessor(t, 'VEC3', { minmax: true }) }));
    return p;
  };

  // Части тела: группируем по кости и материалу
  const groups = new Map();
  for (const part of bodyParts()) {
    const key = part.bone;
    if (!groups.has(key)) groups.set(key, new Map());
    const byMat = groups.get(key);
    if (!byMat.has(part.mat)) byMat.set(part.mat, []);
    byMat.get(part.mat).push(part.geom);
  }
  let triCount = 0;
  for (const [bone, byMat] of groups) {
    const bp = BONES[bone].pos;
    const primitives = [];
    for (const [mat, geoms] of byMat) {
      const pos = [], idx = [], nrm = [];
      for (const geo of geoms) {
        const base = pos.length / 3;
        const n = computeNormals(geo.pos, geo.idx);
        for (let i = 0; i < geo.pos.length; i += 3) { pos.push(geo.pos[i] - bp[0], geo.pos[i + 1] - bp[1], geo.pos[i + 2] - bp[2]); nrm.push(n[i], n[i + 1], n[i + 2]); }
        for (const k of geo.idx) idx.push(k + base);
      }
      triCount += idx.length / 3;
      primitives.push(prim(new Float32Array(pos), new Float32Array(nrm), idx, mat));
    }
    const mesh = g.addMesh({ name: `${bone}_mesh`, primitives });
    const node = g.addNode({ name: `${bone}_geo`, mesh });
    g.json.nodes[boneNode[bone]].children.push(node);
  }

  // Лицо
  const hp = BONES.head.pos;
  const facePrims = [];
  for (const part of faceParts()) {
    const { pos: wp, idx, uv } = part.geom;
    const nrm = computeNormals(wp, idx);
    const pos = new Float32Array(wp.length);
    for (let i = 0; i < wp.length; i += 3) { pos[i] = wp[i] - hp[0]; pos[i + 1] = wp[i + 1] - hp[1]; pos[i + 2] = wp[i + 2] - hp[2]; }
    const targets = MARK_EXPRESSIONS.map((t) => {
      const d = new Float32Array(wp.length);
      for (let i = 0, v = 0; i < wp.length; i += 3, v++) {
        const del = faceTargetDelta(t, part, wp[i], wp[i + 1], wp[i + 2], uv ? [uv[v * 2], uv[v * 2 + 1]] : null);
        d[i] = del[0]; d[i + 1] = del[1]; d[i + 2] = del[2];
      }
      return d;
    });
    triCount += idx.length / 3;
    facePrims.push(prim(pos, nrm, idx, part.mat, targets));
  }
  const faceMesh = g.addMesh({ name: 'Face', primitives: facePrims, weights: MARK_EXPRESSIONS.map(() => 0), extras: { targetNames: MARK_EXPRESSIONS } });
  const faceNode = g.addNode({ name: 'Face', mesh: faceMesh });
  g.json.nodes[boneNode.head].children.push(faceNode);

  // VRM 1.0
  const humanBones = {};
  for (const name of order) humanBones[name] = { node: boneNode[name] };
  const preset = {};
  MARK_EXPRESSIONS.forEach((name, i) => {
    preset[name] = {
      morphTargetBinds: [{ node: faceNode, index: i, weight: 1 }],
      isBinary: false,
      overrideBlink: ['blink', 'blinkLeft', 'blinkRight'].includes(name) ? 'none' : (name === 'happy' || name === 'surprised' ? 'block' : 'none'),
      overrideLookAt: 'none', overrideMouth: ['happy', 'surprised', 'sad', 'angry'].includes(name) ? 'blend' : 'none',
    };
  });
  preset.neutral = { isBinary: false };
  g.json.extensionsUsed.push('VRMC_vrm');
  g.json.extensions.VRMC_vrm = {
    specVersion: '1.0',
    meta: {
      name: 'Mark', version: '1.0.0', authors: ['Stella Assistant (procedural generator)'],
      licenseUrl: 'https://vrm.dev/licenses/1.0/', avatarPermission: 'everyone',
      allowExcessivelyViolentUsage: false, allowExcessivelySexualUsage: false, commercialUsage: 'personalNonProfit',
      allowPoliticalOrReligiousUsage: false, allowAntisocialOrHateUsage: false, creditNotation: 'unnecessary',
      allowRedistribution: true, modification: 'allowModificationRedistribution',
    },
    humanoid: { humanBones },
    expressions: { preset },
  };
  return { glb: g.toGLB(), triCount, json: g.json };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const out = resolve(process.argv[2] || resolve(__dirname, '../assets/models/mark.vrm'));
  mkdirSync(dirname(out), { recursive: true });
  const { glb, triCount } = buildMark();
  writeFileSync(out, glb);
  console.log(`Марк сгенерирован: ${out} (${(glb.length / 1024).toFixed(0)} КБ, ${triCount} треугольников)`);
}

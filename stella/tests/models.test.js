import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { buildMark, BONES, MARK_EXPRESSIONS } from '../tools/generate-mark.mjs';
import { parseGLB } from '../tools/glb-writer.mjs';
import { superEllipsoid, capsule, lens, computeNormals, rotMatrix, applyMat } from '../tools/geometry.mjs';

const ROOT = path.resolve(import.meta.dirname, '..');
const REQUIRED_VRM1 = ['hips', 'spine', 'head', 'leftUpperArm', 'leftLowerArm', 'leftHand', 'rightUpperArm', 'rightLowerArm', 'rightHand', 'leftUpperLeg', 'leftLowerLeg', 'leftFoot', 'rightUpperLeg', 'rightLowerLeg', 'rightFoot'];

describe('Генератор Марка (VRM 1.0)', () => {
  const { glb, json } = buildMark();
  const parsed = parseGLB(glb);

  it('корректный GLB-заголовок', () => { expect(parsed.version).toBe(2); expect(parsed.length).toBe(glb.length); });
  it('объявлено расширение VRMC_vrm 1.0', () => { expect(parsed.json.extensionsUsed).toContain('VRMC_vrm'); expect(parsed.json.extensions.VRMC_vrm.specVersion).toBe('1.0'); });
  it('meta: имя и лицензия', () => { const m = parsed.json.extensions.VRMC_vrm.meta; expect(m.name).toBe('Mark'); expect(m.licenseUrl).toMatch(/^https:/); expect(m.authors.length).toBeGreaterThan(0); });
  it('все обязательные кости гуманоида есть и указывают на ноды', () => {
    const hb = parsed.json.extensions.VRMC_vrm.humanoid.humanBones;
    for (const b of REQUIRED_VRM1) { expect(hb[b]).toBeDefined(); expect(parsed.json.nodes[hb[b].node].name).toBe(b); }
  });
  it('скелет — дерево без циклов, ноги ниже головы', () => {
    const nodes = parsed.json.nodes; const seen = new Set();
    const walk = (i) => { expect(seen.has(i)).toBe(false); seen.add(i); for (const c of nodes[i].children || []) walk(c); };
    for (const r of parsed.json.scenes[0].nodes) walk(r);
    expect(seen.size).toBe(nodes.length);
    expect(BONES.leftFoot.pos[1]).toBeLessThan(BONES.head.pos[1]);
  });
  it('левая рука на +X (соглашение VRM 1.0)', () => { expect(BONES.leftHand.pos[0]).toBeGreaterThan(0); expect(BONES.rightHand.pos[0]).toBeLessThan(0); });
  it('ноды костей без поворотов (Т-поза)', () => { for (const n of parsed.json.nodes) expect(n.rotation).toBeUndefined(); });
  it('все выражения ссылаются на существующие морф-таргеты', () => {
    const preset = parsed.json.extensions.VRMC_vrm.expressions.preset;
    for (const name of MARK_EXPRESSIONS) {
      const b = preset[name].morphTargetBinds[0];
      const mesh = parsed.json.meshes[parsed.json.nodes[b.node].mesh];
      for (const p of mesh.primitives) expect(p.targets.length).toBeGreaterThan(b.index);
      expect(b.weight).toBe(1);
    }
  });
  it('есть все гласные для липсинка и моргание', () => { for (const v of ['aa', 'ih', 'ou', 'ee', 'oh', 'blink', 'happy']) expect(MARK_EXPRESSIONS).toContain(v); });
  it('все примитивы лица имеют одинаковое число морфов', () => {
    const face = parsed.json.meshes.find((m) => m.name === 'Face');
    expect(new Set(face.primitives.map((p) => p.targets.length)).size).toBe(1);
    expect(face.extras.targetNames).toEqual(MARK_EXPRESSIONS);
  });
  it('аксессоры POSITION имеют min/max, данные в пределах буфера', () => {
    for (const m of parsed.json.meshes) for (const p of m.primitives) {
      const a = parsed.json.accessors[p.attributes.POSITION];
      expect(a.min).toHaveLength(3); expect(a.max).toHaveLength(3);
      for (const t of p.targets || []) expect(parsed.json.accessors[t.POSITION].min).toHaveLength(3);
    }
    for (const bv of parsed.json.bufferViews) expect(bv.byteOffset + bv.byteLength).toBeLessThanOrEqual(parsed.bin.length);
  });
  it('индексы треугольников не выходят за вершины', () => {
    for (const m of parsed.json.meshes) for (const p of m.primitives) {
      const ia = parsed.json.accessors[p.indices], pa = parsed.json.accessors[p.attributes.POSITION];
      const bv = parsed.json.bufferViews[ia.bufferView];
      const Arr = ia.componentType === 5125 ? Uint32Array : Uint16Array;
      const idx = new Arr(parsed.bin.buffer.slice(parsed.bin.byteOffset + bv.byteOffset, parsed.bin.byteOffset + bv.byteOffset + bv.byteLength));
      expect(Math.max(...idx)).toBeLessThan(pa.count);
      expect(idx.length % 3).toBe(0);
    }
  });
  it('нормали единичной длины', () => {
    const p = parsed.json.meshes[0].primitives[0];
    const a = parsed.json.accessors[p.attributes.NORMAL], bv = parsed.json.bufferViews[a.bufferView];
    const n = new Float32Array(parsed.bin.buffer.slice(parsed.bin.byteOffset + bv.byteOffset, parsed.bin.byteOffset + bv.byteOffset + bv.byteLength));
    for (let i = 0; i < n.length; i += 30) expect(Math.hypot(n[i], n[i + 1], n[i + 2])).toBeCloseTo(1, 3);
  });
  it('рост персонажа ~1.8 м', () => {
    let maxY = -Infinity;
    for (const m of json.meshes) for (const p of m.primitives) maxY = Math.max(maxY, json.accessors[p.attributes.POSITION].max[1]);
    expect(BONES.head.pos[1] + maxY).toBeGreaterThan(1.7);
    expect(BONES.head.pos[1] + maxY).toBeLessThan(1.95);
  });
  it('генерация детерминирована', () => expect(buildMark().glb.equals(glb)).toBe(true));
});

describe('Файлы моделей в assets', () => {
  it('mark.vrm существует и совпадает с генератором', () => {
    const f = fs.readFileSync(path.join(ROOT, 'assets/models/mark.vrm'));
    expect(f.equals(buildMark().glb)).toBe(true);
  });
  it.skipIf(!fs.existsSync(path.join(ROOT, 'assets/models/stella.vrm')))('stella.vrm — валидная VRM 0.x модель с нужными выражениями', () => {
    const { json } = parseGLB(fs.readFileSync(path.join(ROOT, 'assets/models/stella.vrm')));
    expect(json.extensions.VRM).toBeDefined();
    const bones = json.extensions.VRM.humanoid.humanBones.map((b) => b.bone);
    for (const b of REQUIRED_VRM1) expect(bones).toContain(b);
    const presets = json.extensions.VRM.blendShapeMaster.blendShapeGroups.map((g) => g.presetName);
    for (const p of ['a', 'i', 'u', 'e', 'o', 'blink', 'joy']) expect(presets).toContain(p);
  });
});

describe('Процедурная геометрия', () => {
  it('эллипсоид: все вершины на поверхности', () => {
    const g = superEllipsoid({ radii: [2, 1, 1], seg: 12, rings: 8 });
    for (let i = 0; i < g.pos.length; i += 3) expect((g.pos[i] / 2) ** 2 + g.pos[i + 1] ** 2 + g.pos[i + 2] ** 2).toBeCloseTo(1, 5);
    expect(g.idx.length).toBe(12 * 8 * 6);
  });
  it('капсула ориентирована от a к b', () => {
    const g = capsule([0, 0, 0], [0, 0, 1], 0.1, 0.1, 8, 4);
    const zs = g.pos.filter((_, i) => i % 3 === 2);
    expect(Math.min(...zs)).toBeCloseTo(-0.1, 5);
    expect(Math.max(...zs)).toBeCloseTo(1.1, 5);
  });
  it('линза рта плоская и с uv', () => { const l = lens({ center: [0, 0, 0], width: 1, height: 0.1 }); expect(l.uv.length / 2).toBe(l.pos.length / 3); });
  it('матрица поворота ортонормирована', () => {
    const m = rotMatrix(0.3, 1.1, -0.7);
    const v = applyMat(m, 1, 2, 3);
    expect(Math.hypot(...v)).toBeCloseTo(Math.hypot(1, 2, 3), 6);
  });
  it('нормали треугольника', () => expect([...computeNormals([0, 0, 0, 1, 0, 0, 0, 1, 0], [0, 1, 2])].slice(0, 3)).toEqual([0, 0, 1]));
});

const NICK = path.join(ROOT, 'assets/models/nick.vrm');
describe.skipIf(!fs.existsSync(NICK))('Новая модель Марка (из FBX)', () => {
  const { json } = fs.existsSync(NICK) ? parseGLB(fs.readFileSync(NICK)) : { json: { extensions: { VRMC_vrm: {} } } };
  const vrm = json.extensions.VRMC_vrm;
  it('VRM 1.0 со всеми обязательными костями', () => {
    expect(vrm.specVersion).toBe('1.0');
    for (const b of REQUIRED_VRM1) expect(vrm.humanoid.humanBones[b], b).toBeDefined();
  });
  it('один скелет (дубли объединены)', () => expect(json.nodes.filter((n) => /Shoulder_L$/.test(n.name))).toHaveLength(1));
  it('кости ссылаются на суставы скина', () => {
    const joints = new Set(json.skins.flatMap((s) => s.joints));
    for (const { node } of Object.values(vrm.humanoid.humanBones)) expect(joints.has(node)).toBe(true);
  });
  it('левая рука на +X, персонаж смотрит на +Z', async () => {
    const THREE = await import('three');
    const objs = json.nodes.map((n) => {
      const o = new THREE.Object3D();
      if (n.matrix) o.applyMatrix4(new THREE.Matrix4().fromArray(n.matrix));
      if (n.translation) o.position.fromArray(n.translation);
      if (n.rotation) o.quaternion.fromArray(n.rotation);
      if (n.scale) o.scale.fromArray(n.scale);
      return o;
    });
    json.nodes.forEach((n, i) => (n.children || []).forEach((c) => objs[i].add(objs[c])));
    objs.forEach((o) => { if (!o.parent) o.updateMatrixWorld(true); });
    const wp = (b) => new THREE.Vector3().setFromMatrixPosition(objs[vrm.humanoid.humanBones[b].node].matrixWorld);
    expect(wp('leftHand').x).toBeGreaterThan(0.2);
    expect(wp('rightHand').x).toBeLessThan(-0.2);
    expect(wp('leftToes').z).toBeGreaterThan(wp('leftFoot').z);
    expect(wp('head').y).toBeGreaterThan(wp('hips').y);
  });
  it('есть рот с гласными для липсинка', () => {
    for (const v of ['aa', 'ih', 'ou', 'ee', 'oh', 'happy']) {
      const b = vrm.expressions.preset[v].morphTargetBinds[0];
      expect(json.nodes[b.node].name).toBe('Mouth');
      expect(json.meshes[json.nodes[b.node].mesh].primitives[0].targets.length).toBeGreaterThan(b.index);
    }
  });
  it('текстуры встроены', () => { expect(json.images.length).toBeGreaterThanOrEqual(2); expect(json.textures.length).toBeGreaterThanOrEqual(2); });
});

import { describe, it, expect } from 'vitest';
import { CLIPS, CLIP_NAMES, clipPose, restPose, idleLayer, blendPoses, mergePoses, toVrm0, mirror, BONES, FINGERS } from '../src/renderer/js/avatar/poses.js';
import { ExpressionMixer, Blinker, EMOTION_PRESETS, EMOTION_KEYS, EMOTION_GESTURE } from '../src/renderer/js/avatar/expressions.js';

const VALID = new Set([...BONES, ...FINGERS, 'hipsPos']);
const finitePose = (p) => Object.entries(p).every(([k, v]) => VALID.has(k) && v.length === 3 && v.every(Number.isFinite));

describe('Клипы анимаций', () => {
  it('не меньше 18 клипов', () => expect(CLIP_NAMES.length).toBeGreaterThanOrEqual(18));
  for (const name of CLIP_NAMES) {
    it(`«${name}»: конечные числа и известные кости на всём протяжении`, () => {
      const c = CLIPS[name];
      const variants = c.variants ? c.variants.length : 1;
      for (let v = 0; v < variants; v++) for (let t = -0.1; t <= c.duration + 0.5; t += 0.037) expect(finitePose(clipPose(name, t, v))).toBe(true);
    });
    it(`«${name}»: углы в разумных пределах (|угол| ≤ 2π)`, () => {
      const c = CLIPS[name];
      for (let t = 0; t <= c.duration; t += 0.1) for (const [k, v] of Object.entries(clipPose(name, t))) if (k !== 'hipsPos') for (const a of v) expect(Math.abs(a)).toBeLessThanOrEqual(Math.PI * 2 + 1e-6);
    });
  }
  it('танец имеет 3 варианта, и они различаются', () => {
    expect(CLIPS.dance.variants).toHaveLength(3);
    const a = JSON.stringify(clipPose('dance', 1.3, 0)), b = JSON.stringify(clipPose('dance', 1.3, 1)), c = JSON.stringify(clipPose('dance', 1.3, 2));
    expect(new Set([a, b, c]).size).toBe(3);
  });
  it('танец двигает бёдра (hipsPos)', () => expect(clipPose('dance', 0.4, 0).hipsPos).toBeDefined());
  it('прыжок поднимает персонажа в воздух', () => expect(clipPose('jump', 0.6).hipsPos[1]).toBeGreaterThan(0.1));
  it('махание — правая рука поднята (z < 0 для VRM1)', () => expect(clipPose('wave', 1).rightUpperArm[2]).toBeLessThan(0.5));
  it('кивок двигает голову по X', () => expect(Math.abs(clipPose('nod', 0.15).head[0])).toBeGreaterThan(0.05));
  it('несуществующий клип → пустая поза', () => expect(clipPose('fly', 1)).toEqual({}));
  it('время за пределами клипа зажимается', () => expect(clipPose('bow', 100)).toEqual(clipPose('bow', CLIPS.bow.duration)));
});

describe('Позы и смешивание', () => {
  it('в покое руки опущены (левая z<0, правая z>0)', () => { const r = restPose(); expect(r.leftUpperArm[2]).toBeLessThan(-1); expect(r.rightUpperArm[2]).toBeGreaterThan(1); });
  it('пальцы слегка согнуты, левые и правые симметрично', () => {
    const r = restPose();
    expect(FINGERS).toHaveLength(28);
    expect(r.leftIndexProximal[2]).toBeCloseTo(-r.rightIndexProximal[2]);
  });
  it('дыхание меняется во времени', () => expect(idleLayer(0).spine).not.toEqual(idleLayer(1).spine));
  it('интенсивность 0 — почти без движения', () => expect(idleLayer(1.3, 0).spine).toEqual([0, 0, 0]));
  it('blendPoses: 0 и 1', () => {
    const a = { head: [0, 0, 0] }, b = { head: [1, 2, 3], spine: [1, 1, 1] };
    expect(blendPoses(a, b, 0).head).toEqual([0, 0, 0]);
    expect(blendPoses(a, b, 1).head).toEqual([1, 2, 3]);
    expect(blendPoses(a, b, 0.5).head).toEqual([0.5, 1, 1.5]);
    expect(blendPoses(a, b, 0.5).spine).toEqual([0.5, 0.5, 0.5]);
  });
  it('mergePoses: последний слой побеждает', () => expect(mergePoses({ a: [1, 1, 1] }, { a: [2, 2, 2] }).a).toEqual([2, 2, 2]));
  it('VRM 0.x: инвертирует X и Z', () => expect(toVrm0([1, 2, 3])).toEqual([-1, 2, -3]));
  it('зеркалирование', () => expect(mirror([1, 2, 3])).toEqual([1, -2, -3]));
});

describe('Эмоции', () => {
  it('у каждой эмоции веса в пределах 0..1', () => { for (const p of Object.values(EMOTION_PRESETS)) for (const v of Object.values(p)) { expect(v).toBeGreaterThan(0); expect(v).toBeLessThanOrEqual(1); } });
  it('плавный переход к цели', () => {
    const m = new ExpressionMixer();
    m.set('happy', 0);
    const first = m.update(0.016, 0.016).happy;
    for (let i = 0; i < 120; i++) m.update(0.016 * i, 0.016);
    expect(first).toBeLessThan(0.3);
    expect(m.update(2, 0.016).happy).toBeCloseTo(0.85, 1);
  });
  it('эмоция гаснет после времени удержания', () => {
    const m = new ExpressionMixer();
    m.set('sad', 0, 2);
    for (let t = 0; t < 6; t += 0.05) m.update(t, 0.05);
    expect(m.emotion).toBe('neutral');
    expect(m.current.sad).toBeLessThan(0.05);
  });
  it('во время речи эмоция ослабляется', () => {
    const m = new ExpressionMixer(); m.set('happy', 0);
    for (let i = 0; i < 100; i++) m.update(i * 0.016, 0.016);
    expect(m.update(2, 0.001, 1).happy).toBeLessThan(m.update(2, 0.001, 0).happy);
  });
  it('неизвестная эмоция отклоняется', () => expect(new ExpressionMixer().set('rage', 0)).toBe(false));
  it('у каждой эмоции определён жест (или null)', () => { for (const k of Object.keys(EMOTION_PRESETS)) expect(EMOTION_GESTURE).toHaveProperty(k); });
  it('ключи выражений', () => expect(EMOTION_KEYS).toEqual(['happy', 'sad', 'angry', 'surprised', 'relaxed']));
});

describe('Моргание', () => {
  it('моргает периодически и коротко', () => {
    let seed = 1; const rand = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    const b = new Blinker(rand);
    let blinks = 0, closedFrames = 0, prev = 0;
    for (let t = 0; t < 30; t += 0.016) { const v = b.update(t); if (v > 0.5) closedFrames++; if (prev === 0 && v > 0) blinks++; prev = v; }
    expect(blinks).toBeGreaterThanOrEqual(4);
    expect(blinks).toBeLessThanOrEqual(20);
    expect(closedFrames / (30 / 0.016)).toBeLessThan(0.1);
  });
  it('можно отключить', () => { const b = new Blinker(() => 0); expect(b.update(100, true)).toBe(0); });
});

describe('Посадка и передвижение', async () => {
  const { sitPose, SIT_SAFE } = await import('../src/renderer/js/avatar/poses.js');
  it('сидячая поза: бёдра вперёд, колени согнуты', () => {
    const p = sitPose(0);
    expect(p.leftUpperLeg[0]).toBeLessThan(-1.2);
    expect(p.leftLowerLeg[0]).toBeGreaterThan(1.2);
    for (let t = 0; t < 5; t += 0.3) expect(finitePose(sitPose(t))).toBe(true);
  });
  it('ноги болтаются в противофазе', () => { const p = sitPose(0.7); expect(Math.sign(p.leftLowerLeg[0] - 1.45)).toBe(-Math.sign(p.rightLowerLeg[0] - 1.45)); });
  it('сидя танец и прыжок заменяются', () => {
    expect(SIT_SAFE.dance).toBe('laugh');
    expect(SIT_SAFE.jump).toBe('victory');
    for (const v of Object.values(SIT_SAFE)) if (v) expect(CLIPS).toHaveProperty(v);
  });
  it('ходьба и бег зациклены и различаются по темпу', () => {
    expect(CLIPS.walk.loop).toBe(true);
    expect(CLIPS.run.loop).toBe(true);
    expect(Math.abs(clipPose('run', 0.1).leftUpperLeg[0])).toBeGreaterThan(Math.abs(clipPose('walk', 0.1).leftUpperLeg[0]));
  });
});

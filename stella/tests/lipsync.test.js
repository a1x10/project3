import { describe, it, expect } from 'vitest';
import { bandEnergy, visemesFromSpectrum, LipSmoother, textToVisemeTimeline, visemeAt, VISEMES } from '../src/renderer/js/core/lipsync.js';

const SR = 44100, FFT = 1024, BIN = SR / FFT;
function spectrum(bands) { // bands: [[loHz, hiHz, value]]
  const f = new Uint8Array(FFT / 2);
  for (const [lo, hi, v] of bands) for (let i = Math.floor(lo / BIN); i <= Math.ceil(hi / BIN) && i < f.length; i++) f[i] = v;
  return f;
}

describe('bandEnergy', () => {
  it('0 для тишины', () => expect(bandEnergy(new Uint8Array(512), SR, FFT, 200, 500)).toBe(0));
  it('1 для максимума', () => expect(bandEnergy(new Uint8Array(512).fill(255), SR, FFT, 200, 500)).toBe(1));
  it('пустой диапазон', () => expect(bandEnergy(new Uint8Array(512), SR, FFT, 500, 100)).toBe(0));
});

describe('visemesFromSpectrum', () => {
  it('тишина — рот закрыт', () => { const v = visemesFromSpectrum(new Uint8Array(512), SR, FFT); for (const k of VISEMES) expect(v[k]).toBe(0); });
  it('громкий звук открывает рот', () => {
    const v = visemesFromSpectrum(spectrum([[200, 1100, 220]]), SR, FFT);
    expect(v.aa + v.oh).toBeGreaterThan(0.2);
    expect(v.volume).toBeGreaterThan(0.1);
  });
  it('высокие частоты → «и/э»', () => {
    const v = visemesFromSpectrum(spectrum([[200, 500, 60], [1100, 5000, 230]]), SR, FFT);
    expect(v.ee + v.ih).toBeGreaterThan(v.ou + v.oh);
  });
  it('низкие частоты → «о/у»', () => {
    const v = visemesFromSpectrum(spectrum([[200, 500, 250], [500, 700, 40]]), SR, FFT);
    expect(v.oh + v.ou).toBeGreaterThan(v.ee + v.ih);
  });
  it('сумма не больше 1 и значения в 0..1', () => {
    for (let k = 0; k < 20; k++) {
      const f = new Uint8Array(512).map(() => Math.floor(Math.random() * 256));
      const v = visemesFromSpectrum(f, SR, FFT);
      const sum = VISEMES.reduce((s, x) => s + v[x], 0);
      expect(sum).toBeLessThanOrEqual(1.0001);
      for (const x of VISEMES) { expect(v[x]).toBeGreaterThanOrEqual(0); expect(v[x]).toBeLessThanOrEqual(1); }
    }
  });
});

describe('LipSmoother', () => {
  it('открывает быстрее, чем закрывает', () => {
    const a = new LipSmoother(); a.update({ aa: 1 }, 0.05); const opened = a.v.aa;
    const b = new LipSmoother(); b.v.aa = 1; b.update(null, 0.05); const closed = 1 - b.v.aa;
    expect(opened).toBeGreaterThan(closed);
  });
  it('сходится к цели', () => { const s = new LipSmoother(); for (let i = 0; i < 60; i++) s.update({ oh: 0.7 }, 0.016); expect(s.v.oh).toBeCloseTo(0.7, 2); });
  it('reset', () => { const s = new LipSmoother(); s.update({ aa: 1 }, 1); s.reset(); expect(s.v.aa).toBe(0); });
});

describe('Таймлайн по тексту', () => {
  it('гласные русского языка', () => {
    const t = textToVisemeTimeline('мама');
    expect(t.filter((e) => e.v).map((e) => e.v)).toEqual(['aa', 'aa']);
  });
  it('все русские гласные', () => {
    const vs = textToVisemeTimeline('аоуэиыеёюя').filter((e) => e.v).map((e) => e.v);
    expect(vs).toEqual(['aa', 'oh', 'ou', 'ee', 'ih', 'ih', 'ee', 'oh', 'ou', 'aa']);
  });
  it('в конце рот закрывается', () => expect(textToVisemeTimeline('да').at(-1).v).toBeNull());
  it('паузы на знаках препинания', () => {
    const a = textToVisemeTimeline('да да').at(-1).t;
    const b = textToVisemeTimeline('да. да').at(-1).t;
    expect(b).toBeGreaterThan(a);
  });
  it('visemeAt', () => {
    const t = [{ t: 0, v: 'aa' }, { t: 0.1, v: null }, { t: 0.2, v: 'oh' }];
    expect(visemeAt(t, 0.05)).toBe('aa');
    expect(visemeAt(t, 0.15)).toBeNull();
    expect(visemeAt(t, 1)).toBe('oh');
    expect(visemeAt(t, -1)).toBeNull();
  });
});

import { describe, it, expect } from 'vitest';
import { VAD, rmsOf, sensitivityToThreshold } from '../src/renderer/js/core/vad.js';
import { encodeWav, downsample, RingBuffer } from '../src/renderer/js/core/wav.js';

describe('VAD — детектор речи', () => {
  const run = (vad, seq, dt = 0.1) => seq.map((r, i) => vad.process(r, i * dt)).filter(Boolean);
  it('тишина — нет событий', () => expect(run(new VAD(), Array(30).fill(0.001))).toEqual([]));
  it('фраза: start, затем end после паузы', () => expect(run(new VAD(), [0, 0.2, 0.2, 0.2, 0.2, 0.2, ...Array(12).fill(0)])).toEqual(['start', 'end']));
  it('щелчок короче minSpeech — discard', () => expect(run(new VAD({ minSpeech: 0.5 }), [0, 0.3, ...Array(12).fill(0)])).toEqual(['start', 'discard']));
  it('короткие паузы внутри фразы не обрывают её', () => {
    expect(run(new VAD({ silence: 0.9 }), [0.2, 0.2, 0, 0, 0.2, 0.2, 0, 0, 0.2, ...Array(15).fill(0)])).toEqual(['start', 'end']);
  });
  it('слишком длинная фраза принудительно завершается', () => expect(run(new VAD({ maxSpeech: 2 }), Array(40).fill(0.3))).toContain('end'));
  it('адаптируется к шуму', () => {
    const v = new VAD({ threshold: 0.02 });
    for (let i = 0; i < 300; i++) v.process(0.015, i * 0.05);
    expect(v.process(0.03, 100)).toBeNull(); // 0.03 < 3×шум
  });
  it('reset', () => { const v = new VAD(); v.process(1, 0); v.reset(); expect(v.state).toBe('idle'); });
  it('rmsOf', () => { expect(rmsOf(new Float32Array([1, -1, 1, -1]))).toBe(1); expect(rmsOf(new Float32Array([]))).toBe(0); });
  it('чувствительность → порог (выше чувствительность — ниже порог)', () => {
    expect(sensitivityToThreshold(1)).toBeLessThan(sensitivityToThreshold(0));
    expect(sensitivityToThreshold(5)).toBe(sensitivityToThreshold(1));
    expect(sensitivityToThreshold('x')).toBe(sensitivityToThreshold(0));
  });
});

describe('WAV', () => {
  it('заголовок RIFF/WAVE 16 кГц mono 16-bit', () => {
    const w = encodeWav(new Float32Array(100), 16000);
    const dv = new DataView(w.buffer);
    expect(String.fromCharCode(...w.slice(0, 4))).toBe('RIFF');
    expect(String.fromCharCode(...w.slice(8, 12))).toBe('WAVE');
    expect(dv.getUint16(22, true)).toBe(1);
    expect(dv.getUint32(24, true)).toBe(16000);
    expect(dv.getUint16(34, true)).toBe(16);
    expect(dv.getUint32(40, true)).toBe(200);
    expect(w.length).toBe(244);
  });
  it('клиппинг значений', () => {
    const w = encodeWav(new Float32Array([2, -2, 0.5]));
    const dv = new DataView(w.buffer);
    expect(dv.getInt16(44, true)).toBe(32767);
    expect(dv.getInt16(46, true)).toBe(-32768);
    expect(dv.getInt16(48, true)).toBe(16383);
  });
  it('даунсемплинг 48к → 16к', () => {
    const d = downsample(new Float32Array(48000).fill(0.5), 48000, 16000);
    expect(d.length).toBe(16000);
    expect(d[100]).toBeCloseTo(0.5);
  });
  it('без апсемплинга', () => expect(downsample(new Float32Array(10), 16000, 44100).length).toBe(10));
  it('кольцевой буфер хранит последние N сэмплов по порядку', () => {
    const r = new RingBuffer(4);
    r.push(new Float32Array([1, 2, 3]));
    expect([...r.read()]).toEqual([1, 2, 3]);
    r.push(new Float32Array([4, 5, 6]));
    expect([...r.read()]).toEqual([3, 4, 5, 6]);
    r.clear();
    expect(r.read().length).toBe(0);
  });
});

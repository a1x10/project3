// Липсинк: из спектра звука → веса гласных VRM (aa, ih, ou, ee, oh).
export const VISEMES = ['aa', 'ih', 'ou', 'ee', 'oh'];

/** Средняя энергия в полосе частот [lo, hi] Гц, 0..1. */
export function bandEnergy(freq, sampleRate, fftSize, lo, hi) {
  const binHz = sampleRate / fftSize;
  const a = Math.max(0, Math.floor(lo / binHz)), b = Math.min(freq.length - 1, Math.ceil(hi / binHz));
  if (b < a) return 0;
  let sum = 0;
  for (let i = a; i <= b; i++) sum += freq[i];
  return sum / ((b - a + 1) * 255);
}

/**
 * Оценивает форму рта по спектру (Uint8Array из AnalyserNode.getByteFrequencyData).
 * Грубая эвристика по формантам: F1 (открытость рта) и F2 (передний/задний ряд).
 */
export function visemesFromSpectrum(freq, sampleRate = 44100, fftSize = 1024) {
  const low = bandEnergy(freq, sampleRate, fftSize, 200, 500);
  const mid = bandEnergy(freq, sampleRate, fftSize, 500, 1100);
  const high = bandEnergy(freq, sampleRate, fftSize, 1100, 2600);
  const vhigh = bandEnergy(freq, sampleRate, fftSize, 2600, 5000);
  const vol = Math.min(1, (low + mid + high) * 1.6);
  const out = { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0, volume: vol };
  if (vol < 0.06) return out;
  const total = low + mid + high + vhigh + 1e-6;
  const pl = low / total, pm = mid / total, ph = high / total, pv = vhigh / total;
  out.aa = clamp01((pm * 1.6 + pl * 0.4) * vol * 2.2);
  out.oh = clamp01((pl * 1.4 - ph * 0.3) * vol * 1.6);
  out.ou = clamp01((pl * 1.2 - pm * 0.6) * vol * 1.2);
  out.ee = clamp01((ph * 1.5 - pl * 0.4) * vol * 1.8);
  out.ih = clamp01((pv * 1.8 + ph * 0.4) * vol * 1.5);
  // нормируем, чтобы суммарное открытие рта не превышало 1
  const sum = out.aa + out.oh + out.ou + out.ee + out.ih;
  if (sum > 1) for (const k of VISEMES) out[k] /= sum;
  return out;
}

/** Сглаживание с разной скоростью открытия/закрытия рта. */
export class LipSmoother {
  constructor({ attack = 18, release = 10 } = {}) { this.attack = attack; this.release = release; this.v = { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 }; }
  update(target, dt) {
    for (const k of VISEMES) {
      const t = target?.[k] || 0, c = this.v[k];
      const rate = t > c ? this.attack : this.release;
      this.v[k] = c + (t - c) * (1 - Math.exp(-rate * dt));
      if (this.v[k] < 0.001) this.v[k] = 0;
    }
    return this.v;
  }
  reset() { for (const k of VISEMES) this.v[k] = 0; }
}

const VOWEL_MAP = {
  а: 'aa', я: 'aa', a: 'aa', о: 'oh', ё: 'oh', o: 'oh', у: 'ou', ю: 'ou', u: 'ou', w: 'ou',
  э: 'ee', е: 'ee', e: 'ee', и: 'ih', ы: 'ih', i: 'ih', y: 'ih',
};

/**
 * Таймлайн гласных по тексту — для системного голоса, когда звук нельзя проанализировать.
 * @returns {{t:number, v:string|null}[]} время начала (с) и виcема (null — рот закрыт)
 */
export function textToVisemeTimeline(text, charsPerSecond = 14) {
  const out = [];
  const step = 1 / charsPerSecond;
  let t = 0;
  for (const ch of String(text || '').toLowerCase()) {
    if (/[.!?…]/.test(ch)) { out.push({ t, v: null }); t += step * 4; continue; }
    if (/[,;:—-]/.test(ch)) { out.push({ t, v: null }); t += step * 2; continue; }
    if (/\s/.test(ch)) { t += step * 0.5; continue; }
    const v = VOWEL_MAP[ch];
    if (v) out.push({ t, v });
    else if (/[\p{L}]/u.test(ch)) out.push({ t, v: null });
    t += step;
  }
  out.push({ t, v: null });
  return out;
}

/** Виcема в момент времени по таймлайну. */
export function visemeAt(timeline, time) {
  let cur = null;
  for (const e of timeline) { if (e.t > time) break; cur = e.v; }
  return cur;
}

function clamp01(x) { return x < 0 ? 0 : x > 1 ? 1 : x; }

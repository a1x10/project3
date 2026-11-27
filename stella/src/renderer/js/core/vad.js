// Детектор речи по громкости (Voice Activity Detection) — конечный автомат.
export class VAD {
  /**
   * @param {object} o
   * @param {number} o.threshold порог RMS начала речи
   * @param {number} o.minSpeech минимальная длительность речи, с
   * @param {number} o.silence пауза, после которой фраза считается законченной, с
   * @param {number} o.maxSpeech максимальная длительность фразы, с
   */
  constructor({ threshold = 0.04, minSpeech = 0.3, silence = 0.9, maxSpeech = 15 } = {}) {
    Object.assign(this, { threshold, minSpeech, silence, maxSpeech });
    this.state = 'idle';
    this.speechStart = 0; this.lastVoice = 0; this.noise = threshold / 3;
  }
  /** @returns {'start'|'end'|'discard'|null} */
  process(rms, t) {
    const thr = Math.max(this.threshold, this.noise * 3);
    const voiced = rms > thr;
    if (this.state === 'idle') {
      if (!voiced) { this.noise = this.noise * 0.98 + rms * 0.02; return null; }
      this.state = 'speaking'; this.speechStart = t; this.lastVoice = t;
      return 'start';
    }
    if (voiced) this.lastVoice = t;
    const dur = t - this.speechStart;
    if (t - this.lastVoice > this.silence || dur > this.maxSpeech) {
      this.state = 'idle';
      return this.lastVoice - this.speechStart >= this.minSpeech ? 'end' : 'discard';
    }
    return null;
  }
  reset() { this.state = 'idle'; }
}

export function rmsOf(samples) {
  let s = 0;
  for (let i = 0; i < samples.length; i++) s += samples[i] * samples[i];
  return Math.sqrt(s / (samples.length || 1));
}

/** Чувствительность 0..1 → порог RMS. */
export function sensitivityToThreshold(s) {
  const v = Math.min(1, Math.max(0, Number(s) || 0));
  return 0.09 - v * 0.075; // 0.09 (глухо) … 0.015 (очень чутко)
}

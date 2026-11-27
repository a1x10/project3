// Эмоции → веса выражений VRM, плавные переходы.
export const EMOTION_PRESETS = {
  neutral: {},
  happy: { happy: 0.85 },
  sad: { sad: 0.8 },
  angry: { angry: 0.75 },
  surprised: { surprised: 0.85 },
  relaxed: { relaxed: 0.75 },
  love: { happy: 0.7, relaxed: 0.25 },
  thinking: { relaxed: 0.25 },
  shy: { happy: 0.35, relaxed: 0.35 },
  smug: { relaxed: 0.55, happy: 0.2 },
};
export const EMOTION_KEYS = ['happy', 'sad', 'angry', 'surprised', 'relaxed'];

/** Какая анимация тела подходит к эмоции (если действия нет). */
export const EMOTION_GESTURE = { happy: null, sad: 'shy', angry: 'shake', surprised: 'surprised', love: 'heart', thinking: 'think', shy: 'shy', smug: 'shrug', relaxed: null, neutral: null };

export class ExpressionMixer {
  constructor() { this.current = Object.fromEntries(EMOTION_KEYS.map((k) => [k, 0])); this.target = { ...this.current }; this.emotion = 'neutral'; this.until = 0; }
  set(emotion, now, holdSeconds = 7) {
    const p = EMOTION_PRESETS[emotion];
    if (!p) return false;
    this.emotion = emotion;
    for (const k of EMOTION_KEYS) this.target[k] = p[k] || 0;
    this.until = emotion === 'neutral' ? 0 : now + holdSeconds;
    return true;
  }
  /** @param {number} speaking 0..1 — насколько открыт рот (ослабляем эмоцию рта) */
  update(now, dt, speaking = 0) {
    if (this.until && now > this.until) this.set('neutral', now);
    const k = 1 - Math.exp(-6 * dt);
    for (const e of EMOTION_KEYS) this.current[e] += (this.target[e] - this.current[e]) * k;
    const damp = 1 - Math.min(0.45, speaking * 0.6);
    const out = {};
    for (const e of EMOTION_KEYS) out[e] = this.current[e] * damp;
    return out;
  }
}

/** Планировщик моргания: возвращает вес blink 0..1. */
export class Blinker {
  constructor(rand = Math.random) { this.rand = rand; this.next = 1 + rand() * 3; this.t = -1; }
  update(now, disabled = false) {
    if (disabled) return 0;
    if (this.t < 0 && now >= this.next) this.t = now;
    if (this.t >= 0) {
      const p = (now - this.t) / 0.16;
      if (p >= 1) {
        this.t = -1;
        // иногда двойное моргание
        this.next = now + (this.rand() < 0.15 ? 0.18 : 1.8 + this.rand() * 4.2);
        return 0;
      }
      return Math.sin(p * Math.PI);
    }
    return 0;
  }
}

// Озвучка ответов: ElevenLabs (с анализом звука для липсинка) или системный голос.
import { visemesFromSpectrum, textToVisemeTimeline, visemeAt } from '../core/lipsync.js';
import { isSpeakable } from '../core/tags.js';

export class Speaker {
  constructor({ avatar, getSettings, onState, onSubtitle, onError }) {
    Object.assign(this, { avatar, getSettings, onState, onSubtitle, onError });
    this.queue = [];
    this.playing = false;
    this.ctx = null;
    this.gen = 0;
    this.current = null;
    this.elevenFailed = false;
  }

  _ctx() {
    if (!this.ctx) {
      this.ctx = new AudioContext();
      this.analyser = this.ctx.createAnalyser();
      this.analyser.fftSize = 1024;
      this.analyser.smoothingTimeConstant = 0.5;
      this.gain = this.ctx.createGain();
      this.analyser.connect(this.gain).connect(this.ctx.destination);
      this.freq = new Uint8Array(this.analyser.frequencyBinCount);
    }
    if (this.ctx.state === 'suspended') this.ctx.resume();
    return this.ctx;
  }

  get busy() { return this.playing || this.queue.length > 0; }

  /** Добавить фразу в очередь озвучки. */
  enqueue(text) {
    const s = this.getSettings();
    if (!isSpeakable(text)) return;
    const item = { text, audio: null };
    if (s.ttsEnabled && s.hasElevenlabsKey && !this.elevenFailed) item.audio = this._fetch(text);
    this.queue.push(item);
    if (!this.playing) this._next();
  }

  async _fetch(text) {
    try {
      const b64 = await window.stella.invoke('tts:speak', text);
      if (!b64) return null;
      const bin = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
      return await this._ctx().decodeAudioData(bin.buffer);
    } catch (e) {
      if (/401|402|ключ/i.test(e.message)) this.elevenFailed = true;
      this.onError?.(e.message);
      return null;
    }
  }

  async _next() {
    const item = this.queue.shift();
    if (!item) { this.playing = false; this.avatar?.setMouth(null); this.onSubtitle?.(''); this.onState?.(false); return; }
    this.playing = true;
    this.onState?.(true);
    const gen = this.gen;
    this.onSubtitle?.(item.text);
    const s = this.getSettings();
    const buffer = item.audio ? await item.audio : null;
    if (gen !== this.gen) return;
    if (buffer) await this._playBuffer(buffer, s.volume, gen);
    else if (s.ttsEnabled && s.systemVoiceFallback) await this._speakSystem(item.text, s, gen);
    else await this._fakeTalk(item.text, gen);
    if (gen !== this.gen) return;
    this._next();
  }

  _playBuffer(buffer, volume, gen) {
    return new Promise((resolve) => {
      const ctx = this._ctx();
      this.gain.gain.value = volume ?? 0.9;
      const src = ctx.createBufferSource();
      src.buffer = buffer;
      src.connect(this.analyser);
      this.current = src;
      let raf;
      const loop = () => {
        if (gen !== this.gen) return;
        this.analyser.getByteFrequencyData(this.freq);
        this.avatar?.setMouth(visemesFromSpectrum(this.freq, ctx.sampleRate, this.analyser.fftSize));
        raf = requestAnimationFrame(loop);
      };
      src.onended = () => { cancelAnimationFrame(raf); this.avatar?.setMouth(null); this.current = null; resolve(); };
      src.start();
      loop();
    });
  }

  _speakSystem(text, s, gen) {
    return new Promise((resolve) => {
      if (!('speechSynthesis' in window)) { this._fakeTalk(text, gen).then(resolve); return; }
      const u = new SpeechSynthesisUtterance(text);
      u.lang = 'ru-RU';
      u.volume = s.volume ?? 0.9;
      u.rate = s.voiceSpeed || 1;
      const voices = speechSynthesis.getVoices().filter((v) => v.lang?.startsWith('ru'));
      const female = /irina|svetlana|milena|алёна|female|ekaterina|elena|dariya/i;
      const male = /pavel|dmitri|yuri|male|maxim/i;
      const wantMale = this.getSettings().persona === 'mark';
      u.voice = voices.find((v) => (wantMale ? male : female).test(v.name)) || voices[0] || null;
      if (wantMale && !male.test(u.voice?.name || '')) u.pitch = 0.8; else u.pitch = wantMale ? 1 : 1.15;
      const timeline = textToVisemeTimeline(text, 13 * (u.rate || 1));
      const t0 = performance.now();
      let raf;
      const loop = () => {
        if (gen !== this.gen) return;
        const v = visemeAt(timeline, (performance.now() - t0) / 1000);
        this.avatar?.setMouth(v ? { [v]: 0.75 } : null);
        raf = requestAnimationFrame(loop);
      };
      const done = () => { cancelAnimationFrame(raf); this.avatar?.setMouth(null); resolve(); };
      u.onend = done; u.onerror = done;
      speechSynthesis.speak(u);
      loop();
      // страховка, если onend не придёт
      setTimeout(done, Math.max(3000, timeline[timeline.length - 1].t * 1000 * 1.8 + 2000));
    });
  }

  /** Без голоса: просто двигаем губами пока «читается» субтитр. */
  _fakeTalk(text, gen) {
    return new Promise((resolve) => {
      const timeline = textToVisemeTimeline(text, 16);
      const total = timeline[timeline.length - 1].t + 0.6;
      const t0 = performance.now();
      const loop = () => {
        if (gen !== this.gen) return resolve();
        const t = (performance.now() - t0) / 1000;
        const v = visemeAt(timeline, t);
        this.avatar?.setMouth(v ? { [v]: 0.6 } : null);
        if (t < total) requestAnimationFrame(loop); else { this.avatar?.setMouth(null); resolve(); }
      };
      loop();
    });
  }

  stop() {
    this.gen++;
    this.queue = [];
    try { this.current?.stop(); } catch { /* */ }
    if ('speechSynthesis' in window) speechSynthesis.cancel();
    this.playing = false;
    this.avatar?.setMouth(null);
    this.onSubtitle?.('');
    this.onState?.(false);
  }
}

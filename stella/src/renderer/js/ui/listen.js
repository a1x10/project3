// Микрофон: «нажми и говори» + постоянное прослушивание с обращением по имени.
import { VAD, rmsOf, sensitivityToThreshold } from '../core/vad.js';
import { downsample, encodeWav, RingBuffer, bytesToBase64 } from '../core/wav.js';
import { detectWakeWord } from '../core/wakeword.js';

const TARGET_RATE = 16000;

export class Listener {
  constructor({ getSettings, getNames, onCommand, onWake, onState, onError, isBusy }) {
    Object.assign(this, { getSettings, getNames, onCommand, onWake, onState, onError, isBusy });
    this.mode = 'off'; // off | ptt | wake
    this.awaitingCommandUntil = 0;
  }

  async _open() {
    if (this.stream) return;
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    this.ctx = new AudioContext();
    this.src = this.ctx.createMediaStreamSource(this.stream);
    this.proc = this.ctx.createScriptProcessor(4096, 1, 1);
    this.ring = new RingBuffer(Math.round(this.ctx.sampleRate * 0.6));
    this.rec = null;
    this.vad = new VAD({ threshold: sensitivityToThreshold(this.getSettings().micSensitivity) });
    this.proc.onaudioprocess = (e) => this._onAudio(e.inputBuffer.getChannelData(0));
    this.src.connect(this.proc);
    this.proc.connect(this.ctx.destination);
  }

  _close() {
    try { this.proc?.disconnect(); this.src?.disconnect(); } catch { /* */ }
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close();
    this.stream = null; this.ctx = null; this.rec = null;
  }

  _onAudio(data) {
    const chunk = Float32Array.from(data);
    if (this.mode === 'ptt') { this.rec?.push(chunk); return; }
    if (this.mode !== 'wake') return;
    if (this.isBusy?.()) { this.vad.reset(); this.rec = null; this.ring.push(chunk); return; }
    const ev = this.vad.process(rmsOf(chunk), this.ctx.currentTime);
    if (ev === 'start') { this.rec = [this.ring.read()]; this.onState?.('hearing'); }
    if (this.rec) this.rec.push(chunk); else this.ring.push(chunk);
    if (ev === 'end') { const parts = this.rec; this.rec = null; this.ring.clear(); this.onState?.('wake'); this._recognize(parts, true); }
    if (ev === 'discard') { this.rec = null; this.onState?.('wake'); }
  }

  async _recognize(parts, fromWake) {
    const total = parts.reduce((n, p) => n + p.length, 0);
    if (total < this.ctx.sampleRate * 0.25) return;
    const pcm = new Float32Array(total);
    let o = 0; for (const p of parts) { pcm.set(p, o); o += p.length; }
    const wav = encodeWav(downsample(pcm, this.ctx.sampleRate, TARGET_RATE), TARGET_RATE);
    let text = '';
    try {
      this.onState?.('recognizing');
      text = await window.stella.invoke('stt:transcribe', { base64: bytesToBase64(wav), mime: 'audio/wav' });
    } catch (e) { this.onError?.(e.message); this.onState?.(this.mode === 'wake' ? 'wake' : 'off'); return; }
    this.onState?.(this.mode === 'wake' ? 'wake' : 'off');
    if (!text) return;
    if (!fromWake) { this.onCommand?.(text); return; }
    const now = performance.now();
    if (now < this.awaitingCommandUntil) { this.awaitingCommandUntil = 0; this.onCommand?.(text); return; }
    const w = detectWakeWord(text, this.getNames());
    if (!w.matched) return;
    if (w.onlyName) { this.awaitingCommandUntil = now + 9000; this.onWake?.(); return; }
    this.onCommand?.(w.command, text);
  }

  // --- нажми и говори ---
  async startPtt() {
    try {
      await this._open();
      this.prevMode = this.mode;
      this.mode = 'ptt';
      this.rec = [this.ring.read()];
      this.onState?.('ptt');
    } catch (e) { this.onError?.('Нет доступа к микрофону: ' + e.message); }
  }
  async stopPtt() {
    if (this.mode !== 'ptt') return;
    const parts = this.rec || [];
    this.rec = null;
    this.mode = this.prevMode === 'wake' ? 'wake' : 'off';
    await this._recognize(parts, false);
    if (this.mode === 'off') this._close();
  }

  // --- обращение по имени ---
  async setWake(on) {
    if (on) {
      try { await this._open(); this.mode = 'wake'; this.onState?.('wake'); }
      catch (e) { this.onError?.('Нет доступа к микрофону: ' + e.message); this.mode = 'off'; }
    } else { this.mode = 'off'; this._close(); this.onState?.('off'); }
  }
  updateSensitivity() { if (this.vad) this.vad.threshold = sensitivityToThreshold(this.getSettings().micSensitivity); }
}

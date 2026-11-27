// Кодирование PCM (Float32) в WAV 16-bit mono и даунсемплинг.
export function downsample(input, fromRate, toRate) {
  if (toRate >= fromRate) return Float32Array.from(input);
  const ratio = fromRate / toRate;
  const len = Math.floor(input.length / ratio);
  const out = new Float32Array(len);
  for (let i = 0; i < len; i++) {
    const start = Math.floor(i * ratio), end = Math.min(input.length, Math.floor((i + 1) * ratio));
    let s = 0;
    for (let j = start; j < end; j++) s += input[j];
    out[i] = s / Math.max(1, end - start);
  }
  return out;
}

export function encodeWav(samples, sampleRate = 16000) {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  str(0, 'RIFF'); v.setUint32(4, 36 + samples.length * 2, true); str(8, 'WAVE');
  str(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, sampleRate, true); v.setUint32(28, sampleRate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  str(36, 'data'); v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Uint8Array(buf);
}

/** Кольцевой буфер PCM для «предзаписи» начала фразы. */
export class RingBuffer {
  constructor(size) { this.buf = new Float32Array(size); this.pos = 0; this.full = false; }
  push(chunk) {
    for (let i = 0; i < chunk.length; i++) { this.buf[this.pos] = chunk[i]; this.pos = (this.pos + 1) % this.buf.length; if (this.pos === 0) this.full = true; }
  }
  read() {
    if (!this.full) return this.buf.slice(0, this.pos);
    const out = new Float32Array(this.buf.length);
    out.set(this.buf.subarray(this.pos)); out.set(this.buf.subarray(0, this.pos), this.buf.length - this.pos);
    return out;
  }
  clear() { this.pos = 0; this.full = false; }
}

export function bytesToBase64(bytes) {
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

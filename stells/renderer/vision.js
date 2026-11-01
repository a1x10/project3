// Встроенное машинное зрение (работает сразу, без Python и без интернета):
// детектор движения, трекинг объекта по цвету, яркость/освещённость, FPS.
// Источники: веб-камера компьютера, поток с платы (MJPEG), поток Python-модуля.
// Модели ONNX подключаются через Python-модуль STELLS Vision или на плате.

export class Vision extends EventTarget {
  constructor() {
    super();
    this.video = document.createElement('video');
    this.video.muted = true; this.video.playsInline = true;
    this.img = null;
    this.work = document.createElement('canvas');
    this.work.width = 160; this.work.height = 120;
    this.wctx = this.work.getContext('2d', { willReadFrequently: true });
    this.prev = null;
    this.running = false;
    this.source = null;
    this.opts = { motion: true, color: false, sensitivity: 28, minArea: 6 };
    this.trackColor = null; // [r,g,b]
    this.detections = [];
    this.target = null;     // {x,y} нормализованные 0..1 — центр отслеживаемого объекта
    this.fps = 0;
    this.light = 0;
    this.motionLevel = 0;
    this.views = new Set();
    this.stream = null;
  }

  async startWebcam(deviceId) {
    this.stop();
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ video: deviceId ? { deviceId: { exact: deviceId } } : { width: 1280, height: 720 }, audio: false });
    } catch (e) {
      return { ok: false, reason: 'Камера недоступна: ' + e.message };
    }
    this.video.srcObject = this.stream;
    await this.video.play();
    this.source = { kind: 'webcam', label: this.stream.getVideoTracks()[0]?.label || 'Веб-камера' };
    this._run();
    this.dispatchEvent(new Event('started'));
    return { ok: true };
  }

  startStream(url, label = 'Поток') {
    this.stop();
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.src = url;
    this.img = img;
    this.source = { kind: 'stream', url, label };
    this._run();
    this.dispatchEvent(new Event('started'));
    return { ok: true };
  }

  stop() {
    this.running = false;
    if (this.stream) { this.stream.getTracks().forEach((t) => t.stop()); this.stream = null; }
    if (this.img) { this.img.src = ''; this.img = null; }
    this.source = null; this.prev = null; this.detections = []; this.target = null;
    this.dispatchEvent(new Event('stopped'));
  }

  frameSource() {
    if (this.img) return this.img.naturalWidth ? this.img : null;
    return this.video.readyState >= 2 ? this.video : null;
  }

  static async cameras() {
    try { return (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'videoinput'); } catch { return []; }
  }

  // Подключить <canvas> для отображения кадра + разметки.
  attach(canvas) { this.views.add(canvas); return () => this.views.delete(canvas); }

  pickColorAt(nx, ny) {
    const x = Math.floor(nx * 160), y = Math.floor(ny * 120);
    const d = this.wctx.getImageData(Math.max(0, x - 2), Math.max(0, y - 2), 5, 5).data;
    let r = 0, g = 0, b = 0;
    for (let i = 0; i < d.length; i += 4) { r += d[i]; g += d[i + 1]; b += d[i + 2]; }
    const n = d.length / 4;
    this.trackColor = [r / n, g / n, b / n];
    this.opts.color = true;
  }

  _run() {
    this.running = true;
    let last = performance.now(), frames = 0, acc = 0;
    const tick = () => {
      if (!this.running) return;
      requestAnimationFrame(tick);
      const src = this.frameSource();
      if (!src) return;
      const now = performance.now();
      frames++; acc += now - last; last = now;
      if (acc >= 1000) { this.fps = Math.round(frames * 1000 / acc); frames = 0; acc = 0; }
      try { this._analyze(src); } catch { /* поток без CORS: только отображение */ this.detections = []; }
      this._draw(src);
      this.dispatchEvent(new CustomEvent('frame', { detail: { detections: this.detections, target: this.target, fps: this.fps } }));
    };
    tick();
  }

  _analyze(src) {
    const W = 160, H = 120;
    this.wctx.drawImage(src, 0, 0, W, H);
    const data = this.wctx.getImageData(0, 0, W, H).data;
    const gray = new Uint8ClampedArray(W * H);
    let sum = 0;
    for (let i = 0, j = 0; i < data.length; i += 4, j++) { gray[j] = (data[i] * 77 + data[i + 1] * 150 + data[i + 2] * 29) >> 8; sum += gray[j]; }
    this.light = Math.round(sum / (W * H) / 2.55);
    const dets = [];

    if (this.opts.motion && this.prev) {
      // карта движения по ячейкам 8x8, затем объединение соседних ячеек в объекты
      const C = 8, GW = W / C, GH = H / C, cells = new Uint8Array(GW * GH);
      let moving = 0;
      for (let gy = 0; gy < GH; gy++) for (let gx = 0; gx < GW; gx++) {
        let cnt = 0;
        for (let y = 0; y < C; y++) for (let x = 0; x < C; x++) {
          const k = (gy * C + y) * W + gx * C + x;
          if (Math.abs(gray[k] - this.prev[k]) > this.opts.sensitivity) cnt++;
        }
        if (cnt > 10) { cells[gy * GW + gx] = 1; moving++; }
      }
      this.motionLevel = Math.round(moving / (GW * GH) * 100);
      const seen = new Uint8Array(cells.length);
      for (let i = 0; i < cells.length; i++) {
        if (!cells[i] || seen[i]) continue;
        let minx = 1e9, miny = 1e9, maxx = -1, maxy = -1, n = 0;
        const stack = [i]; seen[i] = 1;
        while (stack.length) {
          const c = stack.pop(), cx = c % GW, cy = (c / GW) | 0; n++;
          minx = Math.min(minx, cx); maxx = Math.max(maxx, cx); miny = Math.min(miny, cy); maxy = Math.max(maxy, cy);
          for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [-1, -1], [1, -1], [-1, 1]]) {
            const nx = cx + dx, ny = cy + dy, ni = ny * GW + nx;
            if (nx >= 0 && ny >= 0 && nx < GW && ny < GH && cells[ni] && !seen[ni]) { seen[ni] = 1; stack.push(ni); }
          }
        }
        if (n >= this.opts.minArea / 3) dets.push({ label: 'движение', score: Math.min(1, n / 20), box: [minx / GW, miny / GH, (maxx - minx + 1) / GW, (maxy - miny + 1) / GH], kind: 'motion' });
      }
    }
    this.prev = gray;

    this.target = null;
    if (this.opts.color && this.trackColor) {
      const [tr, tg, tb] = this.trackColor;
      let sx = 0, sy = 0, n = 0, minx = W, miny = H, maxx = 0, maxy = 0;
      for (let y = 0; y < H; y += 2) for (let x = 0; x < W; x += 2) {
        const i = (y * W + x) * 4;
        const d = Math.abs(data[i] - tr) + Math.abs(data[i + 1] - tg) + Math.abs(data[i + 2] - tb);
        if (d < 70) { sx += x; sy += y; n++; minx = Math.min(minx, x); miny = Math.min(miny, y); maxx = Math.max(maxx, x); maxy = Math.max(maxy, y); }
      }
      if (n > 12) {
        this.target = { x: sx / n / W, y: sy / n / H, size: n / (W * H / 4) };
        dets.push({ label: 'цель', score: Math.min(1, n / 200), box: [minx / W, miny / H, (maxx - minx) / W, (maxy - miny) / H], kind: 'target' });
      }
    }
    // внешние детекции (Python-модуль / плата) — добавляются через setExternal
    this.detections = dets.concat(this.external || []);
  }

  setExternal(list, w = 640, h = 480) {
    this.external = (list || []).map((d) => ({ label: d.label, score: d.score, box: [d.box[0] / w, d.box[1] / h, d.box[2] / w, d.box[3] / h], kind: 'model' }));
  }

  _draw(src) {
    for (const cv of this.views) {
      const ctx = cv.getContext('2d');
      const r = cv.getBoundingClientRect();
      if (cv.width !== Math.round(r.width) || cv.height !== Math.round(r.height)) { cv.width = Math.round(r.width) || 640; cv.height = Math.round(r.height) || 400; }
      const sw = src.videoWidth || src.naturalWidth || 640, sh = src.videoHeight || src.naturalHeight || 480;
      const s = Math.min(cv.width / sw, cv.height / sh), dw = sw * s, dh = sh * s, ox = (cv.width - dw) / 2, oy = (cv.height - dh) / 2;
      ctx.fillStyle = '#000'; ctx.fillRect(0, 0, cv.width, cv.height);
      ctx.drawImage(src, ox, oy, dw, dh);
      ctx.lineWidth = 1.5; ctx.font = '600 11px "Inter Variable", Inter, Segoe UI, sans-serif';
      for (const d of this.detections) {
        const [x, y, w, h] = d.box;
        const col = d.kind === 'target' ? '#c4b5ff' : d.kind === 'model' ? '#f5b544' : '#86aaff';
        ctx.strokeStyle = col; ctx.shadowColor = col; ctx.shadowBlur = 12;
        ctx.strokeRect(ox + x * dw, oy + y * dh, w * dw, h * dh);
        ctx.shadowBlur = 0;
        const txt = `${d.label} ${Math.round(d.score * 100)}%`;
        ctx.fillStyle = col; ctx.fillRect(ox + x * dw, oy + y * dh - 18, ctx.measureText(txt).width + 10, 18);
        ctx.fillStyle = '#06070a'; ctx.fillText(txt, ox + x * dw + 5, oy + y * dh - 5);
      }
      if (this.target) {
        const tx = ox + this.target.x * dw, ty = oy + this.target.y * dh;
        ctx.strokeStyle = '#c4b5ff'; ctx.beginPath(); ctx.arc(tx, ty, 14, 0, Math.PI * 2); ctx.moveTo(tx - 24, ty); ctx.lineTo(tx + 24, ty); ctx.moveTo(tx, ty - 24); ctx.lineTo(tx, ty + 24); ctx.stroke();
      }
    }
  }
}

export const vision = new Vision();

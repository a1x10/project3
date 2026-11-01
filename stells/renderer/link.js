// Связь приложения с платой.
// Способы: WebSocket к STELLS Agent (Wi-Fi/Ethernet/VPN), USB/Serial (Arduino/ESP32),
// пользовательский коннектор (скрипт на любом языке), встроенный симулятор.
const api = window.stells;

export class Link extends EventTarget {
  constructor() {
    super();
    this.state = 'offline';
    this.via = null;
    this.info = null;
    this.telemetry = {};
    this.ws = null;
    this.port = null;
    this.sim = null;
    this.host = null;
    api.connector.onTelemetry((t) => { if (this.via === 'connector') this._telemetry(t); });
    api.connector.onClosed(() => { if (this.via === 'connector') this._set('offline'); });
  }

  _set(state, via = this.via) {
    this.state = state; this.via = state === 'offline' ? null : via;
    this.dispatchEvent(new CustomEvent('state', { detail: { state, via: this.via } }));
  }
  _telemetry(msg) {
    if (msg.type === 'welcome') { this.info = msg; this.dispatchEvent(new CustomEvent('welcome', { detail: msg })); return; }
    if (msg.type === 'log') { this.dispatchEvent(new CustomEvent('log', { detail: msg.text })); return; }
    if (msg.type === 'telemetry' || msg.drone || msg.system) {
      for (const k of ['system', 'drone', 'vision']) if (msg[k]) this.telemetry[k] = { ...(this.telemetry[k] || {}), ...msg[k] };
      this.dispatchEvent(new CustomEvent('telemetry', { detail: this.telemetry }));
    }
    this.dispatchEvent(new CustomEvent('message', { detail: msg }));
  }

  async disconnect() {
    if (this.ws) { this.ws.onclose = null; this.ws.close(); this.ws = null; }
    if (this.port) { try { this.reader && await this.reader.cancel(); await this.port.close(); } catch { /* */ } this.port = null; }
    if (this.via === 'connector') await api.connector.stop();
    if (this.sim) { clearInterval(this.sim.timer); this.sim = null; }
    this.telemetry = {};
    this._set('offline');
  }

  // ---- STELLS Agent по сети
  connectWs(host, port = 8765, token = '') {
    return new Promise(async (resolve) => {
      await this.disconnect();
      this.host = host;
      this._set('connecting', 'ws');
      let done = false;
      const ws = new WebSocket(`ws://${host}:${port}`);
      this.ws = ws;
      const fail = (reason) => { if (!done) { done = true; resolve({ ok: false, reason }); } this.ws = null; this._set('offline'); };
      const to = setTimeout(() => { ws.close(); fail('Плата не отвечает (таймаут 5 с)'); }, 5000);
      ws.onopen = () => ws.send(JSON.stringify({ type: 'hello', token, client: 'STELLS Desktop' }));
      ws.onmessage = (e) => {
        let m; try { m = JSON.parse(e.data); } catch { return; }
        if (m.type === 'welcome' && !done) {
          clearTimeout(to); done = true;
          if (!m.ok) { resolve({ ok: false, reason: 'Неверный токен доступа' }); ws.close(); return; }
          this._set('online', 'ws'); resolve({ ok: true, info: m });
        }
        this._telemetry(m);
      };
      ws.onerror = () => { clearTimeout(to); fail('Нет соединения с ' + host); };
      ws.onclose = () => { clearTimeout(to); if (done) { this.ws = null; this._set('offline'); } else fail('Соединение закрыто'); };
    });
  }

  // ---- USB / Serial (Web Serial API)
  async connectSerial(baud = 115200) {
    await this.disconnect();
    if (!('serial' in navigator)) return { ok: false, reason: 'Web Serial недоступен' };
    try {
      this._set('connecting', 'serial');
      const port = await navigator.serial.requestPort();
      await port.open({ baudRate: baud });
      this.port = port;
      this._set('online', 'serial');
      this._readSerial();
      setTimeout(() => this.send({ type: 'hello' }), 1800); // Arduino перезагружается при открытии порта
      return { ok: true };
    } catch (e) {
      this._set('offline');
      return { ok: false, reason: e.message.includes('No port') ? 'USB-плата не найдена. Подключите кабель и установите драйвер CH340/CP210x.' : e.message };
    }
  }
  async _readSerial() {
    const dec = new TextDecoderStream();
    this.port.readable.pipeTo(dec.writable).catch(() => {});
    this.reader = dec.readable.getReader();
    let buf = '';
    try {
      for (;;) {
        const { value, done } = await this.reader.read();
        if (done) break;
        buf += value;
        let i;
        while ((i = buf.indexOf('\n')) >= 0) {
          const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
          try { this._telemetry(JSON.parse(line)); } catch { this.dispatchEvent(new CustomEvent('log', { detail: line })); }
        }
      }
    } catch { /* порт закрыт */ }
    if (this.via === 'serial') this._set('offline');
  }

  // ---- пользовательский коннектор (уже запущен из IDE)
  useConnector() { this.disconnect().then(() => this._set('online', 'connector')); }

  // ---- встроенный симулятор (для обучения и проверки пульта без железа)
  startSim() {
    this.disconnect().then(() => {
      const s = { x: 0, y: 0, alt: 0, battery: 100, armed: false, mode: 'STABILIZE', roll: 0, pitch: 0, yaw: 0, speed: 0, climb: 0, sats: 14, lat: 43.2389, lon: 76.8897, rc: { roll: 0, pitch: 0, yaw: 0, throttle: 0 }, target: null };
      this.sim = { s, timer: setInterval(() => {
        const rc = s.rc;
        s.roll += (rc.roll * 30 - s.roll) * 0.2;
        s.pitch += (rc.pitch * 30 - s.pitch) * 0.2;
        s.yaw = (s.yaw + rc.yaw * 6 + 360) % 360;
        if (s.armed) {
          if (s.target != null) { const d = s.target - s.alt; s.climb = Math.sign(d) * Math.max(0.6, Math.min(2, Math.abs(d))); if (Math.abs(d) < 0.08) { s.alt = s.target; s.target = null; s.climb = 0; } }
          else s.climb = (rc.throttle - 0.5) * 4;
          if (s.mode === 'LAND') s.climb = -1;
          if (s.mode === 'RTL') {
            const d = Math.hypot(s.x, s.y);
            if (d > 0.3) { s.x -= s.x / d * Math.min(d, 0.25); s.y -= s.y / d * Math.min(d, 0.25); s.climb = Math.max(0, 3 - s.alt); }
            else s.climb = -1;
          }
          s.alt = Math.max(0, s.alt + s.climb * 0.1);
          if (s.alt === 0 && (s.mode === 'LAND' || s.mode === 'RTL')) { s.armed = false; s.mode = 'STABILIZE'; }
          s.battery = Math.max(0, s.battery - 0.01);
          s.speed = Math.hypot(s.roll, s.pitch) / 4;
          const yr = s.yaw * Math.PI / 180, vf = s.pitch / 30 * 3 * 0.1, vr = s.roll / 30 * 3 * 0.1;
          s.x += Math.sin(yr) * vf + Math.cos(yr) * vr; s.y += -Math.cos(yr) * vf + Math.sin(yr) * vr;
          s.lat += Math.cos(s.yaw * Math.PI / 180) * -s.pitch * 1e-7;
          s.lon += Math.sin(s.yaw * Math.PI / 180) * s.roll * 1e-7;
        } else { s.climb = 0; s.speed = 0; }
        const { rc: _rc, target: _t, ...pub } = s;
        this._telemetry({ type: 'telemetry', drone: { ...pub, alt: +s.alt.toFixed(2), roll: +s.roll.toFixed(1), pitch: +s.pitch.toFixed(1), yaw: +s.yaw.toFixed(0), battery: +s.battery.toFixed(0) },
          system: { host: 'симулятор', temp: 42 + Math.random() * 3, load: 0.3 + Math.random() * 0.2 } });
      }, 100) };
      this._set('online', 'sim');
      this._telemetry({ type: 'welcome', ok: true, name: 'STELLS Симулятор', version: '1.0.0' });
    });
  }
  _simCommand(o) {
    const s = this.sim.s;
    if (o.type === 'rc') s.rc = o;
    if (o.type === 'drone') {
      if (o.cmd === 'arm') s.armed = true;
      if (o.cmd === 'disarm') { s.armed = false; s.alt = 0; }
      if (o.cmd === 'takeoff') { s.armed = true; s.mode = 'GUIDED'; s.target = Number(o.value) || 3; }
      if (o.cmd === 'land') s.mode = 'LAND';
      if (o.cmd === 'rtl') s.mode = 'RTL';
      if (o.cmd === 'mode') s.mode = o.value;
    }
  }

  send(obj) {
    if (this.state !== 'online') return false;
    if (this.via === 'ws' && this.ws && this.ws.readyState === 1) { this.ws.send(JSON.stringify(obj)); return true; }
    if (this.via === 'serial' && this.port && this.port.writable) {
      const w = this.port.writable.getWriter();
      w.write(new TextEncoder().encode(JSON.stringify(obj) + '\n')).finally(() => w.releaseLock());
      return true;
    }
    if (this.via === 'connector') { api.connector.send(obj); return true; }
    if (this.via === 'sim') { this._simCommand(obj); return true; }
    return false;
  }

  streamUrl() { return this.via === 'ws' && this.host ? `http://${this.host}:8766/stream` : null; }

  label() {
    return { ws: `Плата ${this.info?.name || this.host || ''}`, serial: 'USB / Serial', connector: 'Свой коннектор', sim: 'Симулятор' }[this.via] || 'Не подключено';
  }
}

export const link = new Link();

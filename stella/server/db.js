'use strict';
// Простая JSON-база с атомарной записью (без внешних зависимостей).
const fs = require('fs');
const path = require('path');

const DEFAULT_PLANS = {
  free: { id: 'free', name: 'Stella Free', price: '0 ₽', messagesPerDay: 30, ttsCharsPerMonth: 3000, sttPerDay: 20, models: ['*'], tools: true, color: '#9ca3af' },
  plus: { id: 'plus', name: 'Stella Plus', price: '299 ₽/мес', messagesPerDay: 400, ttsCharsPerMonth: 100000, sttPerDay: 400, models: ['*'], tools: true, color: '#8b5cf6' },
  pro: { id: 'pro', name: 'Stella Pro', price: '799 ₽/мес', messagesPerDay: 3000, ttsCharsPerMonth: 600000, sttPerDay: 3000, models: ['*'], tools: true, color: '#f59e0b' },
};

class DB {
  constructor(dir) {
    this.dir = dir;
    this.file = path.join(dir, 'stella-cloud.json');
    this.data = { users: [], sessions: [], plans: JSON.parse(JSON.stringify(DEFAULT_PLANS)), codes: [], bannedIps: [], usage: {}, log: [] };
    fs.mkdirSync(dir, { recursive: true });
    if (fs.existsSync(this.file)) {
      try { this.data = { ...this.data, ...JSON.parse(fs.readFileSync(this.file, 'utf8')) }; } catch { fs.copyFileSync(this.file, this.file + '.broken-' + Date.now()); }
    }
    this._t = null;
  }
  save(now = false) {
    const write = () => { const tmp = this.file + '.tmp'; fs.writeFileSync(tmp, JSON.stringify(this.data, null, 1)); fs.renameSync(tmp, this.file); this._t = null; };
    if (now) { clearTimeout(this._t); write(); return; }
    if (!this._t) this._t = setTimeout(write, 300);
  }
  flush() { if (this._t) { clearTimeout(this._t); this.save(true); } }
  log(type, data) {
    this.data.log.push({ ts: Date.now(), type, ...data });
    if (this.data.log.length > 2000) this.data.log.splice(0, this.data.log.length - 2000);
    this.save();
  }
}

module.exports = { DB, DEFAULT_PLANS };

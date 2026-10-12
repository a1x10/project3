// Вход в панель управления.
// Три способа: пароль (ADMIN_PANEL_PASSWORD или заданный в панели), код из WhatsApp (приходит админам бота),
// одноразовая ссылка (команда !панель в личке бота). Сессии — случайные токены в HttpOnly-куке,
// на диске хранится только их хеш. Перебор паролей и кодов ограничен.
import { createHash, randomBytes, randomInt, scryptSync, timingSafeEqual } from 'node:crypto';

const SESSION_TTL_MS = 30 * 24 * 3600 * 1000; // максимум 30 дней
const SESSION_IDLE_MS = 7 * 24 * 3600 * 1000; // без активности — 7 дней
const CODE_TTL_MS = 5 * 60 * 1000;
const LINK_TTL_MS = 10 * 60 * 1000;

const sha256 = (value) => createHash('sha256').update(String(value)).digest('hex');

export function hashPassword(password) {
  const salt = randomBytes(16);
  const hash = scryptSync(String(password), salt, 32, { N: 16384, r: 8, p: 1 });
  return `scrypt$${salt.toString('base64')}$${hash.toString('base64')}`;
}

export function verifyPassword(password, stored) {
  const [kind, salt, hash] = String(stored || '').split('$');
  if (kind !== 'scrypt' || !salt || !hash) return false;
  const expected = Buffer.from(hash, 'base64');
  const actual = scryptSync(String(password), Buffer.from(salt, 'base64'), expected.length, { N: 16384, r: 8, p: 1 });
  return timingSafeEqual(actual, expected);
}

// Счётчик попыток: не больше limit за windowMs
class Attempts {
  constructor(limit, windowMs) {
    this.limit = limit;
    this.windowMs = windowMs;
    this.map = new Map();
  }

  blocked(key) {
    const list = (this.map.get(key) || []).filter((t) => t > Date.now() - this.windowMs);
    this.map.set(key, list);
    return list.length >= this.limit;
  }

  add(key) {
    const list = this.map.get(key) || [];
    list.push(Date.now());
    this.map.set(key, list);
    if (this.map.size > 5000) this.map.delete(this.map.keys().next().value);
  }

  retryIn(key) {
    const list = this.map.get(key) || [];
    return list.length ? Math.max(0, list[0] + this.windowMs - Date.now()) : 0;
  }
}

export class PanelAuth {
  constructor({ config, secrets, core, logger }) {
    this.config = config;
    this.secrets = secrets;
    this.core = core;
    this.logger = logger;
    this.envHash = config.panel.password ? hashPassword(config.panel.password) : null;
    this.code = null; // { hash, expires, tries }
    this.links = new Map(); // hash -> { expires, by }
    // ограничение перебора пароля: по адресу и всего. Вход по коду и по ссылке от него не зависит —
    // так даже при атаке на пароль админ войдёт через WhatsApp.
    this.loginAttempts = new Attempts(8, 15 * 60 * 1000);
    this.globalAttempts = new Attempts(40, 15 * 60 * 1000);
    this.codeRequestsByIp = new Attempts(3, 15 * 60 * 1000);
    this.codeRequests = new Attempts(10, 60 * 60 * 1000);
    this.sessions = this.secrets.get('sessions') || {};
    this.pruneSessions();
  }

  // Пароль из панели важнее пароля из .env
  get passwordHash() {
    return this.secrets.get('panel')?.passwordHash || this.envHash;
  }

  methods() {
    return {
      password: Boolean(this.passwordHash),
      whatsapp: this.config.whatsapp.admins.length > 0,
    };
  }

  limited(ip) {
    if (this.loginAttempts.blocked(ip) || this.globalAttempts.blocked('all')) {
      const minutes = Math.ceil(Math.max(this.loginAttempts.retryIn(ip), 60000) / 60000);
      return `Слишком много попыток. Попробуйте через ${minutes} мин.`;
    }
    return null;
  }

  failed(ip, what) {
    this.loginAttempts.add(ip);
    this.globalAttempts.add('all');
    this.logger?.warn({ ip, what }, 'Неудачная попытка входа в панель');
  }

  loginPassword(password, meta) {
    const limit = this.limited(meta.ip);
    if (limit) return { error: limit, status: 429 };
    const stored = this.passwordHash;
    if (!stored) return { error: 'Пароль не задан — войдите по коду из WhatsApp', status: 400 };
    if (!password || !verifyPassword(password, stored)) {
      this.failed(meta.ip, 'password');
      return { error: 'Неверный пароль', status: 401 };
    }
    return { token: this.createSession({ ...meta, method: 'password' }) };
  }

  // Код из 6 цифр приходит всем админам бота в WhatsApp
  requestCode(meta) {
    if (!this.config.whatsapp.admins.length) return { error: 'Не заданы номера админов (ADMIN_NUMBERS)', status: 400 };
    if (!this.core.wa.isOpen) return { error: 'WhatsApp сейчас не на связи — войдите по паролю', status: 503 };
    if (this.codeRequestsByIp.blocked(meta.ip) || this.codeRequests.blocked('all')) return { error: 'Код уже отправлен несколько раз. Подождите 15 минут.', status: 429 };
    this.codeRequestsByIp.add(meta.ip);
    this.codeRequests.add('all');
    const code = String(randomInt(0, 1_000_000)).padStart(6, '0');
    this.code = { hash: sha256(code), expires: Date.now() + CODE_TTL_MS, tries: 0 };
    const where = meta.ip && meta.ip !== '127.0.0.1' && meta.ip !== '::1' ? ` (запрос с адреса ${meta.ip})` : '';
    this.core.messageAdmins(`🔐 Код для входа в панель бота: *${code}*\nДействует 5 минут${where}. Если это не вы — просто не вводите код.`, { maxAgeMs: CODE_TTL_MS });
    this.logger?.info({ ip: meta.ip }, 'Код входа в панель отправлен админам в WhatsApp');
    return { ok: true, sentTo: this.config.whatsapp.admins.length };
  }

  // у кода своя защита: 5 попыток на код, новый код — не чаще 3 раз за 15 минут с одного адреса
  loginCode(code, meta) {
    const current = this.code;
    if (!current || current.expires < Date.now()) return { error: 'Код устарел — запросите новый', status: 401 };
    current.tries += 1;
    if (current.tries > 5) {
      this.code = null;
      return { error: 'Слишком много попыток — запросите новый код', status: 429 };
    }
    const given = sha256(String(code || '').replace(/\D/g, ''));
    if (!timingSafeEqual(Buffer.from(given), Buffer.from(current.hash))) {
      this.logger?.warn({ ip: meta.ip }, 'Неверный код входа в панель');
      return { error: 'Неверный код', status: 401 };
    }
    this.code = null;
    return { token: this.createSession({ ...meta, method: 'whatsapp' }) };
  }

  // Одноразовая ссылка для команды !панель
  oneTimeLink(by = '') {
    const token = randomBytes(24).toString('base64url');
    this.links.set(sha256(token), { expires: Date.now() + LINK_TTL_MS, by });
    for (const [hash, link] of this.links) if (link.expires < Date.now()) this.links.delete(hash);
    const base = this.config.panel.publicUrl || `http://localhost:${this.config.http.publicPort || this.config.http.port}`;
    return `${base}/auth/link?t=${token}`;
  }

  // ссылку подобрать невозможно (192 бита), поэтому без ограничителя попыток
  loginLink(token, meta) {
    const hash = sha256(token || '');
    const link = this.links.get(hash);
    this.links.delete(hash);
    if (!link || link.expires < Date.now()) {
      this.logger?.warn({ ip: meta.ip }, 'Устаревшая или неверная ссылка входа в панель');
      return { error: 'Ссылка устарела или уже использована. Напишите боту !панель ещё раз.', status: 401 };
    }
    return { token: this.createSession({ ...meta, method: 'link' }) };
  }

  createSession({ ip = '', ua = '', method = '' }) {
    const token = randomBytes(32).toString('base64url');
    this.sessions[sha256(token)] = { createdAt: Date.now(), lastSeen: Date.now(), ip, ua: String(ua).slice(0, 160), method };
    this.saveSessions();
    this.logger?.info({ ip, method }, 'Вход в панель управления');
    this.core.emit?.('panel-login', { ip, method });
    return token;
  }

  session(token) {
    if (!token) return null;
    const id = sha256(token);
    const s = this.sessions[id];
    if (!s) return null;
    const now = Date.now();
    if (now - s.createdAt > SESSION_TTL_MS || now - s.lastSeen > SESSION_IDLE_MS) {
      delete this.sessions[id];
      this.saveSessions();
      return null;
    }
    if (now - s.lastSeen > 60000) {
      s.lastSeen = now;
      this.saveSessions();
    }
    return { id, ...s };
  }

  logout(token) {
    if (!token) return;
    delete this.sessions[sha256(token)];
    this.saveSessions();
  }

  // Выйти на всех устройствах, кроме текущего
  revokeOthers(currentToken) {
    const keep = currentToken ? sha256(currentToken) : null;
    for (const id of Object.keys(this.sessions)) if (id !== keep) delete this.sessions[id];
    this.saveSessions();
  }

  listSessions(currentToken) {
    const current = currentToken ? sha256(currentToken) : null;
    return Object.entries(this.sessions)
      .map(([id, s]) => ({ id: id.slice(0, 10), current: id === current, createdAt: s.createdAt, lastSeen: s.lastSeen, ip: s.ip, ua: s.ua, method: s.method }))
      .sort((a, b) => b.lastSeen - a.lastSeen);
  }

  setPassword(next, { current, currentToken } = {}) {
    if (this.passwordHash && !(current && verifyPassword(current, this.passwordHash))) {
      throw new Error('Текущий пароль неверный');
    }
    if (String(next || '').length < 10) throw new Error('Новый пароль — минимум 10 символов');
    this.secrets.set('panel', { ...(this.secrets.get('panel') || {}), passwordHash: hashPassword(next), changedAt: Date.now() });
    this.revokeOthers(currentToken); // смена пароля выкидывает все остальные сессии
    this.logger?.warn('Пароль панели изменён');
  }

  pruneSessions() {
    const now = Date.now();
    for (const [id, s] of Object.entries(this.sessions)) {
      if (now - s.createdAt > SESSION_TTL_MS || now - s.lastSeen > SESSION_IDLE_MS) delete this.sessions[id];
    }
  }

  saveSessions() {
    this.secrets.set('sessions', this.sessions);
  }
}

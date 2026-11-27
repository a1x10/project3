'use strict';
const crypto = require('crypto');

const USERNAME_RE = /^[\p{L}\p{N}_.-]{2,32}$/u;

function hashPassword(password, salt = crypto.randomBytes(16).toString('hex')) {
  const hash = crypto.scryptSync(String(password), salt, 64).toString('hex');
  return { salt, hash };
}
function verifyPassword(password, salt, hash) {
  const calc = crypto.scryptSync(String(password), salt, 64);
  const ref = Buffer.from(hash, 'hex');
  return ref.length === calc.length && crypto.timingSafeEqual(calc, ref);
}

class Accounts {
  /** @param {import('./store').Store} store */
  constructor(store) { this.store = store; }

  _all() { return this.store.data.accounts; }
  _public(a) {
    if (!a) return null;
    const { passwordHash, passwordSalt, ...rest } = a; // eslint-disable-line no-unused-vars
    return { ...rest, hasPassword: !!passwordHash };
  }

  list() { return this._all().map((a) => this._public(a)); }
  current() { return this._public(this._all().find((a) => a.username === this.store.data.currentAccount)); }

  register({ username, displayName, password, persona, email }) {
    username = String(username || '').trim();
    if (!USERNAME_RE.test(username)) throw new Error('Логин: 2–32 символа (буквы, цифры, _ . -)');
    if (this._all().some((a) => a.username.toLowerCase() === username.toLowerCase())) throw new Error('Такой пользователь уже существует');
    if (!['stella', 'mark'].includes(persona)) throw new Error('Выберите ассистента: Стелла или Марк');
    if (password && String(password).length < 4) throw new Error('Пароль должен быть не короче 4 символов');
    if (email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) throw new Error('Некорректный email');
    const acc = {
      username,
      displayName: String(displayName || username).trim().slice(0, 40),
      email: email ? String(email).trim() : '',
      persona,
      createdAt: Date.now(),
      lastLogin: Date.now(),
      avatarColor: ['#a78bfa', '#f472b6', '#38bdf8', '#34d399', '#fbbf24'][this._all().length % 5],
    };
    if (password) { const { salt, hash } = hashPassword(password); acc.passwordSalt = salt; acc.passwordHash = hash; }
    this._all().push(acc);
    this.store.data.currentAccount = username;
    this.store.data.settings.persona = persona;
    this.store.save();
    return this._public(acc);
  }

  login(username, password) {
    const acc = this._all().find((a) => a.username.toLowerCase() === String(username || '').trim().toLowerCase());
    if (!acc) throw new Error('Пользователь не найден');
    if (acc.passwordHash && !verifyPassword(password || '', acc.passwordSalt, acc.passwordHash)) throw new Error('Неверный пароль');
    acc.lastLogin = Date.now();
    this.store.data.currentAccount = acc.username;
    this.store.data.settings.persona = acc.persona;
    this.store.save();
    return this._public(acc);
  }

  logout() { this.store.data.currentAccount = null; this.store.save(); }

  update(patch) {
    const acc = this._all().find((a) => a.username === this.store.data.currentAccount);
    if (!acc) throw new Error('Нет активного аккаунта');
    if (patch.displayName !== undefined) acc.displayName = String(patch.displayName).trim().slice(0, 40) || acc.displayName;
    if (patch.persona !== undefined) {
      if (!['stella', 'mark'].includes(patch.persona)) throw new Error('Неизвестный ассистент');
      acc.persona = patch.persona; this.store.data.settings.persona = patch.persona;
    }
    if (patch.avatarColor && /^#[0-9a-f]{6}$/i.test(patch.avatarColor)) acc.avatarColor = patch.avatarColor;
    if (patch.bio !== undefined) acc.bio = String(patch.bio).slice(0, 300);
    if (patch.newPassword !== undefined) {
      if (acc.passwordHash && !verifyPassword(patch.oldPassword || '', acc.passwordSalt, acc.passwordHash)) throw new Error('Старый пароль неверен');
      if (patch.newPassword) {
        if (String(patch.newPassword).length < 4) throw new Error('Пароль должен быть не короче 4 символов');
        const { salt, hash } = hashPassword(patch.newPassword); acc.passwordSalt = salt; acc.passwordHash = hash;
      } else { delete acc.passwordSalt; delete acc.passwordHash; }
    }
    this.store.save();
    return this._public(acc);
  }

  remove(username) {
    const before = this._all().length;
    this.store.data.accounts = this._all().filter((a) => a.username !== username);
    delete this.store.data.conversations[username];
    delete this.store.data.memories[username];
    delete this.store.data.stats[username];
    if (this.store.data.currentAccount === username) this.store.data.currentAccount = null;
    this.store.save();
    return before !== this._all().length;
  }
}

module.exports = { Accounts, hashPassword, verifyPassword };

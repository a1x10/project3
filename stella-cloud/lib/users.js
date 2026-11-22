// Accounts. Every Stella account gets its own Linux user (when the server runs as root),
// its own home and workspace — the account's private "window" where its agent works.
//
// Security:
//  - passwords: scrypt + per-user salt, timing-safe compare, strength rules
//  - brute force: per-account lockout (5 failures -> growing lock), per-IP limits live in server.js
//  - sessions: only SHA-256 hashes of tokens are stored; 30-day sliding expiry; list / revoke / revoke all
//  - two-factor: TOTP (Google Authenticator, Aegis, 1Password…), RFC 6238
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { execFileSync } = require('child_process');
const { DATA, readJson, writeJson } = require('./store');

const FILE = path.join(DATA, 'users.json');
const HOMES = process.env.STELLA_HOMES || path.join(DATA, 'homes');
const isRoot = typeof process.getuid === 'function' && process.getuid() === 0 && process.platform === 'linux';
const SESSION_TTL = Number(process.env.STELLA_SESSION_DAYS || 30) * 24 * 3600 * 1000;

let db = readJson(FILE, { users: {}, tokens: {} });
db.invites = db.invites || {};
db.pairs = db.pairs || {};
// migrate: old databases stored raw session tokens as keys -> store only hashes
if (!db.tokenHashes) {
  const t = {};
  for (const [k, v] of Object.entries(db.tokens || {})) t[sha(k)] = Object.assign({ id: rid(), last: Date.now() }, v);
  db.tokens = t; db.tokenHashes = true;
}
const save = () => writeJson(FILE, db);
save();

function sha(s) { return crypto.createHash('sha256').update(String(s)).digest('hex'); }
function rid() { return crypto.randomBytes(6).toString('hex'); }
const hashPw = (pw, salt) => crypto.scryptSync(String(pw), salt, 64, { N: 16384, r: 8, p: 1 });
const newToken = () => crypto.randomBytes(32).toString('base64url');

function validName(n) { return /^[a-z0-9_]{3,24}$/.test(n); }

const COMMON = new Set(['password', 'password1', 'qwerty', 'qwerty123', '123456789', '1234567890', '11111111', 'iloveyou', 'admin123', 'qwertyuiop', 'йцукенгшщз', 'пароль123', '1q2w3e4r5t', 'zaq12wsx', 'letmein123', 'stella123']);
function checkPassword(pw, username) {
  pw = String(pw || '');
  if (pw.length < 10) throw new Error('Пароль минимум 10 символов');
  if (pw.length > 200) throw new Error('Слишком длинный пароль');
  if (/^\d+$/.test(pw)) throw new Error('Пароль не может состоять только из цифр');
  if (new Set(pw).size < 5) throw new Error('Слишком простой пароль');
  if (COMMON.has(pw.toLowerCase())) throw new Error('Этот пароль слишком распространён');
  if (username && pw.toLowerCase().includes(username)) throw new Error('Пароль не должен содержать имя аккаунта');
}

function createLinuxUser(name) {
  const home = path.join(HOMES, name);
  fs.mkdirSync(HOMES, { recursive: true, mode: 0o711 });
  if (!isRoot) {                                   // dev mode: same OS user, separate HOME
    fs.mkdirSync(path.join(home, 'workspace'), { recursive: true });
    return { home, uid: undefined, gid: undefined, sys: null };
  }
  const sys = 'st_' + name;
  try { execFileSync('id', [sys], { stdio: 'ignore' }); }
  catch { execFileSync('useradd', ['-m', '-d', home, '-s', '/usr/sbin/nologin', '-c', 'Stella account ' + name, sys], { stdio: 'ignore' }); }
  fs.mkdirSync(path.join(home, 'workspace'), { recursive: true });
  execFileSync('chown', ['-R', `${sys}:${sys}`, home]);
  if (!fs.existsSync('/usr/local/bin/agy') && !process.env.AGY_PATH) {
    const { spawn } = require('child_process');
    spawn('runuser', ['-u', sys, '--', 'bash', '-c', 'curl -fsSL https://antigravity.google/cli/install.sh | bash'], { stdio: 'ignore', detached: true, env: { HOME: home, PATH: '/usr/local/bin:/usr/bin:/bin' } }).unref();
  }
  fs.chmodSync(home, 0o700);
  const uid = Number(execFileSync('id', ['-u', sys]).toString().trim());
  const gid = Number(execFileSync('id', ['-g', sys]).toString().trim());
  return { home, uid, gid, sys };
}

/* ------------------------------------------------------------------ */
/* invites                                                              */
/* ------------------------------------------------------------------ */
function checkInvite(code) {
  code = String(code || '').trim();
  const mode = process.env.STELLA_SIGNUP || 'invite';
  if (mode === 'open') return null;
  if (mode === 'closed') throw new Error('Регистрация закрыта администратором');
  if (process.env.STELLA_INVITE && code.length >= 8 && safeEq(code, process.env.STELLA_INVITE)) return null;
  const inv = db.invites[code];
  if (!inv || inv.revoked || (inv.uses || 0) >= (inv.maxUses || 1) || (inv.expires && inv.expires < Date.now())) throw new Error('Неверный или уже использованный код приглашения');
  return inv;
}
function createInvite(by, note, maxUses = 1) {
  const code = crypto.randomBytes(8).toString('hex').toUpperCase().replace(/(.{4})(?!$)/g, '$1-');
  db.invites[code] = { code, note: String(note || '').slice(0, 80), by, created: Date.now(), expires: Date.now() + 7 * 24 * 3600 * 1000, uses: 0, maxUses: Math.max(1, Math.min(100, maxUses | 0 || 1)), usedBy: [] };
  save();
  return db.invites[code];
}
function revokeInvite(code) { if (db.invites[code]) { db.invites[code].revoked = true; save(); } }
function listInvites() { return Object.values(db.invites).sort((a, b) => b.created - a.created).slice(0, 100); }

/* ------------------------------------------------------------------ */
/* register / login                                                     */
/* ------------------------------------------------------------------ */
function safeEq(a, b) {
  const x = Buffer.from(String(a)), y = Buffer.from(String(b));
  return x.length === y.length && crypto.timingSafeEqual(x, y);
}
function register(username, password, invite, meta = {}) {
  username = String(username || '').trim().toLowerCase();
  if (!validName(username)) throw new Error('Имя: 3–24 символа, латиница, цифры или _');
  checkPassword(password, username);
  if (db.users[username]) throw new Error('Такой аккаунт уже есть');
  const inv = checkInvite(invite);
  const salt = crypto.randomBytes(16).toString('hex');
  const linux = createLinuxUser(username);
  db.users[username] = {
    name: username, salt, hash: hashPw(password, salt).toString('hex'), created: Date.now(),
    home: linux.home, uid: linux.uid, gid: linux.gid, sys: linux.sys,
    mcpToken: newToken(),
    admin: Object.keys(db.users).length === 0 || (process.env.STELLA_ADMIN || '').split(',').includes(username),
    invitedBy: inv ? inv.by : null, inviteNote: inv ? inv.note : null
  };
  if (inv) { inv.uses = (inv.uses || 0) + 1; inv.usedBy.push(username); }
  save();
  audit('register', username, meta);
  return login(username, password, meta);
}

class AuthError extends Error { constructor(msg, extra) { super(msg); Object.assign(this, extra || {}); } }

// a dummy hash so unknown usernames take the same time as real ones
const DUMMY_SALT = crypto.randomBytes(16).toString('hex');
function login(username, password, meta = {}) {
  username = String(username || '').trim().toLowerCase();
  const u = db.users[username];
  if (u && u.lockUntil && u.lockUntil > Date.now()) {
    throw new AuthError(`Слишком много неверных попыток. Аккаунт временно заблокирован на ${Math.ceil((u.lockUntil - Date.now()) / 60000)} мин.`, { status: 429 });
  }
  const ok = u ? safeEq(hashPw(password, u.salt).toString('hex'), u.hash) : (hashPw(password, DUMMY_SALT), false);
  if (!ok) {
    if (u) {
      u.fails = (u.fails || 0) + 1;
      if (u.fails >= 5) u.lockUntil = Date.now() + Math.min(24 * 60, 15 * 2 ** (u.fails - 5)) * 60000;
      save();
      audit('login_failed', username, meta);
    }
    throw new AuthError('Неверное имя или пароль', { status: 401 });
  }
  if (u.disabled) throw new AuthError('Аккаунт заблокирован администратором', { status: 403 });
  if (u.totp) {
    if (!meta.totp) throw new AuthError('Введите 6-значный код из приложения-аутентификатора', { status: 401, need2fa: true });
    if (!totpCheck(u, meta.totp)) {
      u.fails = (u.fails || 0) + 1; if (u.fails >= 5) u.lockUntil = Date.now() + 15 * 60000; save();
      audit('2fa_failed', username, meta);
      throw new AuthError('Неверный код подтверждения', { status: 401, need2fa: true });
    }
  }
  u.fails = 0; u.lockUntil = 0;
  const token = newSession(u, meta);
  audit('login', username, meta);
  return { token, user: publicUser(u) };
}

/* ------------------------------------------------------------------ */
/* sessions                                                             */
/* ------------------------------------------------------------------ */
function newSession(u, meta = {}) {
  const token = newToken();
  db.tokens[sha(token)] = { id: rid(), user: u.name, created: Date.now(), last: Date.now(), ip: meta.ip || '', ua: String(meta.ua || '').slice(0, 120), kind: meta.kind || '' };
  save();
  return token;
}
function session(token) {
  if (!token || typeof token !== 'string' || token.length > 200) return null;
  const h = sha(token);
  const t = db.tokens[h];
  if (!t) return null;
  if (Date.now() - (t.last || t.created) > SESSION_TTL) { delete db.tokens[h]; save(); return null; }
  if (Date.now() - (t.last || 0) > 10 * 60 * 1000) { t.last = Date.now(); save(); }
  return t;
}
function byToken(token) {
  const t = session(token);
  const u = t ? db.users[t.user] || null : null;
  if (u) u.seen = Date.now();
  return u && !u.disabled ? u : null;
}
function byMcpToken(token) {
  if (!token || typeof token !== 'string') return null;
  return Object.values(db.users).find(u => u.mcpToken && safeEq(u.mcpToken, token) && !u.disabled) || null;
}
function logout(token) { if (token) { delete db.tokens[sha(token)]; save(); } }
function sessions(u, currentToken) {
  const cur = currentToken ? sha(currentToken) : '';
  return Object.entries(db.tokens).filter(([, t]) => t.user === u.name)
    .map(([h, t]) => ({ id: t.id, created: t.created, last: t.last, ip: t.ip, ua: t.ua, kind: t.kind, current: h === cur }))
    .sort((a, b) => b.last - a.last);
}
function revokeSession(u, id) { for (const [h, t] of Object.entries(db.tokens)) if (t.user === u.name && t.id === id) delete db.tokens[h]; save(); audit('session_revoked', u.name, {}); }
function revokeOthers(u, currentToken) {
  const cur = currentToken ? sha(currentToken) : '';
  for (const [h, t] of Object.entries(db.tokens)) if (t.user === u.name && h !== cur) delete db.tokens[h];
  save(); audit('sessions_revoked_all', u.name, {});
}
function changePassword(u, oldPw, newPw, currentToken) {
  if (!safeEq(hashPw(oldPw, u.salt).toString('hex'), u.hash)) throw new Error('Текущий пароль неверный');
  checkPassword(newPw, u.name);
  u.salt = crypto.randomBytes(16).toString('hex');
  u.hash = hashPw(newPw, u.salt).toString('hex');
  revokeOthers(u, currentToken);
  save(); audit('password_changed', u.name, {});
}

/* ------------------------------------------------------------------ */
/* TOTP two-factor (RFC 6238, 30 s, 6 digits, SHA-1 — what all authenticator apps use) */
/* ------------------------------------------------------------------ */
const B32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
function b32enc(buf) { let bits = '', out = ''; for (const b of buf) bits += b.toString(2).padStart(8, '0'); for (let i = 0; i < bits.length; i += 5) out += B32[parseInt(bits.slice(i, i + 5).padEnd(5, '0'), 2)]; return out; }
function b32dec(s) { let bits = ''; for (const c of s.replace(/=+$/, '').toUpperCase()) { const v = B32.indexOf(c); if (v < 0) continue; bits += v.toString(2).padStart(5, '0'); } const out = []; for (let i = 0; i + 8 <= bits.length; i += 8) out.push(parseInt(bits.slice(i, i + 8), 2)); return Buffer.from(out); }
function hotp(secret, counter) {
  const c = Buffer.alloc(8); c.writeBigUInt64BE(BigInt(counter));
  const h = crypto.createHmac('sha1', b32dec(secret)).update(c).digest();
  const o = h[h.length - 1] & 15;
  return String(((h.readUInt32BE(o) & 0x7fffffff) % 1e6)).padStart(6, '0');
}
function totpCheck(u, code, secret) {
  code = String(code || '').replace(/\s/g, '');
  if (!/^\d{6}$/.test(code)) return false;
  const s = secret || u.totp;
  const step = Math.floor(Date.now() / 30000);
  for (const d of [-1, 0, 1]) {
    if (step + d <= (u.totpLastStep || 0)) continue;           // no replay of a used code
    if (safeEq(hotp(s, step + d), code)) { if (!secret) { u.totpLastStep = step + d; save(); } return true; }
  }
  return false;
}
function totpSetup(u) {
  u.totpPending = b32enc(crypto.randomBytes(20));
  save();
  const label = encodeURIComponent('Stella:' + u.name);
  return { secret: u.totpPending, uri: `otpauth://totp/${label}?secret=${u.totpPending}&issuer=Stella&digits=6&period=30` };
}
function totpEnable(u, code) {
  if (!u.totpPending || !totpCheck(u, code, u.totpPending)) throw new Error('Код не подошёл — проверьте время на телефоне и попробуйте ещё раз');
  u.totp = u.totpPending; delete u.totpPending; u.totpLastStep = Math.floor(Date.now() / 30000);
  save(); audit('2fa_enabled', u.name, {});
}
function totpDisable(u, password, code) {
  if (!safeEq(hashPw(password, u.salt).toString('hex'), u.hash)) throw new Error('Неверный пароль');
  if (u.totp && !totpCheck(u, code)) throw new Error('Неверный код подтверждения');
  delete u.totp; delete u.totpPending; save(); audit('2fa_disabled', u.name, {});
}

/* ------------------------------------------------------------------ */
/* admin                                                                */
/* ------------------------------------------------------------------ */
function publicUser(u) { return { name: u.name, created: u.created, admin: !!u.admin, twofa: !!u.totp }; }
function adminView(u) { return { name: u.name, created: u.created, seen: u.seen || 0, admin: !!u.admin, disabled: !!u.disabled, invitedBy: u.invitedBy, note: u.inviteNote, sys: u.sys, twofa: !!u.totp, locked: !!(u.lockUntil && u.lockUntil > Date.now()) }; }
function setDisabled(name, on) {
  const u = db.users[name]; if (!u) throw new Error('нет такого аккаунта');
  if (u.admin && on) throw new Error('Нельзя заблокировать администратора');
  u.disabled = !!on;
  if (on) for (const [t, v] of Object.entries(db.tokens)) if (v.user === name) delete db.tokens[t];
  save(); audit(on ? 'blocked' : 'unblocked', name, {});
}
function unlock(name) { const u = db.users[name]; if (u) { u.fails = 0; u.lockUntil = 0; save(); } }
function remove(name) {
  const u = db.users[name]; if (!u) return;
  if (u.admin) throw new Error('Нельзя удалить администратора');
  for (const [t, v] of Object.entries(db.tokens)) if (v.user === name) delete db.tokens[t];
  delete db.users[name]; save();
  if (isRoot && u.sys) { try { execFileSync('pkill', ['-KILL', '-u', u.sys], { stdio: 'ignore' }); } catch {} try { execFileSync('userdel', ['-r', u.sys], { stdio: 'ignore' }); } catch {} }
  try { fs.rmSync(path.join(DATA, 'users', name), { recursive: true, force: true }); } catch {}
  audit('deleted', name, {});
}

/* ------------------------------------------------------------------ */
/* pairing (QR from the PC)                                             */
/* ------------------------------------------------------------------ */
function createPair(u) {
  const code = crypto.randomBytes(8).toString('hex').toUpperCase();
  db.pairs[code] = { user: u.name, exp: Date.now() + 5 * 60 * 1000 };
  for (const [c, p] of Object.entries(db.pairs)) if (p.exp < Date.now()) delete db.pairs[c];
  save();
  return code;
}
function claimPair(code, meta = {}) {
  code = String(code || '').trim().toUpperCase();
  const p = db.pairs[code];
  if (!p || p.exp < Date.now()) throw new Error('Код привязки устарел — покажите новый');
  delete db.pairs[code];
  const u = db.users[p.user];
  if (!u || u.disabled) throw new Error('Аккаунт недоступен');
  const token = newSession(u, Object.assign({ kind: 'qr' }, meta));
  audit('paired', u.name, meta);
  return { token, user: publicUser(u) };
}

/* ------------------------------------------------------------------ */
/* security log                                                         */
/* ------------------------------------------------------------------ */
function audit(event, user, meta) {
  try { fs.appendFileSync(path.join(DATA, 'security.log'), JSON.stringify({ t: new Date().toISOString(), event, user, ip: meta.ip || '', ua: String(meta.ua || '').slice(0, 80) }) + '\n', { mode: 0o600 }); } catch {}
}

function get(name) { return db.users[name] || null; }
function all() { return Object.values(db.users); }
function userDir(u) { const d = path.join(DATA, 'users', u.name); fs.mkdirSync(d, { recursive: true, mode: 0o700 }); return d; }

module.exports = {
  _save: save, createInvite, revokeInvite, listInvites, adminView, setDisabled, unlock, remove, createPair, claimPair,
  register, login, logout, byToken, byMcpToken, publicUser, get, all, userDir, isRoot,
  sessions, revokeSession, revokeOthers, changePassword, totpSetup, totpEnable, totpDisable, audit, AuthError
};

// Accounts. Every Stella account gets its own Linux user (when the server runs as root),
// its own home and workspace — the account's private "window" where its agent works.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { execFileSync } = require('child_process');
const { DATA, readJson, writeJson } = require('./store');

const FILE = path.join(DATA, 'users.json');
const HOMES = process.env.STELLA_HOMES || path.join(DATA, 'homes');
const isRoot = typeof process.getuid === 'function' && process.getuid() === 0 && process.platform === 'linux';

let db = readJson(FILE, { users: {}, tokens: {} });
db.invites = db.invites || {};
db.pairs = db.pairs || {};
const save = () => writeJson(FILE, db);

const hash = (pw, salt) => crypto.scryptSync(pw, salt, 64).toString('hex');
const newToken = () => crypto.randomBytes(32).toString('hex');

function validName(n) { return /^[a-z0-9_]{3,24}$/.test(n); }

function createLinuxUser(name) {
  const home = path.join(HOMES, name);
  fs.mkdirSync(HOMES, { recursive: true, mode: 0o711 });
  if (!isRoot) {                                   // dev mode: same OS user, separate HOME
    fs.mkdirSync(path.join(home, 'workspace'), { recursive: true });
    return { home, uid: undefined, gid: undefined, sys: null };
  }
  const sys = 'st_' + name;
  try { execFileSync('id', [sys], { stdio: 'ignore' }); }
  catch { execFileSync('useradd', ['-m', '-d', home, '-s', '/bin/bash', '-c', 'Stella account ' + name, sys], { stdio: 'ignore' }); }
  fs.mkdirSync(path.join(home, 'workspace'), { recursive: true });
  execFileSync('chown', ['-R', `${sys}:${sys}`, home]);
  // no shared agy binary? install Antigravity CLI into this account's home (in the background)
  if (!fs.existsSync('/usr/local/bin/agy') && !process.env.AGY_PATH) {
    const { spawn } = require('child_process');
    spawn('su', ['-', sys, '-c', 'curl -fsSL https://antigravity.google/cli/install.sh | bash'], { stdio: 'ignore', detached: true }).unref();
  }
  fs.chmodSync(home, 0o700);
  const uid = Number(execFileSync('id', ['-u', sys]).toString().trim());
  const gid = Number(execFileSync('id', ['-g', sys]).toString().trim());
  return { home, uid, gid, sys };
}

// invite codes: the master code from /etc/stella-cloud.env (STELLA_INVITE) or one-time codes made by an admin
function checkInvite(code) {
  code = String(code || '').trim();
  const mode = process.env.STELLA_SIGNUP || 'invite';
  if (mode === 'open') return null;
  if (mode === 'closed') throw new Error('Регистрация закрыта администратором');
  if (process.env.STELLA_INVITE && code === process.env.STELLA_INVITE) return null;
  const inv = db.invites[code];
  if (!inv || inv.revoked || (inv.uses || 0) >= (inv.maxUses || 1)) throw new Error('Неверный или уже использованный код приглашения');
  return inv;
}
function createInvite(by, note, maxUses = 1) {
  const code = crypto.randomBytes(5).toString('hex').toUpperCase().replace(/(.{5})/, '$1-');
  db.invites[code] = { code, note: String(note || '').slice(0, 80), by, created: Date.now(), uses: 0, maxUses: Math.max(1, Math.min(100, maxUses | 0 || 1)), usedBy: [] };
  save();
  return db.invites[code];
}
function revokeInvite(code) { if (db.invites[code]) { db.invites[code].revoked = true; save(); } }
function listInvites() { return Object.values(db.invites).sort((a, b) => b.created - a.created).slice(0, 100); }

function register(username, password, invite) {
  username = String(username || '').trim().toLowerCase();
  if (!validName(username)) throw new Error('Имя: 3–24 символа, латиница, цифры или _');
  if (String(password || '').length < 8) throw new Error('Пароль минимум 8 символов');
  if (db.users[username]) throw new Error('Такой аккаунт уже есть');
  const inv = checkInvite(invite);
  const salt = crypto.randomBytes(16).toString('hex');
  const linux = createLinuxUser(username);
  db.users[username] = {
    name: username, salt, hash: hash(password, salt), created: Date.now(),
    home: linux.home, uid: linux.uid, gid: linux.gid, sys: linux.sys,
    mcpToken: newToken(),                      // used by this account's agent tools (WhatsApp MCP)
    admin: Object.keys(db.users).length === 0 || (process.env.STELLA_ADMIN || '').split(',').includes(username),
    invitedBy: inv ? inv.by : null, inviteNote: inv ? inv.note : null
  };
  if (inv) { inv.uses = (inv.uses || 0) + 1; inv.usedBy.push(username); }
  save();
  return login(username, password);
}

function login(username, password) {
  username = String(username || '').trim().toLowerCase();
  const u = db.users[username];
  if (!u || hash(String(password || ''), u.salt) !== u.hash) throw new Error('Неверное имя или пароль');
  if (u.disabled) throw new Error('Аккаунт заблокирован администратором');
  const token = newToken();
  db.tokens[token] = { user: username, created: Date.now() };
  save();
  return { token, user: publicUser(u) };
}

function byToken(token) {
  const t = token && db.tokens[token];
  const u = t ? db.users[t.user] || null : null;
  if (u) u.seen = Date.now();
  return u && !u.disabled ? u : null;
}
function byMcpToken(token) {
  if (!token) return null;
  return Object.values(db.users).find(u => u.mcpToken === token && !u.disabled) || null;
}
function logout(token) { delete db.tokens[token]; save(); }
function publicUser(u) { return { name: u.name, created: u.created, admin: !!u.admin }; }
function adminView(u) { return { name: u.name, created: u.created, seen: u.seen || 0, admin: !!u.admin, disabled: !!u.disabled, invitedBy: u.invitedBy, note: u.inviteNote, sys: u.sys }; }
function setDisabled(name, on) {
  const u = db.users[name]; if (!u) throw new Error('нет такого аккаунта');
  if (u.admin && on) throw new Error('Нельзя заблокировать администратора');
  u.disabled = !!on;
  if (on) for (const [t, v] of Object.entries(db.tokens)) if (v.user === name) delete db.tokens[t];
  save();
}
function remove(name) {
  const u = db.users[name]; if (!u) return;
  if (u.admin) throw new Error('Нельзя удалить администратора');
  for (const [t, v] of Object.entries(db.tokens)) if (v.user === name) delete db.tokens[t];
  delete db.users[name]; save();
  if (isRoot && u.sys) { try { execFileSync('pkill', ['-KILL', '-u', u.sys], { stdio: 'ignore' }); } catch {} try { execFileSync('userdel', ['-r', u.sys], { stdio: 'ignore' }); } catch {} }
  try { fs.rmSync(path.join(DATA, 'users', name), { recursive: true, force: true }); } catch {}
}
// pairing: a signed-in device makes a short code (QR), a new device claims it and gets its own session
function createPair(u) {
  const code = crypto.randomBytes(4).toString('hex').toUpperCase();
  db.pairs[code] = { user: u.name, exp: Date.now() + 10 * 60 * 1000 };
  for (const [c, p] of Object.entries(db.pairs)) if (p.exp < Date.now()) delete db.pairs[c];
  save();
  return code;
}
function claimPair(code) {
  code = String(code || '').trim().toUpperCase();
  const p = db.pairs[code];
  if (!p || p.exp < Date.now()) throw new Error('Код привязки устарел — покажите новый');
  delete db.pairs[code];
  const u = db.users[p.user];
  if (!u || u.disabled) throw new Error('Аккаунт недоступен');
  const token = newToken();
  db.tokens[token] = { user: u.name, created: Date.now(), paired: true };
  save();
  return { token, user: publicUser(u) };
}
function get(name) { return db.users[name] || null; }
function all() { return Object.values(db.users); }
function userDir(u) { const d = path.join(DATA, 'users', u.name); fs.mkdirSync(d, { recursive: true, mode: 0o700 }); return d; }

module.exports = { _save: save, createInvite, revokeInvite, listInvites, adminView, setDisabled, remove, createPair, claimPair, register, login, logout, byToken, byMcpToken, publicUser, get, all, userDir, isRoot };

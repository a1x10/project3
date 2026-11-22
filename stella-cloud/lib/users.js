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

function register(username, password) {
  username = String(username || '').trim().toLowerCase();
  if (!validName(username)) throw new Error('Имя: 3–24 символа, латиница, цифры или _');
  if (String(password || '').length < 8) throw new Error('Пароль минимум 8 символов');
  if (db.users[username]) throw new Error('Такой аккаунт уже есть');
  const salt = crypto.randomBytes(16).toString('hex');
  const linux = createLinuxUser(username);
  db.users[username] = {
    name: username, salt, hash: hash(password, salt), created: Date.now(),
    home: linux.home, uid: linux.uid, gid: linux.gid, sys: linux.sys,
    mcpToken: newToken()                       // used by this account's agent tools (WhatsApp MCP)
  };
  save();
  return login(username, password);
}

function login(username, password) {
  username = String(username || '').trim().toLowerCase();
  const u = db.users[username];
  if (!u || hash(String(password || ''), u.salt) !== u.hash) throw new Error('Неверное имя или пароль');
  const token = newToken();
  db.tokens[token] = { user: username, created: Date.now() };
  save();
  return { token, user: publicUser(u) };
}

function byToken(token) {
  const t = token && db.tokens[token];
  return t ? db.users[t.user] || null : null;
}
function byMcpToken(token) {
  if (!token) return null;
  return Object.values(db.users).find(u => u.mcpToken === token) || null;
}
function logout(token) { delete db.tokens[token]; save(); }
function publicUser(u) { return { name: u.name, created: u.created }; }
function get(name) { return db.users[name] || null; }
function all() { return Object.values(db.users); }
function userDir(u) { const d = path.join(DATA, 'users', u.name); fs.mkdirSync(d, { recursive: true, mode: 0o700 }); return d; }

module.exports = { _save: save, register, login, logout, byToken, byMcpToken, publicUser, get, all, userDir, isRoot };

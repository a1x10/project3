// Per-account services the agent can use: profile ("about me"), BilimClass, e-mail.
// Passwords are sealed with AES-256-GCM (vault.js) and are NEVER given to the model:
//  - e-mail: the server logs in itself and only returns messages / sends what the agent asks for
//  - BilimClass & other sites: Stella on the PC types the login into the browser itself
const fs = require('fs');
const path = require('path');
const { readJson, writeJson } = require('./store');
const users = require('./users');
const vault = require('./vault');

const file = u => path.join(users.userDir(u), 'services.json');
const load = u => readJson(file(u), { profile: {}, services: {} });
const save = (u, d) => writeJson(file(u), d);

/* ---------------- profile ("about me") ---------------- */
const PROFILE_FIELDS = ['name', 'address', 'role', 'city', 'language', 'style', 'tasks', 'about'];
function getProfile(u) { return load(u).profile || {}; }
function setProfile(u, p) {
  const d = load(u);
  d.profile = {};
  for (const k of PROFILE_FIELDS) if (p && p[k] != null) d.profile[k] = String(p[k]).slice(0, k === 'about' ? 4000 : 300);
  d.profile.updated = Date.now();
  save(u, d);
  return d.profile;
}
function profileText(u) {
  const p = getProfile(u);
  const lines = [];
  if (p.name) lines.push('Name: ' + p.name + (p.address ? ` (address them as: ${p.address})` : ''));
  if (p.role) lines.push('Occupation / role: ' + p.role);
  if (p.city) lines.push('City / country: ' + p.city);
  if (p.language) lines.push('Preferred language: ' + p.language);
  if (p.style) lines.push('How to talk to them: ' + p.style);
  if (p.tasks) lines.push('What they usually need help with: ' + p.tasks);
  if (p.about) lines.push('About them (in their words): ' + p.about);
  return lines.length ? '[About the user — use it to personalize, never recite it]\n' + lines.join('\n') + '\n\n' : '';
}

/* ---------------- services ---------------- */
const KNOWN = {
  bilimclass: { title: 'BilimClass', url: 'https://bilimclass.kz', kind: 'site' },
  email: { title: 'Почта', kind: 'email' }
};
const EMAIL_PRESETS = {
  'gmail.com': { imap: 'imap.gmail.com', smtp: 'smtp.gmail.com' }, 'googlemail.com': { imap: 'imap.gmail.com', smtp: 'smtp.gmail.com' },
  'yandex.ru': { imap: 'imap.yandex.ru', smtp: 'smtp.yandex.ru' }, 'ya.ru': { imap: 'imap.yandex.ru', smtp: 'smtp.yandex.ru' }, 'yandex.kz': { imap: 'imap.yandex.ru', smtp: 'smtp.yandex.ru' },
  'mail.ru': { imap: 'imap.mail.ru', smtp: 'smtp.mail.ru' }, 'bk.ru': { imap: 'imap.mail.ru', smtp: 'smtp.mail.ru' }, 'inbox.ru': { imap: 'imap.mail.ru', smtp: 'smtp.mail.ru' }, 'list.ru': { imap: 'imap.mail.ru', smtp: 'smtp.mail.ru' },
  'outlook.com': { imap: 'outlook.office365.com', smtp: 'smtp.office365.com' }, 'hotmail.com': { imap: 'outlook.office365.com', smtp: 'smtp.office365.com' },
  'icloud.com': { imap: 'imap.mail.me.com', smtp: 'smtp.mail.me.com' }
};

function list(u) {
  const d = load(u);
  const out = {};
  for (const [k, v] of Object.entries(d.services || {})) out[k] = { connected: true, login: v.login, url: v.url, address: v.address, updated: v.updated };
  return out;
}
function setService(u, name, data) {
  if (!/^[a-z0-9_-]{2,30}$/.test(name)) throw new Error('bad service name');
  const d = load(u); d.services = d.services || {};
  const aad = u.name + ':' + name;
  if (name === 'email') {
    const address = String(data.address || '').trim().toLowerCase();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(address)) throw new Error('Неверный адрес почты');
    const preset = EMAIL_PRESETS[address.split('@')[1]] || {};
    const imap = String(data.imap || preset.imap || '').trim(), smtp = String(data.smtp || preset.smtp || '').trim();
    if (!imap || !smtp) throw new Error('Для этой почты укажите IMAP и SMTP сервер');
    d.services.email = { address, login: address, imap, smtp, secret: vault.seal(String(data.password || ''), aad), updated: Date.now() };
  } else {
    const login = String(data.login || '').trim();
    if (!login || !data.password) throw new Error('Укажите логин и пароль');
    d.services[name] = { login, url: String(data.url || (KNOWN[name] && KNOWN[name].url) || '').trim(), secret: vault.seal(String(data.password), aad), updated: Date.now() };
  }
  save(u, d);
  users.audit('service_saved:' + name, u.name, {});
  return list(u);
}
function removeService(u, name) { const d = load(u); if (d.services) delete d.services[name]; save(u, d); users.audit('service_removed:' + name, u.name, {}); return list(u); }
// only for Stella itself (PC app filling a login form / server mail client) — never sent to the model
function secret(u, name) {
  const s = (load(u).services || {})[name];
  if (!s) return null;
  return Object.assign({}, s, { password: vault.open(s.secret, u.name + ':' + name), secret: undefined });
}

/* ---------------- e-mail ---------------- */
async function imapClient(u) {
  const s = secret(u, 'email');
  if (!s) throw new Error('Почта не подключена. Подключите её: Stella → «Сервисы» → «Почта».');
  const { ImapFlow } = require('imapflow');
  const c = new ImapFlow({ host: s.imap, port: 993, secure: true, auth: { user: s.login, pass: s.password }, logger: false, socketTimeout: 30000 });
  await c.connect();
  return c;
}
async function emailList(u, { folder = 'INBOX', limit = 15, unread = false, search = '' } = {}) {
  const c = await imapClient(u);
  try {
    const lock = await c.getMailboxLock(folder);
    try {
      let uids;
      const q = {};
      if (unread) q.seen = false;
      if (search) q.or = [{ subject: search }, { from: search }, { body: search }];
      uids = await c.search(Object.keys(q).length ? q : { all: true }, { uid: true });
      uids = (uids || []).slice(-Math.min(50, limit)).reverse();
      const out = [];
      if (uids.length) for await (const m of c.fetch(uids, { envelope: true, flags: true, uid: true }, { uid: true })) {
        out.push({ id: m.uid, date: m.envelope.date, from: (m.envelope.from || []).map(a => `${a.name || ''} <${a.address}>`).join(', '), subject: m.envelope.subject || '(без темы)', unread: !m.flags.has('\\Seen') });
      }
      return out.sort((a, b) => new Date(b.date) - new Date(a.date));
    } finally { lock.release(); }
  } finally { await c.logout().catch(() => {}); }
}
async function emailRead(u, { id, folder = 'INBOX' }) {
  const c = await imapClient(u);
  try {
    const lock = await c.getMailboxLock(folder);
    try {
      const m = await c.fetchOne(String(id), { source: true }, { uid: true });
      if (!m) throw new Error('Письмо не найдено');
      const { simpleParser } = require('mailparser');
      const p = await simpleParser(m.source);
      return { id, from: p.from && p.from.text, to: p.to && p.to.text, date: p.date, subject: p.subject, text: String(p.text || '').slice(0, 15000), attachments: (p.attachments || []).map(a => a.filename) };
    } finally { lock.release(); }
  } finally { await c.logout().catch(() => {}); }
}
async function emailSend(u, { to, subject, text, cc }) {
  const s = secret(u, 'email');
  if (!s) throw new Error('Почта не подключена. Подключите её: Stella → «Сервисы» → «Почта».');
  if (!to || !text) throw new Error('to and text are required');
  const nodemailer = require('nodemailer');
  const t = nodemailer.createTransport({ host: s.smtp, port: 465, secure: true, auth: { user: s.login, pass: s.password } });
  const r = await t.sendMail({ from: s.address, to, cc, subject: subject || '', text });
  users.audit('email_sent', u.name, {});
  return { sent: true, messageId: r.messageId, to };
}
async function emailTest(u) { const c = await imapClient(u); await c.logout().catch(() => {}); return true; }

module.exports = { getProfile, setProfile, profileText, list, setService, removeService, secret, emailList, emailRead, emailSend, emailTest, KNOWN };

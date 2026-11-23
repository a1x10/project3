// WhatsApp for each Stella account (unofficial, WhatsApp Web protocol via Baileys).
// Linked by QR code from the phone app. Messages are stored only on this server.
const fs = require('fs');
const path = require('path');
const QRCode = require('qrcode');
const { readJson, saveLater } = require('./store');
const users = require('./users');

let B = null;                                   // baileys module (ESM, loaded lazily)
async function lib() { if (!B) B = await import('@whiskeysockets/baileys'); return B; }

let emit = () => {}, agent = null;
function setup(opts) { emit = opts.emit; agent = opts.agent; }

const MAX_PER_CHAT = 400;
const sessions = new Map();                     // username -> session

function dirOf(u) { return path.join(users.userDir(u), 'whatsapp'); }

function session(u) {
  let s = sessions.get(u.name);
  if (s) return s;
  const storeFile = path.join(dirOf(u), 'store.json');
  const data = readJson(storeFile, { contacts: {}, chats: {}, auto: {}, autoLog: [] });
  s = { u, sock: null, status: 'off', qr: null, me: null, data, storeFile, waiters: [], pending: [], autoTimers: new Map(), autoCount: {} };
  s.save = () => saveLater(storeFile, () => s.data, 1500);
  sessions.set(u.name, s);
  return s;
}

function publicStatus(s) { return { status: s.status, qr: s.qr, me: s.me, error: s.status === 'error' ? s.error : null }; }
function setStatus(s, status, extra = {}) { Object.assign(s, { status }, extra); emit(s.u.name, Object.assign({ t: 'wa.status' }, publicStatus(s))); }

/* ------------------------------------------------------------------ */
/* connect / disconnect                                                 */
/* ------------------------------------------------------------------ */
async function connect(u) {
  const s = session(u);
  if (s.sock && (s.status === 'connected' || s.status === 'connecting' || s.status === 'qr')) return publicStatus(s);
  if (s.status === 'error' || s.status === 'off' || s.status === 'logged_out') s.fails = 0;     // explicit retry by the user
  const { default: makeWASocket, useMultiFileAuthState, Browsers, DisconnectReason, fetchLatestBaileysVersion, fetchLatestWaWebVersion } = await lib();
  const pino = require('pino');
  const authDir = path.join(dirOf(u), 'auth');
  fs.mkdirSync(authDir, { recursive: true, mode: 0o700 });
  const { state, saveCreds } = await useMultiFileAuthState(authDir);
  let version;
  // WhatsApp rejects outdated clients (428 Connection Terminated): use the current WhatsApp Web revision
  try { version = (await fetchLatestWaWebVersion({})).version; } catch {}
  if (!version) { try { version = (await fetchLatestBaileysVersion()).version; } catch {} }
  setStatus(s, 'connecting', { qr: null });

  // optional outbound proxy (servers that can reach the internet only through a proxy)
  const proxyUrl = process.env.STELLA_WA_PROXY || process.env.HTTPS_PROXY || process.env.https_proxy;
  let agentOpt = {};
  if (proxyUrl) { const { HttpsProxyAgent } = require('https-proxy-agent'); const ag = new HttpsProxyAgent(proxyUrl); agentOpt = { agent: ag, fetchAgent: ag }; }
  const sock = makeWASocket(Object.assign(agentOpt, {
    auth: state, version, logger: pino({ level: 'silent' }),
    browser: Browsers.macOS('Desktop'), syncFullHistory: false, markOnlineOnConnect: false
  }));
  s.sock = sock;
  sock.ev.on('creds.update', saveCreds);
  sock.ev.on('connection.update', async ({ connection, lastDisconnect, qr }) => {
    if (qr) setStatus(s, 'qr', { qr: await QRCode.toDataURL(qr, { margin: 1, width: 320 }) });
    if (connection === 'open') {
      s.fails = 0;
      const id = sock.user && sock.user.id;
      setStatus(s, 'connected', { qr: null, me: { id, name: sock.user && sock.user.name } });
      s.data.linked = true; s.save();
    }
    if (connection === 'close') {
      const code = lastDisconnect && lastDisconnect.error && lastDisconnect.error.output && lastDisconnect.error.output.statusCode;
      s.sock = null;
      console.error(`[wa:${u.name}] disconnected code=${code} ${lastDisconnect && lastDisconnect.error ? lastDisconnect.error.message : ''}`);
      if (code === DisconnectReason.loggedOut) {
        fs.rmSync(authDir, { recursive: true, force: true });
        s.data.linked = false; s.save();
        setStatus(s, 'logged_out', { qr: null, me: null });
      } else if (s.status !== 'off') {
        // growing pause between attempts; give up after ~10 failures in a row with a clear status
        s.fails = (s.fails || 0) + 1;
        if (s.fails > 10) { setStatus(s, 'error', { qr: null, error: `WhatsApp не принимает подключение (код ${code}). Попробуйте позже или обновите Stella на сервере.` }); return; }
        setStatus(s, 'reconnecting', { qr: null });
        setTimeout(() => connect(u).catch(e => console.error('wa reconnect', e.message)), Math.min(120000, 3000 * 2 ** (s.fails - 1)));
      }
    }
  });

  sock.ev.on('messaging-history.set', ({ chats, contacts, messages }) => {
    (contacts || []).forEach(c => saveContact(s, c));
    (chats || []).forEach(c => { const ch = chatOf(s, c.id); if (c.name) ch.name = c.name; });
    (messages || []).forEach(m => storeMessage(s, m, true));
    s.save();
  });
  sock.ev.on('contacts.upsert', cs => { cs.forEach(c => saveContact(s, c)); s.save(); });
  sock.ev.on('contacts.update', cs => { cs.forEach(c => saveContact(s, c)); s.save(); });
  sock.ev.on('chats.upsert', cs => { cs.forEach(c => { const ch = chatOf(s, c.id); if (c.name) ch.name = c.name; }); s.save(); });
  sock.ev.on('messages.upsert', ({ messages, type }) => {
    for (const m of messages || []) {
      const rec = storeMessage(s, m, type !== 'notify');
      if (rec && !rec.fromMe && type === 'notify') onIncoming(s, rec);
    }
    s.save();
  });
  return publicStatus(s);
}

async function logout(u) {
  const s = session(u);
  s.status = 'off';
  try { if (s.sock) await s.sock.logout(); } catch {}
  try { if (s.sock) s.sock.end(); } catch {}
  s.sock = null;
  fs.rmSync(path.join(dirOf(u), 'auth'), { recursive: true, force: true });
  s.data.linked = false; s.save();
  setStatus(s, 'off', { qr: null, me: null });
}

// reconnect linked accounts after a server restart
function resumeAll() {
  for (const u of users.all()) {
    const s = session(u);
    if (s.data.linked && fs.existsSync(path.join(dirOf(u), 'auth', 'creds.json'))) connect(u).catch(e => console.error('wa resume', u.name, e.message));
  }
}

/* ------------------------------------------------------------------ */
/* storage                                                              */
/* ------------------------------------------------------------------ */
function chatOf(s, jid) {
  if (!s.data.chats[jid]) s.data.chats[jid] = { jid, name: '', messages: [] };
  return s.data.chats[jid];
}
function saveContact(s, c) {
  if (!c || !c.id) return;
  const prev = s.data.contacts[c.id] || {};
  const rec = Object.assign(prev, { id: c.id });
  for (const k of ['name', 'notify', 'verifiedName', 'lid', 'phoneNumber']) if (c[k]) rec[k] = c[k];
  s.data.contacts[c.id] = rec;
  if (c.lid && c.lid !== c.id) s.data.contacts[c.lid] = Object.assign(s.data.contacts[c.lid] || {}, rec, { id: c.lid });
  if (c.phoneNumber && c.phoneNumber !== c.id) s.data.contacts[c.phoneNumber] = Object.assign(s.data.contacts[c.phoneNumber] || {}, rec, { id: c.phoneNumber });
}
function textOf(msg) {
  const m = msg && msg.message;
  if (!m) return '';
  const inner = m.ephemeralMessage?.message || m.viewOnceMessage?.message || m.viewOnceMessageV2?.message || m;
  return inner.conversation || inner.extendedTextMessage?.text || inner.imageMessage?.caption || inner.videoMessage?.caption ||
    inner.documentMessage?.caption || (inner.audioMessage ? '[голосовое сообщение]' : '') || (inner.stickerMessage ? '[стикер]' : '') ||
    (inner.imageMessage ? '[фото]' : '') || (inner.videoMessage ? '[видео]' : '') || (inner.documentMessage ? '[файл]' : '') || '';
}
function storeMessage(s, m, historic) {
  const jid = m.key && m.key.remoteJid;
  if (!jid || jid === 'status@broadcast' || jid.endsWith('@newsletter')) return null;
  const text = textOf(m);
  if (!text) return null;
  const ch = chatOf(s, jid);
  if (m.key.remoteJidAlt && !ch.alt) ch.alt = m.key.remoteJidAlt;
  if (!m.key.fromMe && m.pushName && !jid.endsWith('@g.us')) {
    const c = s.data.contacts[jid] || (s.data.contacts[jid] = { id: jid });
    if (!c.notify) c.notify = m.pushName;
  }
  const id = m.key.id;
  if (ch.messages.some(x => x.id === id)) return null;
  const ts = Number(m.messageTimestamp || 0) * 1000 || Date.now();
  const rec = { id, fromMe: !!m.key.fromMe, text, ts, sender: m.key.participant || null, senderName: m.key.fromMe ? 'Я' : (m.pushName || null) };
  ch.messages.push(rec);
  if (historic) ch.messages.sort((a, b) => a.ts - b.ts);
  if (ch.messages.length > MAX_PER_CHAT) ch.messages.splice(0, ch.messages.length - MAX_PER_CHAT);
  ch.ts = Math.max(ch.ts || 0, ts);
  return Object.assign({ jid }, rec);
}

function nameOf(s, jid) {
  const ch = s.data.chats[jid];
  const c = s.data.contacts[jid] || (ch && ch.alt && s.data.contacts[ch.alt]) || {};
  return c.name || (ch && ch.name) || c.notify || c.verifiedName || jid.split('@')[0];
}

/* ------------------------------------------------------------------ */
/* queries used by the agent (MCP) and the phone app                    */
/* ------------------------------------------------------------------ */
function listChats(u, query, limit = 30) {
  const s = session(u);
  const q = String(query || '').toLowerCase();
  return Object.values(s.data.chats)
    .map(ch => ({ jid: ch.jid, name: nameOf(s, ch.jid), group: ch.jid.endsWith('@g.us'), ts: ch.ts || 0, last: (ch.messages[ch.messages.length - 1] || {}).text || '', auto: !!s.data.auto[ch.jid] }))
    .filter(c => !q || c.name.toLowerCase().includes(q) || c.jid.includes(q))
    .sort((a, b) => b.ts - a.ts).slice(0, limit);
}

function resolveChat(u, who) {
  const s = session(u);
  who = String(who || '').trim();
  if (!who) throw new Error('contact is required');
  if (/@(s\.whatsapp\.net|g\.us|lid)$/.test(who)) return who;
  const digits = who.replace(/[^\d]/g, '');
  if (digits.length >= 8 && /^[+\d\s()-]+$/.test(who)) {
    const pn = digits + '@s.whatsapp.net';
    const existing = Object.values(s.data.chats).find(ch => ch.jid === pn || ch.alt === pn);
    return existing ? existing.jid : pn;
  }
  const q = who.toLowerCase();
  const cands = Object.values(s.data.chats).filter(ch => !ch.jid.endsWith('@g.us') || true)
    .map(ch => ({ jid: ch.jid, name: nameOf(s, ch.jid), ts: ch.ts || 0 }))
    .filter(c => c.name.toLowerCase().includes(q));
  // also contacts without a chat yet
  for (const c of Object.values(s.data.contacts)) {
    const n = (c.name || c.notify || '').toLowerCase();
    if (n.includes(q) && !cands.some(x => x.jid === c.id) && /@(s\.whatsapp\.net|lid)$/.test(c.id)) cands.push({ jid: c.id, name: c.name || c.notify, ts: 0 });
  }
  if (!cands.length) throw new Error(`Контакт «${who}» не найден. Используйте list_chats, чтобы посмотреть имена.`);
  const exact = cands.filter(c => c.name.toLowerCase() === q);
  const pick = (exact.length ? exact : cands).sort((a, b) => b.ts - a.ts);
  if (pick.length > 1 && !exact.length && pick[0].ts === 0) throw new Error('Несколько контактов подходят: ' + pick.slice(0, 6).map(c => c.name).join(', '));
  return pick[0].jid;
}

function readChat(u, who, limit = 40) {
  const s = session(u);
  const jid = resolveChat(u, who);
  const ch = s.data.chats[jid] || { messages: [] };
  return { jid, name: nameOf(s, jid), messages: ch.messages.slice(-Math.min(200, limit)).map(m => ({ from: m.fromMe ? 'me' : (m.senderName || nameOf(s, jid)), text: m.text, time: new Date(m.ts).toISOString() })) };
}

// samples of how the user writes (to imitate their style)
function styleSamples(u, who, limit = 60) {
  const s = session(u);
  let pool = [];
  if (who) { try { const jid = resolveChat(u, who); pool = (s.data.chats[jid]?.messages || []).filter(m => m.fromMe); } catch {} }
  if (pool.length < limit) {
    const all = Object.values(s.data.chats).filter(ch => !ch.jid.endsWith('@g.us')).flatMap(ch => ch.messages.filter(m => m.fromMe));
    all.sort((a, b) => b.ts - a.ts);
    pool = pool.concat(all.slice(0, limit * 2));
  }
  const seen = new Set();
  return pool.filter(m => m.text && !m.text.startsWith('[') && !seen.has(m.text) && seen.add(m.text)).slice(-limit).map(m => m.text);
}

async function sendText(u, who, text, opts = {}) {
  const s = session(u);
  if (!s.sock || s.status !== 'connected') throw new Error('WhatsApp не подключён. Подключите его во вкладке WhatsApp в приложении Stella.');
  const jid = resolveChat(u, who);
  text = String(text || '').trim();
  if (!text) throw new Error('empty message');
  const sent = await s.sock.sendMessage(jid, { text });
  storeMessage(s, Object.assign({}, sent, { message: { conversation: text } }), false);
  s.save();
  const name = nameOf(s, jid);
  emit(u.name, { t: 'wa.sent', jid, name, text, auto: !!opts.auto });
  if (opts.expectReply !== false && !opts.auto) {
    const origin = opts.origin || agent.lastOrigin.get(u.name) || null;
    s.pending.push({ jid, name, since: Date.now(), origin });
    s.pending = s.pending.filter(p => Date.now() - p.since < 24 * 3600 * 1000).slice(-50);
  }
  return { jid, name, sent: true };
}

// long-poll: next incoming message from that chat
function waitForReply(u, who, timeoutSec = 300) {
  const s = session(u);
  const jid = resolveChat(u, who);
  return new Promise(resolve => {
    const w = { jid, resolve, timer: setTimeout(() => { s.waiters = s.waiters.filter(x => x !== w); resolve(null); }, Math.min(900, timeoutSec) * 1000) };
    s.waiters.push(w);
  });
}

/* ------------------------------------------------------------------ */
/* incoming messages: forward replies, waiters, auto-responder          */
/* ------------------------------------------------------------------ */
function onIncoming(s, rec) {
  const u = s.u;
  const jid = rec.jid;
  const name = nameOf(s, jid);
  // agent waiting inside a run
  s.waiters.filter(w => w.jid === jid).forEach(w => { clearTimeout(w.timer); w.resolve({ from: name, text: rec.text, time: new Date(rec.ts).toISOString() }); });
  s.waiters = s.waiters.filter(w => w.jid !== jid);
  // the user asked the agent to message this person -> forward the answer to the user's devices
  const pend = s.pending.filter(p => p.jid === jid);
  if (pend.length) {
    s.pending = s.pending.filter(p => p.jid !== jid);
    const origin = pend[pend.length - 1].origin;
    const note = `📩 **${name}** ответил(а) в WhatsApp:\n\n> ${rec.text.replace(/\n/g, '\n> ')}`;
    emit(u.name, { t: 'wa.reply', jid, name, text: rec.text, origin });
    emit(u.name, { t: 'notify', title: `${name} ответил(а)`, body: rec.text.slice(0, 140), where: origin && origin.where, chatId: origin && origin.chatId });
    if (origin && origin.where === 'server') agent.addNote(u, origin.chatId, note);
  }
  if (s.data.auto[jid]) scheduleAutoReply(s, jid);
}

function setAuto(u, jid, on) {
  const s = session(u);
  if (on) s.data.auto[jid] = { since: Date.now() }; else delete s.data.auto[jid];
  s.save();
  return listChats(u, '', 200).find(c => c.jid === jid) || null;
}

function scheduleAutoReply(s, jid) {
  clearTimeout(s.autoTimers.get(jid));
  // wait a little so several short messages in a row get one answer
  s.autoTimers.set(jid, setTimeout(() => autoReply(s, jid).catch(e => logAuto(s, jid, null, 'Ошибка: ' + e.message)), 15000));
}

async function autoReply(s, jid) {
  const u = s.u;
  if (!s.data.auto[jid] || s.status !== 'connected') return;
  const day = new Date().toISOString().slice(0, 10);
  const key = day + jid;
  s.autoCount[key] = (s.autoCount[key] || 0) + 1;
  if (s.autoCount[key] > 40) return logAuto(s, jid, null, 'Пропущено: лимит 40 автоответов в день для этого чата');
  const ch = s.data.chats[jid];
  const last = ch.messages[ch.messages.length - 1];
  if (!last || last.fromMe) return;
  const name = nameOf(s, jid);
  const samples = styleSamples(u, jid, 50);
  const history = ch.messages.slice(-30).map(m => (m.fromMe ? 'ME: ' : `${m.senderName || name}: `) + m.text).join('\n');
  const prompt =
    'You are writing a WhatsApp reply AS the user (the account owner), to their contact "' + name + '".\n' +
    'Imitate the user\'s own writing style exactly: language, length, punctuation, emoji use, slang, capitalization. Examples of messages the user wrote:\n' +
    samples.map(x => '- ' + x.replace(/\n/g, ' ')).join('\n') +
    '\n\nRecent conversation (ME = the user):\n' + history +
    '\n\nWrite ONLY the text of the next message from ME. No quotes, no explanations. ' +
    'If no reply is needed, or the message needs a real decision/information only the user has (money, meetings, personal facts you do not know), output exactly NO_REPLY.';
  const out = (await agent.runOnce(u, prompt, 120000)).trim();
  if (!out || /^NO_REPLY\b/.test(out)) return logAuto(s, jid, null, 'Не ответил (нужно решение пользователя)');
  // the contact may have written again or the user may have answered meanwhile
  const now = s.data.chats[jid].messages;
  if (now[now.length - 1].fromMe) return logAuto(s, jid, null, 'Пропущено: вы уже ответили сами');
  await sendText(u, jid, out, { auto: true, expectReply: false });
  logAuto(s, jid, out, 'Отправлено');
}

function logAuto(s, jid, text, status) {
  const rec = { ts: Date.now(), jid, name: nameOf(s, jid), text, status };
  s.data.autoLog.push(rec);
  if (s.data.autoLog.length > 200) s.data.autoLog.splice(0, s.data.autoLog.length - 200);
  s.save();
  emit(s.u.name, { t: 'wa.auto', entry: rec });
}

function overview(u) {
  const s = session(u);
  return Object.assign(publicStatus(s), { chats: listChats(u, '', 60), autoLog: s.data.autoLog.slice(-40).reverse() });
}

// create a WhatsApp group with the given contacts (only when the user asked)
async function createGroup(u, name, contacts) {
  const s = session(u);
  if (!s.sock || s.status !== 'connected') throw new Error('WhatsApp не подключён');
  name = String(name || '').trim().slice(0, 100);
  if (!name) throw new Error('group name required');
  const jids = [...new Set((contacts || []).slice(0, 100).map(c => resolveChat(u, c)).filter(j => !j.endsWith('@g.us')))];
  if (!jids.length) throw new Error('Не найдено ни одного контакта');
  const g = await s.sock.groupCreate(name, jids);
  chatOf(s, g.id).name = name; s.save();
  emit(u.name, { t: 'notify', title: '👥 Группа создана', body: `${name} · ${jids.length} участн.` });
  return { group: name, jid: g.id, members: jids.length };
}
// the same message to several people, paced (2–5 s) to look human and avoid bans; max 30 per call
async function broadcast(u, contacts, text) {
  const s = session(u);
  if (!s.sock || s.status !== 'connected') throw new Error('WhatsApp не подключён');
  text = String(text || '').trim(); if (!text) throw new Error('text required');
  const list = [...new Set((contacts || []).slice(0, 30))];
  const out = [];
  for (const c of list) {
    try { const r = await sendText(u, c, text, { expectReply: true }); out.push({ to: r.name, sent: true }); }
    catch (e) { out.push({ to: c, sent: false, error: e.message }); }
    await new Promise(r => setTimeout(r, 2000 + Math.random() * 3000));
  }
  return { sent: out.filter(x => x.sent).length, total: list.length, details: out };
}

module.exports = { createGroup, broadcast, _test: { session, storeMessage, onIncoming, autoReply }, setup, connect, logout, resumeAll, listChats, readChat, styleSamples, sendText, waitForReply, setAuto, overview, resolveChat };

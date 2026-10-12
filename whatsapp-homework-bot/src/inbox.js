// Переписка с ботом для панели: личные чаты учеников с ботом (целиком) и в группах — только то,
// что обращено к боту, и ответы бота. Хранится в data/chats.json (права 600), старое удаляется.
// Ученики об этом знают: в первом сообщении в личке бот предупреждает, что переписку видит админ класса.
import { EventEmitter } from 'node:events';
import path from 'node:path';
import { readJsonFile, writeJsonFile } from './settings.js';

const MAX_CHATS = 400;
const MAX_MESSAGES = 200;
const KEEP_DAYS = 60;
const TAKEOVER_MS = 30 * 60 * 1000; // админ ответил сам — ИИ молчит в этом чате полчаса

export const isPrivateJid = (jid) => /@(s\.whatsapp\.net|lid)$/.test(String(jid || ''));

// Короткое описание содержимого сообщения: текст, подпись к фото, имя файла
export function contentSummary(content = {}) {
  if (typeof content.text === 'string') return { text: content.text };
  if (content.image) return { text: content.caption || '', media: 'image' };
  if (content.document) return { text: content.caption || content.fileName || 'файл', media: 'file' };
  if (content.audio) return { text: '', media: 'voice' };
  return { text: '', media: 'other' };
}

export class Inbox extends EventEmitter {
  constructor({ file, logger }) {
    super();
    this.file = file;
    this.logger = logger;
    this.data = { chats: {} };
    this.timer = null;
  }

  static fromDataDir(dataDir, logger) {
    return new Inbox({ file: dataDir ? path.join(dataDir, 'chats.json') : null, logger });
  }

  load() {
    const saved = this.file ? readJsonFile(this.file, null) : null;
    if (saved?.chats) this.data = saved;
    this.prune();
    return this;
  }

  scheduleSave() {
    if (!this.file || this.timer) return;
    this.timer = setTimeout(() => {
      this.timer = null;
      this.save();
    }, 1000);
    this.timer.unref?.();
  }

  save() {
    if (!this.file) return;
    clearTimeout(this.timer);
    this.timer = null;
    try {
      writeJsonFile(this.file, this.data, 0o600);
    } catch (error) {
      this.logger?.error({ err: error.message }, 'Не удалось сохранить переписку');
    }
  }

  chatEntry(jid, { name, isGroup } = {}) {
    let chat = this.data.chats[jid];
    if (!chat) {
      chat = { jid, name: name || '', isGroup: Boolean(isGroup), phone: '', unread: 0, lastAt: 0, ai: 'on', aiPausedUntil: 0, messages: [] };
      this.data.chats[jid] = chat;
    }
    if (name && (!chat.name || !chat.isGroup)) chat.name = name;
    return chat;
  }

  // Новый собеседник (ещё ни одного сообщения) — для приветствия в личке
  isNew(jid) {
    return !this.data.chats[jid]?.messages?.length;
  }

  // dir: 'in' — от человека, 'out' — от бота; by: user | bot | admin
  record(jid, { dir, by = dir === 'in' ? 'user' : 'bot', text = '', media = null, name = '', sender = '', id = null, at = Date.now(), isGroup = jid.endsWith('@g.us'), phone = '' }) {
    const chat = this.chatEntry(jid, { name: dir === 'in' && !isGroup ? name : undefined, isGroup });
    if (phone && !chat.phone) chat.phone = phone;
    if (id && chat.messages.some((m) => m.id === id)) return null;
    const message = { id: id || `${at.toString(36)}${Math.random().toString(36).slice(2, 6)}`, dir, by, text: String(text || '').slice(0, 4000), at };
    if (media) message.media = media;
    if (isGroup && dir === 'in') message.name = name || sender || 'Ученик';
    chat.messages.push(message);
    if (chat.messages.length > MAX_MESSAGES) chat.messages.splice(0, chat.messages.length - MAX_MESSAGES);
    chat.lastAt = at;
    if (dir === 'in') chat.unread += 1;
    this.trim();
    this.scheduleSave();
    this.emit('message', { jid, message, chat: this.summary(chat) });
    return message;
  }

  trim() {
    const jids = Object.keys(this.data.chats);
    if (jids.length <= MAX_CHATS) return;
    jids.sort((a, b) => this.data.chats[a].lastAt - this.data.chats[b].lastAt);
    for (const jid of jids.slice(0, jids.length - MAX_CHATS)) delete this.data.chats[jid];
  }

  prune(now = Date.now()) {
    const cutoff = now - KEEP_DAYS * 86400000;
    for (const [jid, chat] of Object.entries(this.data.chats)) {
      chat.messages = (chat.messages || []).filter((m) => m.at >= cutoff);
      if (!chat.messages.length) delete this.data.chats[jid];
    }
  }

  summary(chat) {
    const last = chat.messages.at(-1);
    return {
      jid: chat.jid,
      name: chat.name || chat.phone || chat.jid.split('@')[0],
      phone: chat.phone || '',
      isGroup: chat.isGroup,
      unread: chat.unread,
      lastAt: chat.lastAt,
      last: last ? { text: last.text, media: last.media || null, dir: last.dir, by: last.by } : null,
      ai: this.aiState(chat.jid),
    };
  }

  list() {
    return Object.values(this.data.chats).sort((a, b) => b.lastAt - a.lastAt).map((c) => this.summary(c));
  }

  get(jid, { limit = MAX_MESSAGES } = {}) {
    const chat = this.data.chats[jid];
    if (!chat) return null;
    return { ...this.summary(chat), messages: chat.messages.slice(-limit) };
  }

  markRead(jid) {
    const chat = this.data.chats[jid];
    if (!chat || !chat.unread) return;
    chat.unread = 0;
    this.scheduleSave();
    this.emit('read', { jid });
  }

  unreadTotal() {
    return Object.values(this.data.chats).reduce((sum, c) => sum + (c.unread || 0), 0);
  }

  // ИИ в чате: 'on' | 'off' | 'paused' (админ ответил сам — ИИ ждёт)
  aiState(jid) {
    const chat = this.data.chats[jid];
    if (!chat) return 'on';
    if (chat.ai === 'off') return 'off';
    if (chat.aiPausedUntil > Date.now()) return 'paused';
    return 'on';
  }

  aiAllowed(jid) {
    return this.aiState(jid) === 'on';
  }

  setAi(jid, state) {
    const chat = this.chatEntry(jid);
    chat.ai = state === 'off' ? 'off' : 'on';
    chat.aiPausedUntil = state === 'paused' ? Date.now() + TAKEOVER_MS : 0;
    this.scheduleSave();
    this.emit('chat', this.summary(chat));
  }

  // Админ написал сам — ИИ на время замолкает, чтобы не перебивать
  takeover(jid) {
    const chat = this.chatEntry(jid);
    if (chat.ai !== 'off') chat.aiPausedUntil = Date.now() + TAKEOVER_MS;
    this.scheduleSave();
  }

  // История для ИИ: последние сообщения за сутки
  history(jid, limit = 14) {
    const chat = this.data.chats[jid];
    if (!chat) return [];
    const dayAgo = Date.now() - 24 * 3600 * 1000;
    return chat.messages
      .filter((m) => m.at > dayAgo && (m.text || m.media))
      .slice(-limit)
      .map((m) => ({ name: m.name || chat.name || 'Ученик', text: m.text || (m.media === 'image' ? '[фото]' : m.media === 'voice' ? '[голосовое]' : '[файл]'), fromBot: m.dir === 'out' }));
  }

  remove(jid) {
    delete this.data.chats[jid];
    this.scheduleSave();
  }
}

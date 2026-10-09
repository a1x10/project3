// Вспомогательные функции для тестов: фейковые недели дневника, клиенты, WhatsApp.
import { EventEmitter } from 'node:events';
import { buildConfig } from '../src/config.js';
import { Store } from '../src/store.js';
import { addDays } from '../src/utils/dates.js';

const MONTHS_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];

// spec: { 1: [['Алгебра', '№1'], ['Физкультура', null]], ..., holidays: [5] } — ключ = день недели (1 = пн)
export function rawWeek(mondayIso, spec = {}) {
  const days = [];
  for (let i = 0; i < 7; i += 1) {
    const iso = addDays(mondayIso, i);
    const lessons = spec[i + 1] || [];
    days.push({
      date: `${Number(iso.slice(8, 10))} ${MONTHS_GEN[Number(iso.slice(5, 7)) - 1]}`,
      isHoliday: (spec.holidays || []).includes(i + 1),
      subjects: lessons.map(([label, homework, extra = {}], n) => ({
        label,
        timeslot: `${String(8 + n).padStart(2, '0')}:00 - ${String(8 + n).padStart(2, '0')}:45`,
        homeworkBody: homework,
        ...extra,
      })),
    });
  }
  return { days };
}

export class FakeBilimClient {
  constructor(weeks = {}) {
    this.weeks = weeks; // monday -> raw week
    this.calls = [];
    this.session = { className: '7 «А»', schoolName: 'Школа №1', schoolId: 1, groupId: 2, eduYear: 2025 };
    this.files = {};
    this.fail = null;
  }

  async getWeek(monday) {
    this.calls.push(monday);
    if (this.fail) throw this.fail;
    return this.weeks[monday] || { days: [] };
  }

  async getHomeworkFiles(uuid) {
    return this.files[uuid] || [];
  }
}

export function testConfig(env = {}) {
  return buildConfig({ BOT_TIMEZONE: 'Asia/Almaty', GROQ_API_KEY: 'test-key', DATA_DIR: '/tmp/hw-bot-test-unused', ...env });
}

export function memoryStore() {
  const store = new Store('/dev/null/never-written.json');
  store.scheduleSave = () => {};
  store.save = () => {};
  return store;
}

// "Сейчас" для тестов: вторник 14.10.2025, 10:00 по Алматы
export const TUESDAY_10AM = () => new Date('2025-10-14T10:00:00+05:00');

export class FakeWA extends EventEmitter {
  constructor() {
    super();
    this.sent = [];
    this.isOpen = true;
    this.status = 'open';
    this.me = { id: '77000000000@s.whatsapp.net', lid: '111111111111111@lid', name: 'Бот' };
    this.queue = [];
    this.groups = {};
    this.sock = { signalRepository: { lidMapping: { getPNForLID: async () => null } }, updateMediaMessage: async () => {} };
  }

  async send(jid, content, options = {}) {
    const msg = { key: { id: `BOT${this.sent.length}`, remoteJid: jid, fromMe: true }, message: content };
    this.sent.push({ jid, content, options });
    return msg;
  }

  sendText(jid, text, { quoted } = {}) {
    return this.send(jid, { text }, quoted ? { quoted } : {});
  }

  async typing() {}

  async groupMetadata(jid) {
    if (!this.groups[jid]) throw new Error('no group');
    return this.groups[jid];
  }

  async allGroups() {
    return Object.values(this.groups);
  }

  texts() {
    return this.sent.map((s) => s.content.text).filter(Boolean);
  }
}

// Входящее сообщение в формате Baileys
export function incoming({ chat = '120363000000000001@g.us', sender = '77011112233@s.whatsapp.net', text = '', name = 'Аня', id, contextInfo, ageMs = 0, extra = {} } = {}) {
  const isGroup = chat.endsWith('@g.us');
  const message = contextInfo
    ? { extendedTextMessage: { text, contextInfo } }
    : { conversation: text };
  return {
    key: { remoteJid: chat, id: id || `MSG${Math.random().toString(36).slice(2)}`, fromMe: false, ...(isGroup ? { participant: sender } : {}) },
    message: { ...message, ...extra },
    pushName: name,
    messageTimestamp: Math.floor((Date.now() - ageMs) / 1000),
  };
}

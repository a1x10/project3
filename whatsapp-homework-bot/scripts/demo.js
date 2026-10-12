// Демо-режим: сайт и панель управления на примерных данных — без WhatsApp, BilimClass и ключей.
// Удобно показать проект (портфолио, презентация) или посмотреть панель до настройки бота.
//   npm run demo            → http://localhost:3100  (пароль панели: demo-panel)
import { EventEmitter } from 'node:events';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { Assistant } from '../src/ai/assistant.js';
import { BackupAi, KeyRing } from '../src/ai/keys.js';
import { buildConfig } from '../src/config.js';
import { BotCore } from '../src/core.js';
import { HomeworkPhotos } from '../src/homework/message.js';
import { HomeworkService } from '../src/homework/service.js';
import { contentSummary, Inbox } from '../src/inbox.js';
import { createLogger, logBuffer } from '../src/logger.js';
import { Scheduler } from '../src/scheduler.js';
import { SecretStore } from '../src/secrets.js';
import { Settings } from '../src/settings.js';
import { Store } from '../src/store.js';
import { addDays, mondayOf, nowParts } from '../src/utils/dates.js';
import { PanelAuth } from '../src/web/auth.js';
import { startWebServer } from '../src/web/server.js';

const PORT = Number(process.env.DEMO_PORT || 3100);
const PASSWORD = process.env.DEMO_PASSWORD || 'demo-panel';
const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hwbot-demo-'));
const config = buildConfig({
  DATA_DIR: dataDir, HTTP_PORT: String(PORT), HTTP_HOST: process.env.DEMO_HOST || '127.0.0.1', ADMIN_PANEL_PASSWORD: PASSWORD,
  ADMIN_NUMBERS: '77070000000', BOT_NAME: 'Бот ДЗ', HOMEWORK_PHOTO: 'card', LOG_PRETTY: 'false', BILIM_LOGIN: 'demo', BILIM_PASSWORD: 'demo',
});
const logger = createLogger('info');
const MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];

// --- примерный дневник ---
const PLAN = [
  [['Алгебра', '№ 250–255, стр. 84'], ['Русский язык', 'Упр. 312, выучить правило на с. 96'], ['История Казахстана', 'Параграф 5, выучить даты'], ['Физическая культура', ''], ['Английский язык', 'Ex. 4 p. 37, new words']],
  [['Физика', '§ 12, ответить на вопросы 1–4'], ['Геометрия', '№ 112, 115'], ['Казахский язык', 'Мәтінді оқу, 5-жаттығу'], ['Литература', 'Читать «Капитанская дочка», гл. 3–4']],
  [['Алгебра', '№ 260, 262 (а, б)'], ['Биология', '§ 9, таблица в тетради'], ['Информатика', 'Презентация «Алгоритмы»'], ['Русский язык', 'Упр. 318']],
  [['Химия', '§ 7, задачи 1–3'], ['География', 'Контурная карта, с. 12'], ['Английский язык', 'WB p. 22'], ['Музыка', '']],
  [['Геометрия', 'Подготовиться к СОР'], ['Литература', 'Выучить стихотворение'], ['Физика', 'Лаб. работа №3 — оформить'], ['Самопознание', '']],
];
class DemoDiary {
  constructor() {
    this.session = { className: '7 «В»', schoolName: 'Школа-лицей №70', fullName: 'Демо Ученик', eduYear: 2026 };
    this.loggedIn = true;
  }

  async getWeek(monday) {
    const days = [];
    const shift = Number(monday.slice(8, 10)) % 3;
    for (let i = 0; i < 7; i += 1) {
      const iso = addDays(monday, i);
      const lessons = i < 5 ? PLAN[(i + shift) % 5] : [];
      days.push({
        date: `${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]}`,
        isHoliday: false,
        subjects: lessons.map(([label, hw], n) => ({ label, timeslot: `${String(8 + n).padStart(2, '0')}:${n % 2 ? '55' : '00'} - ${String(8 + n).padStart(2, '0')}:${n % 2 ? '40' : '45'}`, homeworkBody: hw || null })),
      });
    }
    return { days };
  }

  async getHomeworkFiles() {
    return [];
  }

  status() {
    return { mode: 'api', siteAvailable: true, apiError: null };
  }

  setCredentials() {}
  async login() {
    return this.session;
  }
}

// --- WhatsApp «понарошку» ---
class DemoWA extends EventEmitter {
  constructor() {
    super();
    this.status = 'open';
    this.me = { id: '77071234567@s.whatsapp.net', name: 'Бот ДЗ' };
    this.queue = [];
    this.connectedSince = Date.now() - 3 * 86400000;
    this.lastDisconnect = { code: 428, at: Date.now() - 2 * 86400000 };
    this.qr = null;
    this.pairingCode = null;
    this.sock = null;
  }

  get isOpen() {
    return this.status === 'open';
  }

  async send(jid, content, options = {}, { meta = null } = {}) {
    const id = `DEMO${Date.now()}${Math.random().toString(36).slice(2, 6)}`;
    setTimeout(() => this.emit('sent', { jid, content, meta, id, at: Date.now() }), 300);
    logger.child({ module: 'wa' }).info({ jid: jid.split('@')[0] }, 'Демо: сообщение «отправлено»');
    return { key: { id } };
  }

  sendText(jid, text, { meta } = {}) {
    return this.send(jid, { text }, {}, { meta });
  }

  async typing() {}
  async markRead() {}
  async groupMetadata() {
    return { id: GROUP, subject: '7 «В» класс', participants: Array.from({ length: 27 }, (_, i) => ({ id: `7700000${String(i).padStart(4, '0')}@s.whatsapp.net` })) };
  }

  async allGroups() {
    return [await this.groupMetadata(), { id: '120363000000000222@g.us', subject: 'Родители 7В', participants: [] }];
  }

  async qrDataUrl() {
    return null;
  }

  info() {
    return { status: this.status, me: this.me, qr: false, pairingCode: this.pairingCode, pairingNumber: '', connectedSince: this.connectedSince, lastDisconnect: this.lastDisconnect, queue: 0 };
  }

  reconnect() {
    this.status = 'closed';
    this.emit('state');
    setTimeout(() => {
      this.status = 'open';
      this.connectedSince = Date.now();
      this.emit('state');
    }, 1500);
  }

  async relink() {
    this.status = 'qr';
    this.pairingCode = 'DEMO-2026';
    this.emit('state');
  }
}

// --- ИИ «понарошку» ---
class DemoGroq {
  constructor() {
    this.hasKey = true;
  }

  async chat({ messages, json }) {
    if (json) return { text: '{"respond": true}', model: 'demo' };
    const last = messages.at(-1).content;
    const q = typeof last === 'string' ? last : '';
    await new Promise((r) => setTimeout(r, 600));
    return {
      model: 'demo',
      text: /250/.test(q)
        ? 'Смотри: в №250 система из двух уравнений. Выразим y из первого: y = 7 − 2x, подставим во второе и найдём x. Попробуй сам, а я проверю 😉'
        : 'Это демо-режим, поэтому отвечаю заготовкой 🙂 В настоящем боте здесь будет ответ ИИ с учётом ДЗ из дневника.',
    };
  }

  async testKey() {
    return { ok: true, models: ['demo'] };
  }
}

const GROUP = '120363000000000111@g.us';
const store = new Store(path.join(dataDir, 'state.json'), logger).load();
const settings = new Settings({ config, logger }).load();
const secrets = new SecretStore(path.join(dataDir, 'secrets.json'), logger).load();
const diary = new DemoDiary();
const homework = new HomeworkService({ client: diary, store, config, logger: logger.child({ module: 'homework' }) });
const wa = new DemoWA();
const core = new BotCore({ config, store, wa, logger });
const keys = new KeyRing({ secrets, envKey: 'gsk_demo_key_0000000000000000000000000000ab12', logger }).load();
keys.add({ key: 'gsk_reserve_key_000000000000000000000000cd34', label: 'Запасной ключ' });
const backup = new BackupAi({ secrets, logger });
const groq = new DemoGroq();
const assistant = new Assistant({ groq, homework, config, backup, logger });
core.assistant = assistant;
const inbox = new Inbox({ file: null, logger });
wa.on('sent', ({ jid, content, meta, id, at }) => inbox.record(jid, { dir: 'out', by: meta?.by || 'bot', ...contentSummary(content), id, at }));
const photos = new HomeworkPhotos({ config, logger, className: () => diary.session.className });
const scheduler = new Scheduler({ config, store, homework, wa, core, photos, logger: logger.child({ module: 'scheduler' }) });
const auth = new PanelAuth({ config, secrets, core, logger });

// --- примерная история ---
store.update((s) => {
  s.groups[GROUP] = { name: '7 «В» класс', boundAt: Date.now() - 20 * 86400000, ai: true, digest: true };
  s.announcedReady = true;
  const today = nowParts(config.timezone).iso;
  for (let i = 0; i < 14; i += 1) {
    const date = addDays(today, -i);
    const weekend = [6, 7].includes(nowParts(config.timezone, new Date(`${date}T12:00:00Z`)).weekday);
    s.usage[date] = { ai: weekend ? 4 + (i % 3) : 14 + ((i * 7) % 11), dm: weekend ? 2 : 6 + ((i * 5) % 7), digest: weekend ? 0 : 1, voice: i % 3, vision: i % 2 };
  }
  s.jobs.digest = addDays(today, -1);
  s.alertLog = [
    { id: 'a1', key: 'bilim-recovered', text: '✅ Связь с BilimClass восстановлена.', level: 'ok', at: Date.now() - 26 * 3600000 },
    { id: 'a2', key: 'bilim-site-mode', text: 'API BilimClass сбоит (HTTP 426). Беру дневник через сайт — бот работает дальше.', level: 'warn', at: Date.now() - 27 * 3600000 },
    { id: 'a3', key: 'wa-recovered', text: '✅ WhatsApp снова на связи (не было 7 мин). Сообщения из очереди отправлены.', level: 'ok', at: Date.now() - 3 * 86400000 },
  ];
});
const ANYA = '77011112233@s.whatsapp.net';
const DAMIR = '77012223344@s.whatsapp.net';
const minutesAgo = (m) => Date.now() - m * 60000;
const seed = [
  [ANYA, 'in', 'user', 'привет! что задали на завтра?', 95, 'Аня Смирнова'],
  [ANYA, 'out', 'bot', '📚 Домашнее задание на завтра', 94, null, 'image'],
  [ANYA, 'in', 'user', 'а как решить номер 250?', 52, 'Аня Смирнова'],
  [ANYA, 'out', 'bot', 'Смотри: это система из двух уравнений. Выразим y из первого: y = 7 − 2x и подставим во второе 👇', 51],
  [ANYA, 'in', 'user', 'понятно, спасибо!!', 49, 'Аня Смирнова'],
  [DAMIR, 'in', 'user', 'бот, скинь расписание на пятницу', 31, 'Дамир'],
  [DAMIR, 'out', 'bot', '🗓 Пятница: Геометрия 08:00, Литература 08:55, Физика 10:00, Самопознание 10:55', 30],
  [DAMIR, 'in', 'user', 'а лабу по физике как оформлять?', 4, 'Дамир'],
  [GROUP, 'out', 'bot', '📚 Домашнее задание на завтра', 600, null, 'image'],
  [GROUP, 'in', 'user', 'бот, что по химии?', 380, 'Алия'],
  [GROUP, 'out', 'bot', 'По химии на четверг: § 7, задачи 1–3 🧪', 379],
];
for (const [jid, dir, by, text, ago, name, media] of seed) {
  inbox.record(jid, { dir, by, text, at: minutesAgo(ago), name: name || '', media: media || null, phone: jid.endsWith('@g.us') ? '' : jid.split('@')[0] });
}
inbox.data.chats[GROUP].name = '7 «В» класс';
inbox.markRead(GROUP);
inbox.markRead(ANYA);

const log = logger.child({ module: 'scheduler' });
log.info('Сегодня рассылка — после уроков');
logger.child({ module: 'bilim' }).info({ class: '7 «В»' }, 'Вход в BilimClass выполнен');
logger.child({ module: 'wa' }).info('✅ WhatsApp подключён');

startWebServer({
  config, logger: logger.child({ module: 'web' }), wa, homework, core, auth, settings, secrets, scheduler, inbox, keys, backup, groq,
  assistant, diary, bilim: diary, siteBrowser: null, logBuffer, restart: () => logger.warn('Демо: перезапуск'),
});
await scheduler.digestPlan(nowParts(config.timezone));
// живость: время от времени «приходят» сообщения и записи журнала
setInterval(() => {
  logger.child({ module: 'scheduler' }).info('Проверка дневника: новых ДЗ нет');
}, 45000).unref();
console.log(`\nДемо-панель: http://localhost:${PORT}  ·  пароль: ${PASSWORD}\n`);

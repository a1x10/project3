// Подключение к WhatsApp через Baileys: вход по QR или коду, автопереподключение,
// очередь отправки (сообщения не теряются при обрывах связи), кэш данных групп.
import { EventEmitter } from 'node:events';
import fs from 'node:fs';
import makeWASocket, {
  Browsers,
  DisconnectReason,
  fetchLatestBaileysVersion,
  isJidBroadcast,
  isJidNewsletter,
  jidNormalizedUser,
  makeCacheableSignalKeyStore,
  useMultiFileAuthState,
} from 'baileys';
import QRCode from 'qrcode';

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const GROUP_CACHE_MS = 10 * 60 * 1000;

export class WhatsAppConnection extends EventEmitter {
  constructor({ config, store, logger, socketOptions = {} }) {
    super();
    this.socketOptions = socketOptions; // доп. параметры Baileys (например, agent для прокси)
    this.setMaxListeners(50);
    this.config = config;
    this.store = store;
    this.logger = logger;
    this.sock = null;
    this.status = 'starting'; // starting | qr | open | closed | loggedOut
    this.qr = null;
    this.pairingCode = null;
    this.me = null; // { id, lid, name }
    this.retries = 0;
    this.stopped = false;
    this.connectedSince = 0;
    this.lastDisconnect = null;
    this.groupCache = new Map(); // jid -> { at, meta }
    this.sentMessages = new Map(); // id -> message (для повторной отправки по запросу WhatsApp)
    this.queue = [];
    this.pumping = false;
    this.version = null;
  }

  get isOpen() {
    return this.status === 'open' && Boolean(this.sock);
  }

  async start() {
    fs.mkdirSync(this.config.whatsapp.authDir, { recursive: true });
    // Восстанавливаем неотправленные важные сообщения (например, рассылку перед перезапуском)
    for (const item of this.store.data.outbox) {
      this.queue.push({ ...item, content: { text: item.text }, options: {}, resolve: () => {}, reject: () => {}, attempts: 0 });
    }
    try {
      const { version } = await Promise.race([fetchLatestBaileysVersion(), sleep(10000).then(() => ({}))]);
      this.version = version || null;
    } catch {
      this.version = null;
    }
    await this.connect();
    this.pump();
  }

  async connect() {
    if (this.stopped) return;
    const { state, saveCreds } = await useMultiFileAuthState(this.config.whatsapp.authDir);
    const waLogger = this.logger.child({ module: 'baileys' });
    waLogger.level = process.env.WA_LOG_LEVEL || 'error';

    const sock = makeWASocket({
      ...(this.version ? { version: this.version } : {}),
      auth: { creds: state.creds, keys: makeCacheableSignalKeyStore(state.keys, waLogger) },
      logger: waLogger,
      browser: Browsers.ubuntu('Chrome'),
      markOnlineOnConnect: false,
      syncFullHistory: false,
      generateHighQualityLinkPreview: false,
      shouldIgnoreJid: (jid) => isJidBroadcast(jid) || isJidNewsletter(jid),
      cachedGroupMetadata: async (jid) => this.groupCache.get(jid)?.meta,
      getMessage: async (key) => this.sentMessages.get(key.id),
      ...this.socketOptions,
    });
    this.sock = sock;
    this.pairingRequested = false;

    sock.ev.on('creds.update', saveCreds);
    sock.ev.on('connection.update', (update) => this.onConnectionUpdate(sock, update).catch((err) => this.logger.error({ err }, 'connection.update')));
    sock.ev.on('messages.upsert', ({ messages, type }) => {
      if (type !== 'notify') return;
      for (const msg of messages) this.emit('message', msg);
    });
    sock.ev.on('groups.update', (updates) => {
      for (const u of updates) this.groupCache.delete(u.id);
    });
    sock.ev.on('group-participants.update', (event) => {
      this.groupCache.delete(event.id);
      this.emit('participants', event);
    });
  }

  async onConnectionUpdate(sock, { connection, lastDisconnect, qr }) {
    if (sock !== this.sock) return; // событие от старого сокета

    if (qr) {
      const { pairingNumber } = this.config.whatsapp;
      if (pairingNumber && !sock.authState.creds.registered) {
        if (!this.pairingRequested) {
          this.pairingRequested = true;
          try {
            const code = await sock.requestPairingCode(pairingNumber);
            this.pairingCode = code?.match(/.{1,4}/g)?.join('-') || code;
            this.status = 'qr';
            // печатаем напрямую в консоль, чтобы код было легко увидеть в логах
            console.log(
              `\n========================================\n` +
                `  КОД ДЛЯ ПРИВЯЗКИ WHATSAPP: ${this.pairingCode}\n` +
                `  Телефон бота → WhatsApp → Связанные устройства → Привязка устройства →\n` +
                `  «Привязать по номеру телефона» → введите код.\n` +
                `========================================\n`,
            );
            this.logger.warn({ code: this.pairingCode }, 'Ожидаю привязку WhatsApp по коду');
          } catch (error) {
            this.logger.error({ err: error.message }, 'Не удалось получить код привязки — используйте QR-код');
          }
        }
      } else {
        this.qr = qr;
        this.status = 'qr';
        const terminalQr = await QRCode.toString(qr, { type: 'terminal', small: true });
        console.log(
          `\nОтсканируйте QR-код в WhatsApp на телефоне бота: Настройки → Связанные устройства → Привязка устройства\n${terminalQr}` +
            (this.config.http.token ? `QR также доступен в браузере: http://<сервер>:${this.config.http.port}/qr?token=<HTTP_TOKEN>\n` : ''),
        );
        this.logger.warn('Ожидаю привязку WhatsApp: отсканируйте QR-код выше (он обновляется каждые ~20 секунд)');
      }
    }

    if (connection === 'open') {
      this.status = 'open';
      this.qr = null;
      this.pairingCode = null;
      this.retries = 0;
      this.connectedSince = Date.now();
      const user = sock.user || {};
      this.me = { id: jidNormalizedUser(user.id), lid: user.lid ? jidNormalizedUser(user.lid) : null, name: user.name || '' };
      this.logger.info({ me: this.me.id }, '✅ WhatsApp подключён');
      this.emit('open');
      this.pump();
      return;
    }

    if (connection === 'close') {
      this.status = 'closed';
      const code = lastDisconnect?.error?.output?.statusCode;
      this.lastDisconnect = { code, at: Date.now(), message: lastDisconnect?.error?.message };
      this.emit('close', code);
      if (this.stopped) return;

      if (code === DisconnectReason.loggedOut) {
        // сессию отвязали на телефоне — убираем старые ключи и показываем новый QR
        this.status = 'loggedOut';
        const backup = `${this.config.whatsapp.authDir}.logged-out-${Date.now()}`;
        try {
          fs.renameSync(this.config.whatsapp.authDir, backup);
        } catch {
          /* ничего страшного */
        }
        this.logger.error('WhatsApp: бот отвязан от телефона (logged out). Нужна новая привязка — смотрите QR/код ниже.');
        this.emit('loggedOut');
        this.scheduleReconnect(3000);
        return;
      }

      let delay;
      if (code === DisconnectReason.restartRequired) delay = 500;
      else if (code === DisconnectReason.connectionReplaced) {
        delay = 60000;
        this.logger.error('WhatsApp: сессия открыта в другом месте (запущены две копии бота?). Повтор через минуту.');
      } else if (code === DisconnectReason.forbidden) {
        delay = 5 * 60000;
        this.logger.error('WhatsApp: доступ запрещён (403) — номер мог быть заблокирован. Повтор через 5 минут.');
      } else {
        this.retries += 1;
        delay = Math.min(60000, 2000 * 2 ** Math.min(this.retries - 1, 5));
      }
      if (code !== DisconnectReason.restartRequired) {
        this.logger.warn({ code, retryInSec: Math.round(delay / 1000) }, 'WhatsApp: соединение закрыто, переподключаюсь');
      }
      this.scheduleReconnect(delay);
    }
  }

  // Переподключение не должно «умереть» из-за ошибки внутри connect()
  scheduleReconnect(delay) {
    clearTimeout(this.reconnectTimer);
    this.reconnectTimer = setTimeout(async () => {
      try {
        await this.connect();
      } catch (error) {
        this.logger.error({ err: error.message }, 'Не удалось переподключиться к WhatsApp — повтор через 30 с');
        this.scheduleReconnect(30000);
      }
    }, delay);
  }

  waitOpen() {
    if (this.isOpen) return Promise.resolve();
    return new Promise((resolve) => this.once('open', resolve));
  }

  // Поставить сообщение в очередь. persist — сохранить на диск до отправки (для рассылок).
  send(jid, content, options = {}, { persist = false, maxAgeMs = 6 * 3600 * 1000 } = {}) {
    return new Promise((resolve, reject) => {
      const item = { id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, jid, content, options, resolve, reject, attempts: 0, createdAt: Date.now(), maxAgeMs };
      if (persist && typeof content.text === 'string') {
        item.persisted = true;
        this.store.update((s) => s.outbox.push({ id: item.id, jid, text: content.text, createdAt: item.createdAt, maxAgeMs }));
      }
      this.queue.push(item);
      this.pump();
    });
  }

  sendText(jid, text, { quoted, mentions, persist, maxAgeMs } = {}) {
    return this.send(jid, { text, ...(mentions?.length ? { mentions } : {}) }, quoted ? { quoted } : {}, { persist, maxAgeMs });
  }

  dropFromOutbox(item) {
    if (!item.persisted && !this.store.data.outbox.some((o) => o.id === item.id)) return;
    this.store.update((s) => {
      s.outbox = s.outbox.filter((o) => o.id !== item.id);
    });
  }

  async pump() {
    if (this.pumping) return;
    this.pumping = true;
    try {
      while (this.queue.length && !this.stopped) {
        await this.waitOpen();
        const item = this.queue[0];
        if (Date.now() - item.createdAt > (item.maxAgeMs ?? 6 * 3600 * 1000)) {
          this.queue.shift();
          this.dropFromOutbox(item);
          this.logger.warn({ jid: item.jid }, 'Сообщение устарело и не отправлено');
          item.resolve(null);
          continue;
        }
        try {
          const sent = await this.sock.sendMessage(item.jid, item.content, item.options);
          if (sent?.key?.id) {
            this.sentMessages.set(sent.key.id, sent.message);
            if (this.sentMessages.size > 300) this.sentMessages.delete(this.sentMessages.keys().next().value);
          }
          this.queue.shift();
          this.dropFromOutbox(item);
          item.resolve(sent);
        } catch (error) {
          // связь пропала во время отправки — ждём переподключения, попытку не засчитываем
          if (!this.isOpen) continue;
          item.attempts += 1;
          this.logger.warn({ err: error.message, attempt: item.attempts, jid: item.jid }, 'Ошибка отправки сообщения');
          if (item.attempts >= 3) {
            this.queue.shift();
            this.dropFromOutbox(item);
            item.reject(error);
          } else {
            await sleep(3000 * item.attempts);
          }
        }
        await sleep(this.config.whatsapp.sendDelayMs);
      }
    } finally {
      this.pumping = false;
    }
  }

  async typing(jid, on = true) {
    if (!this.isOpen) return;
    try {
      await this.sock.sendPresenceUpdate(on ? 'composing' : 'paused', jid);
    } catch {
      /* не критично */
    }
  }

  async groupMetadata(jid, { fresh = false } = {}) {
    const cached = this.groupCache.get(jid);
    if (!fresh && cached && Date.now() - cached.at < GROUP_CACHE_MS) return cached.meta;
    const meta = await this.sock.groupMetadata(jid);
    this.groupCache.set(jid, { at: Date.now(), meta });
    return meta;
  }

  async allGroups() {
    const groups = await this.sock.groupFetchAllParticipating();
    for (const [jid, meta] of Object.entries(groups)) this.groupCache.set(jid, { at: Date.now(), meta });
    return Object.values(groups);
  }

  async qrDataUrl() {
    return this.qr ? QRCode.toDataURL(this.qr, { margin: 2, width: 360 }) : null;
  }

  // Сообщение отправлено этим ботом (а не владельцем номера с телефона)
  isOwnSent(id) {
    return this.sentMessages.has(id);
  }

  async stop() {
    this.stopped = true;
    clearTimeout(this.reconnectTimer);
    try {
      this.sock?.end(undefined);
    } catch {
      /* уже закрыт */
    }
  }
}

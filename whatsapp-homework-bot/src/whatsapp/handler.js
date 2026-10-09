// Обработка входящих сообщений: команды и ответы ИИ на вопросы по ДЗ.
import { downloadMediaMessage } from 'baileys';
import { BilimAuthError } from '../bilimclass/client.js';
import { errText } from '../logger.js';
import { RateLimiter } from '../utils/ratelimit.js';
import { parseCommand } from './commands.js';
import { isBotJid } from './identity.js';
import { parseMessage } from './message.js';

const MAX_MESSAGE_AGE_MS = 3 * 60 * 1000; // старые сообщения (пришедшие после переподключения) не обрабатываем
const MAX_IMAGE_BYTES = 4 * 1024 * 1024;

export class MessageHandler {
  constructor({ config, core, wa, homework, assistant, commands, logger }) {
    this.config = config;
    this.core = core;
    this.wa = wa;
    this.homework = homework;
    this.assistant = assistant;
    this.commands = commands;
    this.logger = logger;
    this.seen = new Set();
    this.history = new Map(); // chat -> [{ name, text, fromBot, at }]
    this.botMessageIds = new Set();
    this.userLimiter = new RateLimiter(config.ai.userLimit, config.ai.userWindowMinutes * 60 * 1000);
    this.chatLimiter = new RateLimiter(40, 60 * 60 * 1000);
    this.limitWarned = new RateLimiter(1, config.ai.userWindowMinutes * 60 * 1000);
    this.privateWarned = new RateLimiter(1, 24 * 60 * 60 * 1000);
  }

  remember(chat, entry) {
    if (!this.config.ai.historySize) return;
    const list = this.history.get(chat) || [];
    list.push({ ...entry, at: Date.now() });
    while (list.length > this.config.ai.historySize + 5) list.shift();
    this.history.set(chat, list);
  }

  recent(chat) {
    const hourAgo = Date.now() - 3 * 60 * 60 * 1000;
    return (this.history.get(chat) || []).filter((m) => m.at > hourAgo);
  }

  markSeen(id) {
    if (!id) return false;
    if (this.seen.has(id)) return true;
    this.seen.add(id);
    if (this.seen.size > 2000) this.seen.delete(this.seen.values().next().value);
    return false;
  }

  async reply(ctx, text) {
    const sent = await this.wa.sendText(ctx.chat, text, { quoted: ctx.raw, maxAgeMs: 10 * 60 * 1000 });
    if (sent?.key?.id) {
      this.botMessageIds.add(sent.key.id);
      if (this.botMessageIds.size > 1000) this.botMessageIds.delete(this.botMessageIds.values().next().value);
    }
    return sent;
  }

  async handle(msg) {
    const ctx = parseMessage(msg);
    if (!ctx) return;
    if (this.markSeen(ctx.id)) return;
    if (ctx.timestamp && Date.now() - ctx.timestamp > MAX_MESSAGE_AGE_MS) return;

    const command = parseCommand(ctx.text, this.config.features.commandPrefix);
    if (ctx.fromMe) {
      // Свои сообщения игнорируем. Исключение — команды, набранные владельцем номера с телефона:
      // он считается админом (удобно, если бот работает на вашем номере).
      if (!command || this.wa.isOwnSent?.(ctx.id) || this.botMessageIds.has(ctx.id)) return;
      ctx.isOwner = true;
    }

    if (ctx.isGroup) {
      // В чужих группах реагируем только на команды привязки/служебные от админов
      if (!this.core.isTarget(ctx.chat)) {
        if (command && ['bind', 'id', 'groups'].includes(command.name)) await this.runCommand(ctx, command);
        return;
      }
    } else if (!ctx.isOwner && !(await this.core.canUsePrivate(ctx))) {
      if ((command || ctx.text) && this.privateWarned.take(ctx.chat)) {
        await this.reply(ctx, '👋 Я бот домашних заданий класса и отвечаю только участникам группы класса. Пишите мне в группе.');
      }
      return;
    }

    // голосовые попадают в историю после расшифровки
    const label = ctx.text ? (ctx.hasImage ? `[фото] ${ctx.text}` : ctx.text) : ctx.hasImage ? '[фото]' : '';
    if (label && !command) this.remember(ctx.chat, { name: ctx.name || 'Ученик', text: label, fromBot: false });

    if (command) {
      await this.runCommand(ctx, command);
      return;
    }
    await this.maybeAnswer(ctx);
  }

  async runCommand(ctx, command) {
    const result = await this.commands.run(ctx, command);
    if (result && typeof result === 'object' && result.ask) {
      await this.answer(ctx, { question: result.ask, explicit: true, fromCommand: true });
    }
  }

  // Звали ли бота явно: @упоминание, ответ на его сообщение, обращение «бот, ...» или личный чат
  explicitCall(ctx) {
    const me = this.wa.me;
    if (!ctx.isGroup) return { explicit: true, question: ctx.text };
    if (ctx.mentions.some((jid) => isBotJid(jid, me))) {
      return { explicit: true, question: ctx.text.replace(/@\d+/g, '').trim() };
    }
    if (ctx.quoted && (isBotJid(ctx.quoted.participant, me) || this.botMessageIds.has(ctx.quoted.id))) {
      return { explicit: true, question: ctx.text, replyToBot: true };
    }
    const wake = this.config.ai.wakeWords.find((w) => new RegExp(`^${w}(?=[\\s,.:!?]|$)`, 'i').test(ctx.text));
    if (wake) return { explicit: true, question: ctx.text.slice(wake.length).replace(/^[\s,.:!?]+/, '') };
    return { explicit: false, question: ctx.text };
  }

  async maybeAnswer(ctx) {
    if (!this.assistant.enabled) {
      if (!ctx.isGroup && ctx.text) await this.reply(ctx, 'ИИ-помощник сейчас выключен. Команды: !помощь');
      return;
    }
    const groupAi = !ctx.isGroup || this.core.groupSettings(ctx.chat).ai !== false;
    let { explicit, question } = this.explicitCall(ctx);
    const auto = groupAi && this.config.ai.mode === 'smart';
    if (!explicit && !auto) return;

    // Голосовое: расшифровываем и дальше работаем как с текстом
    if (ctx.isVoice) {
      const voiceMode = this.config.ai.voice;
      if (voiceMode === 'off' || (voiceMode === 'direct' && !explicit)) return;
      if (ctx.audioSeconds > this.config.ai.maxVoiceSeconds) {
        if (explicit) await this.reply(ctx, `🎙 Голосовое слишком длинное (лимит ${this.config.ai.maxVoiceSeconds} с). Напишите вопрос текстом.`);
        return;
      }
      try {
        const audio = await downloadMediaMessage(ctx.raw, 'buffer', {}, { logger: this.logger, reuploadRequest: this.wa.sock.updateMediaMessage });
        question = await this.assistant.transcribe(audio, ctx.audioMime);
        this.core.countUsage('voice');
        this.logger.info({ chat: ctx.chat, text: question.slice(0, 100) }, 'Голосовое расшифровано');
        this.remember(ctx.chat, { name: ctx.name || 'Ученик', text: `[голосовое] ${question}`, fromBot: false });
      } catch (error) {
        this.logger.warn({ err: errText(error) }, 'Не удалось расшифровать голосовое');
        if (explicit) await this.reply(ctx, '🎙 Не получилось разобрать голосовое. Попробуйте написать текстом.');
        return;
      }
      if (!question) return;
    }

    // Фото: своё или в сообщении, на которое отвечают
    let image = null;
    const wantsImage = this.config.ai.images && (ctx.hasImage || (ctx.quoted?.hasImage && explicit));
    if (!explicit && auto) {
      if (!question) return; // фото без подписи в группе — не наше дело
      if (this.core.usage('classifier') >= this.config.ai.dailyLimit * 3) return;
      this.core.countUsage('classifier');
      const decision = await this.assistant.shouldRespond(question, this.recent(ctx.chat).slice(0, -1));
      if (!decision.respond) return;
      this.logger.debug({ reason: decision.reason }, 'ИИ решил ответить');
    }
    if (wantsImage) {
      try {
        const source = ctx.hasImage
          ? ctx.raw
          : { key: { remoteJid: ctx.chat, id: ctx.quoted.id, participant: ctx.quoted.participant, fromMe: false }, message: ctx.quoted.message };
        const buffer = await downloadMediaMessage(source, 'buffer', {}, { logger: this.logger, reuploadRequest: this.wa.sock.updateMediaMessage });
        if (buffer.length <= MAX_IMAGE_BYTES) image = { buffer, mimetype: ctx.hasImage ? ctx.imageMime : ctx.quoted.imageMime };
        else if (explicit) await this.reply(ctx, '🖼 Фото слишком большое, попробую ответить по тексту.');
      } catch (error) {
        this.logger.warn({ err: errText(error) }, 'Не удалось скачать фото');
      }
    }
    if (!question && !image) {
      if (explicit) await this.reply(ctx, 'Слушаю 🙂 Напишите вопрос по домашке.');
      return;
    }
    await this.answer(ctx, { question, explicit, image });
  }

  async answer(ctx, { question, explicit, image = null, fromCommand = false }) {
    const userKey = ctx.sender || ctx.chat;
    if (this.core.usage('ai') >= this.config.ai.dailyLimit) {
      if (explicit && this.limitWarned.take(`day|${ctx.chat}`)) await this.reply(ctx, '😴 На сегодня лимит ответов ИИ исчерпан. Завтра снова помогу!');
      return;
    }
    if (!this.userLimiter.take(userKey) || !this.chatLimiter.take(ctx.chat)) {
      if (explicit && this.limitWarned.take(userKey)) {
        const minutes = Math.ceil(this.userLimiter.retryIn(userKey) / 60000) || 1;
        await this.reply(ctx, `⏳ Слишком много вопросов подряд. Попробуйте через ${minutes} мин.`);
      }
      return;
    }

    await this.wa.typing(ctx.chat, true);
    try {
      // сам вопрос в историю не входит (команды туда и не попадают)
      const history = fromCommand ? this.recent(ctx.chat) : this.recent(ctx.chat).slice(0, -1);
      const quoted = ctx.quoted?.text ? { text: ctx.quoted.text, name: isBotJid(ctx.quoted.participant, this.wa.me) ? this.config.ai.botName : '' } : null;
      const text = await this.assistant.answer({ question, senderName: ctx.name, history, quoted, image });
      this.core.countUsage('ai');
      if (image) this.core.countUsage('vision');
      await this.reply(ctx, text);
      this.remember(ctx.chat, { name: this.config.ai.botName, text, fromBot: true });
      this.core.clearAlert('groq-auth');
    } catch (error) {
      this.logger.error({ err: errText(error), status: error.status }, 'Ошибка ИИ');
      if (error.status === 401 || error.status === 403) {
        this.core.notifyAdmins('groq-auth', 'Groq отклоняет ключ API (GROQ_API_KEY). Проверьте ключ на console.groq.com/keys');
      }
      if (error instanceof BilimAuthError) {
        this.core.notifyAdmins('bilim-auth', `Не могу войти в BilimClass: ${errText(error)}`);
      }
      if (explicit) {
        const busy = error.status === 429 ? 'ИИ сейчас перегружен' : 'ИИ временно недоступен';
        await this.reply(ctx, `😔 ${busy}. Попробуйте через минуту.`);
      }
    } finally {
      await this.wa.typing(ctx.chat, false);
    }
  }

  // Бота добавили в группу — подсказываем, как её подключить
  async onParticipants(event) {
    const me = this.wa.me;
    if (event.action !== 'add' || !me) return;
    const added = (event.participants || []).some((p) => isBotJid(typeof p === 'string' ? p : p?.id, me));
    if (!added || this.core.isTarget(event.id)) return;
    await this.wa.sendText(
      event.id,
      `👋 Привет! Я ${this.config.ai.botName} — бот домашних заданий из BilimClass.\n` +
        'Чтобы я присылал сюда ДЗ и отвечал на вопросы, админ группы или бота должен написать: *!привязать*',
    ).catch(() => {});
  }
}

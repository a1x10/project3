// Команды бота: !дз, !расписание, !помощь, админ-команды.
import { formatDay, formatSchedule, formatSubject, formatWeek } from '../homework/format.js';
import { BilimAuthError } from '../bilimclass/client.js';
import { addDays, mondayOf, nowParts, onDay, parseDayArg, formatClock } from '../utils/dates.js';
import { truncate } from '../utils/text.js';

const TODAY_CUTOFF_MINUTES = 12 * 60; // до полудня "!дз" показывает задания на сегодня

const COMMANDS = {
  help: ['помощь', 'help', 'команды', 'меню', 'start', 'старт', 'көмек'],
  homework: ['дз', 'dz', 'домашка', 'домашнее', 'hw', 'homework', 'задание', 'задания', 'тапсырма'],
  week: ['неделя', 'week', 'апта'],
  schedule: ['расписание', 'уроки', 'расп', 'schedule', 'кесте', 'сабақтар'],
  files: ['файлы', 'файл', 'files'],
  ask: ['спросить', 'вопрос', 'ии', 'ai', 'бот', 'gpt', 'сұрақ'],
  status: ['статус', 'status'],
  refresh: ['обновить', 'проверить', 'sync', 'refresh'],
  digest: ['рассылка', 'разослать', 'digest'],
  bind: ['привязать', 'подключить', 'bind'],
  unbind: ['отвязать', 'отключить', 'unbind'],
  auto: ['автоответ', 'автоответы', 'auto'],
  autodigest: ['авторассылка'],
  add: ['добавить', 'add'],
  remove: ['удалить', 'remove', 'del'],
  groups: ['группы', 'groups'],
  id: ['id', 'ид', 'чат'],
};

const LOOKUP = new Map(Object.entries(COMMANDS).flatMap(([name, aliases]) => aliases.map((a) => [a, name])));
const ADMIN_ONLY = new Set(['status', 'refresh', 'digest', 'bind', 'unbind', 'auto', 'autodigest', 'add', 'remove', 'groups', 'id']);

export function parseCommand(text, prefix = '!') {
  const trimmed = String(text || '').trim();
  const prefixes = [...new Set([prefix, '!', '/'])];
  const used = prefixes.find((p) => p && trimmed.startsWith(p));
  if (!used) return null;
  const body = trimmed.slice(used.length).trim();
  const [word = '', ...rest] = body.split(/\s+/);
  const name = LOOKUP.get(word.toLowerCase().replace(/@.*$/, ''));
  if (!name) return null;
  return { name, args: rest.join(' ').trim() };
}

function uptime(ms) {
  const minutes = Math.floor(ms / 60000);
  const d = Math.floor(minutes / 1440);
  const h = Math.floor((minutes % 1440) / 60);
  return `${d ? `${d} д ` : ''}${h} ч ${minutes % 60} мин`;
}

export class Commands {
  constructor({ core, homework, wa, scheduler, config, logger }) {
    this.core = core;
    this.homework = homework;
    this.wa = wa;
    this.scheduler = scheduler;
    this.config = config;
    this.logger = logger;
  }

  helpText(isAdmin) {
    const p = this.config.features.commandPrefix;
    const lines = [
      `🤖 *${this.config.ai.botName} — бот домашних заданий*`,
      '',
      `*${p}дз* — ДЗ на ближайший учебный день`,
      `*${p}дз завтра* / *${p}дз пятница* / *${p}дз 20.10* — на конкретный день`,
      `*${p}дз алгебра* — ДЗ по предмету`,
      `*${p}неделя* — ДЗ на всю неделю (${p}неделя след — на следующую)`,
      `*${p}расписание* [день] — уроки, время, кабинеты`,
      `*${p}файлы* [день] — прислать файлы к заданиям`,
    ];
    if (this.config.ai.mode !== 'off') {
      lines.push(
        `*${p}спросить* вопрос — спросить ИИ`,
        '',
        '🧠 *ИИ-помощник:* задайте вопрос по ДЗ в чате, ответьте на моё сообщение или отметьте меня @ — я объясню и подскажу. ' +
          `Можно прислать фото задания${this.config.ai.voice !== 'off' ? ' или голосовое' : ''}.`,
      );
    }
    if (isAdmin) {
      lines.push(
        '',
        '🔧 *Для админов:*',
        `${p}привязать / ${p}отвязать — присылать ДЗ в эту группу`,
        `${p}автоответ вкл|выкл — ИИ отвечает сам на вопросы в группе`,
        `${p}авторассылка вкл|выкл — ежедневная рассылка ДЗ в эту группу`,
        `${p}рассылка — отправить ДЗ сейчас`,
        `${p}обновить — проверить дневник на изменения`,
        `${p}добавить завтра Алгебра: №250 — добавить ДЗ вручную`,
        `${p}удалить N — удалить добавленное вручную`,
        `${p}статус — состояние бота · ${p}группы — список групп · ${p}id — id чата`,
      );
    }
    return lines.join('\n');
  }

  reply(ctx, text) {
    return this.wa.sendText(ctx.chat, text, { quoted: ctx.raw, maxAgeMs: 10 * 60 * 1000 });
  }

  // Возвращает { ask: 'текст' }, если команду должен обработать ИИ, иначе true/false
  async run(ctx, command) {
    const { name, args } = command;
    if (ADMIN_ONLY.has(name) && !(await this.core.isAdmin(ctx))) {
      await this.reply(ctx, '⛔ Эта команда только для админов бота.');
      return true;
    }
    try {
      switch (name) {
        case 'help':
          await this.reply(ctx, this.helpText(await this.core.isAdmin(ctx)));
          return true;
        case 'ask':
          if (!args) {
            await this.reply(ctx, 'Напишите вопрос после команды, например: !спросить как решить уравнение 2x+5=11');
            return true;
          }
          return { ask: args };
        case 'homework':
          return await this.homeworkCommand(ctx, args);
        case 'week':
          return await this.weekCommand(ctx, args);
        case 'schedule':
          return await this.scheduleCommand(ctx, args);
        case 'files':
          return await this.filesCommand(ctx, args);
        case 'status':
          await this.reply(ctx, await this.statusText());
          return true;
        case 'refresh': {
          const result = await this.scheduler.runPoll({ manual: true });
          await this.reply(ctx, result.added + result.changed ? `✅ Найдено изменений: ${result.added + result.changed} — отправил в группу.` : '✅ Дневник проверен, новых ДЗ нет.');
          return true;
        }
        case 'digest': {
          const targets = ctx.isGroup ? [ctx.chat] : this.core.targets();
          if (!targets.length) {
            await this.reply(ctx, 'Нет привязанных групп. Напишите !привязать в группе класса.');
            return true;
          }
          await this.scheduler.sendDigest({ targets, force: true });
          if (!ctx.isGroup) await this.reply(ctx, `✅ Отправил ДЗ в группы: ${targets.length}`);
          return true;
        }
        case 'bind':
          return await this.bindCommand(ctx);
        case 'unbind':
          if (!ctx.isGroup) return this.reply(ctx, 'Команду нужно писать в группе.').then(() => true);
          this.core.unbindGroup(ctx.chat);
          await this.reply(ctx, this.config.whatsapp.groupIds.includes(ctx.chat)
            ? '⚠️ Группа указана в WA_GROUP_IDS в .env — уберите её оттуда, чтобы отвязать полностью.'
            : '✅ Группа отвязана: ДЗ сюда больше не присылаю.');
          return true;
        case 'auto':
        case 'autodigest':
          return await this.toggleCommand(ctx, name, args);
        case 'add':
          return await this.addCommand(ctx, args);
        case 'remove':
          return await this.removeCommand(ctx, args);
        case 'groups':
          return await this.groupsCommand(ctx);
        case 'id':
          await this.reply(ctx, `ID этого чата: ${ctx.chat}`);
          return true;
        default:
          return false;
      }
    } catch (error) {
      this.logger.error({ err: error.message, command: name }, 'Ошибка команды');
      const text = error instanceof BilimAuthError
        ? '😔 Не могу войти в BilimClass — проверьте логин и пароль в настройках бота.'
        : `😔 Не получилось: ${truncate(error.message, 200)}. Попробуйте позже.`;
      await this.reply(ctx, text);
      return true;
    }
  }

  // День по умолчанию: до полудня учебного дня — сегодня, иначе ближайший следующий учебный день
  async defaultDay() {
    const { iso, minutes } = nowParts(this.config.timezone);
    if (minutes < TODAY_CUTOFF_MINUTES && (await this.homework.isSchoolDay(iso))) return iso;
    return (await this.homework.nextSchoolDay(iso)) || addDays(iso, 1);
  }

  async homeworkCommand(ctx, args) {
    const today = this.homework.today();
    const arg = args.replace(/^на\s+/i, '').trim();
    if (/^(неделю|неделя|week)$/i.test(arg)) return this.weekCommand(ctx, '');
    let day = arg ? parseDayArg(arg, today) : await this.defaultDay();
    if (!day && arg) {
      const result = await this.homework.findSubject(arg);
      await this.reply(ctx, formatSubject(result, arg, today));
      return true;
    }
    day = day || addDays(today, 1);
    const view = await this.homework.dayView(day);
    await this.reply(ctx, formatDay(view, today, { footer: false }));
    return true;
  }

  async weekCommand(ctx, args) {
    const today = this.homework.today();
    let monday = mondayOf(today);
    if (/^(след|следующ|next|келесі)/i.test(args)) monday = addDays(monday, 7);
    else if (/^(прош|прошл|prev|өткен)/i.test(args)) monday = addDays(monday, -7);
    // в выходные показываем следующую неделю
    else if (!args && nowParts(this.config.timezone).weekday >= 6) monday = addDays(monday, 7);
    const days = await this.homework.weekView(monday);
    await this.reply(ctx, formatWeek(days, today));
    return true;
  }

  async scheduleCommand(ctx, args) {
    const today = this.homework.today();
    const day = args ? parseDayArg(args.replace(/^на\s+/i, ''), today) : await this.defaultDay();
    if (!day) {
      await this.reply(ctx, 'Не понял день. Пример: !расписание завтра, !расписание пт, !расписание 20.10');
      return true;
    }
    await this.reply(ctx, formatSchedule(await this.homework.dayView(day), today));
    return true;
  }

  async filesCommand(ctx, args) {
    const today = this.homework.today();
    const day = args ? parseDayArg(args.replace(/^на\s+/i, ''), today) : await this.defaultDay();
    if (!day) {
      await this.reply(ctx, 'Не понял день. Пример: !файлы завтра');
      return true;
    }
    const view = await this.homework.dayView(day);
    const withFiles = view.entries.filter((e) => e.hasFiles);
    if (!withFiles.length) {
      await this.reply(ctx, `📎 К заданиям ${onDay(day, today)} файлов нет.`);
      return true;
    }
    const sent = await this.scheduler.sendFiles(withFiles, [ctx.chat], { force: true });
    if (!sent) await this.reply(ctx, '😔 Не удалось получить файлы из BilimClass. Откройте их в приложении.');
    return true;
  }

  async bindCommand(ctx) {
    if (!ctx.isGroup) {
      await this.reply(ctx, 'Напишите !привязать в той группе, куда присылать ДЗ.');
      return true;
    }
    let name = '';
    try {
      name = (await this.wa.groupMetadata(ctx.chat, { fresh: true })).subject;
    } catch {
      /* без названия */
    }
    this.core.bindGroup(ctx.chat, name);
    const digest = this.config.schedule.digestTime;
    await this.reply(
      ctx,
      `✅ Готово! Группа «${name || 'эта'}» привязана.\n\n` +
        (digest != null ? `• Каждый день в ${formatClock(digest)} пришлю ДЗ на следующий учебный день.\n` : '') +
        (this.config.schedule.notifyChanges ? '• Сообщу, когда в дневнике появится новое ДЗ или его изменят.\n' : '') +
        (this.config.ai.mode !== 'off' ? '• Отвечу на вопросы по домашке — пишите в чат.\n' : '') +
        '\nВсе команды: !помощь',
    );
    return true;
  }

  async toggleCommand(ctx, name, args) {
    if (!ctx.isGroup) {
      await this.reply(ctx, 'Эту команду нужно писать в группе.');
      return true;
    }
    const key = name === 'auto' ? 'ai' : 'digest';
    const on = /^(вкл|on|да|1|включить)$/i.test(args);
    const off = /^(выкл|off|нет|0|выключить)$/i.test(args);
    if (!on && !off) {
      const state = this.core.groupSettings(ctx.chat)[key] ? 'включено' : 'выключено';
      await this.reply(ctx, `Сейчас: ${state}. Напишите «!${name === 'auto' ? 'автоответ' : 'авторассылка'} вкл» или «выкл».`);
      return true;
    }
    this.core.setGroupOption(ctx.chat, key, on);
    const what = key === 'ai' ? 'Автоответы ИИ на вопросы' : 'Ежедневная рассылка ДЗ';
    await this.reply(ctx, `✅ ${what} ${on ? 'включены' : 'выключены'}.${key === 'ai' && off ? ' Спросить ИИ всё ещё можно через !спросить или ответом на моё сообщение.' : ''}`);
    return true;
  }

  async addCommand(ctx, args) {
    const today = this.homework.today();
    // формат: <день> <Предмет>: <текст>
    const match = /^(\S+(?:\s+\S+)?)\s+([^:]+):\s*([\s\S]+)$/.exec(args);
    let date = null;
    let subject = '';
    let text = '';
    if (match) {
      const words = match[1].split(/\s+/);
      // день может состоять из одного слова ("завтра") или двух ("15 октября")
      date = parseDayArg(match[1], today);
      if (date) {
        subject = match[2].trim();
      } else if ((date = parseDayArg(words[0], today))) {
        subject = `${words.slice(1).join(' ')} ${match[2]}`.trim();
      }
      text = match[3].trim();
    }
    if (!date || !subject || !text) {
      await this.reply(ctx, 'Формат: !добавить <день> <Предмет>: <задание>\nНапример: !добавить завтра Алгебра: № 250–255');
      return true;
    }
    const id = this.core.store.update((s) => {
      const newId = s.nextManualId++;
      s.manual.push({ id: newId, date, subject, text, author: ctx.name || '', createdAt: Date.now() });
      return newId;
    });
    await this.reply(ctx, `✅ Добавлено (№${id}): *${subject}* ${onDay(date, today)}\n${text}\n\nУдалить: !удалить ${id}`);
    return true;
  }

  async removeCommand(ctx, args) {
    const id = Number(args.replace(/\D/g, ''));
    const exists = this.core.store.data.manual.some((m) => m.id === id);
    if (!exists) {
      const list = this.core.store.data.manual.map((m) => `№${m.id}: ${m.subject} (${m.date}) — ${truncate(m.text, 40)}`);
      await this.reply(ctx, list.length ? `Не нашёл №${args}. Добавленные вручную:\n${list.join('\n')}` : 'Нет ДЗ, добавленных вручную.');
      return true;
    }
    this.core.store.update((s) => {
      s.manual = s.manual.filter((m) => m.id !== id);
    });
    await this.reply(ctx, `🗑 Удалено №${id}.`);
    return true;
  }

  async groupsCommand(ctx) {
    const groups = await this.wa.allGroups();
    if (!groups.length) {
      await this.reply(ctx, 'Бот пока не состоит ни в одной группе.');
      return true;
    }
    const lines = groups.map((g) => `${this.core.isTarget(g.id) ? '✅' : '▫️'} ${g.subject}\n   ${g.id}`);
    await this.reply(ctx, `Группы бота (✅ — сюда приходит ДЗ):\n\n${lines.join('\n')}`);
    return true;
  }

  async statusText() {
    const s = this.homework.status();
    const session = s.session || {};
    const lastSync = s.lastSuccessAt ? `${Math.round((Date.now() - s.lastSuccessAt) / 60000)} мин назад` : 'ещё не было';
    const targets = this.core.targets().map((jid) => this.core.store.data.groups[jid]?.name || jid);
    return [
      '📊 *Статус бота*',
      `⏱ Работает: ${uptime(Date.now() - this.core.startedAt)}`,
      `📱 WhatsApp: ${this.wa.isOpen ? 'подключён' : this.wa.status}`,
      `📘 BilimClass: ${s.lastError ? `ошибка — ${truncate(s.lastError, 120)}` : 'ок'} (обновлено ${lastSync})`,
      session.className ? `🏫 Класс: ${session.className}${session.schoolName ? `, ${truncate(session.schoolName, 60)}` : ''}` : '',
      `👥 Группы для ДЗ: ${targets.length ? targets.join(', ') : 'нет — напишите !привязать в группе'}`,
      `🧠 ИИ: ${this.config.ai.mode === 'off' ? 'выключен' : `${this.config.ai.mode}, ответов сегодня: ${this.core.usage('ai')}/${this.config.ai.dailyLimit}`}`,
      `📬 В очереди сообщений: ${this.wa.queue.length}`,
      this.config.schedule.digestTime != null ? `🕕 Рассылка: ${formatClock(this.config.schedule.digestTime)}, последняя: ${this.core.store.data.jobs.digest || '—'}` : '🕕 Рассылка выключена',
    ].filter(Boolean).join('\n');
  }
}

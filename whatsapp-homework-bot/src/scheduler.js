// Планировщик: ежедневная рассылка ДЗ, утреннее напоминание, сводка недели, проверка дневника на изменения.
// Работает «тиками» раз в 30 секунд — если бот был выключен в момент рассылки, он догонит её после запуска.
import { BilimAuthError } from './bilimclass/client.js';
import { formatChanges, formatDay, formatSchedule, formatWeek } from './homework/format.js';
import { errText } from './logger.js';
import { addDays, diffDays, mondayOf, nowParts, onDay } from './utils/dates.js';

const TICK_MS = 30 * 1000;
const RETRY_MS = 10 * 60 * 1000;

export class Scheduler {
  constructor({ config, store, homework, wa, core, logger }) {
    this.config = config;
    this.store = store;
    this.homework = homework;
    this.wa = wa;
    this.core = core;
    this.logger = logger;
    this.timer = null;
    this.busy = false;
    this.failures = 0;
    this.lastAttempt = {};
  }

  start() {
    this.timer = setInterval(() => this.tick(), TICK_MS);
    this.timer.unref?.();
    setTimeout(() => this.tick(), 5000).unref?.();
  }

  stop() {
    clearInterval(this.timer);
  }

  jobDone(name, value) {
    this.store.update((s) => {
      s.jobs[name] = value;
    });
  }

  // Пора ли запускать ежедневную задачу: время наступило, сегодня ещё не запускали, не вышли за окно догонялки
  isDue(name, at, now) {
    if (at == null) return false;
    if (this.store.data.jobs[name] === now.iso) return false;
    if (now.minutes < at || now.minutes > at + this.config.schedule.catchUpMinutes) return false;
    return Date.now() - (this.lastAttempt[name] || 0) > RETRY_MS;
  }

  inActiveHours(minutes) {
    const { from, to } = this.config.schedule.activeHours;
    return from <= to ? minutes >= from && minutes <= to : minutes >= from || minutes <= to;
  }

  async tick() {
    if (this.busy || !this.wa.isOpen) return;
    this.busy = true;
    try {
      const now = nowParts(this.config.timezone);
      const { schedule } = this.config;

      if (this.store.data.jobs.prune !== now.iso) {
        this.store.prune(now.iso);
        this.jobDone('prune', now.iso);
      }
      if (this.isDue('digest', schedule.digestTime, now)) await this.guard('digest', now, () => this.dailyDigest(now));
      if (this.isDue('morning', schedule.morningTime, now)) await this.guard('morning', now, () => this.morning(now));
      if (now.weekday === schedule.weeklyDay && this.isDue('weekly', schedule.weeklyTime, now)) {
        await this.guard('weekly', now, () => this.weekly(now));
      }
      const minutesSincePoll = (Date.now() - (this.store.data.jobs.lastPollAt || 0)) / 60000;
      if (schedule.notifyChanges && this.inActiveHours(now.minutes) && minutesSincePoll >= schedule.pollIntervalMinutes) {
        await this.runPoll().catch(() => {});
      }
    } catch (error) {
      this.logger.error({ err: error }, 'Ошибка планировщика');
    } finally {
      this.busy = false;
    }
  }

  async guard(name, now, fn) {
    this.lastAttempt[name] = Date.now();
    try {
      await fn();
      this.jobDone(name, now.iso);
      this.onSuccess();
    } catch (error) {
      this.onFailure(error, name);
    }
  }

  onSuccess() {
    if (this.failures >= 3) this.core.notifyAdmins('bilim-recovered', '✅ Связь с BilimClass восстановлена.', 0);
    this.failures = 0;
    this.core.clearAlert('bilim-down');
    this.core.clearAlert('bilim-auth');
  }

  onFailure(error, job) {
    this.failures += 1;
    this.logger.error({ err: errText(error), job }, 'Задача не выполнена');
    if (error instanceof BilimAuthError) {
      this.core.notifyAdmins('bilim-auth', `Не могу войти в BilimClass: ${errText(error)}`);
    } else if (this.failures >= 3) {
      this.core.notifyAdmins('bilim-down', `BilimClass не отвечает уже ${this.failures} попытки подряд: ${errText(error)}`);
    }
  }

  // Группы, в которые идёт авторассылка
  digestTargets() {
    return this.core.targets().filter((jid) => this.core.groupSettings(jid).digest !== false);
  }

  async dailyDigest(now) {
    const targets = this.digestTargets();
    if (!targets.length) return;
    // Рассылаем, если сегодня учебный день или завтра учебный (вечер воскресенья). В каникулы молчим.
    const next = await this.homework.nextSchoolDay(now.iso);
    if (!next) {
      this.logger.info('Рассылка пропущена: в ближайшие недели нет уроков (каникулы?)');
      return;
    }
    const todaySchool = await this.homework.isSchoolDay(now.iso);
    if (!todaySchool && diffDays(next, now.iso) > 1) {
      this.logger.info({ next }, 'Рассылка пропущена: сегодня выходной, завтра не учимся');
      return;
    }
    await this.sendDigest({ targets, day: next });
  }

  // Отправить ДЗ на день (по умолчанию — ближайший учебный) в указанные группы
  async sendDigest({ targets, day, force = false }) {
    const today = this.homework.today();
    const date = day || (await this.homework.nextSchoolDay(today)) || addDays(today, 1);
    const view = await this.homework.dayView(date, { fresh: true });
    if (!view.entries.length && this.config.schedule.skipEmptyDigest && !force) {
      this.logger.info({ date }, 'ДЗ нет — пустую рассылку пропускаю (SKIP_EMPTY_DIGEST)');
      return;
    }
    const text = formatDay(view, today);
    for (const jid of targets) this.wa.sendText(jid, text, { persist: true }).catch(() => {});
    this.logger.info({ date, groups: targets.length, homework: view.entries.length }, 'Рассылка ДЗ отправлена в очередь');
    if (this.config.features.sendFiles) await this.sendFiles(view.entries.filter((e) => e.hasFiles), targets);
  }

  async morning(now) {
    const targets = this.digestTargets();
    if (!targets.length || !(await this.homework.isSchoolDay(now.iso))) return;
    const view = await this.homework.dayView(now.iso, { fresh: true });
    const text = `☀️ *Доброе утро!*\n\n${formatSchedule(view, now.iso)}${view.entries.length ? `\n\n${formatDay(view, now.iso, { footer: false, title: `📚 *Сдаём сегодня:*` })}` : ''}`;
    for (const jid of targets) this.wa.sendText(jid, text, { persist: true, maxAgeMs: 3 * 3600 * 1000 }).catch(() => {});
  }

  async weekly(now) {
    const targets = this.digestTargets();
    if (!targets.length) return;
    // в выходные — следующая неделя, в будни — текущая
    const monday = now.weekday >= 5 ? addDays(mondayOf(now.iso), 7) : mondayOf(now.iso);
    const days = await this.homework.weekView(monday);
    if (!days.some((d) => d.lessons.length)) return; // каникулы
    const text = formatWeek(days, now.iso);
    for (const jid of targets) this.wa.sendText(jid, text, { persist: true }).catch(() => {});
  }

  // Проверка дневника: новые и изменённые ДЗ сразу отправляются в группы
  async runPoll({ manual = false } = {}) {
    this.jobDone('lastPollAt', Date.now());
    let result;
    try {
      result = await this.homework.pollChanges();
      this.onSuccess();
    } catch (error) {
      this.onFailure(error, 'poll');
      if (manual) throw error;
      return { added: 0, changed: 0 };
    }
    const { added, changed, firstRun } = result;
    if (firstRun) {
      this.logger.info('Первая проверка дневника: запомнил текущие ДЗ, дальше буду сообщать об изменениях');
      return { added: 0, changed: 0 };
    }
    if (!this.config.schedule.notifyChanges || (!added.length && !changed.length)) return { added: added.length, changed: changed.length };

    const today = this.homework.today();
    const targets = this.digestTargets();
    const text = formatChanges({ added, changed }, today);
    this.logger.info({ added: added.length, changed: changed.length }, 'Найдены изменения в дневнике');
    for (const jid of targets) this.wa.sendText(jid, text, { persist: true, maxAgeMs: 12 * 3600 * 1000 }).catch(() => {});
    if (this.config.features.sendFiles) await this.sendFiles([...added, ...changed].filter((e) => e.hasFiles), targets);
    return { added: added.length, changed: changed.length };
  }

  // Скачать и отправить файлы к ДЗ. Каждый файл отправляется в группу один раз (если не force).
  async sendFiles(entries, targets, { force = false } = {}) {
    let sentAny = false;
    const today = this.homework.today();
    for (const entry of entries) {
      let files;
      try {
        files = await this.homework.filesFor(entry);
      } catch (error) {
        this.logger.warn({ err: errText(error), subject: entry.subject }, 'Не удалось получить список файлов');
        continue;
      }
      for (const file of files) {
        const fresh = targets.filter((jid) => force || !this.store.data.sentFiles[`${jid}|${file.key}`]);
        if (!fresh.length) continue;
        let buffer;
        try {
          buffer = await this.homework.downloadFile(file);
        } catch (error) {
          this.logger.warn({ err: errText(error), file: file.name }, 'Файл не скачан');
          const note = `📎 *${entry.subject}*: файл «${file.name}» не получилось переслать (${errText(error)}). Откройте его в BilimClass.`;
          for (const jid of fresh) this.wa.sendText(jid, note).catch(() => {});
          continue;
        }
        const caption = `📎 *${entry.subject}* — ${entry.dueDate ? onDay(entry.dueDate, today) : 'к заданию'}`;
        const isImage = file.mimetype.startsWith('image/') && file.ext !== 'gif';
        const content = isImage
          ? { image: buffer, caption, mimetype: file.mimetype }
          : { document: buffer, fileName: file.name, mimetype: file.mimetype, caption };
        for (const jid of fresh) {
          try {
            await this.wa.send(jid, content, {}, { maxAgeMs: 3 * 3600 * 1000 });
            sentAny = true;
            this.store.update((s) => {
              s.sentFiles[`${jid}|${file.key}`] = Date.now();
            });
          } catch (error) {
            this.logger.warn({ err: errText(error), file: file.name }, 'Файл не отправлен');
          }
        }
      }
    }
    return sentAny;
  }
}

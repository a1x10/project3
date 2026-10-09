// Планировщик: рассылка ДЗ после уроков, утреннее напоминание, сводка недели, проверка дневника на изменения.
// Работает «тиками» раз в 30 секунд — если бот был выключен в момент рассылки, он догонит её после запуска.
import { BilimAuthError } from './bilimclass/client.js';
import { formatChanges, formatDay, formatNewHomework, formatSchedule, formatWeek, formatWeekAhead } from './homework/format.js';
import { dayMessage } from './homework/message.js';
import { entryHash } from './homework/service.js';
import { errText } from './logger.js';
import { addDays, diffDays, formatClock, mondayOf, nowParts, onDay } from './utils/dates.js';
import { splitMessage } from './utils/text.js';

const TICK_MS = 30 * 1000;
const RETRY_MS = 10 * 60 * 1000;
const PLAN_REFRESH_MS = 30 * 60 * 1000;

// Ключ задания для учёта «уже отправляли в группу»
const announceKey = (e) => `${e.lessonDate}|${e.key}`;

export class Scheduler {
  constructor({ config, store, homework, wa, core, logger, clock }) {
    this.config = config;
    this.clock = clock || (() => nowParts(config.timezone)); // текущие дата/время школы (подменяется в тестах)
    this.store = store;
    this.homework = homework;
    this.wa = wa;
    this.core = core;
    this.logger = logger;
    this.timer = null;
    this.busy = false;
    this.failures = 0;
    this.lastAttempt = {};
    this.plan = null; // { date, at, lessonsEnd, todaySchool, source, computedAt }
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
  isDue(name, at, now, until = at == null ? null : at + this.config.schedule.catchUpMinutes) {
    if (at == null) return false;
    if (this.store.data.jobs[name] === now.iso) return false;
    if (now.minutes < at || now.minutes > until) return false;
    return Date.now() - (this.lastAttempt[name] || 0) > RETRY_MS;
  }

  // До какого времени ещё можно отправить сегодняшнюю рассылку (если бот был выключен):
  // CATCH_UP_MINUTES после плана, но не раньше конца ACTIVE_HOURS (по умолчанию 22:00)
  digestDeadline(plan) {
    const { catchUpMinutes, activeHours } = this.config.schedule;
    const base = plan.at + catchUpMinutes;
    return activeHours.from <= activeHours.to ? Math.max(base, activeHours.to) : base;
  }

  inActiveHours(minutes) {
    const { from, to } = this.config.schedule.activeHours;
    return from <= to ? minutes >= from && minutes <= to : minutes >= from || minutes <= to;
  }

  async tick() {
    if (this.busy || !this.wa.isOpen) return;
    this.busy = true;
    try {
      const now = this.clock();
      const { schedule } = this.config;

      if (this.store.data.jobs.prune !== now.iso) {
        this.store.prune(now.iso);
        this.jobDone('prune', now.iso);
      }
      if (schedule.digestMode !== 'off' && this.store.data.jobs.digest !== now.iso) {
        const plan = await this.digestPlan(now);
        if (plan && this.isDue('digest', plan.at, now, this.digestDeadline(plan))) await this.guard('digest', now, () => this.dailyDigest(now));
      }
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

  // Когда сегодня рассылка: через DIGEST_DELAY_MINUTES после последнего урока (по свежему расписанию из дневника).
  // В дни без уроков (вечер воскресенья) и если время уроков неизвестно — в DIGEST_TIME.
  async digestPlan(now) {
    const { schedule } = this.config;
    if (schedule.digestMode === 'off') return null;
    const plan = this.plan?.date === now.iso ? this.plan : null;
    const maxAge = plan?.source === 'error' ? RETRY_MS : PLAN_REFRESH_MS;
    if (plan && Date.now() - plan.computedAt < maxAge) return plan;

    let lessonsEnd = null;
    let source = 'fallback';
    try {
      lessonsEnd = await this.homework.lessonsEnd(now.iso, { fresh: true });
      if (schedule.digestMode === 'fixed') source = 'fixed';
      else if (lessonsEnd != null) source = 'lessons';
    } catch (error) {
      if (plan) return plan; // BilimClass временно недоступен — оставляем прежний план
      source = 'error';
    }
    const at = source === 'lessons' ? Math.min(lessonsEnd + schedule.digestDelayMinutes, 23 * 60 + 59) : schedule.digestTime;
    const changed = !plan || plan.at !== at;
    this.plan = { date: now.iso, at, lessonsEnd, todaySchool: lessonsEnd != null, source, computedAt: Date.now() };
    if (changed && at != null) {
      this.logger.info(
        { at: formatClock(at), lessonsEnd: lessonsEnd != null ? formatClock(lessonsEnd) : null, source },
        source === 'lessons' ? 'Рассылка ДЗ сегодня — после уроков' : 'Рассылка ДЗ сегодня — по времени DIGEST_TIME',
      );
    }
    return this.plan;
  }

  // Ждём ли сегодня рассылку после уроков: тогда новые ДЗ копим для неё, а не шлём по одному
  digestPending(now) {
    const plan = this.plan;
    if (!plan || plan.date !== now.iso || !plan.todaySchool || plan.at == null) return false;
    if (this.store.data.jobs.digest === now.iso) return false;
    return now.minutes <= this.digestDeadline(plan);
  }

  async dailyDigest(now) {
    const targets = this.digestTargets();
    if (!targets.length) return;
    // В учебный день — после уроков. В выходной — только если завтра учимся (вечер воскресенья). В каникулы молчим.
    const next = await this.homework.nextSchoolDay(now.iso);
    const todaySchool = await this.homework.isSchoolDay(now.iso);
    if (!next && !todaySchool) {
      this.logger.info('Рассылка пропущена: в ближайшие недели нет уроков (каникулы?)');
      return;
    }
    if (!todaySchool && diffDays(next, now.iso) > 1) {
      this.logger.info({ next }, 'Рассылка пропущена: сегодня выходной, завтра не учимся');
      return;
    }
    await this.sendDigest({ targets });
  }

  // Разделить задания на новые / изменённые / уже отправленные в группу
  classify(entries) {
    const announced = this.store.data.announced;
    return entries
      .map((e) => {
        const key = announceKey(e);
        if (!(key in announced)) return { ...e, kind: 'new' };
        if (announced[key] !== entryHash(e)) return { ...e, kind: 'changed' };
        return null;
      })
      .filter(Boolean);
  }

  // ready — после полной рассылки; одиночные уведомления не считаются «первой рассылкой»
  markAnnounced(entries, { ready = true } = {}) {
    if (!entries.length && !ready) return;
    this.store.update((s) => {
      for (const e of entries) s.announced[announceKey(e)] = entryHash(e);
      if (ready) s.announcedReady = true;
    });
  }

  // Рассылка: свежие данные из BilimClass на каждый день недели вперёд → только то, что ещё не присылали
  async sendDigest({ targets, force = false }) {
    const data = await this.homework.digestData({ fresh: true });
    const firstTime = !this.store.data.announcedReady;
    const fresh = this.classify(data.entries);
    const now = this.clock();

    const messages = this.config.features.homeworkImage
      ? await this.digestPhotos({ data, fresh, firstTime, now, force })
      : this.digestText({ data, fresh, firstTime, now, force });
    if (!messages) return;

    for (const jid of targets) {
      for (const content of messages) this.wa.send(jid, content, {}, { persist: true }).catch(() => {});
    }
    // «Уже отправлено» запоминаем, только если рассылка ушла во все группы (а не !рассылка в одной из нескольких)
    if (this.digestTargets().every((jid) => targets.includes(jid))) this.markAnnounced(data.entries);
    this.logger.info(
      { groups: targets.length, messages: messages.length, new: fresh.length, total: data.entries.length, firstTime },
      'Рассылка ДЗ отправлена в очередь',
    );
    if (this.config.features.sendFiles) {
      const withFiles = (firstTime ? data.entries : fresh).filter((e) => e.hasFiles);
      await this.sendFiles(withFiles, targets);
    }
  }

  // Текстовый вариант рассылки (HOMEWORK_AS_IMAGE=false)
  digestText({ data, fresh, firstTime, now, force }) {
    if (firstTime) return [{ text: formatWeekAhead(data) }];
    if (!fresh.length && this.config.schedule.skipEmptyDigest && !force) {
      this.logger.info('Новых ДЗ нет — рассылку пропускаю (SKIP_EMPTY_DIGEST)');
      return null;
    }
    const text = formatNewHomework({ fresh, data, remindTomorrow: this.config.schedule.remindTomorrow, checkedAt: now.minutes });
    return splitMessage(text, 6000).map((part) => ({ text: part }));
  }

  // Рассылка фотографиями: «Домашнее задание на завтра» + отдельное фото на каждый день, где появилось новое ДЗ.
  // Новые и изменённые задания на картинке помечены «НОВОЕ» / «ИЗМЕНЕНО».
  async digestPhotos({ data, fresh, firstTime, now, force }) {
    const marks = firstTime ? new Map() : new Map(fresh.map((e) => [announceKey(e), e.kind]));
    const remind = this.config.schedule.remindTomorrow;
    const days = data.days.filter((day) => {
      if (day.date === data.next && (remind || firstTime)) return true;
      if (firstTime) return day.entries.length > 0;
      return day.entries.some((e) => marks.has(announceKey(e)));
    });
    if (!days.length) {
      if (this.config.schedule.skipEmptyDigest && !force) {
        this.logger.info('Новых ДЗ нет — рассылку пропускаю (SKIP_EMPTY_DIGEST)');
        return null;
      }
      return [{ text: '✅ Проверил дневник после уроков — новых домашних заданий нет.' }];
    }
    const messages = [];
    for (const day of days) {
      const dayMarks = day.entries.map((e) => marks.get(announceKey(e))).filter(Boolean);
      let kind = 'digest';
      if (day.date !== data.next && dayMarks.length) kind = dayMarks.every((m) => m === 'changed') ? 'changed' : 'new';
      messages.push(await dayMessage(day, data.today, {
        kind,
        marks,
        markKey: announceKey,
        className: this.homework.client.session?.className,
        checkedAt: formatClock(now.minutes),
        logger: this.logger,
      }));
    }
    return messages;
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
    const now = this.clock();
    // Днём, пока не прошла рассылка после уроков, копим новые ДЗ для неё (кроме заданий на сегодня — они срочные).
    // После рассылки (вечером) и в выходные — сообщаем сразу. Уже отправленное в группу второй раз не шлём.
    const hold = !manual && this.digestPending(now);
    const pick = (list) => this.classify(list).filter((e) => !hold || (e.dueDate && e.dueDate <= today));
    const toAdd = pick(added);
    const toChange = pick(changed);
    const total = { added: added.length, changed: changed.length };
    if (hold && toAdd.length + toChange.length < added.length + changed.length) {
      this.logger.info(total, 'Новые ДЗ найдены — пришлю их в рассылке после уроков');
    }
    if (!toAdd.length && !toChange.length) return total;

    const targets = this.digestTargets();
    this.logger.info({ added: toAdd.length, changed: toChange.length }, 'Найдены изменения в дневнике — отправляю');
    for (const content of await this.changeMessages(toAdd, toChange, today, now)) {
      for (const jid of targets) this.wa.send(jid, content, {}, { persist: true, maxAgeMs: 12 * 3600 * 1000 }).catch(() => {});
    }
    this.markAnnounced([...toAdd, ...toChange], { ready: false });
    if (this.config.features.sendFiles) await this.sendFiles([...toAdd, ...toChange].filter((e) => e.hasFiles), targets);
    return total;
  }

  // Сообщения о новых/изменённых ДЗ: фото дня (с пометками) или текст
  async changeMessages(added, changed, today, now) {
    if (!this.config.features.homeworkImage) return [{ text: formatChanges({ added, changed }, today) }];
    const marks = new Map([...added.map((e) => [announceKey(e), 'new']), ...changed.map((e) => [announceKey(e), 'changed'])]);
    const all = [...added, ...changed];
    const dates = [...new Set(all.map((e) => e.dueDate).filter(Boolean))].sort();
    const messages = [];
    for (const date of dates) {
      const view = await this.homework.dayView(date);
      const kinds = all.filter((e) => e.dueDate === date).map((e) => marks.get(announceKey(e)));
      messages.push(await dayMessage(view, today, {
        kind: kinds.every((k) => k === 'changed') ? 'changed' : 'new',
        marks,
        markKey: announceKey,
        className: this.homework.client.session?.className,
        checkedAt: formatClock(now.minutes),
        logger: this.logger,
      }));
    }
    // задания без известной даты сдачи — текстом
    const undated = (list) => list.filter((e) => !e.dueDate);
    if (undated(all).length) messages.push({ text: formatChanges({ added: undated(added), changed: undated(changed) }, today) });
    return messages;
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

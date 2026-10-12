// Планировщик: рассылка ДЗ после уроков, утреннее напоминание, сводка недели, проверка дневника на изменения.
// Работает «тиками» раз в 30 секунд — если бот был выключен в момент рассылки, он догонит её после запуска.
import { BilimAuthError } from './bilimclass/client.js';
import { formatChanges, formatDay, formatNewHomework, formatSchedule, formatWeek } from './homework/format.js';
import { HomeworkPhotos } from './homework/message.js';
import { entryHash } from './homework/service.js';
import { errText } from './logger.js';
import { describeDay, quietReason } from './settings.js';
import { addDays, diffDays, formatClock, mondayOf, nowParts, onDay } from './utils/dates.js';
import { splitMessage } from './utils/text.js';

const TICK_MS = 30 * 1000;
const RETRY_MS = 10 * 60 * 1000;
const PLAN_REFRESH_MS = 30 * 60 * 1000;
const REPORT_AT = 21 * 60; // вечерний отчёт админу

// Ключ задания для учёта «уже отправляли в группу»
const announceKey = (e) => `${e.lessonDate}|${e.key}`;

export class Scheduler {
  constructor({ config, store, homework, wa, core, logger, clock, photos, settings = null }) {
    this.config = config;
    this.settings = settings; // чтобы убирать закончившуюся паузу и прошедшие пропуски
    // фото с ДЗ: скриншот дневника / нарисованная карточка / текст
    this.photos = photos || new HomeworkPhotos({ config, logger, className: () => homework.client.session?.className });
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

  // Закончившаяся пауза и прошедшие «пропустить» больше не нужны (и не должны показываться в панели)
  cleanupSchedule(now) {
    const s = this.config.schedule;
    const patch = {};
    if (s.pausedUntil && s.pausedUntil !== 'forever' && s.pausedUntil < now.iso) patch['schedule.pausedUntil'] = null;
    const skips = (s.skipDates || []).filter((d) => d >= now.iso);
    if (skips.length !== (s.skipDates || []).length) patch['schedule.skipDates'] = skips;
    if (Object.keys(patch).length) this.settings?.update(patch, { by: 'scheduler' });
  }

  // Что присылать сегодня: «завтра + новое» или «только на завтра» (по графику дня)
  todayScope() {
    return this.config.schedule.days?.[this.clock().weekday]?.scope || 'new';
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
    this.busySince = Date.now();
    try {
      const now = this.clock();
      const { schedule } = this.config;

      if (this.store.data.jobs.prune !== now.iso) {
        this.store.prune(now.iso);
        this.jobDone('prune', now.iso);
      }
      this.cleanupSchedule(now);
      if (this.store.data.jobs.digest !== now.iso) {
        const plan = await this.digestPlan(now);
        if (plan?.at != null && this.isDue('digest', plan.at, now, this.digestDeadline(plan))) await this.guard('digest', now, () => this.dailyDigest(now));
      }
      const quiet = quietReason(schedule, now.iso, now.weekday);
      if (!quiet && this.isDue('morning', schedule.morningTime, now)) await this.guard('morning', now, () => this.morning(now));
      if (!quiet && now.weekday === schedule.weeklyDay && this.isDue('weekly', schedule.weeklyTime, now)) {
        await this.guard('weekly', now, () => this.weekly(now));
      }
      if (this.config.notify?.dailyReport && this.isDue('report', REPORT_AT, now)) {
        this.lastAttempt.report = Date.now();
        await this.core.dailyReport?.(now).catch(() => {});
        this.jobDone('report', now.iso);
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
      // одно сообщение, когда сломалось, и напоминание не чаще раза в сутки; когда починится — сообщение «восстановлено»
      this.core.notifyAdmins('bilim-down', `Не получается получить дневник BilimClass: ${errText(error)}. Бот пробует снова каждые несколько минут.`, 24 * 3600 * 1000);
    }
  }

  // Группы, в которые идёт авторассылка
  digestTargets() {
    return this.core.targets().filter((jid) => this.core.groupSettings(jid).digest !== false);
  }

  // План рассылки на сегодня — по настройке дня недели (из панели или .env):
  //  lessons — через DIGEST_DELAY_MINUTES после последнего урока (по свежему расписанию из дневника),
  //            в день без уроков или если время уроков неизвестно — во время дня (если задано);
  //  time    — в заданное время;  off / пауза / пропуск — сегодня ничего не присылаем.
  // Возвращает { date, at, lessonsEnd, todaySchool, source, scope, quiet }; at = null — рассылки сегодня нет.
  async digestPlan(now) {
    const { schedule } = this.config;
    const day = schedule.days?.[now.weekday] || { mode: 'off' };
    const quiet = quietReason(schedule, now.iso, now.weekday);
    const key = JSON.stringify([day, schedule.digestDelayMinutes, quiet]); // план пересчитывается, если поменяли настройки
    const plan = this.plan?.date === now.iso && this.plan.key === key ? this.plan : null;
    const maxAge = plan?.source === 'error' ? RETRY_MS : PLAN_REFRESH_MS;
    if (plan && Date.now() - plan.computedAt < maxAge) return plan;
    if (quiet) {
      if (this.plan?.quiet !== quiet || this.plan?.date !== now.iso) this.logger.info({ reason: quiet }, 'Сегодня рассылки нет');
      this.plan = { date: now.iso, at: null, lessonsEnd: null, todaySchool: false, source: 'off', scope: day.scope, quiet, key, computedAt: Date.now() };
      return this.plan;
    }

    let lessonsEnd = null;
    let source;
    try {
      lessonsEnd = await this.homework.lessonsEnd(now.iso, { fresh: true });
      source = day.mode === 'time' ? 'fixed' : lessonsEnd != null ? 'lessons' : 'fallback';
    } catch (error) {
      if (plan) return plan; // BilimClass временно недоступен — оставляем прежний план
      source = day.mode === 'time' ? 'fixed' : 'error';
    }
    const at = source === 'lessons' ? Math.min(lessonsEnd + schedule.digestDelayMinutes, 23 * 60 + 59) : day.time ?? null;
    const changed = !plan || plan.at !== at;
    this.plan = { date: now.iso, at, lessonsEnd, todaySchool: lessonsEnd != null, source, scope: day.scope, quiet: null, key, computedAt: Date.now() };
    if (changed && at != null) {
      this.logger.info(
        { at: formatClock(at), lessonsEnd: lessonsEnd != null ? formatClock(lessonsEnd) : null, source, scope: day.scope },
        source === 'lessons' ? 'Рассылка ДЗ сегодня — после уроков' : 'Рассылка ДЗ сегодня — по времени',
      );
    }
    return this.plan;
  }

  // План на неделю словами — для !график и панели
  weekPlanLines() {
    const { schedule } = this.config;
    return [1, 2, 3, 4, 5, 6, 7].map((d) => describeDay(d, schedule.days?.[d], { delay: schedule.digestDelayMinutes }));
  }

  // Ждём ли сегодня рассылку после уроков: тогда новые ДЗ копим для неё, а не шлём по одному
  digestPending(now) {
    const plan = this.plan;
    if (!plan || plan.date !== now.iso || plan.at == null) return false;
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
    await this.sendDigest({ targets, scope: this.config.schedule.days?.[now.weekday]?.scope });
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

  // Рассылка: свежие данные из BilimClass на каждый день недели вперёд → только то, что ещё не присылали.
  // scope 'tomorrow' — только ДЗ на ближайший учебный день (остальное придёт в другие дни как новое).
  // Самая первая рассылка — тоже только «на завтра»: всё, что уже есть в дневнике, бот запоминает, а не вываливает разом.
  async sendDigest({ targets, force = false, scope = 'new' }) {
    const digest = await this.buildDigest({ force, scope });
    if (!digest.messages) return;
    const { data, fresh, firstTime, onlyNext, messages } = digest;

    for (const jid of targets) {
      for (const content of messages) this.wa.send(jid, content, {}, { persist: true }).catch(() => {});
    }
    // «Уже отправлено» запоминаем, только если рассылка ушла во все группы (а не !рассылка в одной из нескольких)
    if (this.digestTargets().every((jid) => targets.includes(jid))) {
      this.markAnnounced(firstTime || !onlyNext ? data.entries : data.entries.filter((e) => e.dueDate === data.next));
    }
    this.core.countUsage?.('digest');
    this.logger.info(
      { groups: targets.length, messages: messages.length, new: fresh.length, total: data.entries.length, firstTime, scope },
      'Рассылка ДЗ отправлена в очередь',
    );
    if (this.config.features.sendFiles) {
      const shown = firstTime ? data.entries.filter((e) => e.dueDate === data.next) : fresh;
      await this.sendFiles(shown.filter((e) => e.hasFiles), targets);
    }
  }

  // Что уйдёт в рассылку (без отправки) — для предпросмотра в панели и терминале
  async buildDigest({ force = false, scope = 'new' } = {}) {
    const data = await this.homework.digestData({ fresh: true });
    const firstTime = !this.store.data.announcedReady;
    const onlyNext = scope === 'tomorrow' || firstTime;
    let fresh = firstTime ? [] : this.classify(data.entries);
    if (onlyNext) fresh = fresh.filter((e) => e.dueDate === data.next);
    const now = this.clock();
    const options = { data, fresh, firstTime, onlyNext, now, force };
    const messages = this.config.features.homeworkImage ? await this.digestPhotos(options) : this.digestText(options);
    return { data, fresh, firstTime, onlyNext, messages };
  }

  // Текстовый вариант рассылки (HOMEWORK_PHOTO=text)
  digestText({ data, fresh, firstTime, now, force }) {
    if (!fresh.length && !firstTime && this.config.schedule.skipEmptyDigest && !force) {
      this.logger.info('Новых ДЗ нет — рассылку пропускаю (SKIP_EMPTY_DIGEST)');
      return null;
    }
    const remindTomorrow = this.config.schedule.remindTomorrow || firstTime;
    const text = formatNewHomework({ fresh, data, remindTomorrow, checkedAt: now.minutes, firstTime });
    return splitMessage(text, 6000).map((part) => ({ text: part }));
  }

  // Рассылка фотографиями: «Домашнее задание на завтра» + отдельное фото на каждый день, где появилось новое ДЗ.
  // Новые и изменённые задания на картинке помечены «НОВОЕ» / «ИЗМЕНЕНО».
  async digestPhotos({ data, fresh, firstTime, onlyNext, now, force }) {
    const marks = firstTime ? new Map() : new Map(fresh.map((e) => [announceKey(e), e.kind]));
    const remind = this.config.schedule.remindTomorrow || firstTime;
    const days = data.days.filter((day) => {
      if (day.date === data.next) return remind || day.entries.some((e) => marks.has(announceKey(e)));
      if (onlyNext) return false;
      return day.entries.some((e) => marks.has(announceKey(e)));
    });
    if (!days.length) {
      if (this.config.schedule.skipEmptyDigest && !force) {
        this.logger.info('Новых ДЗ нет — рассылку пропускаю (SKIP_EMPTY_DIGEST)');
        return null;
      }
      return [{ text: '✅ Проверил дневник после уроков — новых домашних заданий нет.' }];
    }
    const kinds = new Map();
    for (const day of days) {
      const dayMarks = day.entries.map((e) => marks.get(announceKey(e))).filter(Boolean);
      if (day.date !== data.next && dayMarks.length) kinds.set(day.date, dayMarks.every((m) => m === 'changed') ? 'changed' : 'new');
    }
    return this.photos.messages(days, data.today, { kinds, marks, markKey: announceKey, checkedAt: formatClock(now.minutes) });
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
    const total = { added: added.length, changed: changed.length };
    if (firstRun) {
      this.logger.info('Первая проверка дневника: запомнил текущие ДЗ, дальше буду сообщать об изменениях');
      return { added: 0, changed: 0 };
    }
    if (!this.config.schedule.notifyChanges) return total;

    const today = this.homework.today();
    const now = this.clock();
    const quiet = quietReason(this.config.schedule, now.iso, now.weekday);
    if (quiet && !manual) {
      // в «тихий» день ничего не шлём: новое попадёт в следующую рассылку
      if (added.length || changed.length) this.logger.info({ ...total, reason: quiet }, 'Новые ДЗ найдены — пришлю позже');
      return total;
    }
    // ДЗ на сегодня, которое так и не дошло до группы (выставили в «тихий» день, бот был выключен), —
    // срочное, шлём сейчас. Только пока сегодняшняя рассылка впереди: после уроков ДЗ на сегодня уже не нужно.
    const missed = manual || !this.store.data.announcedReady || !this.digestPending(now) ? [] : await this.missedToday(today, [...added, ...changed]);
    if (!added.length && !changed.length && !missed.length) return total;
    // «только на завтра»: задания на дальние дни придут в своей рассылке
    const until = !manual && this.config.schedule.days?.[now.weekday]?.scope === 'tomorrow'
      ? await this.homework.nextSchoolDay(today).catch(() => null)
      : null;
    // Днём, пока не прошла рассылка после уроков, копим новые ДЗ для неё (кроме заданий на сегодня — они срочные).
    // После рассылки (вечером) и в выходные — сообщаем сразу. Уже отправленное в группу второй раз не шлём.
    const hold = !manual && this.digestPending(now);
    const pick = (list) => this.classify(list)
      .filter((e) => !hold || (e.dueDate && e.dueDate <= today))
      .filter((e) => !until || (e.dueDate && e.dueDate <= until));
    const toAdd = [...pick(added), ...missed.filter((e) => e.kind === 'new')];
    const toChange = [...pick(changed), ...missed.filter((e) => e.kind === 'changed')];
    if (missed.length) this.logger.info({ count: missed.length }, 'ДЗ на сегодня ещё не было в группе — отправляю');
    if ((hold || until) && toAdd.length + toChange.length < added.length + changed.length) {
      this.logger.info(total, 'Новые ДЗ найдены — пришлю их в рассылке');
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

  async missedToday(today, known) {
    const seen = new Set(known.map(announceKey));
    try {
      const view = await this.homework.dayView(today);
      return this.classify(view.entries.filter((e) => !e.manual && !seen.has(announceKey(e))));
    } catch {
      return [];
    }
  }

  // Сообщения о новых/изменённых ДЗ: фото дня (с пометками) или текст
  async changeMessages(added, changed, today, now) {
    if (!this.config.features.homeworkImage) return [{ text: formatChanges({ added, changed }, today) }];
    const marks = new Map([...added.map((e) => [announceKey(e), 'new']), ...changed.map((e) => [announceKey(e), 'changed'])]);
    const all = [...added, ...changed];
    const dates = [...new Set(all.map((e) => e.dueDate).filter(Boolean))].sort();
    const views = [];
    const kinds = new Map();
    for (const date of dates) {
      views.push(await this.homework.dayView(date));
      const dayKinds = all.filter((e) => e.dueDate === date).map((e) => marks.get(announceKey(e)));
      kinds.set(date, dayKinds.every((k) => k === 'changed') ? 'changed' : 'new');
    }
    const messages = await this.photos.messages(views, today, { kinds, marks, markKey: announceKey, checkedAt: formatClock(now.minutes) });
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

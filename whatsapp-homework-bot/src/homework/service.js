// Высокоуровневая работа с ДЗ: кэш недель, «следующий учебный день», поиск изменений, контекст для ИИ.
import { createHash } from 'node:crypto';
import { homeworkEntries, normalizeWeek } from '../bilimclass/parse.js';
import { addDays, mondayOf, nowParts, toDM, toDMY, WEEKDAYS, WEEKDAYS_SHORT, weekdayOf } from '../utils/dates.js';
import { normalize, truncate } from '../utils/text.js';
import { findSubjects } from './subjects.js';

const CACHE_TTL_MS = 5 * 60 * 1000;

const MIME = {
  pdf: 'application/pdf', doc: 'application/msword', docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  xls: 'application/vnd.ms-excel', xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  ppt: 'application/vnd.ms-powerpoint', pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  txt: 'text/plain', rtf: 'application/rtf', zip: 'application/zip', rar: 'application/vnd.rar',
  jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', webp: 'image/webp', gif: 'image/gif',
  mp3: 'audio/mpeg', m4a: 'audio/mp4', ogg: 'audio/ogg', mp4: 'video/mp4', mov: 'video/quicktime',
};

export function entryHash(entry) {
  const raw = `${normalize(entry.text)}|${entry.books.map(normalize).join(';')}|${entry.hasFiles ? 1 : 0}`;
  return createHash('sha1').update(raw).digest('hex').slice(0, 12);
}

export class HomeworkService {
  constructor({ client, store, config, logger, now = () => new Date() }) {
    this.client = client;
    this.store = store;
    this.config = config;
    this.logger = logger;
    this.now = now;
    this.cache = new Map(); // monday -> { at, days }
    this.inflight = new Map();
    this.lastSuccessAt = 0;
    this.lastError = null;
  }

  today() {
    return nowParts(this.config.timezone, this.now()).iso;
  }

  async week(mondayIso, { fresh = false } = {}) {
    const cached = this.cache.get(mondayIso);
    if (!fresh && cached && Date.now() - cached.at < CACHE_TTL_MS) return cached.days;
    if (this.inflight.has(mondayIso)) return this.inflight.get(mondayIso);
    const promise = (async () => {
      try {
        const raw = await this.client.getWeek(mondayIso);
        const days = normalizeWeek(raw, mondayIso);
        this.cache.set(mondayIso, { at: Date.now(), days });
        this.lastSuccessAt = Date.now();
        this.lastError = null;
        return days;
      } catch (error) {
        this.lastError = error;
        // если сервер недоступен, лучше показать чуть устаревшие данные, чем ничего
        if (cached && !fresh) {
          this.logger?.warn({ err: error.message }, 'BilimClass недоступен — использую кэш');
          return cached.days;
        }
        throw error;
      } finally {
        this.inflight.delete(mondayIso);
      }
    })();
    this.inflight.set(mondayIso, promise);
    return promise;
  }

  // Все дни в диапазоне [from, to]; дни, которых нет в ответе API, помечены missing
  async days(fromIso, toIso, opts = {}) {
    const mondays = [];
    for (let m = mondayOf(fromIso); m <= toIso; m = addDays(m, 7)) mondays.push(m);
    const weeks = await Promise.all(mondays.map((m) => this.week(m, opts)));
    const byDate = new Map(weeks.flat().map((d) => [d.date, d]));
    const result = [];
    for (let d = fromIso; d <= toIso; d = addDays(d, 1)) {
      result.push(byDate.get(d) || { date: d, isHoliday: false, lessons: [], missing: true });
    }
    return result;
  }

  // Ставим каждому ДЗ дату сдачи (dueDate) в зависимости от того, как школа заполняет дневник
  withDueDates(days) {
    const entries = days.flatMap((day) => homeworkEntries(day));
    if (this.config.features.homeworkAttachedTo === 'due') {
      return entries.map((e) => ({ ...e, dueDate: e.lessonDate }));
    }
    const lessonDates = new Map();
    for (const day of days) {
      for (const lesson of day.lessons) {
        if (!lessonDates.has(lesson.subject)) lessonDates.set(lesson.subject, []);
        lessonDates.get(lesson.subject).push(day.date);
      }
    }
    return entries.map((e) => ({
      ...e,
      dueDate: (lessonDates.get(e.subject) || []).find((d) => d > e.lessonDate) || null,
    }));
  }

  manualEntries(fromIso, toIso) {
    return this.store.data.manual
      .filter((m) => m.date >= fromIso && m.date <= toIso)
      .map((m) => ({
        key: `manual:${m.id}`, id: m.id, manual: true, author: m.author,
        lessonDate: m.date, dueDate: m.date, subject: m.subject, text: m.text, books: [], hasFiles: false, uuid: null, start: '',
      }));
  }

  // ДЗ со сроком сдачи в диапазоне дат
  async entriesDue(fromIso, toIso, opts = {}) {
    const lookBack = this.config.features.homeworkAttachedTo === 'assigned' ? 14 : 0;
    const days = await this.days(addDays(fromIso, -lookBack), toIso, opts);
    const fromDiary = this.withDueDates(days).filter((e) => e.dueDate && e.dueDate >= fromIso && e.dueDate <= toIso);
    return [...fromDiary, ...this.manualEntries(fromIso, toIso)];
  }

  async dayView(iso, opts = {}) {
    const [day] = await this.days(iso, iso, opts);
    const entries = (await this.entriesDue(iso, iso, opts)).sort((a, b) => (a.start || '99').localeCompare(b.start || '99'));
    return { ...day, entries };
  }

  async isSchoolDay(iso) {
    const [day] = await this.days(iso, iso);
    return !day.isHoliday && day.lessons.length > 0;
  }

  // Ближайший день после afterIso, когда есть уроки (пропускает выходные и каникулы)
  async nextSchoolDay(afterIso, maxDays = 21) {
    for (let offset = 1; offset <= maxDays; offset += 7) {
      const from = addDays(afterIso, offset);
      const to = addDays(afterIso, Math.min(offset + 6, maxDays));
      const days = await this.days(from, to);
      const found = days.find((d) => !d.isHoliday && d.lessons.length > 0);
      if (found) return found.date;
    }
    return null;
  }

  async weekView(mondayIso) {
    const sunday = addDays(mondayIso, 6);
    const days = await this.days(mondayIso, sunday);
    const entries = await this.entriesDue(mondayIso, sunday);
    return days.map((day) => ({ ...day, entries: entries.filter((e) => e.dueDate === day.date) }));
  }

  // ДЗ по предмету: ближайшее предстоящее и последнее прошедшее
  async findSubject(query) {
    const today = this.today();
    const from = addDays(today, -14);
    const to = addDays(today, 14);
    const days = await this.days(from, to);
    const known = [...new Set([...days.flatMap((d) => d.lessons.map((l) => l.subject)), ...this.store.data.manual.map((m) => m.subject)])];
    const subjects = findSubjects(query, known);
    if (!subjects.length) return { subjects: [], upcoming: [], last: null, nextLesson: null };
    const entries = (await this.entriesDue(from, to)).filter((e) => subjects.includes(e.subject));
    const upcoming = entries.filter((e) => e.dueDate >= today).sort((a, b) => a.dueDate.localeCompare(b.dueDate));
    const past = entries.filter((e) => e.dueDate < today).sort((a, b) => b.dueDate.localeCompare(a.dueDate));
    const nextLesson = days.find((d) => d.date >= today && d.lessons.some((l) => subjects.includes(l.subject)))?.date || null;
    return { subjects, upcoming, last: past[0] || null, nextLesson };
  }

  // Проверка дневника на новые/изменённые ДЗ. Первый запуск только запоминает текущее состояние.
  async pollChanges() {
    const today = this.today();
    const from = addDays(today, -2);
    const to = addDays(today, 9);
    const days = await this.days(from, to, { fresh: true });
    const snapshots = this.store.data.snapshots;
    const firstRun = !this.store.data.baselineReady;
    const added = [];
    const changed = [];
    const updates = {};

    const dueByKey = new Map(this.withDueDates(days).map((e) => [`${e.lessonDate}|${e.key}`, e.dueDate]));

    for (const day of days) {
      if (day.missing) continue;
      const previous = snapshots[day.date];
      const entries = homeworkEntries(day);
      // защита от сбоев API: день внезапно стал пустым — не затираем снимок, иначе потом будет спам «новых» ДЗ
      if (previous && Object.keys(previous).length && !day.lessons.length) continue;
      const current = {};
      for (const entry of entries) {
        const hash = entryHash(entry);
        current[entry.key] = hash;
        if (firstRun || !previous) continue;
        const dueDate = dueByKey.get(`${entry.lessonDate}|${entry.key}`) || null;
        const relevant = dueDate ? dueDate >= today : entry.lessonDate >= addDays(today, -2);
        if (!relevant) continue;
        if (!(entry.key in previous)) added.push({ ...entry, dueDate });
        else if (previous[entry.key] !== hash) changed.push({ ...entry, dueDate });
      }
      updates[day.date] = current;
    }

    this.store.update((s) => {
      Object.assign(s.snapshots, updates);
      s.baselineReady = true;
    });
    return { added, changed, firstRun };
  }

  async filesFor(entry) {
    if (!entry.hasFiles || !entry.uuid) return [];
    const files = await this.client.getHomeworkFiles(entry.uuid);
    return files.map((f) => {
      const ext = String(f.extension || (f.name || '').split('.').pop() || '').toLowerCase().replace(/[^a-z0-9]/g, '');
      let name = String(f.name || 'Файл').replace(/[\x00-\x1f\x7f/\\]/g, '_').trim().slice(0, 150) || 'Файл';
      if (ext && !name.toLowerCase().endsWith(`.${ext}`)) name += `.${ext}`;
      return { name, ext, size: Number(f.sizeInBytes) || 0, link: f.link, mimetype: MIME[ext] || 'application/octet-stream', key: `${entry.uuid}:${f.uuid || f.id || name}` };
    });
  }

  async downloadFile(file) {
    const maxBytes = this.config.features.maxFileMb * 1024 * 1024;
    if (file.size > maxBytes) throw new Error(`файл больше ${this.config.features.maxFileMb} МБ`);
    const url = new URL(file.link);
    if (url.protocol !== 'https:') throw new Error('небезопасная ссылка на файл');
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 120000);
    try {
      const response = await fetch(url, { signal: controller.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status} при скачивании файла`);
      const length = Number(response.headers.get('content-length') || 0);
      if (length > maxBytes) throw new Error(`файл больше ${this.config.features.maxFileMb} МБ`);
      const buffer = Buffer.from(await response.arrayBuffer());
      if (buffer.length > maxBytes) throw new Error(`файл больше ${this.config.features.maxFileMb} МБ`);
      return buffer;
    } finally {
      clearTimeout(timer);
    }
  }

  // Компактная сводка для нейросети: что задано на ближайшие дни и что было недавно
  async aiContext() {
    const today = this.today();
    const from = addDays(today, -3);
    const to = addDays(today, 7);
    let days;
    let entries;
    try {
      days = await this.days(from, to);
      entries = await this.entriesDue(from, to);
    } catch (error) {
      return `Дневник BilimClass сейчас недоступен (${error.message}). Не выдумывай ДЗ — скажи, что дневник временно недоступен.`;
    }
    const session = this.client.session || {};
    const lines = [
      `Сегодня: ${WEEKDAYS[weekdayOf(today) - 1]}, ${toDMY(today)}.`,
      session.className ? `Класс: ${session.className}${session.schoolName ? `, ${session.schoolName}` : ''}.` : '',
      '',
      'Домашние задания из электронного дневника BilimClass (дата = к какому дню сделать):',
    ];
    let budget = 7000; // ограничиваем размер контекста
    for (const day of days) {
      const dayEntries = entries.filter((e) => e.dueDate === day.date);
      if (!dayEntries.length || budget <= 0) continue;
      const label = `${WEEKDAYS_SHORT[weekdayOf(day.date) - 1]} ${toDM(day.date)}${day.date === today ? ' (сегодня)' : day.date < today ? ' (прошло)' : ''}`;
      lines.push(`[${label}]`);
      for (const e of dayEntries) {
        const parts = [e.text, ...e.books.map((b) => `учебник: ${b}`), e.hasFiles ? '(есть прикреплённый файл)' : ''].filter(Boolean);
        const line = `- ${e.subject}: ${truncate(parts.join('; ') || 'задание без текста', 500)}`;
        budget -= line.length;
        lines.push(line);
      }
    }
    if (!entries.length) lines.push('(в дневнике на эти дни ДЗ нет)');

    const nextDays = days.filter((d) => d.date >= today && d.lessons.length).slice(0, 3);
    if (nextDays.length) {
      lines.push('', 'Расписание ближайших учебных дней:');
      for (const day of nextDays) {
        const lessons = day.lessons.map((l, i) => `${i + 1}) ${l.subject}${l.start ? ` ${l.start}` : ''}${l.theme ? ` — тема: ${truncate(l.theme, 80)}` : ''}`);
        lines.push(`[${WEEKDAYS_SHORT[weekdayOf(day.date) - 1]} ${toDM(day.date)}] ${lessons.join('; ')}`);
      }
    }
    return lines.filter((l, i) => l || lines[i - 1]).join('\n');
  }

  // Предметы, которые встречаются в расписании (для распознавания вопросов про ДЗ)
  async knownSubjects() {
    try {
      const today = this.today();
      const days = await this.days(addDays(today, -7), addDays(today, 7));
      return [...new Set(days.flatMap((d) => d.lessons.map((l) => l.subject)))];
    } catch {
      return [];
    }
  }

  status() {
    return { lastSuccessAt: this.lastSuccessAt, lastError: this.lastError?.message || null, session: this.client.session };
  }
}

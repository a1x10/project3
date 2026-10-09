// Превращаем «сырой» ответ дневника BilimClass в удобную структуру.
import { addDays, parseApiDate } from '../utils/dates.js';
import { htmlToText } from '../utils/text.js';

function clockTimes(timeslot) {
  const raw = typeof timeslot === 'string' ? timeslot : JSON.stringify(timeslot ?? '');
  return (raw.match(/(?<!\d)(?:[01]?\d|2[0-3]):[0-5]\d/g) || []).slice(0, 2).map((t) => t.padStart(5, '0'));
}

const BOOK_FIELDS = [
  ['paragraph', '§'], ['paragraphs', '§'],
  ['pages', 'стр.'], ['page', 'стр.'],
  ['exercises', 'упр.'], ['exercise', 'упр.'],
  ['tasks', '№'], ['task', '№'], ['numbers', '№'],
  ['description', ''], ['comment', ''], ['text', ''], ['body', ''],
];

// Задания из учебника приходят отдельным полем — формат точно не документирован, разбираем осторожно
export function formatBooks(books) {
  if (!books) return [];
  const list = Array.isArray(books) ? books : [books];
  const result = [];
  for (const book of list) {
    if (book == null || book === '') continue;
    if (typeof book === 'string' || typeof book === 'number') {
      const text = htmlToText(book);
      if (text) result.push(text);
      continue;
    }
    if (typeof book !== 'object') continue;
    const title = book.name || book.title || book.bookName || book.book?.name || book.book?.title || '';
    const details = [];
    for (const [key, label] of BOOK_FIELDS) {
      const value = book[key];
      if (value == null || value === '' || (Array.isArray(value) && !value.length)) continue;
      const text = Array.isArray(value) ? value.join(', ') : htmlToText(value);
      if (text) details.push(label ? `${label} ${text}` : text);
    }
    const line = [htmlToText(title), ...details].filter(Boolean).join(', ');
    result.push(line || 'задание в учебнике (подробности в BilimClass)');
  }
  return [...new Set(result)];
}

function normalizeLesson(raw, index) {
  const times = clockTimes(raw.timeslot ?? raw.time ?? raw.timeSlot);
  const text = htmlToText(raw.homeworkBody ?? raw.homework ?? '');
  const books = formatBooks(raw.homeworkBooks);
  const hasFiles = Boolean(raw.hasFiles);
  return {
    index,
    subject: htmlToText(raw.label || raw.subjectName || raw.subject || 'Урок'),
    start: times[0] || '',
    end: times[1] || '',
    teacher: htmlToText(raw.teacherFio || ''),
    cabinet: htmlToText(raw.cabinet || ''),
    theme: htmlToText(raw.theme || ''),
    homework: text || books.length || hasFiles ? { text, books, hasFiles, uuid: raw.homeworkUuid || null } : null,
  };
}

// raw — data из /clientoffice/diary, mondayIso — понедельник запрошенной недели
export function normalizeWeek(raw, mondayIso) {
  const rows = Array.isArray(raw?.days) ? raw.days : [];
  return rows.map((row, position) => {
    // дата вида "29 сентября" — без года; если не разобрали, берём по порядку дней недели
    const date = parseApiDate(row?.date, addDays(mondayIso, 3)) || addDays(mondayIso, position);
    const lessons = (Array.isArray(row?.subjects) ? row.subjects : []).map(normalizeLesson);
    return { date, isHoliday: Boolean(row?.isHoliday), lessons: row?.isHoliday ? [] : lessons };
  });
}

// Плоский список ДЗ дня. key устойчив к перестановке уроков: "предмет#номер_вхождения"
export function homeworkEntries(day) {
  const seen = new Map();
  const entries = [];
  for (const lesson of day.lessons) {
    const count = (seen.get(lesson.subject) || 0) + 1;
    seen.set(lesson.subject, count);
    if (!lesson.homework) continue;
    entries.push({
      key: `${lesson.subject}#${count}`,
      lessonDate: day.date,
      subject: lesson.subject,
      start: lesson.start,
      ...lesson.homework,
    });
  }
  // сдвоенные уроки часто дублируют одно и то же ДЗ — оставляем одно
  const unique = [];
  const texts = new Set();
  for (const entry of entries) {
    const signature = `${entry.subject}|${entry.text}|${entry.books.join(';')}|${entry.uuid || ''}`;
    if (texts.has(signature)) continue;
    texts.add(signature);
    unique.push(entry);
  }
  return unique;
}

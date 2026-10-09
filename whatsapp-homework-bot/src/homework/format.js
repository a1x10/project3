// Оформление сообщений для WhatsApp (*жирный*, _курсив_).
import { addDays, formatClock, humanDay, onDay, toDM, WEEKDAYS_SHORT, weekdayOf } from '../utils/dates.js';
import { truncate } from '../utils/text.js';

const lessonWord = (n) => {
  if (n % 10 === 1 && n % 100 !== 11) return 'урок';
  if (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14)) return 'урока';
  return 'уроков';
};

function entryBody(entry, maxLen = 1500) {
  const lines = [];
  if (entry.text) lines.push(truncate(entry.text, maxLen));
  for (const book of entry.books) lines.push(`📖 ${book}`);
  if (entry.hasFiles) lines.push('📎 К заданию прикреплён файл');
  if (entry.manual) lines.push(`_✍️ добавлено вручную${entry.author ? ` (${entry.author})` : ''}_`);
  if (!lines.length) lines.push('_задание без текста — смотрите в BilimClass_');
  return lines.join('\n');
}

// ДЗ на один день
export function formatDay(view, todayIso, { footer = true, title } = {}) {
  const heading = title || `📚 *ДЗ ${onDay(view.date, todayIso)}*`;
  if (view.isHoliday) return `${heading}\n\n🏖 В дневнике этот день отмечен как выходной/праздник.`;
  if (!view.lessons.length && !view.entries.length) {
    return `${heading}\n\nВ дневнике на этот день нет уроков.`;
  }
  const lines = [heading];
  if (!view.entries.length) {
    lines.push('', 'Домашнего задания в дневнике пока нет 🎉');
  } else {
    view.entries.forEach((entry, i) => {
      lines.push('', `*${i + 1}. ${entry.subject}*`, entryBody(entry));
    });
  }
  const withHomework = new Set(view.entries.map((e) => e.subject));
  const without = [...new Set(view.lessons.map((l) => l.subject))].filter((s) => !withHomework.has(s));
  if (view.entries.length && without.length) lines.push('', `_Без ДЗ: ${without.join(', ')}_`);
  if (footer) lines.push('', '💬 Есть вопрос по заданию? Напишите в чат — помогу разобраться.');
  return lines.join('\n');
}

// Расписание на день
export function formatSchedule(view, todayIso) {
  const heading = `🗓 *Расписание ${onDay(view.date, todayIso)}*`;
  if (view.isHoliday) return `${heading}\n\n🏖 Выходной/праздник.`;
  if (!view.lessons.length) return `${heading}\n\nУроков нет.`;
  const homeworkSubjects = new Set(view.entries.map((e) => e.subject));
  const lines = [heading, `${view.lessons.length} ${lessonWord(view.lessons.length)}`, ''];
  view.lessons.forEach((lesson, i) => {
    const time = lesson.start ? `${lesson.start}${lesson.end ? `–${lesson.end}` : ''} ` : '';
    const room = lesson.cabinet ? ` · каб. ${lesson.cabinet}` : '';
    const hw = homeworkSubjects.has(lesson.subject) ? ' 📝' : '';
    lines.push(`${i + 1}. ${time}*${lesson.subject}*${room}${hw}`);
  });
  if (homeworkSubjects.size) lines.push('', '📝 — есть ДЗ (команда: !дз)');
  return lines.join('\n');
}

// ДЗ на неделю — коротко
export function formatWeek(weekDays, todayIso) {
  const monday = weekDays[0]?.date;
  const lines = [`🗓 *ДЗ на неделю ${toDM(monday)}–${toDM(addDays(monday, 6))}*`];
  let any = false;
  for (const day of weekDays) {
    if (!day.entries.length && !day.lessons.length) continue;
    const mark = day.date === todayIso ? ' (сегодня)' : '';
    lines.push('', `*${WEEKDAYS_SHORT[weekdayOf(day.date) - 1]} ${toDM(day.date)}${mark}*`);
    if (day.isHoliday) {
      lines.push('🏖 выходной');
      continue;
    }
    if (!day.entries.length) {
      lines.push('— без ДЗ');
      continue;
    }
    any = true;
    for (const entry of day.entries) {
      const extra = [entry.books.length ? '📖' : '', entry.hasFiles ? '📎' : ''].join('');
      const short = (entry.text || entry.books[0] || 'см. BilimClass').replace(/\s*\n+\s*/g, '; ');
      lines.push(`• *${entry.subject}:* ${truncate(short, 220)}${extra ? ` ${extra}` : ''}`);
    }
  }
  if (!any) lines.push('', 'На эту неделю ДЗ в дневнике нет.');
  return lines.join('\n');
}

// Уведомление о новых/изменённых ДЗ
export function formatChanges({ added, changed }, todayIso) {
  const items = [...added.map((e) => ({ ...e, kind: 'new' })), ...changed.map((e) => ({ ...e, kind: 'changed' }))]
    .sort((a, b) => (a.dueDate || '9999').localeCompare(b.dueDate || '9999'));
  if (!items.length) return null;
  const lines = [items.length === 1 ? '🔔 *Новое в дневнике*' : `🔔 *Обновления в дневнике (${items.length})*`];
  for (const e of items) {
    const when = e.dueDate ? onDay(e.dueDate, todayIso) : 'к следующему уроку';
    const icon = e.kind === 'new' ? '🆕' : '✏️';
    const note = e.kind === 'changed' ? ' _(изменено)_' : '';
    lines.push('', `${icon} *${e.subject}* — ${when}${note}`, entryBody(e, 1000));
  }
  return lines.join('\n');
}

// Ответ на "!дз алгебра"
export function formatSubject(result, query, todayIso) {
  if (!result.subjects.length) {
    return `🤔 Не нашёл предмет «${query}» в расписании. Напишите название точнее, например: !дз алгебра`;
  }
  const name = result.subjects.join(' / ');
  const lines = [`📘 *${name}*`];
  if (result.upcoming.length) {
    for (const e of result.upcoming.slice(0, 2)) {
      lines.push('', `*ДЗ ${onDay(e.dueDate, todayIso)}:*`, entryBody(e));
    }
  } else {
    lines.push('', 'Предстоящего ДЗ в дневнике пока нет.');
    if (result.nextLesson) lines.push(`Следующий урок: ${humanDay(result.nextLesson, todayIso)}.`);
    if (result.last) lines.push('', `Последнее ДЗ было ${onDay(result.last.dueDate, todayIso)}:`, entryBody(result.last, 600));
  }
  return lines.join('\n');
}

const capital = (text) => text.charAt(0).toUpperCase() + text.slice(1);
const QUESTION_HINT = '💬 Есть вопрос по заданию? Напишите в чат — помогу разобраться.';

function dayTitle(iso, todayIso) {
  return capital(humanDay(iso, todayIso));
}

// Ежедневное сообщение после уроков: только новые/изменённые задания + короткое напоминание на завтра
// fresh: [{ ...entry, kind: 'new' | 'changed' }], data: результат HomeworkService.digestData()
export function formatNewHomework({ fresh, data, remindTomorrow = true, checkedAt }) {
  const { today } = data;
  const lines = [`📚 *Домашнее задание · ${WEEKDAYS_SHORT[weekdayOf(today) - 1]} ${toDM(today)}*`];
  lines.push(`_Проверил дневник BilimClass${checkedAt != null ? ` в ${formatClock(checkedAt)}` : ''} — данные свежие_`);

  if (fresh.length) {
    const anyChanged = fresh.some((e) => e.kind === 'changed');
    const title = anyChanged ? 'Новые и изменённые задания' : fresh.length === 1 ? 'Новое задание' : 'Новые задания';
    lines.push('', `🆕 *${title}${fresh.length > 1 ? ` (${fresh.length})` : ''}:*`);
    for (const e of fresh) {
      const note = e.kind === 'changed' ? ' ✏️ _изменено_' : '';
      lines.push('', `*${e.subject}* — ${onDay(e.dueDate, today)}${note}`, entryBody(e, 1500));
    }
  } else {
    lines.push('', '✅ Новых заданий в дневнике с прошлой проверки нет.');
  }

  if (remindTomorrow && data.next) {
    const nextDay = data.days.find((d) => d.date === data.next);
    const freshKeys = new Set(fresh.map((e) => `${e.lessonDate}|${e.key}`));
    const rest = (nextDay?.entries || []).filter((e) => !freshKeys.has(`${e.lessonDate}|${e.key}`));
    if (rest.length) {
      lines.push('', `📌 *Не забудьте ${onDay(data.next, today)}:*`);
      for (const e of rest) {
        const short = (e.text || e.books[0] || 'см. BilimClass').replace(/\s*\n+\s*/g, '; ');
        lines.push(`• *${e.subject}:* ${truncate(short, 160)}${e.hasFiles ? ' 📎' : ''}`);
      }
    } else if (nextDay && !nextDay.entries.length) {
      lines.push('', `📌 ${capital(onDay(data.next, today))} — ДЗ в дневнике нет 🎉`);
    }
  }
  lines.push('', QUESTION_HINT);
  return lines.join('\n');
}

// Самая первая рассылка: полная картина на неделю вперёд (дальше — только новое)
export function formatWeekAhead(data) {
  const { today } = data;
  const lines = ['📚 *Домашнее задание на неделю вперёд*', '_Дальше буду присылать после уроков только новые задания._'];
  for (const day of data.days) {
    lines.push('', `━━ *${dayTitle(day.date, today)}* ━━`);
    if (!day.entries.length) {
      lines.push('ДЗ пока нет');
      continue;
    }
    day.entries.forEach((e, i) => lines.push(`*${i + 1}. ${e.subject}*`, entryBody(e, 800)));
  }
  if (!data.days.length) lines.push('', 'В ближайшие дни уроков в дневнике нет.');
  lines.push('', QUESTION_HINT);
  return lines.join('\n');
}


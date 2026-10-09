// Работа с датами в часовом поясе школы. Внутри бота дата — строка 'YYYY-MM-DD'.

const DAY_MS = 86400000;

export const WEEKDAYS = ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье'];
export const WEEKDAYS_ACC = ['понедельник', 'вторник', 'среду', 'четверг', 'пятницу', 'субботу', 'воскресенье'];
export const WEEKDAYS_SHORT = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

const MONTHS = {
  января: 1, февраля: 2, марта: 3, апреля: 4, мая: 5, июня: 6,
  июля: 7, августа: 8, сентября: 9, октября: 10, ноября: 11, декабря: 12,
  январь: 1, февраль: 2, март: 3, апрель: 4, май: 5, июнь: 6,
  июль: 7, август: 8, сентябрь: 9, октябрь: 10, ноябрь: 11, декабрь: 12,
  // казахские названия — на случай, если API вернёт даты на казахском
  қаңтар: 1, ақпан: 2, наурыз: 3, сәуір: 4, мамыр: 5, маусым: 6,
  шілде: 7, тамыз: 8, қыркүйек: 9, қазан: 10, қараша: 11, желтоқсан: 12,
};

const WEEKDAY_WORDS = [
  ['понедельник', 'пн', 'пон', 'дүйсенбі'],
  ['вторник', 'вт', 'втор', 'сейсенбі'],
  ['среда', 'среду', 'ср', 'сәрсенбі'],
  ['четверг', 'чт', 'чет', 'бейсенбі'],
  ['пятница', 'пятницу', 'пт', 'пят', 'жұма'],
  ['суббота', 'субботу', 'сб', 'суб', 'сенбі'],
  ['воскресенье', 'вс', 'воск', 'жексенбі'],
];

const pad = (n) => String(n).padStart(2, '0');

// Текущая дата/время в заданном часовом поясе
export function nowParts(timeZone, date = new Date()) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-GB', {
      timeZone, year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
    }).formatToParts(date).map((p) => [p.type, p.value]),
  );
  const iso = `${parts.year}-${parts.month}-${parts.day}`;
  return { iso, minutes: Number(parts.hour) * 60 + Number(parts.minute), weekday: weekdayOf(iso) };
}

const toUtc = (iso) => Date.parse(`${iso}T00:00:00Z`);
const fromUtc = (ms) => new Date(ms).toISOString().slice(0, 10);

export const addDays = (iso, n) => fromUtc(toUtc(iso) + n * DAY_MS);
export const diffDays = (a, b) => Math.round((toUtc(a) - toUtc(b)) / DAY_MS);
// 1 = понедельник ... 7 = воскресенье
export const weekdayOf = (iso) => ((new Date(toUtc(iso)).getUTCDay() + 6) % 7) + 1;
export const mondayOf = (iso) => addDays(iso, 1 - weekdayOf(iso));
export const toDMY = (iso) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}`;
export const toDM = (iso) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}`;

function validIso(y, m, d) {
  const iso = `${y}-${pad(m)}-${pad(d)}`;
  return Number.isNaN(toUtc(iso)) || fromUtc(toUtc(iso)) !== iso ? null : iso;
}

// Дата без года — выбираем год, ближайший к опорной дате (учитывает переход через Новый год)
function nearestYear(month, day, anchorIso) {
  const year = Number(anchorIso.slice(0, 4));
  const candidates = [year - 1, year, year + 1].map((y) => validIso(y, month, day)).filter(Boolean);
  if (!candidates.length) return null;
  return candidates.sort((a, b) => Math.abs(diffDays(a, anchorIso)) - Math.abs(diffDays(b, anchorIso)))[0];
}

// Разбор дат из API: '29.09.2026', '2026-09-29', '29 сентября', '29 сентября 2026'
export function parseApiDate(value, anchorIso) {
  if (typeof value !== 'string') return null;
  const text = value.trim().toLowerCase();
  let m = /^(\d{1,2})\.(\d{1,2})\.(\d{4})$/.exec(text);
  if (m) return validIso(m[3], m[2], m[1]);
  m = /^(\d{4})-(\d{2})-(\d{2})/.exec(text);
  if (m) return validIso(m[1], m[2], m[3]);
  m = /^(\d{1,2})\s+([a-zа-яёәіңғүұқөһ]+)\.?(?:\s+(\d{4}))?/.exec(text);
  if (m && MONTHS[m[2]]) {
    return m[3] ? validIso(m[3], MONTHS[m[2]], m[1]) : nearestYear(MONTHS[m[2]], Number(m[1]), anchorIso);
  }
  return null;
}

// Разбор дня из команды пользователя: "завтра", "пн", "пятницу", "15.10", "15 октября"
export function parseDayArg(input, todayIso) {
  const text = String(input || '').trim().toLowerCase().replace(/[!?.,]+$/g, '');
  if (!text) return null;
  if (/^(сегодня|бүгін|today)$/.test(text)) return todayIso;
  if (/^(завтра|ертең|tomorrow)$/.test(text)) return addDays(todayIso, 1);
  if (/^послезавтра$/.test(text)) return addDays(todayIso, 2);
  if (/^(вчера|кеше|yesterday)$/.test(text)) return addDays(todayIso, -1);
  const word = text.replace(/^(на|в|во|за)\s+/, '');
  const index = WEEKDAY_WORDS.findIndex((words) => words.includes(word));
  if (index >= 0) {
    // ближайший такой день, начиная с сегодняшнего
    const shift = (index + 1 - weekdayOf(todayIso) + 7) % 7;
    return addDays(todayIso, shift);
  }
  let m = /^(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?$/.exec(word);
  if (m) {
    if (m[3]) return validIso(m[3].length === 2 ? `20${m[3]}` : m[3], m[2], m[1]);
    return nearestYear(Number(m[2]), Number(m[1]), todayIso);
  }
  m = /^(\d{1,2})\s+([а-яё]+)$/.exec(word);
  if (m && MONTHS[m[2]]) return nearestYear(MONTHS[m[2]], Number(m[1]), todayIso);
  return null;
}

// "завтра, вторник 14.10" / "среда 15.10"
export function humanDay(iso, todayIso) {
  const base = `${WEEKDAYS[weekdayOf(iso) - 1]}, ${toDM(iso)}`;
  const delta = diffDays(iso, todayIso);
  if (delta === 0) return `сегодня (${base})`;
  if (delta === 1) return `завтра (${base})`;
  if (delta === 2) return `послезавтра (${base})`;
  return base;
}

// Целевая дата для "на ..." — "на завтра (вторник, 14.10)"
export function onDay(iso, todayIso) {
  const delta = diffDays(iso, todayIso);
  const base = `${WEEKDAYS_ACC[weekdayOf(iso) - 1]}, ${toDM(iso)}`;
  if (delta === 0) return `на сегодня, ${base}`;
  if (delta === 1) return `на завтра, ${base}`;
  return `на ${base}`;
}

export const formatClock = (minutes) => `${pad(Math.floor(minutes / 60))}:${pad(minutes % 60)}`;

// Просьбы обычными словами, без «!»: «скинь дз на завтра», «что задали по алгебре», «какие уроки в пятницу».
// Распознаём только явные просьбы — всё остальное (как решить, объясни, проверь) отвечает ИИ.
import { parseDayArg } from '../utils/dates.js';
import { normalize } from '../utils/text.js';

const HOMEWORK = /(^|\s)(дз|д\/з|домашк\S*|домашн\S*|задал\S*|задани\S*|задано|тапсырма\S*|үй\s*жұмыс\S*|hw)(?=\s|$)/;
const SCHEDULE = /(^|\s)(расписани\S*|какие\s+уроки|сколько\s+уроков|уроки\s+(на|в|во)?\s*\S+|кесте\S*|сабақтар\S*)(?=\s|$)/;
const FILES = /(^|\s)(файл\S*)(?=\s|$)/;
const WEEK = /(^|\s)(на\s+(всю\s+)?недел\S*|за\s+недел\S*|недел[юя])(?=\s|$)/;
const NEXT_WEEK = /(след\S*|следующ\S*|келесі)\s+недел/;
// просьба «покажи / скинь / что задали», а не вопрос «как решить»
const ASK = /(^|\s)(скин\S*|кин\S*|пришл\S*|присыл\S*|отправ\S*|покаж\S*|дай\S*|скажи\S*|напиш\S*|что|чт[оё]|че|чо|шо|какое|какие|какая|какой|есть\s+ли|есть|много\s+ли|не\s+знаешь|знаешь|подскаж\S*|қандай|бар\s+ма|send|show)(?=\s|$)/;
// это разговор о ДЗ, а не просьба его показать: «я сделал дз», «кто сделал?», «дз не получается»
const CHAT = /(^|\s)(кто|я|мы|сделал\S*|сдела\S*|сдал\S*|списа\S*|получа\S*|успел\S*|забыл\S*|ненавиж\S*|надоел\S*)(?=\s|$)/;
// сообщение — просто «дз» / «домашка?» / «дз завтра»
const BARE = /^(дз|домашка|домашку|домашнее|домашнее задание|задание|задания|тапсырма)(\s+(на\s+)?\S+)?$/;
const HELP = /(^|\s)(как\s+(решить|сделать|делать|выполнить|написать|найти|понять)|реши\S*|объясн\S*|помоги\S*|помог\S*|проверь\S*|почему|зачем|переведи\S*|не\s+понима\S*|не\s+пойму|түсіндір\S*)(?=\s|$)/;

const DAY_WORDS = [
  'сегодня', 'завтра', 'послезавтра', 'вчера', 'бүгін', 'ертең',
  'понедельник', 'вторник', 'среда', 'среду', 'четверг', 'пятница', 'пятницу', 'суббота', 'субботу', 'воскресенье',
  'пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс',
];

// «к понедельнику», «к пятнице»
const DATIVE = { понедельнику: 'понедельник', вторнику: 'вторник', среде: 'среда', четвергу: 'четверг', пятнице: 'пятница', субботе: 'суббота', воскресенью: 'воскресенье' };

// День из фразы: «на завтра», «в пятницу», «на 20.10», «к понедельнику»
export function findDay(text, todayIso) {
  const norm = normalize(text);
  const date = /(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?)/.exec(text);
  if (date) return parseDayArg(date[1], todayIso);
  for (const word of norm.split(' ')) {
    if (DAY_WORDS.includes(word)) return parseDayArg(word, todayIso);
    if (DATIVE[word]) return parseDayArg(DATIVE[word], todayIso);
  }
  return null;
}

// Предмет из фразы «что задали по алгебре» / «дз по англу»
function findSubjectQuery(norm) {
  const m = /(^|\s)(по|по-)\s*([а-яёәіңғүұқөһa-z][а-яёәіңғүұқөһa-z-]{2,})(\s+[а-яёәіңғүұқөһa-z-]{3,})?/.exec(norm);
  if (!m) return null;
  if (DAY_WORDS.includes(m[3]) || /^(завтра|сегодня|недел)/.test(m[3])) return null;
  // второе слово — только если это часть названия предмета: «русскому языку», «всемирной истории»
  const second = m[4]?.trim();
  return second && /^(язык|яз|литератур|культур|истори|мир|казахстан|труд|грамот|тіл|әдебиет)/.test(second) ? `${m[3]} ${second}` : m[3];
}

/**
 * Распознать просьбу. Возвращает { name: 'homework' | 'week' | 'schedule' | 'files', args } или null.
 * args — в том же формате, что у команд (!дз завтра, !дз алгебра, !неделя след, !расписание пт).
 */
export function detectIntent(text, todayIso) {
  const raw = String(text || '').trim();
  if (!raw || raw.length > 120 || raw.startsWith('!') || raw.startsWith('/')) return null;
  const norm = normalize(raw.replace(/д\/з/gi, 'дз'));
  if (HELP.test(norm)) return null; // «как решить…», «объясни…» — это к ИИ

  const day = findDay(raw, todayIso);
  const dayArg = day ? `${day.slice(8, 10)}.${day.slice(5, 7)}` : '';

  if (HOMEWORK.test(norm)) {
    if (CHAT.test(norm) && !/(^|\s)(скин|кин|пришл|отправ|покаж)/.test(norm)) return null;
    const subject = findSubjectQuery(norm);
    const asking = ASK.test(norm) || raw.includes('?') || day || subject || WEEK.test(norm) || BARE.test(norm);
    if (!asking) return null;
    if (FILES.test(norm)) return { name: 'files', args: dayArg };
    if (WEEK.test(norm) || NEXT_WEEK.test(norm)) return { name: 'week', args: NEXT_WEEK.test(norm) ? 'след' : '' };
    if (subject && !day) return { name: 'homework', args: subject };
    return { name: 'homework', args: dayArg };
  }
  if (SCHEDULE.test(norm) && (ASK.test(norm) || raw.includes('?') || day || /^(расписание|уроки|кесте)(\s+\S+)?$/.test(norm))) {
    return { name: 'schedule', args: dayArg };
  }
  return null;
}

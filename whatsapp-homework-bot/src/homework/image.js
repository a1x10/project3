// Рисуем ДЗ на день в виде картинки-карточки (JPEG), чтобы отправить в WhatsApp как фото.
// Шрифты лежат в assets/fonts (Noto Sans + Noto Sans Math для формул), системные шрифты не нужны.
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { diffDays, weekdayOf, WEEKDAYS, WEEKDAYS_ACC } from '../utils/dates.js';

const FONTS_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../assets/fonts');
const FAMILY = '"Noto Sans", "Noto Sans Math"';
const MONTHS_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];

const W = 1080;
const PAD = 48; // отступ карточек от краёв
const INNER = 36; // отступ текста внутри карточки
const MAX_HEIGHT = 6000;
const MAX_LINES_PER_ENTRY = 18;

const COLORS = {
  headerFrom: '#4F46E5',
  headerTo: '#7C3AED',
  bg: '#F1F5F9',
  card: '#FFFFFF',
  title: '#0F172A',
  text: '#1F2937',
  muted: '#64748B',
  faint: '#94A3B8',
  file: '#2563EB',
  newBg: '#DCFCE7',
  newText: '#15803D',
  changedBg: '#FEF3C7',
  changedText: '#B45309',
};
const SUBJECT_COLORS = ['#6366F1', '#0EA5E9', '#10B981', '#F59E0B', '#EF4444', '#EC4899', '#8B5CF6', '#14B8A6', '#F97316', '#84CC16'];

let canvasLib = null;
let loadError = null;

// Подключаем библиотеку рисования один раз; если на сервере она недоступна — бот перейдёт на текст
async function loadCanvas() {
  if (canvasLib || loadError) return canvasLib;
  try {
    const lib = await import('@napi-rs/canvas');
    for (const file of ['NotoSans-Regular.ttf', 'NotoSans-Bold.ttf', 'NotoSansMath-Regular.ttf']) {
      lib.GlobalFonts.registerFromPath(path.join(FONTS_DIR, file));
    }
    canvasLib = lib;
  } catch (error) {
    loadError = error;
  }
  return canvasLib;
}

export async function imageSupportError() {
  await loadCanvas();
  return loadError;
}

const font = (size, bold = false) => `${bold ? 'bold ' : ''}${size}px ${FAMILY}`;

// Эмодзи и служебные символы шрифт не рисует — убираем, чтобы не было «квадратиков»
export function cleanForImage(text) {
  return String(text || '')
    .replace(/[\p{Extended_Pictographic}\u{1F1E6}-\u{1F1FF}\u{1F3FB}-\u{1F3FF}️‍⃣]/gu, '')
    .replace(/[\u0000-\u0008\u000B-\u001F\u007F]/g, '')
    .replace(/[ \t]+/g, ' ')
    .trim();
}

function subjectColor(name) {
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + ch.codePointAt(0)) >>> 0;
  return SUBJECT_COLORS[hash % SUBJECT_COLORS.length];
}

// Перенос текста по словам; слишком длинные слова режутся по буквам
export function wrapText(ctx, text, maxWidth) {
  const lines = [];
  for (const paragraph of String(text).split('\n')) {
    const words = paragraph.split(' ').filter(Boolean);
    if (!words.length) {
      lines.push('');
      continue;
    }
    let line = '';
    for (const word of words) {
      const candidate = line ? `${line} ${word}` : word;
      if (ctx.measureText(candidate).width <= maxWidth) {
        line = candidate;
        continue;
      }
      if (line) lines.push(line);
      if (ctx.measureText(word).width <= maxWidth) {
        line = word;
        continue;
      }
      let chunk = '';
      for (const ch of word) {
        if (ctx.measureText(chunk + ch).width > maxWidth && chunk) {
          lines.push(chunk);
          chunk = '';
        }
        chunk += ch;
      }
      line = chunk;
    }
    lines.push(line);
  }
  // убираем пустые строки в начале/конце и двойные пустые
  return lines.filter((l, i, arr) => l || (i > 0 && i < arr.length - 1 && arr[i - 1]));
}

function clampLines(lines, max) {
  if (lines.length <= max) return lines;
  const kept = lines.slice(0, max);
  kept[max - 1] = `${kept[max - 1].replace(/\s*\S{0,3}$/, '')}…`;
  return kept;
}

// «на завтра · среда, 15 октября»
export function cardSubtitle(iso, todayIso) {
  const delta = diffDays(iso, todayIso);
  const date = `${Number(iso.slice(8, 10))} ${MONTHS_GEN[Number(iso.slice(5, 7)) - 1]}`;
  const weekday = WEEKDAYS[weekdayOf(iso) - 1];
  if (delta === 0) return `на сегодня · ${weekday}, ${date}`;
  if (delta === 1) return `на завтра · ${weekday}, ${date}`;
  if (delta === 2) return `на послезавтра · ${weekday}, ${date}`;
  return `на ${WEEKDAYS_ACC[weekdayOf(iso) - 1]} · ${date}`;
}

// Подпись под фото: «📚 Домашнее задание на завтра»
export function cardCaption(iso, todayIso, kind = 'digest') {
  const delta = diffDays(iso, todayIso);
  const when = delta === 0 ? 'на сегодня'
    : delta === 1 ? 'на завтра'
      : `на ${WEEKDAYS_ACC[weekdayOf(iso) - 1]}, ${iso.slice(8, 10)}.${iso.slice(5, 7)}`;
  if (kind === 'new') return `🆕 Новое домашнее задание ${when}`;
  if (kind === 'changed') return `✏️ Изменилось домашнее задание ${when}`;
  return `📚 Домашнее задание ${when}`;
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

// Раскладка одной карточки предмета: считаем строки заранее, чтобы знать высоту картинки
function layoutEntry(ctx, entry, mark) {
  const textWidth = W - 2 * PAD - 2 * INNER - 14;
  const badge = mark === 'new' ? 'НОВОЕ' : mark === 'changed' ? 'ИЗМЕНЕНО' : '';
  ctx.font = font(26, true);
  const badgeWidth = badge ? ctx.measureText(badge).width + 36 : 0;

  ctx.font = font(42, true);
  const subjectLines = clampLines(wrapText(ctx, cleanForImage(entry.subject), textWidth - (badge ? badgeWidth + 20 : 0)), 2);

  ctx.font = font(37);
  const body = clampLines(wrapText(ctx, cleanForImage(entry.text), textWidth), MAX_LINES_PER_ENTRY);
  ctx.font = font(33);
  const books = entry.books.flatMap((b) => wrapText(ctx, `Учебник: ${cleanForImage(b)}`, textWidth)).slice(0, 6);
  const extras = [];
  if (entry.hasFiles) extras.push({ text: 'Есть прикреплённый файл', color: COLORS.file });
  if (entry.manual) extras.push({ text: `Добавлено вручную${entry.author ? ` (${cleanForImage(entry.author)})` : ''}`, color: COLORS.muted });
  if (!body.length && !books.length && !entry.hasFiles) extras.push({ text: 'Задание без текста — смотрите в BilimClass', color: COLORS.muted });
  const extraLines = extras.flatMap((e) => wrapText(ctx, e.text, textWidth).map((text) => ({ text, color: e.color })));

  const height = INNER + subjectLines.length * 54 + (body.length ? 10 + body.length * 52 : 0)
    + (books.length ? 12 + books.length * 46 : 0) + (extraLines.length ? 12 + extraLines.length * 46 : 0) + INNER - 8;
  return { entry, badge, badgeWidth, subjectLines, body, books, extraLines, height, mark };
}

function drawEntry(ctx, item, y) {
  const x = PAD;
  const w = W - 2 * PAD;
  ctx.save();
  ctx.shadowColor = 'rgba(15, 23, 42, 0.08)';
  ctx.shadowBlur = 18;
  ctx.shadowOffsetY = 4;
  ctx.fillStyle = COLORS.card;
  roundRect(ctx, x, y, w, item.height, 26);
  ctx.fill();
  ctx.restore();

  // цветная полоска предмета слева
  ctx.save();
  roundRect(ctx, x, y, w, item.height, 26);
  ctx.clip();
  ctx.fillStyle = subjectColor(item.entry.subject);
  ctx.fillRect(x, y, 14, item.height);
  ctx.restore();

  const tx = x + INNER + 14;
  let cy = y + INNER;
  ctx.textBaseline = 'top';

  if (item.badge) {
    const bx = x + w - INNER - item.badgeWidth;
    ctx.fillStyle = item.mark === 'new' ? COLORS.newBg : COLORS.changedBg;
    roundRect(ctx, bx, cy + 4, item.badgeWidth, 44, 22);
    ctx.fill();
    ctx.fillStyle = item.mark === 'new' ? COLORS.newText : COLORS.changedText;
    ctx.font = font(26, true);
    ctx.fillText(item.badge, bx + 18, cy + 11);
  }

  ctx.fillStyle = COLORS.title;
  ctx.font = font(42, true);
  for (const line of item.subjectLines) {
    ctx.fillText(line, tx, cy);
    cy += 54;
  }
  if (item.body.length) {
    cy += 10;
    ctx.fillStyle = COLORS.text;
    ctx.font = font(37);
    for (const line of item.body) {
      ctx.fillText(line, tx, cy);
      cy += 52;
    }
  }
  if (item.books.length) {
    cy += 12;
    ctx.fillStyle = COLORS.muted;
    ctx.font = font(33);
    for (const line of item.books) {
      ctx.fillText(line, tx, cy);
      cy += 46;
    }
  }
  if (item.extraLines.length) {
    cy += 12;
    ctx.font = font(33);
    for (const line of item.extraLines) {
      ctx.fillStyle = line.color;
      ctx.fillText(line.text, tx, cy);
      cy += 46;
    }
  }
}

/**
 * Картинка с ДЗ на один день.
 * view: { date, entries, lessons, isHoliday }, marks: Map(ключ задания → 'new' | 'changed'), markKey(entry) → ключ
 */
export async function renderDayCard(view, todayIso, { className = '', marks = new Map(), markKey = () => '', checkedAt = '' } = {}) {
  const lib = await loadCanvas();
  if (!lib) throw loadError || new Error('библиотека рисования недоступна');
  const measure = lib.createCanvas(W, 100).getContext('2d');

  const headerHeight = 236;
  const items = view.entries.map((e) => layoutEntry(measure, e, marks.get(markKey(e))));

  const withHomework = new Set(view.entries.map((e) => e.subject));
  const without = [...new Set((view.lessons || []).map((l) => l.subject))].filter((s) => !withHomework.has(s));
  measure.font = font(32);
  const withoutLines = view.entries.length && without.length
    ? wrapText(measure, `Без ДЗ: ${cleanForImage(without.join(', '))}`, W - 2 * PAD).slice(0, 4)
    : [];

  // если заданий очень много — обрезаем, чтобы картинка не была бесконечной
  let total = headerHeight + PAD;
  const shown = [];
  for (const item of items) {
    if (total + item.height + 28 > MAX_HEIGHT - 300) break;
    shown.push(item);
    total += item.height + 28;
  }
  const hidden = items.length - shown.length;
  const emptyHeight = items.length ? 0 : 220;
  const height = Math.round(total + emptyHeight + (hidden ? 60 : 0) + (withoutLines.length ? withoutLines.length * 44 + 12 : 0) + 110);

  const canvas = lib.createCanvas(W, height);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = COLORS.bg;
  ctx.fillRect(0, 0, W, height);

  // шапка
  const gradient = ctx.createLinearGradient(0, 0, W, headerHeight);
  gradient.addColorStop(0, COLORS.headerFrom);
  gradient.addColorStop(1, COLORS.headerTo);
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, W, headerHeight);
  ctx.textBaseline = 'top';
  ctx.fillStyle = '#FFFFFF';
  ctx.font = font(64, true);
  ctx.fillText('Домашнее задание', PAD, 52);
  ctx.font = font(38);
  ctx.fillStyle = 'rgba(255, 255, 255, 0.9)';
  ctx.fillText(cardSubtitle(view.date, todayIso), PAD, 140);
  if (className) {
    const label = cleanForImage(className).slice(0, 20);
    ctx.font = font(30, true);
    const lw = ctx.measureText(label).width + 40;
    ctx.fillStyle = 'rgba(255, 255, 255, 0.2)';
    roundRect(ctx, W - PAD - lw, 58, lw, 50, 25);
    ctx.fill();
    ctx.fillStyle = '#FFFFFF';
    ctx.fillText(label, W - PAD - lw + 20, 67);
  }

  let y = headerHeight + PAD;
  if (!items.length) {
    ctx.fillStyle = COLORS.card;
    roundRect(ctx, PAD, y, W - 2 * PAD, 190, 26);
    ctx.fill();
    ctx.fillStyle = COLORS.title;
    ctx.font = font(44, true);
    const title = view.isHoliday ? 'Выходной день' : view.lessons?.length ? 'Домашнего задания нет' : 'Уроков нет';
    ctx.fillText(title, PAD + INNER, y + 44);
    ctx.fillStyle = COLORS.muted;
    ctx.font = font(34);
    ctx.fillText('В дневнике BilimClass заданий на этот день нет', PAD + INNER, y + 110);
    y += 190 + 30;
  }
  for (const item of shown) {
    drawEntry(ctx, item, y);
    y += item.height + 28;
  }
  ctx.textBaseline = 'top';
  if (hidden) {
    ctx.fillStyle = COLORS.muted;
    ctx.font = font(34, true);
    ctx.fillText(`…и ещё ${hidden} — полный список: команда !дз`, PAD, y);
    y += 60;
  }
  if (withoutLines.length) {
    ctx.fillStyle = COLORS.muted;
    ctx.font = font(32);
    for (const line of withoutLines) {
      ctx.fillText(line, PAD, y);
      y += 44;
    }
    y += 12;
  }

  // подвал
  ctx.fillStyle = COLORS.faint;
  ctx.font = font(28);
  ctx.fillText(`BilimClass${checkedAt ? ` · проверено в ${checkedAt}` : ''}`, PAD, height - 70);
  const hint = 'Вопросы по ДЗ — пишите в чат';
  ctx.fillText(hint, W - PAD - ctx.measureText(hint).width, height - 70);

  return canvas.encode('jpeg', 90);
}

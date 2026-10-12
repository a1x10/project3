// Сообщение с ДЗ на один день: фото-карточка (по умолчанию) или текст, если картинка недоступна.
import { diffDays, onDay } from '../utils/dates.js';
import { formatDay } from './format.js';
import { cardCaption, renderDayCard } from './image.js';

export function noHomeworkText(iso, todayIso) {
  const delta = diffDays(iso, todayIso);
  const when = delta === 1 ? 'на завтра' : delta === 0 ? 'на сегодня' : onDay(iso, todayIso);
  return `📚 Домашнего задания ${when} в дневнике нет 🎉`;
}

/**
 * Возвращает содержимое сообщения для Baileys: { image, caption, mimetype } или { text }.
 * kind: 'digest' — «Домашнее задание на завтра», 'new' / 'changed' — уведомление о новом/изменённом ДЗ.
 */
export async function dayMessage(view, todayIso, { asImage = true, kind = 'digest', marks, markKey, className, checkedAt, logger } = {}) {
  if (!view.entries.length) return { text: noHomeworkText(view.date, todayIso) };
  if (asImage) {
    try {
      const image = await renderDayCard(view, todayIso, { className, marks, markKey, checkedAt });
      return { image, caption: cardCaption(view.date, todayIso, kind), mimetype: 'image/jpeg' };
    } catch (error) {
      logger?.warn({ err: error.message }, 'Не получилось нарисовать картинку — отправляю текстом');
    }
  }
  return { text: formatDay(view, todayIso) };
}

// Подпись к настоящему скриншоту: на нём нет пометок «НОВОЕ», поэтому перечисляем новое в подписи
export function screenshotCaption(view, todayIso, kind, marks, markKey) {
  const caption = cardCaption(view.date, todayIso, kind);
  if (!marks?.size) return caption;
  const subjectsBy = (k) => [...new Set(view.entries.filter((e) => marks.get(markKey(e)) === k).map((e) => e.subject))];
  const added = subjectsBy('new');
  const changed = subjectsBy('changed');
  const lines = [caption];
  if (added.length && kind !== 'new') lines.push(`🆕 Новое: ${added.join(', ')}`);
  if (added.length && kind === 'new') lines.push(`Новое: ${added.join(', ')}`);
  if (changed.length) lines.push(`✏️ Изменено: ${changed.join(', ')}`);
  return lines.join('\n');
}

/**
 * Фото с ДЗ на несколько дней сразу.
 * HOMEWORK_PHOTO=screenshot — настоящие скриншоты дневника (один вход на сайт на все дни),
 * при неудаче для конкретного дня — нарисованная карточка. card — только карточки, text — текст.
 */
export class HomeworkPhotos {
  constructor({ config, screenshotter = null, logger, className = () => '', notify = () => {} }) {
    this.config = config;
    this.screenshotter = screenshotter;
    this.logger = logger;
    this.className = className;
    this.notify = notify;
    this.failures = 0;
  }

  get mode() {
    return this.config.features.homeworkPhoto;
  }

  // Можно ли этот день снять скриншотом: на сайте видно ровно то, что знает бот
  screenshotable(view) {
    return view.entries.length > 0
      && !view.entries.some((e) => e.manual)
      && this.config.features.homeworkAttachedTo === 'due';
  }

  async screenshots(views) {
    const wanted = views.filter((v) => this.screenshotable(v));
    if (this.mode !== 'screenshot' || !wanted.length || !this.screenshotter?.available) return new Map();
    try {
      const shots = await this.screenshotter.captureDays(wanted.map((v) => ({
        date: v.date,
        // на снимке должны быть ВСЕ уроки дня (иначе это неполный снимок — лучше отправить карточку)
        subjects: [...new Set([...(v.lessons || []).map((l) => l.subject), ...v.entries.map((e) => e.subject)])],
        key: v.entries.map((e) => `${e.subject}:${e.text}`).join('|'),
      })));
      if (shots.size) {
        if (this.failures >= 3) this.notify('screenshot-recovered', '✅ Скриншоты дневника снова работают.', 0);
        this.failures = 0;
      } else {
        this.failures += 1;
      }
      return shots;
    } catch (error) {
      this.failures += 1;
      this.logger?.warn({ err: error.message }, 'Скриншоты дневника не получились — отправлю нарисованные карточки');
      if (this.failures >= 3) {
        this.notify('screenshot-failed', `Скриншоты дневника не получаются (${error.message}). Пока отправляю нарисованные карточки с ДЗ.`);
      }
      return new Map();
    }
  }

  // views: дни с ДЗ, options.kinds: Map(дата → 'digest' | 'new' | 'changed')
  async messages(views, todayIso, { kinds = new Map(), marks = new Map(), markKey = () => '', checkedAt = '' } = {}) {
    const shots = await this.screenshots(views);
    const result = [];
    for (const view of views) {
      const kind = kinds.get(view.date) || 'digest';
      const shot = shots.get(view.date);
      if (shot) {
        result.push({ image: shot, caption: screenshotCaption(view, todayIso, kind, marks, markKey), mimetype: 'image/jpeg' });
        continue;
      }
      result.push(await dayMessage(view, todayIso, {
        asImage: this.mode !== 'text', kind, marks, markKey, className: this.className(), checkedAt, logger: this.logger,
      }));
    }
    return result;
  }
}

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

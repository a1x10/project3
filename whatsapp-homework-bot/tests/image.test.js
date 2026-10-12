import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { createCanvas, loadImage } from '@napi-rs/canvas';
import { inkRatio } from '../src/bilimclass/screenshot.js';
import { cardCaption, cardSubtitle, cleanForImage, renderDayCard, wrapText } from '../src/homework/image.js';

const entry = (subject, text, extra = {}) => ({ key: subject, lessonDate: '2025-10-15', subject, text, books: [], hasFiles: false, ...extra });

describe('картинка с ДЗ', () => {
  it('рисует JPEG шириной 1080, высота растёт с количеством заданий', async () => {
    const small = await renderDayCard({ date: '2025-10-15', lessons: [], entries: [entry('Алгебра', '№ 250')] }, '2025-10-14');
    const big = await renderDayCard({
      date: '2025-10-15',
      lessons: [{ subject: 'Музыка' }],
      entries: [entry('Алгебра', '№ 250'), entry('Қазақ тілі', 'Мәтінді оқу'), entry('Физика', '§ 12', { hasFiles: true, books: ['Физика 7, стр. 40'] })],
    }, '2025-10-14', { className: '7 «А»', marks: new Map([['Алгебра', 'new']]), markKey: (e) => e.key, checkedAt: '14:35' });
    const a = await loadImage(small);
    const b = await loadImage(big);
    assert.equal(a.width, 1080);
    assert.ok(b.height > a.height);
  });

  it('очень длинное ДЗ и много предметов — картинка ограничена по высоте', async () => {
    const entries = Array.from({ length: 40 }, (_, i) => entry(`Предмет ${i}`, 'очень длинный текст задания '.repeat(60)));
    const img = await loadImage(await renderDayCard({ date: '2025-10-15', lessons: [], entries }, '2025-10-14'));
    assert.ok(img.height <= 6000);
  });

  it('эмодзи убираются, текст и формулы остаются', () => {
    assert.equal(cleanForImage('Выучить 🔥 стих 👍🏽 ❤️'), 'Выучить стих');
    assert.equal(cleanForImage('√9 ≤ 3, x²'), '√9 ≤ 3, x²');
  });

  it('перенос строк: по словам, длинное слово режется', () => {
    const ctx = createCanvas(100, 100).getContext('2d');
    ctx.font = '30px "Noto Sans"';
    const lines = wrapText(ctx, `короткие слова тут ${'ы'.repeat(80)}`, 300);
    assert.ok(lines.length > 2);
    assert.ok(lines.every((l) => ctx.measureText(l).width <= 300));
  });

  it('подписи', () => {
    assert.equal(cardCaption('2025-10-15', '2025-10-14'), '📚 Домашнее задание на завтра');
    assert.equal(cardCaption('2025-10-14', '2025-10-14'), '📚 Домашнее задание на сегодня');
    assert.equal(cardCaption('2025-10-17', '2025-10-14', 'new'), '🆕 Новое домашнее задание на пятницу, 17.10');
    assert.equal(cardCaption('2025-10-20', '2025-10-17', 'changed'), '✏️ Изменилось домашнее задание на понедельник, 20.10');
    assert.equal(cardSubtitle('2025-10-15', '2025-10-14'), 'на завтра · среда, 15 октября');
    assert.equal(cardSubtitle('2025-10-20', '2025-10-14'), 'на понедельник · 20 октября');
  });
});

describe('проверка «пустого» снимка', () => {
  it('пустая картинка — 0 «чернил», с текстом — больше порога', async () => {
    const blank = createCanvas(800, 400);
    const ctx = blank.getContext('2d');
    ctx.fillStyle = '#f5f9fc';
    ctx.fillRect(0, 0, 800, 400);
    ctx.strokeStyle = '#dde3ee';
    ctx.strokeRect(6, 0, 788, 400);
    assert.equal(await inkRatio(blank.toBuffer('image/jpeg')), 0);
    ctx.fillStyle = '#1f2937';
    ctx.font = '32px sans-serif';
    ctx.fillText('Алгебра — № 250, 251 (стр. 58)', 40, 120);
    ctx.fillText('Физическая культура', 40, 200);
    assert.ok((await inkRatio(blank.toBuffer('image/jpeg'))) > 0.003);
  });
});

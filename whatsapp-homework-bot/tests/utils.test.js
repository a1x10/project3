import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { addDays, humanDay, mondayOf, nowParts, onDay, parseApiDate, parseDayArg, weekdayOf } from '../src/utils/dates.js';
import { RateLimiter } from '../src/utils/ratelimit.js';
import { htmlToText, latexToText, markdownToWhatsApp, splitMessage } from '../src/utils/text.js';

describe('даты', () => {
  it('часовой пояс школы', () => {
    // 23:30 UTC 13.10 = 04:30 14.10 в Алматы (UTC+5)
    const p = nowParts('Asia/Almaty', new Date('2025-10-13T23:30:00Z'));
    assert.equal(p.iso, '2025-10-14');
    assert.equal(p.minutes, 4 * 60 + 30);
    assert.equal(p.weekday, 2);
  });

  it('арифметика дат', () => {
    assert.equal(addDays('2025-12-31', 1), '2026-01-01');
    assert.equal(mondayOf('2025-10-19'), '2025-10-13');
    assert.equal(mondayOf('2025-10-13'), '2025-10-13');
    assert.equal(weekdayOf('2025-10-19'), 7);
  });

  it('даты из API, включая "29 сентября" без года и переход через Новый год', () => {
    assert.equal(parseApiDate('29.09.2025', '2025-10-01'), '2025-09-29');
    assert.equal(parseApiDate('2025-09-29', '2025-10-01'), '2025-09-29');
    assert.equal(parseApiDate('29 сентября', '2025-10-01'), '2025-09-29');
    assert.equal(parseApiDate('2 января', '2025-12-31'), '2026-01-02');
    assert.equal(parseApiDate('30 декабря', '2026-01-01'), '2025-12-30');
    assert.equal(parseApiDate('15 қазан', '2025-10-14'), '2025-10-15');
    assert.equal(parseApiDate('31 февраля', '2025-02-10'), null);
    assert.equal(parseApiDate('ерунда', '2025-02-10'), null);
  });

  it('день из команды', () => {
    const tue = '2025-10-14';
    assert.equal(parseDayArg('сегодня', tue), tue);
    assert.equal(parseDayArg('завтра', tue), '2025-10-15');
    assert.equal(parseDayArg('послезавтра', tue), '2025-10-16');
    assert.equal(parseDayArg('пт', tue), '2025-10-17');
    assert.equal(parseDayArg('на пятницу', tue), '2025-10-17');
    assert.equal(parseDayArg('вторник', tue), tue);
    assert.equal(parseDayArg('пн', tue), '2025-10-20');
    assert.equal(parseDayArg('20.10', tue), '2025-10-20');
    assert.equal(parseDayArg('20.10.2025', tue), '2025-10-20');
    assert.equal(parseDayArg('3 ноября', tue), '2025-11-03');
    assert.equal(parseDayArg('алгебра', tue), null);
  });

  it('человеческие подписи дней', () => {
    assert.equal(humanDay('2025-10-15', '2025-10-14'), 'завтра (среда, 15.10)');
    assert.equal(onDay('2025-10-17', '2025-10-14'), 'на пятницу, 17.10');
    assert.equal(onDay('2025-10-15', '2025-10-14'), 'на завтра, среду, 15.10');
  });
});

describe('текст', () => {
  it('HTML из дневника превращается в текст', () => {
    assert.equal(htmlToText('<p>№ 245,&nbsp;247</p><p>Повторить &laquo;формулы&raquo;</p>'), '№ 245, 247\nПовторить «формулы»');
    assert.equal(htmlToText('<ul><li>раз</li><li>два</li></ul>'), '• раз\n• два');
    assert.equal(htmlToText('a < b и c > d'), 'a < b и c > d');
    assert.equal(htmlToText(null), '');
  });

  it('Markdown и LaTeX → WhatsApp', () => {
    const out = markdownToWhatsApp('### Решение\n**Шаг 1:** найдём $x^2 = \\frac{1}{4}$\n- пункт\n<think>секрет</think>');
    assert.ok(out.startsWith('*Решение*'));
    assert.ok(out.includes('*Шаг 1:*'));
    assert.ok(out.includes('x² = 1/4'));
    assert.ok(out.includes('• пункт'));
    assert.ok(!out.includes('секрет'));
    assert.equal(latexToText('\\sqrt{16} \\cdot 2 \\le 10'), '√(16) · 2 ≤ 10');
  });

  it('длинный текст режется на части без потерь', () => {
    const text = Array.from({ length: 50 }, (_, i) => `Абзац ${i} ${'x'.repeat(100)}`).join('\n\n');
    const parts = splitMessage(text, 1000);
    assert.ok(parts.length > 1);
    assert.ok(parts.every((p) => p.length <= 1000));
    assert.equal(parts.join('\n\n'), text);
    const huge = 'y'.repeat(2500);
    assert.equal(splitMessage(huge, 1000).join(''), huge);
  });
});

describe('ограничитель частоты', () => {
  it('не пускает сверх лимита и освобождается со временем', () => {
    const rl = new RateLimiter(2, 1000);
    assert.equal(rl.take('a', 0), true);
    assert.equal(rl.take('a', 10), true);
    assert.equal(rl.take('a', 20), false);
    assert.equal(rl.take('b', 20), true);
    assert.equal(rl.retryIn('a', 500), 500);
    assert.equal(rl.take('a', 1001), true);
  });
});

import { describe, it, expect } from 'vitest';
import { bondLevel } from '../src/renderer/js/ui/profile.js';
import { translit } from '../src/renderer/js/ui/auth.js';
import { linesFor, pick } from '../src/renderer/js/ui/presence.js';
import { icon } from '../src/renderer/js/ui/icons.js';
import { timeAgo, plural } from '../src/renderer/js/ui/dom.js';

describe('Уровень близости', () => {
  it('новичок', () => expect(bondLevel({})).toMatchObject({ level: 0, name: 'Незнакомцы' }));
  it('растёт с общением', () => expect(bondLevel({ messagesSent: 20 }).level).toBeGreaterThan(0));
  it('прогресс в 0..1', () => { for (const n of [0, 5, 50, 500, 5000]) { const b = bondLevel({ messagesSent: n }); expect(b.progress).toBeGreaterThanOrEqual(0); expect(b.progress).toBeLessThanOrEqual(1); } });
  it('максимальный уровень', () => expect(bondLevel({ messagesSent: 1e6 })).toMatchObject({ name: 'Родственные души', progress: 1 }));
});

describe('Транслитерация логина', () => {
  it('Алекс → aleks', () => expect(translit('Алекс')).toBe('aleks'));
  it('Щука Юля → schuka_yulya', () => expect(translit('Щука Юля')).toBe('schuka_yulya'));
  it('латиница не меняется', () => expect(translit('bob')).toBe('bob'));
});

describe('Реплики присутствия', () => {
  for (const p of ['stella', 'mark']) for (const k of ['head', 'body', 'legs', 'back', 'wake', 'bored']) it(`${p}/${k} не пусто`, () => expect(linesFor(p, k).length).toBeGreaterThan(0));
  it('неизвестная персона → Стелла', () => expect(linesFor('x', 'head')).toEqual(linesFor('stella', 'head')));
  it('pick возвращает элемент массива', () => expect(['a', 'b']).toContain(pick(['a', 'b'])));
});

describe('Мелочи интерфейса', () => {
  it('иконка — SVG', () => expect(icon('chat')).toMatch(/^<svg.*<\/svg>$/s));
  it('неизвестная иконка не ломается', () => expect(icon('zzz')).toContain('<svg'));
  it('timeAgo', () => { expect(timeAgo(Date.now())).toBe('только что'); expect(timeAgo(Date.now() - 5 * 60000)).toBe('5 мин назад'); expect(timeAgo(Date.now() - 3 * 3600000)).toBe('3 ч назад'); });
  it('plural', () => {
    expect(plural(1, 'день', 'дня', 'дней')).toBe('день'); expect(plural(3, 'день', 'дня', 'дней')).toBe('дня');
    expect(plural(5, 'день', 'дня', 'дней')).toBe('дней'); expect(plural(11, 'день', 'дня', 'дней')).toBe('дней');
    expect(plural(21, 'день', 'дня', 'дней')).toBe('день'); expect(plural(112, 'день', 'дня', 'дней')).toBe('дней');
  });
});

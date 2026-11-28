import { describe, it, expect } from 'vitest';
import { detectWakeWord, mentionsName, normalize, levenshtein } from '../src/renderer/js/core/wakeword.js';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { PERSONAS } = require('../src/main/persona.js');
const S = PERSONAS.stella.wakeWords, M = PERSONAS.mark.wakeWords;

describe('Обращение по имени — Стелла', () => {
  const yes = [
    ['Стелла, открой браузер', 'открой браузер'],
    ['стелла открой браузер', 'открой браузер'],
    ['Эй, Стелла! Сколько времени?', 'сколько времени'],
    ['Стела, станцуй', 'станцуй'],
    ['Stella, play music', 'play music'],
    ['Слушай, Стелла, поставь таймер', 'поставь таймер'],
    ['Ну стелла давай', 'давай'],
    ['Стэлла, привет', 'привет'],
    ['Стеллочка, ты тут?', 'ты тут'],
    ['Окей Стелла найди котиков', 'найди котиков'],
  ];
  for (const [phrase, cmd] of yes) it(`«${phrase}»`, () => expect(detectWakeWord(phrase, S)).toEqual({ matched: true, command: cmd, onlyName: false }));
  it('только имя', () => expect(detectWakeWord('Стелла!', S)).toEqual({ matched: true, command: '', onlyName: true }));
  const no = ['Открой браузер', 'Я смотрел на звёзды', 'Мы купили стол', 'Вчера была стелла... нет', 'Скажи мне что-то про Марка', 'Стена'];
  for (const p of no) it(`не реагирует: «${p}»`, () => expect(detectWakeWord(p, S).matched).toBe(false));
  it('имя не в начале фразы не активирует', () => expect(detectWakeWord('расскажи как дела стелла', S).matched).toBe(false));
});

describe('Обращение по имени — Марк', () => {
  it('«Марк, выключи музыку»', () => expect(detectWakeWord('Марк, выключи музыку', M)).toMatchObject({ matched: true, command: 'выключи музыку' }));
  it('«Эй Марк»', () => expect(detectWakeWord('Эй Марк', M).onlyName).toBe(true));
  it('Mark, open notes', () => expect(detectWakeWord('Mark, open notes', M).command).toBe('open notes'));
  it('короткое имя не путает «мрак»', () => expect(detectWakeWord('мрак сгущается', M).matched).toBe(false));
  it('не реагирует на Стеллу', () => expect(detectWakeWord('Стелла, привет', M).matched).toBe(false));
});

describe('Упоминание имени и утилиты', () => {
  it('упоминание в середине', () => expect(mentionsName('Спасибо тебе, Стелла!', S)).toBe(true));
  it('нет упоминания', () => expect(mentionsName('Спасибо!', S)).toBe(false));
  it('normalize: ё, регистр, пунктуация', () => expect(normalize('  Ёжик, СТЕЛЛА!! ')).toBe('ежик стелла'));
  it('levenshtein', () => { expect(levenshtein('стелла', 'стела')).toBe(1); expect(levenshtein('', 'abc')).toBe(3); expect(levenshtein('кот', 'кот')).toBe(0); });
});

describe('Что делать с услышанной фразой', async () => {
  const { decideVoice } = await import('../src/renderer/js/ui/listen.js');
  const o = { names: S, fromWake: true, requireName: true };
  it('с именем — команда без имени', () => expect(decideVoice('Стелла, открой ютуб', o)).toEqual({ result: 'command', command: 'открой ютуб' }));
  it('без имени — пропуск (видно в истории, а не молча)', () => expect(decideVoice('открой ютуб', o).result).toBe('no-name'));
  it('только имя — ждём команду', () => expect(decideVoice('Стелла!', o).result).toBe('wake'));
  it('после имени следующая фраза без имени — команда', () => expect(decideVoice('открой ютуб', { ...o, awaiting: true })).toEqual({ result: 'command', command: 'открой ютуб' }));
  it('режим «без имени»: любая фраза — команда, имя убирается', () => {
    expect(decideVoice('открой ютуб', { ...o, requireName: false })).toEqual({ result: 'command', command: 'открой ютуб' });
    expect(decideVoice('Стелла, открой ютуб', { ...o, requireName: false }).command).toBe('открой ютуб');
  });
  it('кнопка микрофона: имя не нужно', () => expect(decideVoice('сколько времени', { ...o, fromWake: false })).toEqual({ result: 'command', command: 'сколько времени' }));
  it('пустой или мусорный текст', () => { expect(decideVoice('', o).result).toBe('empty'); expect(decideVoice(' ... ', o).result).toBe('empty'); expect(decideVoice('(музыка)', { ...o, fromWake: false }).result).toBe('command'); });
});

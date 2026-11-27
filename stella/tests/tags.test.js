import { describe, it, expect } from 'vitest';
import { parseTags, stripTags, SpeechChunker, isSpeakable } from '../src/renderer/js/core/tags.js';

describe('parseTags', () => {
  it('извлекает эмоции и действия', () => expect(parseTags('[happy][wave] Привет!')).toEqual({ clean: 'Привет!', emotions: ['happy'], actions: ['wave'] }));
  it('теги в середине текста', () => expect(parseTags('Смотри [dance] как я умею!').clean).toBe('Смотри как я умею!'));
  it('регистр не важен', () => expect(parseTags('[HAPPY] ok').emotions).toEqual(['happy']));
  it('неизвестные скобки остаются', () => expect(parseTags('массив [index] и [1]').clean).toBe('массив [index] и [1]'));
  it('пробел перед знаком препинания убирается', () => expect(parseTags('Ура [victory]!').clean).toBe('Ура!'));
  it('stripTags', () => expect(stripTags('[think] Хм')).toBe('Хм'));
  it('пустой ввод', () => expect(parseTags(undefined)).toEqual({ clean: '', emotions: [], actions: [] }));
});

describe('SpeechChunker', () => {
  const feed = (tokens, opts) => {
    const c = new SpeechChunker(opts); const out = { sentences: [], tags: [] };
    for (const t of tokens) { const r = c.push(t); out.sentences.push(...r.sentences); out.tags.push(...r.tags); }
    out.sentences.push(...c.flush());
    return out;
  };
  it('режет по предложениям', () => {
    const r = feed(['Привет! Как у тебя дела сегодня? ', 'У меня всё отлично.']);
    expect(r.sentences).toEqual(['Привет! Как у тебя дела сегодня?', 'У меня всё отлично.']);
  });
  it('склеивает слишком короткие фразы', () => expect(feed(['Да. Конечно, сейчас сделаю это для тебя. ']).sentences).toEqual(['Да. Конечно, сейчас сделаю это для тебя.']));
  it('находит теги, разорванные между токенами', () => {
    const r = feed(['[da', 'nce] Смотри, как я ', 'танцую!']);
    expect(r.tags).toEqual([{ type: 'action', name: 'dance' }]);
    expect(r.sentences.join(' ')).not.toContain('[');
  });
  it('эмоции и действия типизируются', () => expect(feed(['[happy][jump] Ура, получилось у нас! ']).tags).toEqual([{ type: 'emotion', name: 'happy' }, { type: 'action', name: 'jump' }]));
  it('не режет внутри блока кода', () => {
    const r = feed(['Вот код:\n```\nprint("a. b. c.")\n', '```\nГотово. ']);
    expect(r.sentences.some((s) => s.includes('print("a. b. c.")'))).toBe(true);
  });
  it('режет по переводу строки', () => expect(feed(['Первая строка\nВторая строка']).sentences).toEqual(['Первая строка', 'Вторая строка']));
  it('многоточие в конце буфера ждёт продолжения', () => {
    const c = new SpeechChunker();
    expect(c.push('Ну, я не знаю, что сказать.').sentences).toEqual([]);
    expect(c.push('.. Может быть').sentences).toEqual(['Ну, я не знаю, что сказать...']);
  });
  it('очень длинная фраза режется по пробелу', () => {
    const long = 'слово '.repeat(60);
    const r = feed([long], { maxChars: 100 });
    expect(r.sentences.length).toBeGreaterThan(1);
    expect(r.sentences.every((s) => s.length <= 100)).toBe(true);
  });
  it('flush возвращает остаток без тегов', () => { const c = new SpeechChunker(); c.push('Остаток [happy'); expect(c.flush()).toEqual(['Остаток [happy']); });
  it('flush пустого — пусто', () => expect(new SpeechChunker().flush()).toEqual([]));
});

describe('isSpeakable', () => {
  it('текст', () => expect(isSpeakable('Привет')).toBe(true));
  it('только эмодзи и знаки', () => expect(isSpeakable('✨!!! ...')).toBe(false));
  it('только код', () => expect(isSpeakable('```\nls\n```')).toBe(false));
});

import { describe, it, expect } from 'vitest';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { PERSONAS, EMOTIONS, ACTIONS, buildSystemPrompt } = require('../src/main/persona.js');
import * as RT from '../src/renderer/js/core/tags.js';
import { CLIPS } from '../src/renderer/js/avatar/poses.js';
import { EMOTION_PRESETS } from '../src/renderer/js/avatar/expressions.js';

describe('Персонажи', () => {
  it('есть Стелла и Марк', () => { expect(PERSONAS.stella.name).toBe('Стелла'); expect(PERSONAS.mark.name).toBe('Марк'); });
  it('Стелла откликается на «Стелла» и «Stella»', () => { expect(PERSONAS.stella.wakeWords).toContain('стелла'); expect(PERSONAS.stella.wakeWords).toContain('stella'); });
  it('Марк откликается на «Марк»', () => expect(PERSONAS.mark.wakeWords).toContain('марк'));
  it('теги в main и renderer совпадают', () => { expect(EMOTIONS).toEqual(RT.EMOTIONS); expect(ACTIONS).toEqual(RT.ACTIONS); });
  it('для каждого действия есть анимация', () => { for (const a of ACTIONS) expect(CLIPS).toHaveProperty(a); });
  it('для каждой эмоции есть выражение лица', () => { for (const e of EMOTIONS) expect(EMOTION_PRESETS).toHaveProperty(e); });
});

describe('Системный промпт', () => {
  it('Стелла — женский род', () => expect(buildSystemPrompt({ persona: 'stella' })).toMatch(/Ты — Стелла.*женском роде/s));
  it('Марк — мужской род', () => expect(buildSystemPrompt({ persona: 'mark' })).toMatch(/Ты — Марк.*мужском роде/s));
  it('неизвестная персона → Стелла', () => expect(buildSystemPrompt({ persona: 'x' })).toContain('Ты — Стелла'));
  it('имя пользователя', () => expect(buildSystemPrompt({ userName: 'Алекс' })).toContain('Пользователя зовут Алекс'));
  it('список тегов', () => { const p = buildSystemPrompt(); expect(p).toContain('[dance]'); expect(p).toContain('[happy]'); });
  it('раздел управления компьютером включается/выключается', () => {
    expect(buildSystemPrompt({ computerControl: true })).toContain('УПРАВЛЕНИЕ КОМПЬЮТЕРОМ');
    expect(buildSystemPrompt({ computerControl: false })).not.toContain('УПРАВЛЕНИЕ КОМПЬЮТЕРОМ');
  });
  it('ОС пользователя', () => { expect(buildSystemPrompt({ os: 'win32' })).toContain('Windows'); expect(buildSystemPrompt({ os: 'darwin' })).toContain('macOS'); });
  it('воспоминания (последние 40)', () => {
    const mem = Array.from({ length: 50 }, (_, i) => ({ text: 'факт ' + i }));
    const p = buildSystemPrompt({ memories: mem });
    expect(p).toContain('- факт 49'); expect(p).toContain('- факт 10'); expect(p).not.toContain('- факт 9\n');
  });
  it('пользовательские инструкции', () => expect(buildSystemPrompt({ customInstructions: 'Зови меня капитан' })).toContain('Зови меня капитан'));
  it('дата', () => expect(buildSystemPrompt({ now: new Date('2026-01-02T10:00:00') })).toContain('2026'));
});

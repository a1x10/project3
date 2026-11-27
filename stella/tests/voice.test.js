import { describe, it, expect, vi } from 'vitest';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { synthesize, listVoices, transcribe, getSubscription, cleanForSpeech } = require('../src/main/voice.js');

describe('Очистка текста для речи', () => {
  it('убирает теги эмоций', () => expect(cleanForSpeech('[happy][wave] Привет!')).toBe('Привет!'));
  it('убирает markdown', () => expect(cleanForSpeech('**Жирный** и _курсив_ # заголовок')).toBe('Жирный и курсив заголовок'));
  it('заменяет блоки кода', () => expect(cleanForSpeech('Вот:\n```js\nconsole.log(1)\n```')).toContain('код на экране'));
  it('ссылки читает по тексту', () => expect(cleanForSpeech('Смотри [тут](https://x.com)')).toBe('Смотри тут'));
  it('голые URL → «ссылка»', () => expect(cleanForSpeech('Открой https://example.com/page')).toBe('Открой ссылка'));
  it('инлайн-код', () => expect(cleanForSpeech('команда `dir`')).toBe('команда dir'));
});

describe('ElevenLabs TTS', () => {
  it('отправляет правильный запрос и возвращает аудио', async () => {
    const fetchImpl = vi.fn(async () => ({ ok: true, arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer }));
    const buf = await synthesize({ apiKey: 'key', voiceId: 'v 1', text: '[happy] Привет!', modelId: 'eleven_flash_v2_5', speed: 5, fetchImpl });
    expect([...buf]).toEqual([1, 2, 3]);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe('https://api.elevenlabs.io/v1/text-to-speech/v%201?output_format=mp3_44100_128');
    expect(init.headers['xi-api-key']).toBe('key');
    const body = JSON.parse(init.body);
    expect(body.text).toBe('Привет!');
    expect(body.model_id).toBe('eleven_flash_v2_5');
    expect(body.voice_settings.speed).toBe(1.2);
  });
  it('пустой текст — без запроса', async () => {
    const fetchImpl = vi.fn();
    expect(await synthesize({ apiKey: 'k', voiceId: 'v', text: '[happy]', fetchImpl })).toBeNull();
    expect(fetchImpl).not.toHaveBeenCalled();
  });
  it('без ключа или голоса — ошибка', async () => {
    await expect(synthesize({ voiceId: 'v', text: 'x' })).rejects.toThrow(/ключ/);
    await expect(synthesize({ apiKey: 'k', text: 'x' })).rejects.toThrow(/голос/);
  });
  it('401 — понятная ошибка', async () => {
    await expect(synthesize({ apiKey: 'k', voiceId: 'v', text: 'x', fetchImpl: async () => ({ ok: false, status: 401, text: async () => '{"detail":{"message":"invalid"}}' }) })).rejects.toThrow(/Неверный ключ ElevenLabs.*invalid/);
  });
  it('402 — закончились символы', async () => {
    await expect(synthesize({ apiKey: 'k', voiceId: 'v', text: 'x', fetchImpl: async () => ({ ok: false, status: 402, text: async () => 'quota' }) })).rejects.toThrow(/символы/);
  });
});

describe('ElevenLabs голоса и STT', () => {
  it('список голосов', async () => {
    const v = await listVoices({ apiKey: 'k', fetchImpl: async () => ({ ok: true, json: async () => ({ voices: [{ voice_id: 'id1', name: 'Rachel', category: 'premade', labels: { gender: 'female', accent: 'american' } }] }) }) });
    expect(v).toEqual([{ id: 'id1', name: 'Rachel', category: 'premade', gender: 'female', accent: 'american', description: '', preview: '' }]);
  });
  it('распознавание речи', async () => {
    const fetchImpl = vi.fn(async () => ({ ok: true, json: async () => ({ text: '  Стелла, открой браузер ' }) }));
    const t = await transcribe({ apiKey: 'k', audio: Buffer.from([0, 1]), mime: 'audio/wav', language: 'rus', fetchImpl });
    expect(t).toBe('Стелла, открой браузер');
    const form = fetchImpl.mock.calls[0][1].body;
    expect(form.get('model_id')).toBe('scribe_v1');
    expect(form.get('language_code')).toBe('rus');
    expect(form.get('file')).toBeInstanceOf(Blob);
  });
  it('автоопределение языка не шлёт language_code', async () => {
    const fetchImpl = vi.fn(async () => ({ ok: true, json: async () => ({ text: 'hi' }) }));
    await transcribe({ apiKey: 'k', audio: Buffer.from([0]), language: 'auto', fetchImpl });
    expect(fetchImpl.mock.calls[0][1].body.get('language_code')).toBeNull();
  });
  it('STT без ключа', async () => { await expect(transcribe({ audio: Buffer.from([]) })).rejects.toThrow(/ключ/); });
  it('подписка', async () => {
    const s = await getSubscription({ apiKey: 'k', fetchImpl: async () => ({ ok: true, json: async () => ({ tier: 'free', character_count: 10, character_limit: 10000 }) }) });
    expect(s).toEqual({ tier: 'free', used: 10, limit: 10000 });
  });
});

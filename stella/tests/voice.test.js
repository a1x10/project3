import { describe, it, expect, vi } from 'vitest';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { synthesize, listVoices, transcribe, getSubscription, cleanForSpeech, elError, checkKey } = require('../src/main/voice.js');

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
    await expect(synthesize({ apiKey: 'k', voiceId: 'v', text: 'x', fetchImpl: async () => ({ ok: false, status: 401, text: async () => '{"detail":{"message":"invalid"}}' }) })).rejects.toThrow(/ElevenLabs отклонил ключ.*invalid/);
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

describe('Диагностика ошибок ElevenLabs', () => {
  const err = (status, detail) => elError(status, JSON.stringify({ detail }));
  it('неверный ключ', () => expect(err(401, { status: 'invalid_api_key', message: 'Invalid API key' }).message).toMatch(/Неверный ключ/));
  it('нет разрешений у ключа', () => {
    const e = err(401, { status: 'missing_permissions', message: 'The API key you used is missing the permission text_to_speech' });
    expect(e.message).toMatch(/разрешений/);
    expect(e.message).toMatch(/Text to Speech/);
    expect(e.fatal).toBe(true);
  });
  it('401 из-за квоты — это не «неверный ключ»', () => expect(err(401, { status: 'quota_exceeded', message: 'quota' }).message).toMatch(/закончились символы/));
  it('бесплатный тариф заблокирован (VPN)', () => expect(err(401, { status: 'detected_unusual_activity', message: 'Unusual activity detected' }).message).toMatch(/VPN/));
  it('голос не найден — не фатально', () => { const e = err(404, { status: 'voice_not_found', message: 'x' }); expect(e.message).toMatch(/Загрузить голоса/); expect(e.fatal).toBe(false); });
  it('текстовая деталь без кода', () => expect(elError(429, JSON.stringify({ detail: 'Too many' })).message).toMatch(/Слишком много/));
  it('сетевая ошибка — подсказка про VPN и облако', async () => {
    const fetchImpl = async () => { throw Object.assign(new Error('fetch failed'), { cause: { code: 'ECONNRESET' } }); };
    await expect(synthesize({ apiKey: 'k', voiceId: 'v', text: 'x', fetchImpl })).rejects.toThrow(/Нет связи с api.elevenlabs.io \(ECONNRESET\).*Stella Cloud/);
  });
});

describe('Проверка ключа по шагам', () => {
  const ok = (body) => ({ ok: true, json: async () => body, arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer });
  const fetchFor = (map) => async (url) => { for (const [k, v] of Object.entries(map)) if (url.includes(k)) return v; throw new Error('?'); };
  it('всё работает', async () => {
    const r = await checkKey({ apiKey: 'sk_good', voiceId: 'v1', fetchImpl: fetchFor({ subscription: ok({ tier: 'free', character_count: 1, character_limit: 10 }), '/voices': ok({ voices: [{ voice_id: 'v1', name: 'A' }] }), 'text-to-speech': ok({}) }) });
    expect(r.ok).toBe(true);
    expect(r.steps.map((s) => s.ok)).toEqual([true, true, true, true]);
  });
  it('ключ с пробелом', async () => {
    const r = await checkKey({ apiKey: 'sk_good \n', voiceId: 'v1', fetchImpl: fetchFor({ subscription: ok({}), '/voices': ok({ voices: [] }), 'text-to-speech': ok({}) }) });
    expect(r.steps[0]).toMatchObject({ ok: false });
  });
  it('выбранного голоса нет', async () => {
    const r = await checkKey({ apiKey: 'k', voiceId: 'missing', fetchImpl: fetchFor({ subscription: ok({}), '/voices': ok({ voices: [{ voice_id: 'other' }] }), 'text-to-speech': ok({}) }) });
    expect(r.steps[2].info).toMatch(/ВЫБРАННОГО ГОЛОСА НЕТ/);
  });
  it('ограниченный ключ: тариф не читается, но синтез работает', async () => {
    const denied = { ok: false, status: 401, text: async () => JSON.stringify({ detail: { status: 'missing_permissions', message: 'missing user_read' } }) };
    const r = await checkKey({ apiKey: 'k', voiceId: 'v', fetchImpl: fetchFor({ subscription: denied, '/voices': denied, 'text-to-speech': ok({}) }) });
    expect(r.ok).toBe(true);
    expect(r.steps[1]).toMatchObject({ ok: false });
  });
  it('пустой ключ', async () => expect((await checkKey({ apiKey: '' })).ok).toBe(false));
});

describe('Голос Стеллы по умолчанию: Вероника на Eleven v3', async () => {
  const { voiceSettingsFor, STELLA_VOICE } = await import('../src/main/voice.js');
  it('id голоса Вероники', () => expect(STELLA_VOICE).toBe('OowtKaZH9N7iuGbsd00l'));
  it('v3: только stability, ровно 0 / 0.5 / 1', () => {
    expect(voiceSettingsFor('eleven_v3', { stability: 1, style: 0.9, speed: 1.1 })).toEqual({ stability: 1 });
    expect(voiceSettingsFor('eleven_v3', { stability: 0.45 })).toEqual({ stability: 0.5 });
    expect(voiceSettingsFor('eleven_v3', { stability: 0.1 })).toEqual({ stability: 0 });
  });
  it('v2: все ползунки', () => expect(voiceSettingsFor('eleven_multilingual_v2', { stability: 0.4, similarity: 0.8, style: 0.3, speed: 1 })).toEqual({ stability: 0.4, similarity_boost: 0.8, style: 0.3, use_speaker_boost: true, speed: 1 }));
  it('запрос как в ElevenLabs: Вероника, eleven_v3, stability 1.0, mp3 44.1 кГц', async () => {
    const fetchImpl = vi.fn(async () => ({ ok: true, arrayBuffer: async () => new Uint8Array([1]).buffer }));
    await synthesize({ apiKey: 'k', voiceId: STELLA_VOICE, text: 'Привет! Это Стелла.', modelId: 'eleven_v3', stability: 1, fetchImpl });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe('https://api.elevenlabs.io/v1/text-to-speech/OowtKaZH9N7iuGbsd00l?output_format=mp3_44100_128');
    expect(JSON.parse(init.body)).toEqual({ text: 'Привет! Это Стелла.', model_id: 'eleven_v3', voice_settings: { stability: 1 } });
  });
});

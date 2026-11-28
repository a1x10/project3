'use strict';
// ElevenLabs: синтез речи (TTS), список голосов, распознавание (STT).
const BASE = 'https://api.elevenlabs.io/v1';

/** Голос Стеллы по умолчанию: «Veronica - Energetic, Clear and Rich» (русский, женский). */
const STELLA_VOICE = 'OowtKaZH9N7iuGbsd00l';

/**
 * Настройки голоса под модель. У Eleven v3 есть только Stability и только три значения:
 * 0 — Creative, 0.5 — Natural, 1 — Robust. Остальное (similarity, style, speed) шлём только для v2/Flash/Turbo.
 */
function voiceSettingsFor(modelId, { stability = 0.45, similarity = 0.8, style = 0.35, speed = 1 } = {}) {
  const st = Math.min(1, Math.max(0, Number(stability) || 0));
  if (/^eleven_v3/.test(modelId || '')) return { stability: st < 0.25 ? 0 : st < 0.75 ? 0.5 : 1 };
  return { stability: st, similarity_boost: similarity, style, use_speaker_boost: true, speed: Math.min(1.2, Math.max(0.7, speed || 1)) };
}

const STATUS_HINTS = {
  invalid_api_key: 'Неверный ключ ElevenLabs. Скопируй ключ заново: elevenlabs.io → Developers → API Keys.',
  missing_permissions: 'У ключа ElevenLabs не хватает разрешений. В настройках ключа включи: Text to Speech, Speech to Text, Voices (Read) и User (Read) — или создай ключ без ограничений.',
  quota_exceeded: 'На тарифе ElevenLabs закончились символы.',
  detected_unusual_activity: 'ElevenLabs отключил бесплатный тариф для этого аккаунта («необычная активность») — так бывает при работе через VPN/прокси. Нужен платный тариф ElevenLabs или сервер Stella Cloud.',
  voice_not_found: 'Голос не найден в твоём аккаунте ElevenLabs. Нажми «Загрузить голоса» и выбери голос из списка.',
  payment_required: 'Нужна оплата тарифа ElevenLabs.',
  free_users_not_allowed: 'Этот голос или модель недоступны на бесплатном тарифе ElevenLabs. Выбери другой голос или модель Flash v2.5.',
  model_not_found: 'Модель синтеза не найдена — выбери Multilingual v2 или Flash v2.5.',
};

function elError(status, text) {
  let msg = text, code = '';
  try {
    const j = JSON.parse(text);
    const d = j.detail;
    code = (d && typeof d === 'object' ? d.status || d.code : '') || '';
    msg = (d && typeof d === 'object' ? d.message : d) || j.message || text;
  } catch { /* */ }
  const hints = { 401: 'ElevenLabs отклонил ключ.', 402: 'Закончились символы на тарифе ElevenLabs.', 404: 'Голос не найден.', 422: 'Некорректные параметры голоса.', 429: 'Слишком много запросов к ElevenLabs.' };
  const hint = STATUS_HINTS[code] || (/permission/i.test(msg) ? STATUS_HINTS.missing_permissions : /unusual activity/i.test(msg) ? STATUS_HINTS.detected_unusual_activity : /quota/i.test(msg) ? STATUS_HINTS.quota_exceeded : hints[status] || 'Ошибка ElevenLabs');
  const e = new Error(`${hint} (${status}${code ? ', ' + code : ''}) ${String(msg).slice(0, 200)}`.trim());
  e.status = status; e.code = code;
  // «насовсем» выключаем ElevenLabs только при проблемах с ключом/балансом
  e.fatal = ['invalid_api_key', 'quota_exceeded', 'detected_unusual_activity', 'missing_permissions', 'payment_required'].includes(code) || (status === 401 && !code);
  return e;
}

/** Сетевые ошибки (нет доступа к api.elevenlabs.io). */
async function elFetch(fetchImpl, url, init) {
  try { return await fetchImpl(url, init); }
  catch (e) {
    const err = new Error(`Нет связи с api.elevenlabs.io (${e.cause?.code || e.message}). Сервис может быть недоступен из твоей сети или страны — включи VPN или используй сервер Stella Cloud.`);
    err.network = true;
    throw err;
  }
}

/** Убирает из текста то, что не нужно произносить: теги, markdown, ссылки, код. */
function cleanForSpeech(text) {
  return String(text || '')
    .replace(/```[\s\S]*?```/g, ' (код на экране) ')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\[[a-z_]+\]/gi, '')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
    .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '$1')
    .replace(/https?:\/\/\S+/g, 'ссылка')
    .replace(/[*_#>~|]+/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

async function synthesize({ apiKey, voiceId, text, modelId = 'eleven_multilingual_v2', stability = 0.45, similarity = 0.8, style = 0.35, speed = 1, fetchImpl = fetch, signal }) {
  if (!apiKey) throw new Error('Не задан ключ ElevenLabs');
  if (!voiceId) throw new Error('Не выбран голос');
  const t = cleanForSpeech(text);
  if (!t) return null;
  const res = await elFetch(fetchImpl, `${BASE}/text-to-speech/${encodeURIComponent(voiceId)}?output_format=mp3_44100_128`, {
    method: 'POST',
    headers: { 'xi-api-key': apiKey, 'Content-Type': 'application/json', Accept: 'audio/mpeg' },
    body: JSON.stringify({
      text: t,
      model_id: modelId,
      voice_settings: voiceSettingsFor(modelId, { stability, similarity, style, speed }),
    }),
    signal,
  });
  if (!res.ok) throw elError(res.status, await res.text());
  return Buffer.from(await res.arrayBuffer());
}

async function listVoices({ apiKey, fetchImpl = fetch }) {
  if (!apiKey) throw new Error('Не задан ключ ElevenLabs');
  const res = await elFetch(fetchImpl, `${BASE}/voices`, { headers: { 'xi-api-key': apiKey } });
  if (!res.ok) throw elError(res.status, await res.text());
  const j = await res.json();
  return (j.voices || []).map((v) => ({
    id: v.voice_id, name: v.name, category: v.category,
    gender: v.labels?.gender || '', accent: v.labels?.accent || '', description: v.labels?.description || v.description || '',
    preview: v.preview_url || '',
  }));
}

async function transcribe({ apiKey, audio, mime = 'audio/webm', language = 'rus', fetchImpl = fetch }) {
  if (!apiKey) throw new Error('Для распознавания речи нужен ключ ElevenLabs');
  const form = new FormData();
  form.append('model_id', 'scribe_v1');
  if (language && language !== 'auto') form.append('language_code', language);
  form.append('tag_audio_events', 'false');
  form.append('file', new Blob([audio], { type: mime }), 'speech.webm');
  const res = await elFetch(fetchImpl, `${BASE}/speech-to-text`, { method: 'POST', headers: { 'xi-api-key': apiKey }, body: form });
  if (!res.ok) throw elError(res.status, await res.text());
  const j = await res.json();
  return String(j.text || '').trim();
}

async function getSubscription({ apiKey, fetchImpl = fetch }) {
  const res = await elFetch(fetchImpl, `${BASE}/user/subscription`, { headers: { 'xi-api-key': apiKey } });
  if (!res.ok) throw elError(res.status, await res.text());
  const j = await res.json();
  return { tier: j.tier, used: j.character_count, limit: j.character_limit };
}

// ---- Через сервер Stella Cloud ----
function cloudErr(status, text) {
  let msg = text; try { msg = JSON.parse(text).error?.message || text; } catch { /* */ }
  const e = new Error(`Stella Cloud: ${String(msg).slice(0, 200)}`); e.status = status; return e;
}
async function cloudSynthesize({ base, token, voiceId, text, modelId, stability, similarity, style, speed, fetchImpl = fetch }) {
  const t = cleanForSpeech(text);
  if (!t) return null;
  const res = await fetchImpl(base.replace(/\/$/, '') + '/api/tts', {
    method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: t, voiceId, modelId, voiceSettings: voiceSettingsFor(modelId, { stability, similarity, style, speed }) }),
  });
  if (!res.ok) throw cloudErr(res.status, await res.text());
  return Buffer.from(await res.arrayBuffer());
}
async function cloudTranscribe({ base, token, audio, mime = 'audio/wav', language = 'rus', fetchImpl = fetch }) {
  const form = new FormData();
  form.append('model_id', 'scribe_v1');
  if (language && language !== 'auto') form.append('language_code', language);
  form.append('file', new Blob([audio], { type: mime }), 'speech.wav');
  const req = new Request('http://x', { method: 'POST', body: form });
  const res = await fetchImpl(base.replace(/\/$/, '') + '/api/stt', { method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': req.headers.get('content-type') }, body: Buffer.from(await req.arrayBuffer()) });
  if (!res.ok) throw cloudErr(res.status, await res.text());
  return String((await res.json()).text || '').trim();
}
async function cloudVoices({ base, token, fetchImpl = fetch }) {
  const res = await fetchImpl(base.replace(/\/$/, '') + '/api/voices', { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw cloudErr(res.status, await res.text());
  const j = await res.json();
  return (j.voices || []).map((v) => ({ id: v.voice_id, name: v.name, category: v.category, gender: v.labels?.gender || '', accent: v.labels?.accent || '', description: '', preview: v.preview_url || '' }));
}

/** Пошаговая проверка ключа: подписка, список голосов, пробный синтез. */
async function checkKey({ apiKey, voiceId, modelId, fetchImpl = fetch }) {
  const steps = [];
  const k = String(apiKey || '');
  if (!k) return { ok: false, steps: [{ name: 'Ключ', ok: false, info: 'Ключ не задан' }] };
  if (k !== k.trim() || /\s/.test(k)) steps.push({ name: 'Формат ключа', ok: false, info: 'В ключе есть пробелы или переносы строк — вставь его заново' });
  else steps.push({ name: 'Формат ключа', ok: true, info: `${k.slice(0, 4)}… (${k.length} символов)` });
  const run = async (name, fn) => { try { steps.push({ name, ok: true, info: await fn() }); } catch (e) { steps.push({ name, ok: false, info: e.message }); } };
  await run('Тариф и баланс', async () => { const s = await getSubscription({ apiKey: k, fetchImpl }); return `${s.tier}: использовано ${s.used} из ${s.limit} символов`; });
  await run('Список голосов', async () => { const v = await listVoices({ apiKey: k, fetchImpl }); return `доступно голосов: ${v.length}${v.some((x) => x.id === voiceId) ? ', выбранный голос есть' : ', ВЫБРАННОГО ГОЛОСА НЕТ — выбери другой'}`; });
  await run('Пробный синтез', async () => { const b = await synthesize({ apiKey: k, voiceId, text: 'Проверка голоса.', modelId, fetchImpl }); return `получено ${b.length} байт звука`; });
  const synth = steps.find((x) => x.name === 'Пробный синтез');
  return { ok: !!synth?.ok, steps };
}

module.exports = { STELLA_VOICE, voiceSettingsFor, checkKey, elError, cloudSynthesize, cloudTranscribe, cloudVoices, synthesize, listVoices, transcribe, getSubscription, cleanForSpeech, BASE };

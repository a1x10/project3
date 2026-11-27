'use strict';
// ElevenLabs: синтез речи (TTS), список голосов, распознавание (STT).
const BASE = 'https://api.elevenlabs.io/v1';

function elError(status, text) {
  let msg = text;
  try { const j = JSON.parse(text); msg = j.detail?.message || j.detail?.status || (typeof j.detail === 'string' ? j.detail : '') || j.message || text; } catch { /* */ }
  const hints = { 401: 'Неверный ключ ElevenLabs.', 402: 'Закончились символы на тарифе ElevenLabs.', 404: 'Голос не найден.', 422: 'Некорректные параметры голоса.', 429: 'Слишком много запросов к ElevenLabs.' };
  const e = new Error(`${hints[status] || 'Ошибка ElevenLabs'} (${status}) ${String(msg).slice(0, 200)}`.trim());
  e.status = status;
  return e;
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
  const res = await fetchImpl(`${BASE}/text-to-speech/${encodeURIComponent(voiceId)}?output_format=mp3_44100_128`, {
    method: 'POST',
    headers: { 'xi-api-key': apiKey, 'Content-Type': 'application/json', Accept: 'audio/mpeg' },
    body: JSON.stringify({
      text: t,
      model_id: modelId,
      voice_settings: { stability, similarity_boost: similarity, style, use_speaker_boost: true, speed: Math.min(1.2, Math.max(0.7, speed)) },
    }),
    signal,
  });
  if (!res.ok) throw elError(res.status, await res.text());
  return Buffer.from(await res.arrayBuffer());
}

async function listVoices({ apiKey, fetchImpl = fetch }) {
  if (!apiKey) throw new Error('Не задан ключ ElevenLabs');
  const res = await fetchImpl(`${BASE}/voices`, { headers: { 'xi-api-key': apiKey } });
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
  const res = await fetchImpl(`${BASE}/speech-to-text`, { method: 'POST', headers: { 'xi-api-key': apiKey }, body: form });
  if (!res.ok) throw elError(res.status, await res.text());
  const j = await res.json();
  return String(j.text || '').trim();
}

async function getSubscription({ apiKey, fetchImpl = fetch }) {
  const res = await fetchImpl(`${BASE}/user/subscription`, { headers: { 'xi-api-key': apiKey } });
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
    body: JSON.stringify({ text: t, voiceId, modelId, voiceSettings: { stability, similarity_boost: similarity, style, use_speaker_boost: true, speed: Math.min(1.2, Math.max(0.7, speed || 1)) } }),
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

module.exports = { cloudSynthesize, cloudTranscribe, cloudVoices, synthesize, listVoices, transcribe, getSubscription, cleanForSpeech, BASE };

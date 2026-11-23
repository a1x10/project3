// "Конференция": live meeting assistant for Stella.exe (like Natively / meeting copilots).
//   the PC records short speech segments (mic = "Я", system sound = "Собеседник") and sends them here;
//   we transcribe them with the fastest Gemini model and answer questions / suggest replies / summarise
//   with a fast model, streaming the text back. Nothing is stored on the server.
const services = require('./services');

const KEY = () => process.env.STELLA_CONF_GEMINI_KEY || process.env.STELLA_GEMINI_API_KEY || '';
const BASE = () => (process.env.STELLA_GEMINI_BASE || 'https://generativelanguage.googleapis.com').replace(/\/$/, '');
const STT_MODEL = () => process.env.STELLA_CONF_STT_MODEL || 'gemini-flash-lite-latest';
const CHAT_MODEL = () => process.env.STELLA_CONF_MODEL || 'gemini-flash-latest';

// OpenRouter (one key for everything): answers by DeepSeek, speech recognition by a Gemini Flash Lite model there.
// Used when STELLA_OPENROUTER_KEY is set (or STELLA_CONF_PROVIDER=openrouter); otherwise Google Gemini directly.
const OR_KEY = () => process.env.STELLA_OPENROUTER_KEY || '';
const OR_BASE = () => (process.env.STELLA_OPENROUTER_BASE || 'https://openrouter.ai/api/v1').replace(/\/$/, '');
const OR_MODEL = () => process.env.STELLA_CONF_OR_MODEL || 'deepseek/deepseek-v4.1-flash';
const OR_STT_MODEL = () => process.env.STELLA_CONF_OR_STT_MODEL || 'google/gemini-3.1-flash-lite';
function provider() {
  const want = (process.env.STELLA_CONF_PROVIDER || '').toLowerCase();
  if (want === 'gemini' && KEY()) return 'gemini';
  if (OR_KEY()) return 'openrouter';
  return 'gemini';
}

function status() {
  if (provider() === 'openrouter') return { ready: true, provider: 'openrouter', stt: OR_STT_MODEL(), model: OR_MODEL() };
  return { ready: !!KEY(), provider: 'gemini', stt: STT_MODEL(), model: CHAT_MODEL() };
}

async function openrouter(body, timeout) {
  const r = await fetch(OR_BASE() + '/chat/completions', {
    method: 'POST',
    headers: { 'content-type': 'application/json', authorization: 'Bearer ' + OR_KEY(), 'x-title': 'Stella' },
    body: JSON.stringify(body), signal: AbortSignal.timeout(timeout || 120000)
  });
  if (!r.ok) { const t = await r.text().catch(() => ''); let m = t; try { m = JSON.parse(t).error.message; } catch {} throw new Error('OpenRouter ' + r.status + ': ' + String(m).slice(0, 200)); }
  return r;
}
// OpenAI-style SSE -> text deltas
async function* sseDeltas(r) {
  const dec = new TextDecoder(); let buf = '';
  for await (const chunk of r.body) {
    buf += dec.decode(chunk, { stream: true });
    let i;
    while ((i = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
      if (!line.startsWith('data:') || line === 'data: [DONE]') continue;
      try { const t = JSON.parse(line.slice(5)).choices?.[0]?.delta?.content; if (t) yield t; } catch {}
    }
  }
}
const STT_PROMPT = 'Transcribe this speech verbatim in the language it is spoken (Russian, Kazakh, English or mixed). ' +
  'Output ONLY the transcribed text with punctuation (keep "?" for questions). No comments, no translation. ' +
  'If there is no intelligible speech (silence, noise, music) output nothing.';
const AUDIO_FORMAT = { 'audio/wav': 'wav', 'audio/mp3': 'mp3', 'audio/ogg': 'ogg', 'audio/flac': 'flac', 'audio/webm': 'webm', 'audio/mp4': 'm4a' };

async function gemini(model, body, stream) {
  if (!KEY()) throw new Error('На сервере не задан ключ для конференций. Запустите установщик с OPENROUTER=1 (DeepSeek) или GEMINI=1.');
  const url = `${BASE()}/v1beta/models/${encodeURIComponent(model)}:${stream ? 'streamGenerateContent?alt=sse' : 'generateContent'}`;
  const r = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json', 'x-goog-api-key': KEY() }, body: JSON.stringify(body), signal: AbortSignal.timeout(stream ? 120000 : 30000) });
  if (!r.ok) { const t = await r.text().catch(() => ''); let m = t; try { m = JSON.parse(t).error.message; } catch {}
    // newer models may not accept thinkingBudget=0 -> retry once with the model's default thinking
    if (r.status === 400 && /thinking/i.test(m) && body.generationConfig && body.generationConfig.thinkingConfig) { delete body.generationConfig.thinkingConfig; return gemini(model, body, stream); }
    throw new Error('Gemini ' + r.status + ': ' + String(m).slice(0, 200)); }
  return r;
}
const textOf = j => ((j.candidates || [])[0]?.content?.parts || []).map(p => p.text || '').join('');

// audio container from the first bytes (WAV from Stella.exe and system audio, WebM/Ogg/MP3 from microphone recorders)
function mimeOf(b64) {
  const h = Buffer.from(String(b64).slice(0, 24), 'base64');
  if (h.slice(0, 4).toString() === 'RIFF') return 'audio/wav';
  if (h[0] === 0x1a && h[1] === 0x45 && h[2] === 0xdf && h[3] === 0xa3) return 'audio/webm';
  if (h.slice(0, 4).toString() === 'OggS') return 'audio/ogg';
  if (h.slice(0, 4).toString() === 'fLaC') return 'audio/flac';
  if (h.slice(0, 3).toString() === 'ID3' || (h[0] === 0xff && (h[1] & 0xe0) === 0xe0)) return 'audio/mp3';
  if (h.slice(4, 8).toString() === 'ftyp') return 'audio/mp4';
  return 'audio/wav';
}
const okModel = (m, def) => (typeof m === 'string' && /^gemini-[\w.-]{1,60}$/.test(m) ? m : def);

// one speech segment (base64 audio) -> text
async function transcribe(u, { audio, who, hint, model }) {
  if (!audio || typeof audio !== 'string') throw new Error('нет аудио');
  audio = audio.replace(/^data:[^,]*,/, '');
  if (provider() === 'openrouter') {
    const r = await openrouter({ model: OR_STT_MODEL(), temperature: 0, max_tokens: 600, messages: [{ role: 'user', content: [
      { type: 'input_audio', input_audio: { data: audio, format: AUDIO_FORMAT[mimeOf(audio)] || 'wav' } },
      { type: 'text', text: STT_PROMPT + (hint ? ' Context words that may appear: ' + String(hint).slice(0, 300) : '') }] }] }, 30000);
    const t = String((await r.json()).choices?.[0]?.message?.content || '').trim();
    return { text: /^(\(.*\)|\[.*\]|-)$/.test(t) ? '' : t, who: who === 'me' ? 'me' : 'them' };
  }
  const r = await gemini(okModel(model, STT_MODEL()), {
    contents: [{ role: 'user', parts: [
      { inline_data: { mime_type: mimeOf(audio), data: audio } },
      { text: STT_PROMPT + (hint ? ' Context words that may appear: ' + String(hint).slice(0, 300) : '') }
    ] }],
    generationConfig: { temperature: 0, maxOutputTokens: 600, thinkingConfig: { thinkingBudget: 0 } }
  });
  const t = textOf(await r.json()).trim();
  return { text: /^(\(.*\)|\[.*\]|-)$/.test(t) ? '' : t, who: who === 'me' ? 'me' : 'them' };
}

const MODES = {
  answer: 'Suggest what the USER should say right now in reply to the latest question or point of the other side. Give a short, natural answer the user can say aloud (2–5 sentences or bullets), then, if useful, 1–2 extra facts in a "Дополнительно:" line. Be concrete, no filler.',
  summary: 'Write a short summary of the meeting so far: key points, decisions, action items with owners/deadlines if mentioned, open questions. Use short Markdown bullets with headings «Главное», «Решения», «Задачи», «Вопросы» (skip empty ones).',
  ask: 'Answer the user\'s question below, using the meeting transcript as context when relevant. Be brief and precise.',
  screen: 'The image is a screenshot of the user\'s screen during the meeting (slides, a shared document, a task, code…). Explain briefly what matters on it and what the user could say or ask about it. If there is a question or task on the screen, answer/solve it.',
  followup: 'Suggest 3 smart questions the user could ask the other side now, based on the conversation. Numbered list, one line each.'
};

// streamed assistant answer -> onDelta(text chunk)
async function assist(u, { mode, transcript, question, image, title }, onDelta) {
  const instr = MODES[mode] || MODES.ask;
  const profile = services.profileText(u) || '';
  const parts = [];
  if (image) parts.push({ inline_data: { mime_type: 'image/jpeg', data: image } });
  parts.push({ text:
    'You are Stella, a real-time meeting assistant sitting next to the user during a call. Reply in the language of the conversation (default Russian). ' +
    'Be fast and short: the user reads your text while talking.\n' + (profile ? 'About the user:\n' + profile.slice(0, 2000) + '\n' : '') +
    (title ? 'Meeting: ' + String(title).slice(0, 200) + '\n' : '') +
    'TRANSCRIPT (Я = the user, Собеседник = other participants; recognition may have small errors):\n' + (String(transcript || '').slice(-14000) || '(пока пусто)') + '\n\n' +
    'TASK: ' + instr + (question ? '\nUSER QUESTION: ' + String(question).slice(0, 2000) : '') });
  if (provider() === 'openrouter') {
    const content = parts.map(p => p.inline_data ? { type: 'image_url', image_url: { url: 'data:' + p.inline_data.mime_type + ';base64,' + p.inline_data.data } } : { type: 'text', text: p.text });
    const r = await openrouter({ model: OR_MODEL(), stream: true, temperature: 0.4, max_tokens: 1500, messages: [{ role: 'user', content }] });
    let all = ''; for await (const t of sseDeltas(r)) { all += t; onDelta(t); }
    return all;
  }
  const r = await gemini(CHAT_MODEL(), { contents: [{ role: 'user', parts }], generationConfig: { temperature: 0.4, maxOutputTokens: 1500, thinkingConfig: { thinkingBudget: 0 } } }, true);
  const dec = new TextDecoder(); let buf = '', all = '';
  for await (const chunk of r.body) {
    buf += dec.decode(chunk, { stream: true });
    let i;
    while ((i = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
      if (!line.startsWith('data:')) continue;
      try { const t = textOf(JSON.parse(line.slice(5))); if (t) { all += t; onDelta(t); } } catch {}
    }
  }
  return all;
}

// OpenAI-compatible chat (used by Stella Conference): proxied to Gemini's OpenAI endpoint with the server key.
// Only gemini-* models; the answer is streamed back unchanged (SSE).
async function chatCompletions(u, body, res) {
  if (provider() === 'openrouter') return chatOpenRouter(u, body, res);
  if (!KEY()) throw new Error('На сервере не задан ключ для конференций. Запустите установщик с OPENROUTER=1 (DeepSeek) или GEMINI=1.');
  if (!body || !Array.isArray(body.messages) || !body.messages.length) throw new Error('нет сообщений');
  const profile = services.profileText(u) || '';
  const messages = body.messages.slice(-60);
  if (profile) messages.unshift({ role: 'system', content: 'About the user (use when it helps):\n' + profile.slice(0, 2000) });
  const req = { model: okModel(body.model, CHAT_MODEL()), messages, stream: body.stream !== false, temperature: typeof body.temperature === 'number' ? body.temperature : 0.5, reasoning_effort: 'none' };
  if (body.max_tokens) req.max_tokens = Math.min(Number(body.max_tokens) || 2048, 8192);
  const call = () => fetch(BASE() + '/v1beta/openai/chat/completions', { method: 'POST', headers: { 'content-type': 'application/json', authorization: 'Bearer ' + KEY() }, body: JSON.stringify(req), signal: AbortSignal.timeout(120000) });
  let r = await call();
  if (r.status === 400) {                   // a model that cannot switch thinking off -> its default
    const t = await r.text(); if (!/reason|think/i.test(t)) throw new Error('Gemini 400: ' + t.slice(0, 200));
    delete req.reasoning_effort; r = await call();
  }
  if (!r.ok) { const t = await r.text().catch(() => ''); let m = t; try { m = (JSON.parse(t)[0] || JSON.parse(t)).error.message; } catch {} throw new Error('Gemini ' + r.status + ': ' + String(m).slice(0, 200)); }
  res.writeHead(200, { 'content-type': r.headers.get('content-type') || 'text/event-stream', 'cache-control': 'no-store', 'x-accel-buffering': 'no' });
  for await (const c of r.body) res.write(c);
  res.end();
}

// same, through OpenRouter: DeepSeek answers (text + images); the client's model name is ignored (server decides)
async function chatOpenRouter(u, body, res) {
  if (!body || !Array.isArray(body.messages) || !body.messages.length) throw new Error('нет сообщений');
  const profile = services.profileText(u) || '';
  const messages = body.messages.slice(-60);
  if (profile) messages.unshift({ role: 'system', content: 'About the user (use when it helps):\n' + profile.slice(0, 2000) });
  const req = { model: OR_MODEL(), messages, stream: body.stream !== false, temperature: typeof body.temperature === 'number' ? body.temperature : 0.5 };
  if (body.max_tokens) req.max_tokens = Math.min(Number(body.max_tokens) || 2048, 8192);
  const r = await openrouter(req);
  res.writeHead(200, { 'content-type': r.headers.get('content-type') || 'text/event-stream', 'cache-control': 'no-store', 'x-accel-buffering': 'no' });
  for await (const c of r.body) res.write(c);
  res.end();
}

module.exports = { status, transcribe, assist, chatCompletions, provider, MODES };

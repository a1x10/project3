// "Конференция": live meeting assistant for Stella.exe (like Natively / meeting copilots).
//   the PC records short speech segments (mic = "Я", system sound = "Собеседник") and sends them here;
//   we transcribe them with the fastest Gemini model and answer questions / suggest replies / summarise
//   with a fast model, streaming the text back. Nothing is stored on the server.
const services = require('./services');

const KEY = () => process.env.STELLA_CONF_GEMINI_KEY || process.env.STELLA_GEMINI_API_KEY || '';
const BASE = () => (process.env.STELLA_GEMINI_BASE || 'https://generativelanguage.googleapis.com').replace(/\/$/, '');
const STT_MODEL = () => process.env.STELLA_CONF_STT_MODEL || 'gemini-flash-lite-latest';
const CHAT_MODEL = () => process.env.STELLA_CONF_MODEL || 'gemini-flash-latest';

function status() { return { ready: !!KEY(), stt: STT_MODEL(), model: CHAT_MODEL() }; }

async function gemini(model, body, stream) {
  if (!KEY()) throw new Error('На сервере не задан ключ Gemini для конференций (STELLA_CONF_GEMINI_KEY). Запустите установщик с GEMINI=1.');
  const url = `${BASE()}/v1beta/models/${encodeURIComponent(model)}:${stream ? 'streamGenerateContent?alt=sse' : 'generateContent'}`;
  const r = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json', 'x-goog-api-key': KEY() }, body: JSON.stringify(body), signal: AbortSignal.timeout(stream ? 120000 : 30000) });
  if (!r.ok) { const t = await r.text().catch(() => ''); let m = t; try { m = JSON.parse(t).error.message; } catch {}
    // newer models may not accept thinkingBudget=0 -> retry once with the model's default thinking
    if (r.status === 400 && /thinking/i.test(m) && body.generationConfig && body.generationConfig.thinkingConfig) { delete body.generationConfig.thinkingConfig; return gemini(model, body, stream); }
    throw new Error('Gemini ' + r.status + ': ' + String(m).slice(0, 200)); }
  return r;
}
const textOf = j => ((j.candidates || [])[0]?.content?.parts || []).map(p => p.text || '').join('');

// one speech segment (16 kHz mono WAV, base64) -> text
async function transcribe(u, { audio, who, hint }) {
  if (!audio || typeof audio !== 'string') throw new Error('нет аудио');
  const r = await gemini(STT_MODEL(), {
    contents: [{ role: 'user', parts: [
      { inline_data: { mime_type: 'audio/wav', data: audio } },
      { text: 'Transcribe this speech verbatim in the language it is spoken (Russian, Kazakh, English or mixed). ' +
        'Output ONLY the transcribed text with punctuation (keep "?" for questions). No comments, no translation. ' +
        'If there is no intelligible speech (silence, noise, music) output nothing.' + (hint ? ' Context words that may appear: ' + String(hint).slice(0, 300) : '') }
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

module.exports = { status, transcribe, assist, MODES };

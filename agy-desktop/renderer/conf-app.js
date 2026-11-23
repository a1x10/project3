// «Конференция» window: records speech segments from the mic («Я») and the call sound («Собеседник»),
// gets them transcribed on the Stella server and shows instant hints.
const $ = s => document.querySelector(s);
const C = window.conf;
const st = { lines: [], started: Date.now(), paused: false, seq: 0, ctx: null, chans: {}, ans: null, answers: [], autoT: 0, lastAuto: 0 };

/* ---------------- audio: 16 kHz mono, simple voice activity detection ---------------- */
const RATE = 16000, FRAME = 4096, FRAME_MS = FRAME / RATE * 1000;
function wav(samples) {
  const b = new ArrayBuffer(44 + samples.length * 2), v = new DataView(b);
  const w = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  w(0, 'RIFF'); v.setUint32(4, 36 + samples.length * 2, true); w(8, 'WAVE'); w(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, RATE, true); v.setUint32(28, RATE * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, 'data'); v.setUint32(40, samples.length * 2, true);
  for (let i = 0, o = 44; i < samples.length; i++, o += 2) { const x = Math.max(-1, Math.min(1, samples[i])); v.setInt16(o, x < 0 ? x * 0x8000 : x * 0x7fff, true); }
  const u8 = new Uint8Array(b); let s = ''; for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  return btoa(s);
}
function channel(who, stream) {
  const src = st.ctx.createMediaStreamSource(stream);
  const proc = st.ctx.createScriptProcessor(FRAME, 1, 1);
  const mute = st.ctx.createGain(); mute.gain.value = 0;          // keep the node running without playing anything
  src.connect(proc); proc.connect(mute); mute.connect(st.ctx.destination);
  const ch = { who, stream, src, proc, enabled: true, noise: 0.004, buf: [], pre: null, speaking: false, silence: 0, speech: 0, startedAt: 0 };
  proc.onaudioprocess = e => {
    if (st.paused || !ch.enabled) return;
    const d = new Float32Array(e.inputBuffer.getChannelData(0));
    let sum = 0; for (let i = 0; i < d.length; i++) sum += d[i] * d[i];
    const rms = Math.sqrt(sum / d.length);
    const loud = rms > Math.max(0.008, ch.noise * 3);
    if (!loud) ch.noise = ch.noise * 0.95 + rms * 0.05;               // track background noise
    if (loud) {
      if (!ch.speaking) { ch.speaking = true; ch.startedAt = Date.now(); if (ch.pre) ch.buf.push(ch.pre); }
      ch.buf.push(d); ch.speech += FRAME_MS; ch.silence = 0;
    } else if (ch.speaking) {
      ch.buf.push(d); ch.silence += FRAME_MS;
      if (ch.silence >= 750) flush(ch);
    } else ch.pre = d;
    if (ch.speaking && ch.buf.length * FRAME_MS >= 12000) flush(ch, true);   // long monologue: send every ~12 s
  };
  return ch;
}
function flush(ch, cont) {
  const parts = ch.buf, speech = ch.speech, at = ch.startedAt;
  ch.buf = []; ch.speech = 0; ch.silence = 0;
  if (!cont) ch.speaking = false; else ch.startedAt = Date.now();
  if (speech < 450) return;                                          // a click / cough
  const n = parts.reduce((a, p) => a + p.length, 0), all = new Float32Array(n);
  let o = 0; for (const p of parts) { all.set(p, o); o += p.length; }
  const line = { id: ++st.seq, who: ch.who, at, text: '', pending: true };
  st.lines.push(line); st.lines.sort((a, b) => a.at - b.at); render();
  C.transcribe(wav(all), ch.who, '').then(r => {
    line.pending = false;
    if (r.error) { line.text = ''; notice('Распознавание: ' + r.error); }
    else line.text = (r.text || '').trim();
    if (!line.text) st.lines = st.lines.filter(l => l !== line);
    render();
    if (line.text && line.who === 'them') maybeAuto(line.text);
  });
}

async function startAudio() {
  st.ctx = new AudioContext({ sampleRate: RATE });
  const errs = [];
  try {
    const mic = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } });
    st.chans.me = channel('me', mic);
  } catch (e) { errs.push('микрофон недоступен (' + e.message + ')'); }
  try {
    const sys = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
    sys.getVideoTracks().forEach(t => t.stop());
    if (sys.getAudioTracks().length) st.chans.them = channel('them', new MediaStream(sys.getAudioTracks()));
    else errs.push('звук звонка недоступен');
  } catch (e) { errs.push('звук звонка недоступен (' + e.message + ')'); }
  if (errs.length) notice('⚠ ' + errs.join('; ') + '.');
  else notice('🎧 Лучше в наушниках: иначе микрофон услышит собеседника из колонок и его речь попадёт в «Я». Предупредите участников, что разговор расшифровывается.', 9000);
  $('#mic').checked = !!st.chans.me; $('#sys').checked = !!st.chans.them;
}
function stopAudio() {
  for (const ch of Object.values(st.chans)) { if (ch.speaking) flush(ch); ch.proc.disconnect(); ch.stream.getTracks().forEach(t => t.stop()); }
  st.chans = {}; if (st.ctx) st.ctx.close().catch(() => {});
}

/* ---------------- UI ---------------- */
let noticeT = 0;
function notice(t, ms = 0) { const n = $('#notice'); n.textContent = t; n.hidden = false; clearTimeout(noticeT); if (ms) noticeT = setTimeout(() => n.hidden = true, ms); }
const hhmm = t => { const d = new Date(t); return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); };
const LABEL = { me: 'Я', them: 'Собеседник' };
function render() {
  const box = $('#transcript'), atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  $('#empty').hidden = st.lines.length > 0;
  box.querySelectorAll('p.l').forEach(x => x.remove());
  for (const l of st.lines) {
    const p = document.createElement('p'); p.className = 'l ' + l.who;
    p.innerHTML = `<span class="who">${LABEL[l.who]}</span>` + (l.pending ? '<span class="pending">…</span>' : escapeHtml(l.text)) + `<span class="t">${hhmm(l.at)}</span>`;
    box.appendChild(p);
  }
  if (atBottom) box.scrollTop = box.scrollHeight;
}
function transcriptText() { return st.lines.filter(l => l.text).map(l => `[${hhmm(l.at)}] ${LABEL[l.who]}: ${l.text}`).join('\n'); }

const TITLES = { answer: '💡 Что ответить', followup: '❓ Вопросы собеседнику', summary: '📝 Итоги', screen: '📸 На экране', ask: '💬 Ответ' };
async function ask(mode, question) {
  if (st.ans) C.cancel(st.ans.id);
  const id = 'a' + Date.now();
  st.ans = { id, mode, question, text: '' };
  $('#answer').hidden = false; $('#atitle').textContent = TITLES[mode] + (question ? ': ' + question.slice(0, 40) : '');
  const at = $('#atext'); at.innerHTML = '<p style="color:var(--muted)">Думаю…</p>'; at.classList.add('streaming');
  document.querySelectorAll('.actions button').forEach(b => b.disabled = true);
  await C.assist({ id, mode, question, transcript: transcriptText() });
}
C.onDelta(d => {
  const a = st.ans; if (!a || a.id !== d.id) return;
  const at = $('#atext');
  if (d.text) { a.text += d.text; at.innerHTML = renderMarkdown(a.text); at.scrollTop = at.scrollHeight; }
  if (d.done) {
    at.classList.remove('streaming');
    if (d.error) at.innerHTML = renderMarkdown(a.text) + `<p style="color:#ff9b9b">⚠ ${escapeHtml(d.error)}</p>`;
    if (a.text) st.answers.push({ at: Date.now(), title: TITLES[a.mode], question: a.question, text: a.text });
    document.querySelectorAll('.actions button').forEach(b => b.disabled = false);
  }
});
// a question from the other side -> hint appears by itself
const Q = /\?\s*$|^(как|что|почему|зачем|когда|где|какой|какая|какие|сколько|можете|расскажите|объясните|қалай|неге|қашан|қандай|қанша|what|why|how|when|where|which|could you|can you|tell me)\b/i;
function maybeAuto(text) {
  if (!$('#auto').checked || !Q.test(text.trim())) return;
  if (Date.now() - st.lastAuto < 6000) return;
  clearTimeout(st.autoT);
  st.autoT = setTimeout(() => { st.lastAuto = Date.now(); ask('answer'); }, 900);   // wait a moment in case the question continues
}

document.querySelectorAll('.actions button').forEach(b => b.onclick = () => ask(b.dataset.m));
$('#askf').onsubmit = e => { e.preventDefault(); const q = $('#ask').value.trim(); if (!q) return; $('#ask').value = ''; ask('ask', q); };
$('#aclose').onclick = () => { $('#answer').hidden = true; if (st.ans) C.cancel(st.ans.id); };
$('#acopy').onclick = () => navigator.clipboard.writeText(st.ans ? st.ans.text : '').catch(() => {});
$('#mic').onchange = () => { if (st.chans.me) st.chans.me.enabled = $('#mic').checked; };
$('#sys').onchange = () => { if (st.chans.them) st.chans.them.enabled = $('#sys').checked; };
$('#op').oninput = () => C.opacity($('#op').value / 100);
let pinned = true; $('#pin').classList.add('on');
$('#pin').onclick = () => { pinned = !pinned; $('#pin').classList.toggle('on', pinned); C.pin(pinned); };
$('#min').onclick = () => C.minimize();
$('#pause').onclick = () => { st.paused = !st.paused; $('#pause').textContent = st.paused ? '▶' : '⏸'; $('#rec').classList.toggle('off', st.paused); for (const ch of Object.values(st.chans)) if (st.paused && ch.speaking) flush(ch); };
$('#x').onclick = () => finish().then(() => C.close());
C.onStop(() => finish());
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('#answer').hidden) $('#aclose').click(); if (e.ctrlKey && e.key === 'Enter') ask('answer'); });
setInterval(() => { if (st.paused) return; const s = Math.floor((Date.now() - st.started) / 1000); $('#timer').textContent = String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0'); }, 1000);

// at the end: transcript + hints are saved to «Конференции» in the work folder
let finished = false;
async function finish() {
  if (finished) return; finished = true;
  stopAudio();
  if (!st.lines.some(l => l.text)) return;
  const d = new Date(st.started);
  const md = `# Конференция ${d.toLocaleDateString('ru-RU')} ${hhmm(st.started)}\n\nДлительность: ${$('#timer').textContent}\n\n## Расшифровка\n\n` +
    st.lines.filter(l => l.text).map(l => `**${LABEL[l.who]}** _${hhmm(l.at)}_: ${l.text}`).join('\n\n') +
    (st.answers.length ? '\n\n## Подсказки Stella\n\n' + st.answers.map(a => `### ${a.title}${a.question ? ': ' + a.question : ''} (${hhmm(a.at)})\n\n${a.text}`).join('\n\n') : '') + '\n';
  try { await C.save(md); } catch {}
}

(async () => {
  const s = await C.status();
  await startAudio();
  if (!s.ready) notice('⚠ ' + (s.error || 'На сервере не включены конференции: нужен ключ Gemini (установщик с GEMINI=1).'));
})();

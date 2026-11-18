// Один общий GPU на всех: очередь задач, автозапуск по запросу,
// загрузка нужной модели и автоотключение после простоя.
import crypto from 'node:crypto';
import { config } from './config.js';
import { gpu } from './higgsfield.js';
import { db, saveDb } from './store.js';

const sleep = ms => new Promise(r => setTimeout(r, ms));
const modelFor = kind => (kind === 'video' ? config.videoModel : config.imageModel);

// off -> starting -> loading -> ready <-> generating -> stopping -> off
export const state = {
  phase: 'off', message: 'Сервер выключен', sessionId: null, model: null,
  startedAt: null, lastActivity: Date.now(), current: null, error: null,
};
const set = (phase, message) => { if (state.phase !== phase || state.message !== message) console.log(`[gpu] ${phase}: ${message}`); state.phase = phase; state.message = message; };

let loopRunning = false;

export function queue() { return db.jobs.filter(j => j.status === 'queued'); }

export function publicStatus() {
  const q = queue();
  const idleLeft = ['ready'].includes(state.phase) && !q.length
    ? Math.max(0, Math.ceil(config.idleSeconds - (Date.now() - state.lastActivity) / 1000)) : null;
  return {
    phase: state.phase, message: state.message, model: state.model, queueLength: q.length,
    generating: state.current ? { id: state.current.id, kind: state.current.kind } : null,
    idleLeft, gpu: config.gpuType, creditsPerHour: config.maxCreditsPerHour, error: state.error, mock: config.mock,
  };
}

export function enqueue(user, kind, prompt) {
  const job = {
    id: crypto.randomUUID(), userId: user.id, username: user.username, kind, prompt,
    status: 'queued', createdAt: Date.now(), urls: [], error: null,
  };
  db.jobs.push(job); saveDb();
  state.lastActivity = Date.now();
  ensureRunning();
  return job;
}

export function queuePosition(jobId) {
  const i = queue().findIndex(j => j.id === jobId);
  return i < 0 ? null : i + 1;
}

// Кнопка «Запустить сервер» или новая задача.
export function ensureRunning() {
  state.lastActivity = Date.now();
  if (!loopRunning) {
    loopRunning = true;
    loop().finally(() => { loopRunning = false; if (queue().length && !state.error) ensureRunning(); });
  }
}

async function waitRental(predicate, label, timeoutMs) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    const r = await gpu.rental(state.sessionId);
    if (r.ended) throw new Error('GPU-сервер завершился (' + r.status + ')');
    if (predicate(r)) return r;
    const s = Math.round((Date.now() - t0) / 1000);
    state.message = `${label}… ${s} с`;
    await sleep(3000);
  }
  throw new Error(label + ': превышено время ожидания');
}

async function loadModel(model) {
  set('loading', `Загружаем модель ${model}…`);
  await gpu.prepare(state.sessionId, model);
  await waitRental(r => r.modelReady && (!r.model || r.model.includes(model) || config.mock),
    `Загружаем модель ${model}`, 30 * 60_000);
  state.model = model;
}

function nextJob() {
  const q = queue();
  // Берём задачу под уже загруженную модель, чтобы не перезагружать её лишний раз.
  return q.find(j => modelFor(j.kind) === state.model) || q[0];
}

async function runJob(job) {
  job.status = 'running'; job.startedAt = Date.now(); saveDb();
  state.current = job;
  set('generating', job.kind === 'video' ? 'Генерируем видео…' : 'Генерируем картинку…');
  try {
    const ids = await gpu.generate(state.sessionId, job.prompt, job.kind);
    const t0 = Date.now();
    for (;;) {
      const res = await gpu.wait(ids);
      if (res.every(r => r.done)) {
        const urls = res.flatMap(r => r.urls);
        if (res.some(r => r.ok) && urls.length) { job.status = 'done'; job.urls = urls; }
        else { job.status = 'failed'; job.error = res.map(r => r.error).filter(Boolean).join('; ') || 'генерация не удалась'; }
        break;
      }
      if (Date.now() - t0 > 40 * 60_000) throw new Error('генерация длится слишком долго');
      state.message = `${job.kind === 'video' ? 'Генерируем видео' : 'Генерируем картинку'}… ${Math.round((Date.now() - t0) / 1000)} с`;
    }
  } catch (e) {
    job.status = 'failed'; job.error = String(e.message || e);
  }
  job.finishedAt = Date.now(); saveDb();
  state.current = null; state.lastActivity = Date.now();
}

async function stopServer(reason) {
  if (!state.sessionId) { set('off', reason); return; }
  set('stopping', 'Выключаем сервер…');
  try { await gpu.stop(state.sessionId); } catch (e) { console.error('[gpu] stop failed', e); }
  state.sessionId = null; state.model = null; state.startedAt = null;
  db.meta.sessionId = null; saveDb();
  set('off', reason);
}

async function loop() {
  state.error = null;
  try {
    if (!state.sessionId) {
      set('starting', `Арендуем GPU ${config.gpuType}…`);
      state.sessionId = await gpu.rent();
      db.meta.sessionId = state.sessionId; saveDb();
      state.startedAt = Date.now();
      await waitRental(r => r.running || r.modelReady, `Запускаем GPU ${config.gpuType}`, 15 * 60_000);
    }
    for (;;) {
      const job = nextJob();
      if (job) {
        const need = modelFor(job.kind);
        if (state.model !== need) await loadModel(need);
        await runJob(job);
        continue;
      }
      // Нет задач. Если модель ещё не загружена (нажали «Запустить»), грузим модель для видео.
      if (!state.model) { await loadModel(config.videoModel); state.lastActivity = Date.now(); continue; }
      set('ready', 'Сервер готов — пишите промт');
      if (Date.now() - state.lastActivity > config.idleSeconds * 1000) {
        await stopServer(`Сервер выключен: нет запросов больше ${config.idleSeconds} с`);
        return;
      }
      await sleep(1000);
    }
  } catch (e) {
    console.error('[gpu] error', e);
    state.error = String(e.message || e);
    // Задачи, которые не успели выполнить, помечаем ошибкой, чтобы они не висели вечно.
    for (const j of db.jobs) if (j.status === 'running') { j.status = 'failed'; j.error = state.error; }
    saveDb(); state.current = null;
    await stopServer('Ошибка: ' + state.error);
  }
}

// Если сервер упал/перезапустился, снимаем зависшие задачи.
export async function recover() {
  // Остался GPU от прошлого запуска процесса — выключаем его.
  if (db.meta.sessionId) {
    try { await gpu.stop(db.meta.sessionId); console.log('[gpu] остановлен старый сервер', db.meta.sessionId); } catch {}
    db.meta.sessionId = null;
  }
  for (const j of db.jobs) if (j.status === 'running') { j.status = 'queued'; }
  saveDb();
  if (queue().length) ensureRunning();
}

// Корректно гасим GPU при остановке процесса, чтобы не тратить кредиты.
for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, async () => {
    console.log('\nОстанавливаем GPU перед выходом…');
    if (state.sessionId) { try { await gpu.stop(state.sessionId); } catch {} }
    process.exit(0);
  });
}

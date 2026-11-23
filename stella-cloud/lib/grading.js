// "Проверка работ": photos of handwritten student work (СОР / СОЧ / контрольные) -> grades.
//  - photos are stored in the teacher's own workspace (their container sees them)
//  - each work is checked by an agent with vision (handwriting in ru / kk / en), in parallel
//  - unreadable or uncertain answers are NOT guessed: they are flagged for the teacher
//  - results: editable table, Excel export, and (after the teacher confirms) entry into BilimClass on the PC
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { execFileSync } = require('child_process');
const { readJson, writeJson } = require('./store');
const users = require('./users');
const sandbox = require('./sandbox');

let agent = null, emit = () => {};
function setup(o) { agent = o.agent; emit = o.emit; }

const PARALLEL = Number(process.env.STELLA_GRADING_PARALLEL || 3);
const uid = () => Date.now().toString(36) + crypto.randomBytes(3).toString('hex');
const dir = u => path.join(users.userDir(u), 'grading');
const fileOf = (u, id) => path.join(dir(u), String(id).replace(/[^\w-]/g, '') + '.json');
const photosDir = (u, id) => path.join(u.home, 'workspace', 'Проверка', String(id).replace(/[^\w-]/g, ''));
const running = new Map();             // batchId -> { active }

const RESULT_SCHEMA = {
  type: 'object',
  properties: {
    student: { type: 'string', description: 'student full name exactly as written on the sheet; empty if not found or hidden' },
    klass: { type: 'string', description: 'class as written, e.g. 9А' },
    variant: { type: 'string' },
    legibility: { type: 'string', enum: ['clear', 'hard', 'unreadable'] },
    answers: { type: 'array', items: { type: 'object', properties: {
      task: { type: 'string' }, read_as: { type: 'string', description: 'what the student wrote (transcribed)' },
      points: { type: 'number' }, max: { type: 'number' }, correct: { type: 'boolean' }, comment: { type: 'string' },
      uncertain: { type: 'boolean', description: 'true if you could not read it confidently' } } } },
    total: { type: 'number' }, max_total: { type: 'number' },
    grade: { type: 'string', description: 'final mark according to the scale' },
    confidence: { type: 'number', description: '0..1 how sure you are about the whole result' },
    needs_review: { type: 'boolean', description: 'true if the teacher must look at this work' },
    review_reason: { type: 'string' },
    feedback: { type: 'string', description: '1–2 sentences for the student, in the language of the work' }
  },
  required: ['student', 'legibility', 'total', 'max_total', 'grade', 'confidence', 'needs_review']
};

const DEFAULT_SCALE = 'Перевод процентов в оценку: 85–100% → 5, 65–84% → 4, 40–64% → 3, 0–39% → 2.';

function load(u, id) { return readJson(fileOf(u, id), null); }
function save(u, b) { fs.mkdirSync(dir(u), { recursive: true, mode: 0o700 }); writeJson(fileOf(u, b.id), b); }
function publicBatch(b) {
  const works = b.works.map((w, i) => ({ id: w.id, no: w.no || i + 1, files: w.files.map(f => path.basename(f)), status: w.status, result: w.result || null, edited: w.edited || null, error: w.error || null }));
  const done = works.filter(w => w.status === 'done').length;
  return { id: b.id, title: b.title, subject: b.subject, klass: b.klass, maxScore: b.maxScore, status: b.status, created: b.created, pagesPerWork: b.pagesPerWork, anonymous: !!b.anonymous,
    counts: { total: works.length, done, review: works.filter(w => w.status === 'done' && (w.edited ? false : w.result && w.result.needs_review)).length, failed: works.filter(w => w.status === 'failed').length, uploaded: b.files.length },
    works };
}
const push = (u, b) => emit(u.name, { t: 'grading', batch: publicBatch(b) });
function list(u) {
  if (!fs.existsSync(dir(u))) return [];
  return fs.readdirSync(dir(u)).filter(f => f.endsWith('.json')).map(f => readJson(path.join(dir(u), f), null)).filter(Boolean)
    .sort((a, b) => b.created - a.created).slice(0, 50).map(b => { const p = publicBatch(b); delete p.works; return p; });
}

function create(u, spec) {
  const b = {
    id: uid(), title: String(spec.title || 'Проверка').slice(0, 120), subject: String(spec.subject || '').slice(0, 80), klass: String(spec.klass || '').slice(0, 20),
    key: String(spec.key || '').slice(0, 20000), maxScore: Number(spec.maxScore) || null, scale: String(spec.scale || DEFAULT_SCALE).slice(0, 2000),
    pagesPerWork: Math.max(1, Math.min(10, Number(spec.pagesPerWork) || 1)),
    // anonymous: the phone blacks out the name area BEFORE upload; names and the class list never leave the phone
    anonymous: !!spec.anonymous, roster: spec.anonymous ? '' : String(spec.roster || '').slice(0, 10000),
    status: 'uploading', created: Date.now(), files: [], keyFiles: [], works: []
  };
  fs.mkdirSync(photosDir(u, b.id), { recursive: true });
  chown(u, path.join(u.home, 'workspace', 'Проверка'));
  save(u, b);
  return publicBatch(b);
}
function chown(u, p) { if (u.uid != null) { try { execFileSync('chown', ['-R', `${u.uid}:${u.gid}`, p]); } catch {} } }

// raw image body (the phone compresses photos before sending)
// seq = page number in shooting order (0-based) -> stable order even with parallel uploads
function upload(u, id, name, kind, req, seq) {
  return new Promise((resolve, reject) => {
    const b = load(u, id); if (!b) return reject(new Error('нет такой проверки'));
    if (b.files.length >= 600) return reject(new Error('Слишком много файлов в одной проверке (максимум 600)'));
    const ext = (String(name).match(/\.(jpe?g|png|webp|heic|pdf)$/i) || ['.jpg'])[0].toLowerCase();
    const n = String(b.files.length + b.keyFiles.length + 1).padStart(4, '0');
    const s = Number.isInteger(seq) && seq >= 0 && seq < 10000 && kind !== 'key' ? String(seq).padStart(4, '0') : null;
    if (b.anonymous && kind !== 'key' && s === null) return reject(new Error('нет номера страницы'));
    const out = path.join(photosDir(u, id), kind === 'key' ? 'key-' + n + ext : s !== null ? 'work-s' + s + ext : 'work-' + n + ext);
    const ws = fs.createWriteStream(out);
    let size = 0;
    req.on('data', d => { size += d.length; if (size > 25 * 1024 * 1024) { req.destroy(); ws.destroy(); fs.rmSync(out, { force: true }); reject(new Error('файл больше 25 МБ')); } });
    req.pipe(ws);
    ws.on('finish', () => {
      const cur = load(u, id);
      const arr = kind === 'key' ? cur.keyFiles : cur.files;
      if (!arr.includes(out)) arr.push(out);
      cur.files.sort();
      save(u, cur); chown(u, out);
      resolve({ ok: true, count: cur.files.length });
    });
    ws.on('error', reject);
  });
}

function start(u, id) {
  const b = load(u, id); if (!b) throw new Error('нет такой проверки');
  if (!b.files.length) throw new Error('Сначала загрузите фото работ');
  if (!b.works.length) {
    const seqOf = f => { const m = path.basename(f).match(/^work-s(\d+)\./); return m ? Number(m[1]) : null; };
    if (b.files.every(f => seqOf(f) !== null)) {
      const groups = new Map();                       // work number -> pages (by shooting order)
      for (const f of b.files) { const no = Math.floor(seqOf(f) / b.pagesPerWork) + 1; if (!groups.has(no)) groups.set(no, []); groups.get(no).push(f); }
      for (const [no, files] of [...groups].sort((a, c) => a[0] - c[0])) b.works.push({ id: uid(), no, files: files.sort(), status: 'queued' });
    } else for (let i = 0; i < b.files.length; i += b.pagesPerWork) b.works.push({ id: uid(), no: i / b.pagesPerWork + 1, files: b.files.slice(i, i + b.pagesPerWork), status: 'queued' });
  } else {
    // photos added after a check: put new pages into new works
    const used = new Set(b.works.flatMap(w => w.files));
    const fresh = b.files.filter(f => !used.has(f));
    let no = Math.max(0, ...b.works.map(w => w.no || 0));
    for (let i = 0; i < fresh.length; i += b.pagesPerWork) b.works.push({ id: uid(), no: ++no, files: fresh.slice(i, i + b.pagesPerWork), status: 'queued' });
    b.works.forEach(w => { if (w.status === 'failed') w.status = 'queued'; });
  }
  b.status = 'checking'; save(u, b); push(u, b);
  if (!running.has(id)) { running.set(id, { active: 0 }); for (let i = 0; i < PARALLEL; i++) next(u, id); }
  return publicBatch(b);
}

function promptFor(u, b, w) {
  const inside = p => sandbox.mode() === 'docker' ? sandbox.toIn(u, p) : p;
  return agent.serverNote(u) +
    'You are checking a student\'s handwritten school work (СОР/СОЧ/контрольная) from photos. Be careful and fair, like an experienced teacher.\n' +
    `Subject: ${b.subject || '—'}. Class: ${b.klass || '—'}. Work: ${b.title}.\n` +
    (b.key ? 'ANSWER KEY / CRITERIA (from the teacher):\n' + b.key + '\n' : '') +
    (b.keyFiles.length ? 'The answer key is also in these images: ' + b.keyFiles.map(inside).join(', ') + '\n' : '') +
    (b.maxScore ? `Maximum score: ${b.maxScore}.\n` : '') +
    'GRADING SCALE: ' + b.scale + '\n' +
    (b.roster ? 'Class list (match the name on the sheet to one of these): ' + b.roster.replace(/\n/g, '; ') + '\n' : '') +
    `\nOPEN AND LOOK AT these photo(s) of ONE student's work (page order): ${w.files.map(inside).join(', ')}\n` +
    (b.anonymous
      ? 'PRIVACY: the student\'s name was blacked out on purpose before upload (the black box says «Работа №…»). Do NOT try to read, guess or reconstruct any name; ' +
        'if a name is still visible anywhere, ignore it. Always set student to an empty string. A missing name is NOT a reason for needs_review.\n'
      : '') +
    'Read the handwriting (Russian, Kazakh or English; children\'s handwriting may be messy — read carefully, use context). ' + (b.anonymous ? '' : 'Find the student name on the sheet. ') +
    'Check every task against the key, give points per task and the total, then the grade by the scale. ' +
    'NEVER invent: if a part is unreadable mark it uncertain, set needs_review=true and explain in review_reason. ' +
    'Set needs_review=true also when ' + (b.anonymous ? '' : 'the name is missing/unclear or ') + 'confidence < 0.75. Answer with the JSON object only.';
}

async function next(u, id) {
  const st = running.get(id); if (!st) return;
  const b = load(u, id); if (!b || b.status !== 'checking') { running.delete(id); return; }
  const w = b.works.find(x => x.status === 'queued');
  if (!w) {
    if (st.active === 0) { b.status = 'done'; save(u, b); push(u, b); running.delete(id); emit(u.name, { t: 'notify', title: '📝 Проверка закончена: ' + b.title, body: `${b.works.filter(x => x.status === 'done').length} работ проверено` }); }
    return;
  }
  w.status = 'checking'; save(u, b); push(u, b);
  st.active++;
  try {
    let r = await agent.runOnce(u, promptFor(u, b, w), 240000, RESULT_SCHEMA);
    if (typeof r === 'string') { const m = r.match(/\{[\s\S]*\}/); r = m ? JSON.parse(m[0]) : null; }
    if (!r || typeof r !== 'object') throw new Error('пустой ответ');
    const cur = load(u, id); const cw = cur.works.find(x => x.id === w.id);
    if (cur.anonymous) r.student = '';             // never keep a name the model may have read anyway
    if (cw) { cw.status = 'done'; cw.result = r; cw.error = null; save(u, cur); push(u, cur); }
  } catch (e) {
    const cur = load(u, id); const cw = cur.works.find(x => x.id === w.id);
    if (cw) { cw.status = 'failed'; cw.error = String(e.message || e).slice(0, 300); save(u, cur); push(u, cur); }
  }
  st.active--;
  next(u, id);
}

function stopBatch(u, id) { const b = load(u, id); if (!b) return; b.status = 'paused'; b.works.forEach(w => { if (w.status === 'queued') w.status = 'queued'; }); save(u, b); running.delete(id); push(u, b); }

// the teacher corrects a result (name / total / grade) -> it counts as reviewed
function edit(u, id, workId, patch) {
  const b = load(u, id); if (!b) throw new Error('нет такой проверки');
  const w = b.works.find(x => x.id === workId); if (!w) throw new Error('нет такой работы');
  w.edited = Object.assign(w.edited || {}, { student: b.anonymous ? undefined : patch.student, total: patch.total, grade: patch.grade, by: 'teacher', at: Date.now() });
  for (const k of Object.keys(w.edited)) if (w.edited[k] === undefined || w.edited[k] === '') delete w.edited[k];
  save(u, b); push(u, b);
}
function recheck(u, id, workId) { const b = load(u, id); const w = b && b.works.find(x => x.id === workId); if (!w) return; w.status = 'queued'; w.edited = null; save(u, b); start(u, id); }

function finalRows(b) {
  return b.works.filter(w => w.status === 'done').map((w, i) => {
    const r = w.result || {}, e = w.edited || {}, no = w.no || i + 1;
    return { no, student: b.anonymous ? 'Работа №' + no : (e.student || r.student || '(без имени)'), klass: r.klass || b.klass, total: e.total ?? r.total, max: r.max_total ?? b.maxScore, grade: e.grade || r.grade,
      legibility: r.legibility, confidence: r.confidence, review: !w.edited && !!r.needs_review, reason: r.review_reason || '', feedback: r.feedback || '', files: w.files.map(f => path.basename(f)) };
  }).sort((a, c) => b.anonymous ? a.no - c.no : a.student.localeCompare(c.student, 'ru'));
}

async function exportXlsx(u, id) {
  const b = load(u, id); if (!b) throw new Error('нет такой проверки');
  const ExcelJS = require('exceljs');
  const wb = new ExcelJS.Workbook(); const ws = wb.addWorksheet('Оценки');
  ws.columns = [{ header: '№', key: 'n', width: 5 }, { header: 'Ученик', key: 'student', width: 30 }, { header: 'Класс', key: 'klass', width: 8 }, { header: 'Баллы', key: 'total', width: 8 }, { header: 'Из', key: 'max', width: 6 }, { header: 'Оценка', key: 'grade', width: 8 },
    { header: 'Почерк', key: 'leg', width: 13 }, { header: 'Уверенность', key: 'conf', width: 12 }, { header: 'Проверить учителю', key: 'review', width: 30 }, { header: 'Комментарий ученику', key: 'feedback', width: 50 }, { header: 'Фото', key: 'files', width: 25 }];
  ws.getRow(1).font = { bold: true };
  finalRows(b).forEach((r, i) => ws.addRow({ n: i + 1, student: r.student, klass: r.klass, total: r.total, max: r.max, grade: r.grade, leg: { clear: 'разборчиво', hard: 'трудно', unreadable: 'неразборчиво' }[r.legibility] || '', conf: r.confidence != null ? Math.round(r.confidence * 100) + '%' : '', review: r.review ? '⚠ ' + r.reason : '', feedback: r.feedback, files: r.files.join(', ') }));
  return wb.xlsx.writeBuffer();
}

function photo(u, id, name) {
  const p = path.join(photosDir(u, id), path.basename(String(name)));
  return fs.existsSync(p) ? p : null;
}
function get(u, id) { const b = load(u, id); return b ? publicBatch(b) : null; }
function rows(u, id) { const b = load(u, id); return b ? finalRows(b) : []; }
function remove(u, id) { stopBatch(u, id); fs.rmSync(fileOf(u, id), { force: true }); fs.rmSync(photosDir(u, id), { recursive: true, force: true }); }

module.exports = { setup, create, upload, start, stopBatch, edit, recheck, exportXlsx, photo, get, list, rows, remove, DEFAULT_SCALE };

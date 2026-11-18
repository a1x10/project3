import express from 'express';
import crypto from 'node:crypto';
import { config } from './config.js';
import { db, saveDb } from './store.js';
import { checkPrompt } from './moderation.js';
import { loadTokens } from './higgsfield.js';
import { enqueue, ensureRunning, publicStatus, queuePosition, recover } from './gpu-manager.js';

const app = express();
app.use(express.json({ limit: '50kb' }));
app.use(express.static('public'));

// ---------- аккаунты ----------
const hash = (pw, salt) => crypto.scryptSync(pw, salt, 64).toString('hex');
const sign = v => v + '.' + crypto.createHmac('sha256', config.secret).update(v).digest('base64url');
const unsign = s => { const i = s?.lastIndexOf('.'); if (!s || i < 0) return null; const v = s.slice(0, i); return sign(v) === s ? v : null; };

function currentUser(req) {
  const m = (req.headers.cookie || '').match(/(?:^|;\s*)sid=([^;]+)/);
  const id = m && unsign(decodeURIComponent(m[1]));
  return id ? db.users.find(u => u.id === id) : null;
}
function setSession(res, user) {
  res.setHeader('Set-Cookie', `sid=${encodeURIComponent(sign(user.id))}; HttpOnly; SameSite=Lax; Path=/; Max-Age=${60 * 60 * 24 * 30}`);
}
const auth = (req, res, next) => { req.user = currentUser(req); req.user ? next() : res.status(401).json({ error: 'Войдите в аккаунт' }); };
const publicUser = u => ({ id: u.id, username: u.username });

const attempts = new Map();
function rateLimit(req, res, next) {
  const k = req.ip; const now = Date.now();
  const a = (attempts.get(k) || []).filter(t => now - t < 60_000); a.push(now); attempts.set(k, a);
  a.length > 10 ? res.status(429).json({ error: 'Слишком много попыток, подождите минуту' }) : next();
}

app.get('/api/config', (req, res) => res.json({ inviteRequired: !!config.inviteCode }));

app.post('/api/register', rateLimit, (req, res) => {
  const { username = '', password = '', invite = '', adult } = req.body || {};
  const name = String(username).trim();
  if (!/^[a-zA-Z0-9_а-яА-ЯёЁ.-]{3,24}$/.test(name)) return res.status(400).json({ error: 'Логин: 3–24 символа (буквы, цифры, _ . -)' });
  if (String(password).length < 6) return res.status(400).json({ error: 'Пароль минимум 6 символов' });
  if (!adult) return res.status(400).json({ error: 'Подтвердите, что вам есть 18 лет' });
  if (config.inviteCode && invite !== config.inviteCode) return res.status(403).json({ error: 'Неверный инвайт-код' });
  if (db.users.some(u => u.username.toLowerCase() === name.toLowerCase())) return res.status(409).json({ error: 'Такой логин уже занят' });
  const salt = crypto.randomBytes(16).toString('hex');
  const user = { id: crypto.randomUUID(), username: name, salt, hash: hash(String(password), salt), createdAt: Date.now() };
  db.users.push(user); saveDb();
  setSession(res, user);
  res.json({ user: publicUser(user) });
});

app.post('/api/login', rateLimit, (req, res) => {
  const { username = '', password = '' } = req.body || {};
  const u = db.users.find(x => x.username.toLowerCase() === String(username).trim().toLowerCase());
  if (!u || !crypto.timingSafeEqual(Buffer.from(hash(String(password), u.salt), 'hex'), Buffer.from(u.hash, 'hex')))
    return res.status(401).json({ error: 'Неверный логин или пароль' });
  setSession(res, u);
  res.json({ user: publicUser(u) });
});

app.post('/api/logout', (req, res) => { res.setHeader('Set-Cookie', 'sid=; Path=/; Max-Age=0'); res.json({ ok: true }); });
app.get('/api/me', (req, res) => { const u = currentUser(req); res.json({ user: u ? publicUser(u) : null }); });

// ---------- сервер и генерации ----------
app.get('/api/status', auth, (req, res) => res.json(publicStatus()));

app.post('/api/start', auth, (req, res) => {
  if (!config.mock && !loadTokens()) return res.status(503).json({ error: 'Владелец сайта ещё не подключил Higgsfield' });
  ensureRunning();
  res.json(publicStatus());
});

app.post('/api/jobs', auth, (req, res) => {
  const kind = req.body?.kind === 'image' ? 'image' : 'video';
  const prompt = String(req.body?.prompt || '').trim();
  if (prompt.length < 3) return res.status(400).json({ error: 'Опишите, что нужно сгенерировать' });
  if (prompt.length > 2000) return res.status(400).json({ error: 'Промт слишком длинный (макс. 2000 символов)' });
  const banned = checkPrompt(prompt);
  if (banned) return res.status(400).json({ error: banned });
  if (!config.mock && !loadTokens()) return res.status(503).json({ error: 'Владелец сайта ещё не подключил Higgsfield' });
  const mine = db.jobs.filter(j => j.userId === req.user.id && ['queued', 'running'].includes(j.status));
  if (mine.length >= config.maxQueuedPerUser) return res.status(429).json({ error: `Не больше ${config.maxQueuedPerUser} задач в очереди на человека` });
  const job = enqueue(req.user, kind, prompt);
  res.json({ job: view(job) });
});

const view = j => ({ id: j.id, kind: j.kind, prompt: j.prompt, status: j.status, urls: j.urls, error: j.error,
  createdAt: j.createdAt, finishedAt: j.finishedAt, position: j.status === 'queued' ? queuePosition(j.id) : null });

app.get('/api/jobs', auth, (req, res) => {
  const jobs = db.jobs.filter(j => j.userId === req.user.id).slice(-30).reverse().map(view);
  res.json({ jobs });
});

app.listen(config.port, async () => {
  console.log(`GPU Studio: http://localhost:${config.port}${config.mock ? '  (ТЕСТОВЫЙ РЕЖИМ, GPU не арендуется)' : ''}`);
  if (!config.mock && !loadTokens()) console.log('⚠ Higgsfield не подключён. Выполните: npm run connect');
  await recover();
});

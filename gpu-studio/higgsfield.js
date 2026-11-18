// Подключение к Higgsfield через MCP-коннектор (https://mcp.higgsfield.ai/mcp)
// и обёртки над GPU-инструментами. В режиме HF_MOCK=1 всё имитируется.
import fs from 'node:fs';
import crypto from 'node:crypto';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import { config } from './config.js';

export const TOKEN_FILE = 'data/higgsfield.json';
export const OAUTH = {
  issuer: 'https://clerk.higgsfield.ai',
  register: 'https://clerk.higgsfield.ai/oauth/register',
  device: 'https://clerk.higgsfield.ai/oauth/device_authorization',
  authorize: 'https://clerk.higgsfield.ai/oauth/authorize',
  token: 'https://clerk.higgsfield.ai/oauth/token',
  scope: 'openid email offline_access',
};

const debug = (...a) => process.env.DEBUG_HF && console.log('[hf]', ...a);

export function loadTokens() {
  try { return JSON.parse(fs.readFileSync(TOKEN_FILE, 'utf8')); } catch { return null; }
}
export function saveTokens(t) {
  fs.mkdirSync('data', { recursive: true });
  fs.writeFileSync(TOKEN_FILE, JSON.stringify(t, null, 2), { mode: 0o600 });
}
export function tokenFromResponse(clientId, j, old = {}) {
  return {
    client_id: clientId,
    access_token: j.access_token,
    refresh_token: j.refresh_token || old.refresh_token,
    expires_at: Date.now() + (Number(j.expires_in || 3600) - 60) * 1000,
  };
}

async function accessToken() {
  let t = loadTokens();
  if (!t) throw new Error('Higgsfield не подключён: запустите "npm run connect"');
  if (Date.now() < t.expires_at) return t.access_token;
  if (!t.refresh_token) throw new Error('Токен Higgsfield истёк: запустите "npm run connect" ещё раз');
  const r = await fetch(OAUTH.token, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ grant_type: 'refresh_token', refresh_token: t.refresh_token, client_id: t.client_id }),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok || !j.access_token) throw new Error('Не удалось обновить токен Higgsfield: ' + (j.error_description || j.error || r.status));
  t = tokenFromResponse(t.client_id, j, t);
  saveTokens(t);
  return t.access_token;
}

let client = null;
async function getClient() {
  if (client) return client;
  const token = await accessToken();
  const transport = new StreamableHTTPClientTransport(new URL(config.mcpUrl), {
    requestInit: { headers: { Authorization: `Bearer ${token}` } },
  });
  const c = new Client({ name: 'gpu-studio', version: '1.0.0' });
  await c.connect(transport);
  client = c;
  return c;
}

// Вызов инструмента MCP; результат — разобранный JSON.
export async function callTool(name, args = {}, retry = true) {
  try {
    const c = await getClient();
    const res = await c.callTool({ name, arguments: args });
    const text = (res.content || []).filter(x => x.type === 'text').map(x => x.text).join('\n');
    let data = res.structuredContent;
    if (!data) { try { data = JSON.parse(text); } catch { data = { text }; } }
    debug(name, JSON.stringify(args), '=>', JSON.stringify(data).slice(0, 2000));
    if (res.isError) throw new Error(`${name}: ${text || 'ошибка'}`);
    return data;
  } catch (e) {
    // Токен мог истечь или соединение оборваться — пересоздаём клиента один раз.
    if (retry && /401|unauthor|closed|ECONN|fetch failed/i.test(String(e))) {
      try { await client?.close(); } catch {}
      client = null;
      const t = loadTokens(); if (t) { t.expires_at = 0; saveTokens(t); }
      return callTool(name, args, false);
    }
    throw e;
  }
}

// ---------- разбор ответов (поля ищем гибко, по имени ключа) ----------
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
function walk(o, fn, path = '') {
  if (o && typeof o === 'object') for (const [k, v] of Object.entries(o)) { fn(k, v, path); walk(v, fn, path + '.' + k); }
}
function findFirst(o, keyRe, test = () => true) {
  let out; walk(o, (k, v) => { if (out === undefined && keyRe.test(k) && test(v)) out = v; }); return out;
}
function findAll(o, keyRe, test = () => true) {
  const out = []; walk(o, (k, v) => { if (keyRe.test(k) && test(v)) out.push(v); }); return out;
}
const isUuid = v => typeof v === 'string' && UUID.test(v);

export function parseRental(d) {
  const statusRaw = String(findFirst(d, /^(status|state)$/i, v => typeof v === 'string') || '').toLowerCase();
  const ended = /end|stop|fail|terminat|cancel/.test(statusRaw);
  let modelReady = false;
  walk(d, (k, v, p) => {
    if (/ready/i.test(k) && v === true) modelReady = true;
    if (/model/i.test(p + k) && /^(status|state)$/i.test(k) && /ready|loaded/i.test(String(v))) modelReady = true;
  });
  const model = findFirst(d, /^(model_id|model|loaded_model)$/i, v => typeof v === 'string') || null;
  const spent = findFirst(d, /spent|credits_used/i, v => typeof v === 'number');
  return { status: statusRaw || 'unknown', running: /work|run|ready|active|idle/.test(statusRaw), ended, modelReady, model, spent };
}

export function parseJobs(d) {
  const terminal = /complet|success|succeed|done|fail|error|nsfw|ip_detected|cancel/;
  const items = Array.isArray(d?.jobs) ? d.jobs : [d];
  return items.map(j => {
    const status = String(findFirst(j, /^(status|state)$/i, v => typeof v === 'string') || '').toLowerCase();
    const urls = [...new Set(findAll(j, /url/i, v => typeof v === 'string' && /^https?:\/\//.test(v)))];
    const err = findFirst(j, /^(error|reason|message)$/i, v => typeof v === 'string');
    return {
      job_id: findFirst(j, /job_id|^id$/i, isUuid),
      status, done: terminal.test(status), ok: /complet|success|succeed|done/.test(status),
      urls, error: err || (status && !/complet|success|succeed|done/.test(status) ? status : null),
    };
  });
}

// ---------- GPU-операции ----------
const mock = {
  sessions: {},
  async rent() { const id = crypto.randomUUID(); this.sessions[id] = { t: Date.now(), model: null, mt: 0 }; return id; },
  async rental(id) {
    const s = this.sessions[id]; if (!s) return { status: 'ended', ended: true };
    const running = Date.now() - s.t > 3000;
    return { status: running ? 'working' : 'starting', running, ended: false, model: s.model, modelReady: !!s.model && Date.now() - s.mt > 4000 };
  },
  async prepare(id, model) { const s = this.sessions[id]; s.model = model; s.mt = Date.now(); },
  async generate(id, prompt, kind) { const j = crypto.randomUUID(); this.jobs[j] = { t: Date.now(), kind, prompt }; return [j]; },
  jobs: {},
  async wait(ids) {
    return ids.map(id => {
      const j = this.jobs[id]; const done = Date.now() - j.t > (j.kind === 'video' ? 8000 : 4000);
      const url = j.kind === 'video'
        ? 'https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4'
        : `https://picsum.photos/seed/${encodeURIComponent(j.prompt)}/768/768`;
      return { job_id: id, status: done ? 'completed' : 'in_progress', done, ok: done, urls: done ? [url] : [], error: null };
    });
  },
  async stop(id) { delete this.sessions[id]; },
};

export const gpu = {
  async rent() {
    if (config.mock) return mock.rent();
    const d = await callTool('gpu_rent', {
      gpu_type: config.gpuType, gpu_count: 1,
      max_credits_per_hour: config.maxCreditsPerHour,
      auto_pause_minutes: 5,          // страховка на стороне Higgsfield (минимум 5 мин)
      idempotency_key: crypto.randomUUID(),
    });
    const id = findFirst(d, /session_id|^id$/i, isUuid);
    if (!id) throw new Error('gpu_rent не вернул session_id: ' + JSON.stringify(d).slice(0, 300));
    return id;
  },
  async rental(id) { return config.mock ? mock.rental(id) : parseRental(await callTool('gpu_rental', { session_id: id })); },
  async prepare(id, model) { return config.mock ? mock.prepare(id, model) : callTool('gpu_rental_prepare', { session_id: id, model_id: model }); },
  async generate(id, prompt, kind) {
    if (config.mock) return mock.generate(id, prompt, kind);
    const d = await callTool('gpu_rental_generate', { session_id: id, prompt, idempotency_key: crypto.randomUUID() });
    const ids = [...new Set(findAll(d, /job_id|^id$/i, isUuid))].filter(x => x !== id);
    if (!ids.length) throw new Error('gpu_rental_generate не вернул job_id: ' + JSON.stringify(d).slice(0, 300));
    return ids;
  },
  async wait(jobIds) {
    if (config.mock) { await new Promise(r => setTimeout(r, 1000)); return mock.wait(jobIds); }
    const d = await callTool('jobs_wait', { jobs: jobIds.map((job_id, index) => ({ index, job_id })), timeout_seconds: 15 });
    return parseJobs(d);
  },
  async stop(id) { return config.mock ? mock.stop(id) : callTool('gpu_rental_stop', { session_id: id }); },
};

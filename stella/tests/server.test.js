import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import http from 'node:http';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { createApp } = require('../server/server.js');
const { DB, DEFAULT_PLANS } = require('../server/db.js');

/** Поддельные OpenRouter и ElevenLabs. */
function upstream() {
  const calls = [];
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url, init });
    if (url.endsWith('/chat/completions')) {
      const body = JSON.parse(init.body);
      const sse = `data: ${JSON.stringify({ choices: [{ delta: { content: 'Привет от ' + body.model } }] })}\n\ndata: ${JSON.stringify({ choices: [], usage: { total_tokens: 42 } })}\n\ndata: [DONE]\n\n`;
      return new Response(sse, { status: 200, headers: { 'content-type': 'text/event-stream' } });
    }
    if (url.endsWith('/models')) return new Response(JSON.stringify({ data: [{ id: 'openai/gpt-4o-mini' }, { id: 'anthropic/claude-x' }] }), { status: 200 });
    if (url.includes('/text-to-speech/')) return new Response(new Uint8Array([7, 7, 7]), { status: 200, headers: { 'content-type': 'audio/mpeg' } });
    if (url.endsWith('/speech-to-text')) return new Response(JSON.stringify({ text: 'Стелла привет' }), { status: 200 });
    if (url.endsWith('/voices')) return new Response(JSON.stringify({ voices: [{ voice_id: 'v1', name: 'Rachel' }] }), { status: 200 });
    return new Response('nope', { status: 404 });
  };
  return { calls, fetchImpl };
}

let server, base, app, up, dir;
async function start(opts = {}) {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'stella-cloud-'));
  up = upstream();
  app = createApp({ dataDir: dir, adminPassword: 'admin-secret', openrouterKey: 'sk-or-SERVER', elevenKey: 'sk_SERVER', fetch: up.fetchImpl, ipRatePerMin: 1000, ...opts });
  server = http.createServer(app.handler);
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  base = `http://127.0.0.1:${server.address().port}`;
}
afterEach(async () => { app?.db.flush(); await new Promise((r) => server.close(r)); });

const req = async (method, p, { body, token, raw, headers = {} } = {}) => {
  const res = await fetch(base + p, { method, headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}), ...headers }, body: raw ?? (body ? JSON.stringify(body) : undefined) });
  const ct = res.headers.get('content-type') || '';
  const data = ct.includes('json') ? await res.json() : ct.includes('audio') ? Buffer.from(await res.arrayBuffer()) : await res.text();
  return { status: res.status, data, res };
};
const register = (u = 'alex', pw = 'secret1') => req('POST', '/api/auth/register', { body: { username: u, password: pw } });
const admin = async () => (await req('POST', '/api/admin/login', { body: { password: 'admin-secret' } })).data.token;

describe('Stella Cloud: аккаунты', () => {
  beforeEach(() => start());
  it('health без авторизации', async () => {
    const r = await req('GET', '/api/health');
    expect(r.data).toMatchObject({ ok: true, name: 'Stella Cloud', ai: true, voice: true });
  });
  it('регистрация выдаёт токен и бесплатный тариф', async () => {
    const r = await register();
    expect(r.status).toBe(200);
    expect(r.data.token.length).toBeGreaterThan(30);
    expect(r.data.user).toMatchObject({ username: 'alex', plan: 'free', planName: 'Stella Free' });
  });
  it('ответ не раскрывает хеш пароля и ключи сервера', async () => {
    const r = await register();
    const s = JSON.stringify(r.data);
    expect(s).not.toMatch(/salt|hash|sk-or-SERVER|sk_SERVER/);
  });
  it('валидация регистрации', async () => {
    expect((await register('a', 'secret1')).status).toBe(400);
    expect((await register('bob', '123')).status).toBe(400);
    await register('bob', 'secret1');
    expect((await register('BOB', 'secret1')).status).toBe(409);
  });
  it('вход и /api/me', async () => {
    await register();
    const r = await req('POST', '/api/auth/login', { body: { username: 'ALEX', password: 'secret1' } });
    expect(r.status).toBe(200);
    const me = await req('GET', '/api/me', { token: r.data.token });
    expect(me.data).toMatchObject({ username: 'alex', usage: { messagesToday: 0 }, limits: { messagesPerDay: DEFAULT_PLANS.free.messagesPerDay } });
  });
  it('неверный пароль', async () => { await register(); expect((await req('POST', '/api/auth/login', { body: { username: 'alex', password: 'nope' } })).status).toBe(401); });
  it('без токена — 401', async () => { expect((await req('GET', '/api/me')).status).toBe(401); expect((await req('GET', '/api/me', { token: 'fake' })).status).toBe(401); });
  it('выход аннулирует токен', async () => {
    const { token } = (await register()).data;
    await req('POST', '/api/auth/logout', { token });
    expect((await req('GET', '/api/me', { token })).status).toBe(401);
  });
  it('закрытая регистрация', async () => {
    await new Promise((r) => server.close(r));
    await start({ openRegistration: false });
    expect((await register()).status).toBe(403);
  });
  it('тарифы публичны', async () => {
    const r = await req('GET', '/api/plans');
    expect(r.data.map((p) => p.id)).toEqual(['free', 'plus', 'pro']);
  });
});

describe('Stella Cloud: прокси и лимиты', () => {
  beforeEach(() => start());
  it('чат проксируется в OpenRouter с ключом сервера', async () => {
    const { token } = (await register()).data;
    const r = await req('POST', '/api/chat/completions', { token, body: { model: 'openai/gpt-4o-mini', messages: [{ role: 'user', content: 'hi' }], stream: true } });
    expect(r.status).toBe(200);
    expect(r.data).toContain('Привет от openai/gpt-4o-mini');
    const call = up.calls.find((c) => c.url.endsWith('/chat/completions'));
    expect(call.init.headers.Authorization).toBe('Bearer sk-or-SERVER');
    expect(JSON.parse(call.init.body).user).toMatch(/^u_/);
    const me = (await req('GET', '/api/me', { token })).data;
    expect(me.usage).toMatchObject({ messagesToday: 1, totalTokens: 42 });
  });
  it('модель по умолчанию подставляется', async () => {
    const { token } = (await register()).data;
    await req('POST', '/api/chat/completions', { token, body: { messages: [] } });
    expect(JSON.parse(up.calls.at(-1).init.body).model).toBe('openai/gpt-4o-mini');
  });
  it('дневной лимит сообщений', async () => {
    const { token, user } = (await register()).data;
    const t = await admin();
    await req('PATCH', `/api/admin/users/${user.id}`, { token: t, body: { customLimits: { messagesPerDay: 2 } } });
    expect((await req('POST', '/api/chat/completions', { token, body: { messages: [] } })).status).toBe(200);
    expect((await req('POST', '/api/chat/completions', { token, body: { messages: [] } })).status).toBe(200);
    const r = await req('POST', '/api/chat/completions', { token, body: { messages: [] } });
    expect(r.status).toBe(429);
    expect(r.data.error.code).toBe('quota');
  });
  it('ограничение моделей по тарифу', async () => {
    const t = await admin();
    await req('PUT', '/api/admin/plans/free', { token: t, body: { models: 'openai/*' } });
    const { token } = (await register()).data;
    expect((await req('POST', '/api/chat/completions', { token, body: { model: 'anthropic/claude-x', messages: [] } })).status).toBe(403);
    expect((await req('POST', '/api/chat/completions', { token, body: { model: 'openai/gpt-4o-mini', messages: [] } })).status).toBe(200);
    const models = (await req('GET', '/api/models', { token })).data.data.map((m) => m.id);
    expect(models).toEqual(['openai/gpt-4o-mini']);
  });
  it('тариф без инструментов вырезает tools', async () => {
    const t = await admin();
    await req('PUT', '/api/admin/plans/free', { token: t, body: { tools: false } });
    const { token } = (await register()).data;
    await req('POST', '/api/chat/completions', { token, body: { messages: [], tools: [{ type: 'function' }] } });
    expect(JSON.parse(up.calls.at(-1).init.body).tools).toBeUndefined();
  });
  it('озвучка и учёт символов', async () => {
    const { token } = (await register()).data;
    const r = await req('POST', '/api/tts', { token, body: { text: 'Привет!', voiceId: 'v1' } });
    expect(r.status).toBe(200);
    expect([...r.data]).toEqual([7, 7, 7]);
    expect(up.calls.at(-1).init.headers['xi-api-key']).toBe('sk_SERVER');
    expect((await req('GET', '/api/me', { token })).data.usage.ttsCharsMonth).toBe(7);
  });
  it('лимит озвучки', async () => {
    const { token, user } = (await register()).data;
    const t = await admin();
    await req('PATCH', `/api/admin/users/${user.id}`, { token: t, body: { customLimits: { ttsCharsPerMonth: 5 } } });
    expect((await req('POST', '/api/tts', { token, body: { text: 'длинный текст' } })).status).toBe(429);
  });
  it('распознавание речи', async () => {
    const { token } = (await register()).data;
    const r = await req('POST', '/api/stt', { token, raw: 'binary', headers: { 'Content-Type': 'multipart/form-data; boundary=x' } });
    expect(r.data.text).toBe('Стелла привет');
    expect((await req('GET', '/api/me', { token })).data.usage.sttToday).toBe(1);
  });
  it('голоса', async () => {
    const { token } = (await register()).data;
    expect((await req('GET', '/api/voices', { token })).data.voices[0].name).toBe('Rachel');
  });
  it('без ключа на сервере — 503', async () => {
    await new Promise((r) => server.close(r));
    await start({ openrouterKey: '' });
    const { token } = (await register()).data;
    expect((await req('POST', '/api/chat/completions', { token, body: { messages: [] } })).status).toBe(503);
  });
});

describe('Stella Cloud: подписки и админка', () => {
  beforeEach(() => start());
  it('админ-вход', async () => {
    expect((await req('POST', '/api/admin/login', { body: { password: 'wrong' } })).status).toBe(401);
    expect(await admin()).toBeTruthy();
    expect((await req('GET', '/api/admin/users')).status).toBe(401);
  });
  it('админ меняет тариф и срок', async () => {
    const { token, user } = (await register()).data;
    const t = await admin();
    const u = (await req('PATCH', `/api/admin/users/${user.id}`, { token: t, body: { plan: 'plus', days: 30 } })).data;
    expect(u.planName).toBe('Stella Plus');
    expect(u.planExpiresAt).toBeGreaterThan(Date.now() + 29 * 86400000);
    expect((await req('GET', '/api/me', { token })).data.limits.messagesPerDay).toBe(DEFAULT_PLANS.plus.messagesPerDay);
  });
  it('истёкший тариф откатывается на бесплатный', async () => {
    const { token, user } = (await register()).data;
    app.db.data.users.find((x) => x.id === user.id).plan = 'pro';
    app.db.data.users.find((x) => x.id === user.id).planExpiresAt = Date.now() - 1000;
    expect((await req('GET', '/api/me', { token })).data.plan).toBe('free');
  });
  it('коды подписки: выпуск и активация', async () => {
    const t = await admin();
    const codes = (await req('POST', '/api/admin/codes', { token: t, body: { plan: 'plus', days: 14, count: 3 } })).data;
    expect(codes).toHaveLength(3);
    expect(codes[0].code).toMatch(/^PLUS-[0-9A-F]{6}-[0-9A-F]{6}$/);
    const { token } = (await register()).data;
    const u = (await req('POST', '/api/redeem', { token, body: { code: codes[0].code.toLowerCase() } })).data;
    expect(u.plan).toBe('plus');
    const { token: t2 } = (await register('bob')).data;
    expect((await req('POST', '/api/redeem', { token: t2, body: { code: codes[0].code } })).status).toBe(409);
    expect((await req('POST', '/api/redeem', { token: t2, body: { code: 'NOPE' } })).status).toBe(404);
  });
  it('повторный код того же тарифа продлевает срок', async () => {
    const t = await admin();
    const [a, b] = (await req('POST', '/api/admin/codes', { token: t, body: { plan: 'plus', days: 10, count: 2 } })).data;
    const { token } = (await register()).data;
    await req('POST', '/api/redeem', { token, body: { code: a.code } });
    const u = (await req('POST', '/api/redeem', { token, body: { code: b.code } })).data;
    expect(u.planExpiresAt).toBeGreaterThan(Date.now() + 19 * 86400000);
  });
  it('бан пользователя', async () => {
    const { token, user } = (await register()).data;
    const t = await admin();
    await req('PATCH', `/api/admin/users/${user.id}`, { token: t, body: { banned: true } });
    expect((await req('GET', '/api/me', { token })).status).toBe(403);
  });
  it('IP-замок аккаунта', async () => {
    const { token, user } = (await register()).data;
    const t = await admin();
    await req('PATCH', `/api/admin/users/${user.id}`, { token: t, body: { ipLock: '10.0.0.1, 10.0.0.2' } });
    const r = await req('GET', '/api/me', { token });
    expect(r.status).toBe(403);
    expect(r.data.error.message).toContain('127.0.0.1');
    await req('PATCH', `/api/admin/users/${user.id}`, { token: t, body: { ipLock: '127.0.0.1' } });
    expect((await req('GET', '/api/me', { token })).status).toBe(200);
  });
  it('блокировка IP целиком', async () => {
    const t = await admin();
    await req('POST', '/api/admin/ips/ban', { token: t, body: { ip: '127.0.0.1' } });
    expect((await req('GET', '/api/plans')).status).toBe(403);
    app.db.data.bannedIps = [];
  });
  it('лимит запросов с одного IP', async () => {
    await new Promise((r) => server.close(r));
    await start({ ipRatePerMin: 3 });
    const codes = [];
    for (let i = 0; i < 5; i++) codes.push((await req('GET', '/api/plans')).status);
    expect(codes.slice(0, 3)).toEqual([200, 200, 200]);
    expect(codes).toContain(429);
  });
  it('пользователь запоминает IP', async () => {
    const { token } = (await register()).data;
    await req('GET', '/api/me', { token });
    const t = await admin();
    const users = (await req('GET', '/api/admin/users', { token: t })).data;
    expect(users[0].lastIp).toBe('127.0.0.1');
    expect(users[0].ips).toContain('127.0.0.1');
  });
  it('создание и удаление пользователя админом, смена пароля', async () => {
    const t = await admin();
    const u = (await req('POST', '/api/admin/users', { token: t, body: { username: 'vip', password: 'secret1', plan: 'pro' } })).data;
    expect(u.plan).toBe('pro');
    await req('PATCH', `/api/admin/users/${u.id}`, { token: t, body: { password: 'newpass1' } });
    expect((await req('POST', '/api/auth/login', { body: { username: 'vip', password: 'newpass1' } })).status).toBe(200);
    await req('DELETE', `/api/admin/users/${u.id}`, { token: t });
    expect((await req('GET', '/api/admin/users', { token: t })).data).toHaveLength(0);
  });
  it('редактирование тарифов', async () => {
    const t = await admin();
    const p = (await req('PUT', '/api/admin/plans/vip', { token: t, body: { name: 'Stella VIP', messagesPerDay: 9999, price: '1999 ₽' } })).data;
    expect(p).toMatchObject({ id: 'vip', name: 'Stella VIP', messagesPerDay: 9999 });
    expect((await req('DELETE', '/api/admin/plans/free', { token: t })).status).toBe(400);
    expect((await req('DELETE', '/api/admin/plans/vip', { token: t })).status).toBe(200);
  });
  it('статистика и журнал', async () => {
    await register();
    const t = await admin();
    const st = (await req('GET', '/api/admin/stats', { token: t })).data;
    expect(st).toMatchObject({ users: 1, ai: true, voice: true });
    const log = (await req('GET', '/api/admin/log', { token: t })).data;
    expect(log.some((e) => e.type === 'register')).toBe(true);
  });
  it('админ-панель отдаётся по /admin', async () => {
    const r = await req('GET', '/admin');
    expect(r.data).toContain('Stella Cloud');
  });
  it('данные сохраняются на диск', async () => {
    await register();
    app.db.flush();
    expect(new DB(dir).data.users).toHaveLength(1);
  });
  it('неизвестный маршрут и битый JSON', async () => {
    expect((await req('GET', '/api/nope')).status).toBe(404);
    expect((await req('POST', '/api/auth/login', { raw: '{oops', headers: { 'Content-Type': 'application/json' } })).status).toBe(400);
  });
});

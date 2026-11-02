import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { injectPrompt } from '../src/gateway.js';
import { api, fakeTelegram, fakeUpstream, startCloud } from './helpers.js';

const OWNER = 1001;
const ALICE = 2002;
const BOB = 3003;

describe('Stella Cloud', () => {
  let tg: Awaited<ReturnType<typeof fakeTelegram>>;
  let up: Awaited<ReturnType<typeof fakeUpstream>>;
  let cloud: Awaited<ReturnType<typeof startCloud>>;
  let base = '';

  /** Full device-flow login through the fake Telegram bot. */
  async function login(tgId: number, client: 'web' | 'studio' | 'stella', viaCode = false) {
    const s = await api(base, '/api/auth/start', { body: { client, device: 'test-pc' } });
    expect(s.status).toBe(200);
    expect(s.json.link).toBe(`https://t.me/stella_test_bot?start=login_${s.json.id}`);
    expect((await api(base, `/api/auth/poll?id=${s.json.id}`)).json.status).toBe('pending');
    const before = tg.sent.length;
    tg.say(tgId, viaCode ? `/login ${s.json.code.toLowerCase()}` : `/start login_${s.json.id}`);
    const offer = await tg.waitFor((m, i = tg.sent.indexOf(m)) => i >= before && m.params.chat_id === tgId && /Подтвердить/.test(JSON.stringify(m.params.reply_markup ?? '')));
    expect(offer.params.text).toContain(s.json.code);
    tg.press(tgId, `approve:${s.json.id}`);
    await tg.waitFor((m) => m.method === 'editMessageText' && m.params.chat_id === tgId && /Вход подтверждён/.test(m.params.text));
    const p = await api(base, `/api/auth/poll?id=${s.json.id}`);
    expect(p.json.status).toBe('approved');
    // consumed exactly once
    expect((await api(base, `/api/auth/poll?id=${s.json.id}`)).json.status).toBe('expired');
    return p.json as { token?: string; apiKey?: string; user: any };
  }

  beforeAll(async () => {
    tg = await fakeTelegram();
    up = await fakeUpstream();
    cloud = await startCloud({
      TELEGRAM_BOT_TOKEN: 'TEST:TOKEN',
      TELEGRAM_API_URL: tg.url,
      ADMIN_TELEGRAM_IDS: String(OWNER),
      ROUTER_URL: up.url,
      ROUTER_ADMIN_EMAIL: 'admin@local',
      ROUTER_ADMIN_PASSWORD: 'pw',
      SYSTEM_PROMPT: 'Ты — Stella. Отвечай по-русски.',
      PUBLIC_URL: 'https://ai.example.com',
    });
    base = cloud.url;
    expect(await cloud.app.botReady).toBe(true);
  });
  afterAll(async () => {
    await cloud?.close();
    await tg?.close();
    await up?.close();
  });

  it('registers users via /start; ADMIN_TELEGRAM_IDS become admins', async () => {
    tg.say(OWNER, '/start', 'Owner');
    await tg.waitFor((m) => m.params.chat_id === OWNER && /администратор/.test(m.params.text ?? ''));
    tg.say(ALICE, '/start', 'Alice');
    const w = await tg.waitFor((m) => m.params.chat_id === ALICE && /Добро пожаловать/.test(m.params.text ?? ''));
    expect(w.params.text).not.toContain('администратор');
    const owner = cloud.app.store.userByTg(OWNER)!;
    expect(owner.role).toBe('admin');
    expect(owner.plan).toBe('unlimited');
    expect(cloud.app.store.userByTg(ALICE)!.plan).toBe('free');
  });

  it('logs the website in with a session and the apps with an API key', async () => {
    const web = await login(ALICE, 'web');
    expect(web.token).toMatch(/^sess_/);
    expect(web.apiKey).toBeUndefined();
    const me = await api(base, '/api/me', { token: web.token });
    expect(me.json.user.name).toBe('Alice');
    expect(me.json.user.planInfo.dailyRequests).toBe(50);
    expect(me.json.apiBase).toBe('https://ai.example.com/v1');

    const app = await login(ALICE, 'stella', true);
    expect(app.apiKey).toMatch(/^sk-stella-/);
    const keys = await api(base, '/api/me/keys', { token: web.token });
    expect(keys.json.keys[0].name).toContain('STELLA CODER');

    expect((await api(base, '/api/me', { token: 'sess_bogus' })).status).toBe(401);
    await api(base, '/api/auth/logout', { method: 'POST', token: web.token });
    expect((await api(base, '/api/me', { token: web.token })).status).toBe(401);
  });

  it('denied login yields no credential', async () => {
    const s = await api(base, '/api/auth/start', { body: { client: 'studio' } });
    tg.say(ALICE, `/start login_${s.json.id}`);
    await tg.waitFor((m) => m.params.chat_id === ALICE && (m.params.text ?? '').includes(s.json.code));
    tg.press(ALICE, `deny:${s.json.id}`);
    await tg.waitFor((m) => m.method === 'editMessageText' && /отклонён/.test(m.params.text));
    expect((await api(base, `/api/auth/poll?id=${s.json.id}`)).json).toEqual({ status: 'denied' });
  });

  it('gateway injects the owner prompt, auto-fetches the router key and records usage', async () => {
    const { apiKey } = await login(ALICE, 'studio');
    const models = await api(base, '/v1/models', { token: apiKey });
    expect(models.json.data.map((m: any) => m.id)).toContain('auto:smart');
    expect(up.enabled).toEqual(['kilo', 'ovh']); // keyless providers switched on once

    const r = await api(base, '/v1/chat/completions', { token: apiKey, body: { messages: [{ role: 'user', content: 'hi' }] }, headers: { 'x-stella-client': 'studio' } });
    expect(r.status).toBe(200);
    expect(r.json.choices[0].message.content).toBe('ok');
    expect(r.headers.get('x-routed-via')).toBe('kilo/qwen');
    const sent = up.requests.at(-1);
    expect(sent.model).toBe('auto:smart');
    expect(sent.messages[0]).toEqual({ role: 'system', content: 'Ты — Stella. Отвечай по-русски.' });

    // client system prompt is merged after the owner's
    await api(base, '/v1/chat/completions', { token: apiKey, body: { model: 'auto:fast', messages: [{ role: 'system', content: 'Пиши код.' }, { role: 'user', content: 'x' }] } });
    expect(up.requests.at(-1).messages[0].content).toBe('Ты — Stella. Отвечай по-русски.\n\nПиши код.');
    expect(up.requests.at(-1).model).toBe('auto:fast');

    // streaming passes SSE through and captures usage
    const s = await api(base, '/v1/chat/completions', { token: apiKey, body: { stream: true, messages: [{ role: 'user', content: 'x' }] } });
    expect(s.text).toContain('Привет');
    expect(s.text).toContain('[DONE]');
    expect(up.requests.at(-1).stream_options).toEqual({ include_usage: true });

    const u = cloud.app.store.usageToday(cloud.app.store.userByTg(ALICE)!.id);
    expect(u.requests).toBe(3);
    expect(u.tokens).toBe(25 + 25 + 18);
  });

  it('refreshes the router key when it rotates', async () => {
    const { apiKey } = await login(ALICE, 'other' as any);
    up.rotate('rotated-key');
    const r = await api(base, '/v1/chat/completions', { token: apiKey, body: { messages: [{ role: 'user', content: 'x' }] } });
    expect(r.status).toBe(200);
    expect(up.enabled).toEqual(['kilo', 'ovh']);
  });

  it('rejects unauthenticated requests and enforces daily limits', async () => {
    expect((await api(base, '/v1/chat/completions', { body: { messages: [] } })).status).toBe(401);
    tg.say(BOB, '/start', 'Bob');
    await tg.waitFor((m) => m.params.chat_id === BOB);
    const { apiKey } = await login(BOB, 'stella');
    const { token: adminToken } = await login(OWNER, 'web');
    const settings = await api(base, '/api/admin/settings', { token: adminToken });
    const plans = { ...settings.json.plans, tiny: { name: 'Tiny', dailyRequests: 1, dailyTokens: null } };
    expect((await api(base, '/api/admin/settings', { method: 'PUT', token: adminToken, body: { plans } })).status).toBe(200);
    const bob = cloud.app.store.userByTg(BOB)!;
    expect((await api(base, `/api/admin/users/${bob.id}`, { method: 'PATCH', token: adminToken, body: { plan: 'tiny' } })).json.user.plan).toBe('tiny');
    expect((await api(base, '/v1/chat/completions', { token: apiKey, body: { messages: [{ role: 'user', content: '1' }] } })).status).toBe(200);
    const limited = await api(base, '/v1/chat/completions', { token: apiKey, body: { messages: [{ role: 'user', content: '2' }] } });
    expect(limited.status).toBe(429);
    expect(limited.json.error.message).toContain('лимит');
  });

  it('admin API: settings, model allowlist, users, ban and delete', async () => {
    const { token } = await login(OWNER, 'web');
    const { token: aliceToken, apiKey: _ } = await login(ALICE, 'web');
    expect((await api(base, '/api/admin/users', { token: aliceToken })).status).toBe(403);

    const put = await api(base, '/api/admin/settings', { method: 'PUT', token, body: { systemPrompt: 'NEW PROMPT', allowedModels: ['auto:smart'] } });
    expect(put.json.systemPrompt).toBe('NEW PROMPT');
    const { apiKey } = await login(ALICE, 'stella');
    expect((await api(base, '/v1/chat/completions', { token: apiKey, body: { model: 'auto:fast', messages: [{ role: 'user', content: 'x' }] } })).status).toBe(403);
    await api(base, '/v1/chat/completions', { token: apiKey, body: { messages: [{ role: 'user', content: 'x' }] } });
    expect(up.requests.at(-1).messages[0].content).toBe('NEW PROMPT');
    await api(base, '/api/admin/settings', { method: 'PUT', token, body: { allowedModels: [], promptMode: 'off' } });
    await api(base, '/v1/chat/completions', { token: apiKey, body: { messages: [{ role: 'user', content: 'x' }] } });
    expect(up.requests.at(-1).messages[0].role).toBe('user');

    const list = await api(base, '/api/admin/users?q=alice', { token });
    expect(list.json.total).toBe(1);
    const alice = list.json.users[0];
    expect(alice.requestsToday).toBeGreaterThan(0);

    expect((await api(base, `/api/admin/users/${alice.id}`, { method: 'PATCH', token, body: { status: 'banned' } })).status).toBe(200);
    expect((await api(base, '/v1/chat/completions', { token: apiKey, body: { messages: [] } })).status).toBe(401); // keys revoked
    expect((await api(base, '/api/me', { token: aliceToken })).status).toBe(401); // sessions dropped
    tg.say(ALICE, '/me');
    await tg.waitFor((m) => m.params.chat_id === ALICE && /заблокирован/.test(m.params.text ?? ''));

    const owner = cloud.app.store.userByTg(OWNER)!;
    expect((await api(base, `/api/admin/users/${owner.id}`, { method: 'DELETE', token })).status).toBe(400);
    expect((await api(base, `/api/admin/users/${alice.id}`, { method: 'DELETE', token })).status).toBe(200);
    expect(cloud.app.store.userById(alice.id)).toBeUndefined();

    const up2 = await api(base, '/api/admin/upstream', { token });
    expect(up2.json.ok).toBe(true);
    expect(up2.json.modelIds).toContain('auto');
    expect((await api(base, '/api/admin/stats', { token })).json.stats.users).toBe(2);
  });

  it('bot admin commands: /user card buttons, /plan, /setprompt keeps newlines, /deluser', async () => {
    const n = tg.sent.length;
    tg.say(ALICE, '/start', 'Alice'); // re-register after deletion
    await tg.waitFor((m) => tg.sent.indexOf(m) >= n && m.params.chat_id === ALICE && /Добро пожаловать/.test(m.params.text ?? ''));
    const alice = cloud.app.store.userByTg(ALICE)!;
    tg.say(OWNER, `/user ${alice.id}`);
    const card = await tg.waitFor((m) => m.params.chat_id === OWNER && (m.params.text ?? '').includes(`ID ${alice.id} ·`));
    expect(JSON.stringify(card.params.reply_markup)).toContain(`ban:${alice.id}`);
    tg.press(OWNER, `ban:${alice.id}`);
    await tg.waitFor((m) => m.method === 'editMessageText' && /заблокирован/.test(m.params.text));
    expect(cloud.app.store.userById(alice.id)!.status).toBe('banned');
    tg.press(OWNER, `unban:${alice.id}`);
    await tg.waitFor(() => cloud.app.store.userById(alice.id)!.status === 'active');

    tg.say(OWNER, `/plan ${alice.id} pro`);
    await tg.waitFor(() => cloud.app.store.userById(alice.id)!.plan === 'pro');
    tg.say(OWNER, '/setprompt Строка 1\nСтрока 2');
    await tg.waitFor((m) => m.params.chat_id === OWNER && /промпт обновлён/.test(m.params.text ?? ''));
    expect(cloud.app.store.getSetting('system_prompt', '')).toBe('Строка 1\nСтрока 2');

    tg.say(ALICE, '/stats'); // not an admin
    await tg.waitFor((m) => m.params.chat_id === ALICE && /Не понял/.test(m.params.text ?? ''));

    tg.say(OWNER, `/deluser ${alice.id}`);
    await tg.waitFor((m) => m.params.chat_id === OWNER && JSON.stringify(m.params.reply_markup ?? '').includes(`deluser:${alice.id}`));
    tg.press(OWNER, `deluser:${alice.id}`);
    await tg.waitFor(() => !cloud.app.store.userById(alice.id));
  });

  it('users manage their own keys and can delete their account', async () => {
    tg.say(BOB, '/key laptop');
    const m = await tg.waitFor((x) => x.params.chat_id === BOB && /sk-stella-/.test(x.params.text ?? ''));
    const key = /sk-stella-[\w-]+/.exec(m.params.text)![0];
    const { token } = await login(BOB, 'web');
    const keys = (await api(base, '/api/me/keys', { token })).json.keys;
    const laptop = keys.find((k: any) => k.name === 'laptop');
    expect((await api(base, `/api/me/keys/${laptop.id}`, { method: 'DELETE', token })).status).toBe(200);
    expect((await api(base, '/v1/models', { token: key })).status).toBe(401);
    expect((await api(base, '/api/me', { method: 'DELETE', token })).status).toBe(200);
    expect(cloud.app.store.userByTg(BOB)).toBeUndefined();
  });

  it('public config and CORS preflight', async () => {
    const c = await api(base, '/api/config');
    expect(c.json.botUsername).toBe('stella_test_bot');
    expect(c.json.apiBase).toBe('https://ai.example.com/v1');
    const pre = await fetch(base + '/v1/chat/completions', { method: 'OPTIONS' });
    expect(pre.status).toBe(204);
    expect(pre.headers.get('access-control-allow-origin')).toBe('*');
  });
});

describe('injectPrompt', () => {
  const s = { systemPrompt: 'P', promptMode: 'prepend' as const, defaultModel: 'auto', allowedModels: [] };
  it('handles array content and off mode', () => {
    expect(injectPrompt([{ role: 'system', content: [{ type: 'text', text: 'A' }] }], s)[0].content).toBe('P\n\nA');
    expect(injectPrompt([{ role: 'user', content: 'u' }], { ...s, promptMode: 'off' })).toEqual([{ role: 'user', content: 'u' }]);
  });
});

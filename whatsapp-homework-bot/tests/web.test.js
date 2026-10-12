import assert from 'node:assert/strict';
import net from 'node:net';
import { after, before, describe, it } from 'node:test';
import { BackupAi, KeyRing } from '../src/ai/keys.js';
import { LogBuffer } from '../src/logger.js';
import { SecretStore } from '../src/secrets.js';
import { hashPassword, verifyPassword } from '../src/web/auth.js';
import { PanelAuth } from '../src/web/auth.js';
import { tokenize } from '../src/web/console.js';
import { startWebServer } from '../src/web/server.js';
import { setup, STUDENT } from './setup.js';

const freePort = () => new Promise((resolve) => {
  const srv = net.createServer();
  srv.listen(0, '127.0.0.1', () => {
    const { port } = srv.address();
    srv.close(() => resolve(port));
  });
});

describe('веб-панель', () => {
  let base;
  let server;
  let t;
  let auth;
  const PASSWORD = 'correct-horse-battery';

  before(async () => {
    const port = await freePort();
    t = setup({ HTTP_PORT: String(port), HTTP_HOST: '127.0.0.1', ADMIN_PANEL_PASSWORD: PASSWORD }, { withInbox: true });
    const secrets = new SecretStore(null).load();
    const keys = new KeyRing({ secrets, envKey: 'gsk_test_env_key_0000000000000000' }).load();
    const backup = new BackupAi({ secrets });
    auth = new PanelAuth({ config: t.config, secrets, core: t.core, logger: t.logger });
    const diary = { status: () => ({ mode: 'api', siteAvailable: false, apiError: null }), setCredentials() {} };
    const bilim = { loggedIn: true, session: t.client.session, setCredentials() {}, async login() {} };
    const groq = { testKey: async (key) => ({ ok: key.endsWith('good'), status: key.endsWith('good') ? 200 : 401, message: 'Invalid API Key', models: ['m'] }) };
    server = startWebServer({
      config: t.config, logger: t.logger, wa: t.wa, homework: t.homework, core: t.core, auth, settings: t.settings, secrets, scheduler: t.scheduler,
      inbox: t.inbox, keys, backup, groq, assistant: t.assistant, diary, bilim, siteBrowser: null, logBuffer: new LogBuffer(), restart: null,
    });
    await new Promise((resolve) => server.once('listening', resolve));
    base = `http://127.0.0.1:${port}`;
  });
  after(() => server.closeAll());

  const call = (path, { method = 'GET', body, cookie = '', headers = {} } = {}) => fetch(`${base}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json', ...(method !== 'GET' ? { 'X-HWB': '1' } : {}), ...(cookie ? { Cookie: cookie } : {}), ...headers },
    body: body === undefined ? undefined : JSON.stringify(body),
    redirect: 'manual',
  });
  const login = async () => {
    const res = await call('/api/auth/login', { method: 'POST', body: { password: PASSWORD } });
    assert.equal(res.status, 200);
    return res.headers.get('set-cookie').split(';')[0];
  };

  it('сайт отдаётся с защитными заголовками', async () => {
    const res = await fetch(`${base}/`);
    assert.equal(res.status, 200);
    assert.match(res.headers.get('content-type'), /text\/html/);
    const csp = res.headers.get('content-security-policy');
    assert.match(csp, /default-src 'self'/);
    assert.match(csp, /script-src 'self' 'sha256-/, 'importmap разрешён по хешу, а не unsafe-inline');
    assert.ok(!/script-src[^;]*unsafe-inline/.test(csp));
    assert.equal(res.headers.get('x-frame-options'), 'DENY');
    assert.equal((await fetch(`${base}/vendor/three/three.module.min.js`)).status, 200);
    for (const path of ['/vendor/three/../../package.json', '/vendor/three/addons/../../../package.json', '/../src/config.js', '/.env']) {
      assert.equal((await fetch(`${base}${path}`)).status, 404, path);
    }
  });

  it('битая кука от другого сайта на localhost не ломает панель', async () => {
    const res = await fetch(`${base}/`, { headers: { Cookie: 'other=100%; x=%E0%A4%A' } });
    assert.equal(res.status, 200);
    const api = await fetch(`${base}/api/auth/me`, { headers: { Cookie: 'other=100%' } });
    assert.equal(api.status, 200);
    assert.notEqual((await fetch(`${base}/api/chats/%E0%A4%A`, { headers: { Cookie: 'other=1' } })).status, 500);
  });

  it('без входа данные панели недоступны', async () => {
    assert.equal((await call('/api/overview')).status, 401);
    assert.equal((await call('/api/events')).status, 401);
    assert.equal((await call('/api/console', { method: 'POST', body: { command: 'status' } })).status, 401);
    const me = await (await call('/api/auth/me')).json();
    assert.deepEqual(me.methods, { password: true, whatsapp: true });
    assert.equal(me.authenticated, false);
  });

  it('вход по паролю: кука HttpOnly + SameSite=Strict', async () => {
    const bad = await call('/api/auth/login', { method: 'POST', body: { password: 'wrong' } });
    assert.equal(bad.status, 401);
    const res = await call('/api/auth/login', { method: 'POST', body: { password: PASSWORD } });
    const cookie = res.headers.get('set-cookie');
    assert.match(cookie, /HttpOnly/);
    assert.match(cookie, /SameSite=Strict/);
    const overview = await (await call('/api/overview', { cookie: cookie.split(';')[0] })).json();
    assert.equal(overview.bilim.className, '7 «А»');
    assert.equal(overview.stats.length, 14);
  });

  it('защита от CSRF: нужен служебный заголовок и своё происхождение', async () => {
    const cookie = await login();
    const noHeader = await fetch(`${base}/api/actions/poll`, { method: 'POST', headers: { Cookie: cookie } });
    assert.equal(noHeader.status, 403);
    const foreign = await call('/api/actions/poll', { method: 'POST', cookie, headers: { Origin: 'https://evil.example' } });
    assert.equal(foreign.status, 403);
    const own = await call('/api/settings', { method: 'PUT', cookie, headers: { Origin: base }, body: { values: {} } });
    assert.equal(own.status, 200);
  });

  it('настройки из панели применяются сразу', async () => {
    const cookie = await login();
    const days = { ...t.settings.describe().find((f) => f.path === 'schedule.days').value };
    days[7] = { mode: 'off', time: '', scope: 'new' };
    const res = await call('/api/settings', { method: 'PUT', cookie, body: { values: { 'schedule.days': days, 'ai.botName': 'Алия' } } });
    const data = await res.json();
    assert.deepEqual(data.changed.sort(), ['ai.botName', 'schedule.days']);
    assert.equal(t.config.schedule.days[7].mode, 'off');
    assert.equal(t.config.ai.botName, 'Алия');
    const bad = await call('/api/settings', { method: 'PUT', cookie, body: { values: { 'schedule.digestDelayMinutes': -5 } } });
    assert.equal(bad.status, 400);
    assert.match((await bad.json()).error, /после уроков/);
  });

  it('ключи: наружу только маска, нерабочий ключ помечается', async () => {
    const cookie = await login();
    const res = await call('/api/access/groq', { method: 'POST', cookie, body: { key: 'gsk_secret_value_1234567890_bad', label: 'Тест' } });
    const text = await res.text();
    assert.ok(!text.includes('secret_value'), 'полный ключ не возвращается');
    const data = JSON.parse(text);
    assert.equal(data.test.ok, false);
    assert.equal(data.keys.find((k) => k.label === 'Тест').status, 'invalid');
    const access = await (await call('/api/access', { cookie })).text();
    assert.ok(!access.includes('gsk_test_env_key_0000000000000000'));
    assert.ok(!access.includes(t.config.bilim.password || '\u0000'));
  });

  it('ответ ученику из панели: от имени бота, ИИ в чате замолкает', async () => {
    const cookie = await login();
    t.inbox.record(STUDENT, { dir: 'in', text: 'помогите', name: 'Аня' });
    const list = await (await call('/api/chats', { cookie })).json();
    assert.equal(list.chats[0].unread, 1);
    const chat = await (await call(`/api/chats/${encodeURIComponent(STUDENT)}`, { cookie })).json();
    assert.equal(chat.messages[0].text, 'помогите');
    assert.equal(t.inbox.unreadTotal(), 0, 'открыли — прочитано');
    const res = await call(`/api/chats/${encodeURIComponent(STUDENT)}/send`, { method: 'POST', cookie, body: { text: 'Привет! Сейчас помогу' } });
    assert.equal(res.status, 200);
    const sent = t.wa.sent.at(-1);
    assert.equal(sent.jid, STUDENT);
    assert.equal(sent.meta.by, 'admin');
    assert.equal(t.inbox.aiState(STUDENT), 'paused');
  });

  it('терминал выполняет только команды бота', async () => {
    const cookie = await login();
    const run = async (command) => (await (await call('/api/console', { method: 'POST', cookie, body: { command } })).json()).output;
    const status = await run('status');
    assert.ok(status.some((l) => /WhatsApp/.test(l.t)));
    assert.match((await run('rm -rf /'))[0].t, /команда не найдена/);
    assert.match((await run('$(reboot)'))[0].t, /команда не найдена/);
    const dz = await run('dz 15.10');
    assert.ok(dz.some((l) => /№ 250/.test(l.t)));
    assert.match((await run('restart --yes'))[0].t, /Перезапуск недоступен/);
    assert.deepEqual(tokenize(`ai ask "как дела" 'и ещё'`), ['ai', 'ask', 'как дела', 'и ещё']);
  });

  it('одноразовая ссылка для входа (команда !панель)', async () => {
    const link = auth.oneTimeLink('admin');
    const path = new URL(link).pathname + new URL(link).search;
    const first = await call(path);
    assert.equal(first.status, 302);
    assert.equal(first.headers.get('location'), '/app');
    assert.match(first.headers.get('set-cookie'), /hwb_session=/);
    const second = await call(path);
    assert.equal(second.headers.get('location'), '/?login=expired', 'второй раз ссылка не работает');
  });

  it('перебор пароля ограничен', async () => {
    let last;
    for (let i = 0; i < 10; i += 1) last = await call('/api/auth/login', { method: 'POST', body: { password: `guess-${i}` } });
    assert.equal(last.status, 429);
    assert.match((await last.json()).error, /Слишком много попыток/);
    // правильный пароль с этого адреса тоже ждёт
    assert.equal((await call('/api/auth/login', { method: 'POST', body: { password: PASSWORD } })).status, 429);
  });

  it('пароль хранится как scrypt-хеш', () => {
    const stored = hashPassword('пароль-123456');
    assert.match(stored, /^scrypt\$/);
    assert.ok(!stored.includes('пароль'));
    assert.equal(verifyPassword('пароль-123456', stored), true);
    assert.equal(verifyPassword('пароль-123457', stored), false);
  });
});

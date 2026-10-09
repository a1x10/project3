import assert from 'node:assert/strict';
import http from 'node:http';
import { after, before, describe, it } from 'node:test';
import { GroqClient, reasoningParams } from '../src/ai/groq.js';
import { BilimApiError, BilimAuthError, BilimClassClient } from '../src/bilimclass/client.js';

// Мини-сервер, имитирующий API: обработчик задаётся в каждом тесте
function mockServer() {
  const state = { handler: null, requests: [] };
  const server = http.createServer((req, res) => {
    let body = Buffer.alloc(0);
    req.on('data', (chunk) => { body = Buffer.concat([body, chunk]); });
    req.on('end', () => {
      const record = { method: req.method, url: new URL(req.url, 'http://x'), headers: req.headers, body };
      state.requests.push(record);
      const [status, json, headers = {}] = state.handler(record);
      res.writeHead(status, { 'Content-Type': 'application/json', ...headers });
      res.end(JSON.stringify(json));
    });
  });
  return {
    state,
    start: () => new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(`http://127.0.0.1:${server.address().port}`))),
    stop: () => new Promise((resolve) => server.close(resolve)),
  };
}

const LOGIN_OK = {
  access_token: 'token-1',
  refresh_token: 'r',
  user_info: {
    userId: 42, surname: 'Иванов', firstname: 'Иван',
    school_id: 777, school: { name: 'Школа-лицей №1', eduYears: [{ eduYear: 2025, isCurrent: true }] },
    group: { id: 55, name: '7 «А»' },
  },
};

describe('BilimClassClient', () => {
  const mock = mockServer();
  let base;
  before(async () => { base = await mock.start(); });
  after(() => mock.stop());

  const client = (extra = {}) => new BilimClassClient({ apiUrl: base, siteUrl: 'https://www.bilimclass.kz', login: 'student', password: 'secret', timeoutMs: 3000, ...extra });

  it('входит, шлёт нужные заголовки и запрашивает дневник по понедельнику', async () => {
    mock.state.requests = [];
    mock.state.handler = (req) => {
      if (req.url.pathname === '/api/v2/os/login') return [200, LOGIN_OK];
      return [200, { data: { days: [{ date: '13 октября', subjects: [] }] } }];
    };
    const c = client();
    const data = await c.getWeek('2025-10-13');
    assert.equal(data.days.length, 1);
    const [login, diary] = mock.state.requests;
    assert.deepEqual(JSON.parse(login.body), { login: 'student', password: 'secret' });
    assert.equal(login.headers['x-localization'], 'ru');
    assert.ok(login.headers['x-mathrix']);
    assert.equal(diary.url.pathname, '/api/v4/os/clientoffice/diary');
    assert.equal(diary.url.searchParams.get('date'), '13.10.2025');
    assert.equal(diary.url.searchParams.get('schoolId'), '777');
    assert.equal(diary.url.searchParams.get('groupId'), '55');
    assert.equal(diary.url.searchParams.get('eduYear'), '2025');
    assert.equal(diary.headers.authorization, 'Bearer token-1');
    assert.equal(diary.headers['x-school-id'], '777');
    assert.equal(c.session.className, '7 «А»');
  });

  it('при истёкшей сессии (401) входит заново и повторяет запрос', async () => {
    mock.state.requests = [];
    let diaryCalls = 0;
    mock.state.handler = (req) => {
      if (req.url.pathname === '/api/v2/os/login') return [200, LOGIN_OK];
      diaryCalls += 1;
      return diaryCalls === 1 ? [401, { message: 'Сессия истекла' }] : [200, { data: { days: [] } }];
    };
    await client().getWeek('2025-10-13');
    assert.equal(mock.state.requests.filter((r) => r.url.pathname === '/api/v2/os/login').length, 2);
  });

  it('повторяет запрос при ошибке сервера 5xx', async () => {
    let diaryCalls = 0;
    mock.state.handler = (req) => {
      if (req.url.pathname === '/api/v2/os/login') return [200, LOGIN_OK];
      diaryCalls += 1;
      return diaryCalls === 1 ? [502, {}] : [200, { data: { days: [] } }];
    };
    await client().getWeek('2025-10-13');
    assert.equal(diaryCalls, 2);
  });

  it('неверный пароль: понятная ошибка и пауза перед следующей попыткой', async () => {
    mock.state.requests = [];
    mock.state.handler = () => [412, { message: 'Неправильный логин или пароль' }];
    const c = client();
    await assert.rejects(() => c.login(), (e) => e instanceof BilimAuthError && /Неправильный логин или пароль/.test(e.message));
    await assert.rejects(() => c.getWeek('2025-10-13'), BilimAuthError);
    assert.equal(mock.state.requests.length, 1, 'второй попытки входа быть не должно');
  });

  it('HTTP 426 — сообщение про обновление API', async () => {
    mock.state.handler = (req) => (req.url.pathname === '/api/v2/os/login' ? [200, LOGIN_OK] : [426, {}]);
    await assert.rejects(() => client().getWeek('2025-10-13'), (e) => e instanceof BilimApiError && e.status === 426);
  });

  it('ручные BILIM_SCHOOL_ID / BILIM_GROUP_ID важнее профиля', async () => {
    mock.state.requests = [];
    mock.state.handler = (req) => (req.url.pathname === '/api/v2/os/login' ? [200, LOGIN_OK] : [200, { data: { files: [{ name: 'a.pdf' }] } }]);
    const c = client({ schoolId: '1', groupId: '2' });
    const files = await c.getHomeworkFiles('uuid-1');
    assert.equal(files.length, 1);
    const req = mock.state.requests.at(-1);
    assert.equal(req.url.searchParams.get('schoolId'), '1');
    assert.equal(req.url.searchParams.get('homeworkUuid'), 'uuid-1');
  });
});

describe('GroqClient', () => {
  const mock = mockServer();
  let base;
  before(async () => { base = await mock.start(); });
  after(() => mock.stop());
  const groq = () => new GroqClient({ apiKey: 'k', baseUrl: base, timeoutMs: 3000 });

  it('параметры рассуждений для разных моделей', () => {
    assert.deepEqual(reasoningParams('openai/gpt-oss-120b', 'low'), { include_reasoning: false, reasoning_effort: 'low' });
    assert.deepEqual(reasoningParams('qwen/qwen3.8-27b'), { reasoning_format: 'hidden' });
    assert.deepEqual(reasoningParams('some/other'), {});
  });

  it('повторяет запрос после 429 с учётом retry-after', async () => {
    let calls = 0;
    mock.state.handler = (req) => {
      calls += 1;
      if (calls === 1) return [429, { error: { message: 'rate limit' } }, { 'retry-after': '0' }];
      const body = JSON.parse(req.body);
      assert.equal(body.model, 'openai/gpt-oss-120b');
      assert.equal(body.include_reasoning, false);
      return [200, { choices: [{ message: { content: '<think>x</think>Ответ: 56' }, finish_reason: 'stop' }] }];
    };
    const result = await groq().chat({ model: 'openai/gpt-oss-120b', messages: [{ role: 'user', content: '7*8' }] });
    assert.equal(result.text, 'Ответ: 56');
    assert.equal(calls, 2);
  });

  it('переходит на запасную модель, если основная отключена', async () => {
    mock.state.handler = (req) => {
      const { model } = JSON.parse(req.body);
      if (model === 'old/model') return [400, { error: { message: 'The model `old/model` has been decommissioned', code: 'model_decommissioned' } }];
      return [200, { choices: [{ message: { content: 'ok' } }] }];
    };
    const result = await groq().chat({ model: 'old/model', fallbacks: ['new/model'], messages: [] });
    assert.equal(result.model, 'new/model');
  });

  it('неверный ключ — сразу ошибка 401 без повторов', async () => {
    let calls = 0;
    mock.state.handler = () => { calls += 1; return [401, { error: { message: 'Invalid API Key' } }]; };
    const g = groq();
    await assert.rejects(() => g.chat({ model: 'a', fallbacks: ['b'], messages: [] }), (e) => e.status === 401);
    assert.equal(calls, 1);
    assert.equal(g.authBroken, true);
  });

  it('распознавание голоса отправляет multipart с файлом', async () => {
    mock.state.handler = (req) => {
      assert.match(req.headers['content-type'], /multipart\/form-data/);
      assert.ok(req.body.includes(Buffer.from('whisper-large-v3-turbo')));
      assert.ok(req.body.includes(Buffer.from('OGGDATA')));
      return [200, { text: ' что задали по алгебре ' }];
    };
    const text = await groq().transcribe(Buffer.from('OGGDATA'), { model: 'whisper-large-v3-turbo' });
    assert.equal(text, 'что задали по алгебре');
  });
});

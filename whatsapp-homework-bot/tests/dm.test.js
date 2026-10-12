import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { BackupAi, KeyRing } from '../src/ai/keys.js';
import { Assistant } from '../src/ai/assistant.js';
import { GroqClient, GroqError } from '../src/ai/groq.js';
import { Inbox } from '../src/inbox.js';
import { SecretStore } from '../src/secrets.js';
import { splitHuman, typingMs } from '../src/whatsapp/handler.js';
import { detectIntent } from '../src/whatsapp/intents.js';
import { incoming } from './helpers.js';
import { setup, STUDENT } from './setup.js';

const memorySecrets = () => {
  const s = new SecretStore(null);
  s.load();
  return s;
};

describe('просьбы обычными словами', () => {
  const today = '2025-10-14';
  it('распознаёт просьбы показать ДЗ, но не вопросы «как решить»', () => {
    assert.deepEqual(detectIntent('скинь дз на завтра', today), { name: 'homework', args: '15.10' });
    assert.deepEqual(detectIntent('что задали по алгебре?', today), { name: 'homework', args: 'алгебре' });
    assert.deepEqual(detectIntent('дз на следующую неделю', today), { name: 'week', args: 'след' });
    assert.deepEqual(detectIntent('какие уроки в пятницу', today), { name: 'schedule', args: '17.10' });
    assert.deepEqual(detectIntent('что задали к четвергу', today), { name: 'homework', args: '16.10' });
    assert.deepEqual(detectIntent('ертең үй жұмысы қандай', today), { name: 'homework', args: '15.10' });
    for (const q of ['как решить дз по алгебре', 'объясни задание по физике', 'я сделал дз', 'кто сделал дз?', 'привет', '!дз']) {
      assert.equal(detectIntent(q, today), null, q);
    }
  });
});

describe('личные сообщения', () => {
  it('первое сообщение — приветствие с честным предупреждением, на «привет» ИИ не зовём', async () => {
    const t = setup({}, { withInbox: true });
    await t.handler.handle(incoming({ chat: STUDENT, text: 'Привет!', name: 'Аня Иванова' }));
    assert.equal(t.wa.texts().length, 1);
    assert.match(t.wa.texts()[0], /^Привет, Аня! 👋/);
    assert.match(t.wa.texts()[0], /Переписку с ботом может видеть админ класса/);
    assert.equal(t.wa.sent[0].options.quoted, undefined, 'в личке без цитаты');
    assert.equal(t.groq.calls.length, 0);
    // второе сообщение — уже без приветствия
    await t.handler.handle(incoming({ chat: STUDENT, text: 'объясни теорему Пифагора' }));
    assert.equal(t.wa.texts().length, 2);
    assert.ok(!/Привет/.test(t.wa.texts()[1]));
  });

  it('«скинь дз на завтра» без ! — присылает ДЗ из дневника, а не ответ ИИ', async () => {
    const t = setup({}, { withInbox: true });
    t.inbox.record(STUDENT, { dir: 'in', text: 'был разговор' }); // не первый раз
    await t.handler.handle(incoming({ chat: STUDENT, text: 'скинь дз на завтра' }));
    assert.equal(t.groq.calls.length, 0);
    assert.match(t.wa.texts()[0], /№ 250/);
    assert.ok(t.wa.read?.length, 'сообщение отмечено прочитанным');
  });

  it('в группе просьба работает, только когда обращаются к боту', async () => {
    const t = setup({}, { withInbox: true });
    const GROUP = t.config.whatsapp.groupIds[0];
    t.groq.classifierAnswer = '{"respond": false}';
    await t.handler.handle(incoming({ chat: GROUP, text: 'скинь дз на завтра' }));
    assert.equal(t.wa.sent.length, 0);
    await t.handler.handle(incoming({ chat: GROUP, text: 'бот, скинь дз на завтра' }));
    assert.match(t.wa.texts()[0], /№ 250/);
  });

  it('админ отвечает сам — ИИ в этом чате замолкает; выключенный ИИ — тоже', async () => {
    const t = setup({}, { withInbox: true });
    t.inbox.record(STUDENT, { dir: 'in', text: 'привет' });
    t.inbox.takeover(STUDENT);
    await t.handler.handle(incoming({ chat: STUDENT, text: 'объясни теорему Пифагора' }));
    assert.equal(t.groq.calls.length, 0);
    assert.equal(t.wa.sent.length, 0);
    assert.equal(t.inbox.get(STUDENT).unread, 2, 'сообщение видно в панели');
    t.inbox.setAi(STUDENT, 'on');
    await t.handler.handle(incoming({ chat: STUDENT, text: 'объясни теорему Пифагора' }));
    assert.equal(t.groq.calls.length, 1);
    t.inbox.setAi(STUDENT, 'off');
    await t.handler.handle(incoming({ chat: STUDENT, text: 'а косинус?' }));
    assert.equal(t.groq.calls.length, 1);
    // команды работают всегда
    await t.handler.handle(incoming({ chat: STUDENT, text: '!дз завтра' }));
    assert.match(t.wa.texts().at(-1), /№ 250/);
  });

  it('в личке ИИ видит переписку как диалог', async () => {
    const t = setup({}, { withInbox: true });
    t.inbox.record(STUDENT, { dir: 'in', text: 'что такое катет?' });
    t.inbox.record(STUDENT, { dir: 'out', text: 'Катет — сторона прямоугольного треугольника у прямого угла.' });
    await t.handler.handle(incoming({ chat: STUDENT, text: 'а гипотенуза?' }));
    const { messages } = t.groq.calls[0];
    assert.deepEqual(messages.slice(1).map((m) => m.role), ['user', 'assistant', 'user']);
    assert.equal(messages.at(-1).content, 'а гипотенуза?');
    assert.match(messages[0].content, /личной переписке/);
  });
});

describe('ответы как у человека', () => {
  it('длинный ответ — до трёх сообщений по абзацам, короткий — одним', () => {
    assert.deepEqual(splitHuman('коротко'), ['коротко']);
    const long = Array.from({ length: 6 }, (_, i) => `Абзац ${i + 1}. ${'слово '.repeat(30).trim()}`).join('\n\n');
    const parts = splitHuman(long);
    assert.ok(parts.length >= 2 && parts.length <= 3, String(parts.length));
    assert.equal(parts.join('\n\n'), long, 'ничего не потеряно');
  });

  it('время «печатает…» зависит от длины', () => {
    const none = () => 0;
    assert.equal(typingMs('ок', none), 1000);
    assert.equal(typingMs('x'.repeat(100), none), 2800);
    assert.equal(typingMs('x'.repeat(5000), none), 7000);
  });

  it('ответ ИИ уходит несколькими сообщениями, цитата — только у первого', async () => {
    const t = setup();
    const long = Array.from({ length: 6 }, (_, i) => `Шаг ${i + 1}. ${'решаем дальше '.repeat(12).trim()}`).join('\n\n');
    t.groq.chat = async (req) => (req.json ? { text: '{"respond": true}' } : { text: long, model: 'm' });
    const GROUP = t.config.whatsapp.groupIds[0];
    await t.handler.handle(incoming({ chat: GROUP, text: 'бот, как решить номер 250 по алгебре?' }));
    assert.ok(t.wa.sent.length >= 2);
    assert.ok(t.wa.sent[0].options.quoted);
    assert.equal(t.wa.sent[1].options.quoted, undefined);
  });
});

describe('ключи ИИ', () => {
  it('нерабочий ключ — бот сам переходит на запасной ключ и продолжает', async () => {
    const keys = new KeyRing({ secrets: memorySecrets(), envKey: 'gsk_env_key_000000000000' }).load();
    keys.add({ key: 'gsk_second_key_11111111111', label: 'Запасной' });
    const switched = [];
    keys.on('invalid', (e) => switched.push(e));
    const used = [];
    const fetchImpl = async (url, opts) => {
      used.push(opts.headers.Authorization);
      if (opts.headers.Authorization === 'Bearer gsk_env_key_000000000000') {
        return new Response(JSON.stringify({ error: { message: 'Invalid API Key' } }), { status: 401 });
      }
      return new Response(JSON.stringify({ choices: [{ message: { content: 'ок' } }] }), { status: 200 });
    };
    const groq = new GroqClient({ keys, baseUrl: 'http://x', fetchImpl });
    const result = await groq.chat({ model: 'm', messages: [] });
    assert.equal(result.text, 'ок');
    assert.deepEqual(used, ['Bearer gsk_env_key_000000000000', 'Bearer gsk_second_key_11111111111']);
    assert.deepEqual(switched, [{ label: 'Ключ из .env', next: 'Запасной' }]);
    const list = keys.list();
    assert.equal(list.find((k) => k.source === 'env').status, 'invalid');
    assert.equal(list.find((k) => k.label === 'Запасной').inUse, true);
    assert.ok(list.every((k) => !JSON.stringify(k).includes('second_key_11111')), 'ключи наружу только маской');
  });

  it('из-за лимита (429) ключ НЕ меняется — лимиты общие на аккаунт', async () => {
    const keys = new KeyRing({ secrets: memorySecrets() }).load();
    keys.add({ key: 'gsk_first_key_000000000000' });
    keys.add({ key: 'gsk_second_key_11111111111' });
    const used = new Set();
    const fetchImpl = async (url, opts) => {
      used.add(opts.headers.Authorization);
      return new Response(JSON.stringify({ error: { message: 'rate limit' } }), { status: 429, headers: { 'retry-after': '60' } });
    };
    const groq = new GroqClient({ keys, baseUrl: 'http://x', fetchImpl });
    await assert.rejects(() => groq.chat({ model: 'm', messages: [] }), (e) => e.status === 429);
    assert.equal(used.size, 1);
  });

  it('ключи сохраняются; ключ из .env можно убрать из панели', () => {
    const secrets = memorySecrets();
    const keys = new KeyRing({ secrets, envKey: 'gsk_env_key_000000000000' }).load();
    const id = keys.add({ key: 'gsk_panel_key_22222222222', label: 'Мой' });
    keys.remove('env');
    const again = new KeyRing({ secrets, envKey: 'gsk_env_key_000000000000' }).load();
    assert.deepEqual(again.list().map((k) => k.id), [id]);
    assert.equal(again.current(), 'gsk_panel_key_22222222222');
    assert.throws(() => again.add({ key: 'плохой ключ' }), /неправильно/);
    assert.throws(() => again.add({ key: 'gsk_panel_key_22222222222' }), /уже добавлен/);
  });

  it('Groq недоступен — отвечает запасной ИИ (без фото)', async () => {
    const secrets = memorySecrets();
    const backup = new BackupAi({ secrets });
    backup.update({ enabled: true, baseUrl: 'https://openrouter.example/api/v1', apiKey: 'sk-or-backup-key-000000', model: 'some/model' });
    const t = setup();
    const calls = [];
    backup.client().client.post = async (path, body) => {
      calls.push(body);
      return { choices: [{ message: { content: 'ответ запасного ИИ' } }] };
    };
    t.groq.fail = new GroqError('Groq перегружен', { status: 503 });
    const assistant = new Assistant({ groq: t.groq, homework: t.homework, config: t.config, logger: t.logger, backup });
    const text = await assistant.answer({ question: 'что на фото?', image: { buffer: Buffer.from('x'), mimetype: 'image/jpeg' } });
    assert.equal(text, 'ответ запасного ИИ');
    assert.equal(calls[0].model, 'some/model');
    assert.equal(typeof calls[0].messages.at(-1).content, 'string', 'фото запасному ИИ не отправляется');
    assert.equal(calls[0].include_reasoning, undefined, 'без параметров Groq');
    assert.throws(() => backup.update({ enabled: true, baseUrl: 'http://evil.example', model: 'x' }), /https/);
  });
});

describe('журнал переписки', () => {
  it('хранит личку, считает непрочитанное, не дублирует', () => {
    const inbox = new Inbox({ file: null });
    inbox.record(STUDENT, { dir: 'in', text: 'привет', name: 'Аня', id: 'A1' });
    inbox.record(STUDENT, { dir: 'in', text: 'привет', name: 'Аня', id: 'A1' });
    inbox.record(STUDENT, { dir: 'out', text: 'Привет!' });
    const [chat] = inbox.list();
    assert.equal(chat.name, 'Аня');
    assert.equal(chat.unread, 1);
    assert.equal(inbox.get(STUDENT).messages.length, 2);
    inbox.markRead(STUDENT);
    assert.equal(inbox.unreadTotal(), 0);
    assert.deepEqual(inbox.history(STUDENT).map((m) => m.fromBot), [false, true]);
  });
});

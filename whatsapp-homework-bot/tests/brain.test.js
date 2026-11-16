import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { askTaskText, dayArg, heuristicDecision, normalizeDecision } from '../src/ai/assistant.js';
import { GroqClient, GroqError } from '../src/ai/groq.js';
import { UnderstandJournal } from '../src/ai/journal.js';
import { personaRules, systemPrompt } from '../src/ai/prompts.js';
import { AiRouter } from '../src/ai/router.js';
import { buildConfig } from '../src/config.js';
import { Settings } from '../src/settings.js';
import { incoming } from './helpers.js';
import { GROUP, setup, STUDENT } from './setup.js';

const at = (iso, hh, mm = 0) => ({ iso, minutes: hh * 60 + mm, weekday: ((new Date(`${iso}T00:00:00Z`).getUTCDay() + 6) % 7) + 1 });
const decide = (t, obj) => {
  t.groq.classifierAnswer = JSON.stringify({ to_bot: 'yes', about_study: true, confidence: 0.9, reason: 'тест', ...obj });
};

describe('мозг: провайдеры и роли', () => {
  const fake = (name, { fail = null } = {}) => ({
    hasKey: true,
    calls: [],
    async chat(req) {
      this.calls.push(req);
      if (fail) throw fail;
      return { text: `ответ ${name}`, model: req.model };
    },
  });

  it('auto: есть ключ OpenRouter — думает OpenRouter, иначе Groq', async () => {
    const config = buildConfig({});
    const groq = fake('groq');
    const openrouter = fake('openrouter');
    const router = new AiRouter({ config, clients: { groq, openrouter } });
    const r = await router.chat('understand', { messages: [] });
    assert.equal(r.provider, 'openrouter');
    assert.equal(openrouter.calls[0].model, 'openrouter/free');
    openrouter.hasKey = false;
    const r2 = await router.chat('chat', { messages: [] });
    assert.equal(r2.provider, 'groq');
    assert.equal(groq.calls[0].model, config.groq.model);
  });

  it('свой провайдер и модель для роли; при сбое — запасной провайдер', async () => {
    const config = buildConfig({});
    config.ai.routing.chat = { provider: 'groq', model: 'my/model' };
    const groq = fake('groq', { fail: new GroqError('лимит', { status: 429 }) });
    const openrouter = fake('openrouter');
    const router = new AiRouter({ config, clients: { groq, openrouter } });
    const r = await router.chat('chat', { messages: [] });
    assert.equal(groq.calls[0].model, 'my/model');
    assert.equal(r.provider, 'openrouter', 'Groq не ответил — ответил OpenRouter');
    assert.equal(router.stats.groq.fail, 1);
    assert.equal(router.status().roles.chat.provider, 'groq');
  });

  it('без ключей — понятная ошибка', async () => {
    const router = new AiRouter({ config: buildConfig({}), clients: {} });
    await assert.rejects(() => router.chat('chat', { messages: [] }), /Нет ни одного ключа ИИ/);
  });

  it('запрос к OpenRouter: имя приложения, скрытые рассуждения, max_tokens', async () => {
    let sent;
    const fetchImpl = async (url, opts) => {
      sent = { url, headers: opts.headers, body: JSON.parse(opts.body) };
      return new Response(JSON.stringify({ choices: [{ message: { content: 'ок' } }] }), { status: 200 });
    };
    const client = new GroqClient({ apiKey: 'sk-or-test-0000000000', baseUrl: 'https://openrouter.ai/api/v1', flavor: 'openrouter', headers: { 'X-Title': 'Bot DZ' }, fetchImpl });
    await client.chat({ model: 'openrouter/free', messages: [], maxTokens: 50, json: true, reasoningEffort: 'low' });
    assert.equal(sent.url, 'https://openrouter.ai/api/v1/chat/completions');
    assert.equal(sent.headers['X-Title'], 'Bot DZ');
    assert.deepEqual(sent.body.reasoning, { effort: 'low', exclude: true });
    assert.equal(sent.body.max_tokens, 50);
    assert.equal(sent.body.include_reasoning, undefined);
    assert.deepEqual(sent.body.response_format, { type: 'json_object' });
  });
});

describe('понимание сообщений', () => {
  it('ответ модели приводится к понятному виду', () => {
    const d = normalizeDecision({ action: 'ask_task', to_bot: 'yes', task: '№250', confidence: '0.8', subject: 'null' });
    assert.equal(d.action, 'ask_task');
    assert.equal(d.task, '№250');
    assert.equal(d.subject, null);
    assert.equal(d.confidence, 0.8);
    assert.equal(normalizeDecision({ action: 'взломать' }).action, 'ignore');
    assert.equal(normalizeDecision({ action: 'answer', to_bot: 'no' }, { isPrivate: true }).toBot, 'yes', 'в личке всё — боту');
  });

  it('без ИИ — правила', () => {
    assert.equal(heuristicDecision('что задали на завтра?', { today: '2025-10-14' }).action, 'send_homework');
    assert.equal(heuristicDecision('как решить номер 250?', { today: '2025-10-14' }).action, 'ask_task');
    assert.equal(heuristicDecision('как решить 2x+5=11?', { today: '2025-10-14' }).action, 'answer');
    assert.equal(heuristicDecision('пошли в кино', { today: '2025-10-14' }).action, 'ignore');
  });

  it('просьба прислать пример — живая и с номером задания', () => {
    const text = askTaskText({ task: '№250', subject: 'Алгебра' }, { random: () => 0 });
    assert.match(text, /пример №250/);
    assert.match(askTaskText({ subject: 'Литература' }, { random: () => 0 }), /вопрос/);
    assert.equal(dayArg('tomorrow', '2025-10-14'), '15.10');
    assert.equal(dayArg('пятница', '2025-10-14'), '17.10');
    assert.equal(dayArg('ерунда', '2025-10-14'), '');
  });
});

describe('бот в группе сам понимает, что делать', () => {
  const withJournal = () => {
    const t = setup();
    t.handler.journal = new UnderstandJournal();
    return t;
  };

  it('«как решить номер 250?» — отвечает с цитатой «скинь пример», а потом решает присланное', async () => {
    const t = withJournal();
    decide(t, { action: 'ask_task', task: '№250', subject: 'Алгебра' });
    await t.handler.handle(incoming({ chat: GROUP, text: 'кто знает как решить номер 250?' }));
    assert.equal(t.wa.sent.length, 1);
    assert.match(t.wa.texts()[0], /№250/);
    assert.ok(t.wa.sent[0].options.quoted, 'ответ с цитатой вопроса');
    assert.equal(t.groq.answers.length, 0, 'пока пример не прислали — не решает');
    assert.equal(t.handler.journal.recent()[0].done, 'попросила пример');

    // тот же ученик присылает пример — бот решает без всяких обращений
    await t.handler.handle(incoming({ chat: GROUP, text: '2x + 5 = 11, найти x' }));
    assert.equal(t.groq.answers.length, 1);
    assert.match(t.groq.answers[0].messages.at(-1).content, /которое ты просила прислать[\s\S]*2x \+ 5 = 11/);
  });

  it('«что задали на завтра?» без обращения — присылает ДЗ из дневника', async () => {
    const t = withJournal();
    decide(t, { action: 'send_homework', day: 'tomorrow' });
    await t.handler.handle(incoming({ chat: GROUP, text: 'а что задали на завтра?' }));
    assert.match(t.wa.texts()[0], /№ 250/);
    assert.equal(t.groq.answers.length, 0);
  });

  it('вопрос другому человеку — молчит и пишет в журнал почему', async () => {
    const t = withJournal();
    decide(t, { action: 'ignore', to_bot: 'no', reason: 'вопрос Ане' });
    await t.handler.handle(incoming({ chat: GROUP, text: 'Аня, ты сделала дз по алгебре?' }));
    assert.equal(t.wa.sent.length, 0);
    const [entry] = t.handler.journal.recent();
    assert.equal(entry.done, 'промолчала');
    assert.equal(entry.decision.reason, 'вопрос Ане');
  });

  it('болтовня даже не уходит в ИИ (экономия лимитов)', async () => {
    const t = withJournal();
    await t.handler.handle(incoming({ chat: GROUP, text: 'пошли после школы в кино' }));
    assert.equal(t.groq.calls.length, 0);
  });

  it('режим «слушать всё» — ИИ читает каждое сообщение', async () => {
    const t = withJournal();
    t.settings.update({ 'ai.mode': 'all' });
    decide(t, { action: 'ignore', to_bot: 'no' });
    await t.handler.handle(incoming({ chat: GROUP, text: 'пошли после школы в кино' }));
    assert.equal(t.groq.calls.length, 1);
    assert.equal(t.wa.sent.length, 0);
  });

  it('«спасибо бот» после её ответа — реакция ❤️, а не сообщение', async () => {
    const t = withJournal();
    decide(t, { action: 'answer' });
    await t.handler.handle(incoming({ chat: GROUP, text: 'бот, что такое фотосинтез?' }));
    const sent = t.wa.sent.length;
    decide(t, { action: 'react' });
    await t.handler.handle(incoming({ chat: GROUP, text: 'спасибо бот', id: 'THANKS1' }));
    assert.equal(t.wa.sent.length, sent, 'сообщений больше нет');
    assert.equal(t.wa.reactions?.length, 1);
    assert.equal(t.wa.reactions[0].id, 'THANKS1');
  });

  it('действия можно выключить: «не просить пример» — сразу отвечает', async () => {
    const t = withJournal();
    t.settings.update({ 'ai.actions': { ...t.config.ai.actions, askTask: false } });
    decide(t, { action: 'ask_task', task: '№250' });
    await t.handler.handle(incoming({ chat: GROUP, text: 'бот, как решить номер 250?' }));
    assert.equal(t.groq.answers.length, 1);
  });

  it('суточный лимит «понимания» — дальше по правилам, без ИИ', async () => {
    const t = withJournal();
    t.settings.update({ 'ai.understandDailyLimit': 10 });
    for (let i = 0; i < 10; i += 1) t.core.countUsage('understand');
    await t.handler.handle(incoming({ chat: GROUP, text: 'что задали на завтра?' }));
    assert.equal(t.groq.calls.length, 0);
    assert.match(t.wa.texts()[0], /№ 250/);
  });
});

describe('характер', () => {
  it('род, тон, эмодзи и свои указания попадают в инструкцию', () => {
    const rules = personaRules({ gender: 'female', tone: 'fun', emoji: 0, length: 'short', custom: 'Называй всех «котики»' });
    assert.match(rules, /женском роде/);
    assert.match(rules, /с юмором/);
    assert.match(rules, /Не используй эмодзи/);
    assert.match(rules, /1–4 строки/);
    assert.match(rules, /котики/);
    assert.match(systemPrompt({ botName: 'Алия', context: 'ctx', persona: { gender: 'male', tone: 'strict', emoji: 2, length: 'normal', custom: '' } }), /мужском роде/);
  });

  it('проверка характера в настройках', () => {
    const config = buildConfig({});
    const settings = new Settings({ config, file: null });
    settings.update({ 'ai.persona': { gender: 'male', tone: 'chill', emoji: 3, length: 'detailed', custom: '' } });
    assert.equal(config.ai.persona.tone, 'chill');
    assert.throws(() => settings.update({ 'ai.persona': { gender: 'robot', tone: 'chill', emoji: 1, length: 'short' } }), /характер/);
    settings.update({ 'ai.routing': { chat: { provider: 'openrouter', model: '~deepseek/deepseek-flash-latest' }, understand: { provider: 'auto' }, vision: { provider: 'groq', model: '' } } });
    assert.equal(config.ai.routing.chat.model, '~deepseek/deepseek-flash-latest');
    assert.throws(() => settings.update({ 'ai.routing': { chat: { provider: 'openai' } } }), /провайдер/);
  });

  it('ответ ИИ — с характером из настроек', async () => {
    const t = setup();
    t.settings.update({ 'ai.persona': { gender: 'female', tone: 'fun', emoji: 2, length: 'short', custom: 'Говори «погнали»' } });
    decide(t, { action: 'answer' });
    await t.handler.handle(incoming({ chat: STUDENT, text: 'объясни теорему Пифагора' }));
    assert.match(t.groq.answers[0].messages[0].content, /погнали/);
  });
});

describe('заметки для ИИ', () => {
  it('!заметка — ИИ учитывает её в ответах', async () => {
    const t = setup();
    await t.handler.handle(incoming({ chat: GROUP, sender: '77015556677@s.whatsapp.net', text: '!заметка Алгебра: учебник Абылкасымова, 7 класс' }));
    assert.match(t.wa.texts()[0], /Запомнила \(№1\)/);
    const context = await t.homework.aiContext();
    assert.match(context, /Заметки админа класса[\s\S]*Алгебра: учебник Абылкасымова/);
    await t.handler.handle(incoming({ chat: GROUP, sender: '77015556677@s.whatsapp.net', text: '!заметка удалить 1' }));
    assert.equal(t.store.data.notes.length, 0);
  });

  it('просроченная заметка не попадает в контекст', async () => {
    const t = setup();
    t.store.data.notes = [{ id: 1, text: 'СОР в понедельник', until: '2025-10-01' }, { id: 2, text: 'Физра на улице', until: '2025-10-20' }];
    const context = await t.homework.aiContext();
    assert.ok(!context.includes('СОР в понедельник'));
    assert.match(context, /Физра на улице \(до 20\.10\)/);
  });
});

describe('отложенные сообщения', () => {
  it('разовое — уходит в своё время один раз; еженедельное — по дням', () => {
    const t = setup();
    t.store.data.scheduled = [
      { id: 1, kind: 'once', text: 'Завтра физра на улице!', at: '2025-10-14T15:00', enabled: true },
      { id: 2, kind: 'weekly', text: 'Не забудьте дневники 📓', days: [2, 4], time: '08:00', enabled: true },
    ];
    assert.deepEqual(t.scheduler.sendScheduled(at('2025-10-14', 7, 59)), []);
    assert.deepEqual(t.scheduler.sendScheduled(at('2025-10-14', 8, 5)), [2], 'вторник 08:00 — еженедельное');
    assert.deepEqual(t.scheduler.sendScheduled(at('2025-10-14', 14, 59)), []);
    assert.deepEqual(t.scheduler.sendScheduled(at('2025-10-14', 15, 1)), [1]);
    assert.deepEqual(t.scheduler.sendScheduled(at('2025-10-14', 15, 30)), [], 'второй раз не шлёт');
    assert.equal(t.store.data.scheduled[0].enabled, false);
    assert.deepEqual(t.wa.texts().sort(), ['Завтра физра на улице!', 'Не забудьте дневники 📓']);
    assert.deepEqual(t.scheduler.sendScheduled(at('2025-10-15', 8, 10)), [], 'среда — не его день');
    assert.deepEqual(t.scheduler.sendScheduled(at('2025-10-16', 8, 10)), [2]);
  });

  it('разовое, пропущенное из-за выключения больше чем на 3 часа, — не отправляется', () => {
    const t = setup();
    t.store.data.scheduled = [{ id: 1, kind: 'once', text: 'старое', at: '2025-10-13T09:00', enabled: true }];
    assert.deepEqual(t.scheduler.sendScheduled(at('2025-10-14', 9)), []);
    assert.equal(t.store.data.scheduled[0].enabled, false);
    assert.equal(t.store.data.scheduled[0].lastRun, 'пропущено');
  });
});

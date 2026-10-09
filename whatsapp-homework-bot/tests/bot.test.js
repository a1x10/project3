import assert from 'node:assert/strict';
import { beforeEach, describe, it } from 'node:test';
import { Assistant, looksLikeStudyQuestion } from '../src/ai/assistant.js';
import { BotCore } from '../src/core.js';
import { HomeworkService } from '../src/homework/service.js';
import { Scheduler } from '../src/scheduler.js';
import { Commands, parseCommand } from '../src/whatsapp/commands.js';
import { MessageHandler } from '../src/whatsapp/handler.js';
import { FakeBilimClient, FakeWA, incoming, memoryStore, rawWeek, testConfig, TUESDAY_10AM } from './helpers.js';

const GROUP = '120363000000000001@g.us';
const OTHER_GROUP = '120363000000000999@g.us';
const ADMIN = '77015556677@s.whatsapp.net';
const STUDENT = '77011112233@s.whatsapp.net';

const WEEKS = {
  '2025-10-13': rawWeek('2025-10-13', {
    1: [['Алгебра', '№ 1']],
    2: [['Физика', '§ 12']],
    3: [['Алгебра', '№ 250'], ['Русский язык', 'Упр. 5']],
    4: [['История', null]],
    5: [['Литература', 'Читать стр. 40-55']],
  }),
  '2025-10-20': rawWeek('2025-10-20', { 1: [['Алгебра', '№ 300']] }),
};

// Фейковая нейросеть: запоминает запросы, отвечает заданным текстом
class FakeGroq {
  constructor() {
    this.calls = [];
    this.classifierAnswer = '{"respond": true, "reason": "вопрос по ДЗ"}';
    this.fail = null;
  }

  async chat(req) {
    this.calls.push(req);
    if (this.fail) throw this.fail;
    if (req.json) return { text: this.classifierAnswer, model: req.model };
    return { text: '**Ответ:** реши уравнение по шагам', model: req.model };
  }

  async transcribe() {
    return 'что задали по физике';
  }
}

function setup(env = {}) {
  const config = testConfig({ ADMIN_NUMBERS: '77015556677', WA_GROUP_IDS: GROUP, ...env });
  const store = memoryStore();
  const wa = new FakeWA();
  wa.groups[GROUP] = { id: GROUP, subject: '7А класс', participants: [{ id: STUDENT }, { id: ADMIN, admin: 'admin' }] };
  wa.groups[OTHER_GROUP] = { id: OTHER_GROUP, subject: 'Футбол', participants: [{ id: STUDENT }] };
  const client = new FakeBilimClient(WEEKS);
  const homework = new HomeworkService({ client, store, config, now: TUESDAY_10AM });
  homework.today = () => '2025-10-14';
  const groq = new FakeGroq();
  const logger = { info() {}, warn() {}, error() {}, debug() {}, child() { return this; } };
  const core = new BotCore({ config, store, wa, logger });
  core.today = () => '2025-10-14';
  const assistant = new Assistant({ groq, homework, config, logger });
  const scheduler = new Scheduler({ config, store, homework, wa, core, logger });
  const commands = new Commands({ core, homework, wa, scheduler, config, logger });
  const handler = new MessageHandler({ config, core, wa, homework, assistant, commands, logger });
  return { config, store, wa, client, homework, groq, core, assistant, scheduler, commands, handler };
}

describe('распознавание команд', () => {
  it('команды с префиксами и алиасами', () => {
    assert.deepEqual(parseCommand('!дз завтра'), { name: 'homework', args: 'завтра' });
    assert.deepEqual(parseCommand('/ДЗ'), { name: 'homework', args: '' });
    assert.deepEqual(parseCommand('!Расписание пт'), { name: 'schedule', args: 'пт' });
    assert.deepEqual(parseCommand('!спросить как дела'), { name: 'ask', args: 'как дела' });
    assert.equal(parseCommand('дз завтра'), null);
    assert.equal(parseCommand('!неизвестно'), null);
  });
});

describe('эвристика вопросов', () => {
  it('отличает вопросы по учёбе от болтовни', () => {
    const subjects = ['Алгебра', 'Физика'];
    assert.equal(looksLikeStudyQuestion('что задали по алгебре', subjects), true);
    assert.equal(looksLikeStudyQuestion('как решить номер 245?', subjects), true);
    assert.equal(looksLikeStudyQuestion('не понимаю физику', subjects), true);
    assert.equal(looksLikeStudyQuestion('ертең үй тапсырма қандай?', subjects), true);
    assert.equal(looksLikeStudyQuestion('пойдём в кино?', subjects), false);
    assert.equal(looksLikeStudyQuestion('привет', subjects), false);
    assert.equal(looksLikeStudyQuestion('а я уже сделал дз', subjects), false);
  });
});

describe('обработка сообщений', () => {
  let t;
  beforeEach(() => { t = setup(); });

  it('!дз завтра отвечает заданием из дневника', async () => {
    await t.handler.handle(incoming({ chat: GROUP, text: '!дз завтра' }));
    assert.equal(t.wa.sent.length, 1);
    assert.match(t.wa.texts()[0], /ДЗ на завтра, среду, 15\.10/);
    assert.match(t.wa.texts()[0], /№ 250/);
    assert.ok(t.wa.sent[0].options.quoted, 'ответ цитирует вопрос');
  });

  it('!дз <предмет> ищет по предмету', async () => {
    await t.handler.handle(incoming({ chat: GROUP, text: '!дз литература' }));
    assert.match(t.wa.texts()[0], /Литература[\s\S]*Читать стр\. 40-55/);
  });

  it('вопрос по ДЗ в группе: классификатор → ответ ИИ с контекстом дневника', async () => {
    await t.handler.handle(incoming({ chat: GROUP, text: 'как решить номер 250 по алгебре?' }));
    assert.equal(t.groq.calls.length, 2);
    assert.equal(t.groq.calls[0].json, true, 'сначала классификатор');
    const system = t.groq.calls[1].messages[0].content;
    assert.match(system, /Алгебра: № 250/);
    assert.match(t.wa.texts()[0], /^\*Ответ:\* реши уравнение/);
    assert.equal(t.core.usage('ai'), 1);
  });

  it('классификатор сказал «не отвечать» — бот молчит', async () => {
    t.groq.classifierAnswer = '{"respond": false}';
    await t.handler.handle(incoming({ chat: GROUP, text: 'Аня, ты сделала алгебру?' }));
    assert.equal(t.wa.sent.length, 0);
  });

  it('болтовня не тратит запросы к ИИ', async () => {
    await t.handler.handle(incoming({ chat: GROUP, text: 'всем привет' }));
    assert.equal(t.groq.calls.length, 0);
    assert.equal(t.wa.sent.length, 0);
  });

  it('упоминание бота — ответ без классификатора', async () => {
    await t.handler.handle(incoming({ chat: GROUP, text: '@77000000000 привет, объясни дроби', contextInfo: { mentionedJid: ['77000000000@s.whatsapp.net'] } }));
    assert.equal(t.groq.calls.length, 1);
    assert.ok(!t.groq.calls[0].json, 'без классификатора');
    assert.equal(t.wa.sent.length, 1);
  });

  it('ответ на сообщение бота (LID) — тоже явное обращение', async () => {
    await t.handler.handle(incoming({
      chat: GROUP, text: 'а второй номер?',
      contextInfo: { stanzaId: 'X1', participant: '111111111111111@lid', quotedMessage: { conversation: 'ДЗ: № 250, 251' } },
    }));
    assert.equal(t.groq.calls.length, 1);
    assert.match(t.groq.calls[0].messages[1].content, /№ 250, 251/);
  });

  it('обращение «бот, ...» в начале сообщения', async () => {
    await t.handler.handle(incoming({ chat: GROUP, text: 'бот, что такое фотосинтез' }));
    assert.equal(t.groq.calls.length, 1);
    assert.match(t.groq.calls[0].messages[1].content, /что такое фотосинтез/);
  });

  it('режим mention: без явного обращения не отвечает', async () => {
    t = setup({ AI_MODE: 'mention' });
    await t.handler.handle(incoming({ chat: GROUP, text: 'как решить номер 250 по алгебре?' }));
    assert.equal(t.groq.calls.length, 0);
  });

  it('!автоответ выкл отключает автоответы, но !спросить работает', async () => {
    await t.handler.handle(incoming({ chat: GROUP, sender: ADMIN, text: '!автоответ выкл' }));
    t.wa.sent = [];
    await t.handler.handle(incoming({ chat: GROUP, text: 'как решить номер 250 по алгебре?' }));
    assert.equal(t.groq.calls.length, 0);
    await t.handler.handle(incoming({ chat: GROUP, text: '!спросить как решить номер 250?' }));
    assert.equal(t.groq.calls.length, 1);
  });

  it('чужая группа: игнор всего, кроме привязки', async () => {
    await t.handler.handle(incoming({ chat: OTHER_GROUP, text: 'как решить номер 250 по алгебре?' }));
    await t.handler.handle(incoming({ chat: OTHER_GROUP, text: '!дз' }));
    assert.equal(t.wa.sent.length, 0);
  });

  it('привязка группы — только админом', async () => {
    await t.handler.handle(incoming({ chat: OTHER_GROUP, sender: STUDENT, text: '!привязать' }));
    assert.match(t.wa.texts()[0], /только для админов/);
    assert.equal(t.core.isTarget(OTHER_GROUP), false);
    await t.handler.handle(incoming({ chat: OTHER_GROUP, sender: ADMIN, text: '!привязать' }));
    assert.equal(t.core.isTarget(OTHER_GROUP), true);
    assert.match(t.wa.texts()[1], /Группа «Футбол» привязана/);
  });

  it('админ группы WhatsApp считается админом бота', async () => {
    t = setup({ ADMIN_NUMBERS: '' });
    await t.handler.handle(incoming({ chat: GROUP, sender: ADMIN, text: '!статус' }));
    assert.match(t.wa.texts()[0], /Статус бота/);
  });

  it('старые и повторные сообщения не обрабатываются', async () => {
    await t.handler.handle(incoming({ chat: GROUP, text: '!дз', ageMs: 10 * 60 * 1000 }));
    const msg = incoming({ chat: GROUP, text: '!дз', id: 'SAME' });
    await t.handler.handle(msg);
    await t.handler.handle(msg);
    assert.equal(t.wa.sent.length, 1);
  });

  it('лимит вопросов на человека', async () => {
    t = setup({ AI_USER_LIMIT: '2' });
    for (let i = 0; i < 4; i += 1) {
      await t.handler.handle(incoming({ chat: GROUP, text: `бот, вопрос ${i}` }));
    }
    const answers = t.groq.calls.length;
    assert.equal(answers, 2);
    assert.match(t.wa.texts()[2], /Слишком много вопросов/);
    assert.equal(t.wa.sent.length, 3, 'предупреждение о лимите — один раз');
  });

  it('ИИ недоступен: при явном вопросе — вежливое сообщение', async () => {
    t.groq.fail = Object.assign(new Error('overloaded'), { status: 503 });
    await t.handler.handle(incoming({ chat: GROUP, text: 'бот, помоги' }));
    assert.match(t.wa.texts()[0], /временно недоступен/);
  });

  it('личка: участнику класса отвечает, постороннему — нет', async () => {
    await t.handler.handle(incoming({ chat: STUDENT, text: 'объясни теорему Пифагора' }));
    assert.equal(t.groq.calls.length, 1);
    await t.handler.handle(incoming({ chat: '79990000000@s.whatsapp.net', text: 'привет' }));
    assert.match(t.wa.texts().at(-1), /отвечаю только участникам/);
    assert.equal(t.groq.calls.length, 1);
  });

  it('команды владельца номера с телефона работают, остальные свои сообщения — игнор', async () => {
    const own = incoming({ chat: OTHER_GROUP, text: '!привязать' });
    own.key.fromMe = true;
    await t.handler.handle(own);
    assert.equal(t.core.isTarget(OTHER_GROUP), true);
    const chatter = incoming({ chat: GROUP, text: 'как решить номер 250 по алгебре?' });
    chatter.key.fromMe = true;
    await t.handler.handle(chatter);
    assert.equal(t.groq.calls.length, 0);
  });

  it('добавление и удаление ДЗ вручную', async () => {
    await t.handler.handle(incoming({ chat: GROUP, sender: ADMIN, text: '!добавить пт История: выучить даты' }));
    assert.match(t.wa.texts()[0], /Добавлено \(№1\): \*История\* на пятницу, 17\.10/);
    await t.handler.handle(incoming({ chat: GROUP, text: '!дз пт' }));
    assert.match(t.wa.texts()[1], /выучить даты/);
    await t.handler.handle(incoming({ chat: GROUP, sender: ADMIN, text: '!удалить 1' }));
    assert.equal(t.store.data.manual.length, 0);
  });
});

describe('планировщик', () => {
  it('рассылка в будний вечер — ДЗ на следующий учебный день', async () => {
    const t = setup();
    await t.scheduler.dailyDigest({ iso: '2025-10-14', minutes: 18 * 60, weekday: 2 });
    assert.equal(t.wa.sent.length, 1);
    assert.equal(t.wa.sent[0].jid, GROUP);
    assert.match(t.wa.texts()[0], /ДЗ на завтра, среду, 15\.10/);
  });

  it('в пятницу — ДЗ на понедельник, в субботу — тишина', async () => {
    const t = setup();
    t.homework.today = () => '2025-10-17';
    await t.scheduler.dailyDigest({ iso: '2025-10-17', minutes: 18 * 60, weekday: 5 });
    assert.match(t.wa.texts()[0], /на понедельник, 20\.10/);
    t.wa.sent = [];
    await t.scheduler.dailyDigest({ iso: '2025-10-18', minutes: 18 * 60, weekday: 6 });
    assert.equal(t.wa.sent.length, 0);
  });

  it('догоняет пропущенную рассылку, но не дважды', () => {
    const t = setup();
    const now = { iso: '2025-10-14', minutes: 18 * 60 + 40, weekday: 2 };
    assert.equal(t.scheduler.isDue('digest', 18 * 60, now), true);
    t.scheduler.jobDone('digest', '2025-10-14');
    assert.equal(t.scheduler.isDue('digest', 18 * 60, now), false);
    assert.equal(t.scheduler.isDue('digest', 18 * 60, { ...now, iso: '2025-10-15', minutes: 17 * 60 }), false);
    assert.equal(t.scheduler.isDue('digest', 18 * 60, { ...now, iso: '2025-10-15', minutes: 23 * 60 }), false, 'за окном догонялки');
  });

  it('новое ДЗ в дневнике → уведомление в группу', async () => {
    const t = setup();
    await t.scheduler.runPoll();
    assert.equal(t.wa.sent.length, 0, 'первая проверка молчит');
    t.client.weeks['2025-10-13'].days[3].subjects[0].homeworkBody = 'Параграф 5';
    t.homework.cache.clear();
    const result = await t.scheduler.runPoll();
    assert.deepEqual(result, { added: 1, changed: 0 });
    assert.match(t.wa.texts()[0], /🆕 \*История\* — на четверг, 16\.10\nПараграф 5/);
  });

  it('ошибки BilimClass: уведомление админу после нескольких сбоев', async () => {
    const t = setup();
    t.client.fail = new Error('ECONNRESET');
    for (let i = 0; i < 3; i += 1) await t.scheduler.runPoll();
    assert.ok(t.wa.sent.some((s) => s.jid === ADMIN && /BilimClass не отвечает/.test(s.content.text)));
  });
});

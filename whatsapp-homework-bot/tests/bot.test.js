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
  // по умолчанию в тестах — текстовый режим (проверять содержимое проще); фото проверяются отдельно
  const config = testConfig({ ADMIN_NUMBERS: '77015556677', WA_GROUP_IDS: GROUP, HOMEWORK_AS_IMAGE: 'false', ...env });
  const store = memoryStore();
  const wa = new FakeWA();
  wa.groups[GROUP] = { id: GROUP, subject: '7А класс', participants: [{ id: STUDENT }, { id: ADMIN, admin: 'admin' }] };
  wa.groups[OTHER_GROUP] = { id: OTHER_GROUP, subject: 'Футбол', participants: [{ id: STUDENT }] };
  const client = new FakeBilimClient(structuredClone(WEEKS)); // копия: тесты меняют дневник
  const homework = new HomeworkService({ client, store, config, now: TUESDAY_10AM });
  homework.today = () => '2025-10-14';
  const groq = new FakeGroq();
  const warnings = [];
  const logger = { info() {}, warn(...args) { warnings.push(args); }, error() {}, debug() {}, child() { return this; } };
  const core = new BotCore({ config, store, wa, logger });
  core.today = () => '2025-10-14';
  const assistant = new Assistant({ groq, homework, config, logger });
  const scheduler = new Scheduler({ config, store, homework, wa, core, logger });
  const commands = new Commands({ core, homework, wa, scheduler, config, logger });
  const handler = new MessageHandler({ config, core, wa, homework, assistant, commands, logger });
  return { config, store, wa, client, homework, groq, core, assistant, scheduler, commands, handler, warnings };
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
  // «сейчас» для планировщика
  const at = (iso, hh, mm = 0) => ({ iso, minutes: hh * 60 + mm, weekday: ((new Date(`${iso}T00:00:00Z`).getUTCDay() + 6) % 7) + 1 });

  it('время рассылки — через 15 минут после последнего урока', async () => {
    const t = setup();
    // вторник: один урок 08:00–08:45 → рассылка в 09:00
    let plan = await t.scheduler.digestPlan(at('2025-10-14', 7));
    assert.equal(plan.source, 'lessons');
    assert.equal(plan.lessonsEnd, 8 * 60 + 45);
    assert.equal(plan.at, 9 * 60);
    // среда: два урока, последний до 09:45 → 10:00
    plan = await t.scheduler.digestPlan(at('2025-10-15', 7));
    assert.equal(plan.at, 10 * 60);
    // воскресенье: уроков нет → DIGEST_TIME (18:00)
    plan = await t.scheduler.digestPlan(at('2025-10-19', 7));
    assert.equal(plan.source, 'fallback');
    assert.equal(plan.at, 18 * 60);
  });

  it('режим fixed и своя задержка после уроков', async () => {
    let t = setup({ DIGEST_MODE: 'fixed', DIGEST_TIME: '19:30' });
    assert.equal((await t.scheduler.digestPlan(at('2025-10-14', 7))).at, 19 * 60 + 30);
    t = setup({ DIGEST_DELAY_MINUTES: '0' });
    assert.equal((await t.scheduler.digestPlan(at('2025-10-14', 7))).at, 8 * 60 + 45);
  });

  it('BilimClass недоступен — рассылка по запасному времени, план пересчитается позже', async () => {
    const t = setup();
    t.client.fail = new Error('down');
    const plan = await t.scheduler.digestPlan(at('2025-10-14', 7));
    assert.equal(plan.source, 'error');
    assert.equal(plan.at, 18 * 60);
  });

  it('первая рассылка — ДЗ на каждый день недели вперёд', async () => {
    const t = setup();
    await t.scheduler.sendDigest({ targets: [GROUP] });
    const text = t.wa.texts()[0];
    assert.match(text, /Домашнее задание на неделю вперёд/);
    assert.match(text, /Завтра \(среда, 15\.10\)[\s\S]*№ 250[\s\S]*Упр\. 5/);
    assert.match(text, /Послезавтра \(четверг, 16\.10\)\* ━━\nДЗ пока нет/);
    assert.match(text, /Пятница, 17\.10[\s\S]*Читать стр\. 40-55/);
    assert.match(text, /Понедельник, 20\.10[\s\S]*№ 300/);
    assert.ok(!/№ 1\b/.test(text), 'прошедшие дни не показываются');
  });

  it('дальше — только новые ДЗ, без повторов старых + напоминание на завтра', async () => {
    const t = setup();
    await t.scheduler.sendDigest({ targets: [GROUP] });

    // ничего не поменялось
    await t.scheduler.sendDigest({ targets: [GROUP] });
    let text = t.wa.texts()[1];
    assert.match(text, /Новых заданий в дневнике с прошлой проверки нет/);
    assert.match(text, /📌 \*Не забудьте на завтра, среду, 15\.10:\*\n• \*Алгебра:\* № 250\n• \*Русский язык:\* Упр\. 5/);

    // учитель выставил ДЗ по истории и изменил русский
    t.client.weeks['2025-10-13'].days[3].subjects[0].homeworkBody = 'Параграф 5';
    t.client.weeks['2025-10-13'].days[2].subjects[1].homeworkBody = 'Упр. 6';
    await t.scheduler.sendDigest({ targets: [GROUP] });
    text = t.wa.texts()[2];
    assert.match(text, /🆕 \*Новые и изменённые задания \(2\):\*/);
    assert.match(text, /\*Русский язык\* — на завтра, среду, 15\.10 ✏️ _изменено_\nУпр\. 6/);
    assert.match(text, /\*История\* — на четверг, 16\.10\nПараграф 5/);
    assert.match(text, /Не забудьте на завтра, среду, 15\.10:\*\n• \*Алгебра:\* № 250\n\n/);
    assert.ok(!text.includes('Читать стр. 40-55'), 'старое ДЗ не повторяется');
  });

  it('данные для рассылки всегда берутся заново из BilimClass', async () => {
    const t = setup();
    await t.scheduler.sendDigest({ targets: [GROUP] });
    const calls = t.client.calls.length;
    await t.scheduler.sendDigest({ targets: [GROUP] });
    assert.ok(t.client.calls.length > calls, 'второй раз тоже идёт запрос в дневник');
    t.client.fail = new Error('BilimClass down');
    await assert.rejects(() => t.scheduler.sendDigest({ targets: [GROUP] }), /down/);
    assert.equal(t.wa.sent.length, 2, 'при ошибке устаревшие данные не отправляются');
  });

  it('в учебный день — после уроков, в субботу — тишина, в воскресенье — на понедельник', async () => {
    const t = setup();
    t.store.data.announcedReady = true;
    t.homework.today = () => '2025-10-17';
    await t.scheduler.dailyDigest(at('2025-10-17', 13));
    assert.match(t.wa.texts()[0], /на понедельник, 20\.10/);
    t.wa.sent = [];
    await t.scheduler.dailyDigest(at('2025-10-18', 18));
    assert.equal(t.wa.sent.length, 0);
    t.homework.today = () => '2025-10-19';
    await t.scheduler.dailyDigest(at('2025-10-19', 18));
    assert.equal(t.wa.sent.length, 1);
  });

  it('полный цикл: до конца уроков молчит, после — сам присылает ДЗ один раз', async () => {
    const t = setup();
    t.scheduler.clock = () => at('2025-10-14', 8, 30); // уроки до 08:45 → рассылка в 09:00
    await t.scheduler.tick();
    assert.equal(t.wa.sent.length, 0);
    t.scheduler.clock = () => at('2025-10-14', 9, 1);
    await t.scheduler.tick();
    assert.equal(t.wa.sent.length, 1);
    assert.match(t.wa.texts()[0], /Домашнее задание на неделю вперёд/);
    assert.equal(t.store.data.jobs.digest, '2025-10-14');
    t.scheduler.clock = () => at('2025-10-14', 9, 30);
    await t.scheduler.tick();
    assert.equal(t.wa.sent.length, 1, 'второй раз в тот же день не шлёт');
  });

  it('бот запустили днём, когда уроки давно закончились — рассылка всё равно уходит (до 22:00)', async () => {
    const t = setup();
    t.scheduler.clock = () => at('2025-10-14', 16); // уроки закончились в 08:45
    await t.scheduler.tick();
    assert.equal(t.wa.sent.length, 1);
    const late = setup();
    late.scheduler.clock = () => at('2025-10-14', 22, 30);
    await late.scheduler.tick();
    assert.equal(late.wa.sent.length, 0, 'ночью не шлём');
  });

  it('догоняет пропущенную рассылку, но не дважды', () => {
    const t = setup();
    const now = at('2025-10-14', 18, 40);
    assert.equal(t.scheduler.isDue('digest', 18 * 60, now), true);
    t.scheduler.jobDone('digest', '2025-10-14');
    assert.equal(t.scheduler.isDue('digest', 18 * 60, now), false);
    assert.equal(t.scheduler.isDue('digest', 18 * 60, at('2025-10-15', 17)), false);
    assert.equal(t.scheduler.isDue('digest', 18 * 60, at('2025-10-15', 23)), false, 'за окном догонялки');
  });

  it('днём новые ДЗ копятся до рассылки после уроков, срочные (на сегодня) — сразу', async () => {
    const t = setup();
    t.store.data.announcedReady = true;
    t.scheduler.clock = () => at('2025-10-14', 8, 30);
    await t.scheduler.digestPlan(at('2025-10-14', 8, 30)); // рассылка в 09:00
    await t.scheduler.runPoll(); // первая проверка — запоминает
    t.client.weeks['2025-10-13'].days[3].subjects[0].homeworkBody = 'Параграф 5'; // на четверг
    t.client.weeks['2025-10-13'].days[1].subjects[0].homeworkBody = '§ 12, 13'; // на сегодня
    await t.scheduler.runPoll();
    assert.equal(t.wa.sent.length, 1);
    assert.match(t.wa.texts()[0], /Физика/);
    assert.ok(!t.wa.texts()[0].includes('История'), 'не срочное ждёт рассылки');

    // рассылка после уроков содержит накопленное
    t.scheduler.clock = () => at('2025-10-14', 9, 5);
    await t.scheduler.sendDigest({ targets: [GROUP] });
    t.scheduler.jobDone('digest', '2025-10-14');
    assert.match(t.wa.texts()[1], /🆕[\s\S]*\*История\* — на четверг, 16\.10\nПараграф 5/);
  });

  it('после рассылки новое ДЗ приходит сразу и не повторяется в следующей рассылке', async () => {
    const t = setup();
    t.scheduler.clock = () => at('2025-10-14', 15);
    await t.scheduler.digestPlan(at('2025-10-14', 15));
    await t.scheduler.sendDigest({ targets: [GROUP] });
    t.scheduler.jobDone('digest', '2025-10-14');
    await t.scheduler.runPoll(); // базовый снимок
    t.client.weeks['2025-10-13'].days[3].subjects[0].homeworkBody = 'Параграф 5';
    const result = await t.scheduler.runPoll();
    assert.deepEqual(result, { added: 1, changed: 0 });
    assert.match(t.wa.texts()[1], /🆕 \*История\* — на четверг, 16\.10\nПараграф 5/);
    await t.scheduler.sendDigest({ targets: [GROUP] });
    assert.match(t.wa.texts()[2], /Новых заданий в дневнике с прошлой проверки нет/);
  });

  it('!обновить сообщает изменения сразу, даже до рассылки', async () => {
    const t = setup();
    t.scheduler.clock = () => at('2025-10-14', 8);
    await t.scheduler.digestPlan(at('2025-10-14', 8));
    await t.scheduler.runPoll();
    t.client.weeks['2025-10-13'].days[3].subjects[0].homeworkBody = 'Параграф 5';
    const result = await t.scheduler.runPoll({ manual: true });
    assert.deepEqual(result, { added: 1, changed: 0 });
    assert.match(t.wa.texts()[0], /История/);
  });

  it('ошибки BilimClass: уведомление админу после нескольких сбоев', async () => {
    const t = setup();
    t.client.fail = new Error('ECONNRESET');
    for (let i = 0; i < 3; i += 1) await t.scheduler.runPoll();
    assert.ok(t.wa.sent.some((s) => s.jid === ADMIN && /BilimClass не отвечает/.test(s.content.text)));
  });
});

describe('ДЗ фотографией', () => {
  const at = (iso, hh, mm = 0) => ({ iso, minutes: hh * 60 + mm, weekday: ((new Date(`${iso}T00:00:00Z`).getUTCDay() + 6) % 7) + 1 });
  const photo = (t) => setup({ HOMEWORK_AS_IMAGE: 'true', ...t });
  const isJpeg = (buf) => Buffer.isBuffer(buf) && buf[0] === 0xff && buf[1] === 0xd8;
  const captions = (wa) => wa.sent.map((s) => s.content.caption || s.content.text);

  it('!дз завтра — фото с подписью «Домашнее задание на завтра»', async () => {
    const t = photo();
    await t.handler.handle(incoming({ chat: GROUP, text: '!дз завтра' }));
    const [msg] = t.wa.sent;
    assert.ok(isJpeg(msg.content.image));
    assert.equal(msg.content.caption, '📚 Домашнее задание на завтра');
    assert.ok(msg.options.quoted, 'ответ на сообщение с командой');
  });

  it('день без ДЗ — короткий текст вместо пустой картинки', async () => {
    const t = photo();
    await t.handler.handle(incoming({ chat: GROUP, text: '!дз чт' }));
    assert.equal(t.wa.texts()[0], '📚 Домашнего задания на четверг, 16.10 в дневнике нет 🎉');
  });

  it('первая рассылка — по фото на каждый день с ДЗ', async () => {
    const t = photo();
    await t.scheduler.sendDigest({ targets: [GROUP] });
    assert.deepEqual(captions(t.wa), [
      '📚 Домашнее задание на завтра',
      '📚 Домашнее задание на пятницу, 17.10',
      '📚 Домашнее задание на понедельник, 20.10',
    ]);
    assert.ok(t.wa.sent.every((s) => isJpeg(s.content.image)));
  });

  it('дальше: фото на завтра + фото дней, где появилось новое ДЗ', async () => {
    const t = photo();
    await t.scheduler.sendDigest({ targets: [GROUP] });
    t.wa.sent = [];
    // ничего нового — только напоминание на завтра
    await t.scheduler.sendDigest({ targets: [GROUP] });
    assert.deepEqual(captions(t.wa), ['📚 Домашнее задание на завтра']);
    t.wa.sent = [];
    // учитель выставил ДЗ на четверг и изменил на пятницу
    t.client.weeks['2025-10-13'].days[3].subjects[0].homeworkBody = 'Параграф 5';
    t.client.weeks['2025-10-13'].days[4].subjects[0].homeworkBody = 'Читать стр. 40-60';
    await t.scheduler.sendDigest({ targets: [GROUP] });
    assert.deepEqual(captions(t.wa), [
      '📚 Домашнее задание на завтра',
      '🆕 Новое домашнее задание на четверг, 16.10',
      '✏️ Изменилось домашнее задание на пятницу, 17.10',
    ]);
  });

  it('без напоминания на завтра и без нового — короткий текст', async () => {
    const t = photo({ DIGEST_REMIND_TOMORROW: 'false' });
    await t.scheduler.sendDigest({ targets: [GROUP] });
    t.wa.sent = [];
    await t.scheduler.sendDigest({ targets: [GROUP] });
    assert.deepEqual(captions(t.wa), ['✅ Проверил дневник после уроков — новых домашних заданий нет.']);
  });

  it('новое ДЗ вечером — фото дня с подписью «Новое домашнее задание»', async () => {
    const t = photo();
    t.scheduler.clock = () => at('2025-10-14', 15);
    await t.scheduler.digestPlan(at('2025-10-14', 15));
    await t.scheduler.sendDigest({ targets: [GROUP] });
    t.scheduler.jobDone('digest', '2025-10-14');
    await t.scheduler.runPoll();
    t.wa.sent = [];
    t.client.weeks['2025-10-13'].days[3].subjects[0].homeworkBody = 'Параграф 5';
    await t.scheduler.runPoll();
    assert.deepEqual(captions(t.wa), ['🆕 Новое домашнее задание на четверг, 16.10']);
    assert.ok(isJpeg(t.wa.sent[0].content.image));
  });

  it('вопрос ответом на фото с ДЗ от бота — картинку не скачиваем, ИИ берёт ДЗ из дневника', async () => {
    const t = photo();
    await t.handler.handle(incoming({
      chat: GROUP, text: 'как решить алгебру?',
      contextInfo: { stanzaId: 'BOTPHOTO', participant: '77000000000@s.whatsapp.net', quotedMessage: { imageMessage: { caption: '📚 Домашнее задание на завтра', mimetype: 'image/jpeg' } } },
    }));
    assert.equal(t.groq.calls.length, 1);
    assert.equal(typeof t.groq.calls[0].messages[1].content, 'string', 'без картинки — текстовый запрос');
    assert.match(t.groq.calls[0].messages[1].content, /Домашнее задание на завтра/);
    assert.ok(!t.warnings.some((w) => String(w[1]).includes('фото')), 'попытки скачать фото не было');
  });
});

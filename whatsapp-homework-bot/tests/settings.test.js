import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, it } from 'node:test';
import { buildConfig } from '../src/config.js';
import { describeDay, isPaused, quietReason, Settings } from '../src/settings.js';
import { parseWeekdays } from '../src/whatsapp/commands.js';
import { incoming } from './helpers.js';
import { ADMIN, GROUP, setup } from './setup.js';

const at = (iso, hh, mm = 0) => ({ iso, minutes: hh * 60 + mm, weekday: ((new Date(`${iso}T00:00:00Z`).getUTCDay() + 6) % 7) + 1 });
const tmpFile = () => path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'hwbot-settings-')), 'settings.json');

describe('настройки на ходу', () => {
  it('меняются, сохраняются в файл и переживают перезапуск', () => {
    const file = tmpFile();
    const config = buildConfig({});
    const settings = new Settings({ config, file }).load();
    const events = [];
    settings.on('change', (paths) => events.push(paths));
    settings.update({ 'ai.botName': 'Алия', 'schedule.digestDelayMinutes': '25', 'features.homeworkPhoto': 'text' });
    assert.equal(config.ai.botName, 'Алия');
    assert.equal(config.schedule.digestDelayMinutes, 25);
    assert.equal(config.features.homeworkImage, false, 'производная настройка обновилась');
    assert.deepEqual(events, [['ai.botName', 'schedule.digestDelayMinutes', 'features.homeworkPhoto']]);

    const again = buildConfig({});
    new Settings({ config: again, file }).load();
    assert.equal(again.ai.botName, 'Алия');
    assert.equal(again.schedule.digestDelayMinutes, 25);
  });

  it('неверное значение — понятная ошибка и ничего не меняется', () => {
    const config = buildConfig({});
    const settings = new Settings({ config, file: null });
    assert.throws(() => settings.update({ 'ai.botName': 'Бот', 'schedule.digestDelayMinutes': '9999' }), /после уроков: ожидается целое число/);
    assert.equal(config.ai.botName, 'Помощник', 'частичных изменений нет');
    assert.throws(() => settings.update({ 'groq.apiKey': 'x' }), /неизвестная настройка/);
    assert.throws(() => settings.update({ 'schedule.days': { 1: { mode: 'time' } } }), /Пн: укажите время|режим/);
  });

  it('сброс к значениям из .env', () => {
    const config = buildConfig({ BOT_NAME: 'Бот 7А' });
    const settings = new Settings({ config, file: null });
    settings.update({ 'ai.botName': 'Другой' });
    settings.reset(['ai.botName']);
    assert.equal(config.ai.botName, 'Бот 7А');
    const row = settings.describe().find((f) => f.path === 'ai.botName');
    assert.equal(row.overridden, false);
    assert.equal(settings.describe().find((f) => f.path === 'schedule.activeHours').value, '07:00-22:00');
  });

  it('описание дня и тихие дни', () => {
    assert.equal(describeDay(7, { mode: 'time', time: 18 * 60, scope: 'tomorrow' }), 'Вс: в 18:00, только на завтра');
    assert.equal(describeDay(1, { mode: 'lessons', time: null, scope: 'new' }, { delay: 15 }), 'Пн: после уроков (+15 мин)');
    assert.equal(describeDay(6, { mode: 'off' }), 'Сб: не присылать');
    const schedule = { days: { 1: { mode: 'off' } }, skipDates: ['2025-10-15'], pausedUntil: null };
    assert.equal(quietReason(schedule, '2025-10-13', 1), 'в этот день недели рассылка выключена');
    assert.equal(quietReason(schedule, '2025-10-15', 3), 'сегодня рассылка пропущена');
    assert.equal(isPaused({ pausedUntil: '2025-10-16' }, '2025-10-16'), true);
    assert.equal(isPaused({ pausedUntil: '2025-10-16' }, '2025-10-17'), false);
    assert.deepEqual(parseWeekdays('будни'), [1, 2, 3, 4, 5]);
    assert.deepEqual(parseWeekdays('пн,ср,пт'), [1, 3, 5]);
    assert.equal(parseWeekdays('завтра'), null);
  });
});

describe('рассылка по дням недели', () => {
  it('выключенный день: рассылки нет, проверки дневника молчат, новое приходит позже', async () => {
    const t = setup();
    t.settings.setDay([2], { mode: 'off' }); // вторник
    t.store.data.announcedReady = true;
    const plan = await t.scheduler.digestPlan(at('2025-10-14', 15));
    assert.equal(plan.at, null);
    assert.equal(plan.quiet, 'в этот день недели рассылка выключена');

    t.scheduler.clock = () => at('2025-10-14', 15);
    await t.scheduler.runPoll(); // базовый снимок
    t.client.weeks['2025-10-13'].days[3].subjects[0].homeworkBody = 'Параграф 5';
    await t.scheduler.runPoll();
    assert.equal(t.wa.sent.length, 0, 'в выключенный день бот молчит');

    // в среду новое ДЗ придёт в рассылке
    t.homework.today = () => '2025-10-15';
    t.scheduler.clock = () => at('2025-10-15', 15);
    await t.scheduler.sendDigest({ targets: [GROUP] });
    assert.match(t.wa.texts()[0], /\*История\* — на завтра, четверг, 16\.10/);
  });

  it('«только на завтра»: ДЗ на дальние дни не вываливаются', async () => {
    const t = setup();
    t.store.data.announcedReady = true; // уже не первая рассылка: всё в дневнике — «новое»
    await t.scheduler.sendDigest({ targets: [GROUP], scope: 'tomorrow' });
    const text = t.wa.texts()[0];
    assert.match(text, /\*Алгебра\* — на завтра/);
    assert.ok(!/стр\. 40-55|№ 300/.test(text), 'пятница и понедельник не показаны');
    // показанное запомнено, остальное придёт потом как новое
    await t.scheduler.sendDigest({ targets: [GROUP] });
    assert.match(t.wa.texts()[1], /Литература[\s\S]*Алгебра\* — на понедельник/);
    assert.ok(!/\*Алгебра\* — на завтра/.test(t.wa.texts()[1]), 'уже показанное не повторяется как новое');
    assert.match(t.wa.texts()[1], /📌 \*Не забудьте на завтра[\s\S]*№ 250/, 'а в напоминании на завтра — есть');
  });

  it('воскресенье по умолчанию — только ДЗ на понедельник', async () => {
    const t = setup({ HOMEWORK_AS_IMAGE: 'true' });
    t.store.data.announcedReady = true;
    t.homework.today = () => '2025-10-19';
    const now = at('2025-10-19', 18, 5);
    t.scheduler.clock = () => now;
    await t.scheduler.digestPlan(now);
    await t.scheduler.dailyDigest(now);
    const captions = t.wa.sent.map((s) => s.content.caption || s.content.text);
    assert.deepEqual(captions, ['📚 Домашнее задание на завтра']);
  });

  it('пауза и пропуск дня: тишина, но !обновить вручную работает', async () => {
    const t = setup();
    t.settings.pause('2025-10-15');
    assert.equal((await t.scheduler.digestPlan(at('2025-10-14', 15))).quiet, 'рассылки на паузе до 2025-10-15');
    assert.equal((await t.scheduler.digestPlan(at('2025-10-16', 15))).quiet, null, 'после паузы — как обычно');
    t.settings.resume();
    t.settings.skipDate('2025-10-14');
    assert.equal((await t.scheduler.digestPlan(at('2025-10-14', 15))).quiet, 'сегодня рассылка пропущена');

    t.scheduler.clock = () => at('2025-10-14', 15);
    await t.scheduler.runPoll();
    t.client.weeks['2025-10-13'].days[3].subjects[0].homeworkBody = 'Параграф 5';
    const result = await t.scheduler.runPoll({ manual: true });
    assert.equal(result.added, 1);
    assert.match(t.wa.texts()[0], /История/);
  });

  it('полный цикл тика: в выключенный день ничего не уходит', async () => {
    const t = setup();
    t.settings.setDay([2], { mode: 'off' });
    t.scheduler.clock = () => at('2025-10-14', 16);
    await t.scheduler.tick();
    assert.equal(t.wa.sent.length, 0);
    t.settings.setDay([2], { mode: 'time', time: 16 * 60 });
    await t.scheduler.tick();
    assert.equal(t.wa.sent.length, 1, 'после изменения настроек план пересчитался сразу');
  });
});

describe('после «тихого» дня ничего не теряется', () => {
  it('ДЗ, выставленное в пропущенный день, приходит утром следующего дня', async () => {
    const t = setup();
    t.store.data.announcedReady = true;
    t.settings.skipDate('2025-10-15'); // среда без рассылки
    t.homework.today = () => '2025-10-15';
    t.scheduler.clock = () => at('2025-10-15', 10);
    await t.scheduler.runPoll(); // базовый снимок
    t.client.weeks['2025-10-13'].days[3].subjects[0].homeworkBody = 'Параграф 5'; // на четверг
    await t.scheduler.runPoll();
    assert.equal(t.wa.sent.length, 0, 'в пропущенный день — тишина');
    // четверг, утро: рассылка после уроков ещё впереди — срочное ДЗ на сегодня приходит сразу
    t.homework.today = () => '2025-10-16';
    t.scheduler.clock = () => at('2025-10-16', 7, 30);
    await t.scheduler.digestPlan(at('2025-10-16', 7, 30));
    await t.scheduler.runPoll();
    assert.equal(t.wa.sent.length, 1);
    assert.match(t.wa.texts()[0], /История[\s\S]*Параграф 5/);
    await t.scheduler.runPoll();
    assert.equal(t.wa.sent.length, 1, 'второй раз не шлёт');
  });

  it('закончившаяся пауза и прошедшие пропуски убираются сами', () => {
    const t = setup();
    t.settings.update({ 'schedule.pausedUntil': '2025-10-13', 'schedule.skipDates': ['2025-10-10', '2025-10-20'] });
    t.scheduler.cleanupSchedule(at('2025-10-14', 9));
    assert.equal(t.config.schedule.pausedUntil, null);
    assert.deepEqual(t.config.schedule.skipDates, ['2025-10-20']);
  });

  it('предпросмотр и «разослать сейчас» используют график дня', () => {
    const t = setup();
    t.scheduler.clock = () => at('2025-10-19', 12);
    assert.equal(t.scheduler.todayScope(), 'tomorrow');
    t.scheduler.clock = () => at('2025-10-14', 12);
    assert.equal(t.scheduler.todayScope(), 'new');
  });
});

describe('команды графика', () => {
  it('!график, !график вс выкл, !график пт 15:00', async () => {
    const t = setup();
    await t.handler.handle(incoming({ chat: GROUP, sender: ADMIN, text: '!график' }));
    assert.match(t.wa.texts()[0], /Пн: после уроков \(\+15 мин\)[\s\S]*Вс: в 18:00, только на завтра/);
    await t.handler.handle(incoming({ chat: GROUP, sender: ADMIN, text: '!график вс выкл' }));
    assert.equal(t.config.schedule.days[7].mode, 'off');
    await t.handler.handle(incoming({ chat: GROUP, sender: ADMIN, text: '!график пт 15:00' }));
    assert.deepEqual(t.config.schedule.days[5], { mode: 'time', time: 15 * 60, scope: 'new' });
    await t.handler.handle(incoming({ chat: GROUP, sender: ADMIN, text: '!график будни только завтра' }));
    assert.equal(t.config.schedule.days[3].scope, 'tomorrow');
    assert.match(t.wa.texts().at(-1), /Ср: после уроков \(\+15 мин\), без уроков — 18:00, только на завтра/);
  });

  it('!пауза 3, !продолжить, !пропустить завтра', async () => {
    const t = setup();
    await t.handler.handle(incoming({ chat: GROUP, sender: ADMIN, text: '!пауза 3' }));
    assert.equal(t.config.schedule.pausedUntil, '2025-10-16');
    assert.match(t.wa.texts()[0], /на паузе по 16\.10 включительно/);
    await t.handler.handle(incoming({ chat: GROUP, sender: ADMIN, text: '!продолжить' }));
    assert.equal(t.config.schedule.pausedUntil, null);
    await t.handler.handle(incoming({ chat: GROUP, sender: ADMIN, text: '!пропустить завтра' }));
    assert.deepEqual(t.config.schedule.skipDates, ['2025-10-15']);
    await t.handler.handle(incoming({ chat: GROUP, sender: ADMIN, text: '!пропустить завтра' }));
    assert.deepEqual(t.config.schedule.skipDates, [], 'повтор отменяет пропуск');
  });

  it('!панель — только номерам из ADMIN_NUMBERS, не админам группы', async () => {
    const t = setup();
    t.commands.panel = { oneTimeLink: () => 'http://localhost:3000/auth/link?t=SECRET' };
    const groupAdmin = '77019998877@s.whatsapp.net';
    t.wa.groups[GROUP].participants.push({ id: groupAdmin, admin: 'admin' });
    await t.handler.handle(incoming({ chat: groupAdmin, text: '!панель' }));
    assert.match(t.wa.texts().at(-1), /только для номеров из ADMIN_NUMBERS/);
    assert.ok(!t.wa.texts().some((x) => x.includes('SECRET')));
    await t.handler.handle(incoming({ chat: ADMIN, text: '!панель' }));
    assert.match(t.wa.texts().at(-1), /SECRET/);
  });

  it('слово-обращение со спецсимволами не ломает ответы', async () => {
    const t = setup();
    t.settings.update({ 'ai.wakeWords': '(ии, бот' });
    await t.handler.handle(incoming({ chat: GROUP, text: 'бот, как решить номер 250?' }));
    assert.equal(t.groq.calls.filter((c) => !c.json).length, 1);
  });

  it('ученикам команды графика недоступны', async () => {
    const t = setup();
    await t.handler.handle(incoming({ chat: GROUP, text: '!пауза' }));
    assert.match(t.wa.texts()[0], /только для админов/);
    assert.equal(t.config.schedule.pausedUntil, null);
  });
});

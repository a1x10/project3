import assert from 'node:assert/strict';
import fs from 'node:fs';
import { describe, it } from 'node:test';
import { formatBooks, homeworkEntries, normalizeWeek } from '../src/bilimclass/parse.js';
import { formatChanges, formatDay, formatSchedule, formatSubject, formatWeek } from '../src/homework/format.js';
import { HomeworkService } from '../src/homework/service.js';
import { findSubjects, subjectScore } from '../src/homework/subjects.js';
import { FakeBilimClient, memoryStore, rawWeek, testConfig, TUESDAY_10AM } from './helpers.js';

const fixture = JSON.parse(fs.readFileSync(new URL('./fixtures/week.json', import.meta.url), 'utf8'));

function makeService({ weeks, env = {}, now = TUESDAY_10AM } = {}) {
  const client = new FakeBilimClient(weeks);
  const store = memoryStore();
  const service = new HomeworkService({ client, store, config: testConfig(env), now });
  return { client, store, service };
}

// Неделя 13–19.10.2025: пн–пт уроки, сб/вс пусто
const WEEK1 = rawWeek('2025-10-13', {
  1: [['Алгебра', '№ 1'], ['Физкультура', null]],
  2: [['Физика', '§ 12'], ['Русский язык', 'Упр. 112']],
  3: [['Алгебра', '№ 250'], ['Английский язык', null, { homeworkBooks: [{ name: 'Excel 7', pages: '34' }] }]],
  4: [['История', null]],
  5: [['Алгебра', null], ['Литература', 'Читать стр. 40-55']],
});
const WEEK2 = rawWeek('2025-10-20', {
  1: [['Алгебра', '№ 300'], ['Физика', null]],
  2: [['Физика', '§ 13']],
  3: [['Алгебра', null]],
  4: [['История', null]],
  5: [['Алгебра', null]],
});

describe('разбор дневника', () => {
  it('нормализует неделю из фикстуры', () => {
    const days = normalizeWeek(fixture, '2025-10-13');
    assert.equal(days.length, 7);
    assert.equal(days[0].date, '2025-10-13');
    assert.equal(days[0].lessons[0].subject, 'Алгебра');
    assert.equal(days[0].lessons[0].start, '08:00');
    assert.equal(days[0].lessons[0].homework.text, '№ 245, 247\nПовторить «формулы»');
    assert.equal(days[0].lessons[2].homework, null);
    assert.equal(days[4].isHoliday, true);
  });

  it('дублирующееся ДЗ сдвоенного урока показывается один раз', () => {
    const days = normalizeWeek(fixture, '2025-10-13');
    const entries = homeworkEntries(days[1]);
    assert.equal(entries.length, 2);
    assert.deepEqual(entries.map((e) => e.key), ['Физика#1', 'Английский язык#1']);
    assert.deepEqual(entries[1].books, ['Excel 7, стр. 34, упр. 2, 3']);
  });

  it('задания из учебника в разных форматах', () => {
    assert.deepEqual(formatBooks(['стр. 5']), ['стр. 5']);
    assert.deepEqual(formatBooks({ title: 'Алгебра 7', paragraph: '12', tasks: [1, 2] }), ['Алгебра 7, § 12, № 1, 2']);
    assert.deepEqual(formatBooks([{ unknown: 1 }]), ['задание в учебнике (подробности в BilimClass)']);
    assert.deepEqual(formatBooks(null), []);
  });

  it('дата дня без названия месяца берётся по порядку', () => {
    const days = normalizeWeek({ days: [{ date: null, subjects: [] }, { date: '???', subjects: [] }] }, '2025-10-13');
    assert.deepEqual(days.map((d) => d.date), ['2025-10-13', '2025-10-14']);
  });
});

describe('предметы', () => {
  it('нечёткий поиск', () => {
    const subjects = ['Алгебра', 'Английский язык', 'Физическая культура', 'Физика', 'Русский язык', 'Казахский язык и литература'];
    assert.deepEqual(findSubjects('алгебре', subjects), ['Алгебра']);
    assert.deepEqual(findSubjects('англ', subjects), ['Английский язык']);
    assert.deepEqual(findSubjects('физра', subjects), ['Физическая культура']);
    assert.deepEqual(findSubjects('физика', subjects), ['Физика']);
    assert.deepEqual(findSubjects('каз', subjects), ['Казахский язык и литература']);
    assert.deepEqual(findSubjects('химия', subjects), []);
    assert.ok(subjectScore('русский', 'Русский язык') > 0);
  });
});

describe('HomeworkService', () => {
  it('ДЗ на день и ближайший учебный день (пропускает выходные)', async () => {
    const { service } = makeService({ weeks: { '2025-10-13': WEEK1, '2025-10-20': WEEK2 } });
    const view = await service.dayView('2025-10-15');
    assert.deepEqual(view.entries.map((e) => e.subject), ['Алгебра', 'Английский язык']);
    assert.equal(await service.nextSchoolDay('2025-10-14'), '2025-10-15');
    assert.equal(await service.nextSchoolDay('2025-10-17'), '2025-10-20');
    assert.equal(await service.isSchoolDay('2025-10-18'), false);
  });

  it('каникулы: учебных дней нет', async () => {
    const { service } = makeService({ weeks: {} });
    assert.equal(await service.nextSchoolDay('2025-10-14'), null);
  });

  it('кэширует недели', async () => {
    const { service, client } = makeService({ weeks: { '2025-10-13': WEEK1 } });
    await service.dayView('2025-10-15');
    await service.dayView('2025-10-16');
    assert.equal(client.calls.filter((m) => m === '2025-10-13').length, 1);
  });

  it('режим assigned: срок ДЗ — следующий урок по предмету', async () => {
    const { service } = makeService({ weeks: { '2025-10-13': WEEK1, '2025-10-20': WEEK2 }, env: { HOMEWORK_ATTACHED_TO: 'assigned' } });
    // ДЗ по алгебре с урока в среду 15.10 нужно сдать к пятнице 17.10
    const friday = await service.dayView('2025-10-17');
    assert.ok(friday.entries.some((e) => e.subject === 'Алгебра' && e.text === '№ 250'));
    // ДЗ по физике со вторника 14.10 — к понедельнику 20.10
    const monday = await service.dayView('2025-10-20');
    assert.ok(monday.entries.some((e) => e.subject === 'Физика' && e.text === '§ 12'));
  });

  it('поиск ДЗ по предмету', async () => {
    const { service } = makeService({ weeks: { '2025-10-13': WEEK1, '2025-10-20': WEEK2 } });
    const result = await service.findSubject('алгебре');
    assert.deepEqual(result.subjects, ['Алгебра']);
    assert.equal(result.upcoming[0].dueDate, '2025-10-15');
    assert.equal(result.last.dueDate, '2025-10-13');
  });

  it('ДЗ, добавленное вручную, появляется в выдаче', async () => {
    const { service, store } = makeService({ weeks: { '2025-10-13': WEEK1 } });
    store.data.manual.push({ id: 1, date: '2025-10-16', subject: 'История', text: 'Выучить даты', author: 'Староста' });
    const view = await service.dayView('2025-10-16');
    assert.equal(view.entries.length, 1);
    assert.equal(view.entries[0].manual, true);
  });

  it('поиск изменений: первая проверка запоминает, дальше — новые и изменённые', async () => {
    const weeks = { '2025-10-13': structuredClone(WEEK1), '2025-10-20': structuredClone(WEEK2) };
    const { service, store } = makeService({ weeks });

    const first = await service.pollChanges();
    assert.equal(first.firstRun, true);
    assert.equal(first.added.length + first.changed.length, 0);
    assert.equal(store.data.baselineReady, true);

    // учитель добавил ДЗ по истории на чт и изменил литературу на пт
    weeks['2025-10-13'].days[3].subjects[0].homeworkBody = 'Параграф 5';
    weeks['2025-10-13'].days[4].subjects[1].homeworkBody = 'Читать стр. 40-60';
    const second = await service.pollChanges();
    assert.deepEqual(second.added.map((e) => e.subject), ['История']);
    assert.deepEqual(second.changed.map((e) => e.subject), ['Литература']);
    assert.equal(second.added[0].dueDate, '2025-10-16');

    // повторная проверка без изменений — тишина
    const third = await service.pollChanges();
    assert.equal(third.added.length + third.changed.length, 0);
  });

  it('поиск изменений: прошедшие дни и сбой API не дают ложных уведомлений', async () => {
    const weeks = { '2025-10-13': structuredClone(WEEK1), '2025-10-20': structuredClone(WEEK2) };
    const { service } = makeService({ weeks });
    await service.pollChanges();

    // ДЗ задним числом на понедельник 13.10 — уже прошло, не сообщаем
    weeks['2025-10-13'].days[0].subjects[1].homeworkBody = 'Отжимания';
    // сбой: среда внезапно пустая
    const savedWednesday = weeks['2025-10-13'].days[2].subjects;
    weeks['2025-10-13'].days[2].subjects = [];
    let result = await service.pollChanges();
    assert.equal(result.added.length + result.changed.length, 0);

    // данные вернулись — это не «новые» ДЗ
    weeks['2025-10-13'].days[2].subjects = savedWednesday;
    result = await service.pollChanges();
    assert.equal(result.added.length + result.changed.length, 0);
  });

  it('контекст для ИИ содержит ДЗ и расписание', async () => {
    const { service } = makeService({ weeks: { '2025-10-13': WEEK1, '2025-10-20': WEEK2 } });
    const context = await service.aiContext();
    assert.match(context, /Сегодня: вторник, 14\.10\.2025/);
    assert.match(context, /Алгебра: № 250/);
    assert.match(context, /Английский язык: учебник: Excel 7, стр\. 34/);
    assert.match(context, /Расписание ближайших учебных дней/);
    assert.match(context, /Класс: 7 «А»/);
  });

  it('контекст для ИИ при недоступном дневнике запрещает выдумывать', async () => {
    const { service, client } = makeService({ weeks: {} });
    client.fail = new Error('timeout');
    const context = await service.aiContext();
    assert.match(context, /недоступен/);
    assert.match(context, /Не выдумывай/);
  });
});

describe('оформление сообщений', () => {
  it('ДЗ на день', async () => {
    const { service } = makeService({ weeks: { '2025-10-13': WEEK1 } });
    const text = formatDay(await service.dayView('2025-10-15'), '2025-10-14');
    assert.match(text, /^📚 \*ДЗ на завтра, среду, 15\.10\*/);
    assert.match(text, /\*1\. Алгебра\*\n№ 250/);
    assert.match(text, /📖 Excel 7, стр\. 34/);
    assert.match(text, /Вопрос по заданию/i);
  });

  it('день без ДЗ и выходной', async () => {
    const { service } = makeService({ weeks: { '2025-10-13': WEEK1 } });
    assert.match(formatDay(await service.dayView('2025-10-16'), '2025-10-14'), /Домашнего задания в дневнике пока нет/);
    assert.match(formatDay(await service.dayView('2025-10-18'), '2025-10-14'), /нет уроков/);
  });

  it('расписание, неделя, изменения, предмет', async () => {
    const { service } = makeService({ weeks: { '2025-10-13': WEEK1, '2025-10-20': WEEK2 } });
    const schedule = formatSchedule(await service.dayView('2025-10-14'), '2025-10-14');
    assert.match(schedule, /1\. 08:00–08:45 \*Физика\* 📝/);
    const week = formatWeek(await service.weekView('2025-10-13'), '2025-10-14');
    assert.match(week, /\*Вт 14\.10 \(сегодня\)\*/);
    assert.match(week, /• \*Литература:\* Читать стр\. 40-55/);
    const changes = formatChanges({ added: [{ subject: 'История', dueDate: '2025-10-16', text: 'Параграф 5', books: [], hasFiles: false }], changed: [] }, '2025-10-14');
    assert.match(changes, /🆕 \*История\* — на четверг, 16\.10/);
    assert.equal(formatChanges({ added: [], changed: [] }, '2025-10-14'), null);
    const subject = formatSubject(await service.findSubject('физике'), 'физике', '2025-10-14');
    assert.match(subject, /📘 \*Физика\*/);
    assert.match(subject, /§ 12/);
  });
});

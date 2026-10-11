import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { HomeworkPhotos, screenshotCaption } from '../src/homework/message.js';
import { testConfig } from './helpers.js';

const JPEG = Buffer.from([0xff, 0xd8, 0xff, 0xe0]);
const entry = (subject, text, extra = {}) => ({ key: `${subject}#1`, lessonDate: '2025-10-15', subject, text, books: [], hasFiles: false, ...extra });
const view = (date, entries) => ({ date, lessons: entries.map((e) => ({ subject: e.subject })), entries: entries.map((e) => ({ ...e, lessonDate: date })) });
const markKey = (e) => `${e.lessonDate}|${e.key}`;

class FakeShooter {
  constructor({ dates = [], fail = null } = {}) {
    this.dates = dates;
    this.fail = fail;
    this.calls = [];
    this.available = true;
  }

  async captureDays(days) {
    this.calls.push(days);
    if (this.fail) throw this.fail;
    return new Map(days.filter((d) => this.dates.includes(d.date)).map((d) => [d.date, JPEG]));
  }
}

const photos = (shooter, env = {}, notify = () => {}) => new HomeworkPhotos({ config: testConfig(env), screenshotter: shooter, logger: { warn() {}, info() {} }, notify });

describe('скриншоты дневника в рассылке', () => {
  it('скриншот, где получилось, и нарисованная карточка, где нет', async () => {
    const shooter = new FakeShooter({ dates: ['2025-10-15'] });
    const days = [view('2025-10-15', [entry('Алгебра', '№ 250')]), view('2025-10-16', [entry('История', '§ 5')])];
    const marks = new Map([['2025-10-16|История#1', 'new']]);
    const [a, b] = await photos(shooter).messages(days, '2025-10-14', { kinds: new Map([['2025-10-16', 'new']]), marks, markKey });
    assert.equal(a.image, JPEG, 'настоящий скриншот');
    assert.equal(a.caption, '📚 Домашнее задание на завтра');
    assert.notEqual(b.image, JPEG);
    assert.equal(b.image[0], 0xff, 'запасная карточка тоже картинка');
    assert.equal(b.caption, '🆕 Новое домашнее задание на четверг, 16.10');
    assert.deepEqual(shooter.calls[0].map((d) => d.subjects), [['Алгебра'], ['История']]);
  });

  it('в подписи к скриншоту перечислено новое и изменённое', () => {
    const v = view('2025-10-15', [entry('Алгебра', '1'), entry('Русский язык', '2'), entry('Физика', '3')]);
    const marks = new Map([['2025-10-15|Алгебра#1', 'new'], ['2025-10-15|Русский язык#1', 'changed']]);
    assert.equal(
      screenshotCaption(v, '2025-10-14', 'digest', marks, markKey),
      '📚 Домашнее задание на завтра\n🆕 Новое: Алгебра\n✏️ Изменено: Русский язык',
    );
  });

  it('сайт недоступен — карточки, после 3 неудач подряд админу уведомление', async () => {
    const notes = [];
    const p = photos(new FakeShooter({ fail: new Error('timeout') }), {}, (key) => notes.push(key));
    for (let i = 0; i < 3; i += 1) {
      const [msg] = await p.messages([view('2025-10-15', [entry('Алгебра', '№ 1')])], '2025-10-14');
      assert.equal(msg.caption, '📚 Домашнее задание на завтра');
    }
    assert.deepEqual(notes, ['screenshot-failed']);
  });

  it('ДЗ, добавленное вручную, и режим assigned — не скриншот (на сайте этого нет)', async () => {
    const shooter = new FakeShooter({ dates: ['2025-10-15'] });
    await photos(shooter).messages([view('2025-10-15', [entry('Алгебра', '№ 1', { manual: true })])], '2025-10-14');
    await photos(shooter, { HOMEWORK_ATTACHED_TO: 'assigned' }).messages([view('2025-10-15', [entry('Алгебра', '№ 1')])], '2025-10-14');
    assert.equal(shooter.calls.length, 0);
  });

  it('режимы card и text не открывают браузер; день без ДЗ — текст', async () => {
    const shooter = new FakeShooter({ dates: ['2025-10-15'] });
    const [card] = await photos(shooter, { HOMEWORK_PHOTO: 'card' }).messages([view('2025-10-15', [entry('Алгебра', '№ 1')])], '2025-10-14');
    assert.ok(card.image && card.image !== JPEG);
    const [text] = await photos(shooter, { HOMEWORK_PHOTO: 'text' }).messages([view('2025-10-15', [entry('Алгебра', '№ 1')])], '2025-10-14');
    assert.match(text.text, /№ 1/);
    const [empty] = await photos(shooter).messages([view('2025-10-15', [])], '2025-10-14');
    assert.equal(empty.text, '📚 Домашнего задания на завтра в дневнике нет 🎉');
    assert.equal(shooter.calls.length, 0);
  });
});

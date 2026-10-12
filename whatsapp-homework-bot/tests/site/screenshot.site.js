// Проверка скриншотов на НАСТОЯЩЕМ сайте www.bilimclass.kz с подменёнными ответами API.
// Нужны интернет и Chromium. Запуск: npm run test:site  (CHROMIUM_PATH=..., при необходимости BROWSER_PROXY=...)
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { loadImage } from '@napi-rs/canvas';
import { DiaryScreenshotter } from '../../src/bilimclass/screenshot.js';
import { BotCore } from '../../src/core.js';
import { HomeworkPhotos } from '../../src/homework/message.js';
import { HomeworkService } from '../../src/homework/service.js';
import { Scheduler } from '../../src/scheduler.js';
import { FakeBilimClient, FakeWA, memoryStore, rawWeek, testConfig } from '../helpers.js';
import { installMocks } from './mock-bilimclass.js';

const logger = { info() {}, warn(...a) { console.log('warn', JSON.stringify(a[0])); }, error() {}, debug() {}, child() { return this; } };
const config = testConfig({
  BILIM_LOGIN: 'student', BILIM_PASSWORD: 'secret', WA_GROUP_IDS: 'g@g.us', HOMEWORK_PHOTO: 'screenshot',
  CHROMIUM_PATH: process.env.CHROMIUM_PATH || '', BROWSER_PROXY: process.env.BROWSER_PROXY || '',
});

// одинаковые данные для сайта (подмена) и для API бота
const SITE_WEEKS = {
  '12.10.2026': { 1: [['Алгебра', '№ 250, 251 (стр. 58). Решить уравнения из раздела «Повторение» и выучить формулы'], ['Физическая культура', '']], 2: [['Қазақ тілі', 'Мәтінді оқу']] },
  '19.10.2026': { 0: [['История', 'Параграф 5']] },
};
const SCORES = { s10: { formattedScore: { mark: 2, markMax: 10 }, attendance: 'missing_without_reason' } };
const shooter = new DiaryScreenshotter({ config, logger, contextHook: (ctx) => installMocks(ctx, { currentWeek: '12.10.2026', weeks: SITE_WEEKS, scores: SCORES }) });

describe('скриншот дневника на сайте BilimClass', { skip: !shooter.available && 'Chromium не найден' }, () => {
  it('снимает нужные дни (и следующей недели), бракует «не тот» день', async () => {
    const shots = await shooter.captureDays([
      { date: '2026-10-13', subjects: ['Алгебра'] },
      { date: '2026-10-19', subjects: ['История'] },
      { date: '2026-10-14', subjects: ['Химия'] },
    ]);
    assert.deepEqual([...shots.keys()].sort(), ['2026-10-13', '2026-10-19']);
    const img = await loadImage(shots.get('2026-10-13'));
    assert.ok(img.width > 700 && img.width <= 824, `мобильная ширина (412 × 2 без полей), получено ${img.width}`);
  });

  it('запасной способ: дневник через сайт (если API сломалось)', async () => {
    const weeks = await shooter.fetchWeeks(['2026-10-12', '2026-10-19']);
    assert.deepEqual([...weeks.keys()], ['2026-10-12', '2026-10-19']);
    assert.equal(weeks.get('2026-10-12').days[1].subjects[0].label, 'Алгебра');
    assert.equal(weeks.get('2026-10-19').days[0].subjects[0].label, 'История');
    assert.equal(shooter.siteUserInfo?.group?.name, '7 «А»', 'профиль ученика взят из ответа на вход');
  });

  it('рассылка после уроков приходит скриншотом дневника', async () => {
    const store = memoryStore();
    const wa = new FakeWA();
    const client = new FakeBilimClient({
      '2026-10-12': rawWeek('2026-10-12', { 2: [['Алгебра', '№ 250, 251 (стр. 58). Решить уравнения из раздела «Повторение» и выучить формулы'], ['Физическая культура', null]], 3: [['Қазақ тілі', 'Мәтінді оқу']] }),
      '2026-10-19': rawWeek('2026-10-19', { 1: [['История', 'Параграф 5']] }),
    });
    const homework = new HomeworkService({ client, store, config });
    homework.today = () => '2026-10-12';
    const core = new BotCore({ config, store, wa, logger });
    const photos = new HomeworkPhotos({ config, screenshotter: shooter, logger });
    const scheduler = new Scheduler({ config, store, homework, wa, core, logger, photos, clock: () => ({ iso: '2026-10-12', minutes: 900, weekday: 1 }) });
    store.data.announcedReady = true; // не первая рассылка: всё в дневнике — новое
    await scheduler.sendDigest({ targets: ['g@g.us'] });
    const captions = wa.sent.map((s) => s.content.caption.split('\n')[0]);
    assert.deepEqual(captions, ['📚 Домашнее задание на завтра', '🆕 Новое домашнее задание на среду, 14.10', '🆕 Новое домашнее задание на понедельник, 19.10']);
    // карточка бота шириной 1080, скриншот сайта — уже (мобильная вёрстка)
    for (const s of wa.sent) assert.ok((await loadImage(s.content.image)).width <= 824, 'это скриншот сайта, а не карточка');
  });
});

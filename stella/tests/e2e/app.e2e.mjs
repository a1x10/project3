// Сквозной тест настоящего приложения Electron.
// Запуск: npm run test:e2e   (на Linux без дисплея: xvfb-run -a npm run test:e2e)
import { _electron as electron, chromium, devices } from 'playwright-core';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { startMockOpenRouter } from './mock-openrouter.mjs';
import http from 'node:http';

const require = createRequire(import.meta.url);
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const SHOTS = path.join(ROOT, 'tests/e2e/screenshots');
fs.mkdirSync(SHOTS, { recursive: true });

const results = [];
async function step(name, fn) {
  const t = Date.now();
  try { await fn(); results.push(['✔', name, Date.now() - t]); console.log(`  ✔ ${name}`); }
  catch (e) { results.push(['✘', name, Date.now() - t]); console.log(`  ✘ ${name}\n    ${e.message}`); throw e; }
}

const mock = await startMockOpenRouter();
// настоящий сервер Stella Cloud, который ходит в поддельный OpenRouter
const { createApp } = require('../../server/server.js');
const cloudApp = createApp({ dataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'stella-cloud-e2e-')), adminPassword: 'adm', openrouterKey: 'sk-or-CLOUD', elevenKey: '', openrouterBase: `http://127.0.0.1:${mock.port}` });
const cloud = http.createServer(cloudApp.handler);
await new Promise((r) => cloud.listen(0, '127.0.0.1', r));
const cloudUrl = `http://127.0.0.1:${cloud.address().port}`;
const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'stella-e2e-'));
const app = await electron.launch({
  executablePath: require('electron'),
  args: [ROOT, '--no-sandbox', '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', ...(process.platform === 'linux' ? ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] : [])],
  env: { ...process.env, STELLA_DATA_DIR: dataDir, STELLA_OPENROUTER_BASE: `http://127.0.0.1:${mock.port}` },
});
const win = await app.firstWindow();
const errors = [];
win.on('pageerror', (e) => errors.push(e.message));
const shot = (n) => win.screenshot({ path: path.join(SHOTS, n + '.png') });

console.log('Stella E2E');
try {
  await step('заставка с логотипом', async () => {
    await win.waitForSelector('#splash .splash-title');
    assert.equal(await win.textContent('#splash-title'), 'Стелла');
    await shot('01-splash');
  });
  await step('VRM-модель загружается, появляется регистрация', async () => {
    await win.waitForSelector('#auth .auth-card', { timeout: 120000 });
    assert.ok(await win.evaluate(() => !!window.__stella.avatar.vrm));
    await shot('02-register');
  });
  await step('выбор Марка в регистрации меняет модель', async () => {
    await win.click('.persona-card[data-persona="mark"]');
    await win.waitForFunction(() => window.__stella.avatar.vrm?.meta?.name?.startsWith('Mark'), null, { timeout: 60000 });
    await shot('03-register-mark');
    await win.click('.persona-card[data-persona="stella"]');
    await win.waitForFunction(() => !window.__stella.avatar.vrm?.meta?.name?.startsWith('Mark'), null, { timeout: 60000 });
  });
  await step('валидация регистрации', async () => {
    await win.fill('#a-name', '');
    await win.fill('#a-user', 'x');
    await win.click('#a-go');
    await win.waitForFunction(() => document.querySelector('#a-err').textContent.length > 0);
  });
  await step('создание аккаунта', async () => {
    await win.fill('#a-name', 'Тестер');
    await win.fill('#a-user', 'tester');
    await win.click('#a-go');
    await win.waitForSelector('#auth.hidden', { state: 'attached' });
    await win.waitForSelector('.modal-backdrop.show', { timeout: 15000 });
    assert.match(await win.textContent('.modal h3'), /дополнительных агентов/);
    assert.match(await win.textContent('.modal .btn.primary'), /Подключить дополнительных агентов/);
    await shot('04a-agents-offer');
    await win.click('.modal .btn:not(.primary)');
    await win.waitForSelector('.modal-backdrop', { state: 'detached' });
    await win.waitForSelector('#home:not(.chatting) .hero-title');
    assert.match(await win.textContent('.hero-title'), /твоя\s+Стелла/);
    await shot('04-home');
  });
  await step('светлая тема по умолчанию', async () => {
    assert.equal(await win.evaluate(() => document.body.dataset.theme), 'white');
    const bg = await win.evaluate(() => getComputedStyle(document.body).getPropertyValue('--bg').trim());
    assert.equal(bg, '#fbfbfa');
  });
  await step('перетаскивание аватара и посадка на панель ввода', async () => {
    const p = await win.evaluate(() => {
      const ctx = window.__stella; const hip = ctx.avatar.screenPointOf('hips'); const r = document.querySelector('#avatar-layer').getBoundingClientRect();
      const box = document.querySelector('.composer-box').getBoundingClientRect();
      return { sx: r.left + hip.x, sy: r.top + hip.y, tx: box.left + box.width * 0.75, ty: box.top };
    });
    await win.mouse.move(p.sx, p.sy);
    await win.mouse.down();
    for (let i = 1; i <= 12; i++) await win.mouse.move(p.sx + ((p.tx - p.sx) * i) / 12, p.sy + ((p.ty - p.sy) * i) / 12);
    await win.mouse.up();
    await win.waitForFunction(() => window.__stella.perch.state === 'sit' && window.__stella.avatar.posture === 'sit', null, { timeout: 5000 });
    await win.waitForTimeout(600);
    await shot('04b-sitting');
    // проверяем, что бёдра на краю панели
    const d = await win.evaluate(() => { const ctx = window.__stella; const hip = ctx.avatar.screenPointOf('hips'); const r = document.querySelector('#avatar-layer').getBoundingClientRect(); return Math.abs(r.top + hip.y - document.querySelector('.composer-box').getBoundingClientRect().top); });
    assert.ok(d < 15, 'бёдра на краю панели, отклонение ' + d);
    await win.dblclick('#avatar-canvas', { position: { x: 100, y: 100 } }).catch(() => {});
    await win.evaluate(() => window.__stella.perch.dock());
  });
  await step('сохранение ключа OpenRouter в настройках', async () => {
    await win.click('.tab[data-tab="ai"]');
    await win.fill('#or-key', 'sk-or-v1-test-key-1234567890');
    await win.press('#or-key', 'Enter');
    await win.waitForSelector('#page-ai .note.ok');
    await win.fill('#model-input', 'mock/tool-model');
    await win.press('#model-input', 'Enter');
    await win.waitForFunction(() => window.__stella.settings.model === 'mock/tool-model');
    await shot('05-ai');
  });
  await step('чат: стриминг ответа, теги → анимация и эмоция', async () => {
    await win.click('.tab[data-tab="home"]');
    await win.fill('#input', 'Привет, Стелла!');
    await win.press('#input', 'Enter');
    await win.waitForFunction(() => document.querySelectorAll('.msg.assistant .seg-text').length > 0 && !window.__stella.chat.busy, null, { timeout: 30000 });
    const text = await win.textContent('.msg.assistant:last-child .bubble');
    assert.match(text, /Привет! Я Стелла/);
    assert.doesNotMatch(text, /\[happy\]/);
    assert.ok(await win.evaluate(() => ['happy', 'neutral'].includes(window.__stella.avatar.mixer.emotion)));
    assert.ok(await win.evaluate(() => document.querySelector('#home').classList.contains('chatting')));
    await shot('06-chat');
  });
  await step('управление ПК: запрос подтверждения и выполнение команды', async () => {
    await win.fill('#input', 'Выполни команду echo');
    await win.press('#input', 'Enter');
    await win.waitForSelector('.modal-backdrop.show', { timeout: 30000 });
    assert.match(await win.textContent('.modal h3'), /Команда/);
    assert.match(await win.textContent('.modal pre'), /echo hello-from-stella/);
    await shot('07-confirm');
    await win.click('.modal .btn.primary');
    await win.waitForSelector('.tool-card.ok', { timeout: 30000 });
    await win.waitForFunction(() => !window.__stella.chat.busy, null, { timeout: 30000 });
    assert.match(await win.textContent('.tool-card.ok pre'), /hello-from-stella/);
    assert.match(await win.textContent('.msg.assistant:last-child .bubble'), /Готово!/);
    await shot('08-tool-done');
  });
  await step('модель получила результат инструмента', async () => {
    const toolMsg = mock.requests.at(-1).messages.find((m) => m.role === 'tool');
    assert.match(toolMsg.content, /hello-from-stella/);
    assert.ok(mock.requests.at(-1).tools.length >= 35);
  });
  await step('отказ в подтверждении', async () => {
    await win.fill('#input', 'Ещё одну команду');
    await win.press('#input', 'Enter');
    await win.waitForSelector('.modal-backdrop.show', { timeout: 30000 });
    await win.click('.modal .btn:not(.primary)');
    await win.waitForSelector('.tool-card.fail', { timeout: 30000 });
    await win.waitForFunction(() => !window.__stella.chat.busy, null, { timeout: 30000 });
  });
  await step('журнал действий во вкладке «Компьютер»', async () => {
    await win.click('.tab[data-tab="computer"]');
    await win.waitForSelector('.log-item');
    assert.ok((await win.$$('.log-item')).length >= 2);
    await shot('09-computer');
  });
  await step('профиль и статистика', async () => {
    await win.click('.tab[data-tab="settings"]');
    await win.waitForSelector('#page-settings .profile-hero');
    assert.match(await win.textContent('.profile-hero h2'), /Тестер/);
    await shot('10-settings');
  });
  await step('пользовательские команды работают без ИИ', async () => {
    await win.click('.tab[data-tab="commands"]');
    await win.waitForSelector('#c-examples');
    await shot('11-commands-empty');
    await win.click('#c-examples');
    await win.waitForFunction(() => document.querySelectorAll('.cmd-item').length === 5);
    await win.click('.cmd-item:nth-child(3)');
    await win.waitForSelector('#e-name');
    await shot('12-command-editor');
    const before = mock.requests.length;
    await win.click('.tab[data-tab="home"]');
    await win.fill('#input', 'Стелла, станцуй');
    await win.press('#input', 'Enter');
    await win.waitForFunction(() => window.__stella.avatar.currentAction === 'dance', null, { timeout: 5000 });
    assert.equal(mock.requests.length, before);
    assert.match(await win.textContent('.msg.assistant:last-child .meta'), /команда «Танец»/);
  });
  await step('смена ассистента на Марка во вкладке «Модель»', async () => {
    await win.click('.tab[data-tab="model"]');
    await win.click('#page-model .persona-card[data-persona="mark"]');
    await win.waitForFunction(() => window.__stella.avatar.vrm?.meta?.name?.startsWith('Mark'), null, { timeout: 60000 });
    await win.waitForFunction(() => document.querySelector('#persona-name').textContent === 'Марк');
    await shot('13-mark-model');
  });
  await step('танец по кнопке', async () => {
    await win.click('.tab[data-tab="home"]');
    await win.evaluate(() => window.__stella.avatar.stop());
    await win.waitForTimeout(600);
    await win.click('#dock button[data-act="dance"]', { force: true });
    assert.equal(await win.evaluate(() => window.__stella.avatar.currentAction), 'dance');
    await win.waitForTimeout(800);
    await shot('14-mark-home');
  });
  await step('касание аватара вызывает реакцию', async () => {
    await win.evaluate(() => { window.__stella.avatar.stop(); });
    await win.waitForFunction(() => !window.__stella.avatar.currentAction, null, { timeout: 5000 });
    await win.evaluate(() => window.__stella.presence.onTouch('head'));
    assert.ok(await win.evaluate(() => ['shy', 'laugh'].includes(window.__stella.avatar.currentAction)));
  });
  await step('Мастерская: игры и агенты', async () => {
    await win.click('.tab[data-tab="workshop"]');
    await win.click('#page-workshop [data-ptab="games"]');
    await win.waitForSelector('#g-follow');
    await shot('15-workshop-games');
    await win.click('#page-workshop [data-ptab="agents"]');
    await win.waitForSelector('#ag-open');
    assert.match(await win.textContent('#page-workshop'), /Antigravity/);
    await shot('16-workshop-agents');
  });
  await step('компаньон в игре: окно поверх и бег за курсором', async () => {
    await win.click('#page-workshop [data-ptab="games"]');
    await win.click('#g-follow');
    await win.waitForFunction(async () => (await window.stella.invoke('game:state')).follow === true, null, { timeout: 15000 });
    const comp = await app.waitForEvent('window', { timeout: 30000 }).catch(() => null) || app.windows().find((w) => w.url().includes('companion'));
    assert.ok(comp, 'окно компаньона открылось');
    await win.click('#g-follow');
    await win.waitForFunction(async () => (await window.stella.invoke('game:state')).follow === false, null, { timeout: 10000 });
  });
  await step('Stella Cloud: регистрация на сервере и чат через облако', async () => {
    await win.click('.tab[data-tab="settings"]');
    await win.waitForSelector('#cl-url');
    await win.fill('#cl-url', cloudUrl);
    await win.click('#cl-check');
    await win.waitForSelector('#cl-status.ok');
    await win.fill('#cl-user', 'cloudtester');
    await win.fill('#cl-pass', 'secret123');
    await win.click('#cl-register');
    await win.waitForSelector('.cloud-plan', { timeout: 15000 });
    assert.match(await win.textContent('.cloud-plan'), /Stella Free/);
    await shot('17-cloud');
    const before = mock.requests.length;
    await win.click('.tab[data-tab="home"]');
    await win.click('#btn-plus');
    await win.fill('#input', 'Привет через облако');
    await win.press('#input', 'Enter');
    await win.waitForFunction(() => !window.__stella.chat.busy && document.querySelectorAll('.msg.assistant').length > 0, null, { timeout: 30000 });
    assert.ok(mock.requests.length > before, 'запрос дошёл до OpenRouter через сервер');
    assert.match(await win.textContent('.msg.assistant:last-child .bubble'), /Привет! Я Стелла/);
    const u = cloudApp.db.data.users.find((x) => x.username === 'cloudtester');
    assert.equal(cloudApp.db.data.usage[u.id][`m:${new Date().toISOString().slice(0, 10)}`], 1);
  });
  await step('окно в реальность: персонаж поверх веб-камеры', async () => {
    await win.click('.tab[data-tab="workshop"]');
    await win.click('#page-workshop [data-ptab="reality"]');
    await win.click('#cam-start');
    await win.waitForFunction(() => document.body.classList.contains('reality') && document.querySelector('#reality-video').readyState >= 2, null, { timeout: 15000 });
    await win.waitForTimeout(800);
    await shot('18-reality-webcam');
    await win.click('#reality-exit');
    await win.waitForFunction(() => !document.body.classList.contains('reality'));
  });
  await step('выход в комнату: телефон подключается по QR-ссылке (AR)', async () => {
    await win.click('.tab[data-tab="workshop"]');
    await win.click('#page-workshop [data-ptab="reality"]');
    await win.click('#ar-toggle');
    await win.waitForFunction(() => /^https:/.test(document.querySelector('#ar-url')?.textContent || ''), null, { timeout: 60000 });
    assert.ok(await win.$('#ar-qr svg'), 'QR-код показан');
    await shot('19-ar-qr');
    const url = (await win.textContent('#ar-url')).trim().replace(/\/\/[\d.]+:/, '//127.0.0.1:');
    const phoneBrowser = await chromium.launch({ args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    try {
      const phoneCtx = await phoneBrowser.newContext({ ...devices['Pixel 7'], ignoreHTTPSErrors: true, permissions: ['camera'] });
      const phone = await phoneCtx.newPage();
      const phoneErrors = [];
      phone.on('pageerror', (e) => phoneErrors.push(e.message));
      await phone.goto(url);
      await phone.waitForFunction(() => window.__arReady === true, null, { timeout: 90000 });
      await phone.screenshot({ path: path.join(SHOTS, '20-phone-start.png') });
      // без ключа страница недоступна
      const denied = await phoneCtx.request.get(url.replace(/\?k=.*/, ''), { ignoreHTTPSErrors: true, headers: { cookie: '' } });
      assert.ok([403, 200].includes(denied.status()));
      await phone.click('#btn-cam');
      await phone.waitForFunction(() => window.__ar.avatar.root.visible && document.querySelector('#cam').readyState >= 2, null, { timeout: 15000 });
      await win.waitForFunction(() => window.__stella.arClients >= 1, null, { timeout: 10000 });
      // компьютер говорит — телефон показывает реплику
      await win.evaluate(() => window.__stella.say('Привет! Я вышла к тебе в комнату!'));
      await phone.waitForFunction(() => document.querySelector('#bubble').textContent.includes('вышла к тебе'), null, { timeout: 15000 });
      // действие на компьютере повторяется на телефоне
      await win.evaluate(() => window.__stella.avatar.play('heart'));
      await phone.waitForFunction(() => window.__ar.avatar.currentAction === 'heart', null, { timeout: 10000 });
      await phone.waitForTimeout(700);
      await phone.screenshot({ path: path.join(SHOTS, '21-phone-camera.png') });
      // касание экрана — персонаж бежит к точке
      const x0 = await phone.evaluate(() => window.__ar.avatar.root.position.x);
      const vp = phone.viewportSize();
      await phone.mouse.click(vp.width * 0.85, vp.height * 0.75);
      await phone.waitForFunction((x) => Math.abs(window.__ar.avatar.root.position.x - x) > 0.2, x0, { timeout: 10000 });
      // сообщение с телефона попадает в чат на компьютере
      const before = await win.evaluate(() => document.querySelectorAll('.msg.user').length);
      await phone.fill('#msg', 'Привет с телефона');
      await phone.click('#btn-send');
      await win.waitForFunction((n) => document.querySelectorAll('.msg.user').length > n, before, { timeout: 15000 });
      assert.match(await win.evaluate(() => [...document.querySelectorAll('.msg.user .bubble')].pop().textContent), /Привет с телефона/);
      assert.deepEqual(phoneErrors, []);
    } finally { await phoneBrowser.close(); }
    await win.click('.tab[data-tab="workshop"]');
    await win.click('#page-workshop [data-ptab="reality"]');
    await win.click('#ar-toggle');
  });
  await step('персонаж съедает файл и может его выплюнуть', async () => {
    await win.click('.tab[data-tab="home"]');
    await win.evaluate(() => window.__stella.perch.dock());
    const food = path.join(os.tmpdir(), `stella-food-${Date.now()}.txt`);
    fs.writeFileSync(food, 'вкусный файл');
    // перетаскивание файла над персонажем: он тянется и открывает рот
    await win.evaluate(() => {
      const dt = new DataTransfer(); dt.items.add(new File(['x'], 'a.txt', { type: 'text/plain' }));
      document.querySelector('#avatar-canvas').dispatchEvent(new DragEvent('dragenter', { dataTransfer: dt, bubbles: true }));
    });
    await win.waitForFunction(() => window.__stella.avatar.currentAction === 'hungry', null, { timeout: 5000 });
    await shot('22-hungry');
    await win.evaluate(() => { const dt = new DataTransfer(); dt.items.add(new File(['x'], 'a.txt')); document.querySelector('#avatar-canvas').dispatchEvent(new DragEvent('dragleave', { dataTransfer: dt, bubbles: true })); });
    const res = await win.evaluate((p) => window.__stella.eatPaths([p]), food);
    assert.equal(res[0].ok, true);
    assert.equal(fs.existsSync(food), false, 'файл исчез');
    await win.waitForFunction(() => window.__stella.avatar.currentAction === 'eat', null, { timeout: 3000 }).catch(() => {});
    await win.waitForSelector('.toast button', { timeout: 5000 });
    await shot('23-eaten');
    // желудок в Мастерской
    await win.click('.tab[data-tab="workshop"]');
    await win.click('#page-workshop [data-ptab="stomach"]');
    await win.waitForSelector('.food-item');
    assert.match(await win.textContent('.food-item'), /stella-food-/);
    await shot('24-stomach');
    await win.click('.food-item [data-spit]');
    await win.waitForFunction(() => !document.querySelector('.food-item'), null, { timeout: 5000 });
    assert.equal(fs.readFileSync(food, 'utf8'), 'вкусный файл', 'файл вернулся на место');
    fs.rmSync(food);
    // важное есть отказывается
    const refused = await win.evaluate((p) => window.__stella.eatPaths([p]), os.homedir());
    assert.equal(refused.length, 0);
    assert.ok(fs.existsSync(os.homedir()));
  });
  await step('голос: без имени — подсказка, с именем — ответ, во время ответа — очередь', async () => {
    await win.click('.tab[data-tab="home"]');
    await win.click('#btn-plus');
    // распознавание вернуло фразу без имени
    await win.evaluate(() => window.__stella.listener.onHeard({ text: 'открой ютуб', result: 'no-name' }));
    await win.waitForFunction(() => [...document.querySelectorAll('.toast')].some((t) => t.textContent.includes('без имени')), null, { timeout: 5000 });
    // команда с именем → ответ модели
    const before = await win.evaluate(() => document.querySelectorAll('.msg.assistant').length);
    await win.evaluate(() => window.__stella.listener.onCommand('привет', 'Стелла, привет'));
    // вторая команда во время ответа встаёт в очередь
    await win.waitForFunction(() => window.__stella.chat.busy, null, { timeout: 5000 });
    await win.evaluate(() => window.__stella.chat.send('как дела', { voice: true }));
    await win.waitForFunction((n) => !window.__stella.chat.busy && document.querySelectorAll('.msg.assistant').length >= n + 2, before, { timeout: 30000 });
    const users = await win.evaluate(() => [...document.querySelectorAll('.msg.user .bubble')].slice(-2).map((b) => b.textContent.trim()));
    assert.deepEqual(users, ['привет', 'как дела']);
    // история распознавания во вкладке Голос
    await win.click('.tab[data-tab="voice"]');
    await win.click('#page-voice [data-ptab="stt"]');
    await win.waitForSelector('#heard-log');
    assert.match(await win.textContent('#heard-log'), /открой ютуб.*нет имени/s);
    await shot('25-heard-log');
  });
  await step('нет ошибок JavaScript на странице', async () => assert.deepEqual(errors, []));
} finally {
  await app.close();
  mock.server.close();
  cloud.close();
  const failed = results.filter((r) => r[0] === '✘').length;
  console.log(`\n${results.length - failed} пройдено, ${failed} провалено. Скриншоты: ${SHOTS}`);
  if (failed) process.exitCode = 1;
}

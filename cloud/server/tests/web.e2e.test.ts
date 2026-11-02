import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { fakeTelegram, fakeUpstream, startCloud } from './helpers.js';

/** Browser test of the website (login via the bot, cabinet, admin). Needs cloud/web/dist and Playwright. */
const webDir = path.resolve(__dirname, '../../web/dist');
let chromium: any = null;
try {
  chromium = createRequire(import.meta.url)(process.env.PLAYWRIGHT_PATH || 'playwright').chromium;
} catch {
  chromium = null;
}
const enabled = !!chromium && fs.existsSync(path.join(webDir, 'index.html'));

describe.skipIf(!enabled)('website e2e', () => {
  let tg: Awaited<ReturnType<typeof fakeTelegram>>;
  let up: Awaited<ReturnType<typeof fakeUpstream>>;
  let cloud: Awaited<ReturnType<typeof startCloud>>;
  let browser: any;

  beforeAll(async () => {
    tg = await fakeTelegram();
    up = await fakeUpstream();
    cloud = await startCloud({ TELEGRAM_BOT_TOKEN: 'T', TELEGRAM_API_URL: tg.url, ADMIN_TELEGRAM_IDS: '77', UPSTREAM_BASE_URL: `${up.url}/v1`, UPSTREAM_API_KEY: 'freellmapi-unified-key', WEB_DIR: webDir });
    await cloud.app.botReady;
    browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
  }, 60_000);
  afterAll(async () => {
    await browser?.close();
    await cloud?.close();
    await tg?.close();
    await up?.close();
  });

  async function loginInBrowser(page: any, tgId: number, name: string) {
    await page.goto(cloud.url + '/');
    await page.getByRole('button', { name: 'Войти через Telegram' }).first().click();
    const code = (await page.getByTestId('login-code').textContent())!.trim();
    expect(code).toMatch(/^[A-Z0-9]{4}-[A-Z0-9]{4}$/);
    const n = tg.sent.length;
    tg.say(tgId, `/login ${code}`, name);
    const offer = await tg.waitFor((m) => tg.sent.indexOf(m) >= n && m.params.chat_id === tgId && JSON.stringify(m.params.reply_markup ?? '').includes('approve:'));
    const data = offer.params.reply_markup.inline_keyboard[0][0].callback_data;
    tg.press(tgId, data);
    await page.getByRole('heading', { name: 'Личный кабинет' }).waitFor({ timeout: 10_000 });
  }

  it('owner logs in, sees cabinet, creates a key, manages users in admin', async () => {
    const page = await browser.newPage();
    const errors: string[] = [];
    page.on('pageerror', (e: Error) => errors.push(e.message));
    await loginInBrowser(page, 77, 'Owner');
    expect(await page.getByText('администратор', { exact: true }).isVisible()).toBe(true);
    await page.getByPlaceholder(/Название ключа/).fill('Cursor');
    await page.getByRole('button', { name: 'Создать ключ' }).click();
    const key = (await page.locator('.keyval').textContent())!;
    expect(key).toMatch(/^sk-stella-/);
    const r = await fetch(`${cloud.url}/v1/chat/completions`, { method: 'POST', headers: { authorization: `Bearer ${key}`, 'content-type': 'application/json' }, body: JSON.stringify({ messages: [{ role: 'user', content: 'hi' }] }) });
    expect(r.status).toBe(200);

    // second user registers via the bot
    tg.say(88, '/start', 'Mallory');
    await tg.waitFor((m) => m.params.chat_id === 88);

    await page.getByRole('link', { name: 'Админка' }).click();
    await page.getByRole('heading', { name: 'Администрирование' }).waitFor();
    const row = page.locator('tr', { hasText: 'Mallory' });
    await row.waitFor();
    await row.getByRole('button', { name: 'Заблокировать' }).click();
    await row.getByRole('button', { name: 'Разблокировать' }).waitFor();
    expect(cloud.app.store.userByTg(88)!.status).toBe('banned');
    await row.getByRole('button', { name: 'Удалить' }).click();
    await row.getByRole('button', { name: 'Удалить?' }).click();
    await page.locator('tr', { hasText: 'Mallory' }).waitFor({ state: 'detached' });
    expect(cloud.app.store.userByTg(88)).toBeUndefined();

    await page.getByRole('button', { name: 'Промпт и тарифы' }).click();
    await page.locator('textarea').first().fill('Ты — ассистент Stella.');
    await page.getByRole('button', { name: 'Сохранить' }).click();
    await page.getByText('Сохранено ✓').waitFor();
    expect(cloud.app.store.getSetting('system_prompt', '')).toBe('Ты — ассистент Stella.');
    await page.screenshot({ path: path.resolve(__dirname, '../../web/test-results/admin.png'), fullPage: true }).catch(() => undefined);
    expect(errors).toEqual([]);
  });

  it('regular user cannot open admin and can delete their account', async () => {
    const page = await browser.newPage();
    await loginInBrowser(page, 99, 'Bob');
    expect(await page.getByRole('link', { name: 'Админка' }).count()).toBe(0);
    await page.goto(cloud.url + '/#/admin');
    await page.getByText('Раздел только для администраторов.').waitFor();
    await page.goto(cloud.url + '/#/cabinet');
    await page.getByRole('button', { name: 'Удалить аккаунт' }).click();
    await page.getByRole('button', { name: 'Да, удалить навсегда' }).click();
    await page.getByRole('button', { name: 'Войти через Telegram' }).first().waitFor();
    expect(cloud.app.store.userByTg(99)).toBeUndefined();
  });
});

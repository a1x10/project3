// Настоящий скриншот дневника BilimClass: бот открывает сайт в браузере (как с телефона),
// входит под учеником, открывает «Дневник» и фотографирует нужный день.
// Оценки, посещаемость и всплывающие окна в кадр не попадают; длинное ДЗ показывается целиком.
import fs from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { createCanvas, loadImage } from '@napi-rs/canvas';
import { mondayOf, toDMY } from '../utils/dates.js';
import { normalize } from '../utils/text.js';

const MONTHS_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
const MOBILE_UA =
  'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36';
// Счётчики и реклама только замедляют загрузку
const BLOCKED = /mc\.yandex|yandex\.ru\/ads|an\.yandex|googlesyndication|google-analytics|googletagmanager|doubleclick|sppopups/;

// Как сайт показывает дату дня: «14 октября»
export const diaryDateLabel = (iso) => `${Number(iso.slice(8, 10))} ${MONTHS_GEN[Number(iso.slice(5, 7)) - 1]}`;

// Правки вида страницы перед снимком
const PAGE_CSS = `
  .bc-dl__hw .truncate, .bc-dl__hw .min-w-0 { white-space: normal !important; overflow: visible !important; text-overflow: clip !important; }
  .bc-dl__grades, .bc-dd__calendar { display: none !important; }
  .bc-dd__head { position: static !important; }
  .bc-dd__date > span ~ span { display: none !important; }
  .bc-diary-day { background: #fff !important; padding-bottom: 14px !important; }
`;

const require = createRequire(import.meta.url);
export const BUNDLED = 'bundled';

// Доля «чернил» (тёмных пикселей — текста) на снимке. На нормальном снимке дня ~2%, на пустом — 0.
// Пустой снимок в группу не уходит никогда: бот попробует ещё раз, а потом отправит нарисованную карточку.
const MIN_INK = 0.003;
export async function inkRatio(buffer) {
  const img = await loadImage(buffer);
  const scale = Math.min(1, 400 / img.width);
  const w = Math.max(1, Math.round(img.width * scale));
  const h = Math.max(1, Math.round(img.height * scale));
  const canvas = createCanvas(w, h);
  const ctx = canvas.getContext('2d');
  ctx.drawImage(img, 0, 0, w, h);
  const data = ctx.getImageData(0, 0, w, h).data;
  let ink = 0;
  for (let i = 0; i < data.length; i += 4) {
    if (0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2] < 150) ink += 1;
  }
  return ink / (w * h);
}

// Браузер, скачанный командой «npx playwright-core install chromium» — точно совместим с библиотекой
function bundledChromium() {
  try {
    const { chromium } = require('playwright-core');
    return fs.existsSync(chromium.executablePath()) ? chromium.executablePath() : null;
  } catch {
    return null;
  }
}

// Где искать Chromium: CHROMIUM_PATH → браузер playwright → системный chromium/chrome
function findChromium(explicit) {
  if (explicit) return fs.existsSync(explicit) ? explicit : null;
  if (bundledChromium()) return BUNDLED;
  const candidates = [
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
    '/usr/bin/google-chrome',
    '/usr/bin/google-chrome-stable',
    '/snap/bin/chromium',
  ];
  for (const base of [process.env.PLAYWRIGHT_BROWSERS_PATH, path.join(os.homedir(), '.cache/ms-playwright')]) {
    try {
      for (const dir of fs.readdirSync(base || '').filter((d) => /^chromium-\d+$/.test(d)).sort().reverse()) {
        candidates.push(path.join(base, dir, 'chrome-linux/chrome'), path.join(base, dir, 'chrome-linux64/chrome'));
      }
    } catch {
      /* папки нет */
    }
  }
  return candidates.find((p) => p && fs.existsSync(p)) || null;
}

export class DiaryScreenshotter {
  constructor({ config, logger, eduYear = () => null, contextHook = null }) {
    this.config = config;
    this.logger = logger;
    this.eduYear = eduYear; // учебный год из API (на случай, если сайт не подскажет его в адресе)
    this.contextHook = contextHook; // для тестов: подмена ответов сервера
    this.executable = findChromium(config.screenshot.chromiumPath);
    this.queue = Promise.resolve(); // одновременно работает только один браузер
    this.cache = new Map(); // ключ (дата + отпечаток ДЗ) -> { at, buffer }
  }

  get available() {
    return Boolean(this.executable);
  }

  // Скриншоты нескольких дней за один вход на сайт.
  // days: [{ date: 'YYYY-MM-DD', subjects: ['Алгебра', ...], key: 'отпечаток ДЗ' }] → Map(date → Buffer JPEG)
  captureDays(days) {
    const run = this.queue.then(() => this.captureNow(days));
    this.queue = run.catch(() => {});
    return run;
  }

  async captureNow(days) {
    const result = new Map();
    const ttl = this.config.screenshot.cacheSeconds * 1000;
    const todo = [];
    for (const day of days) {
      const cached = this.cache.get(`${day.date}|${day.key || ''}`);
      if (cached && Date.now() - cached.at < ttl) result.set(day.date, cached.buffer);
      else todo.push(day);
    }
    if (!todo.length) return result;

    const byWeek = new Map();
    for (const day of todo) {
      const monday = mondayOf(day.date);
      if (!byWeek.has(monday)) byWeek.set(monday, []);
      byWeek.get(monday).push(day);
    }
    const started = Date.now();
    await this.withSite(async (site) => {
      for (const [monday, weekDays] of byWeek) {
        await site.open(monday);
        for (const day of weekDays) {
          try {
            const buffer = await this.shootDay(site.page, day);
            result.set(day.date, buffer);
            this.cache.set(`${day.date}|${day.key || ''}`, { at: Date.now(), buffer });
          } catch (error) {
            this.logger?.warn({ date: day.date, err: error.message }, 'Скриншот дня не получился');
          }
        }
      }
    });
    this.logger?.info({ days: result.size, seconds: Math.round((Date.now() - started) / 1000) }, 'Скриншоты дневника готовы');
    return result;
  }

  // Запасной способ получить дневник: открыть его на сайте и взять ответ, который сайт сам получил от сервера.
  // Работает, даже если у API поменялись правила, — сайт BilimClass всегда знает актуальные.
  // mondays: ['YYYY-MM-DD'] → Map(monday → data как у /clientoffice/diary)
  fetchWeeks(mondays) {
    const run = this.queue.then(() => this.withSite(async (site) => {
      const result = new Map();
      for (const monday of [...new Set(mondays)]) {
        const json = await site.open(monday, { render: false });
        result.set(monday, json?.data ?? json ?? {});
      }
      return result;
    }));
    this.queue = run.catch(() => {});
    return run;
  }

  // Открыть браузер, войти на сайт и выполнить task({ page, open(monday) })
  async withSite(task) {
    if (!this.executable) throw new Error('Chromium не найден — укажите CHROMIUM_PATH или установите chromium');
    const { chromium } = await import('playwright-core');
    const proxy = this.config.screenshot.proxy;
    const browser = await chromium.launch({
      ...(this.executable === BUNDLED ? {} : { executablePath: this.executable }),
      args: ['--disable-dev-shm-usage', '--no-first-run', '--mute-audio', '--disable-gpu'],
      ...(proxy ? { proxy: { server: proxy } } : {}),
    });
    try {
      const context = await browser.newContext({
        viewport: { width: 412, height: 915 },
        deviceScaleFactor: 2,
        isMobile: true,
        hasTouch: true,
        locale: 'ru-RU',
        timezoneId: this.config.timezone,
        userAgent: MOBILE_UA,
      });
      context.setDefaultTimeout(this.config.screenshot.timeoutMs);
      await context.addInitScript(() => {
        try {
          localStorage.setItem('language', 'ru');
        } catch {
          /* ignore */
        }
      });
      if (this.contextHook) await this.contextHook(context);
      await context.route(BLOCKED, (route) => route.abort());

      // Нужная неделя: подставляем её понедельник в запрос дневника, который делает сам сайт
      let targetMonday = null;
      await context.route(/\/clientoffice\/diary\?/, (route) => {
        const url = new URL(route.request().url());
        if (targetMonday) url.searchParams.set('date', toDMY(targetMonday));
        return route.fallback({ url: url.toString() });
      });

      const page = await context.newPage();
      const year = await this.login(page);
      return await task({
        page,
        open: (monday, opts) => {
          targetMonday = monday;
          return this.openDiary(page, year, monday, opts);
        },
      });
    } finally {
      await browser.close().catch(() => {});
    }
  }

  // Вход через обычную форму на сайте. Возвращает учебный год из адреса (/2026/schedule)
  async login(page) {
    const site = this.config.bilim.siteUrl;
    // ответ сервера на вход — в нём профиль ученика (класс, школа); пригодится, если API недоступно
    page.waitForResponse((r) => /\/api\/v2\/os\/login/.test(r.url()) && r.request().method() === 'POST', { timeout: 60000 })
      .then((r) => r.json())
      .then((body) => {
        if (body?.user_info) this.siteUserInfo = body.user_info;
      })
      .catch(() => {});
    await page.goto(`${site}/login`, { waitUntil: 'domcontentloaded' });
    await page.locator('input[type=password]').first().waitFor();
    await page.locator('input[type=text]').first().fill(this.config.bilim.login);
    await page.locator('input[type=password]').first().fill(this.config.bilim.password);
    await page.locator('form button[type=submit]').first().click();
    try {
      await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 30000 });
    } catch {
      throw new Error('не удалось войти на сайт BilimClass (неверный пароль или нужно подтверждение входа)');
    }
    const segment = new URL(page.url()).pathname.split('/')[1];
    return /^\d{4}$/.test(segment) ? segment : String(this.eduYear() || '');
  }

  // render: true — дождаться, пока сайт нарисует дневник (для скриншота);
  // render: false — вернуть сам ответ сервера (JSON дневника), рисовать не нужно
  async openDiary(page, year, monday, { render = true } = {}) {
    const site = this.config.bilim.siteUrl;
    const date = toDMY(monday);
    for (let attempt = 0; ; attempt += 1) {
      const loaded = page.waitForResponse(
        (r) => /\/clientoffice\/diary\?/.test(r.url()) && r.status() === 200 && new URL(r.url()).searchParams.get('date') === date,
        { timeout: this.config.screenshot.timeoutMs },
      );
      await page.goto(`${site}/${year ? `${year}/` : ''}diary`, { waitUntil: 'domcontentloaded' });
      const response = await loaded;
      if (render) {
        await page.locator('.bc-diary-day').first().waitFor();
        // сайт может догружать данные после первого ответа — ждём тишины в сети (но не дольше 8 секунд)
        await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {});
        await page.waitForTimeout(1500); // даём дорисовать ДЗ и иконки
        return null;
      }
      try {
        return await response.json(); // читаем сразу, пока страница не ушла дальше
      } catch (error) {
        if (attempt >= 1) throw error;
      }
    }
  }

  async prepare(page) {
    await page.addStyleTag({ content: PAGE_CSS });
    // прячем всё «висящее» поверх страницы: окна, баннеры, чат поддержки, кнопку «Сегодня»
    await page.evaluate(() => {
      for (const el of document.querySelectorAll('body *')) {
        const { position } = getComputedStyle(el);
        if ((position === 'fixed' || position === 'sticky') && !el.closest('.bc-diary-day')) {
          el.style.setProperty('display', 'none', 'important');
        }
      }
    });
  }

  // Всё, что мешает увидеть блок дня: полупрозрачность (анимация появления ещё не сработала)
  // и элементы поверх него (загрузчики, баннеры, окна). Возвращает, что было исправлено, — для журнала.
  async unveil(block) {
    return block.evaluate((el) => {
      const describe = (node) => `${node.tagName.toLowerCase()}${node.id ? `#${node.id}` : ''}${[...node.classList].slice(0, 3).map((c) => `.${c}`).join('')}`;
      const report = { hidden: [], faded: [] };
      for (let node = el; node && node !== document.documentElement; node = node.parentElement) {
        const cs = getComputedStyle(node);
        if (Number(cs.opacity) < 1) {
          node.style.setProperty('opacity', '1', 'important');
          report.faded.push(describe(node));
        }
        if (cs.visibility === 'hidden') node.style.setProperty('visibility', 'visible', 'important');
      }
      for (const child of el.querySelectorAll('*')) {
        if (getComputedStyle(child).opacity === '0') {
          child.style.setProperty('opacity', '1', 'important');
          report.faded.push(describe(child));
        }
      }
      // поверх блока ничего не должно лежать (в том числе прозрачное для мыши — поэтому временно включаем pointer-events)
      const probe = document.createElement('style');
      probe.textContent = '* { pointer-events: auto !important; }';
      document.head.append(probe);
      for (let round = 0; round < 5; round += 1) {
        const r = el.getBoundingClientRect();
        let changed = false;
        for (const fx of [0.08, 0.3, 0.5, 0.7, 0.92]) {
          for (const fy of [0.08, 0.3, 0.5, 0.7, 0.92]) {
            const x = r.left + r.width * fx;
            const y = r.top + r.height * fy;
            if (x < 0 || y < 0 || x >= window.innerWidth || y >= window.innerHeight) continue;
            const top = document.elementFromPoint(x, y);
            if (!top || el.contains(top) || top.contains(el)) continue;
            top.style.setProperty('display', 'none', 'important');
            report.hidden.push(describe(top));
            changed = true;
          }
        }
        if (!changed) break;
      }
      probe.remove();
      return report;
    });
  }

  async shootDay(page, day) {
    const label = diaryDateLabel(day.date);
    const block = page.locator('.bc-diary-day').filter({
      has: page.locator('.bc-dd__date', { hasText: new RegExp(`(^|\\D)${label}`) }),
    }).first();
    if (!(await block.count())) throw new Error(`на странице нет дня «${label}»`);
    await this.prepare(page);
    // проверка: на снимке должны быть все предметы, по которым есть ДЗ (иначе это не тот день)
    const text = normalize(await block.innerText());
    const missing = (day.subjects || []).filter((s) => !text.includes(normalize(s)));
    if (missing.length) throw new Error(`на странице дня нет предметов: ${missing.join(', ')}`);
    // снимок проверяем: на нём должен быть текст. Пустой — ждём, пока страница дорисуется, и снимаем снова
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      await block.scrollIntoViewIfNeeded().catch(() => {});
      await page.waitForTimeout(attempt === 1 ? 400 : 2000);
      const fixed = await this.unveil(block).catch(() => ({ hidden: [], faded: [] }));
      const buffer = await block.screenshot({ type: 'jpeg', quality: 90, animations: 'disabled' });
      const ink = await inkRatio(buffer);
      if (ink >= MIN_INK) {
        if (fixed.hidden.length || fixed.faded.length) this.logger?.info({ date: day.date, ...fixed }, 'Скриншот: убрал мешающие элементы');
        return buffer;
      }
      this.logger?.warn({ date: day.date, attempt, ink: Number(ink.toFixed(4)), ...fixed }, 'Скриншот дня получился пустым — пробую ещё раз');
    }
    throw new Error('скриншот получился пустым (сайт не дорисовал страницу)');
  }
}

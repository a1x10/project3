// Надёжное получение дневника: два независимых способа.
// 1) API BilimClass — быстро (с продлением входа и повторным входом при сбоях);
// 2) сайт BilimClass в браузере — медленнее, но работает, даже если у API поменялись правила.
// Если API сломалось, бот на время переключается на сайт, а потом снова пробует API.
import { BilimAuthError } from './client.js';

const PREFER_SITE_MS = 30 * 60 * 1000; // после сбоя API полчаса берём данные через сайт
const BATCH_WAIT_MS = 40; // недели, запрошенные почти одновременно, берём за один заход на сайт

export class ResilientBilimClient {
  constructor({ api, site = null, logger, onSwitch = () => {} }) {
    this.api = api;
    this.site = site;
    this.logger = logger;
    this.onSwitch = onSwitch; // уведомление: способ получения данных поменялся
    this.preferSiteUntil = 0;
    this.mode = 'api'; // 'api' | 'site'
    this.lastApiError = null;
    this.pending = new Map(); // monday -> [{ resolve, reject }]
    this.batchTimer = null;
  }

  // --- то, чем пользуются остальные части бота (как у BilimClassClient) ---
  get session() {
    if (this.api.session) return this.api.session;
    const info = this.site?.siteUserInfo;
    if (!info) return null;
    return { className: info.group?.name || '', schoolName: info.school?.name || '', eduYear: null, fullName: [info.surname, info.firstname].filter(Boolean).join(' ') };
  }

  get loggedIn() {
    return this.api.loggedIn;
  }

  get authFailedAt() {
    return this.api.authFailedAt;
  }

  get authFailMessage() {
    return this.api.authFailMessage;
  }

  login() {
    return this.api.login();
  }

  setCredentials(credentials) {
    this.api.setCredentials(credentials);
    this.preferSiteUntil = 0;
  }

  get siteAvailable() {
    return Boolean(this.site?.available);
  }

  setMode(mode, reason) {
    if (this.mode === mode) return;
    this.mode = mode;
    this.logger?.warn({ reason }, mode === 'site' ? 'API BilimClass сбоит — беру дневник через сайт' : 'API BilimClass снова работает');
    this.onSwitch(mode, reason);
  }

  async getWeek(mondayIso) {
    if (this.siteAvailable && Date.now() < this.preferSiteUntil) return this.viaSite(mondayIso);
    try {
      const data = await this.api.getWeek(mondayIso);
      this.lastApiError = null;
      this.setMode('api');
      return data;
    } catch (error) {
      this.lastApiError = error;
      // неверный пароль сайт тоже не пустит; без браузера запасного пути нет
      if (error instanceof BilimAuthError || !this.siteAvailable) throw error;
      this.preferSiteUntil = Date.now() + PREFER_SITE_MS;
      this.setMode('site', error.message);
      return this.viaSite(mondayIso);
    }
  }

  // Несколько недель, запрошенных одновременно, — за один вход на сайт
  viaSite(mondayIso) {
    return new Promise((resolve, reject) => {
      if (!this.pending.has(mondayIso)) this.pending.set(mondayIso, []);
      this.pending.get(mondayIso).push({ resolve, reject });
      if (!this.batchTimer) this.batchTimer = setTimeout(() => this.flush(), BATCH_WAIT_MS);
    });
  }

  async flush() {
    this.batchTimer = null;
    const batch = this.pending;
    this.pending = new Map();
    try {
      const weeks = await this.site.fetchWeeks([...batch.keys()]);
      for (const [monday, waiters] of batch) {
        for (const w of waiters) w.resolve(weeks.get(monday) || { days: [] });
      }
    } catch (error) {
      const failure = new Error(`Дневник недоступен ни через API (${this.lastApiError?.message || 'ошибка'}), ни через сайт (${error.message})`);
      for (const waiters of batch.values()) for (const w of waiters) w.reject(failure);
    }
  }

  // Файлы к ДЗ есть только в API; если оно не работает — файлы просто не пересылаются
  async getHomeworkFiles(uuid) {
    return this.api.getHomeworkFiles(uuid);
  }

  status() {
    return { mode: this.mode, siteAvailable: this.siteAvailable, apiError: this.lastApiError?.message || null };
  }
}

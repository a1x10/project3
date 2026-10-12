// Клиент неофициального API BilimClass (bilimclass.kz).
// Эндпоинты взяты из веб-версии дневника: вход, недели, дневник на неделю, файлы к ДЗ.
import { randomUUID } from 'node:crypto';
import { toDMY } from '../utils/dates.js';

export class BilimAuthError extends Error {}
export class BilimApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
// Не пробуем войти с неверным паролем чаще, чем раз в 30 минут — чтобы не заблокировали аккаунт
const AUTH_RETRY_PAUSE_MS = 30 * 60 * 1000;

export class BilimClassClient {
  constructor({ apiUrl, siteUrl, login, password, schoolId, groupId, eduYear, timeoutMs = 20000, deviceId, logger, fetchImpl }) {
    this.apiUrl = apiUrl;
    this.siteUrl = siteUrl;
    this.credentials = { login, password };
    this.overrides = { schoolId, groupId, eduYear };
    this.timeoutMs = timeoutMs;
    this.deviceId = deviceId || randomUUID();
    this.logger = logger;
    this.fetch = fetchImpl || globalThis.fetch;

    this.token = null;
    this.refreshToken = null;
    this.expiresAt = 0; // когда истекает токен (если сервер сообщил), мс
    this.session = null; // { schoolId, groupId, eduYear, userId, fullName, className, schoolName }
    this.loginPromise = null;
    this.refreshPromise = null;
    this.authFailedAt = 0;
    this.authFailMessage = '';
  }

  // Новые логин/пароль (из панели управления): сбрасываем сессию и паузу после неудачного входа
  setCredentials({ login, password }) {
    this.credentials = { login: login ?? this.credentials.login, password: password ?? this.credentials.password };
    this.token = null;
    this.refreshToken = null;
    this.expiresAt = 0;
    this.authFailedAt = 0;
    this.authFailMessage = '';
  }

  // Время жизни токена: сервер присылает exp_time; формат точно не известен — разбираем осторожно
  static parseExpiry(value, now = Date.now()) {
    if (value == null || value === '') return 0;
    let ms = 0;
    if (typeof value === 'number' || /^\d+$/.test(String(value))) {
      const n = Number(value);
      if (n > 1e12) ms = n; // миллисекунды
      else if (n > 1e9) ms = n * 1000; // секунды unix
      else ms = now + n * 1000; // «через N секунд»
    } else {
      ms = Date.parse(String(value).replace(' ', 'T'));
    }
    // неправдоподобные значения игнорируем — тогда полагаемся на ответ 426 от сервера
    if (!Number.isFinite(ms) || ms < now + 60_000 || ms > now + 90 * 86400_000) return 0;
    return ms;
  }

  applyTokens(body) {
    this.token = body.access_token;
    if (body.refresh_token) this.refreshToken = body.refresh_token;
    this.expiresAt = BilimClassClient.parseExpiry(body.exp_time ?? body.expires_in);
  }

  headers(extra = {}) {
    return {
      'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
      Accept: 'application/json',
      'Content-Type': 'application/json',
      'X-Localization': 'ru',
      'X-Mathrix': this.deviceId,
      Origin: this.siteUrl,
      Referer: `${this.siteUrl}/`,
      ...extra,
    };
  }

  async rawRequest(url, init) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await this.fetch(url, { ...init, signal: controller.signal });
      const text = await response.text();
      let body = null;
      try {
        body = text ? JSON.parse(text) : null;
      } catch {
        body = null;
      }
      return { status: response.status, body, text };
    } catch (error) {
      if (error.name === 'AbortError') throw new BilimApiError(`BilimClass не ответил за ${this.timeoutMs / 1000} с`, 0);
      throw new BilimApiError(`Нет связи с BilimClass: ${error.cause?.code || error.message}`, 0);
    } finally {
      clearTimeout(timer);
    }
  }

  get loggedIn() {
    return Boolean(this.token && this.session);
  }

  async login() {
    // одновременные запросы ждут один и тот же вход
    if (!this.loginPromise) {
      this.loginPromise = this.doLogin().finally(() => {
        this.loginPromise = null;
      });
    }
    return this.loginPromise;
  }

  async doLogin() {
    const { login, password } = this.credentials;
    if (!login || !password) throw new BilimAuthError('Не заданы логин и пароль BilimClass — укажите их в панели («Ключи и доступ») или в .env (BILIM_LOGIN / BILIM_PASSWORD)');
    if (this.authFailedAt && Date.now() - this.authFailedAt < AUTH_RETRY_PAUSE_MS) {
      throw new BilimAuthError(this.authFailMessage);
    }

    const { status, body } = await this.rawRequest(`${this.apiUrl}/api/v2/os/login`, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify({ login: login.trim(), password }),
    });

    if (status !== 200 || !body?.access_token) {
      const serverMessage = body?.message || body?.error || '';
      // 4xx при входе = неверные данные (BilimClass отвечает 412 "Неправильный логин или пароль")
      if (status >= 400 && status < 500 && status !== 426 && status !== 429) {
        this.authFailedAt = Date.now();
        this.authFailMessage = `BilimClass не пустил: ${serverMessage || `HTTP ${status}`}. Проверьте BILIM_LOGIN и BILIM_PASSWORD`;
        throw new BilimAuthError(this.authFailMessage);
      }
      throw new BilimApiError(`Ошибка входа в BilimClass (HTTP ${status}${serverMessage ? `: ${serverMessage}` : ''})`, status);
    }

    this.authFailedAt = 0;
    this.applyTokens(body);
    this.session = this.extractSession(body.user_info || {});
    this.logger?.info(
      { school: this.session.schoolName, class: this.session.className, eduYear: this.session.eduYear },
      'Вход в BilimClass выполнен',
    );
    return this.session;
  }

  // Продление входа без пароля — так же делает сам сайт BilimClass, когда сервер отвечает 426
  async refresh() {
    if (!this.refreshPromise) {
      this.refreshPromise = this.doRefresh().finally(() => {
        this.refreshPromise = null;
      });
    }
    return this.refreshPromise;
  }

  async doRefresh() {
    if (!this.refreshToken) return false;
    try {
      const { status, body } = await this.rawRequest(`${this.apiUrl}/api/v2/os/refresh_token`, {
        method: 'POST',
        headers: this.headers(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
        body: JSON.stringify({ refreshToken: this.refreshToken }),
      });
      if (status === 200 && body?.access_token) {
        this.applyTokens(body);
        this.logger?.info('Вход в BilimClass продлён');
        return true;
      }
      this.logger?.info({ status }, 'Продлить вход не удалось — войду заново');
    } catch (error) {
      this.logger?.warn({ err: error.message }, 'Продлить вход не удалось — войду заново');
    }
    this.refreshToken = null;
    return false;
  }

  // Свежий токен: продлеваем заранее, если знаем срок; не получилось — входим заново
  async ensureFreshToken() {
    if (!this.loggedIn) {
      await this.login();
      return;
    }
    if (this.expiresAt && Date.now() > this.expiresAt - 60_000) {
      if (!(await this.refresh())) {
        this.token = null;
        await this.login();
      }
    }
  }

  extractSession(info) {
    const school = info.school || {};
    const group = info.group || {};
    const now = new Date();
    let eduYear = now.getMonth() >= 7 ? now.getFullYear() : now.getFullYear() - 1;
    const current = (school.eduYears || []).find((y) => y?.isCurrent);
    if (current?.eduYear) eduYear = Number(current.eduYear);

    const session = {
      userId: info.userId ?? info.id ?? null,
      schoolId: this.overrides.schoolId || info.school_id || info.schoolId || school.id || null,
      groupId: this.overrides.groupId || group.id || info.groupId || null,
      eduYear: Number(this.overrides.eduYear) || eduYear,
      fullName: [info.surname, info.firstname].filter(Boolean).join(' '),
      className: group.name || '',
      schoolName: school.name || '',
    };
    if (!session.schoolId) {
      // Логируем только названия полей (без значений), чтобы помочь с настройкой
      this.logger?.warn({ fields: Object.keys(info) }, 'Не удалось определить школу из профиля. Укажите BILIM_SCHOOL_ID в .env');
    }
    return session;
  }

  // GET с авторизацией.
  // 426 — токен устарел: продлеваем его (как сайт), не вышло — входим заново по паролю.
  // 401/403 — сессия недействительна: входим заново. 5xx/429/обрыв — повтор с паузой.
  async get(path, params = {}, { retries = 2 } = {}) {
    await this.ensureFreshToken();
    let relogged = false;
    let refreshed = false;
    for (let attempt = 0; ; attempt += 1) {
      const query = new URLSearchParams(
        Object.entries(params).filter(([, v]) => v !== null && v !== undefined && v !== '').map(([k, v]) => [k, String(v)]),
      );
      const url = `${this.apiUrl}${path}${query.size ? `?${query}` : ''}`;
      let result;
      try {
        result = await this.rawRequest(url, {
          method: 'GET',
          headers: this.headers({ Authorization: `Bearer ${this.token}`, 'x-school-id': String(this.session?.schoolId ?? '') }),
        });
      } catch (error) {
        if (attempt < retries) {
          await sleep(1000 * 2 ** attempt);
          continue;
        }
        throw error;
      }

      const { status, body } = result;
      if (status === 200) return body?.data ?? body;
      if (status === 426 && !refreshed) {
        refreshed = true;
        if (!(await this.refresh())) {
          relogged = true;
          this.token = null;
          await this.login();
        }
        continue;
      }
      if ((status === 401 || status === 403 || status === 426) && !relogged) {
        relogged = true;
        this.token = null;
        await this.login();
        continue;
      }
      if ((status >= 500 || status === 429) && attempt < retries) {
        await sleep(1500 * 2 ** attempt);
        continue;
      }
      if (status === 426) {
        throw new BilimApiError('BilimClass не принимает вход даже после повторного входа (HTTP 426)', status);
      }
      throw new BilimApiError(`BilimClass: ${body?.message || `HTTP ${status}`} (${path})`, status);
    }
  }

  // Дневник на неделю. mondayIso — понедельник недели 'YYYY-MM-DD'
  async getWeek(mondayIso) {
    await this.ensureFreshToken();
    const { schoolId, eduYear, groupId } = this.session;
    const data = await this.get('/api/v4/os/clientoffice/diary', { schoolId, eduYear, date: toDMY(mondayIso), groupId });
    return data || {};
  }

  // Метаданные файлов, прикреплённых к ДЗ (ссылки короткоживущие)
  async getHomeworkFiles(homeworkUuid) {
    if (!homeworkUuid) return [];
    await this.ensureFreshToken();
    const { schoolId, eduYear } = this.session;
    const data = await this.get('/api/v4/os/clientoffice/homeworks/simple-homework/info', { homeworkUuid, schoolId, eduYear });
    return Array.isArray(data?.files) ? data.files : [];
  }
}

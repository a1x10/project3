// Настройки, которые можно менять на ходу — из панели управления и командами в WhatsApp, без перезапуска.
// Значения из .env — это «по умолчанию». Изменения хранятся в data/settings.json и применяются поверх .env
// прямо в общий объект config, поэтому все части бота сразу видят новые значения.
import { EventEmitter } from 'node:events';
import fs from 'node:fs';
import path from 'node:path';
import { ConfigError, defaultDays, normalizePhone, parseClock } from './config.js';

export { defaultDays };
import { formatClock, WEEKDAYS_SHORT } from './utils/dates.js';

export const DAY_MODES = ['lessons', 'time', 'off'];
export const DAY_SCOPES = ['new', 'tomorrow'];

// «Пн: после уроков» / «Вс: 18:00, только на завтра» / «Сб: выкл»
export function describeDay(weekday, day, { delay } = {}) {
  const name = WEEKDAYS_SHORT[weekday - 1];
  if (!day || day.mode === 'off') return `${name}: не присылать`;
  const when = day.mode === 'lessons'
    ? `после уроков${delay != null ? ` (+${delay} мин)` : ''}${day.time != null ? `, без уроков — ${formatClock(day.time)}` : ''}`
    : `в ${formatClock(day.time)}`;
  return `${name}: ${when}${day.scope === 'tomorrow' ? ', только на завтра' : ''}`;
}

const isIso = (v) => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) && !Number.isNaN(Date.parse(`${v}T00:00:00Z`));

// --- типы значений: parse проверяет и приводит к внутреннему виду, format — для панели ---
const T = {
  bool: { parse: (v) => {
    if (typeof v === 'boolean') return v;
    if (/^(1|true|yes|on|да|вкл)$/i.test(String(v))) return true;
    if (/^(0|false|no|off|нет|выкл)$/i.test(String(v))) return false;
    throw new ConfigError('ожидается да/нет');
  } },
  int: (min, max) => ({ parse: (v) => {
    const n = Number(v);
    if (!Number.isInteger(n) || n < min || n > max) throw new ConfigError(`ожидается целое число от ${min} до ${max}`);
    return n;
  } }),
  oneOf: (...allowed) => ({ parse: (v) => {
    const s = String(v).toLowerCase();
    if (!allowed.includes(s)) throw new ConfigError(`допустимо: ${allowed.join(', ')}`);
    return s;
  }, options: allowed }),
  text: (max) => ({ parse: (v) => {
    const s = String(v ?? '').replace(/[\x00-\x1f]/g, ' ').trim();
    if (!s || s.length > max) throw new ConfigError(`ожидается текст до ${max} символов`);
    return s;
  } }),
  clock: { parse: (v) => {
    if (v == null || v === '') return null;
    if (typeof v === 'number' && Number.isInteger(v) && v >= 0 && v < 24 * 60) return v;
    return parseClock(String(v));
  }, format: (m) => (m == null ? '' : formatClock(m)) },
  range: { parse: (v) => {
    if (v && typeof v === 'object') return { from: T.clock.parse(v.from) ?? 0, to: T.clock.parse(v.to) ?? 0 };
    const m = /^(\S+)\s*-\s*(\S+)$/.exec(String(v));
    if (!m) throw new ConfigError('ожидается ЧЧ:ММ-ЧЧ:ММ');
    return { from: parseClock(m[1]), to: parseClock(m[2]) };
  }, format: (r) => `${formatClock(r.from)}-${formatClock(r.to)}` },
  words: { parse: (v) => {
    const list = (Array.isArray(v) ? v : String(v).split(',')).map((w) => String(w).trim().toLowerCase()).filter(Boolean);
    if (list.length > 20 || list.some((w) => w.length > 30)) throw new ConfigError('не больше 20 слов');
    return [...new Set(list)];
  }, format: (l) => l.join(', ') },
  phones: { parse: (v) => {
    const list = (Array.isArray(v) ? v : String(v).split(',')).map(normalizePhone).filter(Boolean);
    if (list.some((p) => !/^\d{10,15}$/.test(p))) throw new ConfigError('номер: только цифры с кодом страны, например 77011234567');
    return [...new Set(list)];
  }, format: (l) => l.join(', ') },
  days: { parse: (v) => {
    if (!v || typeof v !== 'object') throw new ConfigError('ожидается план на 7 дней');
    const days = {};
    for (let d = 1; d <= 7; d += 1) {
      const day = v[d] ?? v[String(d)] ?? (Array.isArray(v) ? v[d - 1] : null);
      if (!day || !DAY_MODES.includes(day.mode)) throw new ConfigError(`${WEEKDAYS_SHORT[d - 1]}: режим ${DAY_MODES.join('/')}`);
      const time = T.clock.parse(day.time);
      if (day.mode === 'time' && time == null) throw new ConfigError(`${WEEKDAYS_SHORT[d - 1]}: укажите время`);
      const scope = day.scope || 'new';
      if (!DAY_SCOPES.includes(scope)) throw new ConfigError(`${WEEKDAYS_SHORT[d - 1]}: что присылать — ${DAY_SCOPES.join('/')}`);
      days[d] = { mode: day.mode, time, scope };
    }
    return days;
  }, format: (days) => Object.fromEntries(Object.entries(days).map(([d, day]) => [d, { ...day, time: T.clock.format(day.time) }])) },
  pause: { parse: (v) => {
    if (v == null || v === '' || v === false) return null;
    if (v === 'forever' || v === true) return 'forever';
    if (isIso(v)) return v;
    throw new ConfigError('пауза: дата ГГГГ-ММ-ДД или forever');
  } },
  dates: { parse: (v) => {
    const list = Array.isArray(v) ? v : String(v || '').split(',').map((s) => s.trim()).filter(Boolean);
    if (list.some((d) => !isIso(d))) throw new ConfigError('даты в формате ГГГГ-ММ-ДД');
    return [...new Set(list)].sort().slice(-60);
  } },
};

// Что можно менять на ходу. group — раздел панели.
export const FIELDS = {
  'schedule.days': { type: T.days, group: 'schedule', label: 'Рассылка по дням недели' },
  'schedule.digestDelayMinutes': { type: T.int(0, 360), group: 'schedule', label: 'Через сколько минут после уроков' },
  'schedule.remindTomorrow': { type: T.bool, group: 'schedule', label: 'Каждый день присылать «ДЗ на завтра»' },
  'schedule.skipEmptyDigest': { type: T.bool, group: 'schedule', label: 'Не присылать, если нового нет' },
  'schedule.notifyChanges': { type: T.bool, group: 'schedule', label: 'Сообщать о новых ДЗ в течение дня' },
  'schedule.pollIntervalMinutes': { type: T.int(10, 1440), group: 'schedule', label: 'Проверять дневник каждые N минут' },
  'schedule.activeHours': { type: T.range, group: 'schedule', label: 'Когда можно писать в группу' },
  'schedule.morningTime': { type: T.clock, group: 'schedule', label: 'Утреннее напоминание (пусто — выкл)' },
  'schedule.pausedUntil': { type: T.pause, group: 'schedule', label: 'Пауза рассылок' },
  'schedule.skipDates': { type: T.dates, group: 'schedule', label: 'Дни без рассылки' },
  'features.homeworkPhoto': { type: T.oneOf('screenshot', 'card', 'text'), group: 'schedule', label: 'Как присылать ДЗ' },
  'features.sendFiles': { type: T.bool, group: 'schedule', label: 'Пересылать файлы к ДЗ' },
  'ai.mode': { type: T.oneOf('smart', 'mention', 'off'), group: 'ai', label: 'Когда ИИ отвечает в группе' },
  'ai.style': { type: T.oneOf('tutor', 'hints'), group: 'ai', label: 'Стиль помощи' },
  'ai.humanLike': { type: T.bool, group: 'ai', label: 'Отвечать по-человечески (печатает, пишет короткими сообщениями)' },
  'ai.voice': { type: T.oneOf('all', 'direct', 'off'), group: 'ai', label: 'Голосовые вопросы' },
  'ai.images': { type: T.bool, group: 'ai', label: 'Понимать фото заданий' },
  'ai.botName': { type: T.text(40), group: 'ai', label: 'Имя бота' },
  'ai.wakeWords': { type: T.words, group: 'ai', label: 'Слова-обращения' },
  'ai.userLimit': { type: T.int(1, 1000), group: 'ai', label: 'Вопросов от одного человека за окно' },
  'ai.dailyLimit': { type: T.int(1, 100000), group: 'ai', label: 'Ответов ИИ в сутки' },
  'whatsapp.privateChat': { type: T.oneOf('members', 'all', 'admins', 'off'), group: 'access', label: 'Кто может писать боту в личку' },
  'whatsapp.admins': { type: T.phones, group: 'access', label: 'Номера админов' },
  'whatsapp.groupAdminsAreBotAdmins': { type: T.bool, group: 'access', label: 'Админы группы — тоже админы бота' },
  'notify.whatsapp': { type: T.bool, group: 'notify', label: 'Технические уведомления админам в WhatsApp' },
  'notify.dailyReport': { type: T.bool, group: 'notify', label: 'Вечерний отчёт админу' },
};

const getPath = (obj, p) => p.split('.').reduce((o, k) => o?.[k], obj);
function setPath(obj, p, value) {
  const keys = p.split('.');
  const last = keys.pop();
  const target = keys.reduce((o, k) => (o[k] ??= {}), obj);
  target[last] = value;
}

// Запись JSON атомарно (временный файл + rename) и только для владельца
export function writeJsonFile(file, data, mode = 0o600) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(data, null, 1), { mode });
  fs.renameSync(tmp, file);
  try {
    fs.chmodSync(file, mode);
  } catch {
    /* файловая система без прав доступа */
  }
}

export function readJsonFile(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (error) {
    if (error.code !== 'ENOENT') {
      try {
        fs.renameSync(file, `${file}.corrupt-${Date.now()}`);
      } catch {
        /* ignore */
      }
    }
    return fallback;
  }
}

export class Settings extends EventEmitter {
  constructor({ config, file = config.dataDir ? path.join(config.dataDir, 'settings.json') : null, logger }) {
    super();
    this.config = config;
    this.file = file;
    this.logger = logger;
    // значения из .env — чтобы можно было вернуть «как было»
    this.defaults = Object.fromEntries(Object.keys(FIELDS).map((p) => [p, structuredClone(getPath(config, p))]));
    this.overrides = {};
  }

  load() {
    const saved = this.file ? readJsonFile(this.file, {}) : {};
    for (const [p, value] of Object.entries(saved.values || {})) {
      if (!FIELDS[p]) continue;
      try {
        this.overrides[p] = FIELDS[p].type.parse(value);
      } catch (error) {
        this.logger?.warn({ setting: p, err: error.message }, 'Сохранённая настройка не подходит — беру из .env');
      }
    }
    for (const [p, value] of Object.entries(this.overrides)) this.applyValue(p, value);
    return this;
  }

  applyValue(p, value) {
    setPath(this.config, p, structuredClone(value));
    if (p === 'features.homeworkPhoto') this.config.features.homeworkImage = value !== 'text';
  }

  get(p) {
    return getPath(this.config, p);
  }

  // Изменить несколько настроек сразу: либо все проверены и применены, либо ничего
  update(patch, { by = 'panel' } = {}) {
    const parsed = {};
    for (const [p, raw] of Object.entries(patch || {})) {
      const field = FIELDS[p];
      if (!field) throw new ConfigError(`неизвестная настройка ${p}`);
      try {
        parsed[p] = field.type.parse(raw);
      } catch (error) {
        throw new ConfigError(`${field.label}: ${error.message}`);
      }
    }
    const changed = [];
    for (const [p, value] of Object.entries(parsed)) {
      if (JSON.stringify(value) === JSON.stringify(this.get(p))) continue;
      this.overrides[p] = value;
      this.applyValue(p, value);
      changed.push(p);
    }
    if (changed.length) {
      this.save();
      this.logger?.info({ changed, by }, 'Настройки изменены');
      this.emit('change', changed);
    }
    return changed;
  }

  // Вернуть значения из .env
  reset(paths = Object.keys(this.overrides)) {
    const changed = [];
    for (const p of paths) {
      if (!(p in this.overrides)) continue;
      delete this.overrides[p];
      this.applyValue(p, this.defaults[p]);
      changed.push(p);
    }
    if (changed.length) {
      this.save();
      this.emit('change', changed);
    }
    return changed;
  }

  save() {
    if (!this.file) return;
    try {
      writeJsonFile(this.file, { version: 1, updatedAt: new Date().toISOString(), values: this.overrides }, 0o644);
    } catch (error) {
      this.logger?.error({ err: error.message }, 'Не удалось сохранить настройки');
    }
  }

  // Для панели: значения в удобном виде, описание и признак «изменено относительно .env»
  describe() {
    return Object.entries(FIELDS).map(([p, field]) => {
      const format = field.type.format || ((v) => v);
      return {
        path: p,
        group: field.group,
        label: field.label,
        options: field.type.options,
        value: format(this.get(p)),
        default: format(this.defaults[p]),
        overridden: p in this.overrides,
      };
    });
  }

  // --- удобные действия с расписанием ---
  setDay(weekdays, change) {
    const days = structuredClone(this.config.schedule.days);
    for (const d of weekdays) days[d] = { ...days[d], ...change };
    return this.update({ 'schedule.days': days }, { by: 'whatsapp' });
  }

  pause(until = 'forever') {
    return this.update({ 'schedule.pausedUntil': until }, { by: 'whatsapp' });
  }

  resume() {
    return this.update({ 'schedule.pausedUntil': null }, { by: 'whatsapp' });
  }

  skipDate(iso, skip = true) {
    const list = new Set(this.config.schedule.skipDates);
    if (skip) list.add(iso);
    else list.delete(iso);
    return this.update({ 'schedule.skipDates': [...list] }, { by: 'whatsapp' });
  }
}

// Рассылки на паузе в этот день? (пауза действует по дату включительно)
export function isPaused(schedule, iso) {
  const until = schedule.pausedUntil;
  if (!until) return false;
  return until === 'forever' || iso <= until;
}

// Почему сегодня бот молчит (или null, если всё по плану)
export function quietReason(schedule, iso, weekday) {
  if (isPaused(schedule, iso)) {
    return schedule.pausedUntil === 'forever' ? 'рассылки на паузе' : `рассылки на паузе до ${schedule.pausedUntil}`;
  }
  if (schedule.skipDates?.includes(iso)) return 'сегодня рассылка пропущена';
  if (schedule.days?.[weekday]?.mode === 'off') return 'в этот день недели рассылка выключена';
  return null;
}

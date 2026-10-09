// Загрузка и проверка настроек из .env / переменных окружения.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

export class ConfigError extends Error {}

function loadDotEnv() {
  const file = process.env.ENV_FILE || path.join(ROOT, '.env');
  if (fs.existsSync(file)) process.loadEnvFile(file);
}

const str = (env, name, def = '') => (env[name] ?? def).toString().trim();

function bool(env, name, def) {
  const raw = str(env, name);
  if (!raw) return def;
  if (/^(1|true|yes|on|да|вкл)$/i.test(raw)) return true;
  if (/^(0|false|no|off|нет|выкл)$/i.test(raw)) return false;
  throw new ConfigError(`${name}: ожидается true/false, получено "${raw}"`);
}

function int(env, name, def, { min = -Infinity, max = Infinity } = {}) {
  const raw = str(env, name);
  if (!raw) return def;
  const value = Number(raw);
  if (!Number.isInteger(value) || value < min || value > max) {
    throw new ConfigError(`${name}: ожидается целое число от ${min} до ${max}, получено "${raw}"`);
  }
  return value;
}

function oneOf(env, name, def, allowed) {
  const raw = str(env, name, def).toLowerCase();
  if (!allowed.includes(raw)) throw new ConfigError(`${name}: допустимо ${allowed.join(' | ')}, получено "${raw}"`);
  return raw;
}

const list = (env, name, def = '') =>
  str(env, name, def).split(',').map((s) => s.trim()).filter(Boolean);

// "18:00" -> минуты от полуночи; пустая строка -> null (выключено)
export function parseClock(value, name = 'time') {
  if (!value) return null;
  const m = /^([01]?\d|2[0-3]):([0-5]\d)$/.exec(value.trim());
  if (!m) throw new ConfigError(`${name}: ожидается время ЧЧ:ММ, получено "${value}"`);
  return Number(m[1]) * 60 + Number(m[2]);
}

function clockRange(env, name, def) {
  const raw = str(env, name, def);
  const m = /^(\S+)\s*-\s*(\S+)$/.exec(raw);
  if (!m) throw new ConfigError(`${name}: ожидается диапазон ЧЧ:ММ-ЧЧ:ММ, получено "${raw}"`);
  return { from: parseClock(m[1], name), to: parseClock(m[2], name) };
}

// Номер телефона -> только цифры с кодом страны (77011234567). Местный формат 8701... -> 7701...
export function normalizePhone(value) {
  const digits = String(value || '').replace(/\D/g, '');
  return /^8\d{10}$/.test(digits) ? `7${digits.slice(1)}` : digits;
}

export function buildConfig(env = process.env) {
  const timezone = str(env, 'BOT_TIMEZONE', 'Asia/Almaty');
  try {
    new Intl.DateTimeFormat('ru', { timeZone: timezone });
  } catch {
    throw new ConfigError(`BOT_TIMEZONE: неизвестный часовой пояс "${timezone}"`);
  }

  const config = {
    root: ROOT,
    dataDir: path.resolve(ROOT, str(env, 'DATA_DIR', './data')),
    logLevel: str(env, 'LOG_LEVEL', 'info'),
    timezone,

    bilim: {
      login: str(env, 'BILIM_LOGIN'),
      password: env.BILIM_PASSWORD ?? '',
      apiUrl: str(env, 'BILIM_API_URL', 'https://api.bilimclass.kz').replace(/\/+$/, ''),
      siteUrl: str(env, 'BILIM_SITE_URL', 'https://www.bilimclass.kz').replace(/\/+$/, ''),
      // Необязательные ручные переопределения, если автоопределение по профилю не сработало
      schoolId: str(env, 'BILIM_SCHOOL_ID'),
      groupId: str(env, 'BILIM_GROUP_ID'),
      eduYear: str(env, 'BILIM_EDU_YEAR'),
      timeoutMs: int(env, 'BILIM_TIMEOUT_SECONDS', 20, { min: 5, max: 120 }) * 1000,
    },

    whatsapp: {
      authDir: '',
      groupIds: list(env, 'WA_GROUP_IDS'),
      groupName: str(env, 'WA_GROUP_NAME'),
      pairingNumber: normalizePhone(str(env, 'WA_PAIRING_NUMBER')),
      admins: list(env, 'ADMIN_NUMBERS').map(normalizePhone).filter(Boolean),
      groupAdminsAreBotAdmins: bool(env, 'GROUP_ADMINS_ARE_BOT_ADMINS', true),
      privateChat: oneOf(env, 'PRIVATE_CHAT', 'members', ['members', 'all', 'admins', 'off']),
      sendDelayMs: int(env, 'SEND_DELAY_MS', 1500, { min: 300, max: 30000 }),
    },

    groq: {
      apiKey: str(env, 'GROQ_API_KEY'),
      baseUrl: str(env, 'GROQ_BASE_URL', 'https://api.groq.com/openai/v1').replace(/\/+$/, ''),
      model: str(env, 'GROQ_MODEL', 'openai/gpt-oss-120b'),
      fastModel: str(env, 'GROQ_FAST_MODEL', 'openai/gpt-oss-20b'),
      visionModel: str(env, 'GROQ_VISION_MODEL', 'qwen/qwen3.8-27b'),
      whisperModel: str(env, 'GROQ_WHISPER_MODEL', 'whisper-large-v3-turbo'),
      fallbackModels: list(env, 'GROQ_FALLBACK_MODELS', 'openai/gpt-oss-20b'),
      timeoutMs: int(env, 'GROQ_TIMEOUT_SECONDS', 60, { min: 10, max: 300 }) * 1000,
    },

    schedule: {
      digestTime: parseClock(str(env, 'DIGEST_TIME', '18:00'), 'DIGEST_TIME'),
      morningTime: parseClock(str(env, 'MORNING_TIME', ''), 'MORNING_TIME'),
      weeklyTime: parseClock(str(env, 'WEEKLY_TIME', ''), 'WEEKLY_TIME'),
      weeklyDay: int(env, 'WEEKLY_DAY', 7, { min: 1, max: 7 }),
      pollIntervalMinutes: int(env, 'POLL_INTERVAL_MINUTES', 30, { min: 10, max: 24 * 60 }),
      activeHours: clockRange(env, 'ACTIVE_HOURS', '07:00-22:00'),
      catchUpMinutes: int(env, 'CATCH_UP_MINUTES', 180, { min: 0, max: 24 * 60 }),
      notifyChanges: bool(env, 'NOTIFY_CHANGES', true),
      skipEmptyDigest: bool(env, 'SKIP_EMPTY_DIGEST', false),
    },

    features: {
      // due — ДЗ записано в дневнике на день, к которому его нужно сделать (так показывает BilimClass);
      // assigned — ДЗ записано на урок, где его задали, срок — следующий урок по предмету
      homeworkAttachedTo: oneOf(env, 'HOMEWORK_ATTACHED_TO', 'due', ['due', 'assigned']),
      sendFiles: bool(env, 'SEND_FILES', true),
      maxFileMb: int(env, 'MAX_FILE_MB', 30, { min: 1, max: 100 }),
      commandPrefix: str(env, 'COMMAND_PREFIX', '!'),
    },

    ai: {
      mode: oneOf(env, 'AI_MODE', 'smart', ['smart', 'mention', 'off']),
      style: oneOf(env, 'AI_STYLE', 'tutor', ['tutor', 'hints']),
      voice: oneOf(env, 'AI_VOICE', 'all', ['all', 'direct', 'off']),
      images: bool(env, 'AI_IMAGES', true),
      botName: str(env, 'BOT_NAME', 'Помощник'),
      wakeWords: list(env, 'WAKE_WORDS', 'бот,ботик,ии,помощник').map((w) => w.toLowerCase()),
      maxVoiceSeconds: int(env, 'MAX_VOICE_SECONDS', 120, { min: 5, max: 900 }),
      userLimit: int(env, 'AI_USER_LIMIT', 8, { min: 1, max: 1000 }),
      userWindowMinutes: int(env, 'AI_USER_WINDOW_MINUTES', 10, { min: 1, max: 24 * 60 }),
      dailyLimit: int(env, 'AI_DAILY_LIMIT', 400, { min: 1, max: 100000 }),
      historySize: int(env, 'AI_HISTORY_SIZE', 14, { min: 0, max: 60 }),
      maxAnswerChars: int(env, 'AI_MAX_ANSWER_CHARS', 1800, { min: 300, max: 20000 }),
    },

    http: {
      port: int(env, 'HTTP_PORT', 3000, { min: 0, max: 65535 }),
      host: str(env, 'HTTP_HOST', '127.0.0.1'),
      token: str(env, 'HTTP_TOKEN'),
    },
  };

  config.whatsapp.authDir = path.join(config.dataDir, 'wa-auth');
  if (config.ai.mode !== 'off' && !config.groq.apiKey) config.ai.mode = 'off';
  return config;
}

// fatal — без этого запуск бессмысленен, warnings — бот запустится, но часть функций отключена
export function validateForStart(config) {
  const fatal = [];
  const warnings = [];
  if (!config.bilim.login || !config.bilim.password) {
    fatal.push('Не заданы BILIM_LOGIN и BILIM_PASSWORD (логин и пароль от BilimClass)');
  }
  if (!config.groq.apiKey) {
    warnings.push('GROQ_API_KEY не задан — ИИ-ответы выключены (ключ: https://console.groq.com/keys)');
  }
  if (!config.whatsapp.admins.length) {
    warnings.push('ADMIN_NUMBERS не задан — админ-команды доступны только админам группы, уведомления об ошибках не отправляются');
  }
  return { fatal, warnings };
}

export function loadConfig() {
  loadDotEnv();
  return buildConfig(process.env);
}

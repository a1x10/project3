import { EventEmitter } from 'node:events';
import pino from 'pino';
import pretty from 'pino-pretty';

const LEVELS = { 10: 'trace', 20: 'debug', 30: 'info', 40: 'warn', 50: 'error', 60: 'fatal' };
const SKIP = new Set(['level', 'time', 'msg', 'pid', 'hostname', 'module']);

// Последние записи журнала в памяти — для панели и терминала на сайте (живой журнал)
export class LogBuffer extends EventEmitter {
  constructor(size = 1500) {
    super();
    this.size = size;
    this.items = [];
    this.seq = 0;
    this.setMaxListeners(100);
  }

  // pino пишет сюда строки JSON
  write(line) {
    let entry;
    try {
      entry = JSON.parse(line);
    } catch {
      return true;
    }
    const extra = {};
    for (const [k, v] of Object.entries(entry)) if (!SKIP.has(k)) extra[k] = v;
    const item = {
      id: ++this.seq,
      time: entry.time || Date.now(),
      level: LEVELS[entry.level] || 'info',
      module: entry.module || '',
      msg: typeof entry.msg === 'string' ? entry.msg : '',
      extra: Object.keys(extra).length ? extra : null,
    };
    this.items.push(item);
    if (this.items.length > this.size) this.items.splice(0, this.items.length - this.size);
    this.emit('log', item);
    return true;
  }

  recent(limit = 200, minLevel = 'debug') {
    const order = ['trace', 'debug', 'info', 'warn', 'error', 'fatal'];
    const min = order.indexOf(minLevel);
    return this.items.filter((i) => order.indexOf(i.level) >= min).slice(-limit);
  }
}

export const logBuffer = new LogBuffer();

export function createLogger(level = 'info') {
  const isPretty = !/^(0|false|no|off)$/i.test(process.env.LOG_PRETTY || '');
  const out = isPretty
    ? pretty({ colorize: true, translateTime: 'SYS:yyyy-mm-dd HH:MM:ss', ignore: 'pid,hostname' })
    : process.stdout;
  return pino(
    {
      level,
      // Пароли и токены никогда не должны попасть в логи
      redact: {
        paths: ['password', '*.password', 'token', '*.token', 'access_token', '*.access_token', 'apiKey', '*.apiKey', 'authorization', '*.authorization', 'refreshToken', '*.refreshToken'],
        censor: '[скрыто]',
      },
    },
    pino.multistream([
      { level, stream: out },
      { level, stream: logBuffer },
    ]),
  );
}

// Короткое описание ошибки для логов и сообщений админу
export function errText(error) {
  if (!error) return 'unknown error';
  return error.message || String(error);
}

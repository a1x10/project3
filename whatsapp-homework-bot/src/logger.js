import pino from 'pino';

export function createLogger(level = 'info') {
  const pretty = !/^(0|false|no|off)$/i.test(process.env.LOG_PRETTY || '');
  return pino({
    level,
    // Пароли и токены никогда не должны попасть в логи
    redact: {
      paths: ['password', '*.password', 'token', '*.token', 'access_token', '*.access_token', 'apiKey', '*.apiKey', 'authorization', '*.authorization'],
      censor: '[скрыто]',
    },
    transport: pretty
      ? { target: 'pino-pretty', options: { colorize: true, translateTime: 'SYS:yyyy-mm-dd HH:MM:ss', ignore: 'pid,hostname' } }
      : undefined,
  });
}

// Короткое описание ошибки для логов и сообщений админу
export function errText(error) {
  if (!error) return 'unknown error';
  return error.message || String(error);
}

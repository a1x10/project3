// Точка входа: собираем все части бота и запускаем.
import { randomUUID } from 'node:crypto';
import path from 'node:path';
import { Assistant } from './ai/assistant.js';
import { GroqClient } from './ai/groq.js';
import { BilimAuthError, BilimClassClient } from './bilimclass/client.js';
import { ConfigError, loadConfig, validateForStart } from './config.js';
import { BotCore } from './core.js';
import { startHealthServer } from './health.js';
import { HomeworkService } from './homework/service.js';
import { createLogger, errText } from './logger.js';
import { Scheduler } from './scheduler.js';
import { Store } from './store.js';
import { formatClock } from './utils/dates.js';
import { Commands } from './whatsapp/commands.js';
import { WhatsAppConnection } from './whatsapp/connection.js';
import { MessageHandler } from './whatsapp/handler.js';

let config;
try {
  config = loadConfig();
} catch (error) {
  console.error(error instanceof ConfigError ? `Ошибка в настройках (.env): ${error.message}` : error);
  process.exit(1);
}

const logger = createLogger(config.logLevel);
const { fatal, warnings } = validateForStart(config);
for (const w of warnings) logger.warn(w);
if (fatal.length) {
  for (const f of fatal) logger.fatal(f);
  logger.fatal('Скопируйте .env.example в .env и заполните. Подробнее — README.md');
  setTimeout(() => process.exit(1), 200);
} else {
  main().catch((error) => {
    logger.fatal({ err: error }, 'Бот упал при запуске');
    setTimeout(() => process.exit(1), 200);
  });
}

async function main() {
  const store = new Store(path.join(config.dataDir, 'state.json'), logger).load();
  if (!store.data.deviceId) store.update((s) => { s.deviceId = randomUUID(); });

  const bilim = new BilimClassClient({ ...config.bilim, deviceId: store.data.deviceId, logger: logger.child({ module: 'bilim' }) });
  const homework = new HomeworkService({ client: bilim, store, config, logger: logger.child({ module: 'homework' }) });
  const groq = new GroqClient({ ...config.groq, logger: logger.child({ module: 'groq' }) });
  const assistant = new Assistant({ groq, homework, config, logger: logger.child({ module: 'ai' }) });
  const wa = new WhatsAppConnection({ config, store, logger: logger.child({ module: 'wa' }) });
  const core = new BotCore({ config, store, wa, logger });
  const scheduler = new Scheduler({ config, store, homework, wa, core, logger: logger.child({ module: 'scheduler' }) });
  const commands = new Commands({ core, homework, wa, scheduler, config, logger: logger.child({ module: 'commands' }) });
  const handler = new MessageHandler({ config, core, wa, homework, assistant, commands, logger: logger.child({ module: 'handler' }) });

  logger.info(
    {
      digest: config.schedule.digestTime != null ? formatClock(config.schedule.digestTime) : 'выкл',
      poll: `каждые ${config.schedule.pollIntervalMinutes} мин`,
      ai: config.ai.mode,
      timezone: config.timezone,
    },
    'Запуск бота домашних заданий',
  );

  // Проверяем вход в BilimClass сразу, чтобы ошибка в пароле была видна в логах при запуске
  try {
    await bilim.login();
  } catch (error) {
    if (error instanceof BilimAuthError) logger.error(errText(error));
    else logger.warn({ err: errText(error) }, 'BilimClass пока недоступен — попробую позже');
  }

  wa.on('message', (msg) => {
    handler.handle(msg).catch((error) => logger.error({ err: error }, 'Ошибка обработки сообщения'));
  });
  wa.on('participants', (event) => {
    handler.onParticipants(event).catch(() => {});
  });
  wa.on('open', () => {
    core.autoBindByName();
    if (!bilim.loggedIn && bilim.authFailedAt) {
      core.notifyAdmins('bilim-auth', `Не могу войти в BilimClass: ${bilim.authFailMessage}`);
    }
  });

  const server = startHealthServer({ config, wa, homework, core, logger });
  await wa.start();
  scheduler.start();

  let stopping = false;
  const shutdown = async (signal) => {
    if (stopping) return;
    stopping = true;
    logger.info({ signal }, 'Останавливаюсь…');
    scheduler.stop();
    server?.close();
    await wa.stop();
    store.save();
    setTimeout(() => process.exit(0), 300);
  };
  process.on('SIGINT', () => shutdown('SIGINT'));
  process.on('SIGTERM', () => shutdown('SIGTERM'));
  process.on('unhandledRejection', (reason) => logger.error({ err: reason }, 'Необработанная ошибка (promise)'));
  process.on('uncaughtException', (error) => {
    // после неизвестной ошибки безопаснее перезапуститься (Docker/PM2/systemd поднимут бота снова)
    logger.fatal({ err: error }, 'Критическая ошибка — перезапуск');
    store.save();
    setTimeout(() => process.exit(1), 300);
  });
}

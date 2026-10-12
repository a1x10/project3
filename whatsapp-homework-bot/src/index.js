// Точка входа: собираем все части бота и запускаем.
import { randomUUID } from 'node:crypto';
import path from 'node:path';
import { Assistant } from './ai/assistant.js';
import { GroqClient } from './ai/groq.js';
import { BackupAi, KeyRing } from './ai/keys.js';
import { BilimAuthError, BilimClassClient } from './bilimclass/client.js';
import { ResilientBilimClient } from './bilimclass/resilient.js';
import { DiaryScreenshotter } from './bilimclass/screenshot.js';
import { ConfigError, loadConfig, validateForStart } from './config.js';
import { BotCore } from './core.js';
import { HomeworkPhotos } from './homework/message.js';
import { HomeworkService } from './homework/service.js';
import { contentSummary, Inbox, isPrivateJid } from './inbox.js';
import { createLogger, errText, logBuffer } from './logger.js';
import { Scheduler } from './scheduler.js';
import { SecretStore } from './secrets.js';
import { Settings } from './settings.js';
import { Store } from './store.js';
import { Watchdog } from './watchdog.js';
import { PanelAuth } from './web/auth.js';
import { startWebServer } from './web/server.js';
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
// Бот работает под присмотром Docker / PM2 / systemd — тогда его можно перезапускать из панели
const supervised = Boolean(process.env.RUNNING_IN_DOCKER || process.env.pm_id || process.env.INVOCATION_ID);

async function main() {
  const store = new Store(path.join(config.dataDir, 'state.json'), logger).load();
  if (!store.data.deviceId) store.update((s) => { s.deviceId = randomUUID(); });
  // настройки из панели (data/settings.json) поверх .env и секреты (data/secrets.json, права 600)
  const settings = new Settings({ config, logger: logger.child({ module: 'settings' }) }).load();
  const secrets = new SecretStore(path.join(config.dataDir, 'secrets.json'), logger).load();
  const savedBilim = secrets.get('bilim');
  if (savedBilim?.login && savedBilim?.password) {
    config.bilim.login = savedBilim.login;
    config.bilim.password = savedBilim.password;
  }

  const { fatal, warnings } = validateForStart(config);
  for (const w of warnings) logger.warn(w);
  for (const f of fatal) logger.error(`${f} — задайте их в .env или в панели управления («Ключи и доступ»)`);

  const bilim = new BilimClassClient({ ...config.bilim, deviceId: store.data.deviceId, logger: logger.child({ module: 'bilim' }) });
  // Браузер с сайтом BilimClass: скриншоты дневника и запасной способ получить ДЗ, если API сбоит
  const siteBrowser = new DiaryScreenshotter({ config, logger: logger.child({ module: 'site' }), eduYear: () => bilim.session?.eduYear });
  let core; // создаётся ниже, нужен для уведомлений
  const diary = new ResilientBilimClient({
    api: bilim,
    site: siteBrowser.available ? siteBrowser : null,
    logger: logger.child({ module: 'bilim' }),
    onSwitch: (mode, reason) => {
      if (mode === 'site') core?.notifyAdmins('bilim-site-mode', `API BilimClass сбоит (${reason}). Беру дневник через сайт — бот работает дальше.`, 24 * 3600 * 1000);
    },
  });
  const homework = new HomeworkService({ client: diary, store, config, logger: logger.child({ module: 'homework' }) });

  // ИИ: ключи Groq (с автозаменой нерабочего) + запасной провайдер
  const keys = new KeyRing({ secrets, envKey: config.groq.apiKey, logger: logger.child({ module: 'keys' }) }).load();
  const backup = new BackupAi({ secrets, logger: logger.child({ module: 'backup-ai' }), timeoutMs: config.groq.timeoutMs });
  const groq = new GroqClient({ ...config.groq, keys, logger: logger.child({ module: 'groq' }) });
  const assistant = new Assistant({ groq, homework, config, backup, logger: logger.child({ module: 'ai' }) });

  const wa = new WhatsAppConnection({ config, store, logger: logger.child({ module: 'wa' }) });
  core = new BotCore({ config, store, wa, logger });
  core.assistant = assistant;
  keys.on('invalid', ({ label, next }) => {
    core.notifyAdmins(
      `groq-key-${label}`,
      next
        ? `Ключ Groq «${label}» перестал работать — бот сам переключился на «${next}». Замените ключ в панели («Ключи и доступ»).`
        : `Ключ Groq «${label}» не работает, рабочих ключей больше нет — ИИ молчит${backup.client() ? ' (отвечает запасной ИИ)' : ''}. Добавьте ключ в панели («Ключи и доступ»).`,
      24 * 3600 * 1000,
    );
  });

  // Переписка для панели: личка целиком, в группах — сообщения бота и обращения к нему
  const inbox = Inbox.fromDataDir(config.dataDir, logger.child({ module: 'inbox' })).load();
  wa.on('sent', ({ jid, content, meta, id, at }) => {
    if (!isPrivateJid(jid) && !core.isTarget(jid)) return;
    inbox.record(jid, { dir: 'out', by: meta?.by || 'bot', ...contentSummary(content), id, at });
  });

  if (siteBrowser.available) logger.info({ chromium: siteBrowser.executable }, 'Браузер для сайта BilimClass найден: скриншоты и запасной способ получения ДЗ включены');
  else logger.warn('Chromium не найден — без скриншотов и без запасного способа получения ДЗ. Установите chromium или задайте CHROMIUM_PATH');
  const photos = new HomeworkPhotos({
    config,
    screenshotter: siteBrowser.available ? siteBrowser : null, // режим (скриншот/карточка/текст) можно менять в панели на ходу
    logger: logger.child({ module: 'photos' }),
    className: () => bilim.session?.className,
    notify: (key, text, throttle) => core.notifyAdmins(key, text, throttle),
  });
  const scheduler = new Scheduler({ config, store, homework, wa, core, photos, logger: logger.child({ module: 'scheduler' }) });

  const restart = (reason = 'panel') => {
    if (!supervised) {
      logger.warn('Перезапуск недоступен: бот запущен без Docker/PM2/systemd — перезапустите вручную');
      return false;
    }
    logger.warn({ reason }, 'Перезапуск бота');
    store.save();
    inbox.save();
    setTimeout(() => process.exit(0), 400);
    return true;
  };
  const auth = new PanelAuth({ config, secrets, core, logger: logger.child({ module: 'panel' }) });
  const commands = new Commands({ core, homework, wa, scheduler, config, settings, panel: config.panel.enabled ? auth : null, logger: logger.child({ module: 'commands' }) });
  const handler = new MessageHandler({ config, core, wa, homework, assistant, commands, inbox, logger: logger.child({ module: 'handler' }) });

  // Изменения настроек на ходу
  settings.on('change', (paths) => {
    if (paths.includes('ai.userLimit')) handler.userLimiter.limit = config.ai.userLimit;
  });

  logger.info(
    {
      digest: scheduler.weekPlanLines(),
      poll: `каждые ${config.schedule.pollIntervalMinutes} мин`,
      ai: assistant.enabled ? config.ai.mode : 'выкл',
      keys: keys.list().length,
      panel: config.panel.enabled ? (auth.methods().password || auth.methods().whatsapp ? 'вкл' : 'нет способа входа — задайте ADMIN_PANEL_PASSWORD или ADMIN_NUMBERS') : 'выкл',
      timezone: config.timezone,
    },
    'Запуск бота домашних заданий',
  );

  // Проверяем вход в BilimClass сразу, чтобы ошибка в пароле была видна в логах при запуске
  if (config.bilim.login && config.bilim.password) {
    try {
      await bilim.login();
    } catch (error) {
      if (error instanceof BilimAuthError) logger.error(errText(error));
      else logger.warn({ err: errText(error) }, 'BilimClass пока недоступен — попробую позже');
    }
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

  const server = startWebServer({
    config, logger: logger.child({ module: 'web' }), wa, homework, core, auth, settings, secrets, scheduler, inbox, keys, backup, groq,
    assistant, diary, bilim, siteBrowser, logBuffer, restart: supervised ? restart : null,
  });
  await wa.start();
  scheduler.start();
  const watchdog = new Watchdog({ wa, scheduler, core, restart, logger: logger.child({ module: 'watchdog' }) });
  watchdog.start();

  let stopping = false;
  const shutdown = async (signal) => {
    if (stopping) return;
    stopping = true;
    logger.info({ signal }, 'Останавливаюсь…');
    scheduler.stop();
    watchdog.stop();
    server?.closeAll();
    await wa.stop();
    store.save();
    inbox.save();
    setTimeout(() => process.exit(0), 300);
  };
  process.on('SIGINT', () => shutdown('SIGINT'));
  process.on('SIGTERM', () => shutdown('SIGTERM'));
  process.on('unhandledRejection', (reason) => logger.error({ err: reason }, 'Необработанная ошибка (promise)'));
  process.on('uncaughtException', (error) => {
    // после неизвестной ошибки безопаснее перезапуститься (Docker/PM2/systemd поднимут бота снова)
    logger.fatal({ err: error }, 'Критическая ошибка — перезапуск');
    store.save();
    inbox.save();
    setTimeout(() => process.exit(1), 300);
  });
}

main().catch((error) => {
  logger.fatal({ err: error }, 'Бот упал при запуске');
  setTimeout(() => process.exit(1), 200);
});

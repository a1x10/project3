// Сторож: раз в минуту проверяет, что бот жив, и чинит сам то, что можно починить без человека.
//  • WhatsApp долго без связи и не переподключается — переподключаем принудительно;
//  • планировщик «завис» на одной задаче — снимаем блокировку;
//  • процесс разросся по памяти — аккуратно перезапускаемся (Docker/PM2/systemd поднимут бота);
//  • когда связь вернулась — пишем админу, сколько её не было.
import { monitorEventLoopDelay } from 'node:perf_hooks';

const CHECK_MS = 60 * 1000;

export class Watchdog {
  constructor({ wa, scheduler, core, logger, restart, memoryLimitMb = 1200 }) {
    this.wa = wa;
    this.scheduler = scheduler;
    this.core = core;
    this.logger = logger;
    this.restart = restart;
    this.memoryLimitMb = memoryLimitMb;
    this.waDownSince = 0;
    this.lastForcedReconnect = 0;
    this.memoryStrikes = 0;
    this.lag = monitorEventLoopDelay({ resolution: 50 });
  }

  start() {
    this.lag.enable();
    this.timer = setInterval(() => this.check(), CHECK_MS);
    this.timer.unref?.();
  }

  stop() {
    clearInterval(this.timer);
    this.lag.disable();
  }

  check(now = Date.now()) {
    try {
      this.checkWhatsApp(now);
      this.checkScheduler(now);
      this.checkMemory();
      this.checkLag();
    } catch (error) {
      this.logger.error({ err: error.message }, 'Сторож: ошибка проверки');
    }
  }

  checkWhatsApp(now) {
    const { status } = this.wa;
    if (this.wa.isOpen) {
      if (this.waDownSince && now - this.waDownSince > 5 * 60 * 1000) {
        const minutes = Math.round((now - this.waDownSince) / 60000);
        this.core.notifyAdmins('wa-recovered', `✅ WhatsApp снова на связи (не было ${minutes} мин). Сообщения из очереди отправлены.`, 0);
      }
      this.waDownSince = 0;
      return;
    }
    // ждём привязку по QR / коду — это не поломка
    if (status === 'qr' || status === 'loggedOut') {
      this.waDownSince = 0;
      return;
    }
    if (!this.waDownSince) this.waDownSince = now;
    const down = now - this.waDownSince;
    if (down > 5 * 60 * 1000 && now - this.lastForcedReconnect > 5 * 60 * 1000) {
      this.lastForcedReconnect = now;
      this.logger.warn({ minutes: Math.round(down / 60000) }, 'Сторож: WhatsApp долго без связи — переподключаю принудительно');
      this.wa.reconnect();
    }
    if (down > 15 * 60 * 1000) {
      this.core.notifyAdmins('wa-down', `WhatsApp без связи уже ${Math.round(down / 60000)} мин. Бот переподключается сам; если не поможет — откройте панель → «Ключи и доступ» → WhatsApp.`, 6 * 3600 * 1000);
    }
  }

  checkScheduler(now) {
    const s = this.scheduler;
    if (s.busy && s.busySince && now - s.busySince > 10 * 60 * 1000) {
      this.logger.error('Сторож: планировщик завис больше чем на 10 минут — снимаю блокировку');
      s.busy = false;
    }
  }

  checkMemory() {
    const rssMb = process.memoryUsage().rss / 1048576;
    if (rssMb < this.memoryLimitMb) {
      this.memoryStrikes = 0;
      return;
    }
    this.memoryStrikes += 1;
    this.logger.warn({ rssMb: Math.round(rssMb) }, 'Сторож: бот занимает много памяти');
    if (this.memoryStrikes >= 3 && this.restart) {
      this.core.notifyAdmins('memory-restart', `Бот занял ${Math.round(rssMb)} МБ памяти — перезапускаюсь, чтобы работать стабильно.`, 3600 * 1000);
      setTimeout(() => this.restart('memory'), 5000).unref?.();
    }
  }

  checkLag() {
    const p99 = this.lag.percentile(99) / 1e6;
    if (p99 > 2000) this.logger.warn({ ms: Math.round(p99) }, 'Сторож: бот отвечает с задержкой (перегружен процессор?)');
    this.lag.reset();
  }
}

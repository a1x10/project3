// Простое надёжное хранилище состояния в JSON-файле.
// Запись атомарная (временный файл + rename), поэтому при сбое питания файл не портится.
import fs from 'node:fs';
import path from 'node:path';

const DEFAULT_STATE = () => ({
  version: 1,
  groups: {}, // jid -> { name, boundAt, ai: true, digest: true }
  snapshots: {}, // 'YYYY-MM-DD' -> { itemKey: hash } — для поиска новых/изменённых ДЗ
  baselineReady: false,
  jobs: {}, // имя задачи -> дата последнего запуска 'YYYY-MM-DD' или timestamp
  sentFiles: {}, // ключ файла -> timestamp отправки
  manual: [], // ДЗ, добавленные вручную командой
  outbox: [], // неотправленные сообщения (переживают перезапуск)
  usage: {}, // 'YYYY-MM-DD' -> { ai: n, voice: n, vision: n }
  alerts: {}, // ключ -> timestamp последнего уведомления админу
  nextManualId: 1,
});

export class Store {
  constructor(file, logger) {
    this.file = file;
    this.logger = logger;
    this.state = DEFAULT_STATE();
    this.timer = null;
  }

  load() {
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    if (!fs.existsSync(this.file)) return this;
    try {
      const parsed = JSON.parse(fs.readFileSync(this.file, 'utf8'));
      this.state = { ...DEFAULT_STATE(), ...parsed };
    } catch (error) {
      const broken = `${this.file}.corrupt-${Date.now()}`;
      fs.renameSync(this.file, broken);
      this.logger?.warn({ broken }, 'Файл состояния повреждён — сохранил копию и начинаю с чистого');
    }
    return this;
  }

  get data() {
    return this.state;
  }

  // Изменить состояние и запланировать сохранение
  update(mutator) {
    const result = mutator(this.state);
    this.scheduleSave();
    return result;
  }

  scheduleSave(delayMs = 500) {
    if (this.timer) return;
    this.timer = setTimeout(() => {
      this.timer = null;
      this.save();
    }, delayMs);
    this.timer.unref?.();
  }

  save() {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    const tmp = `${this.file}.tmp`;
    try {
      const fd = fs.openSync(tmp, 'w');
      fs.writeSync(fd, JSON.stringify(this.state, null, 1));
      fs.fsyncSync(fd);
      fs.closeSync(fd);
      fs.renameSync(tmp, this.file);
    } catch (error) {
      this.logger?.error({ err: error }, 'Не удалось сохранить состояние');
    }
  }

  // Удаляем старые данные, чтобы файл не рос бесконечно
  prune(todayIso) {
    const today = Date.parse(`${todayIso}T00:00:00Z`);
    const DAY = 86400000;
    this.update((s) => {
      for (const date of Object.keys(s.snapshots)) {
        if (Date.parse(`${date}T00:00:00Z`) < today - 14 * DAY) delete s.snapshots[date];
      }
      for (const [key, ts] of Object.entries(s.sentFiles)) {
        if (ts < Date.now() - 30 * DAY) delete s.sentFiles[key];
      }
      s.manual = s.manual.filter((m) => Date.parse(`${m.date}T00:00:00Z`) >= today - 7 * DAY);
      for (const date of Object.keys(s.usage)) {
        if (Date.parse(`${date}T00:00:00Z`) < today - 60 * DAY) delete s.usage[date];
      }
      s.outbox = s.outbox.filter((m) => m.createdAt > Date.now() - 2 * DAY);
    });
  }
}

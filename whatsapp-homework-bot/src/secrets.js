// Секреты, заданные из панели: ключи ИИ, логин/пароль BilimClass, пароль панели.
// Хранятся отдельно от остальных настроек в data/secrets.json с правами 600 (читает только владелец).
// В логи и в панель целиком никогда не попадают — только маска вида gsk_…a1b2.
import { readJsonFile, writeJsonFile } from './settings.js';

export const mask = (value) => {
  const s = String(value || '');
  if (!s) return '';
  if (s.length <= 10) return '•'.repeat(Math.min(s.length, 8));
  return `${s.slice(0, 4)}…${s.slice(-4)}`;
};

export class SecretStore {
  constructor(file, logger) {
    this.file = file;
    this.logger = logger;
    this.data = {};
  }

  load() {
    this.data = this.file ? readJsonFile(this.file, {}) : {};
    return this;
  }

  get(section) {
    return this.data[section] === undefined ? null : structuredClone(this.data[section]);
  }

  set(section, value) {
    if (value == null) delete this.data[section];
    else this.data[section] = structuredClone(value);
    this.save();
  }

  save() {
    if (!this.file) return;
    try {
      writeJsonFile(this.file, this.data, 0o600);
    } catch (error) {
      this.logger?.error({ err: error.message }, 'Не удалось сохранить секреты');
    }
  }
}

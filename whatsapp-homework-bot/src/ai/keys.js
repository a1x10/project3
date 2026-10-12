// Ключи ИИ: несколько ключей Groq (основной + запасные из ВАШЕГО аккаунта) и запасной ИИ-провайдер.
//
// Зачем несколько ключей одного аккаунта: если ключ отозвали, удалили или он утёк — бот сам переключится
// на следующий и сообщит админу. Лимиты Groq общие на аккаунт (организацию), поэтому запасные ключи
// лимиты НЕ увеличивают — и не должны: ключи с разных аккаунтов ради обхода лимитов запрещены правилами Groq.
// Поэтому бот меняет ключ только когда текущий не работает (401/403), а не когда упёрся в лимит (429).
//
// Запасной провайдер (любой OpenAI-совместимый API: OpenRouter, Together, свой сервер…) включается,
// только если Groq недоступен или перегружен — это другой сервис со своим договором и лимитами.
import { createHash, randomBytes } from 'node:crypto';
import { EventEmitter } from 'node:events';
import { mask } from '../secrets.js';
import { GroqClient } from './groq.js';

const fingerprint = (key) => createHash('sha256').update(String(key)).digest('hex').slice(0, 16);
const KEY_RE = /^[A-Za-z0-9_\-.:]{16,300}$/;

export class KeyRing extends EventEmitter {
  constructor({ secrets, envKey = '', logger }) {
    super();
    this.secrets = secrets;
    this.envKey = envKey;
    this.logger = logger;
    this.keys = [];
    this.active = null;
    this.envHidden = null;
  }

  load() {
    const saved = this.secrets?.get('groq') || {};
    this.keys = (saved.keys || []).filter((k) => k && typeof k.key === 'string');
    this.active = saved.active || null;
    this.envHidden = saved.envHidden || null;
    if (this.envKey && this.envHidden !== fingerprint(this.envKey) && !this.keys.some((k) => k.key === this.envKey)) {
      this.keys.unshift({ id: 'env', label: 'Ключ из .env', key: this.envKey, source: 'env', addedAt: 0, status: 'unknown' });
    }
    if (!this.keys.some((k) => k.id === this.active)) this.active = this.keys[0]?.id || null;
    return this;
  }

  save() {
    this.secrets?.set('groq', {
      keys: this.keys.filter((k) => k.source !== 'env'),
      active: this.active,
      envHidden: this.envHidden,
    });
  }

  usable(k) {
    return k && !k.disabled && k.status !== 'invalid';
  }

  // Ключ, которым сейчас пользоваться: активный, а если он сломан — первый рабочий
  current() {
    const active = this.keys.find((k) => k.id === this.active);
    if (this.usable(active)) return active.key;
    return this.keys.find((k) => this.usable(k))?.key || null;
  }

  get hasKey() {
    return Boolean(this.current());
  }

  list() {
    const current = this.current();
    return this.keys.map((k) => ({
      id: k.id,
      label: k.label,
      masked: mask(k.key),
      source: k.source || 'panel',
      status: k.status || 'unknown',
      disabled: Boolean(k.disabled),
      lastError: k.lastError || null,
      lastOkAt: k.lastOkAt || null,
      addedAt: k.addedAt || null,
      inUse: k.key === current,
      active: k.id === this.active,
    }));
  }

  add({ key, label = '' }) {
    const value = String(key || '').trim();
    if (!KEY_RE.test(value)) throw new Error('Ключ выглядит неправильно — скопируйте его целиком (Groq: начинается с gsk_)');
    if (this.keys.some((k) => k.key === value)) throw new Error('Такой ключ уже добавлен');
    const entry = {
      id: randomBytes(6).toString('hex'),
      label: String(label || '').trim().slice(0, 40) || `Ключ ${this.keys.length + 1}`,
      key: value,
      source: 'panel',
      addedAt: Date.now(),
      status: 'unknown',
    };
    this.keys.push(entry);
    if (!this.usable(this.keys.find((k) => k.id === this.active))) this.active = entry.id;
    this.save();
    this.emit('change');
    return entry.id;
  }

  remove(id) {
    const entry = this.keys.find((k) => k.id === id);
    if (!entry) throw new Error('Ключ не найден');
    if (entry.source === 'env') this.envHidden = fingerprint(entry.key);
    this.keys = this.keys.filter((k) => k.id !== id);
    if (this.active === id) this.active = this.keys.find((k) => this.usable(k))?.id || this.keys[0]?.id || null;
    this.save();
    this.emit('change');
  }

  activate(id) {
    const entry = this.keys.find((k) => k.id === id);
    if (!entry) throw new Error('Ключ не найден');
    entry.disabled = false;
    entry.status = entry.status === 'invalid' ? 'unknown' : entry.status; // дать ключу ещё шанс
    this.active = id;
    this.save();
    this.emit('change');
  }

  setDisabled(id, disabled) {
    const entry = this.keys.find((k) => k.id === id);
    if (!entry) throw new Error('Ключ не найден');
    entry.disabled = Boolean(disabled);
    this.save();
    this.emit('change');
  }

  byId(id) {
    return this.keys.find((k) => k.id === id) || null;
  }

  markOk(key) {
    const entry = this.keys.find((k) => k.key === key);
    if (!entry) return;
    const wasBad = entry.status !== 'ok';
    entry.status = 'ok';
    entry.lastError = null;
    entry.lastOkAt = Date.now();
    if (wasBad) this.save();
  }

  // Ключ не принят (401/403). true — есть другой рабочий ключ, запрос можно повторить
  markInvalid(key, message) {
    const entry = this.keys.find((k) => k.key === key);
    if (!entry || entry.status === 'invalid') return this.current() !== key && this.hasKey;
    entry.status = 'invalid';
    entry.lastError = String(message || 'ключ не принят').slice(0, 200);
    const next = this.keys.find((k) => this.usable(k));
    if (next) this.active = next.id;
    this.save();
    this.logger?.warn({ key: entry.label, next: next?.label || null }, 'Ключ Groq не работает');
    this.emit('invalid', { label: entry.label, next: next?.label || null });
    this.emit('change');
    return Boolean(next);
  }
}

// Запасной ИИ: OpenAI-совместимый API (адрес, ключ, модель)
export class BackupAi {
  constructor({ secrets, logger, timeoutMs = 60000 }) {
    this.secrets = secrets;
    this.logger = logger;
    this.timeoutMs = timeoutMs;
    this.cached = null;
  }

  get settings() {
    return this.secrets?.get('backup') || { enabled: false, baseUrl: '', apiKey: '', model: '', label: '' };
  }

  describe() {
    const s = this.settings;
    return { enabled: Boolean(s.enabled), baseUrl: s.baseUrl || '', model: s.model || '', label: s.label || '', key: mask(s.apiKey), hasKey: Boolean(s.apiKey) };
  }

  static validate({ baseUrl, apiKey, model }) {
    let url;
    try {
      url = new URL(String(baseUrl || ''));
    } catch {
      throw new Error('Адрес API запасного ИИ: нужна ссылка вида https://openrouter.ai/api/v1');
    }
    if (url.protocol !== 'https:' && !['localhost', '127.0.0.1'].includes(url.hostname)) throw new Error('Адрес API должен начинаться с https://');
    if (!String(model || '').trim()) throw new Error('Укажите модель запасного ИИ');
    if (apiKey && !KEY_RE.test(String(apiKey).trim())) throw new Error('Ключ запасного ИИ выглядит неправильно');
    return url.toString().replace(/\/+$/, '');
  }

  // patch: { enabled, baseUrl, apiKey (пусто — оставить прежний), model, label }
  update(patch) {
    const current = this.settings;
    const next = { ...current, ...patch, apiKey: patch.apiKey ? String(patch.apiKey).trim() : current.apiKey };
    if (next.enabled || next.baseUrl || next.model) next.baseUrl = BackupAi.validate(next);
    // сменили адрес, а ключ не ввели — старый ключ на чужой адрес не отправляем
    if (!patch.apiKey && current.baseUrl && next.baseUrl !== current.baseUrl) next.apiKey = '';
    next.model = String(next.model || '').trim();
    next.label = String(next.label || '').trim().slice(0, 40);
    next.enabled = Boolean(next.enabled);
    this.secrets.set('backup', next);
    this.cached = null;
  }

  // { client, model } или null, если запасной ИИ не настроен
  client() {
    const s = this.settings;
    if (!s.enabled || !s.baseUrl || !s.model) return null;
    const signature = `${s.baseUrl}|${s.apiKey}|${s.model}`;
    if (this.cached?.signature !== signature) {
      this.cached = { signature, client: new GroqClient({ apiKey: s.apiKey || 'none', baseUrl: s.baseUrl, timeoutMs: this.timeoutMs, logger: this.logger, plain: true }), model: s.model };
    }
    return { client: this.cached.client, model: this.cached.model };
  }
}

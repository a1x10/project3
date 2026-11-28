'use strict';
const fs = require('fs');
const path = require('path');

const SECRET_KEYS = ['openrouterKey', 'elevenlabsKey', 'cloudToken'];

const DEFAULT_SETTINGS = Object.freeze({
  // Интеллект
  provider: 'openrouter',
  lang: 'ru',
  openrouterKey: '',
  model: 'openai/gpt-4o-mini',
  temperature: 0.8,
  maxTokens: 1200,
  customInstructions: '',
  // Stella Cloud
  cloudEnabled: false,
  cloudUrl: '',
  cloudToken: '',
  cloudUser: '',
  agentsPromptShown: false,
  agentsEnabled: true,
  gameComments: true,
  arVoiceOnPhone: false,
  gameCommentSec: 60,
  // Голос
  ttsEnabled: true,
  elevenlabsKey: '',
  elevenModel: 'eleven_v3',
  voiceStella: 'OowtKaZH9N7iuGbsd00l', // Veronica - Energetic, Clear and Rich
  voiceMark: 'pNInz6obpgDQGcFmaJgB',
  voiceStability: 1,
  voiceSimilarity: 0.8,
  voiceStyle: 0.35,
  voiceSpeed: 1.0,
  volume: 0.9,
  systemVoiceFallback: true,
  // Слух
  wakeWordEnabled: false,
  wakeRequireName: true,
  sttLanguage: 'rus',
  micSensitivity: 0.5,
  // Команды
  commandsEnabled: true,
  commandMatch: 'contains', // exact | contains
  // Аватар
  persona: 'stella',
  markModel: 'nick', // nick | classic
  avatarSide: 'right', // right | left
  customModelStella: '',
  customModelMark: '',
  lookAtCursor: true,
  idleAnimations: true,
  animationIntensity: 1,
  background: 'white',
  proactive: true,
  proactiveMinutes: 10,
  // Компьютер
  computerControl: true,
  permissionMode: 'confirm_risky', // confirm_all | confirm_risky | autonomous
  commandTimeout: 60,
  // Интерфейс
  accent: '#8b5cf6',
  showSplash: true,
  companionMode: false,
  launchAtStartup: false,
  uiScale: 1,
});

class Store {
  /**
   * @param {string} dir папка с данными
   * @param {{encrypt?:(s:string)=>string, decrypt?:(s:string)=>string}} [crypto]
   */
  constructor(dir, crypto = {}) {
    this.dir = dir;
    this.file = path.join(dir, 'stella-data.json');
    this.crypto = crypto;
    this.data = { settings: { ...DEFAULT_SETTINGS }, accounts: [], currentAccount: null, conversations: {}, memories: {}, stats: {}, actionLog: [], commands: {}, settingsVersion: 2 };
    this._load();
  }

  _load() {
    try {
      if (!fs.existsSync(this.file)) return;
      const raw = JSON.parse(fs.readFileSync(this.file, 'utf8'));
      this.data = { ...this.data, ...raw, settings: { ...DEFAULT_SETTINGS, ...(raw.settings || {}) } };
      this.data.settingsVersion = raw.settingsVersion || 1; // в старых файлах версии нет
      migrateVoice(this.data);
      for (const k of SECRET_KEYS) {
        const v = this.data.settings[k];
        if (typeof v === 'string' && v.startsWith('enc:') && this.crypto.decrypt) {
          try { this.data.settings[k] = this.crypto.decrypt(v.slice(4)); } catch { this.data.settings[k] = ''; }
        }
      }
    } catch (e) {
      // повреждённый файл — сохраняем копию и начинаем заново
      try { fs.copyFileSync(this.file, this.file + '.broken-' + Date.now()); } catch { /* ignore */ }
    }
  }

  save() {
    fs.mkdirSync(this.dir, { recursive: true });
    const out = JSON.parse(JSON.stringify(this.data));
    for (const k of SECRET_KEYS) {
      const v = out.settings[k];
      if (v && this.crypto.encrypt) out.settings[k] = 'enc:' + this.crypto.encrypt(v);
    }
    const tmp = this.file + '.tmp';
    fs.writeFileSync(tmp, JSON.stringify(out, null, 2));
    fs.renameSync(tmp, this.file);
  }

  getSettings() { return { ...this.data.settings }; }

  /** Настройки для UI: ключи маскируются. */
  getPublicSettings() {
    const s = this.getSettings();
    for (const k of SECRET_KEYS) s[k] = s[k] ? maskKey(s[k]) : '';
    const cloud = !!(this.data.settings.cloudEnabled && this.data.settings.cloudToken && this.data.settings.cloudUrl);
    s.cloudActive = cloud;
    s.hasOwnOpenrouterKey = !!this.data.settings.openrouterKey;
    s.hasOwnElevenlabsKey = !!this.data.settings.elevenlabsKey;
    s.hasOpenrouterKey = cloud || !!this.data.settings.openrouterKey;
    s.hasElevenlabsKey = cloud || !!this.data.settings.elevenlabsKey;
    return s;
  }

  updateSettings(patch) {
    const clean = {};
    for (const [k, v] of Object.entries(patch || {})) {
      if (!(k in DEFAULT_SETTINGS)) continue;
      if (SECRET_KEYS.includes(k) && typeof v === 'string' && v.includes('•')) continue; // маска не перезаписывает ключ
      const def = DEFAULT_SETTINGS[k];
      if (typeof def === 'number') { const n = Number(v); if (!Number.isFinite(n)) continue; clean[k] = n; }
      else if (typeof def === 'boolean') clean[k] = !!v;
      else clean[k] = String(v ?? '').trim();
    }
    if (clean.permissionMode && !['confirm_all', 'confirm_risky', 'autonomous'].includes(clean.permissionMode)) delete clean.permissionMode;
    if (clean.persona && !['stella', 'mark'].includes(clean.persona)) delete clean.persona;
    if ('temperature' in clean) clean.temperature = clamp(clean.temperature, 0, 2);
    if ('volume' in clean) clean.volume = clamp(clean.volume, 0, 1);
    if ('maxTokens' in clean) clean.maxTokens = Math.round(clamp(clean.maxTokens, 64, 32000));
    if (clean.commandMatch && !['exact', 'contains'].includes(clean.commandMatch)) delete clean.commandMatch;
    if (clean.avatarSide && !['left', 'right'].includes(clean.avatarSide)) delete clean.avatarSide;
    if (clean.markModel && !['nick', 'classic'].includes(clean.markModel)) delete clean.markModel;
    if ('commandTimeout' in clean) clean.commandTimeout = Math.round(clamp(clean.commandTimeout, 5, 600));
    Object.assign(this.data.settings, clean);
    this.save();
    return this.getPublicSettings();
  }

  // --- Переписки ---
  _accKey() { return this.data.currentAccount || 'guest'; }
  listConversations() {
    const all = this.data.conversations[this._accKey()] || [];
    return all.map(({ id, title, createdAt, updatedAt, messages }) => ({ id, title, createdAt, updatedAt, count: messages.length }))
      .sort((a, b) => b.updatedAt - a.updatedAt);
  }
  getConversation(id) { return (this.data.conversations[this._accKey()] || []).find((c) => c.id === id) || null; }
  createConversation(title = 'Новый чат') {
    const key = this._accKey();
    const conv = { id: 'c_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6), title, createdAt: Date.now(), updatedAt: Date.now(), messages: [] };
    (this.data.conversations[key] ||= []).push(conv);
    this.save();
    return conv;
  }
  appendMessage(convId, msg) {
    const conv = this.getConversation(convId);
    if (!conv) throw new Error('Чат не найден');
    conv.messages.push({ ...msg, ts: msg.ts || Date.now() });
    if (conv.messages.length > 500) conv.messages.splice(0, conv.messages.length - 500);
    conv.updatedAt = Date.now();
    if (conv.title === 'Новый чат' && msg.role === 'user' && msg.content) conv.title = String(msg.content).slice(0, 40);
    this.bumpStat(msg.role === 'user' ? 'messagesSent' : 'messagesReceived');
    this.save();
    return conv;
  }
  deleteConversation(id) {
    const key = this._accKey();
    this.data.conversations[key] = (this.data.conversations[key] || []).filter((c) => c.id !== id);
    this.save();
  }
  renameConversation(id, title) {
    const c = this.getConversation(id); if (!c) return null;
    c.title = String(title).slice(0, 80) || c.title; this.save(); return c;
  }

  // --- Память ---
  getMemories() { return [...(this.data.memories[this._accKey()] || [])]; }
  addMemory(text) {
    const t = String(text || '').trim().slice(0, 500);
    if (!t) throw new Error('Пустой факт');
    const list = (this.data.memories[this._accKey()] ||= []);
    if (list.some((m) => m.text.toLowerCase() === t.toLowerCase())) return list;
    list.push({ id: 'm_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 5), text: t, ts: Date.now() });
    if (list.length > 200) list.shift();
    this.save();
    return list;
  }
  removeMemory(id) {
    const key = this._accKey();
    this.data.memories[key] = (this.data.memories[key] || []).filter((m) => m.id !== id);
    this.save();
  }

  // --- Статистика ---
  bumpStat(name, by = 1) {
    const s = (this.data.stats[this._accKey()] ||= {});
    s[name] = (s[name] || 0) + by;
  }
  getStats() { return { ...(this.data.stats[this._accKey()] || {}) }; }

  // --- Журнал действий ---
  logAction(entry) {
    this.data.actionLog.push({ ...entry, ts: Date.now() });
    if (this.data.actionLog.length > 300) this.data.actionLog.splice(0, this.data.actionLog.length - 300);
    this.bumpStat('actions');
    this.save();
  }
  getActionLog() { return [...this.data.actionLog].reverse(); }
  clearActionLog() { this.data.actionLog = []; this.save(); }

  // --- Пользовательские команды ---
  listCommands() { return JSON.parse(JSON.stringify((this.data.commands ||= {})[this._accKey()] || [])); }
  saveCommand(cmd) {
    const c = normalizeCommand(cmd);
    const list = ((this.data.commands ||= {})[this._accKey()] ||= []);
    const i = list.findIndex((x) => x.id === c.id);
    if (i >= 0) list[i] = { ...c, createdAt: list[i].createdAt, updatedAt: Date.now() };
    else list.push({ ...c, createdAt: Date.now(), updatedAt: Date.now() });
    this.save();
    return c;
  }
  deleteCommand(id) {
    const key = this._accKey();
    (this.data.commands ||= {})[key] = (this.data.commands[key] || []).filter((c) => c.id !== id);
    this.save();
  }
  importCommands(arr) {
    if (!Array.isArray(arr)) throw new Error('Ожидался массив команд');
    let n = 0;
    for (const raw of arr) { try { this.saveCommand({ ...raw, id: undefined }); n++; } catch { /* пропускаем битые */ } }
    return n;
  }

  resetAll() {
    this.data = { settings: { ...DEFAULT_SETTINGS }, accounts: [], currentAccount: null, conversations: {}, memories: {}, stats: {}, actionLog: [], commands: {}, settingsVersion: 2 };
    this.save();
  }
}

const ACTION_TYPES = ['say', 'animation', 'emotion', 'open_url', 'web_search', 'launch_app', 'open_path', 'run_command', 'press_keys', 'type_text', 'media_control', 'set_volume', 'wait'];

function normalizeCommand(cmd = {}) {
  const name = String(cmd.name || '').trim().slice(0, 60);
  if (!name) throw new Error('Укажите название команды');
  const triggers = (Array.isArray(cmd.triggers) ? cmd.triggers : String(cmd.triggers || '').split(/[\n,;]/))
    .map((t) => String(t).trim().toLowerCase()).filter(Boolean).slice(0, 20);
  if (!triggers.length) throw new Error('Добавьте хотя бы одну фразу-триггер');
  const actions = (cmd.actions || []).filter((a) => a && ACTION_TYPES.includes(a.type)).map((a) => ({ type: a.type, value: String(a.value ?? '').slice(0, 2000) })).slice(0, 30);
  if (!actions.length) throw new Error('Добавьте хотя бы одно действие');
  return { id: cmd.id || 'cmd_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6), name, triggers, actions, enabled: cmd.enabled !== false };
}

/** v2: голос Стеллы по умолчанию — Вероника на Eleven v3. Меняем только то, что пользователь не трогал. */
function migrateVoice(data) {
  if ((data.settingsVersion || 1) >= 2) return;
  const s = data.settings;
  if (s.voiceStella === '21m00Tcm4TlvDq8ikWAM') s.voiceStella = DEFAULT_SETTINGS.voiceStella;
  if (s.elevenModel === 'eleven_multilingual_v2') s.elevenModel = DEFAULT_SETTINGS.elevenModel;
  if (s.voiceStability === 0.45) s.voiceStability = DEFAULT_SETTINGS.voiceStability;
  data.settingsVersion = 2;
}

function clamp(v, a, b) { return Math.min(b, Math.max(a, v)); }
function maskKey(k) { return k.length <= 8 ? '••••' : k.slice(0, 5) + '••••••' + k.slice(-4); }

module.exports = { Store, DEFAULT_SETTINGS, SECRET_KEYS, maskKey, normalizeCommand, ACTION_TYPES, migrateVoice };

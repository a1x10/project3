import { describe, it, expect, beforeEach } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { Store, DEFAULT_SETTINGS, maskKey } = require('../src/main/store.js');

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'stella-store-'));
const fakeCrypto = { encrypt: (s) => Buffer.from(s).toString('base64').split('').reverse().join(''), decrypt: (s) => Buffer.from(s.split('').reverse().join(''), 'base64').toString() };

describe('Store: настройки', () => {
  let dir, store;
  beforeEach(() => { dir = tmp(); store = new Store(dir, fakeCrypto); });

  it('отдаёт значения по умолчанию', () => {
    expect(store.getSettings()).toEqual({ ...DEFAULT_SETTINGS });
  });
  it('по умолчанию персона — Стелла, режим — подтверждать рискованное', () => {
    expect(store.getSettings().persona).toBe('stella');
    expect(store.getSettings().permissionMode).toBe('confirm_risky');
  });
  it('игнорирует неизвестные ключи', () => {
    store.updateSettings({ hacker: 1 });
    expect(store.getSettings()).not.toHaveProperty('hacker');
  });
  it('приводит типы: число, булево, строка', () => {
    store.updateSettings({ temperature: '0.5', ttsEnabled: 0, model: '  x/y  ' });
    const s = store.getSettings();
    expect(s.temperature).toBe(0.5);
    expect(s.ttsEnabled).toBe(false);
    expect(s.model).toBe('x/y');
  });
  it('ограничивает диапазоны', () => {
    store.updateSettings({ temperature: 9, volume: -1, maxTokens: 5, commandTimeout: 99999 });
    const s = store.getSettings();
    expect(s.temperature).toBe(2);
    expect(s.volume).toBe(0);
    expect(s.maxTokens).toBe(64);
    expect(s.commandTimeout).toBe(600);
  });
  it('отбрасывает нечисловые значения для числовых полей', () => {
    store.updateSettings({ temperature: 'abc' });
    expect(store.getSettings().temperature).toBe(DEFAULT_SETTINGS.temperature);
  });
  it('проверяет допустимые значения режима и персоны', () => {
    store.updateSettings({ permissionMode: 'root', persona: 'bob' });
    expect(store.getSettings().permissionMode).toBe('confirm_risky');
    expect(store.getSettings().persona).toBe('stella');
    store.updateSettings({ permissionMode: 'autonomous', persona: 'mark' });
    expect(store.getSettings().permissionMode).toBe('autonomous');
    expect(store.getSettings().persona).toBe('mark');
  });
  it('маскирует ключи в публичных настройках', () => {
    store.updateSettings({ openrouterKey: 'sk-or-v1-abcdefghijklmnop' });
    const pub = store.getPublicSettings();
    expect(pub.openrouterKey).not.toContain('abcdefghij');
    expect(pub.openrouterKey).toContain('•');
    expect(pub.hasOpenrouterKey).toBe(true);
    expect(pub.hasElevenlabsKey).toBe(false);
  });
  it('маска не перезаписывает настоящий ключ', () => {
    store.updateSettings({ openrouterKey: 'sk-or-v1-secret-123456' });
    store.updateSettings({ openrouterKey: store.getPublicSettings().openrouterKey });
    expect(store.getSettings().openrouterKey).toBe('sk-or-v1-secret-123456');
  });
  it('шифрует ключи на диске и расшифровывает при загрузке', () => {
    store.updateSettings({ elevenlabsKey: 'sk_eleven_secret' });
    const raw = fs.readFileSync(path.join(dir, 'stella-data.json'), 'utf8');
    expect(raw).not.toContain('sk_eleven_secret');
    expect(raw).toContain('enc:');
    const again = new Store(dir, fakeCrypto);
    expect(again.getSettings().elevenlabsKey).toBe('sk_eleven_secret');
  });
  it('сохраняет и перечитывает данные', () => {
    store.updateSettings({ accent: '#ff0000' });
    expect(new Store(dir, fakeCrypto).getSettings().accent).toBe('#ff0000');
  });
  it('восстанавливается после повреждённого файла', () => {
    fs.writeFileSync(path.join(dir, 'stella-data.json'), '{broken json');
    const s = new Store(dir, fakeCrypto);
    expect(s.getSettings().persona).toBe('stella');
    expect(fs.readdirSync(dir).some((f) => f.includes('.broken-'))).toBe(true);
  });
  it('maskKey для коротких ключей', () => {
    expect(maskKey('abc')).toBe('••••');
    expect(maskKey('abcdefghijklmnop')).toBe('abcde••••••mnop');
  });
});

describe('Store: чаты, память, статистика', () => {
  let store;
  beforeEach(() => { store = new Store(tmp()); });

  it('создаёт чат и добавляет сообщения', () => {
    const c = store.createConversation();
    store.appendMessage(c.id, { role: 'user', content: 'Привет, Стелла! Как дела?' });
    store.appendMessage(c.id, { role: 'assistant', content: 'Отлично!' });
    expect(store.getConversation(c.id).messages).toHaveLength(2);
  });
  it('даёт чату название по первому сообщению', () => {
    const c = store.createConversation();
    store.appendMessage(c.id, { role: 'user', content: 'Помоги разобрать папку загрузок пожалуйста прямо сейчас' });
    expect(store.getConversation(c.id).title).toBe('Помоги разобрать папку загрузок пожалуйс');
  });
  it('ошибка при записи в несуществующий чат', () => {
    expect(() => store.appendMessage('nope', { role: 'user', content: 'x' })).toThrow();
  });
  it('ограничивает историю 500 сообщениями', () => {
    const c = store.createConversation();
    for (let i = 0; i < 520; i++) store.data.conversations.guest[0].messages.push({ role: 'user', content: String(i) });
    store.appendMessage(c.id, { role: 'user', content: 'last' });
    const m = store.getConversation(c.id).messages;
    expect(m).toHaveLength(500);
    expect(m.at(-1).content).toBe('last');
  });
  it('список чатов отсортирован по времени', async () => {
    const a = store.createConversation();
    const b = store.createConversation();
    store.getConversation(a.id).updatedAt = 10;
    store.getConversation(b.id).updatedAt = 20;
    expect(store.listConversations().map((c) => c.id)).toEqual([b.id, a.id]);
  });
  it('переименовывает и удаляет чат', () => {
    const c = store.createConversation();
    store.renameConversation(c.id, 'Работа');
    expect(store.getConversation(c.id).title).toBe('Работа');
    store.deleteConversation(c.id);
    expect(store.getConversation(c.id)).toBeNull();
  });
  it('чаты изолированы между аккаунтами', () => {
    store.data.currentAccount = 'anna';
    store.createConversation();
    store.data.currentAccount = 'boris';
    expect(store.listConversations()).toHaveLength(0);
  });
  it('запоминает факты без дубликатов', () => {
    store.addMemory('Люблю кофе');
    store.addMemory('люблю кофе');
    store.addMemory('Живу в Казани');
    expect(store.getMemories().map((m) => m.text)).toEqual(['Люблю кофе', 'Живу в Казани']);
  });
  it('не принимает пустой факт', () => { expect(() => store.addMemory('   ')).toThrow(); });
  it('удаляет факт', () => {
    store.addMemory('Факт');
    const id = store.getMemories()[0].id;
    store.removeMemory(id);
    expect(store.getMemories()).toHaveLength(0);
  });
  it('считает статистику сообщений', () => {
    const c = store.createConversation();
    store.appendMessage(c.id, { role: 'user', content: 'a' });
    store.appendMessage(c.id, { role: 'user', content: 'b' });
    store.appendMessage(c.id, { role: 'assistant', content: 'c' });
    expect(store.getStats()).toMatchObject({ messagesSent: 2, messagesReceived: 1 });
  });
  it('журнал действий: новые сверху, лимит 300', () => {
    for (let i = 0; i < 305; i++) store.logAction({ name: 't' + i, ok: true });
    const log = store.getActionLog();
    expect(log).toHaveLength(300);
    expect(log[0].name).toBe('t304');
    expect(store.getStats().actions).toBe(305);
    store.clearActionLog();
    expect(store.getActionLog()).toHaveLength(0);
  });
  it('resetAll очищает всё', () => {
    store.addMemory('x'); store.updateSettings({ persona: 'mark' });
    store.resetAll();
    expect(store.getMemories()).toHaveLength(0);
    expect(store.getSettings().persona).toBe('stella');
  });
});

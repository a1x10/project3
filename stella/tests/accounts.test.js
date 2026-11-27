import { describe, it, expect, beforeEach } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { Store } = require('../src/main/store.js');
const { Accounts, hashPassword, verifyPassword } = require('../src/main/accounts.js');

let store, acc;
beforeEach(() => { store = new Store(fs.mkdtempSync(path.join(os.tmpdir(), 'stella-acc-'))); acc = new Accounts(store); });

describe('Регистрация', () => {
  it('создаёт аккаунт со Стеллой', () => {
    const a = acc.register({ username: 'alex', displayName: 'Алекс', persona: 'stella' });
    expect(a).toMatchObject({ username: 'alex', displayName: 'Алекс', persona: 'stella', hasPassword: false });
    expect(acc.current().username).toBe('alex');
  });
  it('создаёт аккаунт с Марком и меняет персону в настройках', () => {
    acc.register({ username: 'bob', persona: 'mark' });
    expect(store.getSettings().persona).toBe('mark');
  });
  it('требует выбрать Стеллу или Марка', () => {
    expect(() => acc.register({ username: 'x1', persona: 'astra' })).toThrow(/Стелла или Марк/);
    expect(() => acc.register({ username: 'x1' })).toThrow();
  });
  it('проверяет логин', () => {
    expect(() => acc.register({ username: 'a', persona: 'stella' })).toThrow(/Логин/);
    expect(() => acc.register({ username: 'with space', persona: 'stella' })).toThrow(/Логин/);
    expect(() => acc.register({ username: 'x'.repeat(33), persona: 'stella' })).toThrow(/Логин/);
  });
  it('разрешает кириллический логин', () => {
    expect(acc.register({ username: 'маша', persona: 'stella' }).username).toBe('маша');
  });
  it('запрещает дубликаты без учёта регистра', () => {
    acc.register({ username: 'Alex', persona: 'stella' });
    expect(() => acc.register({ username: 'alex', persona: 'mark' })).toThrow(/существует/);
  });
  it('проверяет email', () => {
    expect(() => acc.register({ username: 'em', persona: 'stella', email: 'bad' })).toThrow(/email/);
    expect(acc.register({ username: 'em2', persona: 'stella', email: 'a@b.ru' }).email).toBe('a@b.ru');
  });
  it('проверяет длину пароля', () => {
    expect(() => acc.register({ username: 'pw', persona: 'stella', password: '12' })).toThrow(/4/);
  });
  it('не раскрывает хеш пароля', () => {
    const a = acc.register({ username: 'sec', persona: 'stella', password: 'secret' });
    expect(a).not.toHaveProperty('passwordHash');
    expect(a).not.toHaveProperty('passwordSalt');
    expect(a.hasPassword).toBe(true);
    expect(JSON.stringify(acc.list())).not.toContain('secret');
  });
});

describe('Вход и выход', () => {
  beforeEach(() => { acc.register({ username: 'anna', persona: 'stella', password: 'qwerty' }); acc.logout(); });
  it('входит с верным паролем', () => { expect(acc.login('anna', 'qwerty').username).toBe('anna'); });
  it('логин без учёта регистра', () => { expect(acc.login('ANNA', 'qwerty').username).toBe('anna'); });
  it('отказывает с неверным паролем', () => { expect(() => acc.login('anna', 'nope')).toThrow(/Неверный/); });
  it('отказывает несуществующему', () => { expect(() => acc.login('ghost', '')).toThrow(/не найден/); });
  it('выход сбрасывает текущий аккаунт', () => { acc.login('anna', 'qwerty'); acc.logout(); expect(acc.current()).toBeNull(); });
  it('вход без пароля для аккаунта без пароля', () => {
    acc.register({ username: 'free', persona: 'mark' }); acc.logout();
    expect(acc.login('free').persona).toBe('mark');
    expect(store.getSettings().persona).toBe('mark');
  });
});

describe('Изменение профиля', () => {
  beforeEach(() => acc.register({ username: 'max', displayName: 'Макс', persona: 'stella', password: 'old1' }));
  it('меняет имя и био', () => {
    const a = acc.update({ displayName: 'Максим', bio: 'Люблю звёзды' });
    expect(a.displayName).toBe('Максим');
    expect(a.bio).toBe('Люблю звёзды');
  });
  it('меняет ассистента', () => {
    expect(acc.update({ persona: 'mark' }).persona).toBe('mark');
    expect(store.getSettings().persona).toBe('mark');
    expect(() => acc.update({ persona: 'zzz' })).toThrow();
  });
  it('меняет цвет только на валидный hex', () => {
    expect(acc.update({ avatarColor: '#123abc' }).avatarColor).toBe('#123abc');
    expect(acc.update({ avatarColor: 'red' }).avatarColor).toBe('#123abc');
  });
  it('смена пароля требует старый', () => {
    expect(() => acc.update({ oldPassword: 'bad', newPassword: 'new1' })).toThrow(/Старый/);
    acc.update({ oldPassword: 'old1', newPassword: 'new1' });
    acc.logout();
    expect(acc.login('max', 'new1').username).toBe('max');
  });
  it('можно убрать пароль', () => {
    expect(acc.update({ oldPassword: 'old1', newPassword: '' }).hasPassword).toBe(false);
  });
  it('удаление аккаунта удаляет его данные', () => {
    store.addMemory('секрет');
    expect(acc.remove('max')).toBe(true);
    expect(acc.list()).toHaveLength(0);
    expect(store.data.memories.max).toBeUndefined();
  });
  it('без входа update бросает ошибку', () => { acc.logout(); expect(() => acc.update({ displayName: 'x' })).toThrow(); });
});

describe('Хеширование паролей', () => {
  it('проверяет верный пароль', () => { const { salt, hash } = hashPassword('пароль'); expect(verifyPassword('пароль', salt, hash)).toBe(true); });
  it('отвергает неверный', () => { const { salt, hash } = hashPassword('a'); expect(verifyPassword('b', salt, hash)).toBe(false); });
  it('разная соль — разный хеш', () => { expect(hashPassword('x').hash).not.toBe(hashPassword('x').hash); });
});

import { describe, it, expect, beforeEach } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { matchCommand, resolveActions, actionToTool, EXAMPLE_COMMANDS, ACTION_TYPES } from '../src/renderer/js/core/commands.js';
const require = createRequire(import.meta.url);
const { Store, normalizeCommand, ACTION_TYPES: MAIN_TYPES } = require('../src/main/store.js');

const cmds = [
  { id: 'yt', name: 'YouTube', triggers: ['открой ютуб'], actions: [{ type: 'open_url', value: 'https://youtube.com' }] },
  { id: 'find', name: 'Поиск', triggers: ['найди {query}'], actions: [{ type: 'web_search', value: '{query}' }] },
  { id: 'wx', name: 'Погода', triggers: ['какая погода в {query} сегодня'], actions: [{ type: 'say', value: 'Погода в {query}' }] },
  { id: 'off', name: 'Выключенная', triggers: ['секрет'], actions: [{ type: 'say', value: 'x' }], enabled: false },
  { id: 'yt2', name: 'YouTube музыка', triggers: ['открой ютуб музыку'], actions: [{ type: 'open_url', value: 'https://music.youtube.com' }] },
];
const names = ['стелла', 'марк'];

describe('Совпадение команд', () => {
  it('точная фраза', () => expect(matchCommand('Открой ютуб', cmds).command.id).toBe('yt'));
  it('фраза внутри предложения (режим «содержит»)', () => expect(matchCommand('пожалуйста открой ютуб быстрее', cmds).command.id).toBe('yt'));
  it('режим «точно» не принимает лишние слова', () => {
    expect(matchCommand('пожалуйста открой ютуб', cmds, 'exact')).toBeNull();
    expect(matchCommand('открой ютуб', cmds, 'exact').command.id).toBe('yt');
  });
  it('обращение по имени убирается', () => expect(matchCommand('Стелла, открой ютуб', cmds, 'exact', names).command.id).toBe('yt'));
  it('{query} захватывает остаток', () => expect(matchCommand('найди рецепт блинов', cmds)).toMatchObject({ command: { id: 'find' }, query: 'рецепт блинов' }));
  it('{query} в середине шаблона', () => expect(matchCommand('Какая погода в Казани сегодня?', cmds)).toMatchObject({ command: { id: 'wx' }, query: 'казани' }));
  it('{query} не срабатывает без текста', () => expect(matchCommand('найди', cmds)).toBeNull());
  it('выключенные команды игнорируются', () => expect(matchCommand('секрет', cmds)).toBeNull());
  it('побеждает самый длинный триггер', () => expect(matchCommand('открой ютуб музыку', cmds).command.id).toBe('yt2'));
  it('нет совпадения', () => expect(matchCommand('расскажи анекдот', cmds)).toBeNull());
  it('не совпадает по части слова', () => expect(matchCommand('открой ютубчик', cmds)).toBeNull());
  it('пустые входные данные', () => { expect(matchCommand('', cmds)).toBeNull(); expect(matchCommand('открой ютуб', null)).toBeNull(); });
});

describe('Действия команд', () => {
  it('подставляет {query}', () => expect(resolveActions(cmds[1], 'котики')[0].value).toBe('котики'));
  it('не меняет исходную команду', () => { resolveActions(cmds[1], 'x'); expect(cmds[1].actions[0].value).toBe('{query}'); });
  it('перевод в инструменты', () => {
    expect(actionToTool({ type: 'open_url', value: 'a' })).toEqual({ name: 'open_url', args: { url: 'a' } });
    expect(actionToTool({ type: 'set_volume', value: '40' })).toEqual({ name: 'set_volume', args: { level: 40 } });
    expect(actionToTool({ type: 'press_keys', value: 'ctrl+c' })).toEqual({ name: 'press_keys', args: { keys: 'ctrl+c' } });
    expect(actionToTool({ type: 'say', value: 'x' })).toBeNull();
    expect(actionToTool({ type: 'animation', value: 'dance' })).toBeNull();
  });
  it('типы действий в main и renderer совпадают', () => expect(ACTION_TYPES.map((a) => a[0])).toEqual(MAIN_TYPES));
  it('примеры команд валидны', () => { for (const c of EXAMPLE_COMMANDS) expect(() => normalizeCommand(c)).not.toThrow(); });
  it('пример «найди» работает', () => {
    const list = EXAMPLE_COMMANDS.map((c) => normalizeCommand(c));
    expect(matchCommand('загугли погоду', list).query).toBe('погоду');
  });
});

describe('Хранение команд', () => {
  let store;
  beforeEach(() => { store = new Store(fs.mkdtempSync(path.join(os.tmpdir(), 'stella-cmd-'))); });
  it('валидация', () => {
    expect(() => normalizeCommand({ triggers: ['a'], actions: [{ type: 'say', value: 'x' }] })).toThrow(/название/);
    expect(() => normalizeCommand({ name: 'x', actions: [{ type: 'say', value: 'x' }] })).toThrow(/триггер/);
    expect(() => normalizeCommand({ name: 'x', triggers: 'a', actions: [{ type: 'hack', value: 'x' }] })).toThrow(/действие/);
  });
  it('триггеры из строки, в нижнем регистре, без пустых', () => expect(normalizeCommand({ name: 'x', triggers: 'Открой Ютуб\n\n, Включи', actions: [{ type: 'say' }] }).triggers).toEqual(['открой ютуб', 'включи']));
  it('сохраняет, обновляет и удаляет', () => {
    const c = store.saveCommand({ name: 'A', triggers: ['a'], actions: [{ type: 'say', value: '1' }] });
    store.saveCommand({ ...c, name: 'B' });
    expect(store.listCommands()).toHaveLength(1);
    expect(store.listCommands()[0].name).toBe('B');
    store.deleteCommand(c.id);
    expect(store.listCommands()).toHaveLength(0);
  });
  it('команды у каждого аккаунта свои', () => {
    store.data.currentAccount = 'a';
    store.saveCommand({ name: 'A', triggers: ['a'], actions: [{ type: 'say' }] });
    store.data.currentAccount = 'b';
    expect(store.listCommands()).toHaveLength(0);
  });
  it('импорт пропускает битые записи', () => {
    expect(store.importCommands([{ name: 'ok', triggers: ['x'], actions: [{ type: 'say' }] }, { name: '' }, null])).toBe(1);
    expect(() => store.importCommands({})).toThrow();
  });
  it('listCommands возвращает копию', () => {
    store.saveCommand({ name: 'A', triggers: ['a'], actions: [{ type: 'say' }] });
    store.listCommands()[0].name = 'hack';
    expect(store.listCommands()[0].name).toBe('A');
  });
  it('новые настройки: avatarSide и commandMatch проверяются', () => {
    store.updateSettings({ avatarSide: 'top', commandMatch: 'regex' });
    expect(store.getSettings()).toMatchObject({ avatarSide: 'right', commandMatch: 'contains' });
    store.updateSettings({ avatarSide: 'left', commandMatch: 'exact' });
    expect(store.getSettings()).toMatchObject({ avatarSide: 'left', commandMatch: 'exact' });
  });
});

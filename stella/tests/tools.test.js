import { describe, it, expect, beforeEach, vi } from 'vitest';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { TOOL_DEFS, TOOL_NAMES, LABELS, createExecutor, expandPath, searchUrl, validateUrl, truncate, fmtSize } = require('../src/main/computer/tools.js');

function makeDeps(home, overrides = {}) {
  const calls = { exec: [], opened: [], trashed: [], notified: [], timers: [], avatar: [], memories: [] };
  const deps = {
    platform: 'linux', homedir: home, fs: fsp, calls,
    exec: vi.fn(async (cmd, args) => { calls.exec.push([cmd, args]); return { code: 0, stdout: 'ok', stderr: '' }; }),
    runShell: vi.fn(async (c) => ({ code: 0, stdout: 'out:' + c, stderr: '' })),
    spawnDetached: vi.fn(async () => {}),
    shell: { openExternal: async (u) => calls.opened.push(u), openPath: async (p) => { calls.opened.push(p); return ''; }, trashItem: async (p) => calls.trashed.push(p) },
    clipboard: { text: '', readText() { return this.text; }, writeText(t) { this.text = t; } },
    notify: (t, b) => calls.notified.push([t, b]),
    screenshot: async () => ({ dataUrl: 'data:image/jpeg;base64,AAA', width: 1000, height: 500, bounds: { x: 0, y: 0, width: 2000, height: 1000 }, scaleFactor: 1 }),
    screenInfo: async () => [{ bounds: { x: 0, y: 0, width: 1920, height: 1080 }, scaleFactor: 1.25, primary: true }],
    cursorPosition: async () => ({ x: 3, y: 4 }),
    killPid: vi.fn(),
    store: { addMemory: (t) => calls.memories.push(t) },
    onTimer: (m) => calls.timers.push(m),
    avatar: (c) => calls.avatar.push(c),
    getSettings: () => ({ commandTimeout: 30 }),
    ...overrides,
  };
  return deps;
}

let home, deps, ex;
beforeEach(() => { home = fs.mkdtempSync(path.join(os.tmpdir(), 'stella-tools-')); deps = makeDeps(home); ex = createExecutor(deps); });

describe('Схема инструментов', () => {
  it('больше 35 инструментов', () => expect(TOOL_DEFS.length).toBeGreaterThanOrEqual(35));
  it('уникальные имена', () => expect(new Set(TOOL_NAMES).size).toBe(TOOL_NAMES.length));
  it('у каждого есть описание и русская подпись', () => {
    for (const t of TOOL_DEFS) { expect(t.function.description.length).toBeGreaterThan(5); expect(LABELS[t.function.name]).toBeTruthy(); }
  });
  it('required ⊆ properties', () => {
    for (const t of TOOL_DEFS) for (const r of t.function.parameters.required) expect(t.function.parameters.properties).toHaveProperty(r);
  });
  it('у каждого инструмента есть обработчик', () => { for (const n of TOOL_NAMES) expect(typeof ex.handlers[n]).toBe('function'); });
});

describe('Вспомогательные функции', () => {
  it('expandPath: ~ и алиасы', () => {
    expect(expandPath('~', home)).toBe(home);
    expect(expandPath('~/a/b', home)).toBe(path.join(home, 'a/b'));
    expect(expandPath('Рабочий стол', home)).toBe(path.join(home, 'Desktop'));
    expect(expandPath('загрузки', home)).toBe(path.join(home, 'Downloads'));
    expect(expandPath('docs/x.txt', home)).toBe(path.join(home, 'docs/x.txt'));
    expect(expandPath('"/tmp/q"', home)).toBe('/tmp/q');
    expect(() => expandPath('', home)).toThrow();
  });
  it('searchUrl', () => {
    expect(searchUrl('лофи музыка', 'youtube')).toBe('https://www.youtube.com/results?search_query=' + encodeURIComponent('лофи музыка'));
    expect(searchUrl('x', 'yandex')).toContain('yandex.ru');
    expect(searchUrl('x', 'unknown')).toContain('google.com');
    expect(() => searchUrl(' ')).toThrow();
  });
  it('validateUrl добавляет https и отвергает опасные схемы', () => {
    expect(validateUrl('youtube.com')).toBe('https://youtube.com/');
    expect(() => validateUrl('javascript:alert(1)')).toThrow();
    expect(() => validateUrl('file:///etc/passwd')).toThrow();
  });
  it('truncate и fmtSize', () => {
    expect(truncate('abc', 10)).toBe('abc');
    expect(truncate('a'.repeat(20), 5)).toContain('обрезано');
    expect(fmtSize(10)).toBe('10 Б');
    expect(fmtSize(2048)).toBe('2.0 КБ');
    expect(fmtSize(5 * 1024 ** 3)).toBe('5.00 ГБ');
  });
});

describe('Файлы', () => {
  it('пишет, читает и дописывает', async () => {
    expect((await ex.execute('write_file', { path: 'notes/plan.txt', content: 'Привет' })).ok).toBe(true);
    await ex.execute('write_file', { path: 'notes/plan.txt', content: '!', append: true });
    const r = await ex.execute('read_file', { path: '~/notes/plan.txt' });
    expect(r.output).toBe('Привет!');
  });
  it('список папки: папки сверху, скрытые не показываются', async () => {
    fs.mkdirSync(path.join(home, 'zdir')); fs.writeFileSync(path.join(home, 'a.txt'), '1'); fs.writeFileSync(path.join(home, '.hidden'), '');
    const r = await ex.execute('list_directory', { path: '~' });
    const lines = r.output.split('\n').slice(1);
    expect(lines[0]).toContain('zdir');
    expect(r.output).toContain('a.txt');
    expect(r.output).not.toContain('.hidden');
    expect((await ex.execute('list_directory', { path: '~', show_hidden: true })).output).toContain('.hidden');
  });
  it('пустая папка', async () => { fs.mkdirSync(path.join(home, 'e')); expect((await ex.execute('list_directory', { path: 'e' })).output).toContain('пуста'); });
  it('чтение папки как файла — ошибка', async () => { const r = await ex.execute('read_file', { path: '~' }); expect(r.ok).toBe(false); expect(r.output).toMatch(/папка/); });
  it('двоичный файл не выводится', async () => { fs.writeFileSync(path.join(home, 'b.bin'), Buffer.from([1, 0, 2, 0])); expect((await ex.execute('read_file', { path: 'b.bin' })).output).toMatch(/Двоичный/); });
  it('несуществующий файл — ok:false', async () => { const r = await ex.execute('read_file', { path: 'nope.txt' }); expect(r.ok).toBe(false); expect(r.output).toMatch(/^Ошибка/); });
  it('создаёт папку, перемещает и копирует', async () => {
    await ex.execute('create_folder', { path: 'x/y' });
    fs.writeFileSync(path.join(home, 'x/y/f.txt'), 'data');
    await ex.execute('copy_path', { source: 'x/y/f.txt', destination: 'copy/f.txt' });
    await ex.execute('move_path', { source: 'x/y/f.txt', destination: 'moved/g.txt' });
    expect(fs.readFileSync(path.join(home, 'copy/f.txt'), 'utf8')).toBe('data');
    expect(fs.existsSync(path.join(home, 'moved/g.txt'))).toBe(true);
    expect(fs.existsSync(path.join(home, 'x/y/f.txt'))).toBe(false);
  });
  it('удаление — в корзину', async () => {
    fs.writeFileSync(path.join(home, 'del.txt'), '');
    const r = await ex.execute('delete_path', { path: 'del.txt' });
    expect(r.ok).toBe(true);
    expect(deps.calls.trashed[0]).toBe(path.join(home, 'del.txt'));
  });
  it('поиск файлов по имени', async () => {
    fs.mkdirSync(path.join(home, 'deep/er'), { recursive: true });
    fs.writeFileSync(path.join(home, 'deep/er/Report_2024.docx'), '');
    fs.mkdirSync(path.join(home, 'node_modules/report'), { recursive: true });
    const r = await ex.execute('search_files', { query: 'report' });
    expect(r.output).toContain('Report_2024.docx');
    expect(r.output).not.toContain('node_modules');
  });
  it('поиск: ничего не найдено', async () => expect((await ex.execute('search_files', { query: 'zzzz' })).output).toMatch(/Ничего/));
});

describe('Система', () => {
  it('run_command возвращает код и вывод', async () => {
    const r = await ex.execute('run_command', { command: 'echo hi' });
    expect(r.output).toContain('Код выхода: 0');
    expect(r.output).toContain('out:echo hi');
    expect(deps.runShell).toHaveBeenCalledWith('echo hi', { cwd: home, timeout: 30000 });
  });
  it('run_command: пустая команда', async () => expect((await ex.execute('run_command', { command: ' ' })).ok).toBe(false));
  it('run_command: stderr и таймаут', async () => {
    deps.runShell.mockResolvedValueOnce({ code: 1, stdout: '', stderr: 'boom', timedOut: true });
    const r = await ex.execute('run_command', { command: 'x' });
    expect(r.output).toContain('STDERR');
    expect(r.output).toContain('превышено время');
  });
  it('open_url и web_search открывают браузер', async () => {
    await ex.execute('open_url', { url: 'example.com' });
    await ex.execute('web_search', { query: 'котики', engine: 'google' });
    expect(deps.calls.opened[0]).toBe('https://example.com/');
    expect(deps.calls.opened[1]).toContain('google.com/search?q=');
  });
  it('open_url отклоняет javascript:', async () => expect((await ex.execute('open_url', { url: 'javascript:alert(1)' })).ok).toBe(false));
  it('launch_app на Linux запускает процесс', async () => {
    await ex.execute('launch_app', { name: 'gedit' });
    expect(deps.spawnDetached).toHaveBeenCalledWith('gedit', []);
  });
  it('system_info содержит пути', async () => {
    const r = await ex.execute('system_info');
    expect(r.output).toContain('Рабочий стол');
    expect(r.output).toContain(home);
  });
  it('буфер обмена', async () => {
    await ex.execute('clipboard_write', { text: 'скопируй' });
    expect((await ex.execute('clipboard_read')).output).toBe('скопируй');
  });
  it('уведомление', async () => { await ex.execute('notify', { text: 'Тест' }); expect(deps.calls.notified[0]).toEqual(['Стелла', 'Тест']); });
  it('kill_process по pid', async () => { await ex.execute('kill_process', { pid: 1234 }); expect(deps.killPid).toHaveBeenCalledWith(1234); });
  it('kill_process без параметров — ошибка', async () => expect((await ex.execute('kill_process', {})).ok).toBe(false));
  it('ошибка внешней программы с подсказкой про xdotool', async () => {
    deps.exec.mockResolvedValueOnce({ code: 'ENOENT', stdout: '', stderr: 'spawn xdotool ENOENT' });
    const r = await ex.execute('mouse_click', {});
    expect(r.ok).toBe(false);
    expect(r.output).toContain('xdotool');
  });
  it('информация об экранах', async () => expect((await ex.execute('get_screen_info')).output).toContain('1920×1080'));
  it('дата и время', async () => expect((await ex.execute('get_datetime')).ok).toBe(true));
  it('power_action cancel на Linux', async () => {
    const r = await ex.execute('power_action', { action: 'cancel' });
    expect(r.output).toContain('отменено');
    expect(deps.calls.exec.at(-1)).toEqual(['shutdown', ['-c']]);
  });
});

describe('Экран и мышь', () => {
  it('скриншот возвращает картинку', async () => {
    const r = await ex.execute('take_screenshot');
    expect(r.image).toMatch(/^data:image\/jpeg/);
    expect(r.output).toContain('1000×500');
  });
  it('координаты кликов масштабируются по скриншоту', async () => {
    await ex.execute('take_screenshot');
    await ex.execute('mouse_click', { x: 100, y: 50 });
    expect(deps.calls.exec.at(-1)[1]).toEqual(['mousemove', '200', '100', 'click', '1']);
  });
  it('без скриншота координаты как есть', async () => {
    await ex.execute('mouse_move', { x: 7, y: 8 });
    expect(deps.calls.exec.at(-1)[1]).toEqual(['mousemove', '7', '8']);
  });
  it('учитывает масштаб и смещение второго монитора', async () => {
    const d = makeDeps(home, { screenshot: async () => ({ dataUrl: 'x', width: 960, height: 540, bounds: { x: 1920, y: 0, width: 1920, height: 1080 }, scaleFactor: 2 }) });
    const e = createExecutor(d);
    await e.execute('take_screenshot');
    expect(e.mapXY(480, 270)).toEqual({ x: 1920 * 2 + 1920, y: 1080 });
  });
  it('на macOS координаты в точках (без scaleFactor)', async () => {
    const d = makeDeps(home, { platform: 'darwin', screenshot: async () => ({ dataUrl: 'x', width: 1440, height: 900, bounds: { x: 0, y: 0, width: 1440, height: 900 }, scaleFactor: 2 }) });
    const e = createExecutor(d);
    await e.execute('take_screenshot');
    expect(e.mapXY(100, 100)).toEqual({ x: 100, y: 100 });
  });
  it('перетаскивание и ввод текста', async () => {
    expect((await ex.execute('mouse_drag', { from_x: 1, from_y: 2, to_x: 3, to_y: 4 })).ok).toBe(true);
    expect((await ex.execute('type_text', { text: 'Привет' })).output).toContain('6 символов');
    expect((await ex.execute('press_keys', { keys: 'ctrl+v' })).ok).toBe(true);
  });
  it('позиция курсора', async () => expect((await ex.execute('get_cursor_position')).output).toContain('3, 4'));
});

describe('Таймеры, память, аватар', () => {
  it('таймер срабатывает', async () => {
    vi.useFakeTimers();
    const r = await ex.execute('set_timer', { seconds: 5, message: 'Чай!' });
    expect(r.ok).toBe(true);
    vi.advanceTimersByTime(5000);
    expect(deps.calls.timers).toEqual(['Чай!']);
    vi.useRealTimers();
  });
  it('таймер: валидация времени', async () => {
    expect((await ex.execute('set_timer', { seconds: -1, message: 'x' })).ok).toBe(false);
    expect((await ex.execute('set_timer', { seconds: 9e9, message: 'x' })).ok).toBe(false);
  });
  it('cancelTimers отменяет таймеры', async () => {
    vi.useFakeTimers();
    await ex.execute('set_timer', { seconds: 1, message: 'x' });
    ex.cancelTimers();
    vi.advanceTimersByTime(2000);
    expect(deps.calls.timers).toEqual([]);
    vi.useRealTimers();
  });
  it('remember_fact', async () => { await ex.execute('remember_fact', { fact: 'Любит чай' }); expect(deps.calls.memories).toEqual(['Любит чай']); });
  it('play_animation передаёт команду аватару', async () => {
    await ex.execute('play_animation', { animation: 'dance', emotion: 'happy' });
    expect(deps.calls.avatar[0]).toEqual({ animation: 'dance', emotion: 'happy' });
  });
  it('wait ограничен 30 секундами', async () => {
    vi.useFakeTimers();
    const p = ex.execute('wait', { seconds: 999 });
    vi.advanceTimersByTime(30000);
    expect((await p).output).toContain('30');
    vi.useRealTimers();
  });
  it('неизвестный инструмент', async () => expect(await ex.execute('teleport', {})).toEqual({ ok: false, output: 'Неизвестный инструмент: teleport' }));
});

describe('Новые инструменты', () => {
  it('hold_keys и mouse_move_relative', async () => {
    expect((await ex.execute('hold_keys', { keys: 'w', ms: 200 })).output).toContain('Удерживала w');
    expect(deps.calls.exec.at(-1)[1]).toEqual(['keydown', 'w', 'sleep', '0.2', 'keyup', 'w']);
    expect((await ex.execute('mouse_move_relative', { dx: 10, dy: 0 })).ok).toBe(true);
  });
  it('ui_list_elements на Linux — понятная ошибка', async () => {
    const r = await ex.execute('ui_list_elements', {});
    expect(r.ok).toBe(false);
    expect(r.output).toMatch(/Windows/);
  });
  it('ui_click на Windows: не найдено', async () => {
    const d = makeDeps(home, { platform: 'win32' });
    d.exec = async () => ({ code: 0, stdout: 'NOT_FOUND', stderr: '' });
    const r = await createExecutor(d).execute('ui_click', { name: 'ОК' });
    expect(r.ok).toBe(false);
    expect(r.output).toContain('не найден');
  });
  it('ui_click на Windows: нажато', async () => {
    const d = makeDeps(home, { platform: 'win32' });
    d.exec = async () => ({ code: 0, stdout: 'INVOKED: Сохранить', stderr: '' });
    expect((await createExecutor(d).execute('ui_click', { name: 'сохр' })).output).toBe('Нажато: Сохранить');
  });
  it('agent_task: Antigravity не установлена', async () => {
    const d = makeDeps(home, { spawnDetached: async () => { throw new Error('ENOENT'); } });
    const r = await createExecutor(d).execute('agent_task', { agent: 'antigravity', task: 'сделай сайт' });
    expect(r.ok).toBe(false);
    expect(r.output).toMatch(/Antigravity не установлена/);
  });
  it('agent_task: пустая задача', async () => expect((await ex.execute('agent_task', { agent: 'antigravity', task: ' ' })).ok).toBe(false));
  it('agent_task: задача копируется и вставляется', async () => {
    vi.useFakeTimers();
    const p = ex.execute('agent_task', { agent: 'antigravity', task: 'Сделай сайт' });
    await vi.runAllTimersAsync();
    const r = await p;
    vi.useRealTimers();
    expect(r.ok).toBe(true);
    expect(deps.clipboard.text).toBe('Сделай сайт');
    expect(deps.calls.exec.map((c) => c[1].join(' '))).toEqual(expect.arrayContaining(['key ctrl+l', 'key ctrl+v', 'key Return']));
  });
});

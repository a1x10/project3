import { describe, it, expect, beforeEach, vi } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { createStomach } = require('../src/main/stomach.js');

let home, st, trashed, appDir;
beforeEach(() => {
  home = fs.mkdtempSync(path.join(os.tmpdir(), 'stomach-home-'));
  appDir = path.join(home, 'StellaApp');
  fs.mkdirSync(appDir);
  trashed = [];
  st = createStomach({ dir: path.join(home, '.stella', 'stomach'), home, platform: 'linux', protect: [appDir], trash: async (p) => { trashed.push({ name: path.basename(p), content: fs.existsSync(p) && fs.statSync(p).isFile() ? fs.readFileSync(p, 'utf8') : null }); fs.rmSync(p, { recursive: true, force: true }); } });
});
const file = (rel, content = 'вкусно') => { const p = path.join(home, rel); fs.mkdirSync(path.dirname(p), { recursive: true }); fs.writeFileSync(p, content); return p; };

describe('Съесть', () => {
  it('файл исчезает с рабочего стола и попадает в желудок', async () => {
    const p = file('Desktop/отчёт.docx', 'данные');
    const [r] = await st.eat([p]);
    expect(r).toMatchObject({ ok: true, name: 'отчёт.docx', isDir: false, size: 'данные'.length * 2 - 0 || expect.any(Number) });
    expect(fs.existsSync(p)).toBe(false);
    expect(st.list()).toHaveLength(1);
  });
  it('папку целиком', async () => {
    file('Desktop/проект/a.txt'); file('Desktop/проект/b/c.txt');
    const [r] = await st.eat([path.join(home, 'Desktop/проект')]);
    expect(r).toMatchObject({ ok: true, isDir: true });
    expect(r.size).toBeGreaterThan(0);
    expect(fs.existsSync(path.join(home, 'Desktop/проект'))).toBe(false);
  });
  it('ярлык приложения помечается как ярлык (программа не удаляется)', async () => {
    const [r] = await st.eat([file('Desktop/Telegram.lnk')]);
    expect(r.isShortcut).toBe(true);
  });
  it('несколько файлов за раз', async () => {
    const r = await st.eat([file('Desktop/1.txt'), file('Desktop/2.txt'), file('Desktop/3.txt')]);
    expect(r.every((x) => x.ok)).toBe(true);
    expect(st.list()).toHaveLength(3);
  });
  it('несуществующий файл', async () => expect((await st.eat([path.join(home, 'nope.txt')]))[0]).toMatchObject({ ok: false, error: 'Такого файла уже нет' }));
  it('на другой диск — копирует и удаляет оригинал', async () => {
    const p = file('Desktop/far.txt', 'далеко');
    const fsp = require('fs/promises');
    const orig = fsp.rename;
    const spy = vi.spyOn(fsp, 'rename').mockImplementationOnce(async () => { throw Object.assign(new Error('cross-device'), { code: 'EXDEV' }); });
    const [r] = await st.eat([p]);
    spy.mockRestore();
    expect(r.ok).toBe(true);
    expect(fs.existsSync(p)).toBe(false);
    expect(fs.readFileSync(path.join(st.dir, r.id), 'utf8')).toBe('далеко');
    expect(fsp.rename).toBe(orig);
  });
});

describe('Что есть нельзя', () => {
  it('системные папки', () => {
    expect(st.forbidden('/etc')).toMatch(/системная/);
    expect(st.forbidden('/usr/bin/ls')).toMatch(/системная/);
  });
  it('диск целиком и домашнюю папку', () => {
    expect(st.forbidden('/')).toBeTruthy();
    expect(st.forbidden(home)).toMatch(/домашняя/);
  });
  it('важные папки пользователя целиком', () => {
    expect(st.forbidden(path.join(home, 'Desktop'))).toMatch(/Desktop/);
    expect(st.forbidden(path.join(home, 'Documents'))).toMatch(/важная/);
    expect(st.forbidden(path.join(home, 'Desktop', 'file.txt'))).toBeNull();
  });
  it('себя и свой желудок', () => {
    expect(st.forbidden(appDir)).toMatch(/себя/);
    expect(st.forbidden(path.join(appDir, 'resources', 'app.asar'))).toMatch(/себя/);
    expect(st.forbidden(st.dir)).toMatch(/себя/);
    expect(st.forbidden(path.join(home, '.stella'))).toMatch(/себя/); // папка, содержащая желудок
  });
  it('Windows: системные пути и корень диска', () => {
    const w = createStomach({ dir: 'C:\\Users\\me\\AppData\\Roaming\\Stella\\stomach', home: 'C:\\Users\\me', platform: 'win32', trash: async () => {} });
    expect(w.forbidden('C:\\Windows\\System32')).toMatch(/системная/);
    expect(w.forbidden('C:\\Program Files\\App')).toMatch(/системная/);
    expect(w.forbidden('D:\\')).toBeTruthy();
    expect(w.forbidden('C:\\Users\\me')).toMatch(/домашняя/);
    expect(w.forbidden('c:\\users\\ME\\desktop')).toBeTruthy();
    expect(w.forbidden('C:\\Users\\me\\Desktop\\мусор.txt')).toBeNull();
  });
  it('запрещённое не трогается при попытке съесть', async () => {
    const r = await st.eat([path.join(home, 'Desktop'), appDir]);
    expect(r.every((x) => !x.ok)).toBe(true);
    expect(fs.existsSync(appDir)).toBe(true);
  });
});

describe('Выплюнуть и переварить', () => {
  it('выплюнуть возвращает файл на место', async () => {
    const p = file('Desktop/важное.txt', 'не ешь меня');
    const [r] = await st.eat([p]);
    const back = await st.spit(r.id);
    expect(back.restoredTo).toBe(p);
    expect(fs.readFileSync(p, 'utf8')).toBe('не ешь меня');
    expect(st.list()).toHaveLength(0);
  });
  it('если на месте уже новый файл — возвращает рядом с пометкой', async () => {
    const p = file('Desktop/a.txt', 'старый');
    const [r] = await st.eat([p]);
    file('Desktop/a.txt', 'новый');
    const back = await st.spit(r.id);
    expect(back.restoredTo).toBe(path.join(home, 'Desktop/a (возвращён).txt'));
    expect(fs.readFileSync(back.restoredTo, 'utf8')).toBe('старый');
  });
  it('восстанавливает удалённую родительскую папку', async () => {
    const p = file('Desktop/x/y/z.txt');
    const [r] = await st.eat([p]);
    fs.rmSync(path.join(home, 'Desktop/x'), { recursive: true });
    await st.spit(r.id);
    expect(fs.existsSync(p)).toBe(true);
  });
  it('выплюнуть несуществующее', async () => expect(st.spit('nope')).rejects.toThrow(/нет/));
  it('переварить — в Корзину с исходным именем', async () => {
    const [r] = await st.eat([file('Desktop/старьё.txt', 'хлам')]);
    const done = await st.digest(r.id);
    expect(done).toHaveLength(1);
    expect(trashed).toEqual([{ name: 'старьё.txt', content: 'хлам' }]);
    expect(st.list()).toHaveLength(0);
    expect(fs.existsSync(path.join(st.dir, r.id))).toBe(false);
  });
  it('переварить всё', async () => {
    await st.eat([file('1.txt'), file('2.txt')]);
    expect(await st.digest()).toHaveLength(2);
    expect(trashed).toHaveLength(2);
  });
  it('автопереваривание через 7 дней', async () => {
    await st.eat([file('old.txt')]);
    expect(await st.autoDigest(Date.now() + 3 * 86400000)).toHaveLength(0);
    expect(await st.autoDigest(Date.now() + 8 * 86400000)).toHaveLength(1);
  });
  it('если Корзина недоступна — файл остаётся в желудке', async () => {
    const s2 = createStomach({ dir: st.dir, home, platform: 'linux', trash: async () => { throw new Error('no trash'); } });
    await s2.eat([file('keep.txt')]);
    expect(await s2.digest()).toHaveLength(0);
    expect(s2.list()).toHaveLength(1);
  });
});

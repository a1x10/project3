'use strict';
// «Желудок»: файлы, которые перетащили на персонажа. Съеденное можно выплюнуть (вернуть на место),
// а через N дней оно «переваривается» — уходит в Корзину системы.
const fs = require('fs');
const fsp = require('fs/promises');
const path = require('path');
const os = require('os');
const crypto = require('crypto');
const { isSystemPath } = require('./computer/safety');

async function moveAny(src, dst) {
  try { await fsp.rename(src, dst); }
  catch (e) {
    if (e.code !== 'EXDEV') throw e; // другой диск — копируем и удаляем
    await fsp.cp(src, dst, { recursive: true, errorOnExist: true, force: false });
    await fsp.rm(src, { recursive: true, force: true });
  }
}

async function sizeOf(p) {
  const st = await fsp.lstat(p);
  if (!st.isDirectory()) return st.size;
  let n = 0;
  for (const e of await fsp.readdir(p, { withFileTypes: true })) n += await sizeOf(path.join(p, e.name)).catch(() => 0);
  return n;
}

/**
 * @param {object} o
 * @param {string} o.dir папка желудка
 * @param {(p:string) => Promise<void>} o.trash отправить в Корзину
 * @param {string[]} [o.protect] пути, которые нельзя есть (папка приложения, данные и т.д.)
 * @param {string} [o.platform]
 * @param {string} [o.home]
 * @param {number} [o.digestDays]
 */
function createStomach(o) {
  const platform = o.platform || process.platform;
  const home = o.home || os.homedir();
  const index = path.join(o.dir, 'stomach.json');
  const norm = (p) => (platform === 'win32' ? path.win32.resolve(p).toLowerCase() : path.resolve(p));
  const protect = [o.dir, ...(o.protect || [])].filter(Boolean).map(norm);

  const load = () => { try { return JSON.parse(fs.readFileSync(index, 'utf8')); } catch { return []; } };
  const save = (list) => { fs.mkdirSync(o.dir, { recursive: true }); fs.writeFileSync(index, JSON.stringify(list, null, 1)); };

  /** Почему этот путь нельзя съесть (или null, если можно). */
  function forbidden(p) {
    const n = norm(p);
    if (isSystemPath(p, platform)) return 'Это системная папка — её есть нельзя, Windows сломается';
    if (/^[a-z]:\\?$/i.test(n) || n === '/') return 'Это целый диск — он не влезет';
    if (n === norm(home)) return 'Это вся твоя домашняя папка — слишком много';
    for (const d of ['Desktop', 'Documents', 'Downloads', 'Pictures', 'Music', 'Videos']) if (n === norm(path.join(home, d))) return `Это целая папка «${d}» — не буду, она важная`;
    for (const pr of protect) if (n === pr || n.startsWith(pr + (platform === 'win32' ? '\\' : '/')) || pr.startsWith(n + (platform === 'win32' ? '\\' : '/'))) return 'Это мои собственные файлы — себя я не ем';
    return null;
  }

  async function eat(paths) {
    const list = load();
    const out = [];
    for (const p of paths || []) {
      const name = path.basename(p);
      const reason = forbidden(p);
      if (reason) { out.push({ name, original: p, ok: false, error: reason }); continue; }
      try {
        const st = await fsp.lstat(p);
        const id = 'f_' + Date.now().toString(36) + crypto.randomBytes(3).toString('hex');
        const dst = path.join(o.dir, id);
        const size = await sizeOf(p).catch(() => 0);
        fs.mkdirSync(o.dir, { recursive: true });
        await moveAny(p, dst);
        const item = { id, name, original: p, isDir: st.isDirectory(), isShortcut: /\.(lnk|url|desktop)$/i.test(name), size, eatenAt: Date.now() };
        list.push(item);
        out.push({ ...item, ok: true });
      } catch (e) {
        out.push({ name, original: p, ok: false, error: e.code === 'EBUSY' || e.code === 'EPERM' ? 'Файл занят другой программой или нет прав — не могу проглотить' : e.code === 'ENOENT' ? 'Такого файла уже нет' : e.message });
      }
    }
    save(list);
    return out;
  }

  /** Вернуть файл на место (если там уже есть такой — с пометкой «(возвращён)»). */
  async function spit(id) {
    const list = load();
    const item = list.find((x) => x.id === id);
    if (!item) throw new Error('В желудке такого нет');
    let target = item.original;
    if (fs.existsSync(target)) {
      const ext = item.isDir ? '' : path.extname(target);
      const base = target.slice(0, target.length - ext.length);
      let i = 1;
      do { target = `${base} (возвращён${i > 1 ? ' ' + i : ''})${ext}`; i++; } while (fs.existsSync(target));
    }
    await fsp.mkdir(path.dirname(target), { recursive: true });
    await moveAny(path.join(o.dir, id), target);
    save(list.filter((x) => x.id !== id));
    return { ...item, restoredTo: target };
  }

  /** Переварить: отправить в Корзину (один файл или всё). */
  async function digest(id) {
    const list = load();
    const keep = [];
    const done = [];
    for (const item of list) {
      if (id && item.id !== id) { keep.push(item); continue; }
      const p = path.join(o.dir, item.id);
      try {
        if (fs.existsSync(p)) {
          // в Корзине файл должен называться как раньше
          const named = path.join(o.dir, '_digest', item.name);
          await fsp.mkdir(path.dirname(named), { recursive: true });
          await fsp.rm(named, { recursive: true, force: true });
          await moveAny(p, named);
          await o.trash(named);
        }
        done.push(item);
      } catch { keep.push(item); }
    }
    save(keep);
    return done;
  }

  /** Автоматически переварить то, что лежит дольше digestDays. */
  async function autoDigest(now = Date.now()) {
    const days = o.digestDays ?? 7;
    const old = load().filter((x) => now - x.eatenAt > days * 86400000);
    const res = [];
    for (const x of old) res.push(...(await digest(x.id)));
    return res;
  }

  return { eat, spit, digest, autoDigest, list: load, forbidden, dir: o.dir };
}

module.exports = { createStomach };

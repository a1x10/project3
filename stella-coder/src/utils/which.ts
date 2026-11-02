import { accessSync, constants } from 'node:fs';
import path from 'node:path';

const cache = new Map<string, string | null>();

/** Locate an executable on PATH (handles PATHEXT on Windows). */
export function which(cmd: string): string | null {
  if (cache.has(cmd)) return cache.get(cmd)!;
  const exts = process.platform === 'win32' ? (process.env.PATHEXT ?? '.EXE;.CMD;.BAT;.COM').split(';') : [''];
  const dirs = (process.env.PATH ?? '').split(path.delimiter).filter(Boolean);
  for (const d of dirs) {
    for (const ext of exts) {
      const full = path.join(d, cmd + ext);
      try {
        accessSync(full, process.platform === 'win32' ? constants.F_OK : constants.X_OK);
        cache.set(cmd, full);
        return full;
      } catch {
        /* next */
      }
    }
  }
  cache.set(cmd, null);
  return null;
}

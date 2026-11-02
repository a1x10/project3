import { promises as fs, constants as fsc } from 'node:fs';
import path from 'node:path';

export async function exists(p: string): Promise<boolean> {
  try {
    await fs.access(p, fsc.F_OK);
    return true;
  } catch {
    return false;
  }
}

export async function readJson<T>(p: string, fallback: T): Promise<T> {
  try {
    return JSON.parse(await fs.readFile(p, 'utf8')) as T;
  } catch {
    return fallback;
  }
}

/** Atomic write: write to temp then rename (prevents half-written files on crash). */
export async function writeFileAtomic(p: string, data: string | Buffer, mode?: number): Promise<void> {
  await fs.mkdir(path.dirname(p), { recursive: true });
  const tmp = `${p}.${process.pid}.${Date.now()}.tmp`;
  await fs.writeFile(tmp, data, mode !== undefined ? { mode } : undefined);
  try {
    await fs.rename(tmp, p);
  } catch (e) {
    // Windows can fail rename over a locked file; fall back to direct write.
    await fs.writeFile(p, data, mode !== undefined ? { mode } : undefined);
    await fs.rm(tmp, { force: true });
    if ((e as NodeJS.ErrnoException).code !== 'EPERM' && (e as NodeJS.ErrnoException).code !== 'EEXIST') throw e;
  }
}

export async function writeJson(p: string, value: unknown, mode?: number): Promise<void> {
  await writeFileAtomic(p, JSON.stringify(value, null, 2) + '\n', mode);
}

export function isBinaryBuffer(buf: Buffer): boolean {
  const n = Math.min(buf.length, 8000);
  for (let i = 0; i < n; i++) if (buf[i] === 0) return true;
  return false;
}

export function detectEol(text: string): '\r\n' | '\n' {
  const crlf = (text.match(/\r\n/g) ?? []).length;
  const lf = (text.match(/(?<!\r)\n/g) ?? []).length;
  return crlf > lf ? '\r\n' : '\n';
}

export function toPosix(p: string): string {
  return p.split(path.sep).join('/');
}

export function truncate(text: string, max: number, note = '… [truncated]'): string {
  if (text.length <= max) return text;
  const head = Math.floor(max * 0.7);
  const tail = max - head;
  return text.slice(0, head) + `\n${note} ${text.length - max} chars omitted …\n` + text.slice(text.length - tail);
}

import { realpathSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import picomatch from 'picomatch';

export interface PathContext {
  cwd: string;
  roots: string[]; // workspace roots (project root + additional directories)
  confidential?: string[]; // glob patterns (relative to root, or absolute)
}

export interface ResolvedPath {
  abs: string; // lexical absolute path
  real: string; // symlinks resolved (nearest existing ancestor)
  inWorkspace: boolean;
  isSystem: boolean;
  isConfidential: boolean;
  relToRoot: string | null;
  viaSymlink: boolean;
}

const POSIX_SYSTEM = ['/etc', '/bin', '/sbin', '/usr', '/boot', '/dev', '/proc', '/sys', '/lib', '/lib64', '/var/lib', '/System', '/Library', '/private/etc'];
const WIN_SYSTEM = ['c:\\windows', 'c:\\program files', 'c:\\program files (x86)', 'c:\\programdata'];

export const DEFAULT_CONFIDENTIAL = ['**/.env', '**/.env.*', '**/*.pem', '**/*.key', '**/id_rsa*', '**/id_ed25519*', '**/.npmrc', '**/.pypirc', '**/credentials.json', '**/.aws/credentials', '**/secrets.*'];

export function expandHome(p: string): string {
  if (p === '~') return os.homedir();
  if (p.startsWith('~/') || p.startsWith('~\\')) return path.join(os.homedir(), p.slice(2));
  return p;
}

/** Resolve symlinks for the deepest existing ancestor, then re-append the missing tail. */
export function realpathLoose(abs: string): string {
  let cur = abs;
  const tail: string[] = [];
  for (let i = 0; i < 256; i++) {
    try {
      const r = realpathSync.native(cur);
      return tail.length ? path.join(r, ...tail.reverse()) : r;
    } catch {
      const parent = path.dirname(cur);
      if (parent === cur) return abs;
      tail.push(path.basename(cur));
      cur = parent;
    }
  }
  return abs;
}

function norm(p: string): string {
  const r = path.resolve(p);
  return process.platform === 'win32' ? r.toLowerCase() : r;
}

export function isWithin(child: string, parent: string): boolean {
  const c = norm(child);
  const p = norm(parent);
  if (c === p) return true;
  const rel = path.relative(p, c);
  return !!rel && !rel.startsWith('..') && !path.isAbsolute(rel);
}

export function isSystemPath(p: string): boolean {
  const n = norm(p);
  if (process.platform === 'win32') return WIN_SYSTEM.some((s) => n === s || n.startsWith(s + '\\'));
  return n === '/' || POSIX_SYSTEM.some((s) => n === s || n.startsWith(s + '/'));
}

export function resolvePath(input: string, ctx: PathContext): ResolvedPath {
  if (typeof input !== 'string' || !input.length) throw new Error('Path must be a non-empty string');
  if (input.includes('\0')) throw new Error('Path contains NUL byte');
  const abs = path.resolve(ctx.cwd, expandHome(input));
  const real = realpathLoose(abs);
  const realRoots = ctx.roots.map((r) => realpathLoose(path.resolve(r)));
  const inWorkspace = realRoots.some((r) => isWithin(real, r)) && ctx.roots.some((r) => isWithin(abs, r) || isWithin(real, realpathLoose(r)));
  const root = realRoots.find((r) => isWithin(real, r)) ?? null;
  const relToRoot = root ? path.relative(root, real).split(path.sep).join('/') : null;
  const patterns = [...DEFAULT_CONFIDENTIAL, ...(ctx.confidential ?? [])];
  const isConfidential = matchesAny(real, relToRoot, patterns);
  return { abs, real, inWorkspace, isSystem: isSystemPath(real), isConfidential, relToRoot, viaSymlink: norm(abs) !== norm(real) };
}

export function matchesAny(absPath: string, rel: string | null, patterns: string[]): boolean {
  const posixAbs = absPath.split(path.sep).join('/');
  for (const pat of patterns) {
    const p = expandHome(pat).split(path.sep).join('/');
    const isAbs = p.startsWith('/') || /^[A-Za-z]:\//.test(p);
    const m = picomatch(p.startsWith('//') ? p.slice(1) : p, { dot: true, nocase: process.platform === 'win32' });
    if (isAbs || p.startsWith('//')) {
      if (m(posixAbs)) return true;
    } else {
      if (rel !== null && m(rel)) return true;
      if (picomatch(p, { dot: true, basename: !p.includes('/') })(posixAbs)) return true;
    }
  }
  return false;
}

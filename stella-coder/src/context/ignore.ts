import { readFileSync } from 'node:fs';
import path from 'node:path';
import ignore, { type Ignore } from 'ignore';

export const DEFAULT_IGNORES = [
  '.git/',
  'node_modules/',
  'dist/',
  'build/',
  'out/',
  '.next/',
  '.nuxt/',
  '.svelte-kit/',
  '.turbo/',
  '.cache/',
  'coverage/',
  '.venv/',
  'venv/',
  'env/',
  '__pycache__/',
  '.mypy_cache/',
  '.pytest_cache/',
  '.ruff_cache/',
  '.tox/',
  'target/',
  '.gradle/',
  '.idea/',
  '.vs/',
  'bin/Debug/',
  'obj/',
  '*.pyc',
  '*.class',
  '*.o',
  '*.so',
  '*.dll',
  '*.exe',
  '*.min.js',
  '*.map',
  '.DS_Store',
  'Thumbs.db',
];

export class IgnoreMatcher {
  private ig: Ignore;
  constructor(
    readonly root: string,
    extra: string[] = [],
    useDefaults = true,
  ) {
    this.ig = ignore({ allowRelativePaths: true });
    if (useDefaults) this.ig.add(DEFAULT_IGNORES);
    for (const f of ['.gitignore', '.stellaignore']) {
      try {
        this.ig.add(readFileSync(path.join(root, f), 'utf8'));
      } catch {
        /* none */
      }
    }
    if (extra.length) this.ig.add(extra);
  }

  /** rel: posix path relative to root. dirs should end with '/'. */
  ignores(rel: string, isDir = false): boolean {
    if (!rel || rel === '.' || rel.startsWith('..')) return false;
    const p = isDir && !rel.endsWith('/') ? rel + '/' : rel;
    try {
      return this.ig.ignores(p);
    } catch {
      return false;
    }
  }

  addNested(dirRel: string, content: string) {
    const lines = content
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter((l) => l && !l.startsWith('#'))
      .map((l) => {
        const neg = l.startsWith('!');
        const body = neg ? l.slice(1) : l;
        const anchored = body.startsWith('/') ? body.slice(1) : '**/' + body;
        return (neg ? '!' : '') + (dirRel ? dirRel + '/' : '') + anchored;
      });
    this.ig.add(lines);
  }
}

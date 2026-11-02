import { promises as fs } from 'node:fs';
import path from 'node:path';
import type { IgnoreMatcher } from './ignore.js';

export interface WalkEntry {
  rel: string; // posix, relative to base
  abs: string;
  isDir: boolean;
  mtimeMs?: number;
  size?: number;
}

export interface WalkOptions {
  ignore?: IgnoreMatcher;
  maxFiles?: number;
  maxDepth?: number;
  includeDirs?: boolean;
  stat?: boolean;
  signal?: AbortSignal;
  followSymlinks?: boolean;
}

/** Breadth-first, ignore-aware directory walk. Never follows symlinked dirs by default (loop-safe). */
export async function* walk(base: string, opts: WalkOptions = {}): AsyncGenerator<WalkEntry> {
  const max = opts.maxFiles ?? 100_000;
  const maxDepth = opts.maxDepth ?? 64;
  const ig = opts.ignore;
  const igRoot = ig?.root ?? base;
  let count = 0;
  const queue: Array<{ dir: string; depth: number }> = [{ dir: base, depth: 0 }];
  while (queue.length) {
    if (opts.signal?.aborted) return;
    const { dir, depth } = queue.shift()!;
    let entries: import('node:fs').Dirent[];
    try {
      entries = await fs.readdir(dir, { withFileTypes: true });
    } catch {
      continue;
    }
    entries.sort((a, b) => a.name.localeCompare(b.name));
    for (const e of entries) {
      const abs = path.join(dir, e.name);
      const relIg = path.relative(igRoot, abs).split(path.sep).join('/');
      const rel = path.relative(base, abs).split(path.sep).join('/');
      let isDir = e.isDirectory();
      if (e.isSymbolicLink()) {
        if (!opts.followSymlinks) {
          try {
            const st = await fs.stat(abs);
            if (st.isDirectory()) continue; // skip symlinked dirs
          } catch {
            continue;
          }
        } else {
          try {
            isDir = (await fs.stat(abs)).isDirectory();
          } catch {
            continue;
          }
        }
      }
      if (ig && ig.ignores(relIg, isDir)) continue;
      if (isDir) {
        if (opts.includeDirs) yield { rel, abs, isDir: true };
        if (depth + 1 < maxDepth) queue.push({ dir: abs, depth: depth + 1 });
        continue;
      }
      let st: { mtimeMs: number; size: number } | undefined;
      if (opts.stat) {
        try {
          const s = await fs.stat(abs);
          st = { mtimeMs: s.mtimeMs, size: s.size };
        } catch {
          continue;
        }
      }
      yield { rel, abs, isDir: false, ...st };
      if (++count >= max) return;
    }
  }
}

import { promises as fs } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { stellaHome } from '../config/paths.js';

export interface InstructionFile {
  path: string;
  scope: 'user' | 'project' | 'local' | 'parent' | 'nested';
  content: string;
}

const NAMES = ['STELLA.md', '.stella/STELLA.md'];
const COMPAT = ['CLAUDE.md', 'AGENTS.md']; // read as fallbacks for interoperability

/**
 * STELLA.md discovery: global (~/.stella/STELLA.md), every directory from the filesystem root
 * down to the project root and cwd, plus STELLA.local.md (gitignored personal notes).
 * Supports @path imports (relative to the including file, max depth 5).
 */
export async function loadInstructions(root: string, cwd: string): Promise<InstructionFile[]> {
  const out: InstructionFile[] = [];
  const seen = new Set<string>();
  const add = async (p: string, scope: InstructionFile['scope']) => {
    const real = path.resolve(p);
    if (seen.has(real)) return;
    try {
      const raw = await fs.readFile(real, 'utf8');
      seen.add(real);
      out.push({ path: real, scope, content: await expandImports(raw, path.dirname(real), 0, seen) });
    } catch {
      /* missing */
    }
  };
  await add(path.join(stellaHome(), 'STELLA.md'), 'user');

  const dirs: string[] = [];
  let d = path.resolve(cwd);
  for (;;) {
    dirs.unshift(d);
    const parent = path.dirname(d);
    if (parent === d || d === os.homedir()) break;
    d = parent;
  }
  for (const dir of dirs) {
    const scope = path.resolve(dir) === path.resolve(root) ? 'project' : path.resolve(dir).startsWith(path.resolve(root)) ? 'nested' : 'parent';
    let found = false;
    for (const n of NAMES) {
      const before = out.length;
      await add(path.join(dir, n), scope);
      if (out.length > before) found = true;
    }
    if (!found) for (const n of COMPAT) await add(path.join(dir, n), scope);
    await add(path.join(dir, 'STELLA.local.md'), 'local');
  }
  return out;
}

async function expandImports(text: string, base: string, depth: number, seen: Set<string>): Promise<string> {
  if (depth >= 5) return text;
  const lines = text.split('\n');
  let inFence = false;
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i]!;
    if (/^\s*```/.test(l)) inFence = !inFence;
    if (inFence) continue;
    const m = /^\s*@([~./\w-][^\s]*)\s*$/.exec(l);
    if (!m) continue;
    let p = m[1]!;
    if (p.startsWith('~/')) p = path.join(os.homedir(), p.slice(2));
    const abs = path.resolve(base, p);
    if (seen.has(abs)) continue;
    try {
      const sub = await fs.readFile(abs, 'utf8');
      seen.add(abs);
      lines[i] = `<!-- imported from ${p} -->\n` + (await expandImports(sub, path.dirname(abs), depth + 1, seen));
    } catch {
      /* leave as-is */
    }
  }
  return lines.join('\n');
}

export function instructionsBlock(files: InstructionFile[]): string {
  if (!files.length) return '';
  return files.map((f) => `<instructions source="${f.path}" scope="${f.scope}">\n${f.content.trim()}\n</instructions>`).join('\n\n');
}

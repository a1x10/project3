import { promises as fs } from 'node:fs';
import path from 'node:path';
import type { Runtime } from '../agent/runtime.js';
import { resolvePath } from '../security/paths.js';
import { isBinaryBuffer } from '../utils/fsutil.js';
import type { ContentBlock } from '../types.js';

const MAX_FILE = 100_000;

/** Expand @path mentions into attached file contents (like pasting the file into the prompt). */
export async function expandMentions(prompt: string, rt: Runtime): Promise<{ blocks: ContentBlock[]; attached: string[]; skipped: string[] }> {
  const attached: string[] = [];
  const skipped: string[] = [];
  const blocks: ContentBlock[] = [{ type: 'text', text: prompt }];
  const re = /(^|\s)@("[^"]+"|[^\s,;:!?()]+)/g;
  const seen = new Set<string>();
  let m: RegExpExecArray | null;
  while ((m = re.exec(prompt)) && attached.length < 10) {
    const raw = m[2]!.replace(/^"|"$/g, '');
    if (seen.has(raw)) continue;
    seen.add(raw);
    let r;
    try {
      r = resolvePath(raw, { cwd: rt.cwd, roots: rt.roots, confidential: rt.settings.permissions?.confidential });
    } catch {
      continue;
    }
    if (!r.inWorkspace || r.isConfidential) {
      skipped.push(raw);
      continue;
    }
    const st = await fs.stat(r.real).catch(() => null);
    if (!st) continue;
    if (st.isDirectory()) {
      const entries = (await fs.readdir(r.real, { withFileTypes: true })).slice(0, 200).map((e) => (e.isDirectory() ? e.name + '/' : e.name));
      blocks.push({ type: 'text', text: `<directory path="${raw}">\n${entries.join('\n')}\n</directory>` });
      attached.push(raw + '/');
      continue;
    }
    const buf = await fs.readFile(r.real);
    if (isBinaryBuffer(buf)) {
      const ext = path.extname(r.real).toLowerCase();
      const img: Record<string, string> = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.webp': 'image/webp' };
      if (img[ext] && buf.length < 5_000_000) {
        blocks.push({ type: 'image', mediaType: img[ext]!, data: buf.toString('base64') });
        attached.push(raw);
      } else skipped.push(raw);
      continue;
    }
    const text = buf.toString('utf8');
    const lines = text.split('\n');
    const body = text.length > MAX_FILE ? text.slice(0, MAX_FILE) + `\n… [truncated: ${text.length - MAX_FILE} more chars; use Read with offset]` : text;
    blocks.push({ type: 'text', text: `<file path="${raw}" lines="${lines.length}">\n${body}\n</file>` });
    if (text.length <= MAX_FILE) rt.readState.mark(r.real, st);
    attached.push(raw);
  }
  return { blocks, attached, skipped };
}

/** Tab-completion for @paths. */
export async function completePath(partial: string, cwd: string): Promise<string[]> {
  const p = partial.replace(/^"/, '');
  const dir = p.endsWith('/') ? p : path.dirname(p) === '.' && !p.includes('/') ? '' : path.dirname(p) + '/';
  const base = p.slice(dir.length);
  const abs = path.resolve(cwd, dir || '.');
  try {
    const entries = await fs.readdir(abs, { withFileTypes: true });
    return entries
      .filter((e) => e.name.startsWith(base) && !['node_modules', '.git'].includes(e.name) && (base.startsWith('.') || !e.name.startsWith('.')))
      .slice(0, 50)
      .map((e) => dir + e.name + (e.isDirectory() ? '/' : ''))
      .sort();
  } catch {
    return [];
  }
}

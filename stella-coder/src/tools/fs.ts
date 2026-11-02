import { promises as fs } from 'node:fs';
import path from 'node:path';
import { z } from 'zod';
import type { PermissionDescriptor } from '../permissions/engine.js';
import { resolvePath, type ResolvedPath } from '../security/paths.js';
import { unifiedDiff } from '../utils/diff.js';
import { detectEol, isBinaryBuffer, writeFileAtomic } from '../utils/fsutil.js';
import { walk } from '../context/walk.js';
import { defineTool, ToolError, type ToolContext, type ToolResult } from './types.js';

const MAX_READ_LINES = 2000;
const MAX_LINE_LEN = 2000;
const MAX_READ_BYTES = 5 * 1024 * 1024;

export function rp(ctx: ToolContext, p: string): ResolvedPath {
  return resolvePath(p, { cwd: ctx.cwd, roots: ctx.roots, confidential: ctx.services.settings?.permissions?.confidential });
}

export function relDisplay(ctx: ToolContext, abs: string): string {
  const rel = path.relative(ctx.root, abs);
  return rel && !rel.startsWith('..') ? rel.split(path.sep).join('/') : abs;
}

function readDesc(ctx: ToolContext, p: string, verb = 'Read'): PermissionDescriptor {
  const r = rp(ctx, p);
  return { kind: 'read', risk: 'low', readOnly: true, summary: `${verb} ${relDisplay(ctx, r.abs)}`, paths: [r] };
}

function writeDesc(ctx: ToolContext, paths: string[], verb: string, risk: 'low' | 'medium' | 'high' = 'medium'): PermissionDescriptor {
  const rs = paths.map((p) => rp(ctx, p));
  return { kind: 'write', risk, readOnly: false, summary: `${verb} ${rs.map((r) => relDisplay(ctx, r.abs)).join(' → ')}`, paths: rs };
}

/** Shared guard for every mutation: lock ownership, read-before-write freshness, checkpoint. */
async function prepareWrite(ctx: ToolContext, abs: string, tool: string, requireRead: boolean): Promise<void> {
  const claim = ctx.services.locks.claim(abs, ctx.agentId);
  if (!claim.ok) throw new ToolError(`File ${relDisplay(ctx, abs)} is currently owned by agent "${claim.owner}". Coordinate through the main agent instead of editing it in parallel.`);
  let st: import('node:fs').Stats | null = null;
  try {
    st = await fs.stat(abs);
  } catch {
    st = null;
  }
  if (st && requireRead) {
    const seen = ctx.services.readState.get(abs);
    if (!seen) throw new ToolError(`You must Read ${relDisplay(ctx, abs)} before modifying it.`);
    if (Math.abs(seen.mtimeMs - st.mtimeMs) > 1 || seen.size !== st.size) {
      throw new ToolError(`${relDisplay(ctx, abs)} was modified since you last read it (possibly by the user or a linter). Read it again before editing.`);
    }
  }
  await ctx.services.checkpoints.recordBefore(ctx.turnId, abs, tool);
}

async function finishWrite(ctx: ToolContext, abs: string) {
  await ctx.services.checkpoints.recordAfter(ctx.turnId, abs);
  try {
    const st = await fs.stat(abs);
    ctx.services.readState.mark(abs, st);
  } catch {
    ctx.services.readState.forget(abs);
  }
  ctx.services.index?.invalidate?.(abs);
}

function quickValidate(abs: string, content: string): string {
  if (abs.endsWith('.json') && !abs.endsWith('tsconfig.json')) {
    try {
      JSON.parse(content);
    } catch (e) {
      return `\nWarning: ${path.basename(abs)} is not valid JSON after this change: ${(e as Error).message}`;
    }
  }
  return '';
}

export const ReadTool = defineTool({
  name: 'Read',
  description:
    'Read a file from the local filesystem. Returns lines prefixed with line numbers (cat -n format). By default reads up to 2000 lines; use offset/limit for large files. Read a file before editing it. Jupyter notebooks are rendered cell by cell.',
  kind: 'read',
  concurrencySafe: true,
  schema: z.object({
    file_path: z.string().describe('Absolute path, or path relative to the working directory'),
    offset: z.number().int().min(1).optional().describe('1-based line number to start from'),
    limit: z.number().int().min(1).optional().describe('Number of lines to read'),
  }),
  describe: (i, ctx) => readDesc(ctx, i.file_path),
  async run(i, ctx): Promise<ToolResult> {
    const r = rp(ctx, i.file_path);
    let st;
    try {
      st = await fs.stat(r.abs);
    } catch {
      throw new ToolError(`File not found: ${i.file_path}`);
    }
    if (st.isDirectory()) throw new ToolError(`${i.file_path} is a directory. Use DirectoryTree or Glob to list it.`);
    if (st.size > MAX_READ_BYTES && !i.offset && !i.limit) throw new ToolError(`File is ${(st.size / 1048576).toFixed(1)} MB. Use offset/limit or Grep to read parts of it.`);
    const buf = await fs.readFile(r.abs);
    if (isBinaryBuffer(buf)) return { content: `${relDisplay(ctx, r.abs)} is a binary file (${st.size} bytes); contents not shown.`, filesRead: [r.abs] };
    let text = buf.toString('utf8');
    if (r.abs.endsWith('.ipynb')) text = renderNotebook(text);
    const lines = text.split(/\r?\n/);
    if (lines.length && lines[lines.length - 1] === '') lines.pop();
    const start = (i.offset ?? 1) - 1;
    const count = i.limit ?? MAX_READ_LINES;
    const slice = lines.slice(start, start + count);
    ctx.services.readState.mark(r.abs, st);
    if (!lines.length) return { content: `<system-reminder>${relDisplay(ctx, r.abs)} exists but is empty.</system-reminder>`, filesRead: [r.abs] };
    const width = String(start + slice.length).length;
    const out = slice.map((l, k) => `${String(start + k + 1).padStart(Math.max(width, 5))}\t${l.length > MAX_LINE_LEN ? l.slice(0, MAX_LINE_LEN) + ' …[line truncated]' : l}`).join('\n');
    const more = start + slice.length < lines.length ? `\n… (${lines.length - start - slice.length} more lines; use offset=${start + slice.length + 1} to continue)` : '';
    return { content: out + more, filesRead: [r.abs], display: { kind: 'text', title: `Read ${slice.length} lines` } };
  },
});

function renderNotebook(json: string): string {
  try {
    const nb = JSON.parse(json);
    return (nb.cells ?? [])
      .map((c: any, idx: number) => {
        const src = Array.isArray(c.source) ? c.source.join('') : String(c.source ?? '');
        const outs = (c.outputs ?? [])
          .map((o: any) => (o.text ? (Array.isArray(o.text) ? o.text.join('') : o.text) : o.data?.['text/plain'] ? [].concat(o.data['text/plain']).join('') : ''))
          .filter(Boolean)
          .join('\n');
        return `<cell id="${idx}" type="${c.cell_type}">\n${src}\n${outs ? `<output>\n${outs}\n</output>\n` : ''}</cell>`;
      })
      .join('\n');
  } catch {
    return json;
  }
}

export const WriteTool = defineTool({
  name: 'Write',
  description: 'Create a new file or completely overwrite an existing one. Prefer Edit for changing existing files. Existing files must be Read first. Parent directories are created automatically.',
  kind: 'write',
  schema: z.object({
    file_path: z.string(),
    content: z.string().describe('Full file contents'),
  }),
  describe: (i, ctx) => writeDesc(ctx, [i.file_path], 'Write'),
  async run(i, ctx) {
    const r = rp(ctx, i.file_path);
    let before = '';
    let existed = true;
    try {
      before = await fs.readFile(r.real, 'utf8');
    } catch {
      existed = false;
    }
    await prepareWrite(ctx, r.real, 'Write', existed);
    await writeFileAtomic(r.real, i.content);
    await finishWrite(ctx, r.real);
    const d = unifiedDiff(before, i.content, relDisplay(ctx, r.real));
    const lines = i.content.split('\n').length;
    return {
      content: (existed ? `Updated ${relDisplay(ctx, r.real)} (+${d.added} -${d.removed})` : `Created ${relDisplay(ctx, r.real)} (${lines} lines)`) + quickValidate(r.real, i.content),
      filesChanged: [r.real],
      display: { kind: 'diff', title: `${existed ? 'Update' : 'Create'} ${relDisplay(ctx, r.real)}`, body: d.text, added: d.added, removed: d.removed },
    };
  },
});

export interface EditSpec {
  old_string: string;
  new_string: string;
  replace_all?: boolean;
}

/** Apply one exact-match edit. Handles CRLF files transparently. */
export function applyEdit(content: string, e: EditSpec, fileLabel: string): string {
  if (e.old_string === e.new_string) throw new ToolError('old_string and new_string are identical — nothing to change.');
  const eol = detectEol(content);
  let oldS = e.old_string;
  let newS = e.new_string;
  if (eol === '\r\n' && !content.includes(oldS) && oldS.includes('\n')) {
    oldS = oldS.replace(/\r?\n/g, '\r\n');
    newS = newS.replace(/\r?\n/g, '\r\n');
  }
  if (oldS === '') {
    if (content.length) throw new ToolError('old_string is empty but the file is not; provide the text to replace.');
    return newS;
  }
  const count = content.split(oldS).length - 1;
  if (count === 0) {
    const hint = nearestLine(content, e.old_string);
    throw new ToolError(`old_string not found in ${fileLabel}. It must match exactly, including whitespace and indentation.${hint ? `\nClosest line: ${hint}` : ''}`);
  }
  if (count > 1 && !e.replace_all) throw new ToolError(`old_string occurs ${count} times in ${fileLabel}. Add surrounding context to make it unique, or set replace_all.`);
  return e.replace_all ? content.split(oldS).join(newS) : content.replace(oldS, () => newS);
}

function nearestLine(content: string, needle: string): string | null {
  const first = needle.split(/\r?\n/).find((l) => l.trim())?.trim();
  if (!first) return null;
  const lines = content.split(/\r?\n/);
  const idx = lines.findIndex((l) => l.trim() === first);
  if (idx >= 0) return `${idx + 1}: ${lines[idx]}`;
  const loose = lines.findIndex((l) => l.includes(first.slice(0, Math.min(30, first.length))));
  return loose >= 0 ? `${loose + 1}: ${lines[loose]}` : null;
}

async function editFile(ctx: ToolContext, filePath: string, edits: EditSpec[], tool: string): Promise<ToolResult> {
  const r = rp(ctx, filePath);
  let before: string;
  try {
    before = await fs.readFile(r.real, 'utf8');
  } catch {
    if (edits.length && edits[0]!.old_string === '') {
      before = '';
    } else throw new ToolError(`File not found: ${filePath}`);
  }
  const exists = before !== '' || (await fs.stat(r.real).then(() => true, () => false));
  await prepareWrite(ctx, r.real, tool, exists);
  let after = before;
  edits.forEach((e, k) => {
    try {
      after = applyEdit(after, e, relDisplay(ctx, r.real));
    } catch (err) {
      throw new ToolError(edits.length > 1 ? `Edit #${k + 1} failed (no changes were written): ${(err as Error).message}` : (err as Error).message);
    }
  });
  await writeFileAtomic(r.real, after);
  await finishWrite(ctx, r.real);
  const d = unifiedDiff(before, after, relDisplay(ctx, r.real));
  return {
    content: `Edited ${relDisplay(ctx, r.real)}: ${edits.length} change(s), +${d.added} -${d.removed} lines.` + quickValidate(r.real, after),
    filesChanged: [r.real],
    display: { kind: 'diff', title: `Update ${relDisplay(ctx, r.real)}`, body: d.text, added: d.added, removed: d.removed },
  };
}

export const EditTool = defineTool({
  name: 'Edit',
  description:
    'Replace an exact string in a file. old_string must match the file exactly (whitespace included) and be unique unless replace_all is true. Read the file first. Use an empty old_string only to create a new empty-file content.',
  kind: 'write',
  schema: z.object({
    file_path: z.string(),
    old_string: z.string(),
    new_string: z.string(),
    replace_all: z.boolean().optional(),
  }),
  describe: (i, ctx) => writeDesc(ctx, [i.file_path], 'Edit'),
  run: (i, ctx) => editFile(ctx, i.file_path, [i], 'Edit'),
});

export const MultiEditTool = defineTool({
  name: 'MultiEdit',
  description: 'Apply several exact-string edits to one file atomically, in order. If any edit fails, nothing is written.',
  kind: 'write',
  schema: z.object({
    file_path: z.string(),
    edits: z.array(z.object({ old_string: z.string(), new_string: z.string(), replace_all: z.boolean().optional() })).min(1),
  }),
  describe: (i, ctx) => writeDesc(ctx, [i.file_path], `MultiEdit (${i.edits.length})`),
  run: (i, ctx) => editFile(ctx, i.file_path, i.edits, 'MultiEdit'),
});

export const DeleteTool = defineTool({
  name: 'Delete',
  description: 'Delete a file, or a directory when recursive=true. Every deleted file is checkpointed and can be restored with /rewind.',
  kind: 'write',
  schema: z.object({ path: z.string(), recursive: z.boolean().optional() }),
  describe: (i, ctx) => writeDesc(ctx, [i.path], i.recursive ? 'Delete directory' : 'Delete', 'high'),
  async run(i, ctx) {
    const r = rp(ctx, i.path);
    if (ctx.roots.some((root) => path.resolve(root) === r.real)) throw new ToolError('Refusing to delete a workspace root.');
    const st = await fs.stat(r.real).catch(() => null);
    if (!st) throw new ToolError(`Not found: ${i.path}`);
    const files: string[] = [];
    if (st.isDirectory()) {
      if (!i.recursive) throw new ToolError(`${i.path} is a directory; set recursive=true to delete it.`);
      for await (const e of walk(r.real, { maxFiles: 5001 })) files.push(e.abs);
      if (files.length > 5000) throw new ToolError('Directory has more than 5000 files; refusing bulk delete. Use a shell command with explicit confirmation.');
    } else files.push(r.real);
    for (const f of files) {
      const c = ctx.services.locks.claim(f, ctx.agentId);
      if (!c.ok) throw new ToolError(`${relDisplay(ctx, f)} is owned by agent "${c.owner}".`);
      await ctx.services.checkpoints.recordBefore(ctx.turnId, f, 'Delete');
    }
    await fs.rm(r.real, { recursive: !!i.recursive, force: false });
    for (const f of files) await finishWrite(ctx, f);
    return { content: `Deleted ${relDisplay(ctx, r.real)}${files.length > 1 ? ` (${files.length} files)` : ''}`, filesChanged: files, display: { kind: 'text', title: `Deleted ${relDisplay(ctx, r.real)}` } };
  },
});

async function transfer(ctx: ToolContext, src: string, dst: string, overwrite: boolean | undefined, move: boolean): Promise<ToolResult> {
  const s = rp(ctx, src);
  const d = rp(ctx, dst);
  const sst = await fs.stat(s.real).catch(() => null);
  if (!sst) throw new ToolError(`Source not found: ${src}`);
  if (sst.isDirectory()) throw new ToolError('Directory move/copy is not supported by this tool; use a shell command.');
  let target = d.real;
  const dstSt = await fs.stat(target).catch(() => null);
  if (dstSt?.isDirectory()) target = path.join(target, path.basename(s.real));
  else if (dstSt && !overwrite) throw new ToolError(`Destination exists: ${dst}. Set overwrite=true to replace it.`);
  for (const f of move ? [s.real, target] : [target]) {
    const c = ctx.services.locks.claim(f, ctx.agentId);
    if (!c.ok) throw new ToolError(`${relDisplay(ctx, f)} is owned by agent "${c.owner}".`);
    await ctx.services.checkpoints.recordBefore(ctx.turnId, f, move ? 'Move' : 'Copy');
  }
  await fs.mkdir(path.dirname(target), { recursive: true });
  if (move) {
    try {
      await fs.rename(s.real, target);
    } catch (e) {
      if ((e as NodeJS.ErrnoException).code !== 'EXDEV') throw e;
      await fs.copyFile(s.real, target);
      await fs.rm(s.real);
    }
    await finishWrite(ctx, s.real);
  } else await fs.copyFile(s.real, target);
  await finishWrite(ctx, target);
  return { content: `${move ? 'Moved' : 'Copied'} ${relDisplay(ctx, s.real)} → ${relDisplay(ctx, target)}`, filesChanged: move ? [s.real, target] : [target] };
}

export const MoveTool = defineTool({
  name: 'Move',
  description: 'Move or rename a file. Fails if the destination exists unless overwrite=true.',
  kind: 'write',
  schema: z.object({ source: z.string(), destination: z.string(), overwrite: z.boolean().optional() }),
  describe: (i, ctx) => writeDesc(ctx, [i.source, i.destination], 'Move', 'medium'),
  run: (i, ctx) => transfer(ctx, i.source, i.destination, i.overwrite, true),
});

export const CopyTool = defineTool({
  name: 'Copy',
  description: 'Copy a file. Fails if the destination exists unless overwrite=true.',
  kind: 'write',
  schema: z.object({ source: z.string(), destination: z.string(), overwrite: z.boolean().optional() }),
  describe: (i, ctx) => ({ ...writeDesc(ctx, [i.destination], 'Copy to', 'low'), paths: [rp(ctx, i.source), rp(ctx, i.destination)] }),
  run: (i, ctx) => transfer(ctx, i.source, i.destination, i.overwrite, false),
});

export const FileInfoTool = defineTool({
  name: 'FileInfo',
  description: 'Get metadata for a file or directory: type, size, line count, modification time, permissions, symlink target.',
  kind: 'read',
  concurrencySafe: true,
  schema: z.object({ path: z.string() }),
  describe: (i, ctx) => readDesc(ctx, i.path, 'Inspect'),
  async run(i, ctx) {
    const r = rp(ctx, i.path);
    const lst = await fs.lstat(r.abs).catch(() => null);
    if (!lst) throw new ToolError(`Not found: ${i.path}`);
    const st = await fs.stat(r.abs).catch(() => lst);
    const info: Record<string, unknown> = {
      path: relDisplay(ctx, r.abs),
      type: lst.isSymbolicLink() ? 'symlink' : st.isDirectory() ? 'directory' : 'file',
      size: st.size,
      modified: new Date(st.mtimeMs).toISOString(),
      mode: '0' + (st.mode & 0o777).toString(8),
      inWorkspace: r.inWorkspace,
    };
    if (lst.isSymbolicLink()) info.target = await fs.readlink(r.abs);
    if (st.isFile() && st.size < MAX_READ_BYTES) {
      const buf = await fs.readFile(r.abs);
      info.binary = isBinaryBuffer(buf);
      if (!info.binary) {
        const t = buf.toString('utf8');
        info.lines = t.split('\n').length;
        info.eol = detectEol(t) === '\r\n' ? 'CRLF' : 'LF';
      }
    }
    if (st.isDirectory()) info.entries = (await fs.readdir(r.abs)).length;
    return { content: JSON.stringify(info, null, 2) };
  },
});

export const DirectoryTreeTool = defineTool({
  name: 'DirectoryTree',
  description: 'Show the directory tree (respects .gitignore and default ignores such as node_modules, .git, dist).',
  kind: 'read',
  concurrencySafe: true,
  schema: z.object({
    path: z.string().optional().describe('Directory (default: working directory)'),
    depth: z.number().int().min(1).max(10).optional().describe('Max depth (default 3)'),
    max_entries: z.number().int().min(10).max(5000).optional(),
  }),
  describe: (i, ctx) => readDesc(ctx, i.path ?? '.', 'List'),
  async run(i, ctx) {
    const r = rp(ctx, i.path ?? '.');
    const max = i.max_entries ?? 400;
    const entries: { rel: string; isDir: boolean }[] = [];
    for await (const e of walk(r.real, { ignore: ctx.services.ignore, maxDepth: i.depth ?? 3, includeDirs: true, maxFiles: max, signal: ctx.signal })) {
      entries.push(e);
      if (entries.length >= max) break;
    }
    entries.sort((a, b) => a.rel.localeCompare(b.rel));
    const lines = [relDisplay(ctx, r.real) + '/'];
    for (const e of entries) {
      const depth = e.rel.split('/').length - 1;
      lines.push(`${'  '.repeat(depth)}${e.isDir ? '▸ ' : '  '}${e.rel.split('/').pop()}${e.isDir ? '/' : ''}`);
    }
    if (entries.length >= max) lines.push(`… truncated at ${max} entries`);
    return { content: lines.join('\n') };
  },
});

export const fsTools = [ReadTool, WriteTool, EditTool, MultiEditTool, DeleteTool, MoveTool, CopyTool, FileInfoTool, DirectoryTreeTool];

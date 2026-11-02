import { spawn } from 'node:child_process';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import picomatch from 'picomatch';
import { z } from 'zod';
import { walk } from '../context/walk.js';
import { isBinaryBuffer } from '../utils/fsutil.js';
import { which } from '../utils/which.js';
import { relDisplay, rp } from './fs.js';
import { defineTool, ToolError, type ToolContext } from './types.js';

const readDesc = (ctx: ToolContext, p: string | undefined, what: string) => {
  const r = rp(ctx, p ?? '.');
  return { kind: 'read' as const, risk: 'low' as const, readOnly: true, summary: `${what} in ${relDisplay(ctx, r.abs)}`, paths: [r] };
};

export const GlobTool = defineTool({
  name: 'Glob',
  description: 'Find files by glob pattern (e.g. "**/*.ts", "src/**/test_*.py"). Results are sorted by modification time, newest first. Respects .gitignore and default ignores.',
  kind: 'read',
  concurrencySafe: true,
  schema: z.object({
    pattern: z.string(),
    path: z.string().optional().describe('Directory to search (default: working directory)'),
    limit: z.number().int().min(1).max(5000).optional(),
  }),
  describe: (i, ctx) => readDesc(ctx, i.path, `Glob ${i.pattern}`),
  async run(i, ctx) {
    const base = rp(ctx, i.path ?? '.').real;
    const match = picomatch(i.pattern, { dot: true, nocase: process.platform === 'win32' });
    const matchBase = !i.pattern.includes('/') ? picomatch(i.pattern, { dot: true, basename: true }) : null;
    const hits: { rel: string; abs: string; mtimeMs: number }[] = [];
    for await (const e of walk(base, { ignore: ctx.services.ignore, stat: true, signal: ctx.signal })) {
      if (match(e.rel) || matchBase?.(e.rel)) hits.push({ rel: e.rel, abs: e.abs, mtimeMs: e.mtimeMs ?? 0 });
    }
    hits.sort((a, b) => b.mtimeMs - a.mtimeMs);
    const limit = i.limit ?? 200;
    const shown = hits.slice(0, limit).map((h) => relDisplay(ctx, h.abs));
    if (!shown.length) return { content: 'No files found.' };
    return { content: shown.join('\n') + (hits.length > limit ? `\n… ${hits.length - limit} more (narrow the pattern)` : ''), display: { kind: 'files', title: `${hits.length} files` } };
  },
});

const GrepSchema = z.object({
  pattern: z.string().describe('Regular expression (Rust/JS regex syntax)'),
  path: z.string().optional().describe('File or directory (default: working directory)'),
  glob: z.string().optional().describe('Filter files by glob, e.g. "*.ts" or "src/**/*.py"'),
  output_mode: z.enum(['content', 'files_with_matches', 'count']).optional().describe('Default files_with_matches'),
  case_insensitive: z.boolean().optional(),
  context: z.number().int().min(0).max(20).optional().describe('Lines of context around matches (content mode)'),
  multiline: z.boolean().optional(),
  head_limit: z.number().int().min(1).optional().describe('Limit output lines/entries (default 250)'),
});
type GrepInput = z.infer<typeof GrepSchema>;

export const GrepTool = defineTool({
  name: 'Grep',
  description: 'Search file contents with a regular expression (ripgrep when available, built-in engine otherwise). Modes: files_with_matches (default), content (matching lines with line numbers), count.',
  kind: 'read',
  concurrencySafe: true,
  schema: GrepSchema,
  describe: (i, ctx) => readDesc(ctx, i.path, `Grep "${i.pattern}"`),
  async run(i, ctx) {
    const target = rp(ctx, i.path ?? '.').real;
    const limit = i.head_limit ?? 250;
    const rg = which('rg');
    const out = rg && !process.env.STELLA_NO_RG ? await ripgrep(rg, i, target, ctx) : await jsGrep(i, target, ctx);
    const lines = out.split('\n').filter(Boolean);
    if (!lines.length) return { content: 'No matches found.' };
    const rel = lines.map((l) => relativize(l, ctx));
    return { content: rel.slice(0, limit).join('\n') + (rel.length > limit ? `\n… ${rel.length - limit} more (use head_limit or narrow the search)` : '') };
  },
});

function relativize(line: string, ctx: ToolContext): string {
  const root = ctx.root + path.sep;
  return line.startsWith(root) ? line.slice(root.length).split(path.sep).join('/') : line;
}

function ripgrep(rg: string, i: GrepInput, target: string, ctx: ToolContext): Promise<string> {
  const args = ['--color', 'never', '--no-messages'];
  const mode = i.output_mode ?? 'files_with_matches';
  if (mode === 'files_with_matches') args.push('-l');
  else if (mode === 'count') args.push('-c');
  else args.push('-n', '--no-heading', '--max-columns', '400');
  if (i.case_insensitive) args.push('-i');
  if (i.multiline) args.push('-U', '--multiline-dotall');
  if (i.context && mode === 'content') args.push('-C', String(i.context));
  if (i.glob) args.push('--glob', i.glob);
  for (const g of ['!node_modules', '!.git', '!dist', '!build', '!.venv', '!venv', '!__pycache__', '!coverage', '!.next']) args.push('--glob', g);
  args.push('--', i.pattern, target);
  return new Promise((resolve, reject) => {
    const p = spawn(rg, args, { cwd: ctx.cwd, signal: ctx.signal, windowsHide: true });
    let out = '';
    let err = '';
    p.stdout.on('data', (d) => {
      if (out.length < 4_000_000) out += d;
    });
    p.stderr.on('data', (d) => (err += d));
    p.on('error', reject);
    p.on('close', (code) => {
      if (code === 2 && !out) reject(new ToolError(`grep failed: ${err.trim() || 'invalid pattern'}`));
      else resolve(out);
    });
  });
}

async function jsGrep(i: GrepInput, target: string, ctx: ToolContext): Promise<string> {
  let re: RegExp;
  try {
    re = new RegExp(i.pattern, (i.case_insensitive ? 'i' : '') + (i.multiline ? 'ms' : '') + 'g');
  } catch (e) {
    throw new ToolError(`Invalid regex: ${(e as Error).message}`);
  }
  const globM = i.glob ? picomatch(i.glob, { dot: true, basename: !i.glob.includes('/') }) : null;
  const mode = i.output_mode ?? 'files_with_matches';
  const out: string[] = [];
  const st = await fs.stat(target);
  const files: string[] = [];
  if (st.isFile()) files.push(target);
  else for await (const e of walk(target, { ignore: ctx.services.ignore, signal: ctx.signal })) if (!globM || globM(e.rel)) files.push(e.abs);
  for (const f of files) {
    let buf: Buffer;
    try {
      buf = await fs.readFile(f);
    } catch {
      continue;
    }
    if (buf.length > 5_000_000 || isBinaryBuffer(buf)) continue;
    const text = buf.toString('utf8');
    re.lastIndex = 0;
    if (mode === 'files_with_matches') {
      if (re.test(text)) out.push(f);
      continue;
    }
    const lines = text.split(/\r?\n/);
    if (mode === 'count') {
      const n = lines.filter((l) => {
        re.lastIndex = 0;
        return re.test(l);
      }).length;
      if (n) out.push(`${f}:${n}`);
      continue;
    }
    const c = i.context ?? 0;
    const emit = new Set<number>();
    lines.forEach((l, k) => {
      re.lastIndex = 0;
      if (re.test(l)) for (let j = Math.max(0, k - c); j <= Math.min(lines.length - 1, k + c); j++) emit.add(j);
    });
    for (const k of [...emit].sort((a, b) => a - b)) out.push(`${f}:${k + 1}:${lines[k]!.slice(0, 400)}`);
    if (out.length > 20000) break;
  }
  return out.join('\n');
}

export const SymbolSearchTool = defineTool({
  name: 'SymbolSearch',
  description: 'Find definitions of functions, classes, methods, types, interfaces and variables by name across the project (uses the project index; supports prefix/substring/fuzzy matching).',
  kind: 'read',
  concurrencySafe: true,
  schema: z.object({
    query: z.string(),
    kind: z.enum(['function', 'class', 'interface', 'type', 'enum', 'variable', 'method', 'struct', 'trait', 'module']).optional(),
    exact: z.boolean().optional(),
    limit: z.number().int().min(1).max(500).optional(),
  }),
  describe: (i) => ({ kind: 'read', risk: 'low', readOnly: true, summary: `SymbolSearch ${i.query}` }),
  async run(i, ctx) {
    await ctx.services.index.ensure(ctx.signal);
    const hits = ctx.services.index.findSymbols(i.query, { kind: i.kind, exact: i.exact, limit: i.limit ?? 50 });
    if (!hits.length) return { content: `No symbols matching "${i.query}".` };
    return { content: hits.map((h: any) => `${h.file}:${h.line}  ${h.kind} ${h.name}${h.exported ? ' (exported)' : ''}`).join('\n') };
  },
});

export const ReferenceSearchTool = defineTool({
  name: 'ReferenceSearch',
  description: 'Find all usages of a symbol (whole-word matches), separating its definitions from references.',
  kind: 'read',
  concurrencySafe: true,
  schema: z.object({ symbol: z.string().regex(/^[\w$.]+$/, 'identifier expected'), glob: z.string().optional(), limit: z.number().int().optional() }),
  describe: (i) => ({ kind: 'read', risk: 'low', readOnly: true, summary: `ReferenceSearch ${i.symbol}` }),
  async run(i, ctx) {
    await ctx.services.index.ensure(ctx.signal);
    const defs = ctx.services.index.findSymbols(i.symbol, { exact: true, limit: 50 }) as Array<{ file: string; line: number; kind: string }>;
    const defKeys = new Set(defs.map((d) => `${d.file}:${d.line}`));
    const pattern = `(^|[^\\w$])${i.symbol.replace(/[.$]/g, '\\$&')}([^\\w$]|$)`;
    const res = await GrepTool.run({ pattern, glob: i.glob, output_mode: 'content', head_limit: i.limit ?? 300 }, ctx);
    const refs = res.content.split('\n').filter((l) => /^[^:]+:\d+:/.test(l) && !defKeys.has(l.split(':').slice(0, 2).join(':')));
    const lines = [`Definitions (${defs.length}):`, ...defs.map((d) => `  ${d.file}:${d.line} ${d.kind}`), `References (${refs.length}):`, ...refs.map((r) => '  ' + r)];
    return { content: lines.join('\n') };
  },
});

export const SemanticSearchTool = defineTool({
  name: 'SemanticSearch',
  description:
    'Ranked natural-language search over the codebase ("where is authentication handled", "retry logic for http"). Uses a local BM25 index over code chunks with identifier splitting and symbol boosting; returns the most relevant file regions. Use Grep for exact patterns.',
  kind: 'read',
  concurrencySafe: true,
  schema: z.object({ query: z.string(), limit: z.number().int().min(1).max(50).optional() }),
  describe: (i) => ({ kind: 'read', risk: 'low', readOnly: true, summary: `SemanticSearch "${i.query}"` }),
  async run(i, ctx) {
    const hits = await ctx.services.index.search(i.query, i.limit ?? 8);
    if (!hits.length) return { content: 'No relevant code found.' };
    return { content: hits.map((h: any) => `## ${h.file} (lines ${h.startLine}-${h.endLine}, score ${h.score})\n${h.preview}`).join('\n\n') };
  },
});

export const DependencySearchTool = defineTool({
  name: 'DependencySearch',
  description: 'Analyze dependencies: for a file, list what it imports and which files import it; for a package name, show where it is declared and which files use it.',
  kind: 'read',
  concurrencySafe: true,
  schema: z.object({ file: z.string().optional(), package: z.string().optional() }),
  describe: (i) => ({ kind: 'read', risk: 'low', readOnly: true, summary: `DependencySearch ${i.file ?? i.package ?? ''}` }),
  async run(i, ctx) {
    const idx = ctx.services.index;
    await idx.ensure(ctx.signal);
    if (!i.file && !i.package) throw new ToolError('Provide file or package.');
    const out: string[] = [];
    if (i.file) {
      const rel = relDisplay(ctx, rp(ctx, i.file).real);
      const rec = idx.get(rel);
      out.push(`Imports of ${rel}:`, ...(rec?.imports.length ? rec.imports.map((x: string) => '  ' + x) : ['  (none found)']));
      const importers = idx.importersOf(rel);
      out.push(`Imported by (${importers.length}):`, ...importers.map((x: string) => '  ' + x));
    }
    if (i.package) {
      const users = idx.list().filter((f: any) => f.imports.some((x: string) => x === i.package || x.startsWith(i.package + '/') || x.startsWith(i.package + '.')));
      out.push(`Files importing ${i.package} (${users.length}):`, ...users.slice(0, 200).map((f: any) => '  ' + f.rel));
      for (const m of ['package.json', 'requirements.txt', 'pyproject.toml', 'go.mod', 'Cargo.toml']) {
        const text = await fs.readFile(path.join(ctx.root, m), 'utf8').catch(() => '');
        const line = text.split('\n').find((l) => l.includes(i.package!));
        if (line) out.push(`Declared in ${m}: ${line.trim()}`);
      }
    }
    return { content: out.join('\n') };
  },
});

export const searchTools = [GlobTool, GrepTool, SymbolSearchTool, ReferenceSearchTool, SemanticSearchTool, DependencySearchTool];

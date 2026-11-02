import { promises as fs } from 'node:fs';
import path from 'node:path';
import { readJson, writeJson } from '../utils/fsutil.js';
import { Semaphore } from '../utils/async.js';
import type { IgnoreMatcher } from './ignore.js';
import { walk } from './walk.js';

export type SymbolKind = 'function' | 'class' | 'interface' | 'type' | 'enum' | 'variable' | 'method' | 'struct' | 'trait' | 'module';

export interface SymbolDef {
  name: string;
  kind: SymbolKind;
  line: number;
  exported?: boolean;
}

export interface FileRecord {
  rel: string;
  lang: string;
  size: number;
  mtimeMs: number;
  symbols: SymbolDef[];
  imports: string[];
  lines: number;
}

const LANG_BY_EXT: Record<string, string> = {
  '.ts': 'typescript', '.tsx': 'typescript', '.mts': 'typescript', '.cts': 'typescript',
  '.js': 'javascript', '.jsx': 'javascript', '.mjs': 'javascript', '.cjs': 'javascript',
  '.py': 'python', '.pyi': 'python', '.go': 'go', '.rs': 'rust', '.java': 'java', '.kt': 'kotlin', '.kts': 'kotlin',
  '.cs': 'csharp', '.rb': 'ruby', '.php': 'php', '.swift': 'swift', '.c': 'c', '.h': 'c', '.cpp': 'cpp', '.cc': 'cpp',
  '.hpp': 'cpp', '.scala': 'scala', '.lua': 'lua', '.dart': 'dart', '.vue': 'vue', '.svelte': 'svelte',
  '.html': 'html', '.css': 'css', '.scss': 'scss', '.sql': 'sql', '.sh': 'shell', '.bash': 'shell', '.ps1': 'powershell',
  '.md': 'markdown', '.json': 'json', '.yaml': 'yaml', '.yml': 'yaml', '.toml': 'toml', '.xml': 'xml',
};

export function languageOf(file: string): string {
  return LANG_BY_EXT[path.extname(file).toLowerCase()] ?? 'other';
}

const CODE_LANGS = new Set(['typescript', 'javascript', 'python', 'go', 'rust', 'java', 'kotlin', 'csharp', 'ruby', 'php', 'swift', 'c', 'cpp', 'scala', 'lua', 'dart', 'vue', 'svelte', 'shell', 'powershell']);

type Pattern = [RegExp, SymbolKind, number?];
const SYMBOL_PATTERNS: Record<string, Pattern[]> = {
  typescript: [
    [/^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)/, 'function'],
    [/^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)/, 'class'],
    [/^\s*(?:export\s+)?interface\s+([A-Za-z_$][\w$]*)/, 'interface'],
    [/^\s*(?:export\s+)?type\s+([A-Za-z_$][\w$]*)\s*(?:<[^=]*>)?\s*=/, 'type'],
    [/^\s*(?:export\s+)?(?:const\s+)?enum\s+([A-Za-z_$][\w$]*)/, 'enum'],
    [/^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*(?::[^=]+)?=>/, 'function'],
    [/^\s*(?:export\s+)(?:const|let|var)\s+([A-Za-z_$][\w$]*)/, 'variable'],
    [/^\s+(?:public\s+|private\s+|protected\s+|static\s+|readonly\s+|async\s+|override\s+)*(?!if\b|for\b|while\b|switch\b|catch\b|return\b|function\b|constructor\b)([A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\([^)]*\)\s*(?::\s*[^{]+)?\{\s*$/, 'method'],
  ],
  python: [
    [/^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)/, 'function'],
    [/^\s*class\s+([A-Za-z_]\w*)/, 'class'],
    [/^([A-Z_][A-Z0-9_]*)\s*(?::[^=]+)?=/, 'variable'],
  ],
  go: [
    [/^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)/, 'function'],
    [/^type\s+([A-Za-z_]\w*)\s+struct/, 'struct'],
    [/^type\s+([A-Za-z_]\w*)\s+interface/, 'interface'],
    [/^type\s+([A-Za-z_]\w*)\s+/, 'type'],
  ],
  rust: [
    [/^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+([A-Za-z_]\w*)/, 'function'],
    [/^\s*(?:pub(?:\([^)]*\))?\s+)?struct\s+([A-Za-z_]\w*)/, 'struct'],
    [/^\s*(?:pub(?:\([^)]*\))?\s+)?enum\s+([A-Za-z_]\w*)/, 'enum'],
    [/^\s*(?:pub(?:\([^)]*\))?\s+)?trait\s+([A-Za-z_]\w*)/, 'trait'],
    [/^\s*(?:pub(?:\([^)]*\))?\s+)?mod\s+([A-Za-z_]\w*)/, 'module'],
    [/^\s*(?:pub(?:\([^)]*\))?\s+)?type\s+([A-Za-z_]\w*)/, 'type'],
  ],
  java: [
    [/^\s*(?:(?:public|private|protected|static|final|abstract|sealed)\s+)*(?:class|record)\s+([A-Za-z_]\w*)/, 'class'],
    [/^\s*(?:(?:public|private|protected|static)\s+)*interface\s+([A-Za-z_]\w*)/, 'interface'],
    [/^\s*(?:(?:public|private|protected|static)\s+)*enum\s+([A-Za-z_]\w*)/, 'enum'],
    [/^\s*(?:(?:public|private|protected|static|final|abstract|synchronized)\s+)+[\w<>\[\],.? ]+\s+([A-Za-z_]\w*)\s*\(/, 'method'],
  ],
  ruby: [
    [/^\s*def\s+(?:self\.)?([A-Za-z_]\w*[?!]?)/, 'function'],
    [/^\s*class\s+([A-Z]\w*)/, 'class'],
    [/^\s*module\s+([A-Z]\w*)/, 'module'],
  ],
  php: [
    [/^\s*(?:(?:public|private|protected|static|abstract|final)\s+)*function\s+([A-Za-z_]\w*)/, 'function'],
    [/^\s*(?:abstract\s+|final\s+)?class\s+([A-Za-z_]\w*)/, 'class'],
    [/^\s*interface\s+([A-Za-z_]\w*)/, 'interface'],
    [/^\s*trait\s+([A-Za-z_]\w*)/, 'trait'],
  ],
  c: [
    [/^(?!\s*(?:if|for|while|switch|return)\b)[A-Za-z_][\w\s\*]*?\b([A-Za-z_]\w*)\s*\([^;{]*\)\s*\{?\s*$/, 'function'],
    [/^\s*(?:typedef\s+)?struct\s+([A-Za-z_]\w*)/, 'struct'],
    [/^\s*class\s+([A-Za-z_]\w*)/, 'class'],
  ],
  swift: [
    [/^\s*(?:public\s+|private\s+|internal\s+|static\s+)*func\s+([A-Za-z_]\w*)/, 'function'],
    [/^\s*(?:public\s+|final\s+)*(?:class|struct|enum|protocol|actor)\s+([A-Za-z_]\w*)/, 'class'],
  ],
};
SYMBOL_PATTERNS.javascript = SYMBOL_PATTERNS.typescript!.filter(([, k]) => k !== 'interface' && k !== 'type' && k !== 'enum');
SYMBOL_PATTERNS.vue = SYMBOL_PATTERNS.javascript;
SYMBOL_PATTERNS.svelte = SYMBOL_PATTERNS.javascript;
SYMBOL_PATTERNS.kotlin = [
  [/^\s*(?:(?:public|private|internal|open|data|sealed|abstract)\s+)*class\s+([A-Za-z_]\w*)/, 'class'],
  [/^\s*(?:(?:public|private|internal|override|suspend)\s+)*fun\s+(?:<[^>]*>\s*)?(?:[\w.]+\.)?([A-Za-z_]\w*)/, 'function'],
  [/^\s*(?:(?:public|private)\s+)*(?:interface|object)\s+([A-Za-z_]\w*)/, 'interface'],
];
SYMBOL_PATTERNS.csharp = SYMBOL_PATTERNS.java;
SYMBOL_PATTERNS.scala = SYMBOL_PATTERNS.kotlin;
SYMBOL_PATTERNS.cpp = SYMBOL_PATTERNS.c;

const IMPORT_PATTERNS: Record<string, RegExp[]> = {
  typescript: [/\bimport\s+(?:[\s\S]*?\s+from\s+)?['"]([^'"]+)['"]/g, /\brequire\(\s*['"]([^'"]+)['"]\s*\)/g, /\bimport\(\s*['"]([^'"]+)['"]\s*\)/g, /\bexport\s+[\s\S]*?\s+from\s+['"]([^'"]+)['"]/g],
  python: [/^\s*from\s+([.\w]+)\s+import/gm, /^\s*import\s+([.\w]+)/gm],
  go: [/^\s*import\s+"([^"]+)"/gm, /^\s+"([^"]+)"$/gm],
  rust: [/^\s*use\s+([\w:]+)/gm, /^\s*(?:pub\s+)?mod\s+(\w+);/gm],
  java: [/^\s*import\s+(?:static\s+)?([\w.]+)/gm],
  ruby: [/^\s*require(?:_relative)?\s+['"]([^'"]+)['"]/gm],
  php: [/^\s*use\s+([\w\\]+)/gm, /\b(?:require|include)(?:_once)?\s*\(?\s*['"]([^'"]+)['"]/g],
  c: [/^\s*#include\s+[<"]([^>"]+)[>"]/gm],
};
IMPORT_PATTERNS.javascript = IMPORT_PATTERNS.typescript!;
IMPORT_PATTERNS.vue = IMPORT_PATTERNS.typescript!;
IMPORT_PATTERNS.svelte = IMPORT_PATTERNS.typescript!;
IMPORT_PATTERNS.kotlin = IMPORT_PATTERNS.java!;
IMPORT_PATTERNS.scala = IMPORT_PATTERNS.java!;
IMPORT_PATTERNS.csharp = [/^\s*using\s+([\w.]+)\s*;/gm];
IMPORT_PATTERNS.cpp = IMPORT_PATTERNS.c!;

export function extractSymbols(text: string, lang: string): SymbolDef[] {
  const pats = SYMBOL_PATTERNS[lang];
  if (!pats) return [];
  const out: SymbolDef[] = [];
  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length && out.length < 2000; i++) {
    const line = lines[i]!;
    if (line.length > 400) continue;
    for (const [re, kind] of pats) {
      const m = re.exec(line);
      if (m && m[1]) {
        out.push({ name: m[1], kind, line: i + 1, exported: /^\s*(export|pub\b|public\b)/.test(line) || undefined });
        break;
      }
    }
  }
  return out;
}

export function extractImports(text: string, lang: string): string[] {
  const pats = IMPORT_PATTERNS[lang];
  if (!pats) return [];
  const set = new Set<string>();
  for (const re of pats) {
    re.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = re.exec(text)) && set.size < 500) if (m[1]) set.add(m[1]);
  }
  return [...set];
}

/** Split identifiers into searchable terms: getUserName → get, user, name, getusername. */
export function tokenize(text: string): string[] {
  const out: string[] = [];
  const words = text.match(/[A-Za-z_][A-Za-z0-9_]*|[Ѐ-ӿ]+|\d+/g) ?? [];
  for (const w of words) {
    const lower = w.toLowerCase();
    if (lower.length < 2 || STOP.has(lower)) continue;
    out.push(stem(lower));
    const parts = w.split(/_|(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])/).filter((p) => p.length > 1);
    if (parts.length > 1) for (const p of parts) out.push(stem(p.toLowerCase()));
  }
  return out;
}

const STOP = new Set(['the', 'and', 'for', 'with', 'this', 'that', 'from', 'are', 'was', 'not', 'but', 'you', 'all', 'can', 'has', 'have', 'its', 'into', 'var', 'let', 'const', 'return', 'new', 'if', 'else', 'of', 'to', 'in', 'is', 'it', 'be', 'as', 'on', 'or', 'an', 'at', 'by', 'self', 'def', 'import', 'export', 'true', 'false', 'null', 'none', 'undefined']);

function stem(w: string): string {
  if (w.length > 5 && w.endsWith('ing')) return w.slice(0, -3);
  if (w.length > 4 && w.endsWith('ies')) return w.slice(0, -3) + 'y';
  if (w.length > 4 && w.endsWith('es') && !w.endsWith('ses')) return w.slice(0, -2);
  if (w.length > 3 && w.endsWith('s') && !w.endsWith('ss')) return w.slice(0, -1);
  if (w.length > 5 && w.endsWith('ed')) return w.slice(0, -2);
  return w;
}

interface Chunk {
  file: string;
  startLine: number;
  endLine: number;
  len: number;
  tf: Map<string, number>;
}

export interface SearchHit {
  file: string;
  startLine: number;
  endLine: number;
  score: number;
  preview: string;
}

/**
 * Incremental project index: file list, symbols and imports (persisted with mtime-based
 * invalidation) plus an in-memory BM25 index over ~50-line chunks for ranked search.
 */
export class ProjectIndex {
  private files = new Map<string, FileRecord>();
  private building: Promise<void> | null = null;
  private built = false;
  private dirty = new Set<string>();
  private chunks: Chunk[] | null = null;
  private df = new Map<string, number>();
  private avgLen = 1;
  maxFiles = 50_000;
  maxFileBytes = 1_000_000;

  constructor(
    readonly root: string,
    private readonly ignore: IgnoreMatcher,
    private readonly cacheFile: string | null,
  ) {}

  get size() {
    return this.files.size;
  }
  get isBuilt() {
    return this.built;
  }

  invalidate(abs: string) {
    const rel = path.relative(this.root, abs).split(path.sep).join('/');
    if (!rel.startsWith('..')) this.dirty.add(rel);
    this.chunks = null;
  }

  /** Build or refresh (incremental). Safe to call concurrently. */
  ensure(signal?: AbortSignal): Promise<void> {
    if (this.built && !this.dirty.size) return Promise.resolve();
    if (this.building) return this.building;
    this.building = (this.built ? this.refreshDirty() : this.build(signal)).finally(() => {
      this.building = null;
    });
    return this.building;
  }

  private async refreshDirty() {
    const sem = new Semaphore(16);
    const list = [...this.dirty];
    this.dirty.clear();
    await Promise.all(
      list.map((rel) =>
        sem.run(async () => {
          const abs = path.join(this.root, rel);
          try {
            const st = await fs.stat(abs);
            const rec = await this.indexFile(rel, abs, st.size, st.mtimeMs);
            if (rec) this.files.set(rel, rec);
          } catch {
            this.files.delete(rel);
          }
        }),
      ),
    );
  }

  private async build(signal?: AbortSignal) {
    const cached = this.cacheFile ? await readJson<{ version: number; files: FileRecord[] }>(this.cacheFile, { version: 0, files: [] }) : { version: 0, files: [] };
    const prev = new Map(cached.version === 2 ? cached.files.map((f) => [f.rel, f]) : []);
    const sem = new Semaphore(24);
    const tasks: Promise<void>[] = [];
    const next = new Map<string, FileRecord>();
    for await (const e of walk(this.root, { ignore: this.ignore, stat: true, maxFiles: this.maxFiles, signal })) {
      const old = prev.get(e.rel);
      if (old && old.mtimeMs === e.mtimeMs && old.size === e.size) {
        next.set(e.rel, old);
        continue;
      }
      tasks.push(
        sem.run(async () => {
          const rec = await this.indexFile(e.rel, e.abs, e.size ?? 0, e.mtimeMs ?? 0);
          if (rec) next.set(e.rel, rec);
        }),
      );
    }
    await Promise.all(tasks);
    this.files = next;
    this.built = true;
    this.chunks = null;
    if (this.cacheFile) await writeJson(this.cacheFile, { version: 2, files: [...next.values()] }).catch(() => {});
  }

  private async indexFile(rel: string, abs: string, size: number, mtimeMs: number): Promise<FileRecord | null> {
    const lang = languageOf(rel);
    const rec: FileRecord = { rel, lang, size, mtimeMs, symbols: [], imports: [], lines: 0 };
    if (size > this.maxFileBytes || (!CODE_LANGS.has(lang) && lang !== 'markdown')) return rec;
    try {
      const text = await fs.readFile(abs, 'utf8');
      if (text.includes('\0')) return rec;
      rec.lines = text.split('\n').length;
      if (CODE_LANGS.has(lang)) {
        rec.symbols = extractSymbols(text, lang);
        rec.imports = extractImports(text, lang);
      }
    } catch {
      /* unreadable */
    }
    return rec;
  }

  list(): FileRecord[] {
    return [...this.files.values()];
  }
  get(rel: string): FileRecord | undefined {
    return this.files.get(rel);
  }

  findSymbols(query: string, opts: { kind?: SymbolKind; exact?: boolean; limit?: number } = {}): Array<SymbolDef & { file: string }> {
    const q = query.toLowerCase();
    const out: Array<SymbolDef & { file: string; rank: number }> = [];
    for (const f of this.files.values()) {
      for (const s of f.symbols) {
        if (opts.kind && s.kind !== opts.kind) continue;
        const n = s.name.toLowerCase();
        let rank = -1;
        if (n === q) rank = 0;
        else if (!opts.exact && n.startsWith(q)) rank = 1;
        else if (!opts.exact && n.includes(q)) rank = 2;
        else if (!opts.exact && fuzzy(q, n)) rank = 3;
        if (rank >= 0) out.push({ ...s, file: f.rel, rank });
      }
    }
    out.sort((a, b) => a.rank - b.rank || a.file.localeCompare(b.file) || a.line - b.line);
    return out.slice(0, opts.limit ?? 100).map(({ rank: _r, ...s }) => s);
  }

  /** Files whose imports reference the given module/file. */
  importersOf(target: string): string[] {
    const t = target.replace(/\\/g, '/');
    const base = t.replace(/\.(tsx?|jsx?|mjs|cjs|py|go|rs)$/, '');
    const stemName = path.posix.basename(base);
    const out: string[] = [];
    for (const f of this.files.values()) {
      for (const imp of f.imports) {
        if (imp === t) {
          out.push(f.rel);
          break;
        }
        if (imp.startsWith('.')) {
          const resolved = path.posix.normalize(path.posix.join(path.posix.dirname(f.rel), imp)).replace(/\.(tsx?|jsx?|mjs|cjs)$/, '').replace(/\/index$/, '');
          if (resolved === base || resolved === base.replace(/\/index$/, '')) {
            out.push(f.rel);
            break;
          }
        } else if (f.lang === 'python' && (imp === base.replace(/\//g, '.') || imp.endsWith('.' + stemName) || imp === stemName)) {
          out.push(f.rel);
          break;
        }
      }
    }
    return out;
  }

  private async buildChunks() {
    const chunks: Chunk[] = [];
    const df = new Map<string, number>();
    const sem = new Semaphore(24);
    let totalLen = 0;
    await Promise.all(
      [...this.files.values()]
        .filter((f) => (CODE_LANGS.has(f.lang) || f.lang === 'markdown') && f.size < 300_000)
        .map((f) =>
          sem.run(async () => {
            let text: string;
            try {
              text = await fs.readFile(path.join(this.root, f.rel), 'utf8');
            } catch {
              return;
            }
            const lines = text.split(/\r?\n/);
            const pathTerms = tokenize(f.rel.replace(/[/.]/g, ' '));
            for (let s = 0; s < lines.length; s += 40) {
              const e = Math.min(lines.length, s + 50);
              const terms = [...tokenize(lines.slice(s, e).join('\n')), ...pathTerms];
              const tf = new Map<string, number>();
              for (const t of terms) tf.set(t, (tf.get(t) ?? 0) + 1);
              for (const sym of f.symbols) if (sym.line > s && sym.line <= e) for (const t of tokenize(sym.name)) tf.set(t, (tf.get(t) ?? 0) + 3);
              for (const t of tf.keys()) df.set(t, (df.get(t) ?? 0) + 1);
              totalLen += terms.length;
              chunks.push({ file: f.rel, startLine: s + 1, endLine: e, len: terms.length, tf });
            }
          }),
        ),
    );
    this.chunks = chunks;
    this.df = df;
    this.avgLen = chunks.length ? totalLen / chunks.length : 1;
  }

  /** BM25-ranked search over code chunks. */
  async search(query: string, limit = 10): Promise<SearchHit[]> {
    await this.ensure();
    if (!this.chunks) await this.buildChunks();
    const chunks = this.chunks!;
    const qTerms = [...new Set(tokenize(query))];
    if (!qTerms.length) return [];
    const N = chunks.length;
    const k1 = 1.2;
    const b = 0.75;
    const scored: Array<{ c: Chunk; score: number }> = [];
    for (const c of chunks) {
      let score = 0;
      for (const t of qTerms) {
        const f = c.tf.get(t);
        if (!f) continue;
        const n = this.df.get(t) ?? 0;
        const idf = Math.log(1 + (N - n + 0.5) / (n + 0.5));
        score += (idf * (f * (k1 + 1))) / (f + k1 * (1 - b + (b * c.len) / this.avgLen));
      }
      if (score > 0) scored.push({ c, score });
    }
    scored.sort((x, y) => y.score - x.score);
    const seenFiles = new Map<string, number>();
    const hits: SearchHit[] = [];
    for (const { c, score } of scored) {
      const n = seenFiles.get(c.file) ?? 0;
      if (n >= 2) continue;
      seenFiles.set(c.file, n + 1);
      let preview = '';
      try {
        const text = await fs.readFile(path.join(this.root, c.file), 'utf8');
        const lines = text.split(/\r?\n/).slice(c.startLine - 1, c.endLine);
        const best = lines.map((l, i) => ({ i, s: qTerms.filter((t) => l.toLowerCase().includes(t)).length })).sort((a, b2) => b2.s - a.s)[0];
        const from = Math.max(0, (best?.i ?? 0) - 2);
        preview = lines
          .slice(from, from + 6)
          .map((l, i) => `${c.startLine + from + i}: ${l.slice(0, 200)}`)
          .join('\n');
      } catch {
        /* gone */
      }
      hits.push({ file: c.file, startLine: c.startLine, endLine: c.endLine, score: Math.round(score * 100) / 100, preview });
      if (hits.length >= limit) break;
    }
    return hits;
  }
}

function fuzzy(q: string, s: string): boolean {
  if (q.length < 3) return false;
  let i = 0;
  for (const ch of s) if (ch === q[i]) i++;
  return i === q.length;
}

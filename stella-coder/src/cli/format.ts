import path from 'node:path';
import type { ToolDisplay } from '../tools/types.js';
import { c } from './theme.js';

export function rel(root: string, p: unknown): string {
  if (typeof p !== 'string') return '';
  const r = path.isAbsolute(p) ? path.relative(root, p) : p;
  return r && !r.startsWith('..') ? r.split(path.sep).join('/') : p;
}

/** Compact one-line argument summary for a tool call header: Read(src/app.ts). */
export function toolArgs(name: string, input: Record<string, any>, root: string): string {
  const i = input ?? {};
  switch (name) {
    case 'Read':
      return rel(root, i.file_path) + (i.offset ? `:${i.offset}${i.limit ? `-${i.offset + i.limit}` : ''}` : '');
    case 'Write':
    case 'Edit':
    case 'MultiEdit':
      return rel(root, i.file_path);
    case 'Delete':
    case 'FileInfo':
    case 'DirectoryTree':
      return rel(root, i.path ?? '.');
    case 'Move':
    case 'Copy':
      return `${rel(root, i.source)} → ${rel(root, i.destination)}`;
    case 'Bash':
    case 'PowerShell':
    case 'Cmd':
    case 'StartProcess':
      return oneLine(i.command);
    case 'RunCommand':
      return oneLine([i.program, ...(i.args ?? [])].join(' '));
    case 'Glob':
      return i.pattern + (i.path ? ` in ${rel(root, i.path)}` : '');
    case 'Grep':
      return `"${i.pattern}"${i.glob ? ` ${i.glob}` : ''}${i.path ? ` in ${rel(root, i.path)}` : ''}`;
    case 'WebFetch':
      return i.url;
    case 'WebSearch':
    case 'SemanticSearch':
    case 'SymbolSearch':
      return `"${i.query}"`;
    case 'Task':
      return `${i.subagent_type ?? 'general'}: ${i.description}`;
    case 'Skill':
      return i.name;
    case 'TodoWrite':
      return `${(i.todos ?? []).length} items`;
    case 'Memory':
      return `${i.action}${i.content ? ` "${oneLine(i.content).slice(0, 50)}"` : ''}`;
    case 'GitCommit':
      return oneLine(String(i.message ?? '').split('\n')[0]);
    default: {
      const s = JSON.stringify(i);
      return s === '{}' ? '' : s.length > 80 ? s.slice(0, 80) + '…' : s;
    }
  }
}

function oneLine(s: unknown): string {
  const t = String(s ?? '').replace(/\s*\n\s*/g, ' ⏎ ');
  return t.length > 120 ? t.slice(0, 120) + '…' : t;
}

/** Lines shown under a finished tool call. */
export function toolResultLines(name: string, content: string, isError: boolean, display: ToolDisplay | undefined, durationMs: number, width: number): string[] {
  const pre = c.faint('  ⎿  ');
  const cont = '     ';
  if (isError) {
    const ls = content.split('\n').filter(Boolean);
    return [pre + c.err(ls[0]?.slice(0, width) ?? 'Error'), ...ls.slice(1, 4).map((l) => cont + c.err(l.slice(0, width))), ...(ls.length > 4 ? [cont + c.faint(`… +${ls.length - 4} lines`)] : [])];
  }
  if (display?.kind === 'diff') {
    const out = [pre + `${display.title ?? 'Updated'} ${c.add(`+${display.added ?? 0}`)} ${c.del(`-${display.removed ?? 0}`)}`];
    const body = (display.body ?? '').split('\n').filter((l) => !l.startsWith('---') && !l.startsWith('+++'));
    for (const l of body.slice(0, 14)) {
      const s = l.slice(0, width);
      out.push(cont + (l.startsWith('+') ? c.add(s) : l.startsWith('-') ? c.del(s) : l.startsWith('@@') ? c.faint(s) : c.dim(s)));
    }
    if (body.length > 14) out.push(cont + c.faint(`… +${body.length - 14} lines (/diff to see all)`));
    return out;
  }
  if (display?.kind === 'todo') {
    return (display.body ?? '').split('\n').map((l, i) => (i === 0 ? pre : cont) + (l.startsWith('[x]') ? c.ok('✔ ') + c.faint(l.slice(4)) : l.startsWith('[~]') ? c.brand('◐ ') + c.bold(l.slice(4)) : c.faint('○ ') + l.slice(4)));
  }
  if (display?.kind === 'agent') return [pre + c.brand(display.title ?? 'subagent') + c.faint(`  ${display.body ?? ''}`)];
  if (name === 'Read') return [pre + c.dim(display?.title ?? `Read ${content.split('\n').length} lines`)];
  if (name === 'Glob' || name === 'Grep' || name === 'SymbolSearch' || name === 'ReferenceSearch') {
    const n = content === 'No files found.' || content.startsWith('No ') ? 0 : content.split('\n').filter(Boolean).length;
    return [pre + c.dim(n ? `Found ${n} ${name === 'Glob' || (name === 'Grep' && !content.includes(':')) ? 'files' : 'results'}` : content.split('\n')[0]!)];
  }
  if (name === 'Skill') return [pre + c.dim(display?.title ?? 'Skill loaded')];
  const lines = content.split('\n');
  const shown = lines.slice(0, 5).map((l, i) => (i === 0 ? pre : cont) + c.dim(l.slice(0, width)));
  if (lines.length > 5) shown.push(cont + c.faint(`… +${lines.length - 5} lines${durationMs > 1500 ? ` · ${(durationMs / 1000).toFixed(1)}s` : ''}`));
  return shown.length ? shown : [pre + c.faint('(no output)')];
}

export function fmtTokens(n: number) {
  return n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n);
}

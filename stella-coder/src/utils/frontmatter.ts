/**
 * Minimal YAML-frontmatter parser for Markdown files (skills, agents, commands).
 * Supports scalars, quoted strings, inline arrays [a, b] and block lists (- item).
 */
export interface Parsed<T = Record<string, unknown>> {
  data: T;
  body: string;
}

export function parseFrontmatter<T = Record<string, unknown>>(src: string): Parsed<T> {
  const text = src.replace(/^﻿/, '');
  const m = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(text);
  if (!m) return { data: {} as T, body: text };
  const data: Record<string, unknown> = {};
  let currentKey: string | null = null;
  for (const rawLine of m[1]!.split(/\r?\n/)) {
    const line = rawLine.replace(/\s+#.*$/, '');
    if (!line.trim()) continue;
    const list = /^\s*-\s+(.*)$/.exec(line);
    if (list && currentKey) {
      const arr = (data[currentKey] as unknown[]) ?? [];
      arr.push(scalar(list[1]!));
      data[currentKey] = arr;
      continue;
    }
    const kv = /^([A-Za-z0-9_\-]+)\s*:\s*(.*)$/.exec(line);
    if (kv) {
      currentKey = kv[1]!;
      const v = kv[2]!.trim();
      data[currentKey] = v === '' ? [] : scalar(v);
    }
  }
  return { data: data as T, body: text.slice(m[0].length) };
}

function scalar(v: string): unknown {
  const s = v.trim();
  if (/^\[.*\]$/.test(s)) {
    const inner = s.slice(1, -1).trim();
    if (!inner) return [];
    return inner.split(',').map((x) => scalar(x));
  }
  if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) return s.slice(1, -1);
  if (s === 'true') return true;
  if (s === 'false') return false;
  if (s === 'null') return null;
  if (/^-?\d+(\.\d+)?$/.test(s)) return Number(s);
  return s;
}

export function toList(v: unknown): string[] {
  if (Array.isArray(v)) return v.map(String).filter(Boolean);
  if (typeof v === 'string') return v.split(',').map((s) => s.trim()).filter(Boolean);
  return [];
}

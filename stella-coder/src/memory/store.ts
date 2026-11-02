import { promises as fs } from 'node:fs';
import path from 'node:path';
import { containsSecret } from '../utils/redact.js';
import { newId } from '../utils/ids.js';
import { readJson, writeJson } from '../utils/fsutil.js';
import { stellaHome } from '../config/paths.js';

export type MemoryType = 'user' | 'project' | 'technical' | 'task' | 'session';

export interface MemoryItem {
  id: string;
  type: MemoryType;
  content: string;
  tags?: string[];
  createdAt: number;
  updatedAt: number;
  source?: string; // session id
}

/**
 * Long-term memory. User-level items live in ~/.stella/memory.json; project/technical/task items
 * in the project data dir; session items in memory only. Secrets are refused.
 */
export class MemoryStore {
  private session: MemoryItem[] = [];
  private readonly userFile = path.join(stellaHome(), 'memory.json');
  private readonly projectFile: string;

  constructor(projectMemoryDir: string) {
    this.projectFile = path.join(projectMemoryDir, 'memory.json');
  }

  private fileFor(type: MemoryType): string | null {
    if (type === 'session') return null;
    return type === 'user' ? this.userFile : this.projectFile;
  }

  async list(type?: MemoryType): Promise<MemoryItem[]> {
    const user = await readJson<MemoryItem[]>(this.userFile, []);
    const proj = await readJson<MemoryItem[]>(this.projectFile, []);
    const all = [...user, ...proj, ...this.session];
    return type ? all.filter((m) => m.type === type) : all;
  }

  private async load(type: MemoryType): Promise<MemoryItem[]> {
    const f = this.fileFor(type);
    if (!f) return [...this.session];
    return (await readJson<MemoryItem[]>(f, [])).filter((m) => m.type === type);
  }
  private async save(type: MemoryType, items: MemoryItem[]): Promise<void> {
    const f = this.fileFor(type);
    if (!f) {
      this.session = items;
      return;
    }
    const others = (await readJson<MemoryItem[]>(f, [])).filter((m) => m.type !== type);
    await writeJson(f, [...others, ...items]);
  }

  async add(type: MemoryType, content: string, tags?: string[], source?: string): Promise<{ item?: MemoryItem; duplicateOf?: MemoryItem; error?: string }> {
    const text = content.trim();
    if (!text) return { error: 'empty memory' };
    if (containsSecret(text)) return { error: 'Refusing to store what looks like a secret (API key, password, private key). Store credentials with `stella auth set` instead.' };
    const items = await this.load(type);
    const norm = normalize(text);
    const dup = items.find((m) => normalize(m.content) === norm || similarity(normalize(m.content), norm) > 0.9);
    if (dup) return { duplicateOf: dup };
    const now = Date.now();
    const item: MemoryItem = { id: newId('m'), type, content: text, tags, createdAt: now, updatedAt: now, source };
    items.push(item);
    await this.save(type, items);
    return { item };
  }

  async update(id: string, content: string): Promise<MemoryItem | null> {
    if (containsSecret(content)) throw new Error('Refusing to store a secret in memory.');
    for (const type of ['user', 'project', 'technical', 'task', 'session'] as MemoryType[]) {
      const items = await this.load(type);
      const it = items.find((m) => m.id === id);
      if (it) {
        it.content = content.trim();
        it.updatedAt = Date.now();
        await this.save(type, items);
        return it;
      }
    }
    return null;
  }

  async remove(id: string): Promise<boolean> {
    for (const type of ['user', 'project', 'technical', 'task', 'session'] as MemoryType[]) {
      const items = await this.load(type);
      const next = items.filter((m) => m.id !== id);
      if (next.length !== items.length) {
        await this.save(type, next);
        return true;
      }
    }
    return false;
  }

  async clear(type: MemoryType): Promise<number> {
    const items = await this.load(type);
    await this.save(type, []);
    return items.length;
  }

  /** Text block injected into the system prompt. */
  async promptBlock(maxChars = 6000): Promise<string> {
    const all = await this.list();
    if (!all.length) return '';
    const label: Record<MemoryType, string> = { user: 'User preferences', project: 'Project knowledge', technical: 'Technical decisions', task: 'Open tasks', session: 'This session' };
    const out: string[] = [];
    for (const t of ['user', 'project', 'technical', 'task', 'session'] as MemoryType[]) {
      const items = all.filter((m) => m.type === t).sort((a, b) => b.updatedAt - a.updatedAt);
      if (items.length) out.push(`## ${label[t]}`, ...items.map((m) => `- [${m.id}] ${m.content}`));
    }
    const s = out.join('\n');
    return s.length > maxChars ? s.slice(0, maxChars) + '\n…(more memories omitted; use Memory list)' : s;
  }

  async exportMarkdown(): Promise<string> {
    return this.promptBlock(1e9);
  }

  async fileExists(): Promise<boolean> {
    return fs.access(this.projectFile).then(() => true, () => false);
  }
}

function normalize(s: string) {
  return s.toLowerCase().replace(/\s+/g, ' ').replace(/[.!?]+$/, '').trim();
}

function similarity(a: string, b: string): number {
  const A = new Set(a.split(' '));
  const B = new Set(b.split(' '));
  let inter = 0;
  for (const w of A) if (B.has(w)) inter++;
  return inter / Math.max(1, Math.max(A.size, B.size));
}

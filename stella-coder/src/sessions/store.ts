import { createReadStream, promises as fs } from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
import type { ChatMessage, Usage } from '../types.js';
import { newId } from '../utils/ids.js';
import { readJson, writeJson } from '../utils/fsutil.js';

/**
 * Sessions are stored as JSONL event logs (one JSON object per line, append-only, versioned)
 * plus a small meta JSON. Format:
 *   {"v":1,"type":"message","message":{...}}
 *   {"v":1,"type":"compact","summary":"...","replacedCount":42}
 *   {"v":1,"type":"usage","model":"...","usage":{...},"costUsd":0.01}
 *   {"v":1,"type":"event","name":"model_change","data":{...}}
 */
export interface SessionMeta {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  cwd: string;
  model: string;
  messageCount: number;
  costUsd: number;
  usage: Usage;
  status: 'active' | 'idle' | 'interrupted';
  pendingTask?: string;
  version: 1;
}

export type SessionRecord =
  | { v: 1; type: 'message'; message: ChatMessage; ts: number }
  | { v: 1; type: 'compact'; summary: string; replacedCount: number; ts: number }
  | { v: 1; type: 'usage'; model: string; usage: Usage; costUsd: number; ts: number }
  | { v: 1; type: 'event'; name: string; data?: unknown; ts: number };

export class SessionStore {
  /** The session currently open in this process (kept in sync by rename). */
  live: SessionMeta | null = null;
  constructor(private readonly dir: string) {}

  private jsonl(id: string) {
    return path.join(this.dir, `${safeId(id)}.jsonl`);
  }
  private metaFile(id: string) {
    return path.join(this.dir, `${safeId(id)}.meta.json`);
  }

  async create(cwd: string, model: string): Promise<SessionMeta> {
    const now = Date.now();
    const meta: SessionMeta = { id: newId('s'), title: 'New session', createdAt: now, updatedAt: now, cwd, model, messageCount: 0, costUsd: 0, usage: { inputTokens: 0, outputTokens: 0, cacheReadTokens: 0, cacheWriteTokens: 0 }, status: 'active', version: 1 };
    await fs.mkdir(this.dir, { recursive: true });
    await writeJson(this.metaFile(meta.id), meta);
    await fs.writeFile(this.jsonl(meta.id), '');
    return meta;
  }

  async append(id: string, rec: SessionRecord): Promise<void> {
    await fs.appendFile(this.jsonl(id), JSON.stringify(rec) + '\n');
  }

  async saveMeta(meta: SessionMeta): Promise<void> {
    meta.updatedAt = Date.now();
    await writeJson(this.metaFile(meta.id), meta);
  }

  async getMeta(id: string): Promise<SessionMeta | null> {
    return readJson<SessionMeta | null>(this.metaFile(id), null);
  }

  /** Rebuild the live conversation: messages after the latest compaction summary. */
  async loadMessages(id: string): Promise<{ messages: ChatMessage[]; records: number; todos?: unknown; mode?: string }> {
    let messages: ChatMessage[] = [];
    let records = 0;
    let todos: unknown;
    let mode: string | undefined;
    const file = this.jsonl(id);
    try {
      await fs.access(file);
    } catch {
      return { messages, records, todos, mode };
    }
    const rl = readline.createInterface({ input: createReadStream(file, 'utf8'), crlfDelay: Infinity });
    for await (const line of rl) {
      if (!line.trim()) continue;
      let rec: SessionRecord;
      try {
        rec = JSON.parse(line);
      } catch {
        continue; // tolerate a torn final line after a crash
      }
      records++;
      if (rec.type === 'message') messages.push(rec.message);
      else if (rec.type === 'compact') messages = [summaryMessage(rec.summary)];
      else if (rec.type === 'event' && rec.name === 'todos') todos = rec.data;
      else if (rec.type === 'event' && rec.name === 'mode') mode = String(rec.data);
    }
    return { messages: repairTranscript(messages), records, todos, mode };
  }

  async list(): Promise<SessionMeta[]> {
    let files: string[] = [];
    try {
      files = await fs.readdir(this.dir);
    } catch {
      return [];
    }
    const metas = await Promise.all(files.filter((f) => f.endsWith('.meta.json')).map((f) => readJson<SessionMeta | null>(path.join(this.dir, f), null)));
    return metas.filter((m): m is SessionMeta => !!m).sort((a, b) => b.updatedAt - a.updatedAt);
  }

  async rename(id: string, title: string): Promise<boolean> {
    const m = this.live?.id === id ? this.live : await this.getMeta(id);
    if (!m) return false;
    m.title = title.slice(0, 120);
    await this.saveMeta(m);
    return true;
  }

  async delete(id: string): Promise<boolean> {
    const m = await this.getMeta(id);
    if (!m) return false;
    await fs.rm(this.jsonl(id), { force: true });
    await fs.rm(this.metaFile(id), { force: true });
    return true;
  }

  /** Full-text search across titles and message text. */
  async search(query: string, limit = 20): Promise<Array<{ meta: SessionMeta; snippet: string }>> {
    const q = query.toLowerCase();
    const out: Array<{ meta: SessionMeta; snippet: string }> = [];
    for (const meta of await this.list()) {
      if (meta.title.toLowerCase().includes(q)) {
        out.push({ meta, snippet: meta.title });
      } else {
        const text = await fs.readFile(this.jsonl(meta.id), 'utf8').catch(() => '');
        const idx = text.toLowerCase().indexOf(q);
        if (idx >= 0) out.push({ meta, snippet: text.slice(Math.max(0, idx - 60), idx + 80).replace(/\\n|\s+/g, ' ') });
      }
      if (out.length >= limit) break;
    }
    return out;
  }

  async findByPrefix(prefix: string): Promise<SessionMeta | null> {
    const all = await this.list();
    return all.find((m) => m.id === prefix) ?? all.find((m) => m.id.startsWith(prefix)) ?? all.find((m) => m.title.toLowerCase() === prefix.toLowerCase()) ?? null;
  }
}

function safeId(id: string) {
  if (!/^[A-Za-z0-9_-]+$/.test(id)) throw new Error('invalid session id');
  return id;
}

export function summaryMessage(summary: string): ChatMessage {
  return {
    role: 'user',
    content: [{ type: 'text', text: `<conversation-summary>\nThis session continues from an earlier conversation that was compacted. Summary of everything so far:\n\n${summary}\n</conversation-summary>` }],
    meta: { kind: 'compact-summary', ts: Date.now() },
  };
}

/**
 * Make a transcript valid for providers after a crash/interrupt: every tool_use must be followed
 * by a matching tool_result; dangling calls get a synthetic "interrupted" result.
 */
export function repairTranscript(messages: ChatMessage[]): ChatMessage[] {
  const out: ChatMessage[] = [];
  for (let i = 0; i < messages.length; i++) {
    const m = messages[i]!;
    out.push(m);
    if (m.role !== 'assistant') continue;
    const uses = m.content.filter((b) => b.type === 'tool_use') as Array<{ id: string }>;
    if (!uses.length) continue;
    const next = messages[i + 1];
    const have = new Set((next?.role === 'user' ? next.content : []).filter((b) => b.type === 'tool_result').map((b: any) => b.toolUseId));
    const missing = uses.filter((u) => !have.has(u.id));
    if (!missing.length) continue;
    const synthetic = missing.map((u) => ({ type: 'tool_result' as const, toolUseId: u.id, content: 'Tool execution was interrupted before completing.', isError: true }));
    if (next?.role === 'user' && have.size) {
      next.content = [...next.content, ...synthetic];
    } else {
      out.push({ role: 'user', content: synthetic });
    }
  }
  return out;
}

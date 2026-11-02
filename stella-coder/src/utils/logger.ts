import { appendFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { redact } from './redact.js';

/**
 * Append-only JSONL audit log. Every tool call, permission decision and hook run is recorded
 * with secrets masked. Never throws.
 */
export class AuditLog {
  constructor(private readonly file: string | null) {
    if (file) {
      try {
        mkdirSync(path.dirname(file), { recursive: true });
      } catch {
        /* ignore */
      }
    }
  }
  write(kind: string, data: Record<string, unknown>): void {
    if (!this.file) return;
    try {
      const line = redact(JSON.stringify({ ts: new Date().toISOString(), kind, ...data }));
      appendFileSync(this.file, line + '\n');
    } catch {
      /* ignore */
    }
  }
}

export const debugEnabled = () => !!process.env.STELLA_DEBUG;
export function debug(...args: unknown[]) {
  if (debugEnabled()) process.stderr.write('[stella] ' + args.map((a) => (typeof a === 'string' ? a : JSON.stringify(a))).join(' ') + '\n');
}

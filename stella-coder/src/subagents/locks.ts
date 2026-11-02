import path from 'node:path';

/**
 * Cooperative file ownership between the main agent and subagents running in parallel.
 * The first agent to modify a file owns it until it finishes; others get a conflict error
 * and must coordinate through the main agent instead of silently overwriting each other.
 */
export class FileLockManager {
  private owners = new Map<string, string>();

  private key(p: string) {
    const r = path.resolve(p);
    return process.platform === 'win32' ? r.toLowerCase() : r;
  }

  claim(file: string, agentId: string): { ok: true } | { ok: false; owner: string } {
    const k = this.key(file);
    const owner = this.owners.get(k);
    if (owner && owner !== agentId) return { ok: false, owner };
    if (agentId !== 'main') this.owners.set(k, agentId);
    return { ok: true };
  }

  releaseAll(agentId: string) {
    for (const [k, v] of this.owners) if (v === agentId) this.owners.delete(k);
  }

  held(): Array<{ file: string; owner: string }> {
    return [...this.owners].map(([file, owner]) => ({ file, owner }));
  }
}

/** Tracks what each agent has read, to enforce read-before-edit and detect external changes. */
export class ReadState {
  private seen = new Map<string, { mtimeMs: number; size: number }>();
  mark(file: string, stat: { mtimeMs: number; size: number }) {
    this.seen.set(path.resolve(file), { mtimeMs: stat.mtimeMs, size: stat.size });
  }
  get(file: string) {
    return this.seen.get(path.resolve(file));
  }
  forget(file: string) {
    this.seen.delete(path.resolve(file));
  }
}

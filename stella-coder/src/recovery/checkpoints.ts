import { createHash } from 'node:crypto';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import { readJson, writeFileAtomic, writeJson } from '../utils/fsutil.js';
import { unifiedDiff } from '../utils/diff.js';

export interface CheckpointEntry {
  turnId: string;
  turnIndex: number;
  file: string; // absolute path
  before: string | null; // blob id, or null if the file did not exist
  after?: string | null; // hash after the agent's change (null = deleted)
  tool: string;
  ts: number;
}

export interface TurnInfo {
  turnId: string;
  turnIndex: number;
  prompt: string;
  ts: number;
  files: string[];
}

export interface RewindResult {
  restored: string[];
  removed: string[];
  conflicts: Array<{ file: string; reason: string }>;
}

const sha = (data: Buffer | string) => createHash('sha256').update(data).digest('hex');

/**
 * File checkpoints. Before the agent first touches a file within a turn, its original bytes are
 * stored as a content-addressed blob. Rewinding restores files to their state before a given
 * turn, refusing (unless forced) when the user changed the file after the agent did.
 */
export class CheckpointStore {
  private entries: CheckpointEntry[] = [];
  private turns: TurnInfo[] = [];
  private loaded = false;
  private readonly indexFile: string;
  private readonly blobDir: string;

  constructor(private readonly dir: string) {
    this.indexFile = path.join(dir, 'index.json');
    this.blobDir = path.join(dir, 'blobs');
  }

  private async load() {
    if (this.loaded) return;
    const data = await readJson<{ entries: CheckpointEntry[]; turns: TurnInfo[] }>(this.indexFile, { entries: [], turns: [] });
    this.entries = data.entries;
    this.turns = data.turns;
    this.loaded = true;
  }
  private async save() {
    await writeJson(this.indexFile, { version: 1, entries: this.entries, turns: this.turns });
  }

  async beginTurn(turnId: string, prompt: string): Promise<void> {
    await this.load();
    if (this.turns.some((t) => t.turnId === turnId)) return;
    this.turns.push({ turnId, turnIndex: this.turns.length, prompt: prompt.slice(0, 200), ts: Date.now(), files: [] });
    await this.save();
  }

  private turnIndex(turnId: string): number {
    return this.turns.find((t) => t.turnId === turnId)?.turnIndex ?? this.turns.length;
  }

  /** Snapshot the file before modification (once per file per turn). */
  async recordBefore(turnId: string, file: string, tool: string): Promise<void> {
    await this.load();
    if (this.entries.some((e) => e.turnId === turnId && e.file === file)) return;
    let before: string | null = null;
    try {
      const buf = await fs.readFile(file);
      before = sha(buf);
      const blob = path.join(this.blobDir, before);
      await fs.mkdir(this.blobDir, { recursive: true });
      try {
        await fs.access(blob);
      } catch {
        await writeFileAtomic(blob, buf);
      }
    } catch (e) {
      if ((e as NodeJS.ErrnoException).code !== 'ENOENT') throw e;
    }
    this.entries.push({ turnId, turnIndex: this.turnIndex(turnId), file, before, tool, ts: Date.now() });
    const t = this.turns.find((x) => x.turnId === turnId);
    if (t && !t.files.includes(file)) t.files.push(file);
    await this.save();
  }

  async recordAfter(turnId: string, file: string): Promise<void> {
    await this.load();
    const e = [...this.entries].reverse().find((x) => x.turnId === turnId && x.file === file);
    if (!e) return;
    try {
      e.after = sha(await fs.readFile(file));
    } catch {
      e.after = null;
    }
    await this.save();
  }

  async listTurns(): Promise<TurnInfo[]> {
    await this.load();
    return [...this.turns];
  }

  async changedFiles(fromTurnIndex = 0): Promise<string[]> {
    await this.load();
    return [...new Set(this.entries.filter((e) => e.turnIndex >= fromTurnIndex).map((e) => e.file))];
  }

  private async blob(id: string): Promise<Buffer> {
    return fs.readFile(path.join(this.blobDir, id));
  }

  /** Diff of every file changed since `fromTurnIndex` (original → current). */
  async diff(fromTurnIndex = 0, root?: string): Promise<string> {
    await this.load();
    const out: string[] = [];
    for (const file of await this.changedFiles(fromTurnIndex)) {
      const first = this.entries.find((e) => e.file === file && e.turnIndex >= fromTurnIndex)!;
      const before = first.before ? (await this.blob(first.before)).toString('utf8') : '';
      let after = '';
      try {
        after = await fs.readFile(file, 'utf8');
      } catch {
        /* deleted */
      }
      const rel = root ? path.relative(root, file).split(path.sep).join('/') : file;
      const d = unifiedDiff(before, after, rel);
      if (d.text) out.push(d.text);
    }
    return out.join('\n');
  }

  /**
   * Restore all files touched in turns >= turnIndex to their state before that turn.
   * Conflict: the file's current content differs from what the agent last wrote.
   */
  async rewind(turnIndex: number, opts: { force?: boolean } = {}): Promise<RewindResult> {
    await this.load();
    const result: RewindResult = { restored: [], removed: [], conflicts: [] };
    const affected = this.entries.filter((e) => e.turnIndex >= turnIndex);
    const files = [...new Set(affected.map((e) => e.file))];
    for (const file of files) {
      const fileEntries = affected.filter((e) => e.file === file);
      const first = fileEntries[0]!;
      const last = fileEntries[fileEntries.length - 1]!;
      let current: string | null = null;
      try {
        current = sha(await fs.readFile(file));
      } catch {
        current = null;
      }
      if (!opts.force && last.after !== undefined && current !== last.after) {
        result.conflicts.push({ file, reason: 'file was modified outside the agent after its last change' });
        continue;
      }
      if (first.before === null) {
        await fs.rm(file, { force: true });
        result.removed.push(file);
      } else {
        await writeFileAtomic(file, await this.blob(first.before));
        result.restored.push(file);
      }
    }
    if (!result.conflicts.length || opts.force) {
      this.entries = this.entries.filter((e) => e.turnIndex < turnIndex);
      this.turns = this.turns.filter((t) => t.turnIndex < turnIndex);
    } else {
      const conflicted = new Set(result.conflicts.map((c) => c.file));
      this.entries = this.entries.filter((e) => e.turnIndex < turnIndex || conflicted.has(e.file));
    }
    await this.save();
    return result;
  }
}

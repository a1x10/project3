import { DatabaseSync } from 'node:sqlite';
import fs from 'node:fs';
import path from 'node:path';

export interface User {
  id: number;
  tg_id: number;
  tg_username: string | null;
  name: string;
  role: 'user' | 'admin';
  plan: string;
  status: 'active' | 'banned';
  created_at: number;
  last_seen_at: number | null;
}

export interface Plan {
  name: string;
  /** null = unlimited */
  dailyRequests: number | null;
  dailyTokens: number | null;
}

export const DEFAULT_PLANS: Record<string, Plan> = {
  free: { name: 'Free', dailyRequests: 50, dailyTokens: 200_000 },
  pro: { name: 'Pro', dailyRequests: 1000, dailyTokens: 5_000_000 },
  unlimited: { name: 'Unlimited', dailyRequests: null, dailyTokens: null },
};

const SCHEMA = `
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tg_id INTEGER NOT NULL UNIQUE,
  tg_username TEXT,
  name TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT 'user',
  plan TEXT NOT NULL DEFAULT 'free',
  status TEXT NOT NULL DEFAULT 'active',
  created_at INTEGER NOT NULL,
  last_seen_at INTEGER
);
CREATE TABLE IF NOT EXISTS api_keys (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  prefix TEXT NOT NULL,
  key_hash TEXT NOT NULL UNIQUE,
  client TEXT,
  created_at INTEGER NOT NULL,
  last_used_at INTEGER,
  revoked_at INTEGER
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS login_requests (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL,
  client TEXT NOT NULL,
  kind TEXT NOT NULL,
  device TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  ts INTEGER NOT NULL,
  day TEXT NOT NULL,
  model TEXT,
  client TEXT,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  status INTEGER NOT NULL DEFAULT 200
);
CREATE INDEX IF NOT EXISTS usage_user_day ON usage(user_id, day);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
`;

export class Store {
  readonly db: DatabaseSync;

  constructor(file: string) {
    if (file !== ':memory:') fs.mkdirSync(path.dirname(path.resolve(file)), { recursive: true });
    this.db = new DatabaseSync(file);
    this.db.exec(SCHEMA);
  }

  close() {
    this.db.close();
  }

  // ---------------- settings
  getSetting<T>(key: string, fallback: T): T {
    const row = this.db.prepare('SELECT value FROM settings WHERE key = ?').get(key) as { value: string } | undefined;
    if (!row) return fallback;
    try {
      return JSON.parse(row.value) as T;
    } catch {
      return fallback;
    }
  }
  setSetting(key: string, value: unknown) {
    this.db.prepare('INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value').run(key, JSON.stringify(value));
  }
  plans(): Record<string, Plan> {
    return this.getSetting('plans', DEFAULT_PLANS);
  }

  // ---------------- users
  userByTg(tgId: number): User | undefined {
    return this.db.prepare('SELECT * FROM users WHERE tg_id = ?').get(tgId) as unknown as User | undefined;
  }
  userById(id: number): User | undefined {
    return this.db.prepare('SELECT * FROM users WHERE id = ?').get(id) as unknown as User | undefined;
  }
  findUser(q: string): User | undefined {
    const s = q.trim().replace(/^@/, '');
    if (/^\d+$/.test(s)) return this.userById(Number(s)) ?? this.userByTg(Number(s));
    return this.db.prepare('SELECT * FROM users WHERE lower(tg_username) = lower(?)').get(s) as unknown as User | undefined;
  }
  /** Create or refresh a user from Telegram data. */
  upsertTgUser(tg: { id: number; username?: string; first_name?: string; last_name?: string }, makeAdmin: boolean): { user: User; created: boolean } {
    const name = [tg.first_name, tg.last_name].filter(Boolean).join(' ') || tg.username || `user${tg.id}`;
    const existing = this.userByTg(tg.id);
    const now = Date.now();
    if (existing) {
      this.db.prepare('UPDATE users SET tg_username = ?, name = ?, last_seen_at = ?, role = CASE WHEN ? THEN \'admin\' ELSE role END WHERE id = ?').run(tg.username ?? null, name, now, makeAdmin ? 1 : 0, existing.id);
      return { user: this.userById(existing.id)!, created: false };
    }
    const role = makeAdmin ? 'admin' : 'user';
    const plan = makeAdmin ? 'unlimited' : this.getSetting('default_plan', 'free');
    const r = this.db.prepare('INSERT INTO users(tg_id, tg_username, name, role, plan, created_at, last_seen_at) VALUES(?,?,?,?,?,?,?)').run(tg.id, tg.username ?? null, name, role, plan, now, now);
    return { user: this.userById(Number(r.lastInsertRowid))!, created: true };
  }
  listUsers(opts: { q?: string; limit?: number; offset?: number } = {}): { users: Array<User & { requests_today: number; tokens_today: number; keys: number }>; total: number } {
    const day = today();
    const q = (opts.q ?? '').trim().replace(/^@/, '');
    const where = q ? `WHERE lower(u.name) LIKE lower(?) OR lower(coalesce(u.tg_username,'')) LIKE lower(?) OR CAST(u.tg_id AS TEXT) = ? OR CAST(u.id AS TEXT) = ?` : '';
    const params = q ? [`%${q}%`, `%${q}%`, q, q] : [];
    const total = (this.db.prepare(`SELECT count(*) AS n FROM users u ${where}`).get(...params) as { n: number }).n;
    const users = this.db
      .prepare(
        `SELECT u.*,
          coalesce((SELECT count(*) FROM usage g WHERE g.user_id = u.id AND g.day = ? AND g.status < 400), 0) AS requests_today,
          coalesce((SELECT sum(input_tokens + output_tokens) FROM usage g WHERE g.user_id = u.id AND g.day = ?), 0) AS tokens_today,
          (SELECT count(*) FROM api_keys k WHERE k.user_id = u.id AND k.revoked_at IS NULL) AS keys
         FROM users u ${where} ORDER BY u.id DESC LIMIT ? OFFSET ?`,
      )
      .all(day, day, ...params, opts.limit ?? 50, opts.offset ?? 0) as any[];
    return { users, total };
  }
  updateUser(id: number, patch: Partial<Pick<User, 'role' | 'plan' | 'status' | 'name'>>): User | undefined {
    const fields = Object.entries(patch).filter(([, v]) => v !== undefined);
    if (!fields.length) return this.userById(id);
    this.db.prepare(`UPDATE users SET ${fields.map(([k]) => `${k} = ?`).join(', ')} WHERE id = ?`).run(...fields.map(([, v]) => v as string), id);
    if (patch.status === 'banned') this.db.prepare('DELETE FROM sessions WHERE user_id = ?').run(id);
    return this.userById(id);
  }
  deleteUser(id: number): boolean {
    return this.db.prepare('DELETE FROM users WHERE id = ?').run(id).changes > 0;
  }
  touch(userId: number) {
    this.db.prepare('UPDATE users SET last_seen_at = ? WHERE id = ?').run(Date.now(), userId);
  }

  // ---------------- usage
  usageToday(userId: number): { requests: number; tokens: number } {
    const r = this.db.prepare('SELECT count(*) AS requests, coalesce(sum(input_tokens + output_tokens), 0) AS tokens FROM usage WHERE user_id = ? AND day = ? AND status < 400').get(userId, today()) as { requests: number; tokens: number };
    return { requests: Number(r.requests), tokens: Number(r.tokens) };
  }
  usageDays(userId: number, days = 14): Array<{ day: string; requests: number; tokens: number }> {
    return this.db
      .prepare('SELECT day, count(*) AS requests, coalesce(sum(input_tokens + output_tokens),0) AS tokens FROM usage WHERE user_id = ? GROUP BY day ORDER BY day DESC LIMIT ?')
      .all(userId, days) as any[];
  }
  recordUsage(u: { userId: number; model?: string; client?: string; input: number; output: number; status: number }) {
    this.db.prepare('INSERT INTO usage(user_id, ts, day, model, client, input_tokens, output_tokens, status) VALUES(?,?,?,?,?,?,?,?)').run(u.userId, Date.now(), today(), u.model ?? null, u.client ?? null, u.input, u.output, u.status);
  }
  stats() {
    const day = today();
    const one = (sql: string, ...p: any[]) => Number((this.db.prepare(sql).get(...p) as any).n ?? 0);
    return {
      users: one('SELECT count(*) AS n FROM users'),
      banned: one("SELECT count(*) AS n FROM users WHERE status = 'banned'"),
      activeToday: one('SELECT count(DISTINCT user_id) AS n FROM usage WHERE day = ?', day),
      requestsToday: one('SELECT count(*) AS n FROM usage WHERE day = ?', day),
      tokensToday: one('SELECT coalesce(sum(input_tokens + output_tokens),0) AS n FROM usage WHERE day = ?', day),
      newToday: one('SELECT count(*) AS n FROM users WHERE created_at >= ?', startOfDay()),
    };
  }
}

export function today(d = new Date()): string {
  return d.toISOString().slice(0, 10);
}
function startOfDay(): number {
  const d = new Date();
  d.setUTCHours(0, 0, 0, 0);
  return d.getTime();
}

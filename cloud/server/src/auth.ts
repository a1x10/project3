import { createHash, randomBytes, randomInt } from 'node:crypto';
import type { Store, User } from './db.js';

export const sha256 = (s: string) => createHash('sha256').update(s).digest('hex');
export const randomToken = (bytes = 32) => randomBytes(bytes).toString('base64url');

const CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; // no 0/O/1/I
export function humanCode(len = 8): string {
  let s = '';
  for (let i = 0; i < len; i++) s += CODE_ALPHABET[randomInt(CODE_ALPHABET.length)];
  return `${s.slice(0, 4)}-${s.slice(4)}`;
}

export type Client = 'web' | 'studio' | 'stella' | 'other';
export type LoginKind = 'session' | 'apikey';

export interface LoginRequest {
  id: string;
  code: string;
  client: Client;
  kind: LoginKind;
  device: string | null;
  status: 'pending' | 'approved' | 'denied' | 'consumed';
  user_id: number | null;
  created_at: number;
  expires_at: number;
}

export class Auth {
  constructor(
    private readonly store: Store,
    private readonly opts: { sessionTtlDays: number; loginTtlSec: number },
  ) {}

  // ---------------- API keys (STELLA, Studio, any OpenAI client)
  createApiKey(userId: number, name: string, client?: string): { key: string; id: number; prefix: string } {
    const key = `sk-stella-${randomToken(24)}`;
    const prefix = key.slice(0, 16);
    const r = this.store.db
      .prepare('INSERT INTO api_keys(user_id, name, prefix, key_hash, client, created_at) VALUES(?,?,?,?,?,?)')
      .run(userId, name.slice(0, 60) || 'key', prefix, sha256(key), client ?? null, Date.now());
    return { key, id: Number(r.lastInsertRowid), prefix };
  }
  listKeys(userId: number) {
    return this.store.db
      .prepare('SELECT id, name, prefix, client, created_at, last_used_at FROM api_keys WHERE user_id = ? AND revoked_at IS NULL ORDER BY id DESC')
      .all(userId) as Array<{ id: number; name: string; prefix: string; client: string | null; created_at: number; last_used_at: number | null }>;
  }
  revokeKey(userId: number | null, keyId: number): boolean {
    const sql = userId === null ? 'UPDATE api_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL' : 'UPDATE api_keys SET revoked_at = ? WHERE id = ? AND user_id = ? AND revoked_at IS NULL';
    const args = userId === null ? [Date.now(), keyId] : [Date.now(), keyId, userId];
    return this.store.db.prepare(sql).run(...args).changes > 0;
  }
  revokeAllKeys(userId: number): number {
    return Number(this.store.db.prepare('UPDATE api_keys SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL').run(Date.now(), userId).changes);
  }

  // ---------------- sessions (website)
  createSession(userId: number): string {
    const token = `sess_${randomToken(32)}`;
    const now = Date.now();
    this.store.db.prepare('INSERT INTO sessions(token_hash, user_id, created_at, expires_at) VALUES(?,?,?,?)').run(sha256(token), userId, now, now + this.opts.sessionTtlDays * 86_400_000);
    return token;
  }
  deleteSession(token: string) {
    this.store.db.prepare('DELETE FROM sessions WHERE token_hash = ?').run(sha256(token));
  }

  /** Resolve a bearer credential (session token or API key) to an active-or-banned user. */
  resolve(bearer: string | undefined | null): { user: User; via: 'session' | 'apikey'; keyId?: number } | null {
    if (!bearer) return null;
    const token = bearer.replace(/^Bearer\s+/i, '').trim();
    if (!token) return null;
    const h = sha256(token);
    if (token.startsWith('sess_')) {
      const row = this.store.db.prepare('SELECT user_id, expires_at FROM sessions WHERE token_hash = ?').get(h) as { user_id: number; expires_at: number } | undefined;
      if (!row || row.expires_at < Date.now()) return null;
      const user = this.store.userById(row.user_id);
      return user ? { user, via: 'session' } : null;
    }
    const row = this.store.db.prepare('SELECT id, user_id FROM api_keys WHERE key_hash = ? AND revoked_at IS NULL').get(h) as { id: number; user_id: number } | undefined;
    if (!row) return null;
    const user = this.store.userById(row.user_id);
    if (!user) return null;
    this.store.db.prepare('UPDATE api_keys SET last_used_at = ? WHERE id = ?').run(Date.now(), row.id);
    return { user, via: 'apikey', keyId: row.id };
  }

  // ---------------- login through Telegram (device flow)
  startLogin(client: Client, kind: LoginKind, device?: string): LoginRequest {
    this.store.db.prepare('DELETE FROM login_requests WHERE expires_at < ?').run(Date.now() - 3_600_000);
    const req: LoginRequest = {
      id: randomToken(12),
      code: humanCode(),
      client,
      kind,
      device: device ? device.slice(0, 80) : null,
      status: 'pending',
      user_id: null,
      created_at: Date.now(),
      expires_at: Date.now() + this.opts.loginTtlSec * 1000,
    };
    this.store.db
      .prepare('INSERT INTO login_requests(id, code, client, kind, device, status, created_at, expires_at) VALUES(?,?,?,?,?,?,?,?)')
      .run(req.id, req.code, req.client, req.kind, req.device, req.status, req.created_at, req.expires_at);
    return req;
  }
  getLogin(id: string): LoginRequest | undefined {
    return this.store.db.prepare('SELECT * FROM login_requests WHERE id = ?').get(id) as unknown as LoginRequest | undefined;
  }
  loginByCode(code: string): LoginRequest | undefined {
    const c = code.trim().toUpperCase().replace(/[^A-Z0-9]/g, '');
    if (c.length !== 8) return undefined;
    return this.store.db.prepare("SELECT * FROM login_requests WHERE replace(code, '-', '') = ? AND status = 'pending' AND expires_at > ?").get(c, Date.now()) as unknown as LoginRequest | undefined;
  }
  decide(id: string, userId: number, approve: boolean): LoginRequest | undefined {
    const r = this.getLogin(id);
    if (!r || r.status !== 'pending' || r.expires_at < Date.now()) return undefined;
    this.store.db.prepare('UPDATE login_requests SET status = ?, user_id = ? WHERE id = ?').run(approve ? 'approved' : 'denied', userId, id);
    return this.getLogin(id);
  }

  /** Client polls; an approved request yields its credential exactly once. */
  poll(id: string): { status: 'pending' | 'denied' | 'expired' | 'unknown' } | { status: 'approved'; user: User; token?: string; apiKey?: string } {
    const r = this.getLogin(id);
    if (!r) return { status: 'unknown' };
    if (r.status === 'denied') return { status: 'denied' };
    if (r.status === 'consumed') return { status: 'expired' };
    if (r.status === 'pending') return r.expires_at < Date.now() ? { status: 'expired' } : { status: 'pending' };
    // approved → consume atomically
    const changed = this.store.db.prepare("UPDATE login_requests SET status = 'consumed' WHERE id = ? AND status = 'approved'").run(id).changes;
    if (!changed) return { status: 'expired' };
    const user = this.store.userById(r.user_id!);
    if (!user) return { status: 'unknown' };
    if (r.kind === 'session') return { status: 'approved', user, token: this.createSession(user.id) };
    const label = r.client === 'studio' ? 'Vibing AI Studio' : r.client === 'stella' ? 'STELLA CODER' : r.client;
    const { key } = this.createApiKey(user.id, `${label}${r.device ? ` · ${r.device}` : ''}`, r.client);
    return { status: 'approved', user, apiKey: key };
  }
}

export function publicUser(u: User) {
  return { id: u.id, tgId: u.tg_id, username: u.tg_username, name: u.name, role: u.role, plan: u.plan, status: u.status, createdAt: u.created_at, lastSeenAt: u.last_seen_at };
}

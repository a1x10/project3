import os from 'node:os';
import { getCredential, setCredential } from '../config/settings.js';

/**
 * Stella Cloud sign-in for the terminal: device flow through the Telegram bot.
 * Saves `cloud.url` and `cloud.apiKey` into ~/.stella/credentials.json (0600); the `cloud`
 * provider (and Vibing AI Studio) read them from there.
 */
export interface LoginIO {
  print(text: string): void;
  openUrl?(url: string): void;
  sleep?(ms: number): Promise<void>;
  /** Stop after this long (ms). */
  timeoutMs?: number;
}

export function normalizeCloudUrl(url: string): string {
  let u = url.trim().replace(/\/+$/, '').replace(/\/v1$/, '');
  if (!/^https?:\/\//i.test(u)) u = `https://${u}`;
  return u;
}

async function json(res: Response) {
  const j: any = await res.json().catch(() => null);
  if (!res.ok) throw new Error(j?.error?.message || `HTTP ${res.status}`);
  return j;
}

export async function cloudLogin(urlArg: string | undefined, io: LoginIO): Promise<{ url: string; user: any }> {
  const saved = await getCredential('cloud.url');
  const raw = urlArg || process.env.STELLA_CLOUD_URL || saved;
  if (!raw) throw new Error('Укажите адрес сервера: stella-coder login https://ai.example.com');
  const url = normalizeCloudUrl(raw);
  const start = await json(
    await fetch(`${url}/api/auth/start`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-stella-client': 'stella' },
      body: JSON.stringify({ client: 'stella', kind: 'apikey', device: `${os.hostname()} · терминал` }),
    }),
  );
  io.print(`\n  Вход в Stella Cloud (${url})\n`);
  if (start.link) io.print(`  1. Откройте бота: ${start.link}`);
  else io.print('  1. Откройте Telegram-бота сервера');
  io.print(`  2. Подтвердите вход. Код: ${start.code}   (или отправьте боту: /login ${start.code})\n`);
  if (start.link) io.openUrl?.(start.link);
  const sleep = io.sleep ?? ((ms: number) => new Promise((r) => setTimeout(r, ms)));
  const deadline = Date.now() + (io.timeoutMs ?? Math.max(30_000, (start.expiresAt ?? Date.now() + 600_000) - Date.now()));
  while (Date.now() < deadline) {
    await sleep((start.interval ?? 2) * 1000);
    let r: any;
    try {
      r = await json(await fetch(`${url}/api/auth/poll?id=${encodeURIComponent(start.id)}`));
    } catch {
      continue; // network hiccup
    }
    if (r.status === 'approved' && r.apiKey) {
      await setCredential('cloud.url', url);
      await setCredential('cloud.apiKey', r.apiKey);
      return { url, user: r.user };
    }
    if (r.status === 'denied') throw new Error('Вход отклонён в Telegram.');
    if (r.status === 'expired' || r.status === 'unknown') throw new Error('Код устарел — запустите stella-coder login ещё раз.');
  }
  throw new Error('Время ожидания истекло — запустите stella-coder login ещё раз.');
}

export async function cloudLogout(): Promise<boolean> {
  const url = await getCredential('cloud.url');
  const key = await getCredential('cloud.apiKey');
  if (url && key) {
    await fetch(`${url}/api/auth/logout`, { method: 'POST', headers: { authorization: `Bearer ${key}`, 'content-type': 'application/json' }, body: '{}' }).catch(() => undefined);
  }
  await setCredential('cloud.apiKey', null);
  return !!key;
}

export async function cloudWhoami(): Promise<{ url?: string; user?: any; error?: string }> {
  const url = await getCredential('cloud.url');
  const key = await getCredential('cloud.apiKey');
  if (!url || !key) return { url, error: 'не выполнен вход (stella-coder login)' };
  try {
    const r = await json(await fetch(`${url}/api/me`, { headers: { authorization: `Bearer ${key}` } }));
    return { url, user: r.user };
  } catch (e) {
    return { url, error: (e as Error).message };
  }
}

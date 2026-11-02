import { randomBytes } from 'node:crypto';

export function newId(prefix = ''): string {
  const t = Date.now().toString(36);
  const r = randomBytes(5).toString('hex');
  return `${prefix}${t}${r}`;
}

export function shortHash(input: string): string {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h.toString(16).padStart(8, '0');
}

const TOKEN_KEY = 'stella-cloud-session';

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || '';
  } catch {
    return '';
  }
}
export function setToken(t) {
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private mode */
  }
}

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

export async function api(path, { method, body, token = getToken() } = {}) {
  const res = await fetch(path, {
    method: method || (body ? 'POST' : 'GET'),
    headers: { ...(body ? { 'content-type': 'application/json' } : {}), ...(token ? { authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  let json = null;
  try {
    json = await res.json();
  } catch {
    /* empty */
  }
  if (!res.ok) throw new ApiError(res.status, json?.error?.message || `HTTP ${res.status}`);
  return json;
}

export const fmt = (n) => (n === null || n === undefined ? '∞' : Number(n).toLocaleString('ru-RU'));
export const date = (ts) => (ts ? new Date(ts).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }) : '—');

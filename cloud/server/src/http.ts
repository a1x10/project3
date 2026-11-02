import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';

export type Req = http.IncomingMessage & { params: Record<string, string>; query: URLSearchParams; pathname: string };
export type Handler = (req: Req, res: http.ServerResponse) => Promise<void> | void;

export class HttpError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly type = 'error',
  ) {
    super(message);
  }
}

interface Route {
  method: string;
  re: RegExp;
  keys: string[];
  handler: Handler;
}

export class Router {
  private routes: Route[] = [];
  add(method: string, pattern: string, handler: Handler) {
    const keys: string[] = [];
    const re = new RegExp('^' + pattern.replace(/:([A-Za-z_]+)/g, (_m, k) => (keys.push(k), '([^/]+)')).replace(/\*$/, '.*') + '/?$');
    this.routes.push({ method, re, keys, handler });
    return this;
  }
  get = (p: string, h: Handler) => this.add('GET', p, h);
  post = (p: string, h: Handler) => this.add('POST', p, h);
  patch = (p: string, h: Handler) => this.add('PATCH', p, h);
  put = (p: string, h: Handler) => this.add('PUT', p, h);
  delete = (p: string, h: Handler) => this.add('DELETE', p, h);

  match(method: string, pathname: string): { handler: Handler; params: Record<string, string> } | null {
    for (const r of this.routes) {
      if (r.method !== method) continue;
      const m = r.re.exec(pathname);
      if (m) return { handler: r.handler, params: Object.fromEntries(r.keys.map((k, i) => [k, decodeURIComponent(m[i + 1]!)])) };
    }
    return null;
  }
}

export function sendJson(res: http.ServerResponse, status: number, body: unknown) {
  if (res.headersSent) return;
  const data = JSON.stringify(body);
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'content-length': Buffer.byteLength(data) });
  res.end(data);
}

export function sendError(res: http.ServerResponse, status: number, message: string, type = 'error') {
  sendJson(res, status, { error: { message, type } });
}

export async function readBody(req: http.IncomingMessage, max: number): Promise<Buffer> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const c of req) {
    size += (c as Buffer).length;
    if (size > max) throw new HttpError(413, 'Request body too large');
    chunks.push(c as Buffer);
  }
  return Buffer.concat(chunks);
}

export async function readJson<T = any>(req: http.IncomingMessage, max = 1_000_000): Promise<T> {
  const buf = await readBody(req, max);
  if (!buf.length) return {} as T;
  try {
    return JSON.parse(buf.toString('utf8')) as T;
  } catch {
    throw new HttpError(400, 'Invalid JSON body');
  }
}

/** API routes are called from the website, the desktop app (file:// origin) and CLI — token auth, no cookies. */
export function applyCors(req: http.IncomingMessage, res: http.ServerResponse) {
  res.setHeader('access-control-allow-origin', '*');
  res.setHeader('access-control-allow-headers', 'authorization, content-type, x-stella-client');
  res.setHeader('access-control-allow-methods', 'GET, POST, PUT, PATCH, DELETE, OPTIONS');
  res.setHeader('access-control-expose-headers', 'x-routed-via, x-ratelimit-remaining-requests');
  res.setHeader('access-control-max-age', '86400');
}

const MIME: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.json': 'application/json',
  '.webmanifest': 'application/manifest+json',
  '.woff2': 'font/woff2',
  '.exe': 'application/octet-stream',
  '.txt': 'text/plain; charset=utf-8',
};

/** Serve the SPA from webDir (index.html fallback for client routes). */
export function serveStatic(webDir: string, pathname: string, res: http.ServerResponse): boolean {
  if (!fs.existsSync(webDir)) return false;
  const root = path.resolve(webDir);
  let file = path.resolve(root, '.' + decodeURIComponent(pathname));
  if (!file.startsWith(root)) return false;
  if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(root, 'index.html');
  if (!fs.existsSync(file)) return false;
  const ext = path.extname(file);
  res.writeHead(200, {
    'content-type': MIME[ext] ?? 'application/octet-stream',
    'cache-control': ext === '.html' ? 'no-cache' : 'public, max-age=31536000, immutable',
    'x-content-type-options': 'nosniff',
    'referrer-policy': 'no-referrer',
    ...(ext === '.html' ? { 'content-security-policy': "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; connect-src 'self'; frame-ancestors 'none'" } : {}),
  });
  fs.createReadStream(file).pipe(res);
  return true;
}

/** Tiny fixed-window limiter for auth endpoints. */
export class RateLimiter {
  private hits = new Map<string, { n: number; reset: number }>();
  constructor(
    private readonly max: number,
    private readonly windowMs: number,
  ) {}
  allow(key: string): boolean {
    const now = Date.now();
    const h = this.hits.get(key);
    if (!h || h.reset < now) {
      this.hits.set(key, { n: 1, reset: now + this.windowMs });
      if (this.hits.size > 10_000) for (const [k, v] of this.hits) if (v.reset < now) this.hits.delete(k);
      return true;
    }
    h.n++;
    return h.n <= this.max;
  }
}

export function clientIp(req: http.IncomingMessage): string {
  const fwd = req.headers['x-forwarded-for'];
  const first = (Array.isArray(fwd) ? fwd[0] : fwd)?.split(',')[0]?.trim();
  return first || req.socket.remoteAddress || 'unknown';
}

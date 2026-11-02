import http from 'node:http';
import type { AddressInfo } from 'node:net';
import { createApp, type App } from '../src/app.js';
import { loadConfig } from '../src/config.js';
import { Store } from '../src/db.js';

export async function listen(handler: http.RequestListener): Promise<{ url: string; server: http.Server; close: () => Promise<void> }> {
  const server = http.createServer(handler);
  await new Promise<void>((r) => server.listen(0, '127.0.0.1', r));
  const { port } = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${port}`,
    server,
    close: () =>
      new Promise((r) => {
        server.close(() => r());
        server.closeAllConnections();
      }),
  };
}

const body = (req: http.IncomingMessage) =>
  new Promise<any>((resolve) => {
    let s = '';
    req.on('data', (c) => (s += c));
    req.on('end', () => {
      try {
        resolve(s ? JSON.parse(s) : {});
      } catch {
        resolve({});
      }
    });
  });

/** Fake Telegram Bot API: records outgoing calls, lets tests push updates. */
export async function fakeTelegram() {
  const sent: Array<{ method: string; params: any }> = [];
  const queue: any[] = [];
  let waiters: Array<() => void> = [];
  let updateId = 1;
  const srv = await listen(async (req, res) => {
    const method = (req.url ?? '').split('/').pop()!;
    const params = await body(req);
    const reply = (result: unknown) => {
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ ok: true, result }));
    };
    if (method === 'getMe') return reply({ id: 999, is_bot: true, username: 'stella_test_bot' });
    if (method === 'getUpdates') {
      const take = () => reply(queue.splice(0).filter((u) => u.update_id >= (params.offset ?? 0)));
      if (queue.length) return take();
      const t = setTimeout(take, 300);
      waiters.push(() => {
        clearTimeout(t);
        take();
      });
      return;
    }
    sent.push({ method, params });
    reply(method === 'sendMessage' ? { message_id: sent.length, chat: { id: params.chat_id, type: 'private' } } : true);
  });
  const push = (u: any) => {
    queue.push({ update_id: updateId++, ...u });
    const w = waiters;
    waiters = [];
    w.forEach((f) => f());
  };
  const names = new Map<number, string>();
  const from = (id: number, name?: string) => {
    if (name) names.set(id, name);
    const first_name = names.get(id) ?? `User${id}`;
    return { id, first_name, username: first_name.toLowerCase(), is_bot: false };
  };
  return {
    ...srv,
    sent,
    /** Send a private text message as a Telegram user. */
    say(id: number, text: string, name?: string) {
      push({ message: { message_id: updateId, from: from(id, name), chat: { id, type: 'private' }, text } });
    },
    press(id: number, data: string) {
      push({ callback_query: { id: `cb${updateId}`, from: from(id), data, message: { message_id: 1, chat: { id, type: 'private' } } } });
    },
    async waitFor(pred: (m: { method: string; params: any }) => boolean, ms = 5000) {
      const end = Date.now() + ms;
      for (;;) {
        const m = sent.find(pred);
        if (m) return m;
        if (Date.now() > end) throw new Error('timeout waiting for telegram call; sent: ' + JSON.stringify(sent.map((s) => s.params.text ?? s.method)));
        await new Promise((r) => setTimeout(r, 20));
      }
    },
    lastTo(chat: number) {
      return [...sent].reverse().find((s) => s.params.chat_id === chat && s.method === 'sendMessage');
    },
  };
}

/** Fake OpenAI-compatible upstream (FreeLLMAPI stand-in) with dashboard auth endpoints. */
export async function fakeUpstream(opts: { key?: string } = {}) {
  let key = opts.key ?? 'freellmapi-unified-key';
  const requests: any[] = [];
  const srv = await listen(async (req, res) => {
    const url = req.url ?? '';
    const json = (status: number, j: unknown, headers: Record<string, string> = {}) => {
      res.writeHead(status, { 'content-type': 'application/json', ...headers });
      res.end(JSON.stringify(j));
    };
    if (url === '/api/auth/login') {
      const b = await body(req);
      return b.email === 'admin@local' && b.password === 'pw' ? json(200, { token: 'dash-session' }) : json(401, { error: { message: 'bad creds' } });
    }
    if (url === '/api/settings/api-key') return req.headers.authorization === 'Bearer dash-session' ? json(200, { apiKey: key }) : json(401, { error: { message: 'no' } });
    if (req.headers.authorization !== `Bearer ${key}`) return json(401, { error: { message: 'Invalid API key' } });
    if (url === '/v1/models') return json(200, { object: 'list', data: [{ id: 'auto' }, { id: 'auto:smart' }, { id: 'auto:fast' }] });
    if (url === '/v1/chat/completions') {
      const b = await body(req);
      requests.push(b);
      if (b.stream) {
        res.writeHead(200, { 'content-type': 'text/event-stream', 'x-routed-via': 'groq/llama' });
        for (const w of ['Привет', ', мир']) res.write(`data: ${JSON.stringify({ choices: [{ delta: { content: w } }] })}\n\n`);
        res.write(`data: ${JSON.stringify({ choices: [], usage: { prompt_tokens: 11, completion_tokens: 7 } })}\n\n`);
        res.end('data: [DONE]\n\n');
        return;
      }
      return json(200, { id: 'x', choices: [{ message: { role: 'assistant', content: 'ok' } }], usage: { prompt_tokens: 20, completion_tokens: 5 } }, { 'x-routed-via': 'kilo/qwen' });
    }
    json(404, { error: { message: 'nope' } });
  });
  return {
    ...srv,
    requests,
    rotate(k: string) {
      key = k;
    },
  };
}

export async function startCloud(env: Record<string, string> = {}): Promise<{ app: App; url: string; close: () => Promise<void> }> {
  const cfg = loadConfig({ PORT: '0', HOST: '127.0.0.1', WEB_DIR: '/nonexistent', DOWNLOADS_DIR: '/nonexistent', ...env } as any);
  const app = createApp(cfg, { store: new Store(':memory:') });
  const port = await app.listen();
  return { app, url: `http://127.0.0.1:${port}`, close: () => app.close() };
}

export async function api(base: string, path: string, init: { method?: string; token?: string; body?: unknown; headers?: Record<string, string> } = {}) {
  const res = await fetch(base + path, {
    method: init.method ?? (init.body ? 'POST' : 'GET'),
    headers: { ...(init.body ? { 'content-type': 'application/json' } : {}), ...(init.token ? { authorization: `Bearer ${init.token}` } : {}), ...init.headers },
    body: init.body ? JSON.stringify(init.body) : undefined,
  });
  const text = await res.text();
  let json: any = null;
  try {
    json = JSON.parse(text);
  } catch {
    /* sse or text */
  }
  return { status: res.status, json, text, headers: res.headers };
}

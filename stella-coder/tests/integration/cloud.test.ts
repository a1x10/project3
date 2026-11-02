import http from 'node:http';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import type { AddressInfo } from 'node:net';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { cloudLogin, cloudLogout, cloudWhoami, normalizeCloudUrl } from '../../src/cloud/login.js';
import { isolateHome, makeProject, mockOpenAI, runtimeFor, text, type MockServer } from '../helpers/mock.js';

/** Fake Stella Cloud: device-flow auth endpoints + /v1 forwarded to a scripted OpenAI mock. */
describe('Stella Cloud login and provider', () => {
  let llm: MockServer;
  let server: http.Server;
  let url = '';
  let polls = 0;
  const loggedOut: string[] = [];
  const KEY = 'sk-stella-test-key';

  beforeAll(async () => {
    await isolateHome();
    delete process.env.STELLA_CLOUD_URL;
    delete process.env.STELLA_CLOUD_API_KEY;
    delete process.env.STELLA_MODEL;
    llm = await mockOpenAI(() => text('Привет из облака'));
    server = http.createServer(async (req, res) => {
      const json = (code: number, j: unknown) => res.writeHead(code, { 'content-type': 'application/json' }).end(JSON.stringify(j));
      let body = '';
      for await (const c of req) body += c;
      if (req.url === '/api/auth/start') {
        const b = JSON.parse(body);
        expect(b).toMatchObject({ client: 'stella', kind: 'apikey' });
        return json(200, { id: 'L1', code: 'ABCD-EFGH', link: 'https://t.me/bot?start=login_L1', interval: 0.01, expiresAt: Date.now() + 60_000 });
      }
      if (req.url?.startsWith('/api/auth/poll')) return json(200, ++polls < 3 ? { status: 'pending' } : { status: 'approved', apiKey: KEY, user: { name: 'Анна', planInfo: { name: 'Free', dailyRequests: 50 } } });
      if (req.url === '/api/auth/logout') return loggedOut.push(String(req.headers.authorization)), json(200, { ok: true });
      if (req.url === '/api/me') return req.headers.authorization === `Bearer ${KEY}` ? json(200, { user: { name: 'Анна', role: 'user', planInfo: { name: 'Free' }, usageToday: { requests: 1 } } }) : json(401, { error: { message: 'Требуется вход' } });
      if (req.url?.startsWith('/v1/')) {
        if (req.headers.authorization !== `Bearer ${KEY}`) return json(401, { error: { message: 'bad key' } });
        const r = await fetch(llm.url.replace(/\/v1$/, '') + req.url, { method: 'POST', headers: { 'content-type': 'application/json', 'x-stella-client': String(req.headers['x-stella-client'] ?? '') }, body });
        res.writeHead(r.status, { 'content-type': r.headers.get('content-type') ?? 'text/event-stream' });
        res.end(Buffer.from(await r.arrayBuffer()));
        return;
      }
      json(404, {});
    });
    await new Promise<void>((r) => server.listen(0, '127.0.0.1', r));
    url = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  });
  afterAll(async () => {
    server.closeAllConnections();
    await new Promise((r) => server.close(r));
    await llm.close();
  });

  it('normalizes server URLs', () => {
    expect(normalizeCloudUrl('ai.example.com/')).toBe('https://ai.example.com');
    expect(normalizeCloudUrl('http://h:8080/v1')).toBe('http://h:8080');
  });

  it('without login the cloud provider explains how to sign in', async () => {
    const rt = await runtimeFor(await makeProject({}), { model: 'cloud:auto' });
    await expect(rt.registry.provider('cloud')).rejects.toThrow(/stella-coder login/);
    await rt.shutdown();
  });

  it('login saves url + key, becomes the default model and talks to the gateway', async () => {
    const lines: string[] = [];
    const opened: string[] = [];
    const r = await cloudLogin(url + '/', { print: (t) => lines.push(t), openUrl: (u) => opened.push(u), sleep: async () => undefined });
    expect(r.user.name).toBe('Анна');
    expect(lines.join('\n')).toContain('ABCD-EFGH');
    expect(opened).toEqual(['https://t.me/bot?start=login_L1']);
    const creds = JSON.parse(readFileSync(path.join(process.env.STELLA_HOME!, 'credentials.json'), 'utf8'));
    expect(creds['cloud.url']).toBe(url);
    expect(creds['cloud.apiKey']).toBe(KEY);
    expect((await cloudWhoami()).user.name).toBe('Анна');

    const rt = await runtimeFor(await makeProject({}), {});
    expect(`${rt.main.model.provider}:${rt.main.model.id}`).toBe('cloud:auto');
    const res = await rt.submit('привет');
    expect(res?.text).toContain('Привет из облака');
    expect(llm.requests.at(-1)!.body.model).toBe('auto');
    expect(llm.requests.at(-1)!.headers!['x-stella-client']).toBe('stella');
    await rt.shutdown();
  });

  it('logout revokes the key on the server and removes it locally', async () => {
    expect(await cloudLogout()).toBe(true);
    expect(loggedOut).toEqual([`Bearer ${KEY}`]);
    expect((await cloudWhoami()).error).toMatch(/не выполнен вход/);
    const rt = await runtimeFor(await makeProject({}), {});
    expect(rt.main.model.provider).toBe('freellmapi'); // back to the local router default
    await rt.shutdown();
  });
});

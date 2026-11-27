import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import https from 'node:https';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { createArServer, lanAddresses, ensureCert, parseCookies } = require('../src/main/ar-server.js');

const ROOT = path.resolve(import.meta.dirname, '..');
const MODEL = path.join(ROOT, 'assets/models/mark.vrm');

let srv, base, messages, clientCounts, dir;
function make(extra = {}) {
  messages = []; clientCounts = [];
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'stella-ar-'));
  return createArServer({
    rendererDir: path.join(ROOT, 'src/renderer'), nodeModules: path.join(ROOT, 'node_modules'), certDir: dir,
    getModelFile: () => MODEL, getInfo: () => ({ persona: 'stella', name: 'Стелла', model: '/model?v=1' }),
    onMessage: (t) => messages.push(t), onClients: (n) => clientCounts.push(n), insecure: true, ...extra,
  });
}
beforeEach(async () => { srv = make(); const r = await srv.start(0); base = r.url.replace(/\/ar\/\?k=.*$/, ''); });
afterEach(() => srv.stop());

const get = (p, headers = {}) => fetch(base + p, { headers, redirect: 'manual' });
const k = () => '?k=' + encodeURIComponent(srv.token);

describe('AR-сервер: доступ', () => {
  it('ссылка содержит IP, порт и секретный ключ', () => {
    expect(srv.url).toMatch(/^http:\/\/[\d.]+:\d+\/ar\/\?k=.{20,}$/);
    expect(srv.token.length).toBeGreaterThanOrEqual(24);
  });
  it('без ключа — 403', async () => {
    expect((await get('/ar/')).status).toBe(403);
    expect((await get('/model')).status).toBe(403);
    expect((await get('/events')).status).toBe(403);
    expect((await get('/ar/?k=wrong')).status).toBe(403);
  });
  it('с ключом отдаёт страницу и ставит cookie', async () => {
    const r = await get('/ar/' + k());
    expect(r.status).toBe(200);
    expect(await r.text()).toContain('Stella AR');
    expect(r.headers.get('set-cookie')).toMatch(/stella_ar=.*HttpOnly; SameSite=Strict/);
  });
  it('дальше достаточно cookie (для import модулей)', async () => {
    const cookie = `stella_ar=${encodeURIComponent(srv.token)}`;
    const r = await get('/lib/three.module.js', { cookie });
    expect(r.status).toBe(200);
    expect(r.headers.get('content-type')).toContain('javascript');
    expect((await get('/js/avatar/avatar.js', { cookie })).status).toBe(200);
    expect((await get('/lib/addons/loaders/GLTFLoader.js', { cookie })).status).toBe(200);
    expect((await get('/lib/three-vrm.module.js', { cookie })).status).toBe(200);
  });
  it('нельзя выйти за пределы разрешённых папок', async () => {
    const cookie = `stella_ar=${encodeURIComponent(srv.token)}`;
    for (const p of ['/js/../../main/main.js', '/js/%2e%2e/%2e%2e/main/store.js', '/lib/addons/../../../package.json', '/ar/../../main/main.js']) {
      expect((await get(p, { cookie })).status, p).toBe(404);
    }
  });
  it('корень перенаправляет на страницу AR', async () => {
    const r = await get('/' + k());
    expect(r.status).toBe(302);
    expect(r.headers.get('location')).toBe('/ar/' + k());
  });
});

describe('AR-сервер: данные и события', () => {
  it('отдаёт модель персонажа', async () => {
    const r = await get('/model' + k());
    const buf = Buffer.from(await r.arrayBuffer());
    expect(buf.readUInt32LE(0)).toBe(0x46546c67);
    expect(buf.length).toBe(fs.statSync(MODEL).size);
  });
  it('информация о персонаже', async () => expect(await (await get('/api/info' + k())).json()).toMatchObject({ name: 'Стелла' }));
  it('поток событий: приветствие, рассылка, счётчик телефонов', async () => {
    const ac = new AbortController();
    const res = await fetch(base + '/events' + k(), { signal: ac.signal });
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    const next = async () => { while (!buf.includes('\n\n')) buf += dec.decode((await reader.read()).value); const i = buf.indexOf('\n\n'); const line = buf.slice(0, i); buf = buf.slice(i + 2); return JSON.parse(line.replace(/^data: /, '')); };
    expect(await next()).toMatchObject({ type: 'hello', name: 'Стелла' });
    await new Promise((r) => setTimeout(r, 50));
    expect(srv.clients).toBe(1);
    expect(srv.broadcast({ type: 'action', name: 'dance' })).toBe(1);
    expect(await next()).toEqual({ type: 'action', name: 'dance' });
    srv.broadcast({ type: 'say', text: 'Привет из компьютера', audio: null });
    expect((await next()).text).toBe('Привет из компьютера');
    ac.abort();
    await new Promise((r) => setTimeout(r, 100));
    expect(srv.clients).toBe(0);
    expect(clientCounts).toEqual([1, 0]);
  });
  it('сообщение с телефона уходит в приложение', async () => {
    const r = await fetch(base + '/api/message' + k(), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: '  Станцуй!  ' }) });
    expect(r.status).toBe(200);
    expect(messages).toEqual(['Станцуй!']);
  });
  it('пустые и битые сообщения игнорируются', async () => {
    await fetch(base + '/api/message' + k(), { method: 'POST', body: '{oops' });
    await fetch(base + '/api/message' + k(), { method: 'POST', body: JSON.stringify({ text: '   ' }) });
    expect(messages).toEqual([]);
  });
  it('повторный start возвращает тот же адрес', async () => expect((await srv.start(0)).url).toBe(srv.url));
  it('stop закрывает сервер', async () => {
    await srv.stop();
    expect(srv.url).toBe('');
    await expect(fetch(base + '/ar/' + k())).rejects.toThrow();
    srv = make(); await srv.start(0);
  });
});

describe('Сеть и сертификат', () => {
  it('домашние сети в приоритете', () => {
    const ips = lanAddresses({ a: [{ family: 'IPv4', address: '100.64.0.1', internal: false }], b: [{ family: 'IPv4', address: '192.168.1.5', internal: false }, { family: 'IPv4', address: '127.0.0.1', internal: true }], c: [{ family: 'IPv6', address: 'fe80::1', internal: false }, { family: 'IPv4', address: '10.0.0.3', internal: false }] });
    expect(ips).toEqual(['192.168.1.5', '10.0.0.3', '100.64.0.1']);
  });
  it('разбор cookie', () => expect(parseCookies('a=1; stella_ar=x%3Dy')).toEqual({ a: '1', stella_ar: 'x=y' }));
  it('сертификат создаётся с IP в SAN и кэшируется', () => {
    const d = fs.mkdtempSync(path.join(os.tmpdir(), 'cert-'));
    const c1 = ensureCert(d, ['192.168.1.5']);
    expect(c1.cert).toContain('BEGIN CERTIFICATE');
    const x = new (require('node:crypto').X509Certificate)(c1.cert);
    expect(x.subjectAltName).toContain('IP Address:192.168.1.5');
    expect(ensureCert(d, ['192.168.1.5']).cert).toBe(c1.cert);
    expect(ensureCert(d, ['10.0.0.9']).cert).not.toBe(c1.cert);
  }, 60000);
  it('HTTPS-режим работает', async () => {
    const s = make({ insecure: false });
    const r = await s.start(0);
    expect(r.url).toMatch(/^https:/);
    const status = await new Promise((resolve, reject) => https.get(r.url.replace(/\/\/[\d.]+:/, '//127.0.0.1:'), { rejectUnauthorized: false }, (res) => { res.resume(); resolve(res.statusCode); }).on('error', reject));
    expect(status).toBe(200);
    await s.stop();
  }, 60000);
});

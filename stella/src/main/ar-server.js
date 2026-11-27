'use strict';
// Локальный HTTPS-сервер для AR на телефоне: страница с персонажем, модель, события в реальном времени.
// Доступ только по секретному токену из QR-кода (персонаж может управлять компьютером — посторонним сюда нельзя).
const https = require('https');
const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');

const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.vrm': 'application/octet-stream', '.png': 'image/png', '.svg': 'image/svg+xml' };

/** IPv4-адреса компьютера в локальной сети (домашние сети — первыми). */
function lanAddresses(ifaces = os.networkInterfaces()) {
  const out = [];
  for (const list of Object.values(ifaces)) for (const a of list || []) {
    if ((a.family === 'IPv4' || a.family === 4) && !a.internal) out.push(a.address);
  }
  const rank = (ip) => (ip.startsWith('192.168.') ? 0 : ip.startsWith('10.') ? 1 : /^172\.(1[6-9]|2\d|3[01])\./.test(ip) ? 2 : 3);
  return out.sort((a, b) => rank(a) - rank(b));
}

/** Самоподписанный сертификат (кэшируется; пересоздаётся при смене IP). */
function ensureCert(dir, ips) {
  const file = path.join(dir, 'ar-cert.json');
  try {
    const c = JSON.parse(fs.readFileSync(file, 'utf8'));
    if (c.expires > Date.now() + 86400000 && ips.every((ip) => c.ips.includes(ip))) return c;
  } catch { /* создаём новый */ }
  const selfsigned = require('selfsigned');
  const pems = selfsigned.generate([{ name: 'commonName', value: 'Stella AR' }], {
    days: 825, keySize: 2048, algorithm: 'sha256',
    extensions: [{ name: 'subjectAltName', altNames: [{ type: 2, value: 'localhost' }, ...ips.map((ip) => ({ type: 7, ip }))] }],
  });
  const c = { key: pems.private, cert: pems.cert, ips, expires: Date.now() + 800 * 86400000 };
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(file, JSON.stringify(c));
  return c;
}

function parseCookies(h = '') {
  const out = {};
  for (const part of String(h).split(';')) { const i = part.indexOf('='); if (i > 0) out[part.slice(0, i).trim()] = decodeURIComponent(part.slice(i + 1).trim()); }
  return out;
}

/**
 * @param {object} o
 * @param {string} o.rendererDir папка src/renderer
 * @param {string} o.nodeModules папка node_modules
 * @param {() => string} o.getModelFile путь к текущей VRM-модели
 * @param {() => object} o.getInfo данные о персонаже
 * @param {(text:string) => void} o.onMessage сообщение с телефона
 * @param {(n:number) => void} [o.onClients]
 * @param {string} o.certDir куда сохранить сертификат
 * @param {boolean} [o.insecure] HTTP вместо HTTPS (для тестов)
 */
function createArServer(o) {
  const token = o.token || crypto.randomBytes(18).toString('base64url');
  const clients = new Set();
  let server = null, ping = null, url = '';

  const STATIC = {
    '/lib/three.module.js': path.join(o.nodeModules, 'three/build/three.module.js'),
    '/lib/three-vrm.module.js': path.join(o.nodeModules, '@pixiv/three-vrm/lib/three-vrm.module.js'),
  };
  const DIRS = [
    ['/lib/addons/', path.join(o.rendererDir, 'vendor/three-addons')],
    ['/js/', path.join(o.rendererDir, 'js')],
    ['/ar/', path.join(o.rendererDir, 'ar')],
  ];

  function resolveStatic(p) {
    if (STATIC[p]) return STATIC[p];
    for (const [prefix, dir] of DIRS) {
      if (!p.startsWith(prefix)) continue;
      const full = path.resolve(dir, '.' + p.slice(prefix.length - 1));
      if (full.startsWith(dir + path.sep) && fs.existsSync(full) && fs.statSync(full).isFile()) return full;
    }
    return null;
  }

  function authed(req, u) {
    const k = u.searchParams.get('k') || parseCookies(req.headers.cookie).stella_ar || String(req.headers['x-stella-token'] || '');
    const a = Buffer.from(sha(k)), b = Buffer.from(sha(token));
    return crypto.timingSafeEqual(a, b);
  }
  const sha = (s) => crypto.createHash('sha256').update(String(s)).digest('hex');

  function sendFile(res, file, extra = {}) {
    res.writeHead(200, { 'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-cache', ...extra });
    fs.createReadStream(file).pipe(res);
  }

  async function handler(req, res) {
    const u = new URL(req.url, 'https://x');
    res.setHeader('X-Content-Type-Options', 'nosniff');
    if (u.pathname === '/' ) { res.writeHead(302, { Location: '/ar/' + u.search }); res.end(); return; }
    if (!authed(req, u)) { res.writeHead(403, { 'Content-Type': 'text/plain; charset=utf-8' }); res.end('Нет доступа. Отсканируй QR-код в приложении Stella (Мастерская → Реальный мир).'); return; }
    const cookie = { 'Set-Cookie': `stella_ar=${encodeURIComponent(token)}; Path=/; HttpOnly; SameSite=Strict${o.insecure ? '' : '; Secure'}` };
    try {
      if (u.pathname === '/ar' || u.pathname === '/ar/') return sendFile(res, path.join(o.rendererDir, 'ar', 'index.html'), cookie);
      if (u.pathname === '/model') return sendFile(res, o.getModelFile());
      if (u.pathname === '/api/info') { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(o.getInfo())); return; }
      if (u.pathname === '/events') {
        res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', Connection: 'keep-alive', ...cookie });
        res.write(`data: ${JSON.stringify({ type: 'hello', ...o.getInfo() })}\n\n`);
        clients.add(res);
        o.onClients?.(clients.size);
        req.on('close', () => { clients.delete(res); o.onClients?.(clients.size); });
        return;
      }
      if (u.pathname === '/api/message' && req.method === 'POST') {
        let body = '';
        for await (const c of req) { body += c; if (body.length > 20000) break; }
        let text = '';
        try { text = String(JSON.parse(body).text || '').trim().slice(0, 2000); } catch { /* */ }
        if (text) o.onMessage?.(text);
        res.writeHead(200, { 'Content-Type': 'application/json' }); res.end('{"ok":true}');
        return;
      }
      const file = resolveStatic(u.pathname);
      if (file) return sendFile(res, file);
      res.writeHead(404); res.end();
    } catch (e) {
      if (!res.headersSent) { res.writeHead(500); res.end(String(e.message)); }
    }
  }

  return {
    token,
    get clients() { return clients.size; },
    get url() { return url; },
    async start(port = 8790) {
      if (server) return { url, token };
      const ips = lanAddresses();
      const host = ips[0] || '127.0.0.1';
      if (o.insecure) server = http.createServer(handler);
      else { const c = ensureCert(o.certDir, ips.length ? ips : ['127.0.0.1']); server = https.createServer({ key: c.key, cert: c.cert }, handler); }
      await new Promise((resolve, reject) => {
        server.once('error', reject);
        server.listen(port, '0.0.0.0', resolve);
      }).catch(async (e) => {
        if (e.code !== 'EADDRINUSE') throw e;
        await new Promise((resolve) => server.listen(0, '0.0.0.0', resolve));
      });
      const p = server.address().port;
      url = `${o.insecure ? 'http' : 'https'}://${host}:${p}/ar/?k=${encodeURIComponent(token)}`;
      ping = setInterval(() => { for (const c of clients) c.write(': ping\n\n'); }, 20000);
      return { url, token, ips, port: p };
    },
    broadcast(event) {
      const line = `data: ${JSON.stringify(event)}\n\n`;
      for (const c of clients) c.write(line);
      return clients.size;
    },
    async stop() {
      clearInterval(ping);
      for (const c of clients) c.end();
      clients.clear();
      if (server) { const s = server; await new Promise((r) => { s.close(() => r()); s.closeAllConnections?.(); }); }
      server = null; url = '';
      o.onClients?.(0);
    },
    _handler: handler,
  };
}

module.exports = { createArServer, lanAddresses, ensureCert, parseCookies };

// HTTP-сервер для мониторинга: /health (для Docker/uptime-мониторов) и /qr (привязка WhatsApp из браузера).
import http from 'node:http';
import { timingSafeEqual } from 'node:crypto';

function tokenOk(provided, expected) {
  if (!expected || !provided) return false;
  const a = Buffer.from(String(provided));
  const b = Buffer.from(expected);
  return a.length === b.length && timingSafeEqual(a, b);
}

const page = (title, body, refresh) => `<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">${refresh ? `<meta http-equiv="refresh" content="${refresh}">` : ''}
<title>${title}</title><style>body{font-family:system-ui,sans-serif;max-width:520px;margin:40px auto;padding:0 16px;text-align:center;color:#222}
img{width:100%;max-width:360px;image-rendering:pixelated}code{font-size:28px;letter-spacing:3px}</style></head><body>${body}</body></html>`;

export function startHealthServer({ config, wa, homework, core, logger }) {
  if (!config.http.port) return null;
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    try {
      if (url.pathname === '/health') {
        const waDownFor = wa.isOpen ? 0 : Date.now() - (wa.lastDisconnect?.at || core.startedAt);
        // «нездоров», если WhatsApp не на связи дольше 10 минут (и бот уже был привязан)
        const healthy = wa.isOpen || wa.status === 'qr' || waDownFor < 10 * 60 * 1000;
        const s = homework.status();
        res.writeHead(healthy ? 200 : 503, { 'Content-Type': 'application/json; charset=utf-8' });
        res.end(JSON.stringify({
          status: healthy ? 'ok' : 'degraded',
          whatsapp: wa.status,
          uptimeSec: Math.round((Date.now() - core.startedAt) / 1000),
          bilimLastSync: s.lastSuccessAt ? new Date(s.lastSuccessAt).toISOString() : null,
          bilimError: s.lastError,
          queue: wa.queue.length,
          groups: core.targets().length,
        }));
        return;
      }
      if (url.pathname === '/qr') {
        if (!tokenOk(url.searchParams.get('token'), config.http.token)) {
          res.writeHead(403, { 'Content-Type': 'text/plain; charset=utf-8' });
          res.end('Доступ запрещён. Задайте HTTP_TOKEN в .env и откройте /qr?token=ВАШ_ТОКЕН');
          return;
        }
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
        if (wa.isOpen) {
          res.end(page('WhatsApp подключён', `<h2>✅ WhatsApp подключён</h2><p>${wa.me?.id || ''}</p>`));
        } else if (wa.pairingCode) {
          res.end(page('Код привязки', `<h2>Код для привязки</h2><code>${wa.pairingCode}</code><p>WhatsApp → Связанные устройства → Привязка устройства → «Привязать по номеру телефона»</p>`, 20));
        } else if (wa.qr) {
          res.end(page('QR для WhatsApp', `<h2>Отсканируйте в WhatsApp</h2><p>Настройки → Связанные устройства → Привязка устройства</p><img src="${await wa.qrDataUrl()}" alt="QR"><p>Страница обновляется сама</p>`, 15));
        } else {
          res.end(page('Подключение…', `<h2>Подключаюсь к WhatsApp… (${wa.status})</h2>`, 5));
        }
        return;
      }
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('Not found');
    } catch (error) {
      logger.error({ err: error }, 'HTTP error');
      res.writeHead(500);
      res.end('error');
    }
  });
  server.on('error', (error) => logger.error({ err: error.message }, 'HTTP-сервер не запустился'));
  server.listen(config.http.port, config.http.host, () => logger.info(`HTTP: http://${config.http.host}:${config.http.port}/health`));
  return server;
}

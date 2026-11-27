// Поддельный OpenRouter для сквозных тестов: отвечает стримом SSE по сценарию.
import http from 'node:http';

export function startMockOpenRouter(port = 0) {
  const requests = [];
  const server = http.createServer(async (req, res) => {
    let body = '';
    for await (const c of req) body += c;
    if (req.url.endsWith('/models')) {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ data: [{ id: 'mock/tool-model', name: 'Mock', supported_parameters: ['tools'], pricing: { prompt: '0', completion: '0' } }] }));
      return;
    }
    const json = JSON.parse(body || '{}');
    requests.push(json);
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    const send = (o) => res.write(`data: ${JSON.stringify(o)}\n\n`);
    const msgs = json.messages || [];
    const last = msgs[msgs.length - 1];
    const lastUser = [...msgs].reverse().find((m) => m.role === 'user');
    const userText = typeof lastUser?.content === 'string' ? lastUser.content : '';
    res.write(': OPENROUTER PROCESSING\n\n');
    if (last?.role === 'tool') {
      const text = `[happy][dance] Готово! Результат: ${String(last.content).split('\n').pop().slice(0, 60)}`;
      for (const ch of text.match(/.{1,6}/gs)) { send({ choices: [{ delta: { content: ch } }] }); await new Promise((r) => setTimeout(r, 15)); }
      send({ choices: [{ delta: {}, finish_reason: 'stop' }] });
    } else if (/команд/i.test(userText)) {
      send({ choices: [{ delta: { content: '[think] Сейчас выполню.' } }] });
      send({ choices: [{ delta: { tool_calls: [{ index: 0, id: 'call_e2e', type: 'function', function: { name: 'run_command', arguments: '{"command":' } }] } }] });
      send({ choices: [{ delta: { tool_calls: [{ index: 0, function: { arguments: '"echo hello-from-stella"}' } }] } }] });
      send({ choices: [{ delta: {}, finish_reason: 'tool_calls' }] });
    } else {
      const text = '[happy][wave] Привет! Я Стелла. Рада познакомиться! Чем займёмся сегодня?';
      for (const ch of text.match(/.{1,5}/gs)) { send({ choices: [{ delta: { content: ch } }] }); await new Promise((r) => setTimeout(r, 15)); }
      send({ choices: [{ delta: {}, finish_reason: 'stop' }] });
    }
    res.end('data: [DONE]\n\n');
  });
  return new Promise((resolve) => server.listen(port, '127.0.0.1', () => resolve({ server, port: server.address().port, requests })));
}

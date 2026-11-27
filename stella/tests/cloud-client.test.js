// Связка приложения с сервером Stella Cloud: настоящий сервер + клиентские функции.
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import http from 'node:http';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { createApp } = require('../server/server.js');
const llm = require('../src/main/llm.js');
const voice = require('../src/main/voice.js');

let server, base, token;
beforeAll(async () => {
  const fetchImpl = async (url, init = {}) => {
    if (url.endsWith('/chat/completions')) {
      const b = JSON.parse(init.body);
      const tool = b.tools?.length && !b.messages.some((m) => m.role === 'tool');
      const ev = tool
        ? [{ choices: [{ delta: { tool_calls: [{ index: 0, id: 'c1', function: { name: 'get_datetime', arguments: '{}' } }] } }] }, { choices: [{ delta: {}, finish_reason: 'tool_calls' }] }]
        : [{ choices: [{ delta: { content: '[happy] Облако работает!' } }] }, { choices: [{ delta: {}, finish_reason: 'stop' }] }];
      return new Response(ev.map((e) => `data: ${JSON.stringify(e)}\n\n`).join('') + 'data: [DONE]\n\n', { headers: { 'content-type': 'text/event-stream' } });
    }
    if (url.endsWith('/models')) return new Response(JSON.stringify({ data: [{ id: 'openai/gpt-4o-mini', supported_parameters: ['tools'], pricing: {} }] }));
    if (url.includes('/text-to-speech/')) return new Response(new Uint8Array([1, 2]), { headers: { 'content-type': 'audio/mpeg' } });
    if (url.endsWith('/speech-to-text')) {
      expect(init.headers['Content-Type']).toMatch(/^multipart\/form-data; boundary=/);
      return new Response(JSON.stringify({ text: ' Марк, привет ' }));
    }
    if (url.endsWith('/voices')) return new Response(JSON.stringify({ voices: [{ voice_id: 'v', name: 'Adam', labels: { gender: 'male' } }] }));
    return new Response('', { status: 404 });
  };
  const app = createApp({ dataDir: fs.mkdtempSync(path.join(os.tmpdir(), 'sc-')), adminPassword: 'a', openrouterKey: 'k', elevenKey: 'e', fetch: fetchImpl });
  server = http.createServer(app.handler);
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  base = `http://127.0.0.1:${server.address().port}`;
  token = (await (await fetch(base + '/api/auth/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: 'client', password: 'secret1' }) })).json()).token;
});
afterAll(() => new Promise((r) => server.close(r)));

describe('Приложение через Stella Cloud', () => {
  it('агентный цикл с инструментами работает через сервер', async () => {
    const r = await llm.runAgent({ apiKey: token, baseUrl: base + '/api', provider: 'cloud', model: 'openai/gpt-4o-mini', systemPrompt: 's', history: [{ role: 'user', content: 'время?' }], tools: [{ type: 'function', function: { name: 'get_datetime' } }], executeTool: async () => ({ ok: true, output: '12:00' }) });
    expect(r.text).toBe('[happy] Облако работает!');
    expect(r.steps).toBe(2);
  });
  it('ошибки сервера понятны пользователю', async () => {
    await expect(llm.streamChat({ apiKey: 'bad', baseUrl: base + '/api', provider: 'cloud', model: 'x', messages: [] })).rejects.toThrow(/Stella Cloud: Сессия истекла/);
  });
  it('без входа — подсказка про Stella Cloud', async () => {
    await expect(llm.streamChat({ apiKey: '', provider: 'cloud', model: 'x', messages: [] })).rejects.toThrow(/Войдите в Stella Cloud/);
  });
  it('список моделей через сервер', async () => {
    const m = await llm.listModels({ baseUrl: base + '/api', apiKey: token });
    expect(m[0]).toMatchObject({ id: 'openai/gpt-4o-mini', tools: true });
  });
  it('озвучка через сервер', async () => {
    const b = await voice.cloudSynthesize({ base, token, voiceId: 'v', text: '[wave] Привет!', modelId: 'm', speed: 1 });
    expect([...b]).toEqual([1, 2]);
  });
  it('распознавание через сервер (multipart)', async () => {
    expect(await voice.cloudTranscribe({ base, token, audio: Buffer.from([0, 1, 2]), language: 'rus' })).toBe('Марк, привет');
  });
  it('голоса через сервер', async () => {
    expect((await voice.cloudVoices({ base, token }))[0]).toMatchObject({ id: 'v', name: 'Adam', gender: 'male' });
  });
  it('ошибка лимита из облака', async () => {
    await expect(voice.cloudSynthesize({ base, token: 'bad', voiceId: 'v', text: 'x' })).rejects.toThrow(/Stella Cloud/);
  });
});

import { describe, it, expect, vi } from 'vitest';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { SSEParser, mergeToolCallDeltas, safeJson, describeHttpError, streamChat, runAgent, listModels, trimHistory } = require('../src/main/llm.js');

/** Ответ fetch со стримом SSE, разбитым на произвольные куски. */
function sseResponse(events, { chunkSize = 7 } = {}) {
  const text = events.map((e) => (typeof e === 'string' ? e : `data: ${JSON.stringify(e)}\n\n`)).join('') + 'data: [DONE]\n\n';
  const bytes = new TextEncoder().encode(text);
  let i = 0;
  return {
    ok: true, status: 200,
    body: { getReader: () => ({ read: async () => (i >= bytes.length ? { done: true } : { done: false, value: bytes.slice(i, (i += chunkSize)) }) }) },
  };
}
const tokenEvents = (text) => [...text].map((c) => ({ choices: [{ delta: { content: c } }] })).concat([{ choices: [{ delta: {}, finish_reason: 'stop' }] }]);
const toolEvents = (name, args, id = 'call_1') => {
  const s = JSON.stringify(args);
  return [
    { choices: [{ delta: { tool_calls: [{ index: 0, id, type: 'function', function: { name, arguments: '' } }] } }] },
    { choices: [{ delta: { tool_calls: [{ index: 0, function: { arguments: s.slice(0, 5) } }] } }] },
    { choices: [{ delta: { tool_calls: [{ index: 0, function: { arguments: s.slice(5) } }] } }] },
    { choices: [{ delta: {}, finish_reason: 'tool_calls' }] },
  ];
};

describe('SSE парсер', () => {
  it('собирает события, разорванные посреди строки', () => {
    const p = new SSEParser();
    expect(p.push('data: {"a"')).toEqual([]);
    expect(p.push(':1}\n\ndata: {"b":2}\n')).toEqual([{ a: 1 }, { b: 2 }]);
  });
  it('пропускает комментарии OpenRouter и пустые строки', () => {
    const p = new SSEParser();
    expect(p.push(': OPENROUTER PROCESSING\n\n\ndata: {"x":1}\n')).toEqual([{ x: 1 }]);
  });
  it('понимает [DONE] и \\r\\n', () => {
    const p = new SSEParser();
    expect(p.push('data: {"x":1}\r\ndata: [DONE]\r\n')).toEqual([{ x: 1 }]);
    expect(p.done).toBe(true);
  });
  it('игнорирует мусор', () => expect(new SSEParser().push('data: not json\nevent: ping\n')).toEqual([]));
});

describe('Сборка tool_calls', () => {
  it('склеивает аргументы по индексу', () => {
    const acc = [];
    mergeToolCallDeltas(acc, [{ index: 0, id: 'a', function: { name: 'read_', arguments: '{"pa' } }]);
    mergeToolCallDeltas(acc, [{ index: 0, function: { name: 'file', arguments: 'th":"x"}' } }, { index: 1, id: 'b', function: { name: 'wait', arguments: '{}' } }]);
    expect(acc).toEqual([
      { id: 'a', type: 'function', function: { name: 'read_file', arguments: '{"path":"x"}' } },
      { id: 'b', type: 'function', function: { name: 'wait', arguments: '{}' } },
    ]);
  });
  it('safeJson: пусто, лишняя запятая, мусор', () => {
    expect(safeJson('')).toEqual({});
    expect(safeJson('{"a":1,}')).toEqual({ a: 1 });
    expect(safeJson('{oops')).toEqual({ __raw: '{oops' });
  });
});

describe('Ошибки HTTP', () => {
  it('401 — неверный ключ', () => { const e = describeHttpError(401, '{"error":{"message":"No auth"}}'); expect(e.message).toMatch(/Неверный ключ/); expect(e.status).toBe(401); expect(e.raw).toBe('No auth'); });
  it('402 — баланс', () => expect(describeHttpError(402, 'x').message).toMatch(/баланс/));
  it('429 — лимит', () => expect(describeHttpError(429, 'x').message).toMatch(/Слишком много/));
  it('неизвестный статус', () => expect(describeHttpError(418, 'teapot').message).toMatch(/Ошибка OpenRouter \(418\)/));
});

describe('streamChat', () => {
  it('стримит токены и отправляет правильный запрос', async () => {
    const fetchImpl = vi.fn(async () => sseResponse(tokenEvents('Привет!')));
    const tokens = [];
    const r = await streamChat({ apiKey: 'k', model: 'm/x', messages: [{ role: 'user', content: 'hi' }], tools: [{ type: 'function', function: { name: 't' } }], onToken: (t) => tokens.push(t), fetchImpl });
    expect(r.content).toBe('Привет!');
    expect(tokens.join('')).toBe('Привет!');
    expect(r.finishReason).toBe('stop');
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toMatch(/\/chat\/completions$/);
    expect(init.headers.Authorization).toBe('Bearer k');
    const body = JSON.parse(init.body);
    expect(body).toMatchObject({ model: 'm/x', stream: true, tool_choice: 'auto' });
    expect(body.tools).toHaveLength(1);
  });
  it('без инструментов не шлёт tools', async () => {
    const fetchImpl = vi.fn(async () => sseResponse(tokenEvents('ok')));
    await streamChat({ apiKey: 'k', model: 'm', messages: [], fetchImpl });
    expect(JSON.parse(fetchImpl.mock.calls[0][1].body)).not.toHaveProperty('tools');
  });
  it('собирает вызов инструмента из стрима', async () => {
    const r = await streamChat({ apiKey: 'k', model: 'm', messages: [], fetchImpl: async () => sseResponse(toolEvents('read_file', { path: '~/a.txt' })) });
    expect(r.toolCalls[0].function).toEqual({ name: 'read_file', arguments: '{"path":"~/a.txt"}' });
  });
  it('работает с ответом без стрима (text)', async () => {
    const fetchImpl = async () => ({ ok: true, text: async () => 'data: {"choices":[{"delta":{"content":"A"}}]}\n\ndata: [DONE]\n' });
    expect((await streamChat({ apiKey: 'k', model: 'm', messages: [], fetchImpl })).content).toBe('A');
  });
  it('без ключа — понятная ошибка', async () => { await expect(streamChat({ model: 'm', messages: [] })).rejects.toThrow(/ключ OpenRouter/); });
  it('HTTP ошибка', async () => {
    await expect(streamChat({ apiKey: 'k', model: 'm', messages: [], fetchImpl: async () => ({ ok: false, status: 401, text: async () => 'bad' }) })).rejects.toThrow(/Неверный ключ/);
  });
  it('ошибка внутри стрима', async () => {
    await expect(streamChat({ apiKey: 'k', model: 'm', messages: [], fetchImpl: async () => sseResponse([{ error: { code: 502, message: 'down' } }]) })).rejects.toThrow(/502/);
  });
  it('собирает usage', async () => {
    const r = await streamChat({ apiKey: 'k', model: 'm', messages: [], fetchImpl: async () => sseResponse([...tokenEvents('x'), { choices: [], usage: { total_tokens: 9 } }]) });
    expect(r.usage).toEqual({ total_tokens: 9 });
  });
});

describe('Агентный цикл', () => {
  it('выполняет инструмент и продолжает диалог', async () => {
    const responses = [sseResponse(toolEvents('system_info', {})), sseResponse(tokenEvents('[happy] Готово!'))];
    const fetchImpl = vi.fn(async () => responses.shift());
    const executeTool = vi.fn(async () => ({ ok: true, output: 'Windows 11' }));
    const starts = [], ends = [];
    const r = await runAgent({ apiKey: 'k', model: 'm', systemPrompt: 'sys', history: [{ role: 'user', content: 'инфо' }], tools: [{}], executeTool, fetchImpl, onToolStart: (t) => starts.push(t), onToolEnd: (t) => ends.push(t) });
    expect(r.text).toBe('[happy] Готово!');
    expect(r.steps).toBe(2);
    expect(executeTool).toHaveBeenCalledWith({ id: 'call_1', name: 'system_info', args: {} });
    expect(starts).toHaveLength(1); expect(ends[0].ok).toBe(true);
    expect(r.newMessages.map((m) => m.role)).toEqual(['assistant', 'tool', 'assistant']);
    expect(r.newMessages[1]).toMatchObject({ tool_call_id: 'call_1', content: 'Windows 11' });
    const second = JSON.parse(fetchImpl.mock.calls[1][1].body);
    expect(second.messages[0]).toEqual({ role: 'system', content: 'sys' });
    expect(second.messages.at(-1).role).toBe('tool');
  });
  it('скриншот добавляется как картинка, но не в историю', async () => {
    const responses = [sseResponse(toolEvents('take_screenshot', {})), sseResponse(tokenEvents('Вижу рабочий стол'))];
    const fetchImpl = vi.fn(async () => responses.shift());
    const r = await runAgent({ apiKey: 'k', model: 'm', systemPrompt: 's', history: [], tools: [{}], fetchImpl, executeTool: async () => ({ ok: true, output: 'shot', image: 'data:image/jpeg;base64,AA' }) });
    const second = JSON.parse(fetchImpl.mock.calls[1][1].body);
    expect(second.messages.at(-1).content[1]).toEqual({ type: 'image_url', image_url: { url: 'data:image/jpeg;base64,AA' } });
    expect(JSON.stringify(r.newMessages)).not.toContain('base64');
  });
  it('исключение в инструменте превращается в ошибку для модели', async () => {
    const responses = [sseResponse(toolEvents('x', {})), sseResponse(tokenEvents('Не вышло'))];
    const r = await runAgent({ apiKey: 'k', model: 'm', systemPrompt: 's', history: [], tools: [{}], fetchImpl: async () => responses.shift(), executeTool: async () => { throw new Error('сломалось'); } });
    expect(r.newMessages[1].content).toBe('Ошибка: сломалось');
  });
  it('если модель не умеет инструменты — повторяет без них', async () => {
    const calls = [];
    const fetchImpl = async (u, init) => { const b = JSON.parse(init.body); calls.push(b); return b.tools ? { ok: false, status: 404, text: async () => '{"error":{"message":"No endpoints found that support tool use"}}' } : sseResponse(tokenEvents('ok')); };
    const warn = vi.fn();
    const r = await runAgent({ apiKey: 'k', model: 'm', systemPrompt: 's', history: [], tools: [{}], fetchImpl, executeTool: async () => ({}), onWarning: warn });
    expect(r.text).toBe('ok');
    expect(calls).toHaveLength(2);
    expect(warn).toHaveBeenCalled();
  });
  it('останавливается после maxSteps', async () => {
    const fetchImpl = async () => sseResponse(toolEvents('wait', { seconds: 0 }));
    const r = await runAgent({ apiKey: 'k', model: 'm', systemPrompt: 's', history: [], tools: [{}], fetchImpl, executeTool: async () => ({ ok: true, output: '' }), maxSteps: 3 });
    expect(r.truncated).toBe(true);
    expect(r.steps).toBe(3);
  });
  it('уважает отмену', async () => {
    const ac = new AbortController(); ac.abort();
    await expect(runAgent({ apiKey: 'k', model: 'm', systemPrompt: 's', history: [], signal: ac.signal, executeTool: async () => ({}) })).rejects.toThrow(/Отменено/);
  });
  it('несколько инструментов за шаг выполняются по порядку', async () => {
    const ev = [
      { choices: [{ delta: { tool_calls: [{ index: 0, id: 'a', function: { name: 'one', arguments: '{}' } }, { index: 1, id: 'b', function: { name: 'two', arguments: '{}' } }] } }] },
      { choices: [{ delta: {}, finish_reason: 'tool_calls' }] },
    ];
    const responses = [sseResponse(ev), sseResponse(tokenEvents('done'))];
    const order = [];
    await runAgent({ apiKey: 'k', model: 'm', systemPrompt: 's', history: [], tools: [{}], fetchImpl: async () => responses.shift(), executeTool: async (c) => { order.push(c.name); return { ok: true, output: c.name }; } });
    expect(order).toEqual(['one', 'two']);
  });
});

describe('Список моделей и история', () => {
  it('listModels разбирает возможности и цены', async () => {
    const fetchImpl = async () => ({ ok: true, json: async () => ({ data: [
      { id: 'b/vision', name: 'B', supported_parameters: ['tools'], architecture: { input_modalities: ['text', 'image'] }, pricing: { prompt: '0.000001', completion: '0.000002' } },
      { id: 'a/free', name: 'A', supported_parameters: [], architecture: { modality: 'text->text' }, pricing: { prompt: '0', completion: '0' } },
    ] }) });
    const m = await listModels({ fetchImpl });
    expect(m.map((x) => x.id)).toEqual(['a/free', 'b/vision']);
    expect(m[0]).toMatchObject({ tools: false, vision: false, free: true });
    expect(m[1]).toMatchObject({ tools: true, vision: true, free: false, promptPrice: 1, completionPrice: 2 });
  });
  it('listModels: ошибка', async () => { await expect(listModels({ fetchImpl: async () => ({ ok: false, status: 500 }) })).rejects.toThrow(/500/); });
  it('trimHistory не начинает с сообщения tool', () => {
    const h = [{ role: 'user' }, { role: 'assistant' }, { role: 'tool' }, { role: 'tool' }, { role: 'assistant' }, { role: 'user' }];
    const t = trimHistory(h, 4);
    expect(t[0].role).not.toBe('tool');
    expect(t.at(-1).role).toBe('user');
  });
  it('trimHistory не трогает короткую историю', () => expect(trimHistory([{ role: 'user' }], 40)).toHaveLength(1));
});

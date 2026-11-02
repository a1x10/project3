import http from 'node:http';
import { promises as fs } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import type { AddressInfo } from 'node:net';
import { Runtime, type RuntimeOptions } from '../../src/agent/runtime.js';
import type { Settings } from '../../src/config/settings.js';

/**
 * Scripted LLM endpoints speaking the real wire protocols (OpenAI chat-completions SSE,
 * Anthropic Messages SSE, Gemini streamGenerateContent SSE). The "model" is a test script that
 * decides the next reply from the actual request (including real tool results); the tools
 * themselves execute for real against temporary projects.
 */
export interface ToolCallSpec {
  name: string;
  args: Record<string, unknown>;
  id?: string;
}
export type Reply = { text?: string; tools?: ToolCallSpec[]; stop?: 'end_turn' | 'max_tokens' | 'refusal'; usage?: { input: number; output: number } } | { status: number; error: string; headers?: Record<string, string> };

export interface MockRequest {
  body: any;
  index: number;
  /** Provider-neutral view: last user text and tool results in the request. */
  lastUserText: string;
  toolResults: Array<{ id: string; content: string; isError: boolean }>;
  system: string;
  toolNames: string[];
}

export type Script = (req: MockRequest) => Reply | Promise<Reply>;

export interface MockServer {
  url: string;
  requests: MockRequest[];
  close(): Promise<void>;
}

function listen(handler: http.RequestListener): Promise<{ server: http.Server; url: string }> {
  return new Promise((resolve) => {
    const server = http.createServer(handler);
    server.listen(0, '127.0.0.1', () => resolve({ server, url: `http://127.0.0.1:${(server.address() as AddressInfo).port}` }));
  });
}

async function readBody(req: http.IncomingMessage): Promise<any> {
  const chunks: Buffer[] = [];
  for await (const c of req) chunks.push(c as Buffer);
  const t = Buffer.concat(chunks).toString('utf8');
  return t ? JSON.parse(t) : {};
}

function chunks(s: string, n = 3): string[] {
  if (!s) return [];
  const size = Math.max(1, Math.ceil(s.length / n));
  const out: string[] = [];
  for (let i = 0; i < s.length; i += size) out.push(s.slice(i, i + size));
  return out;
}

let callSeq = 0;

// ---------------- OpenAI-compatible ----------------
export async function mockOpenAI(script: Script): Promise<MockServer> {
  const requests: MockRequest[] = [];
  const { server, url } = await listen(async (req, res) => {
    if (req.method !== 'POST' || !req.url?.endsWith('/chat/completions')) {
      res.writeHead(404).end();
      return;
    }
    const body = await readBody(req);
    const msgs: any[] = body.messages ?? [];
    const lastUser = [...msgs].reverse().find((m) => m.role === 'user');
    const trailingTools: any[] = [];
    for (let i = msgs.length - 1; i >= 0 && msgs[i].role === 'tool'; i--) trailingTools.unshift(msgs[i]);
    const mr: MockRequest = {
      body,
      index: requests.length,
      lastUserText: typeof lastUser?.content === 'string' ? lastUser.content : (lastUser?.content ?? []).map((p: any) => p.text ?? '').join(''),
      toolResults: trailingTools.map((t) => ({ id: t.tool_call_id, content: String(t.content).replace(/^ERROR: /, ''), isError: String(t.content).startsWith('ERROR: ') })),
      system: msgs.find((m) => m.role === 'system')?.content ?? '',
      toolNames: (body.tools ?? []).map((t: any) => t.function.name),
    };
    requests.push(mr);
    const reply = await script(mr);
    if ('status' in reply) {
      res.writeHead(reply.status, { 'content-type': 'application/json', ...(reply.headers ?? {}) }).end(JSON.stringify({ error: { message: reply.error } }));
      return;
    }
    res.writeHead(200, { 'content-type': 'text/event-stream' });
    const send = (o: unknown) => res.write(`data: ${JSON.stringify(o)}\n\n`);
    for (const piece of chunks(reply.text ?? '')) send({ choices: [{ index: 0, delta: { content: piece } }] });
    (reply.tools ?? []).forEach((t, idx) => {
      const id = t.id ?? `call_${++callSeq}`;
      const args = JSON.stringify(t.args);
      send({ choices: [{ index: 0, delta: { tool_calls: [{ index: idx, id, type: 'function', function: { name: t.name, arguments: '' } }] } }] });
      for (const a of chunks(args, 2)) send({ choices: [{ index: 0, delta: { tool_calls: [{ index: idx, function: { arguments: a } }] } }] });
    });
    const finish = reply.tools?.length ? 'tool_calls' : reply.stop === 'max_tokens' ? 'length' : 'stop';
    send({ choices: [{ index: 0, delta: {}, finish_reason: finish }] });
    send({ choices: [], usage: { prompt_tokens: reply.usage?.input ?? 1000, completion_tokens: reply.usage?.output ?? 50 } });
    res.write('data: [DONE]\n\n');
    res.end();
  });
  return { url: url + '/v1', requests, close: () => new Promise((r) => server.close(() => r())) };
}

// ---------------- Anthropic Messages ----------------
export async function mockAnthropic(script: Script): Promise<MockServer> {
  const requests: MockRequest[] = [];
  const { server, url } = await listen(async (req, res) => {
    if (req.method !== 'POST' || !req.url?.startsWith('/v1/messages')) {
      res.writeHead(404).end();
      return;
    }
    const body = await readBody(req);
    const msgs: any[] = body.messages ?? [];
    const last = msgs[msgs.length - 1];
    const blocks: any[] = typeof last?.content === 'string' ? [{ type: 'text', text: last.content }] : last?.content ?? [];
    const mr: MockRequest = {
      body,
      index: requests.length,
      lastUserText: blocks.filter((b) => b.type === 'text').map((b) => b.text).join(''),
      toolResults: blocks.filter((b) => b.type === 'tool_result').map((b) => ({ id: b.tool_use_id, content: typeof b.content === 'string' ? b.content : JSON.stringify(b.content), isError: !!b.is_error })),
      system: typeof body.system === 'string' ? body.system : (body.system ?? []).map((s: any) => s.text).join(''),
      toolNames: (body.tools ?? []).map((t: any) => t.name),
    };
    requests.push(mr);
    const reply = await script(mr);
    if ('status' in reply) {
      res.writeHead(reply.status, { 'content-type': 'application/json', ...(reply.headers ?? {}) }).end(JSON.stringify({ type: 'error', error: { type: reply.status === 429 ? 'rate_limit_error' : 'api_error', message: reply.error } }));
      return;
    }
    res.writeHead(200, { 'content-type': 'text/event-stream' });
    const send = (event: string, data: unknown) => res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
    const model = body.model;
    send('message_start', { type: 'message_start', message: { id: 'msg_' + ++callSeq, type: 'message', role: 'assistant', model, content: [], stop_reason: null, stop_sequence: null, usage: { input_tokens: reply.usage?.input ?? 1200, output_tokens: 1, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 } } });
    let index = 0;
    // a thinking block with a signature, to verify it is replayed unchanged
    send('content_block_start', { type: 'content_block_start', index, content_block: { type: 'thinking', thinking: '', signature: '' } });
    send('content_block_delta', { type: 'content_block_delta', index, delta: { type: 'signature_delta', signature: `sig-${mr.index}` } });
    send('content_block_stop', { type: 'content_block_stop', index });
    index++;
    if (reply.text) {
      send('content_block_start', { type: 'content_block_start', index, content_block: { type: 'text', text: '' } });
      for (const p of chunks(reply.text)) send('content_block_delta', { type: 'content_block_delta', index, delta: { type: 'text_delta', text: p } });
      send('content_block_stop', { type: 'content_block_stop', index });
      index++;
    }
    for (const t of reply.tools ?? []) {
      const id = t.id ?? `toolu_${++callSeq}`;
      send('content_block_start', { type: 'content_block_start', index, content_block: { type: 'tool_use', id, name: t.name, input: {} } });
      for (const p of chunks(JSON.stringify(t.args), 3)) send('content_block_delta', { type: 'content_block_delta', index, delta: { type: 'input_json_delta', partial_json: p } });
      send('content_block_stop', { type: 'content_block_stop', index });
      index++;
    }
    const stop = reply.tools?.length ? 'tool_use' : reply.stop ?? 'end_turn';
    send('message_delta', { type: 'message_delta', delta: { stop_reason: stop, stop_sequence: null }, usage: { output_tokens: reply.usage?.output ?? 40 } });
    send('message_stop', { type: 'message_stop' });
    res.end();
  });
  return { url, requests, close: () => new Promise((r) => server.close(() => r())) };
}

// ---------------- Gemini ----------------
export async function mockGemini(script: Script): Promise<MockServer> {
  const requests: MockRequest[] = [];
  const { server, url } = await listen(async (req, res) => {
    if (req.method !== 'POST' || !req.url?.includes(':streamGenerateContent')) {
      res.writeHead(404).end();
      return;
    }
    const body = await readBody(req);
    const contents: any[] = body.contents ?? [];
    const last = contents[contents.length - 1];
    const mr: MockRequest = {
      body,
      index: requests.length,
      lastUserText: (last?.parts ?? []).filter((p: any) => p.text).map((p: any) => p.text).join(''),
      toolResults: (last?.parts ?? []).filter((p: any) => p.functionResponse).map((p: any) => ({ id: p.functionResponse.name, content: String(p.functionResponse.response.result ?? p.functionResponse.response.error), isError: 'error' in p.functionResponse.response })),
      system: body.systemInstruction?.parts?.[0]?.text ?? '',
      toolNames: (body.tools?.[0]?.functionDeclarations ?? []).map((f: any) => f.name),
    };
    requests.push(mr);
    const reply = await script(mr);
    if ('status' in reply) {
      res.writeHead(reply.status).end(JSON.stringify({ error: { message: reply.error } }));
      return;
    }
    res.writeHead(200, { 'content-type': 'text/event-stream' });
    const send = (o: unknown) => res.write(`data: ${JSON.stringify(o)}\n\n`);
    for (const p of chunks(reply.text ?? '')) send({ candidates: [{ content: { role: 'model', parts: [{ text: p }] } }] });
    if (reply.tools?.length) send({ candidates: [{ content: { role: 'model', parts: reply.tools.map((t) => ({ functionCall: { name: t.name, args: t.args } })) } }] });
    send({ candidates: [{ content: { role: 'model', parts: [] }, finishReason: 'STOP' }], usageMetadata: { promptTokenCount: reply.usage?.input ?? 900, candidatesTokenCount: reply.usage?.output ?? 30 } });
    res.end();
  });
  return { url, requests, close: () => new Promise((r) => server.close(() => r())) };
}

// ---------------- Temp projects / runtime ----------------
export async function tempDir(prefix = 'stella-test-'): Promise<string> {
  return fs.realpath(await fs.mkdtemp(path.join(os.tmpdir(), prefix)));
}

export async function makeProject(files: Record<string, string>): Promise<string> {
  const dir = await tempDir('stella-proj-');
  for (const [rel, content] of Object.entries(files)) {
    const p = path.join(dir, rel);
    await fs.mkdir(path.dirname(p), { recursive: true });
    await fs.writeFile(p, content);
  }
  return dir;
}

/** Isolated STELLA_HOME per test so sessions/memory/credentials never touch the real home. */
export async function isolateHome(): Promise<string> {
  const home = await tempDir('stella-home-');
  process.env.STELLA_HOME = home;
  process.env.STELLA_NO_AUDIT = '';
  return home;
}

export function openaiSettings(url: string, extra: Settings = {}): Settings {
  return {
    providers: { mock: { type: 'openai', baseUrl: url, apiKey: 'test-key', models: [{ id: 'scripted', name: 'Scripted Mock', contextWindow: 200_000, maxOutput: 8000, inputPrice: 1, outputPrice: 2 }] } },
    model: 'mock:scripted',
    ...extra,
  };
}

export async function runtimeFor(cwd: string, settings: Settings, opts: Partial<RuntimeOptions> = {}): Promise<Runtime> {
  return Runtime.create({ cwd, settings, connectMcp: false, ...opts });
}

export const text = (t: string): Reply => ({ text: t });
export const call = (name: string, args: Record<string, unknown>, textBefore?: string): Reply => ({ text: textBefore, tools: [{ name, args }] });

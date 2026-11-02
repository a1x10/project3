import { spawn, type ChildProcess } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { McpManager } from '../../src/mcp/manager.js';
import { call, isolateHome, makeProject, mockOpenAI, openaiSettings, runtimeFor, text, type MockServer } from '../helpers/mock.js';
import { runSlash } from '../../src/cli/commands.js';

const fixture = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../fixtures/mcp-server.mjs');
let server: MockServer | null = null;
let child: ChildProcess | null = null;
beforeEach(async () => {
  await isolateHome();
});
afterEach(async () => {
  await server?.close();
  child?.kill();
  server = null;
  child = null;
});

describe('MCP', () => {
  it('connects to a stdio server, discovers tools and calls them', async () => {
    const m = new McpManager(process.cwd());
    m.register('calc', { type: 'stdio', command: process.execPath, args: [fixture] }, 'user', true);
    const st = await m.connect('calc');
    expect(st.status).toBe('connected');
    expect(st.tools.map((t) => t.name).sort()).toEqual(['add', 'fail']);
    const tools = m.tools();
    expect(tools.map((t) => t.name)).toContain('mcp__calc__add');
    expect(tools[0]!.inputJsonSchema).toBeTruthy();
    expect((await m.callTool('calc', 'add', { a: 2, b: 40 })).content).toBe('42');
    expect((await m.callTool('calc', 'fail', {})).isError).toBe(true);
    await m.closeAll();
  });

  it('connects over Streamable HTTP with auth headers from env', async () => {
    child = spawn(process.execPath, [fixture, '--http', '0'], { stdio: ['ignore', 'pipe', 'inherit'] });
    const port = await new Promise<number>((resolve) => child!.stdout!.on('data', (d) => /LISTENING (\d+)/.test(String(d)) && resolve(Number(/LISTENING (\d+)/.exec(String(d))![1]))));
    process.env.TEST_MCP_TOKEN = 'secret-token';
    const m = new McpManager(process.cwd());
    m.register('remote', { type: 'http', url: `http://127.0.0.1:${port}/mcp`, headers: { Authorization: 'Bearer ${TEST_MCP_TOKEN}' } }, 'user', true);
    expect((await m.connect('remote')).status).toBe('connected');
    expect((await m.callTool('remote', 'add', { a: 1, b: 1 })).content).toBe('2');
    m.register('noauth', { type: 'http', url: `http://127.0.0.1:${port}/mcp` }, 'user', true);
    const bad = await m.connect('noauth', 5000);
    expect(bad.status).toBe('failed');
    await m.closeAll();
  });

  it('agent uses MCP tools with permission checks; untrusted project servers stay disabled', async () => {
    const proj = await makeProject({ '.mcp.json': JSON.stringify({ mcpServers: { calc: { command: process.execPath, args: [fixture] } } }) });
    let result = '';
    server = await mockOpenAI((req) => {
      if (req.index === 0) {
        expect(req.toolNames).toContain('mcp__calc__add');
        return call('mcp__calc__add', { a: 20, b: 22 });
      }
      result = req.toolResults[0]!.content;
      return text('done');
    });
    const untrusted = await runtimeFor(proj, openaiSettings(server.url), { connectMcp: true });
    await untrusted.mcp.connectAll();
    expect(untrusted.mcp.get('calc')!.status).toBe('untrusted');
    await untrusted.shutdown();

    const rt = await runtimeFor(proj, openaiSettings(server.url), { connectMcp: true, trust: true, allowedTools: ['mcp__calc'] });
    await rt.mcp.connectAll();
    expect(rt.mcp.get('calc')!.status).toBe('connected');
    await rt.submit('add 20 and 22 with the calculator');
    expect(result).toBe('42');
    const out: string[] = [];
    await runSlash('/mcp list', { rt, print: (t) => out.push(t), submit: async () => {}, exit: () => {} });
    expect(out.join('')).toContain('calc');
    await rt.shutdown();
  });
});

import { promises as fs } from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { call, isolateHome, makeProject, mockOpenAI, openaiSettings, runtimeFor, text, type MockServer } from '../helpers/mock.js';
import type { AgentEvent } from '../../src/agent/events.js';

let server: MockServer | null = null;
beforeEach(async () => {
  await isolateHome();
});
afterEach(async () => {
  await server?.close();
  server = null;
});

describe('agent loop (real tools, scripted model over the OpenAI wire protocol)', () => {
  it('reads, edits, runs failing tests, fixes the bug and verifies', async () => {
    const proj = await makeProject({
      'math.js': 'export function add(a, b) {\n  return a - b;\n}\n',
      'test.js': "import { add } from './math.js';\nif (add(2, 3) !== 5) { console.error('FAIL: add(2,3) =', add(2, 3)); process.exit(1); }\nconsole.log('PASS');\n",
      'package.json': JSON.stringify({ name: 'demo', type: 'module', scripts: { test: 'node test.js' } }),
    });
    const steps: string[] = [];
    server = await mockOpenAI((req) => {
      const r = req.toolResults[0];
      switch (req.index) {
        case 0:
          expect(req.toolNames).toContain('Edit');
          expect(req.system).toContain('STELLA CODER');
          return call('Bash', { command: 'node test.js' }, 'Running tests first.');
        case 1:
          steps.push(r!.content);
          expect(r!.isError).toBe(true);
          expect(r!.content).toContain('FAIL');
          return call('Read', { file_path: 'math.js' });
        case 2:
          expect(r!.content).toContain('return a - b;');
          return call('Edit', { file_path: 'math.js', old_string: 'return a - b;', new_string: 'return a + b;' });
        case 3:
          expect(r!.isError).toBeFalsy();
          return call('Bash', { command: 'node test.js' });
        case 4:
          steps.push(r!.content);
          expect(r!.content).toContain('PASS');
          return text('Fixed `add` in math.js: it subtracted instead of adding. Tests pass.');
        default:
          return text('done');
      }
    });
    const rt = await runtimeFor(proj, openaiSettings(server.url), { permissionMode: 'acceptEdits', allowedTools: ['Bash(node test.js)'] });
    const events: AgentEvent[] = [];
    rt.events.on('event', (e: AgentEvent) => events.push(e));
    const res = await rt.submit('The tests fail, fix it');
    expect(res!.stopReason).toBe('end_turn');
    expect(res!.text).toContain('Tests pass');
    expect(await fs.readFile(path.join(proj, 'math.js'), 'utf8')).toContain('return a + b;');
    expect(steps[0]).toContain('Exit code: 1');
    expect(steps[1]).toContain('Exit code: 0');
    expect(events.some((e) => e.type === 'text_delta')).toBe(true);
    expect(events.filter((e) => e.type === 'tool_result')).toHaveLength(4);
    // session persisted with usage/cost
    expect(rt.session.costUsd).toBeGreaterThan(0);
    const reloaded = await rt.sessions.loadMessages(rt.session.id);
    expect(reloaded.messages.length).toBe(rt.main.messages.length);
    await rt.shutdown();
  });

  it('denies unapproved shell commands in non-interactive mode and reports it to the model', async () => {
    const proj = await makeProject({ 'a.txt': 'hello' });
    server = await mockOpenAI((req) => (req.index === 0 ? call('Bash', { command: 'rm a.txt' }) : text(req.toolResults[0]!.content)));
    const rt = await runtimeFor(proj, openaiSettings(server.url));
    const res = await rt.submit('delete a.txt');
    expect(res!.text).toMatch(/Permission required|no user is available/);
    expect(await fs.readFile(path.join(proj, 'a.txt'), 'utf8')).toBe('hello');
    await rt.shutdown();
  });

  it('executes independent read-only calls in parallel within one turn', async () => {
    const proj = await makeProject({ 'a.txt': 'A', 'b.txt': 'B', 'c.txt': 'C' });
    server = await mockOpenAI((req) =>
      req.index === 0
        ? { tools: ['a.txt', 'b.txt', 'c.txt'].map((f) => ({ name: 'Read', args: { file_path: f } })) }
        : text(req.toolResults.map((r) => r.content.trim().split('\t')[1]).join('')),
    );
    const rt = await runtimeFor(proj, openaiSettings(server.url));
    const res = await rt.submit('read all');
    expect(res!.text).toBe('ABC');
    await rt.shutdown();
  });

  it('returns validation errors for bad tool input and unknown tools', async () => {
    const proj = await makeProject({});
    server = await mockOpenAI((req) => {
      if (req.index === 0) return { tools: [{ name: 'Read', args: { nope: 1 } }, { name: 'Teleport', args: {} }] };
      return text(req.toolResults.map((r) => (r.isError ? 'ERR:' + r.content.slice(0, 30) : 'OK')).join('|'));
    });
    const rt = await runtimeFor(proj, openaiSettings(server.url));
    const res = await rt.submit('x');
    expect(res!.text).toContain('ERR:Invalid input for Read');
    expect(res!.text).toContain('ERR:Unknown tool "Teleport"');
    await rt.shutdown();
  });

  it('retries transient 429/500 errors and succeeds', async () => {
    const proj = await makeProject({});
    let n = 0;
    server = await mockOpenAI(() => (n++ < 2 ? { status: n === 1 ? 429 : 500, error: 'busy', headers: { 'retry-after': '0' } } : text('recovered')));
    const rt = await runtimeFor(proj, openaiSettings(server.url));
    const statuses: string[] = [];
    rt.events.on('event', (e: AgentEvent) => e.type === 'status' && statuses.push(e.text));
    const res = await rt.submit('hi');
    expect(res!.text).toBe('recovered');
    expect(statuses.some((s) => s.includes('retrying'))).toBe(true);
    await rt.shutdown();
  });

  it('can be interrupted mid-command and keeps a valid transcript', async () => {
    const proj = await makeProject({});
    server = await mockOpenAI((req) => (req.index === 0 ? call('Bash', { command: 'node -e "setTimeout(()=>{},30000)"' }) : text('after interrupt')));
    const rt = await runtimeFor(proj, openaiSettings(server.url), { permissionMode: 'bypassPermissions' });
    rt.events.on('event', (e: AgentEvent) => {
      if (e.type === 'tool_call') setTimeout(() => rt.interrupt(), 300);
    });
    const t0 = Date.now();
    const res = await rt.submit('run long');
    expect(Date.now() - t0).toBeLessThan(10_000);
    expect(res!.stopReason).toBe('aborted');
    const last = rt.main.messages[rt.main.messages.length - 1]!;
    expect(last.role).toBe('user');
    expect(last.content[0]!.type).toBe('tool_result');
    // next prompt works on the same transcript
    const res2 = await rt.submit('continue');
    expect(res2!.text).toBe('after interrupt');
    await rt.shutdown();
  });

  it('delivers a message queued while the agent is working', async () => {
    const proj = await makeProject({ 'f.txt': 'x' });
    let sawQueued = false;
    server = await mockOpenAI(async (req) => {
      if (req.index === 0) {
        await new Promise((r) => setTimeout(r, 100));
        return call('Read', { file_path: 'f.txt' });
      }
      sawQueued = JSON.stringify(req.body.messages).includes('also check README');
      return text('ok');
    });
    const rt = await runtimeFor(proj, openaiSettings(server.url));
    const p = rt.submit('look at f');
    await new Promise((r) => setTimeout(r, 30));
    expect(await rt.submit('also check README')).toBeNull();
    await p;
    expect(sawQueued).toBe(true);
    await rt.shutdown();
  });
});

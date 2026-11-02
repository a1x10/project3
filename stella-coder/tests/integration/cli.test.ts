import { execFile } from 'node:child_process';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { call, makeProject, mockOpenAI, openaiSettings, tempDir, text, type MockServer } from '../helpers/mock.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const cli = path.join(root, 'dist/cli/main.js');
let server: MockServer | null = null;
afterEach(async () => {
  await server?.close();
  server = null;
});

beforeAll(async () => {
  await fs.access(cli).catch(() => {
    throw new Error('Run `npm run build` before the CLI tests');
  });
});

function runCli(args: string[], env: Record<string, string>, cwd: string, input?: string): Promise<{ code: number; stdout: string; stderr: string }> {
  return new Promise((resolve) => {
    const p = execFile(process.execPath, [cli, ...args], { cwd, env: { ...process.env, ...env, NO_COLOR: '1', FORCE_COLOR: '0' }, timeout: 60_000 }, (err, stdout, stderr) => resolve({ code: err ? ((err as any).code ?? 1) : 0, stdout, stderr }));
    if (input !== undefined) {
      p.stdin!.end(input);
    }
  });
}

async function homeWith(settings: object) {
  const home = await tempDir('stella-clihome-');
  await fs.writeFile(path.join(home, 'settings.json'), JSON.stringify(settings));
  return home;
}

describe('stella CLI (built binary)', () => {
  it('prints version and help', async () => {
    const v = await runCli(['--version'], {}, root);
    expect(v.stdout.trim()).toMatch(/^\d+\.\d+\.\d+$/);
    const h = await runCli(['--help'], {}, root);
    expect(h.stdout).toContain('STELLA CODER');
    expect(h.stdout).toContain('--permission-mode');
  });

  it('-p runs the agent with real tools and --output-format json', async () => {
    const proj = await makeProject({ 'hello.txt': 'world' });
    server = await mockOpenAI((req) => (req.index === 0 ? call('Read', { file_path: 'hello.txt' }) : text(`It says ${req.toolResults[0]!.content.split('\t')[1]}.`)));
    const home = await homeWith(openaiSettings(server.url));
    const r = await runCli(['-p', 'what is in hello.txt?', '--output-format', 'json'], { STELLA_HOME: home }, proj);
    expect(r.code).toBe(0);
    const j = JSON.parse(r.stdout);
    expect(j.result).toBe('It says world.');
    expect(j.session_id).toMatch(/^s/);
    expect(j.tool_calls).toBe(1);
    expect(j.total_cost_usd).toBeGreaterThan(0);
  });

  it('-p text mode streams the answer and reads stdin', async () => {
    const proj = await makeProject({});
    server = await mockOpenAI((req) => text(`stdin seen: ${req.lastUserText.includes('ERROR 42')}`));
    const home = await homeWith(openaiSettings(server.url));
    const r = await runCli(['-p', 'explain this log'], { STELLA_HOME: home }, proj, 'line1\nERROR 42 at foo\n');
    expect(r.stdout.trim()).toBe('stdin seen: true');
  });

  it('stream-json emits NDJSON events and a final result', async () => {
    const proj = await makeProject({ 'a.txt': 'x' });
    server = await mockOpenAI((req) => (req.index === 0 ? call('Glob', { pattern: '*.txt' }) : text('found')));
    const home = await homeWith(openaiSettings(server.url));
    const r = await runCli(['-p', 'list', '--output-format', 'stream-json'], { STELLA_HOME: home }, proj);
    const lines = r.stdout.trim().split('\n').map((l) => JSON.parse(l));
    expect(lines.some((l) => l.type === 'tool_call' && l.name === 'Glob')).toBe(true);
    expect(lines.some((l) => l.type === 'tool_result')).toBe(true);
    expect(lines[lines.length - 1]).toMatchObject({ type: 'result', result: 'found' });
  });

  it('--continue resumes the last session; permission flags are enforced', async () => {
    const proj = await makeProject({});
    server = await mockOpenAI((req) => {
      if (req.lastUserText === 'second') return text(`history:${JSON.stringify(req.body.messages).includes('first-reply')}`);
      if (req.lastUserText === 'touch') return req.index >= 0 && !req.toolResults.length ? call('Write', { file_path: 'w.txt', content: 'w' }) : text(req.toolResults[0]!.content.slice(0, 40));
      return text('first-reply');
    });
    const home = await homeWith(openaiSettings(server.url));
    await runCli(['-p', 'first'], { STELLA_HOME: home }, proj);
    const r = await runCli(['-c', '-p', 'second'], { STELLA_HOME: home }, proj);
    expect(r.stdout.trim()).toBe('history:true');
    const denied = await runCli(['-p', 'touch'], { STELLA_HOME: home }, proj);
    expect(denied.stdout).toContain('Permission required');
    await expect(fs.access(path.join(proj, 'w.txt'))).rejects.toThrow();
    const allowed = await runCli(['-p', 'touch', '--allowedTools', 'Write'], { STELLA_HOME: home }, proj);
    expect(allowed.stdout).toContain('Created w.txt');
  });

  it('subcommands: doctor, sessions, auth, slash commands in -p', async () => {
    const proj = await makeProject({});
    server = await mockOpenAI(() => text('x'));
    const home = await homeWith(openaiSettings(server.url));
    const d = await runCli(['doctor'], { STELLA_HOME: home }, proj);
    expect(d.stdout).toContain('Node');
    expect(d.stdout).toContain('provider mock');
    const a = await runCli(['auth', 'set', 'openai', 'sk-test-1234567890abcdef'], { STELLA_HOME: home }, proj);
    expect(a.stdout).toContain('sk-tes');
    const creds = await fs.stat(path.join(home, 'credentials.json'));
    if (process.platform !== 'win32') expect(creds.mode & 0o777).toBe(0o600);
    const st = await runCli(['-p', '/status'], { STELLA_HOME: home }, proj);
    expect(st.stdout).toContain('Mode');
    const s = await runCli(['sessions'], { STELLA_HOME: home }, proj);
    expect(s.code).toBe(0);
    const add = await runCli(['mcp', 'add', 'remote', '--url', 'http://127.0.0.1:9/mcp', '--header', 'Authorization: Bearer ${NOPE}'], { STELLA_HOME: home }, proj);
    expect(add.stdout).toContain('Added remote');
    const local = JSON.parse(await fs.readFile(path.join(proj, '.stella/settings.local.json'), 'utf8'));
    expect(local.mcpServers.remote).toMatchObject({ type: 'http', url: 'http://127.0.0.1:9/mcp', headers: { Authorization: 'Bearer ${NOPE}' } });
    const add2 = await runCli(['mcp', 'add', 'calc', '--', process.execPath, 'server.mjs'], { STELLA_HOME: home }, proj);
    expect(add2.stdout).toContain('Added calc');
    const local2 = JSON.parse(await fs.readFile(path.join(proj, '.stella/settings.local.json'), 'utf8'));
    expect(local2.mcpServers.calc).toMatchObject({ type: 'stdio', command: process.execPath, args: ['server.mjs'] });
  });
});

import http from 'node:http';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import type { AddressInfo } from 'node:net';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { Runtime } from '../../src/agent/runtime.js';
import type { Tool, ToolContext } from '../../src/tools/types.js';
import { detectProject, profileSummary } from '../../src/context/project.js';
import { isolateHome, makeProject, openaiSettings, runtimeFor } from '../helpers/mock.js';
import { htmlToText, parseDuckDuckGo } from '../../src/tools/web.js';

let rt: Runtime;
let proj: string;

function ctx(): ToolContext {
  return { cwd: rt.cwd, root: rt.root, roots: rt.roots, signal: new AbortController().signal, agentId: 'main', turnId: 't-test', services: rt.services, progress: () => {} };
}
const tool = (name: string): Tool => rt.allTools().find((t) => t.name === name)!;
const run = async (name: string, input: any) => tool(name).run(tool(name).schema.parse(input), ctx());

beforeAll(async () => {
  await isolateHome();
  proj = await makeProject({
    'package.json': JSON.stringify({ name: 'shop', main: 'src/index.ts', scripts: { test: 'vitest run', build: 'tsc' }, dependencies: { express: '^4', react: '^18' }, devDependencies: { typescript: '^5', vitest: '^1' } }),
    'tsconfig.json': '{}',
    'README.md': '# Shop\nAn online shop.',
    'src/index.ts': "import { createServer } from './server';\nimport express from 'express';\ncreateServer();\n",
    'src/server.ts': "export function createServer() {\n  return startHttp(8080);\n}\nfunction startHttp(port: number) { return port; }\nexport class PaymentGateway {\n  charge(amount: number) { return authenticateUser(amount); }\n}\n",
    'src/auth/login.ts': 'export async function authenticateUser(token: string) {\n  // verify the session token and load the user profile\n  return verifyJwtSignature(token);\n}\nexport const SESSION_TTL = 3600;\n',
    'src/__tests__/server.test.ts': "import { createServer } from '../server';\n",
    'node_modules/ignored/index.js': 'export const ignoredSymbol = 1;',
    'dist/out.js': 'compiled',
    'app.py': 'class Inventory:\n    def add_item(self, sku):\n        return sku\n',
    '.gitignore': 'secret-dir/\n',
    'secret-dir/x.ts': 'export const hidden = 1;',
  });
  rt = await runtimeFor(proj, openaiSettings('http://127.0.0.1:9/v1'));
  await rt.index.ensure();
});
afterAll(async () => rt.shutdown());

describe('search & navigation tools', () => {
  it('Glob respects ignores', async () => {
    const r = await run('Glob', { pattern: '**/*.ts' });
    expect(r.content).toContain('src/server.ts');
    expect(r.content).not.toContain('node_modules');
    expect(r.content).not.toContain('secret-dir');
  });
  it('Grep in all modes (ripgrep and built-in engine)', async () => {
    for (const noRg of ['', '1']) {
      process.env.STELLA_NO_RG = noRg;
      const files = await run('Grep', { pattern: 'createServer' });
      expect(files.content).toContain('src/index.ts');
      expect(files.content).not.toContain('node_modules');
      const content = await run('Grep', { pattern: 'startHttp\\(', output_mode: 'content', glob: '*.ts' });
      expect(content.content).toMatch(/src\/server\.ts:2:/);
      const count = await run('Grep', { pattern: 'export', output_mode: 'count', path: 'src/server.ts' });
      expect(count.content).toMatch(/2/);
    }
    process.env.STELLA_NO_RG = '';
  });
  it('SymbolSearch / ReferenceSearch / DependencySearch', async () => {
    const s = await run('SymbolSearch', { query: 'PaymentGateway' });
    expect(s.content).toContain('src/server.ts:5  class PaymentGateway');
    const py = await run('SymbolSearch', { query: 'add_item' });
    expect(py.content).toContain('app.py:2');
    expect((await run('SymbolSearch', { query: 'ignoredSymbol' })).content).toContain('No symbols');
    const refs = await run('ReferenceSearch', { symbol: 'authenticateUser' });
    expect(refs.content).toContain('Definitions (1)');
    expect(refs.content).toContain('src/server.ts:6');
    const deps = await run('DependencySearch', { file: 'src/server.ts' });
    expect(deps.content).toContain('src/index.ts');
    const pkg = await run('DependencySearch', { package: 'express' });
    expect(pkg.content).toContain('src/index.ts');
    expect(pkg.content).toContain('package.json');
  });
  it('SemanticSearch ranks the relevant chunk first', async () => {
    const r = await run('SemanticSearch', { query: 'where is the user session token verified for authentication' });
    expect(r.content.split('\n')[0]).toContain('src/auth/login.ts');
  });
  it('DirectoryTree and FileInfo', async () => {
    const t = await run('DirectoryTree', { depth: 2 });
    expect(t.content).toContain('src/');
    expect(t.content).not.toContain('node_modules');
    const info = JSON.parse((await run('FileInfo', { path: 'src/server.ts' })).content);
    expect(info).toMatchObject({ type: 'file', lines: 8, binary: false });
  });
  it('index updates incrementally after edits', async () => {
    await run('Read', { file_path: 'src/auth/login.ts' });
    await run('Edit', { file_path: 'src/auth/login.ts', old_string: 'export const SESSION_TTL', new_string: 'export function refreshSession() {}\nexport const SESSION_TTL' });
    await rt.index.ensure();
    expect((await run('SymbolSearch', { query: 'refreshSession' })).content).toContain('src/auth/login.ts');
  });
});

describe('file tools', () => {
  it('Read with offset/limit, notebooks, binary and empty files', async () => {
    await fs.writeFile(path.join(proj, 'big.txt'), Array.from({ length: 50 }, (_, i) => `line ${i + 1}`).join('\n'));
    const r = await run('Read', { file_path: 'big.txt', offset: 10, limit: 3 });
    expect(r.content).toMatch(/10\tline 10\n.*11\tline 11\n.*12\tline 12/);
    expect(r.content).toContain('offset=13');
    await fs.writeFile(path.join(proj, 'bin.dat'), Buffer.from([0, 1, 2, 0]));
    expect((await run('Read', { file_path: 'bin.dat' })).content).toContain('binary');
    await fs.writeFile(path.join(proj, 'nb.ipynb'), JSON.stringify({ cells: [{ cell_type: 'code', source: ['print(1)'], outputs: [{ text: ['1\n'] }] }] }));
    expect((await run('Read', { file_path: 'nb.ipynb' })).content).toContain('print(1)');
    await fs.writeFile(path.join(proj, 'empty.txt'), '');
    expect((await run('Read', { file_path: 'empty.txt' })).content).toContain('empty');
  });
  it('MultiEdit is atomic', async () => {
    await fs.writeFile(path.join(proj, 'm.txt'), 'alpha beta gamma');
    await run('Read', { file_path: 'm.txt' });
    await expect(run('MultiEdit', { file_path: 'm.txt', edits: [{ old_string: 'alpha', new_string: 'A' }, { old_string: 'missing', new_string: 'x' }] })).rejects.toThrow(/Edit #2 failed/);
    expect(await fs.readFile(path.join(proj, 'm.txt'), 'utf8')).toBe('alpha beta gamma');
    await run('MultiEdit', { file_path: 'm.txt', edits: [{ old_string: 'alpha', new_string: 'A' }, { old_string: 'gamma', new_string: 'G' }] });
    expect(await fs.readFile(path.join(proj, 'm.txt'), 'utf8')).toBe('A beta G');
  });
  it('Move, Copy and Delete with checkpoints', async () => {
    await fs.writeFile(path.join(proj, 'mv.txt'), 'move me');
    await run('Copy', { source: 'mv.txt', destination: 'copies/' });
    await expect(run('Copy', { source: 'mv.txt', destination: 'copies/' })).rejects.toThrow(/exists/);
    expect(await fs.readFile(path.join(proj, 'copies/mv.txt'), 'utf8')).toBe('move me');
    await run('Move', { source: 'mv.txt', destination: 'moved.txt' });
    expect(await fs.readFile(path.join(proj, 'moved.txt'), 'utf8')).toBe('move me');
    await expect(run('Delete', { path: 'copies' })).rejects.toThrow(/recursive/);
    await run('Delete', { path: 'copies', recursive: true });
    await expect(fs.access(path.join(proj, 'copies'))).rejects.toThrow();
    await expect(run('Delete', { path: '.' , recursive: true})).rejects.toThrow(/workspace root/);
  });
  it('Write validates JSON', async () => {
    const r = await run('Write', { file_path: 'conf.json', content: '{bad json' });
    expect(r.content).toContain('not valid JSON');
  });
});

describe('process tools', () => {
  it('RunCommand, StartProcess, ProcessStatus, StopProcess and persistent cwd', async () => {
    const r = await run('RunCommand', { program: process.execPath, args: ['-e', 'console.log("hi"); console.error("warn")'] });
    expect(r.content).toContain('hi');
    expect(r.content).toContain('[stderr]');
    expect(r.content).toContain('Exit code: 0');
    const fail = await run('RunCommand', { program: process.execPath, args: ['-e', 'process.exit(3)'] });
    expect(fail.isError).toBe(true);
    expect(fail.content).toContain('Exit code: 3');
    const t = await run('Bash', { command: 'node -e "setTimeout(()=>{}, 10000)"', timeout: 1000 });
    expect(t.content).toContain('timed out');
    const started = await run('StartProcess', { command: `node -e "let i=0;setInterval(()=>console.log('tick '+(i++)),100)"`, wait_ms: 500 });
    const id = /Started (bg\d+)/.exec(started.content)![1]!;
    expect(started.content).toContain('tick');
    await new Promise((res) => setTimeout(res, 300));
    const st = await run('ProcessStatus', { id });
    expect(st.content).toContain('running');
    expect(st.content).toContain('tick');
    expect((await run('StopProcess', { id })).content).toContain('Stopped');
    await new Promise((res) => setTimeout(res, 300));
    expect((await run('ProcessStatus', {})).content).toMatch(/killed|exited/);
    await fs.mkdir(path.join(proj, 'sub'), { recursive: true });
    const cd = await run('Bash', { command: 'cd sub && pwd' });
    expect(cd.content).toContain('[cwd is now sub]');
    const pwd = (await run('Bash', { command: 'pwd' })).content;
    expect(pwd.split('\n')[0]!.replace(/\\/g, '/')).toMatch(/\/sub$/);
    expect(rt.shellCwd.get('main')).toMatch(/sub$/);
    const out = await run('Bash', { command: 'cd / && pwd' });
    expect(out.content).toContain('reset to project root');
    expect(rt.processes.history.length).toBeGreaterThan(3);
  });
});

describe('web tools', () => {
  let srv: http.Server;
  let base = '';
  beforeAll(async () => {
    srv = http.createServer((req, res) => {
      if (req.url === '/doc') {
        res.writeHead(200, { 'content-type': 'text/html' });
        res.end('<html><head><title>Docs</title><script>evil()</script></head><body><h1>Install</h1><p>Run <code>npm i</code> &amp; enjoy.</p><a href="https://x.dev">link</a></body></html>');
      } else {
        res.writeHead(404).end('nope');
      }
    });
    await new Promise<void>((r) => srv.listen(0, '127.0.0.1', () => r()));
    base = `http://127.0.0.1:${(srv.address() as AddressInfo).port}`;
  });
  afterAll(() => srv.close());
  it('WebFetch converts HTML to markdown text and reports HTTP errors', async () => {
    const r = await run('WebFetch', { url: `${base}/doc` });
    expect(r.content).toContain('# Docs');
    expect(r.content).toContain('# Install');
    expect(r.content).toContain('`npm i` & enjoy');
    expect(r.content).toContain('[link](https://x.dev)');
    expect(r.content).not.toContain('evil');
    const nf = await run('WebFetch', { url: `${base}/missing` });
    expect(nf.isError).toBe(true);
  });
  it('parses DuckDuckGo HTML results', () => {
    const html = '<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa&rut=x">Example <b>A</b></a><a class="result__snippet" href="#">Snippet &amp; text</a>';
    expect(parseDuckDuckGo(html)).toEqual([{ title: 'Example A', url: 'https://example.com/a', snippet: 'Snippet & text' }]);
    expect(htmlToText('<p>a</p><p>b</p>')).toBe('a\n\nb');
  });
});

describe('project understanding', () => {
  it('detects languages, frameworks, entry points, tests and commands', async () => {
    const p = await detectProject(proj, rt.index);
    expect(p.languages[0]!.lang).toBe('typescript');
    expect(p.frameworks).toEqual(expect.arrayContaining(['Express', 'React', 'TypeScript', 'Vitest']));
    expect(p.entryPoints).toContain('src/index.ts');
    expect(p.commands.test).toBe('npm test');
    expect(p.commands.typecheck).toBe('npx tsc --noEmit');
    expect(p.testDirs).toContain('src/__tests__');
    expect(p.readme).toContain('online shop');
    expect(profileSummary(p)).toContain('Frameworks/tools:');
  });
  it('works in an empty project', async () => {
    const empty = await makeProject({});
    const r2 = await runtimeFor(empty, openaiSettings('http://127.0.0.1:9/v1'));
    const p = await r2.getProfile();
    expect(p.fileCount).toBe(0);
    expect(p.languages).toEqual([]);
    expect(await r2.systemPrompt()).toContain('Project:');
    await r2.shutdown();
  });
  it('detects Python projects', async () => {
    const py = await makeProject({ 'pyproject.toml': '[project]\nname="x"\ndependencies=["fastapi","pydantic"]\n[tool.ruff]\n', 'main.py': 'def run():\n    pass\n', 'tests/test_main.py': 'def test_x():\n    assert True\n' });
    const r3 = await runtimeFor(py, openaiSettings('http://127.0.0.1:9/v1'));
    const p = await r3.getProfile();
    expect(p.frameworks).toEqual(expect.arrayContaining(['FastAPI', 'Pydantic']));
    expect(p.commands.test).toBe('python -m pytest');
    expect(p.commands.lint).toBe('ruff check .');
    expect(p.commands.run).toBe('python main.py');
    await r3.shutdown();
  });
});

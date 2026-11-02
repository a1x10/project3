import { execFile, spawnSync } from 'node:child_process';
import { promises as fs, existsSync, readFileSync } from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, it } from 'vitest';
import { tempDir } from '../helpers/mock.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, '../../..');
const fakeRouter = path.join(here, '../fixtures/fake-freellmapi.mjs');
const node = process.execPath;

function freePort(): Promise<number> {
  return new Promise((r) => {
    const s = net.createServer().listen(0, '127.0.0.1', () => {
      const p = (s.address() as net.AddressInfo).port;
      s.close(() => r(p));
    });
  });
}

/** Fake docker/git/npm on PATH that record calls and emulate the real tools. */
async function fakeBin(dir: string, port: number, log: string, state: string) {
  const bin = path.join(dir, 'bin');
  await fs.mkdir(bin, { recursive: true });
  const docker = `#!/bin/sh
echo "docker $*" >> "${log}"
if [ "$1" = "info" ]; then exit 0; fi
if [ "$1" = "compose" ] && [ "$2" = "version" ]; then exit 0; fi
if [ "$1" = "compose" ] && [ "$2" = "up" ]; then
  test -f docker-compose.yml || exit 3
  grep -q "ENCRYPTION_KEY=" .env || exit 4
  P=$(grep '^PORT=' .env | cut -d= -f2); [ -n "$P" ] || P=${port}
  PORT=$P FAKE_STATE="${state}" nohup "${node}" "${fakeRouter}" >/dev/null 2>&1 &
  echo $! > "${dir}/fake-router.pid"
  exit 0
fi
if [ "$1" = "compose" ] && [ "$2" = "stop" ]; then kill $(cat "${dir}/fake-router.pid") 2>/dev/null; exit 0; fi
exit 0
`;
  const git = `#!/bin/sh
echo "git $*" >> "${log}"
if [ "$1" = "clone" ]; then
  eval dest=\\\${$#}
  mkdir -p "$dest/server/dist" && cp "${fakeRouter}" "$dest/server/dist/index.js" && echo '{"name":"fake"}' > "$dest/package.json"
fi
exit 0
`;
  const npm = `#!/bin/sh
echo "npm $* (cwd=$(pwd))" >> "${log}"
exit 0
`;
  for (const [name, body] of [['docker', docker], ['git', git], ['npm', npm]]) await fs.writeFile(path.join(bin, name), body, { mode: 0o755 });
  return bin;
}

const pids: string[] = [];
afterEach(() => {
  for (const f of pids.splice(0)) {
    try {
      process.kill(Number(readFileSync(f, 'utf8')), 'SIGTERM');
    } catch {
      /* gone */
    }
  }
});

describe.skipIf(process.platform === 'win32')('FreeLLMAPI installer and autostart', () => {
  it('installer (docker mode): writes compose/.env, starts router, creates dashboard account, saves unified key, enables keyless providers', async () => {
    const dir = await tempDir('stella-inst-');
    const port = await freePort();
    const log = path.join(dir, 'calls.log');
    const state = path.join(dir, 'router-state.json');
    const bin = await fakeBin(dir, port, log, state);
    const home = path.join(dir, 'stella-home');
    const routerDir = path.join(dir, 'freellmapi');
    pids.push(path.join(dir, 'fake-router.pid'));
    const env = { ...process.env, PATH: `${bin}:${process.env.PATH}`, STELLA_HOME: home, FREELLMAPI_DIR: routerDir, FREELLMAPI_PORT: String(port), FREELLMAPI_API_KEY: '' };
    const r = spawnSync(node, [path.join(repo, 'install.mjs'), '--yes', '--stella', '--studio', '--router-mode', 'docker'], { env, encoding: 'utf8', timeout: 120_000 });
    const out = r.stdout + r.stderr;
    expect(r.status, out).toBe(0);
    expect(out).toContain('Роутер установлен и запущен');
    expect(out).toContain('Единый ключ получен');
    const compose = await fs.readFile(path.join(routerDir, 'docker-compose.yml'), 'utf8');
    expect(compose).toContain('ghcr.io/tashfeenahmed/freellmapi:latest');
    expect(compose).toContain('127.0.0.1');
    const dotenv = await fs.readFile(path.join(routerDir, '.env'), 'utf8');
    expect(dotenv).toMatch(/ENCRYPTION_KEY=[0-9a-f]{64}/);
    expect((await fs.stat(path.join(routerDir, '.env'))).mode & 0o777).toBe(0o600);
    const creds = JSON.parse(await fs.readFile(path.join(home, 'credentials.json'), 'utf8'));
    expect(creds['freellmapi.apiKey']).toBe('freellmapi-fake-unified-key');
    expect((await fs.stat(path.join(home, 'credentials.json'))).mode & 0o777).toBe(0o600);
    expect(await fs.readFile(path.join(routerDir, 'dashboard-login.txt'), 'utf8')).toMatch(/email: owner@freellmapi\.local\npassword: \S{12,}/);
    const routerState = JSON.parse(await fs.readFile(state, 'utf8'));
    expect(routerState.keys.map((k: any) => k.platform).sort()).toEqual(['kilo', 'ovh']); // keyless chat providers only
    const calls = await fs.readFile(log, 'utf8');
    expect(calls).toContain('docker compose pull');
    expect(calls).toContain('docker compose up -d');
    expect(calls).toMatch(/npm ci .*cwd=.*stella-coder/);
    expect(calls).toMatch(/npm run build .*cwd=.*vibing-studio/);
    expect(calls).toMatch(/npm link .*cwd=.*stella-coder/);

    // Re-running is idempotent: key still valid, .env (encryption key) preserved.
    const r2 = spawnSync(node, [path.join(repo, 'install.mjs'), '--yes', '--stella', '--router-mode', 'docker'], { env, encoding: 'utf8', timeout: 120_000 });
    expect(r2.stdout).toContain('Роутер уже запущен');
    expect(r2.stdout).toContain('Сохранённый ключ работает');
    expect(await fs.readFile(path.join(routerDir, '.env'), 'utf8')).toBe(dotenv);

    // STELLA autostarts the stopped router and uses the saved key.
    spawnSync(path.join(bin, 'docker'), ['compose', 'stop'], { cwd: routerDir, env });
    await new Promise((res) => setTimeout(res, 300));
    const cli = path.join(repo, 'stella-coder', 'dist', 'cli', 'main.js');
    const proj = await tempDir('stella-proj-');
    const res = await new Promise<{ code: number; stdout: string; stderr: string }>((resolve) =>
      execFile(node, [cli, '-p', 'hello'], { cwd: proj, env: { ...env, FREELLMAPI_BASE_URL: `http://127.0.0.1:${port}/v1`, NO_COLOR: '1' }, timeout: 60_000 }, (err, stdout, stderr) =>
        resolve({ code: err ? ((err as any).code ?? 1) : 0, stdout, stderr }),
      ),
    );
    expect(res.stderr).toContain('Запускаю роутер FreeLLMAPI');
    expect(res.stdout.trim()).toBe('router says hi');
    expect(res.code).toBe(0);
  });

  it('source mode: clone, npm ci/build, background start, status, stop', async () => {
    const dir = await tempDir('stella-src-');
    const port = await freePort();
    const log = path.join(dir, 'calls.log');
    const bin = await fakeBin(dir, port, log, path.join(dir, 'state.json'));
    const routerDir = path.join(dir, 'freellmapi');
    const env = { ...process.env, PATH: `${bin}:${process.env.PATH}`, FREELLMAPI_DIR: routerDir, FREELLMAPI_PORT: String(port), STELLA_HOME: path.join(dir, 'h') };
    const cliPath = path.join(repo, 'tools', 'freellmapi-router.mjs');
    const inst = spawnSync(node, [cliPath, 'install', '--mode', 'source'], { env, encoding: 'utf8', timeout: 60_000 });
    expect(inst.status, inst.stdout + inst.stderr).toBe(0);
    const calls = await fs.readFile(log, 'utf8');
    expect(calls).toContain('git clone --depth 1 https://github.com/tashfeenahmed/freellmapi.git');
    expect(calls).toContain('npm ci --no-audit --no-fund');
    expect(calls).toContain('npm run build');
    const st = JSON.parse(spawnSync(node, [cliPath, 'status'], { env, encoding: 'utf8' }).stdout);
    expect(st).toMatchObject({ installed: true, mode: 'source', running: true });
    expect(existsSync(path.join(routerDir, 'router.pid'))).toBe(true);
    expect(spawnSync(node, [cliPath, 'stop'], { env, encoding: 'utf8' }).stdout).toContain('остановлен');
    await new Promise((res) => setTimeout(res, 400));
    expect(JSON.parse(spawnSync(node, [cliPath, 'status'], { env, encoding: 'utf8' }).stdout).running).toBe(false);
    const ens = spawnSync(node, [cliPath, 'ensure'], { env, encoding: 'utf8', timeout: 60_000 });
    expect(ens.stdout).toContain('FreeLLMAPI работает');
    spawnSync(node, [cliPath, 'stop'], { env });
  });

  it('falls back to a manual key when the dashboard API answers unexpectedly (no crash)', async () => {
    const dir = await tempDir('stella-html-');
    const port = await freePort();
    const bin = await fakeBin(dir, port, path.join(dir, 'calls.log'), path.join(dir, 'state.json'));
    const { spawn } = await import('node:child_process');
    const srv = spawn(node, [fakeRouter], { env: { ...process.env, PORT: String(port), FAKE_HTML_STATUS: '1' }, stdio: 'ignore' });
    try {
      for (let i = 0; i < 40; i++) {
        if (await fetch(`http://127.0.0.1:${port}/api/ping`).then((r) => r.ok, () => false)) break;
        await new Promise((r) => setTimeout(r, 100));
      }
      const env = { ...process.env, PATH: `${bin}:${process.env.PATH}`, STELLA_HOME: path.join(dir, 'h'), FREELLMAPI_DIR: path.join(dir, 'fl'), FREELLMAPI_PORT: String(port), FREELLMAPI_API_KEY: '' };
      const r = spawnSync(node, [path.join(repo, 'install.mjs'), '--yes', '--stella', '--router-mode', 'docker'], { env, encoding: 'utf8', timeout: 60_000 });
      expect(r.status, r.stdout + r.stderr).toBe(0);
      expect(r.stdout).toContain('Роутер уже запущен');
      expect(r.stdout).toContain('вернул не JSON (text/html');
      expect(r.stdout).toContain('Ключ не сохранён');
      expect(r.stdout + r.stderr).not.toContain('TypeError');
    } finally {
      srv.kill();
    }
  });

  it('moves off a port taken by another program (e.g. Flowise) and STELLA/studio follow the saved port', async () => {
    const { spawn } = await import('node:child_process');
    const dir = await tempDir('stella-port-');
    const busy = await freePort();
    // A separate process (spawnSync below blocks this one): an HTML app such as Flowise on the router port.
    const code = `require('http').createServer((q,r)=>r.writeHead(200,{'content-type':'text/html'}).end('<!DOCTYPE html><html><head><title>Flowise - Build AI Agents, Visually</title></head></html>')).listen(${busy},'127.0.0.1')`;
    const otherProc = spawn(node, ['-e', code], { stdio: 'ignore' });
    const other = { close: () => otherProc.kill() };
    for (let i = 0; i < 50; i++) {
      if (await fetch(`http://127.0.0.1:${busy}/`).then(() => true, () => false)) break;
      await new Promise((r) => setTimeout(r, 100));
    }
    const bin = await fakeBin(dir, busy, path.join(dir, 'calls.log'), path.join(dir, 'state.json'));
    const routerDir = path.join(dir, 'fl');
    pids.push(path.join(dir, 'fake-router.pid'));
    const env: NodeJS.ProcessEnv = { ...process.env, PATH: `${bin}:${process.env.PATH}`, STELLA_HOME: path.join(dir, 'h'), FREELLMAPI_DIR: routerDir, FREELLMAPI_DEFAULT_PORT: String(busy), FREELLMAPI_API_KEY: '' };
    delete env.FREELLMAPI_PORT;
    delete env.FREELLMAPI_BASE_URL;
    try {
      const r = spawnSync(node, [path.join(repo, 'install.mjs'), '--yes', '--stella', '--router-mode', 'docker'], { env, encoding: 'utf8', timeout: 90_000 });
      const out = r.stdout + r.stderr;
      expect(r.status, out).toBe(0);
      expect(out).toContain(`Порт ${busy} занят другой программой (Flowise - Build AI Agents, Visually)`);
      expect(out).not.toContain('Роутер уже запущен');
      const saved = JSON.parse(await fs.readFile(path.join(routerDir, 'stella-router.json'), 'utf8'));
      expect(saved.port).not.toBe(busy);
      expect(await fs.readFile(path.join(routerDir, '.env'), 'utf8')).toContain(`PORT=${saved.port}`);
      expect(out).toContain(`http://127.0.0.1:${saved.port}`);
      expect(out).toContain('Единый ключ получен');
      const { freellmapiBaseUrl } = await import('../../src/providers/registry.js');
      expect(freellmapiBaseUrl(env)).toBe(`http://localhost:${saved.port}/v1`);
      const cli = path.join(repo, 'stella-coder', 'dist', 'cli', 'main.js');
      const res = spawnSync(node, [cli, '-p', 'hello'], { cwd: await tempDir('p-'), env: { ...env, NO_COLOR: '1' }, encoding: 'utf8', timeout: 60_000 });
      expect(res.stdout.trim(), res.stderr).toBe('router says hi');
    } finally {
      other.close();
    }
  });

  it('reports a missing install instead of hanging', async () => {
    const dir = await tempDir('stella-none-');
    const env = { ...process.env, FREELLMAPI_DIR: path.join(dir, 'none'), FREELLMAPI_PORT: String(await freePort()) };
    const r = spawnSync(node, [path.join(repo, 'tools', 'freellmapi-router.mjs'), 'ensure'], { env, encoding: 'utf8' });
    expect(r.status).toBe(1);
    expect(r.stdout).toContain('not-installed');
  });
});

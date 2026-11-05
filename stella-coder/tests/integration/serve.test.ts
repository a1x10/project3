import { spawn } from 'node:child_process';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, it } from 'vitest';
import { call, makeProject, mockOpenAI, tempDir, text, type MockServer } from '../helpers/mock.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const cli = path.join(root, 'dist/cli/main.js');
let server: MockServer | null = null;
afterEach(async () => {
  await server?.close();
  server = null;
});

/** `stella serve`: JSON lines over stdio, as used by the Vibing AI Studio «Разработка» mode. */
describe('stella serve (desktop protocol)', () => {
  it('runs prompts, forwards permission requests and applies the answer', async () => {
    server = await mockOpenAI((req) => (req.toolResults.length ? text('Готово: bot.py создан.') : call('Write', { file_path: 'bot.py', content: 'print("hi")\n' }, 'Создаю бота.')));
    const proj = await makeProject({ 'README.md': '# demo\n' });
    const home = await tempDir('stella-serve-');
    await fs.writeFile(path.join(home, 'credentials.json'), JSON.stringify({}));
    const p = spawn(process.execPath, [cli, 'serve', '--cwd', proj, '-m', 'cloud:auto:smart'], {
      env: { ...process.env, STELLA_HOME: home, STELLA_CLOUD_URL: server.url.replace(/\/v1$/, ''), STELLA_CLOUD_API_KEY: 'sk-test', NO_COLOR: '1' },
    });
    const seen: string[] = [];
    const result = await new Promise<any>((resolve, reject) => {
      const t = setTimeout(() => reject(new Error('timeout; seen ' + seen.join(','))), 30_000);
      readline.createInterface({ input: p.stdout! }).on('line', (line) => {
        const m = JSON.parse(line);
        seen.push(m.type === 'event' ? `event:${m.event.type}` : m.type);
        const send = (o: unknown) => p.stdin!.write(JSON.stringify(o) + '\n');
        if (m.type === 'ready') {
          expect(m.model).toBe('cloud:auto:smart');
          send({ type: 'prompt', text: 'Сделай телеграм-бота' });
        } else if (m.type === 'permission_request') {
          expect(m.summary).toContain('bot.py');
          send({ type: 'answer', id: m.id, value: { decision: 'allow_once' } });
        } else if (m.type === 'done') {
          clearTimeout(t);
          resolve(m);
        }
      });
    });
    p.stdin!.end();
    expect(result.text).toContain('bot.py создан');
    expect(await fs.readFile(path.join(proj, 'bot.py'), 'utf8')).toBe('print("hi")\n');
    expect(seen).toContain('event:tool_result');
    expect(server.requests[0]!.body.model).toBe('auto:smart');
    expect(server.requests[0]!.headers!['x-stella-client']).toBe('stella');
  });
});

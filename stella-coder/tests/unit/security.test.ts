import { promises as fs } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { resolvePath, isWithin, isSystemPath } from '../../src/security/paths.js';
import { containsSecret, redact } from '../../src/utils/redact.js';
import { tempDir } from '../helpers/mock.js';

describe('path security', () => {
  it('detects traversal outside the workspace', async () => {
    const root = await tempDir();
    expect(resolvePath('../../etc/passwd', { cwd: root, roots: [root] }).inWorkspace).toBe(false);
    expect(resolvePath('src/../a.txt', { cwd: root, roots: [root] }).inWorkspace).toBe(true);
    expect(() => resolvePath('a\0b', { cwd: root, roots: [root] })).toThrow();
  });
  it('resolves symlinks that escape the workspace', async () => {
    const root = await tempDir();
    const outside = await tempDir();
    await fs.writeFile(path.join(outside, 'secret.txt'), 's');
    await fs.symlink(outside, path.join(root, 'link'), 'dir').catch(() => {});
    const r = resolvePath('link/secret.txt', { cwd: root, roots: [root] });
    if (r.viaSymlink) {
      expect(r.inWorkspace).toBe(false);
      expect(r.real).toBe(path.join(outside, 'secret.txt'));
    }
    const r2 = resolvePath('link/new-file.txt', { cwd: root, roots: [root] });
    if (r2.viaSymlink) expect(r2.inWorkspace).toBe(false);
  });
  it('system paths and containment', () => {
    if (process.platform !== 'win32') {
      expect(isSystemPath('/etc/hosts')).toBe(true);
      expect(isSystemPath('/home/u/project')).toBe(false);
    }
    expect(isWithin(path.resolve('/a/b/c'), path.resolve('/a/b'))).toBe(true);
    expect(isWithin(path.resolve('/a/bc'), path.resolve('/a/b'))).toBe(false);
  });
});

describe('secret redaction', () => {
  it('masks provider keys and passwords', () => {
    const s = 'key=sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUV and OPENAI sk-proj-abcdefghijklmnopqrstuvwxyz password: hunter2hunter2';
    expect(containsSecret(s)).toBe(true);
    const r = redact(s);
    expect(r).not.toContain('ABCDEFGHIJKLMNOPQRSTUV');
    expect(r).not.toContain('abcdefghijklmnopqrstuvwxyz');
    expect(r).not.toContain('hunter2hunter2');
    expect(containsSecret('just a normal sentence about tokens')).toBe(false);
  });
});

describe('confidential files cannot leak through other tools', () => {
  it('Bash referencing .env asks; Grep skips confidential files', async () => {
    const { isolateHome, makeProject, openaiSettings, runtimeFor } = await import('../helpers/mock.js');
    await isolateHome();
    const proj = await makeProject({ '.env': 'API_TOKEN=supersecretvalue123', 'src/a.ts': 'const API_TOKEN = process.env.API_TOKEN;' });
    const rt = await runtimeFor(proj, openaiSettings('http://127.0.0.1:9/v1'));
    const ctx = { cwd: proj, root: proj, roots: [proj], signal: new AbortController().signal, agentId: 'main', turnId: 't', services: rt.services, progress: () => {} };
    const bash = rt.allTools().find((t) => t.name === 'Bash')!;
    const d1 = await bash.describe({ command: 'cat .env' }, ctx);
    expect(rt.permissions.check('Bash', d1).behavior).toBe('ask');
    const d2 = await bash.describe({ command: 'cat src/a.ts' }, ctx);
    expect(rt.permissions.check('Bash', d2).behavior).toBe('allow');
    const grep = rt.allTools().find((t) => t.name === 'Grep')!;
    for (const noRg of ['', '1']) {
      process.env.STELLA_NO_RG = noRg;
      const r = await grep.run({ pattern: 'API_TOKEN', output_mode: 'content' }, ctx);
      expect(r.content).toContain('src/a.ts');
      expect(r.content).not.toContain('supersecretvalue123');
    }
    process.env.STELLA_NO_RG = '';
    const { shellQuote } = await import('../../src/security/quote.js');
    expect(shellQuote("a'b $(rm -rf x)", 'posix')).toBe("'a'\\''b $(rm -rf x)'");
    await rt.shutdown();
  });
});

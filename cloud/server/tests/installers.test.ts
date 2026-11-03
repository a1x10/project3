import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { startCloud } from './helpers.js';

describe('one-command STELLA CODER installers', () => {
  const dl = fs.mkdtempSync(path.join(os.tmpdir(), 'stella-dl-'));
  let cloud: Awaited<ReturnType<typeof startCloud>>;
  beforeAll(async () => {
    cloud = await startCloud({ DOWNLOADS_DIR: dl, PUBLIC_URL: 'https://ai.example.com' });
  });
  afterAll(() => cloud.close());

  it('without a package the scripts say so; with one they point at it', async () => {
    let ps1 = await (await fetch(`${cloud.url}/install.ps1`)).text();
    expect(ps1).toContain("$Package = ''");
    expect((await (await fetch(`${cloud.url}/api/config`)).json()).stellaPackage).toBeNull();

    fs.writeFileSync(path.join(dl, 'stella-coder-0.1.0.tgz'), 'x');
    ps1 = await (await fetch(`${cloud.url}/install.ps1`)).text();
    expect(ps1).toContain("$Package = 'https://ai.example.com/downloads/stella-coder-0.1.0.tgz'");
    expect(ps1).toContain("stella-coder.cmd login $Server");
    expect(/[^\x00-\x7F]/.test(ps1)).toBe(false); // Windows PowerShell 5.1 reads scripts as ANSI
    const sh = await (await fetch(`${cloud.url}/install.sh`)).text();
    expect(sh).toContain("PACKAGE='https://ai.example.com/downloads/stella-coder-0.1.0.tgz'");
    const file = path.join(dl, 'install.sh');
    fs.writeFileSync(file, sh);
    expect(spawnSync('bash', ['-n', file]).status).toBe(0);
    const cfg = await (await fetch(`${cloud.url}/api/config`)).json();
    expect(cfg.stellaPackage).toBe('stella-coder-0.1.0.tgz');
    const tgz = await fetch(`${cloud.url}/downloads/stella-coder-0.1.0.tgz`);
    expect(tgz.status).toBe(200);
  });
});

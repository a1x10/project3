import { promises as fs } from 'node:fs';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { SettingsSchema } from '../../src/config/settings.js';
import { parseFrontmatter } from '../../src/utils/frontmatter.js';

const ex = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../examples');

describe('shipped examples are valid', () => {
  it('settings files match the schema', async () => {
    for (const f of ['.stella/settings.json', 'settings.providers.json']) {
      const r = SettingsSchema.safeParse(JSON.parse(await fs.readFile(path.join(ex, f), 'utf8')));
      expect(r.success, f).toBe(true);
    }
    const mcp = JSON.parse(await fs.readFile(path.join(ex, '.mcp.json'), 'utf8'));
    expect(Object.keys(mcp.mcpServers)).toContain('github');
  });
  it('agent/skill/command frontmatter parses', async () => {
    expect(parseFrontmatter(await fs.readFile(path.join(ex, '.stella/agents/migrator.md'), 'utf8')).data).toMatchObject({ name: 'migrator', maxTurns: 40 });
    expect(parseFrontmatter(await fs.readFile(path.join(ex, '.stella/skills/release-notes/SKILL.md'), 'utf8')).data.name).toBe('release-notes');
    expect(parseFrontmatter(await fs.readFile(path.join(ex, '.stella/commands/release.md'), 'utf8')).data['argument-hint']).toBe('<patch|minor|major>');
  });
  it('guard hook blocks dangerous commands with exit 2', () => {
    const run = (cmd: string) => {
      try {
        execFileSync(process.execPath, [path.join(ex, '.stella/hooks/guard.cjs')], { input: JSON.stringify({ tool_input: { command: cmd } }), stdio: 'pipe' });
        return 0;
      } catch (e: any) {
        return e.status;
      }
    };
    expect(run('terraform apply -auto-approve')).toBe(2);
    expect(run('npm test')).toBe(0);
  });
  it('plugin secret scanner flags secrets', () => {
    const out = execFileSync(process.execPath, [path.join(ex, 'plugin/acme/scan.cjs')], { input: JSON.stringify({ tool_input: { content: 'key = AKIAABCDEFGHIJKLMNOP' } }) }).toString();
    expect(JSON.parse(out).decision).toBe('block');
  });
});

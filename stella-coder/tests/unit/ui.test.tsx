import React from 'react';
import { render } from 'ink-testing-library';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { App } from '../../src/cli/App.js';
import { renderMarkdown, highlight } from '../../src/cli/markdown.js';
import { call, isolateHome, makeProject, mockOpenAI, openaiSettings, runtimeFor, text, type MockServer } from '../helpers/mock.js';

const strip = (s: string) => s.replace(/\x1b\[[0-9;]*m/g, '');
const tick = (ms = 80) => new Promise((r) => setTimeout(r, ms));
async function until(fn: () => boolean, ms = 5000) {
  const t0 = Date.now();
  while (!fn()) {
    if (Date.now() - t0 > ms) throw new Error('timeout waiting for UI');
    await tick(30);
  }
}

let server: MockServer | null = null;
beforeEach(async () => {
  await isolateHome();
});
afterEach(async () => {
  await server?.close();
  server = null;
});

describe('markdown renderer', () => {
  it('renders headings, lists, code fences, inline code and tables', () => {
    const out = strip(renderMarkdown('# Title\n- item **bold**\n1. one\n```ts\nconst x = 1;\n```\n| a | b |\n|---|---|\n| 1 | 2 |\n> quote\n- [x] done'));
    expect(out).toContain('Title');
    expect(out).toContain('• item bold');
    expect(out).toContain('│ const x = 1;');
    expect(out).toContain('ts');
    expect(out).toContain(' 1 │ 2 ');
    expect(out).toContain('▎ quote');
    expect(out).toContain('☑ done');
    expect(strip(highlight('+a\n-b', 'diff'))).toBe('+a\n-b');
  });
});

describe('interactive UI (Ink)', () => {
  it('shows the banner, runs slash commands, streams answers and asks permission', async () => {
    const proj = await makeProject({ 'f.txt': 'content' });
    server = await mockOpenAI((req) => {
      if (req.lastUserText.includes('write it')) return req.toolResults.length ? text('Wrote the file.') : call('Write', { file_path: 'new.txt', content: 'hello' });
      return text('# Answer\nHello from **STELLA**');
    });
    const rt = await runtimeFor(proj, openaiSettings(server.url));
    const ui = render(<App rt={rt} version="9.9.9" />);
    await tick();
    expect(strip(ui.lastFrame()!)).toContain('STELLA CODER');
    expect(strip(ui.lastFrame()!)).toContain('Scripted Mock');

    ui.stdin.write('/he');
    await tick();
    expect(strip(ui.lastFrame()!)).toContain('/help');
    ui.stdin.write('lp');
    await tick();
    ui.stdin.write('\r');
    await until(() => strip(ui.frames.join('\n')).includes('Commands'));

    ui.stdin.write('hi there');
    await tick();
    ui.stdin.write('\r');
    await until(() => strip(ui.frames.join('\n')).includes('Hello from STELLA'));

    ui.stdin.write('please write it');
    await tick();
    ui.stdin.write('\r');
    await until(() => strip(ui.lastFrame()!).includes('Allow Write?'));
    await tick();
    expect(strip(ui.lastFrame()!)).toContain("don't ask again");
    ui.stdin.write('1');
    await until(() => strip(ui.frames.join('\n')).includes('Wrote the file.'));
    expect(strip(ui.frames.join('\n'))).toContain('Create new.txt');
    ui.unmount();
    await rt.shutdown();
  });

  it('shift+tab cycles permission modes', async () => {
    const proj = await makeProject({});
    server = await mockOpenAI(() => text('x'));
    const rt = await runtimeFor(proj, openaiSettings(server.url));
    const ui = render(<App rt={rt} version="1" />);
    await tick();
    ui.stdin.write('\x1b[Z');
    await tick();
    expect(rt.permissions.mode).toBe('acceptEdits');
    expect(strip(ui.lastFrame()!)).toContain('accept edits on');
    ui.stdin.write('\x1b[Z');
    await tick();
    expect(rt.permissions.mode).toBe('plan');
    ui.unmount();
    await rt.shutdown();
  });
});

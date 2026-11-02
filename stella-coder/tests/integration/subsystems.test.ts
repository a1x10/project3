import { promises as fs } from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { call, isolateHome, makeProject, mockAnthropic, mockGemini, mockOpenAI, openaiSettings, runtimeFor, text, type MockServer } from '../helpers/mock.js';
import type { AgentEvent } from '../../src/agent/events.js';
import { runSlash, type CommandContext } from '../../src/cli/commands.js';
import { Runtime } from '../../src/agent/runtime.js';

let servers: MockServer[] = [];
let home = '';
beforeEach(async () => {
  home = await isolateHome();
});
afterEach(async () => {
  await Promise.all(servers.map((s) => s.close()));
  servers = [];
});
const track = (s: MockServer) => (servers.push(s), s);

function cmdCtx(rt: Runtime, out: string[] = []): CommandContext {
  return { rt, print: (t) => out.push(t), submit: async (p) => void (await rt.submit(p)), exit: () => {} };
}

describe('sessions', () => {
  it('persists, lists, renames, searches and resumes a conversation', async () => {
    const proj = await makeProject({ 'x.txt': 'X' });
    const s = track(await mockOpenAI((req) => (req.index === 0 ? text('first answer') : text(`I remember: ${JSON.stringify(req.body.messages).includes('first answer')}`))));
    const rt = await runtimeFor(proj, openaiSettings(s.url));
    await rt.submit('remember the word pineapple');
    const id = rt.session.id;
    expect(rt.session.title).toContain('pineapple');
    await rt.sessions.rename(id, 'Fruit chat');
    await rt.shutdown();

    const rt2 = await runtimeFor(proj, openaiSettings(s.url), { resume: 'last' });
    expect(rt2.session.id).toBe(id);
    expect(rt2.session.title).toBe('Fruit chat');
    expect(rt2.main.messages.length).toBe(2);
    const r = await rt2.submit('what did you say?');
    expect(r!.text).toBe('I remember: true');
    const found = await rt2.sessions.search('pineapple');
    expect(found.map((f) => f.meta.id)).toContain(id);
    expect((await rt2.sessions.list()).length).toBe(1);
    // /clear starts a new session, old one still resumable
    await rt2.clear();
    expect(rt2.session.id).not.toBe(id);
    expect(rt2.main.messages).toHaveLength(0);
    await rt2.resume(id.slice(0, 8));
    expect(rt2.main.messages.length).toBe(4);
    await rt2.shutdown();
  });

  it('recovers an interrupted session with a dangling tool call', async () => {
    const proj = await makeProject({});
    const s = track(await mockOpenAI(() => text('ok')));
    const rt = await runtimeFor(proj, openaiSettings(s.url));
    await rt.sessions.append(rt.session.id, { v: 1, type: 'message', message: { role: 'user', content: [{ type: 'text', text: 'go' }] }, ts: 1 });
    await rt.sessions.append(rt.session.id, { v: 1, type: 'message', message: { role: 'assistant', content: [{ type: 'tool_use', id: 'dangling', name: 'Bash', input: { command: 'ls' } }] }, ts: 2 });
    await fs.appendFile(path.join(rt.paths.sessionsDir, `${rt.session.id}.jsonl`), '{"v":1,"type":"mess'); // torn line
    rt.session.status = 'active';
    rt.session.pendingTask = 'go';
    await rt.sessions.saveMeta(rt.session);
    const rt2 = await runtimeFor(proj, openaiSettings(s.url), { resume: rt.session.id });
    expect(rt2.main.messages).toHaveLength(3);
    expect(rt2.main.messages[2]!.content[0]).toMatchObject({ type: 'tool_result', toolUseId: 'dangling', isError: true });
    expect(rt2.warnings.join(' ')).toContain('interrupted');
    expect((await rt2.submit('continue'))!.text).toBe('ok');
  });
});

describe('checkpoints and rewind', () => {
  it('restores edited/created/deleted files and refuses to clobber user changes', async () => {
    const proj = await makeProject({ 'a.txt': 'original\n', 'b.txt': 'keep me\n' });
    const s = track(
      await mockOpenAI((req) => {
        if (req.index === 0) return { tools: [{ name: 'Read', args: { file_path: 'a.txt' } }, { name: 'Read', args: { file_path: 'b.txt' } }] };
        if (req.index === 1)
          return {
            tools: [
              { name: 'Edit', args: { file_path: 'a.txt', old_string: 'original', new_string: 'changed' } },
              { name: 'Write', args: { file_path: 'new/c.txt', content: 'created' } },
              { name: 'Delete', args: { path: 'b.txt' } },
            ],
          };
        return text('done');
      }),
    );
    const rt = await runtimeFor(proj, openaiSettings(s.url), { permissionMode: 'bypassPermissions' });
    await rt.submit('change things');
    expect(await fs.readFile(path.join(proj, 'a.txt'), 'utf8')).toBe('changed\n');
    await expect(fs.access(path.join(proj, 'b.txt'))).rejects.toThrow();
    const turns = await rt.checkpoints.listTurns();
    expect(turns[0]!.files.length).toBe(3);
    const diff = await rt.checkpoints.diff(0, proj);
    expect(diff).toContain('-original');
    expect(diff).toContain('+changed');

    // user edits a.txt by hand → conflict
    await fs.writeFile(path.join(proj, 'a.txt'), 'user edit\n');
    const r1 = await rt.checkpoints.rewind(0);
    expect(r1.conflicts.map((c) => path.basename(c.file))).toEqual(['a.txt']);
    expect(await fs.readFile(path.join(proj, 'a.txt'), 'utf8')).toBe('user edit\n');
    expect(await fs.readFile(path.join(proj, 'b.txt'), 'utf8')).toBe('keep me\n');
    await expect(fs.access(path.join(proj, 'new/c.txt'))).rejects.toThrow();
    const r2 = await rt.checkpoints.rewind(0, { force: true });
    expect(r2.restored.map((f) => path.basename(f))).toContain('a.txt');
    expect(await fs.readFile(path.join(proj, 'a.txt'), 'utf8')).toBe('original\n');
    await rt.shutdown();
  });

  it('requires read-before-edit and detects external modification', async () => {
    const proj = await makeProject({ 'f.txt': 'one\n' });
    const results: string[] = [];
    const s = track(
      await mockOpenAI(async (req) => {
        if (req.index > 0) results.push(req.toolResults[0]!.content);
        if (req.index === 0) return call('Edit', { file_path: 'f.txt', old_string: 'one', new_string: 'two' });
        if (req.index === 1) return call('Read', { file_path: 'f.txt' });
        if (req.index === 2) {
          await fs.writeFile(path.join(proj, 'f.txt'), 'one, modified by user\n');
          return call('Edit', { file_path: 'f.txt', old_string: 'one', new_string: 'two' });
        }
        return text('stop');
      }),
    );
    const rt = await runtimeFor(proj, openaiSettings(s.url), { permissionMode: 'acceptEdits' });
    await rt.submit('edit');
    expect(results[0]).toContain('must Read');
    expect(results[2]).toContain('modified since you last read it');
    await rt.shutdown();
  });
});

describe('context compaction', () => {
  it('auto-compacts when the context is nearly full and keeps working', async () => {
    const proj = await makeProject({});
    let compactPrompt = '';
    const s = track(
      await mockOpenAI((req) => {
        const isCompact = req.lastUserText.includes('<transcript>');
        if (isCompact) {
          compactPrompt = req.lastUserText;
          return { text: 'SUMMARY: user wants pineapples; decided to use TypeScript.', usage: { input: 500, output: 50 } };
        }
        return { text: `reply ${req.index}`, usage: { input: 9000, output: 100 } };
      }),
    );
    const settings = openaiSettings(s.url);
    (settings.providers!.mock!.models![0] as any).contextWindow = 20_000;
    (settings.providers!.mock!.models![0] as any).maxOutput = 2000;
    const rt = await runtimeFor(proj, { ...settings, autoCompactThreshold: 0.5 });
    const compacts: AgentEvent[] = [];
    rt.events.on('event', (e: AgentEvent) => e.type === 'compact' && compacts.push(e));
    await rt.submit('I like pineapples');
    await rt.submit('use typescript');
    await rt.submit('next');
    expect(compacts.length).toBeGreaterThanOrEqual(1);
    expect(compactPrompt).toContain('pineapples');
    expect(rt.main.messages[0]!.meta?.kind).toBe('compact-summary');
    expect(JSON.stringify(rt.main.messages)).toContain('SUMMARY: user wants pineapples');
    // the session file records the compaction and resumes from the summary
    const loaded = await rt.sessions.loadMessages(rt.session.id);
    expect(loaded.messages[0]!.meta?.kind).toBe('compact-summary');
    await rt.shutdown();
  });

  it('manual /compact with instructions', async () => {
    const proj = await makeProject({});
    const s = track(await mockOpenAI((req) => (req.lastUserText.includes('<transcript>') ? text(`S:${req.lastUserText.includes('focus on tests') ? 'focused' : 'plain'}`) : text('a'))));
    const rt = await runtimeFor(proj, openaiSettings(s.url));
    await rt.submit('hello');
    const out: string[] = [];
    await runSlash('/compact focus on tests', cmdCtx(rt, out));
    expect(rt.main.messages[0]!.content[0]).toMatchObject({ type: 'text' });
    expect(JSON.stringify(rt.main.messages[0])).toContain('S:focused');
    await rt.shutdown();
  });
});

describe('subagents', () => {
  it('runs several subagents in parallel with their own context and returns reports', async () => {
    const proj = await makeProject({ 'src/a.ts': 'export const a = 1;\n', 'src/b.ts': 'export const b = 2;\n' });
    const seenSubSystem: string[] = [];
    let concurrent = 0;
    let maxConcurrent = 0;
    const s = track(
      await mockOpenAI(async (req) => {
        const isSub = req.system.includes('You are a subagent');
        if (!isSub) {
          if (req.index === 0)
            return {
              tools: [
                { name: 'Task', args: { description: 'inspect a', prompt: 'Report the value exported from src/a.ts', subagent_type: 'explorer' } },
                { name: 'Task', args: { description: 'inspect b', prompt: 'Report the value exported from src/b.ts', subagent_type: 'explorer' } },
              ],
            };
          return text(req.toolResults.map((r) => r.content).join(' | '));
        }
        seenSubSystem.push(req.system);
        expect(req.toolNames).not.toContain('Task');
        expect(req.toolNames).not.toContain('Edit');
        const file = req.lastUserText.includes('a.ts') ? 'src/a.ts' : 'src/b.ts';
        if (!req.toolResults.length) {
          concurrent++;
          maxConcurrent = Math.max(maxConcurrent, concurrent);
          await new Promise((r) => setTimeout(r, 150));
          concurrent--;
          return call('Read', { file_path: file });
        }
        return text(`${file}: ${req.toolResults[0]!.content.split('\t')[1]}`);
      }),
    );
    const rt = await runtimeFor(proj, openaiSettings(s.url));
    const subEvents: AgentEvent[] = [];
    rt.events.on('event', (e: AgentEvent) => e.type === 'subagent' && subEvents.push(e));
    const r = await rt.submit('inspect both files using subagents');
    expect(r!.text).toContain('src/a.ts: export const a = 1;');
    expect(r!.text).toContain('src/b.ts: export const b = 2;');
    expect(maxConcurrent).toBe(2);
    expect(seenSubSystem[0]).toContain('Explorer');
    expect(subEvents.filter((e: any) => e.status === 'completed')).toHaveLength(2);
    expect(rt.subagents.listRuns().every((x) => x.status === 'completed')).toBe(true);
    await rt.shutdown();
  });

  it('read-only subagents cannot modify files and parallel writers get lock conflicts', async () => {
    const proj = await makeProject({ 'shared.txt': 'base\n' });
    const s = track(
      await mockOpenAI(async (req) => {
        const isSub = req.system.includes('You are a subagent');
        if (!isSub) {
          if (req.index === 0)
            return {
              tools: [
                { name: 'Task', args: { description: 'w1', prompt: 'write shared.txt as ONE', subagent_type: 'coder' } },
                { name: 'Task', args: { description: 'w2', prompt: 'write shared.txt as TWO', subagent_type: 'coder' } },
              ],
            };
          return text(req.toolResults.map((r) => r.content).join(' || '));
        }
        const val = req.lastUserText.includes('ONE') ? 'ONE' : 'TWO';
        if (!req.toolResults.length) {
          if (val === 'TWO') await new Promise((r) => setTimeout(r, 200));
          return call('Write', { file_path: 'shared-new.txt', content: val });
        }
        if (val === 'ONE') await new Promise((r) => setTimeout(r, 600));
        return text(`${val}: ${req.toolResults[0]!.content}`);
      }),
    );
    const rt = await runtimeFor(proj, openaiSettings(s.url), { permissionMode: 'acceptEdits' });
    const r = await rt.submit('two writers');
    expect(r!.text).toMatch(/owned by agent "coder-\d"/);
    await rt.shutdown();
  });
});

describe('plan mode', () => {
  it('blocks writes, presents the plan, and implements after approval', async () => {
    const proj = await makeProject({ 'app.txt': 'v1\n' });
    const results: string[] = [];
    const s = track(
      await mockOpenAI((req) => {
        if (req.index > 0) results.push(req.toolResults[0]?.content ?? '');
        switch (req.index) {
          case 0:
            expect(req.system).toContain('Plan mode is ACTIVE');
            return call('Write', { file_path: 'app.txt', content: 'v2' });
          case 1:
            return call('Read', { file_path: 'app.txt' });
          case 2:
            return call('ExitPlanMode', { plan: '## Plan\n1. Update app.txt to v2\n2. Verify' });
          case 3:
            return call('Write', { file_path: 'app.txt', content: 'v2\n' });
          default:
            return text('implemented');
        }
      }),
    );
    const rt = await runtimeFor(proj, openaiSettings(s.url), { permissionMode: 'plan' });
    let shownPlan = '';
    rt.handlers.planApproval = async (plan) => {
      shownPlan = plan;
      return { decision: 'approve', mode: 'acceptEdits' };
    };
    const r = await rt.submit('update the app to v2');
    expect(results[0]).toContain('plan mode is active');
    expect(shownPlan).toContain('Update app.txt');
    expect(results[2]).toContain('approved');
    expect(rt.permissions.mode).toBe('acceptEdits');
    expect(await fs.readFile(path.join(proj, 'app.txt'), 'utf8')).toBe('v2\n');
    expect(r!.text).toBe('implemented');
    await rt.shutdown();
  });
});

describe('interactive permission flow', () => {
  it('asks the user; allow_session creates a rule; deny returns feedback', async () => {
    const proj = await makeProject({ 'print.js': 'console.log("arg", process.argv[2]);' });
    const results: string[] = [];
    const s = track(
      await mockOpenAI((req) => {
        if (req.index > 0) results.push(req.toolResults[0]!.content);
        if (req.index === 0) return call('Bash', { command: 'node print.js 1' });
        if (req.index === 1) return call('Bash', { command: 'node print.js 2' });
        if (req.index === 2) return call('Write', { file_path: 'x.txt', content: 'x' });
        return text('end');
      }),
    );
    const rt = await runtimeFor(proj, openaiSettings(s.url));
    const asked: string[] = [];
    rt.handlers.permission = async (req) => {
      asked.push(req.tool);
      return req.tool === 'Bash' ? { decision: 'allow_session' } : { decision: 'deny', feedback: 'use a different filename' };
    };
    await rt.submit('go');
    expect(asked).toEqual(['Bash', 'Write']); // second Bash auto-allowed by session rule
    expect(results[0]).toContain('1');
    expect(results[1]).toContain('2');
    expect(results[2]).toContain('use a different filename');
    expect(rt.permissions.listRules().session).toContain('Bash(node print.js:*)');
    await rt.shutdown();
  });
});

describe('hooks', () => {
  it('runs PreToolUse (block via exit 2), PostToolUse context, UserPromptSubmit and Stop hooks', async () => {
    const proj = await makeProject({ 'ok.txt': 'fine' });
    const log = path.join(proj, 'hook.log');
    const node = process.execPath.replace(/\\/g, '/');
    const script = (code: string) => `"${node}" -e "${code.replace(/"/g, '\\"')}"`;
    const settings = openaiSettings('', {
      hooks: {
        UserPromptSubmit: [{ hooks: [{ type: 'command', command: script(`process.stdout.write('Remember: answer in English.')`) }] }],
        PreToolUse: [{ matcher: 'Bash', hooks: [{ type: 'command', command: script(`let d='';process.stdin.on('data',c=>d+=c).on('end',()=>{const j=JSON.parse(d);if(j.tool_input.command.includes('forbidden')){process.stderr.write('forbidden command');process.exit(2)}})`) }] }],
        PostToolUse: [{ matcher: 'Read', hooks: [{ type: 'command', command: script(`require('fs').appendFileSync(${JSON.stringify(log)},'post-read\\n')`) }] }],
        Stop: [{ hooks: [{ type: 'command', command: script(`let d='';process.stdin.on('data',c=>d+=c).on('end',()=>{const j=JSON.parse(d);if(!j.stop_hook_active){process.stderr.write('run the linter first');process.exit(2)}})`) }] }],
      },
    });
    const results: string[] = [];
    let sawReminder = false;
    let stopFeedback = false;
    const s = track(
      await mockOpenAI((req) => {
        if (req.index === 0) sawReminder = req.lastUserText.includes('Remember: answer in English.');
        if (req.toolResults[0]) results.push(req.toolResults[0].content);
        if (req.index === 0) return call('Bash', { command: 'echo forbidden' });
        if (req.index === 1) return call('Read', { file_path: 'ok.txt' });
        if (req.index === 2) return text('finished');
        stopFeedback = req.lastUserText.includes('run the linter first');
        return text('linted, finished');
      }),
    );
    settings.providers!.mock!.baseUrl = s.url;
    const rt = await runtimeFor(proj, settings, { permissionMode: 'bypassPermissions', trust: true });
    const r = await rt.submit('do it');
    expect(sawReminder).toBe(true);
    expect(results[0]).toContain('Blocked by PreToolUse hook: forbidden command');
    expect(await fs.readFile(log, 'utf8')).toContain('post-read');
    expect(stopFeedback).toBe(true);
    expect(r!.text).toBe('linted, finished');
    expect(rt.hooks.history.length).toBeGreaterThanOrEqual(4);
    await rt.shutdown();
  });

  it('ignores project hooks in untrusted folders', async () => {
    const proj = await makeProject({ '.stella/settings.json': JSON.stringify({ hooks: { UserPromptSubmit: [{ hooks: [{ type: 'command', command: 'echo INJECTED' }] }] } }) });
    let saw = false;
    const s = track(await mockOpenAI((req) => ((saw = req.lastUserText.includes('INJECTED')), text('x'))));
    const rt = await runtimeFor(proj, openaiSettings(s.url));
    expect(rt.trusted).toBe(false);
    await rt.submit('hi');
    expect(saw).toBe(false);
    expect(rt.warnings.join(' ')).toContain('trust');
    await rt.shutdown();
  });
});

describe('skills and custom commands', () => {
  it('lists skills in the prompt, loads them with the Skill tool, runs /commands', async () => {
    const proj = await makeProject({
      '.stella/skills/pdf-report/SKILL.md': '---\nname: pdf-report\ndescription: Generate PDF reports from CSV data files\n---\nUse scripts/render.py to render. Always add a title page.',
      '.stella/skills/pdf-report/scripts/render.py': 'print(1)',
      '.stella/commands/greet.md': '---\ndescription: greet someone\n---\nSay hello to $ARGUMENTS politely.',
    });
    let skillResult = '';
    let suggested = false;
    let commandPrompt = '';
    const s = track(
      await mockOpenAI((req) => {
        if (req.lastUserText.includes('Say hello to')) {
          commandPrompt = req.lastUserText;
          return text('Hello Bob!');
        }
        if (req.index === 0) {
          expect(req.system).toContain('pdf-report: Generate PDF reports');
          expect(req.system).toContain('react:');
          suggested = req.lastUserText.includes('skill "pdf-report" looks relevant');
          return call('Skill', { name: 'pdf-report' });
        }
        skillResult = req.toolResults[0]?.content ?? skillResult;
        return text('ok');
      }),
    );
    const rt = await runtimeFor(proj, openaiSettings(s.url));
    await rt.submit('create a PDF report from the sales CSV data');
    expect(suggested).toBe(true);
    expect(skillResult).toContain('Always add a title page');
    expect(skillResult).toContain('scripts/render.py');
    await runSlash('/greet Bob', cmdCtx(rt));
    expect(commandPrompt).toContain('Say hello to Bob politely');
    // create & delete via /skills
    const out: string[] = [];
    await runSlash('/skills create my-flow Handles my flow', cmdCtx(rt, out));
    expect(rt.skills.get('my-flow')).toBeTruthy();
    await runSlash('/skills delete my-flow', cmdCtx(rt, out));
    expect(rt.skills.get('my-flow')).toBeUndefined();
    await rt.shutdown();
  });
});

describe('memory', () => {
  it('stores durable memories, refuses secrets, deduplicates and injects into the prompt', async () => {
    const proj = await makeProject({});
    let systemHasMemory = false;
    const results: string[] = [];
    const s = track(
      await mockOpenAI((req) => {
        if (req.toolResults[0]) results.push(req.toolResults[0].content);
        if (req.index === 0) return call('Memory', { action: 'add', type: 'user', content: 'Prefers tabs over spaces' });
        if (req.index === 1) return call('Memory', { action: 'add', type: 'user', content: 'prefers tabs over spaces.' });
        if (req.index === 2) return call('Memory', { action: 'add', type: 'project', content: 'api_key = sk-ant-api03-SECRETSECRETSECRET123' });
        if (req.index === 3) return text('saved');
        systemHasMemory = req.system.includes('Prefers tabs over spaces');
        return text('hi');
      }),
    );
    const rt = await runtimeFor(proj, openaiSettings(s.url));
    await rt.submit('remember my prefs');
    expect(results[0]).toContain('Saved memory');
    expect(results[1]).toContain('Already remembered');
    expect(results[2]).toContain('secret');
    await rt.shutdown();
    const rt2 = await runtimeFor(proj, openaiSettings(s.url));
    await rt2.submit('hello');
    expect(systemHasMemory).toBe(true);
    const items = await rt2.memory.list('user');
    expect(items).toHaveLength(1);
    await rt2.memory.remove(items[0]!.id);
    expect(await rt2.memory.list('user')).toHaveLength(0);
    await rt2.shutdown();
  });

  it('loads STELLA.md hierarchy with @imports', async () => {
    const proj = await makeProject({ 'STELLA.md': '# Rules\nUse pnpm.\n@docs/style.md\n', 'docs/style.md': 'Never use var.', '.git/HEAD': 'ref: refs/heads/main\n', 'pkg/STELLA.md': 'Package rule.' });
    await fs.writeFile(path.join(home, 'STELLA.md'), 'Global: be brief.');
    let sys = '';
    const s = track(await mockOpenAI((req) => ((sys = req.system), text('x'))));
    const rt = await runtimeFor(path.join(proj, 'pkg'), openaiSettings(s.url));
    await rt.submit('hi');
    expect(sys).toContain('Use pnpm.');
    expect(sys).toContain('Never use var.');
    expect(sys).toContain('Package rule.');
    expect(sys).toContain('Global: be brief.');
    await rt.shutdown();
  });
});

describe('git integration', () => {
  it('status, diff, branch and commit through tools; never pushes', async () => {
    const proj = await makeProject({ 'readme.md': 'v1\n' });
    const g = (...a: string[]) => execFileSync('git', a, { cwd: proj, stdio: 'pipe' }).toString();
    g('init', '-q', '-b', 'main');
    g('-c', 'user.email=t@t', '-c', 'user.name=t', 'add', '.');
    g('-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'init');
    await fs.writeFile(path.join(proj, 'readme.md'), 'v2\n');
    const results: string[] = [];
    const s = track(
      await mockOpenAI((req) => {
        if (req.toolResults[0]) results.push(req.toolResults[0].content);
        switch (req.index) {
          case 0:
            return { tools: [{ name: 'GitStatus', args: {} }, { name: 'GitDiff', args: {} }] };
          case 1:
            results.push(req.toolResults[1]!.content);
            return call('GitBranch', { action: 'create', name: 'feature/x' });
          case 2:
            return call('GitCommit', { message: 'Update readme to v2', files: ['readme.md'] });
          case 3:
            return call('GitLog', { limit: 5 });
          default:
            return text('committed');
        }
      }),
    );
    process.env.GIT_AUTHOR_NAME = process.env.GIT_COMMITTER_NAME = 'Test';
    process.env.GIT_AUTHOR_EMAIL = process.env.GIT_COMMITTER_EMAIL = 't@example.com';
    const rt = await runtimeFor(proj, openaiSettings(s.url), { permissionMode: 'acceptEdits', allowedTools: ['GitBranch', 'GitCommit'] });
    expect(await rt.systemPrompt()).toContain('Branch: main');
    await rt.submit('commit my change on a branch');
    expect(results[0]).toContain('Unstaged (1)');
    expect(results[1]).toContain('+v2');
    expect(results[3]).toContain('Committed');
    expect(results[4]).toContain('Update readme to v2');
    expect(g('branch', '--show-current').trim()).toBe('feature/x');
    expect(rt.allTools().some((t) => /push/i.test(t.name))).toBe(false);
    await rt.shutdown();
  });
});

describe('multiple providers', () => {
  it('Anthropic adapter (official SDK) streams, runs tools and replays thinking blocks unchanged', async () => {
    const proj = await makeProject({ 'n.txt': '42' });
    const s = track(
      await mockAnthropic((req) => {
        if (req.index === 0) {
          expect(req.body.tools[0].eager_input_streaming).toBe(true);
          expect(req.body.cache_control).toEqual({ type: 'ephemeral' });
          expect(req.body.output_config).toEqual({ effort: 'high' });
          return call('Read', { file_path: 'n.txt' }, 'Reading.');
        }
        const assistant = req.body.messages[1];
        expect(assistant.content[0]).toMatchObject({ type: 'thinking', signature: 'sig-0' });
        return text(`value=${req.toolResults[0]!.content.split('\t')[1]}`);
      }),
    );
    process.env.ANTHROPIC_BASE_URL = s.url;
    const rt = await runtimeFor(proj, { anthropicFallbacks: false, providers: { anthropic: { type: 'anthropic', apiKey: 'sk-ant-test' } } }, { model: 'sonnet' });
    const r = await rt.submit('read n.txt');
    delete process.env.ANTHROPIC_BASE_URL;
    expect(r!.text).toBe('value=42');
    expect(rt.session.costUsd).toBeGreaterThan(0);
    await rt.shutdown();
  });

  it('Anthropic adapter sends server-side fallbacks on supported models', async () => {
    const proj = await makeProject({});
    const s = track(
      await mockAnthropic((req) => {
        expect(req.body.fallbacks).toBe('default');
        return text('ok');
      }),
    );
    process.env.ANTHROPIC_BASE_URL = s.url;
    const rt = await runtimeFor(proj, { providers: { anthropic: { type: 'anthropic', apiKey: 'sk-ant-test' } } }, { model: 'opus' });
    expect((await rt.submit('hi'))!.text).toBe('ok');
    delete process.env.ANTHROPIC_BASE_URL;
    await rt.shutdown();
  });

  it('Gemini adapter streams function calls and results', async () => {
    const proj = await makeProject({ 'g.txt': 'gem' });
    const s = track(
      await mockGemini((req) => {
        if (req.index === 0) {
          expect(req.toolNames).toContain('Read');
          expect(JSON.stringify(req.body.tools)).not.toContain('additionalProperties');
          return call('Read', { file_path: 'g.txt' });
        }
        return text(`got ${req.toolResults[0]!.content.split('\t')[1]}`);
      }),
    );
    const rt = await runtimeFor(proj, { providers: { gemini: { type: 'gemini', baseUrl: s.url, apiKey: 'g-test' } } }, { model: 'flash' });
    expect((await rt.submit('read g'))!.text).toBe('got gem');
    await rt.shutdown();
  });

  it('switches models mid-session and keeps the conversation', async () => {
    const proj = await makeProject({});
    const a = track(await mockOpenAI(() => text('from A')));
    const b = track(await mockGemini((req) => text(`from B, history=${JSON.stringify(req.body.contents).includes('from A')}`)));
    const settings = openaiSettings(a.url, { providers: { ...openaiSettings(a.url).providers, gemini: { type: 'gemini', baseUrl: b.url, apiKey: 'k' } } });
    const rt = await runtimeFor(proj, settings);
    expect((await rt.submit('one'))!.text).toBe('from A');
    rt.switchModel('gemini:gemini-2.5-flash');
    expect((await rt.submit('two'))!.text).toBe('from B, history=true');
    await rt.shutdown();
  });
});

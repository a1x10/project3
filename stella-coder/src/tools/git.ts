import { promises as fs } from 'node:fs';
import path from 'node:path';
import { z } from 'zod';
import { git, gitStatus } from '../git/git.js';
import { truncate } from '../utils/fsutil.js';
import { defineTool, ToolError } from './types.js';

const ro = (summary: string) => ({ kind: 'read' as const, risk: 'low' as const, readOnly: true, summary });

export const GitStatusTool = defineTool({
  name: 'GitStatus',
  description: 'Show git status: branch, upstream ahead/behind, staged, unstaged, untracked and conflicted files.',
  kind: 'read',
  concurrencySafe: true,
  schema: z.object({}),
  describe: () => ro('git status'),
  async run(_i, ctx) {
    const s = await gitStatus(ctx.cwd);
    if (!s) throw new ToolError('Not a git repository (or git is not installed).');
    const lines = [`Branch: ${s.branch ?? '(detached)'}${s.upstream ? ` → ${s.upstream} (ahead ${s.ahead}, behind ${s.behind})` : ' (no upstream)'}`];
    const sec = (name: string, xs: string[]) => xs.length && lines.push(`${name} (${xs.length}):`, ...xs.slice(0, 200).map((x) => '  ' + x));
    sec('Conflicted', s.conflicted);
    sec('Staged', s.staged);
    sec('Unstaged', s.unstaged);
    sec('Untracked', s.untracked);
    if (!s.staged.length && !s.unstaged.length && !s.untracked.length && !s.conflicted.length) lines.push('Working tree clean.');
    if (s.conflicted.length) {
      for (const f of s.conflicted.slice(0, 20)) {
        const text = await fs.readFile(path.join(ctx.cwd, f), 'utf8').catch(() => '');
        const n = (text.match(/^<<<<<<< /gm) ?? []).length;
        lines.push(`  ${f}: ${n} conflict region(s)`);
      }
    }
    return { content: lines.join('\n') };
  },
});

export const GitDiffTool = defineTool({
  name: 'GitDiff',
  description: 'Show git diff. staged=true for the index, ref to compare against a commit/branch, path to limit to files.',
  kind: 'read',
  concurrencySafe: true,
  schema: z.object({ staged: z.boolean().optional(), ref: z.string().optional(), path: z.string().optional(), stat: z.boolean().optional() }),
  describe: (i) => ro(`git diff ${i.ref ?? ''}`),
  async run(i, ctx) {
    if (i.ref && /^-/.test(i.ref)) throw new ToolError('Invalid ref');
    const args = ['diff', '--no-ext-diff'];
    if (i.staged) args.push('--cached');
    if (i.stat) args.push('--stat');
    if (i.ref) args.push(i.ref);
    if (i.path) args.push('--', i.path);
    const r = await git(args, ctx.cwd, ctx.signal);
    if (!r.ok) throw new ToolError(r.stderr || 'git diff failed');
    return { content: truncate(r.stdout, 40_000) || 'No differences.', display: { kind: 'diff', title: 'git diff', body: truncate(r.stdout, 6000) } };
  },
});

export const GitLogTool = defineTool({
  name: 'GitLog',
  description: 'Show recent commits (hash, author, date, subject). Optionally for a path or ref.',
  kind: 'read',
  concurrencySafe: true,
  schema: z.object({ limit: z.number().int().min(1).max(200).optional(), path: z.string().optional(), ref: z.string().optional() }),
  describe: () => ro('git log'),
  async run(i, ctx) {
    if (i.ref && /^-/.test(i.ref)) throw new ToolError('Invalid ref');
    const args = ['log', `-n${i.limit ?? 20}`, '--date=short', '--pretty=format:%h %ad %an  %s'];
    if (i.ref) args.push(i.ref);
    if (i.path) args.push('--', i.path);
    const r = await git(args, ctx.cwd, ctx.signal);
    if (!r.ok) throw new ToolError(r.stderr || 'git log failed');
    return { content: r.stdout || 'No commits.' };
  },
});

export const GitBranchTool = defineTool({
  name: 'GitBranch',
  description: 'List branches, create a new branch, or switch to an existing one. Never deletes branches.',
  kind: 'write',
  schema: z.object({ action: z.enum(['list', 'create', 'switch']), name: z.string().optional(), from: z.string().optional() }),
  describe: (i) => (i.action === 'list' ? ro('git branch') : { kind: 'write', risk: 'medium', readOnly: false, summary: `git ${i.action} branch ${i.name ?? ''}` }),
  async run(i, ctx) {
    if (i.action === 'list') {
      const r = await git(['branch', '-vv', '--all'], ctx.cwd);
      return { content: r.stdout || r.stderr };
    }
    if (!i.name || !/^[\w./-]+$/.test(i.name) || i.name.startsWith('-')) throw new ToolError('Valid branch name required');
    const args = i.action === 'create' ? ['switch', '-c', i.name, ...(i.from ? [i.from] : [])] : ['switch', i.name];
    const r = await git(args, ctx.cwd);
    if (!r.ok) throw new ToolError(r.stderr.trim());
    return { content: (r.stdout + r.stderr).trim() || `On branch ${i.name}` };
  },
});

export const GitCommitTool = defineTool({
  name: 'GitCommit',
  description:
    'Stage files and create a commit. Provide explicit `files` (preferred) or all=true to stage every tracked change. Writes a clear message: short imperative subject (<72 chars), blank line, body explaining why. Never pushes.',
  kind: 'write',
  schema: z.object({ message: z.string().min(3), files: z.array(z.string()).optional(), all: z.boolean().optional() }),
  describe: (i) => ({ kind: 'write', risk: 'medium', readOnly: false, summary: `git commit: ${i.message.split('\n')[0]}` }),
  async run(i, ctx) {
    if (i.files?.length) {
      if (i.files.some((f) => f.startsWith('-'))) throw new ToolError('Invalid file name');
      const a = await git(['add', '--', ...i.files], ctx.cwd);
      if (!a.ok) throw new ToolError(a.stderr.trim());
    } else if (i.all) {
      const a = await git(['add', '-u'], ctx.cwd);
      if (!a.ok) throw new ToolError(a.stderr.trim());
    }
    const r = await git(['commit', '-m', i.message], ctx.cwd);
    if (!r.ok) throw new ToolError((r.stdout + r.stderr).trim() || 'commit failed');
    const h = await git(['log', '-1', '--pretty=format:%h %s'], ctx.cwd);
    return { content: `Committed ${h.stdout}\n${r.stdout.trim()}` };
  },
});

export const gitTools = [GitStatusTool, GitDiffTool, GitLogTool, GitBranchTool, GitCommitTool];

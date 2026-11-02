import { execProgram } from '../tools/process.js';
import { which } from '../utils/which.js';

export interface GitResult {
  ok: boolean;
  stdout: string;
  stderr: string;
  code: number | null;
}

export async function git(args: string[], cwd: string, signal?: AbortSignal, timeoutMs = 60_000): Promise<GitResult> {
  if (!which('git')) return { ok: false, stdout: '', stderr: 'git is not installed', code: null };
  const r = await execProgram('git', ['-c', 'core.quotepath=off', '-c', 'color.ui=never', ...args], { cwd, timeoutMs, signal });
  return { ok: r.exitCode === 0, stdout: r.stdout, stderr: r.stderr, code: r.exitCode };
}

export async function isGitRepo(cwd: string): Promise<boolean> {
  const r = await git(['rev-parse', '--is-inside-work-tree'], cwd);
  return r.ok && r.stdout.trim() === 'true';
}

export interface GitStatusInfo {
  branch: string | null;
  upstream: string | null;
  ahead: number;
  behind: number;
  staged: string[];
  unstaged: string[];
  untracked: string[];
  conflicted: string[];
}

export async function gitStatus(cwd: string): Promise<GitStatusInfo | null> {
  const r = await git(['status', '--porcelain=v2', '--branch'], cwd);
  if (!r.ok) return null;
  const info: GitStatusInfo = { branch: null, upstream: null, ahead: 0, behind: 0, staged: [], unstaged: [], untracked: [], conflicted: [] };
  for (const line of r.stdout.split('\n')) {
    if (line.startsWith('# branch.head ')) info.branch = line.slice(14).trim();
    else if (line.startsWith('# branch.upstream ')) info.upstream = line.slice(18).trim();
    else if (line.startsWith('# branch.ab ')) {
      const m = /\+(\d+) -(\d+)/.exec(line);
      if (m) {
        info.ahead = Number(m[1]);
        info.behind = Number(m[2]);
      }
    } else if (line.startsWith('1 ') || line.startsWith('2 ')) {
      const parts = line.split(' ');
      const xy = parts[1]!;
      const file = line.startsWith('2 ') ? line.split('\t')[0]!.split(' ').slice(9).join(' ') : parts.slice(8).join(' ');
      if (xy[0] !== '.') info.staged.push(file);
      if (xy[1] !== '.') info.unstaged.push(file);
    } else if (line.startsWith('u ')) info.conflicted.push(line.split(' ').slice(10).join(' '));
    else if (line.startsWith('? ')) info.untracked.push(line.slice(2));
  }
  return info;
}

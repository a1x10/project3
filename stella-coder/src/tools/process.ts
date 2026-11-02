import { spawn, spawnSync, type ChildProcess } from 'node:child_process';
import { which } from '../utils/which.js';

export interface ShellSpec {
  file: string;
  args: (cmd: string) => string[];
  kind: 'posix' | 'powershell' | 'cmd';
}

let cachedBash: ShellSpec | null | undefined;
export function bashShell(preferred?: string): ShellSpec | null {
  if (preferred) return { file: preferred, args: (c) => ['-c', c], kind: 'posix' };
  if (cachedBash !== undefined) return cachedBash;
  if (process.platform === 'win32') {
    const gitBash = which('bash') ?? (['C:\\Program Files\\Git\\bin\\bash.exe'].find((p) => spawnSync(p, ['--version']).status === 0) || null);
    cachedBash = gitBash ? { file: gitBash, args: (c) => ['-c', c], kind: 'posix' } : null;
  } else {
    const sh = process.env.SHELL && /(bash|zsh)$/.test(process.env.SHELL) ? process.env.SHELL : which('bash') ?? '/bin/sh';
    cachedBash = { file: sh, args: (c) => ['-c', c], kind: 'posix' };
  }
  return cachedBash;
}

export function powershellShell(): ShellSpec | null {
  const ps = which('pwsh') ?? (process.platform === 'win32' ? which('powershell') : null);
  return ps ? { file: ps, args: (c) => ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', c], kind: 'powershell' } : null;
}

export function cmdShell(): ShellSpec | null {
  if (process.platform !== 'win32') return null;
  return { file: process.env.ComSpec ?? 'cmd.exe', args: (c) => ['/d', '/s', '/c', c], kind: 'cmd' };
}

export function safeEnv(extra?: Record<string, string>): NodeJS.ProcessEnv {
  return {
    ...process.env,
    ...(extra ?? {}),
    STELLA_CODER: '1',
    GIT_TERMINAL_PROMPT: '0',
    GIT_PAGER: 'cat',
    PAGER: 'cat',
    npm_config_yes: process.env.npm_config_yes ?? 'false',
    NO_UPDATE_NOTIFIER: '1',
  };
}

/** Kill a process and all of its children. */
export function killTree(child: ChildProcess, signal: NodeJS.Signals = 'SIGTERM') {
  if (child.pid === undefined || child.exitCode !== null) return;
  if (process.platform === 'win32') {
    try {
      spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], { windowsHide: true });
    } catch {
      child.kill();
    }
    return;
  }
  try {
    process.kill(-child.pid, signal);
  } catch {
    try {
      child.kill(signal);
    } catch {
      /* gone */
    }
  }
  if (signal === 'SIGTERM') {
    const t = setTimeout(() => {
      try {
        process.kill(-child.pid!, 'SIGKILL');
      } catch {
        /* gone */
      }
    }, 2000);
    t.unref();
  }
}

export interface ExecOptions {
  cwd: string;
  timeoutMs: number;
  signal?: AbortSignal;
  env?: Record<string, string>;
  onOutput?: (chunk: string, stream: 'stdout' | 'stderr') => void;
  maxBuffer?: number;
  input?: string;
}

export interface ExecResult {
  stdout: string;
  stderr: string;
  exitCode: number | null;
  signal: string | null;
  timedOut: boolean;
  aborted: boolean;
  durationMs: number;
}

/** Run a program (no shell interpolation of args) with streaming output, timeout and tree-kill. */
export function execProgram(file: string, args: string[], opts: ExecOptions): Promise<ExecResult> {
  const started = Date.now();
  const max = opts.maxBuffer ?? 2_000_000;
  return new Promise((resolve, reject) => {
    let child: ChildProcess;
    try {
      child = spawn(file, args, {
        cwd: opts.cwd,
        env: safeEnv(opts.env),
        stdio: [opts.input !== undefined ? 'pipe' : 'ignore', 'pipe', 'pipe'],
        detached: process.platform !== 'win32',
        windowsHide: true,
      });
    } catch (e) {
      return reject(e);
    }
    if (opts.input !== undefined && child.stdin) {
      child.stdin.on('error', () => {});
      child.stdin.end(opts.input);
    }
    let stdout = '';
    let stderr = '';
    let timedOut = false;
    let aborted = false;
    const add = (which: 'stdout' | 'stderr') => (d: Buffer) => {
      const s = d.toString('utf8');
      if (which === 'stdout') stdout = stdout.length < max ? stdout + s : stdout;
      else stderr = stderr.length < max ? stderr + s : stderr;
      opts.onOutput?.(s, which);
    };
    child.stdout!.on('data', add('stdout'));
    child.stderr!.on('data', add('stderr'));
    const timer = setTimeout(() => {
      timedOut = true;
      killTree(child);
    }, opts.timeoutMs);
    const onAbort = () => {
      aborted = true;
      killTree(child);
    };
    opts.signal?.addEventListener('abort', onAbort, { once: true });
    child.on('error', (e) => {
      clearTimeout(timer);
      opts.signal?.removeEventListener('abort', onAbort);
      reject(e);
    });
    child.on('close', (code, sig) => {
      clearTimeout(timer);
      opts.signal?.removeEventListener('abort', onAbort);
      resolve({ stdout, stderr, exitCode: code, signal: sig, timedOut, aborted, durationMs: Date.now() - started });
    });
  });
}

export interface BackgroundProcess {
  id: string;
  command: string;
  cwd: string;
  pid?: number;
  startedAt: number;
  status: 'running' | 'exited' | 'killed' | 'failed';
  exitCode: number | null;
  output: string; // ring buffer
  readOffset: number; // absolute offset already returned to the model
  dropped: number; // bytes dropped from the front of the ring
  child: ChildProcess;
}

/** Long-running processes (dev servers, watchers) started by the agent. */
export class ProcessManager {
  private procs = new Map<string, BackgroundProcess>();
  private seq = 0;
  readonly history: Array<{ command: string; exitCode: number | null; durationMs: number; ts: number; agentId: string }> = [];
  ringSize = 200_000;

  start(command: string, shell: ShellSpec, cwd: string, env?: Record<string, string>): BackgroundProcess {
    const id = `bg${++this.seq}`;
    const child = spawn(shell.file, shell.args(command), { cwd, env: safeEnv(env), stdio: ['ignore', 'pipe', 'pipe'], detached: process.platform !== 'win32', windowsHide: true });
    const p: BackgroundProcess = { id, command, cwd, pid: child.pid, startedAt: Date.now(), status: 'running', exitCode: null, output: '', readOffset: 0, dropped: 0, child };
    const add = (d: Buffer) => {
      p.output += d.toString('utf8');
      if (p.output.length > this.ringSize) {
        const cut = p.output.length - this.ringSize;
        p.output = p.output.slice(cut);
        p.dropped += cut;
      }
    };
    child.stdout!.on('data', add);
    child.stderr!.on('data', add);
    child.on('error', (e) => {
      p.status = 'failed';
      p.output += `\n[spawn error] ${e.message}`;
    });
    child.on('close', (code) => {
      if (p.status === 'running') p.status = 'exited';
      p.exitCode = code;
    });
    this.procs.set(id, p);
    return p;
  }

  get(id: string) {
    return this.procs.get(id);
  }
  list() {
    return [...this.procs.values()];
  }

  /** Output produced since the last read. */
  readNew(id: string): string {
    const p = this.procs.get(id);
    if (!p) return '';
    const start = Math.max(0, p.readOffset - p.dropped);
    const out = p.output.slice(start);
    p.readOffset = p.dropped + p.output.length;
    return out;
  }

  stop(id: string): boolean {
    const p = this.procs.get(id);
    if (!p || p.status !== 'running') return false;
    p.status = 'killed';
    killTree(p.child);
    return true;
  }

  stopAll() {
    for (const p of this.procs.values()) if (p.status === 'running') this.stop(p.id);
  }
}

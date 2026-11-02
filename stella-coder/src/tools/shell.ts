import path from 'node:path';
import { z } from 'zod';
import { analyzeShell } from '../permissions/shell.js';
import type { PermissionDescriptor } from '../permissions/engine.js';
import { isWithin } from '../security/paths.js';
import { truncate } from '../utils/fsutil.js';
import { bashShell, cmdShell, execProgram, powershellShell, type ShellSpec } from './process.js';
import { rp, relDisplay } from './fs.js';
import { defineTool, ToolError, type ToolContext, type ToolResult } from './types.js';

const MAX_OUTPUT = 30_000;
const CWD_MARK = '__STELLA_CWD__';

export function shellDesc(cmd: string, label: string, ctx?: ToolContext): PermissionDescriptor {
  const a = analyzeShell(cmd);
  const d: PermissionDescriptor = { kind: 'execute', risk: a.risk, readOnly: a.readOnly, command: cmd, summary: `${label}: ${cmd.length > 160 ? cmd.slice(0, 160) + '…' : cmd}` };
  if (ctx) {
    // Commands touching confidential files (cat .env, cp id_rsa …) must not bypass the
    // confidentiality prompt just because the command itself is read-only.
    const conf = confidentialRefs(cmd, ctx);
    if (conf.length) d.paths = conf;
  }
  return d;
}

function confidentialRefs(cmd: string, ctx: ToolContext) {
  const tokens = cmd.match(/"[^"]*"|'[^']*'|[^\s;&|<>()]+/g) ?? [];
  const out = [];
  for (const raw of tokens.slice(0, 200)) {
    const t = raw.replace(/^["']|["']$/g, '').replace(/^[<>]+/, '');
    if (!t || t.startsWith('-') || t.length > 400 || !/[./\\]|^~|key|env|secret|credential|id_/i.test(t)) continue;
    try {
      const r = rp(ctx, t);
      if (r.isConfidential) out.push(r);
    } catch {
      /* not a path */
    }
  }
  return out;
}

function timeoutOf(ctx: ToolContext, ms?: number) {
  const def = ctx.services.settings?.commandTimeoutMs ?? 120_000;
  return Math.min(ms ?? def, 600_000);
}

export function formatExec(r: { stdout: string; stderr: string; exitCode: number | null; timedOut: boolean; aborted: boolean; durationMs: number }, timeoutMs: number): ToolResult {
  const parts: string[] = [];
  if (r.stdout.trim()) parts.push(r.stdout.trimEnd());
  if (r.stderr.trim()) parts.push((parts.length ? '\n[stderr]\n' : '[stderr]\n') + r.stderr.trimEnd());
  let status = `Exit code: ${r.exitCode ?? 'none'} (${(r.durationMs / 1000).toFixed(1)}s)`;
  if (r.timedOut) status = `Command timed out after ${timeoutMs / 1000}s and was killed. For long-running processes use StartProcess.`;
  if (r.aborted) status = 'Command was interrupted by the user.';
  const body = truncate(parts.join('\n'), MAX_OUTPUT);
  const isError = r.timedOut || r.aborted || (r.exitCode !== 0 && r.exitCode !== null);
  return { content: `${body ? body + '\n' : '(no output)\n'}${status}`, isError, display: { kind: 'command', title: status, body: truncate(parts.join('\n'), 4000) } };
}

async function runInShell(shell: ShellSpec, command: string, ctx: ToolContext, timeoutMs: number, trackCwd: boolean): Promise<ToolResult> {
  const cwd = ctx.services.shellCwd?.get(ctx.agentId) ?? ctx.cwd;
  const wrapped = trackCwd && shell.kind === 'posix' ? `${command}\n__stella_ec=$?; printf '\\n${CWD_MARK}%s\\n' "$PWD" >&2; exit $__stella_ec` : command;
  const r = await execProgram(shell.file, shell.args(wrapped), {
    cwd,
    timeoutMs,
    signal: ctx.signal,
    env: ctx.services.settings?.env,
    onOutput: (chunk, s) => {
      if (!chunk.includes(CWD_MARK)) ctx.progress(s === 'stderr' ? chunk : chunk);
    },
  });
  let note = '';
  if (trackCwd) {
    const m = new RegExp(`\\n?${CWD_MARK}(.*)\\n?`).exec(r.stderr);
    if (m) {
      r.stderr = r.stderr.replace(m[0], '');
      const newCwd = toNativePath(m[1]!.trim());
      if (newCwd && path.resolve(newCwd) !== path.resolve(cwd)) {
        if (ctx.roots.some((root) => isWithin(newCwd, root))) {
          ctx.services.shellCwd?.set(ctx.agentId, newCwd);
          note = `\n[cwd is now ${relDisplay(ctx, newCwd) || '.'}]`;
        } else {
          ctx.services.shellCwd?.set(ctx.agentId, ctx.root);
          note = `\n[cwd outside the workspace is not persisted; reset to project root]`;
        }
      }
    }
  }
  ctx.services.processes?.history.push({ command, exitCode: r.exitCode, durationMs: r.durationMs, ts: Date.now(), agentId: ctx.agentId });
  const res = formatExec(r, timeoutMs);
  res.content += note;
  return res;
}

/** Git-Bash on Windows prints /c/Users/...; convert to C:\Users\... */
function toNativePath(p: string): string {
  if (process.platform === 'win32') {
    const m = /^\/([a-zA-Z])\/(.*)$/.exec(p);
    if (m) return `${m[1]!.toUpperCase()}:\\${m[2]!.replace(/\//g, '\\')}`;
  }
  return p;
}

const commandSchema = z.object({
  command: z.string().min(1),
  timeout: z.number().int().min(1000).max(600_000).optional().describe('Timeout in ms (default 120000, max 600000)'),
  description: z.string().optional().describe('Short description of what the command does (5-10 words)'),
});

export const BashTool = defineTool({
  name: 'Bash',
  description:
    'Execute a shell command (bash/zsh; Git Bash on Windows) in the project. The working directory persists between calls (within the workspace). Output is streamed and truncated to 30k chars. Use dedicated tools (Read, Grep, Glob, Edit) instead of cat/grep/sed when possible. For servers and watchers use StartProcess.',
  kind: 'execute',
  schema: commandSchema,
  isEnabled: (s) => !!bashShell(s.settings?.shell),
  describe: (i, ctx) => shellDesc(i.command, 'Run', ctx),
  async run(i, ctx) {
    const sh = bashShell(ctx.services.settings?.shell);
    if (!sh) throw new ToolError('No bash-compatible shell found. On Windows install Git for Windows or use the PowerShell tool.');
    return runInShell(sh, i.command, ctx, timeoutOf(ctx, i.timeout), true);
  },
});

export const PowerShellTool = defineTool({
  name: 'PowerShell',
  description: 'Execute a PowerShell command (pwsh, or Windows PowerShell). Use on Windows for native commands.',
  kind: 'execute',
  schema: commandSchema,
  isEnabled: () => !!powershellShell(),
  describe: (i, ctx) => shellDesc(i.command, 'PowerShell', ctx),
  async run(i, ctx) {
    const sh = powershellShell();
    if (!sh) throw new ToolError('PowerShell is not installed.');
    return runInShell(sh, i.command, ctx, timeoutOf(ctx, i.timeout), false);
  },
});

export const CmdTool = defineTool({
  name: 'Cmd',
  description: 'Execute a command with Windows cmd.exe.',
  kind: 'execute',
  schema: commandSchema,
  isEnabled: () => process.platform === 'win32',
  describe: (i, ctx) => shellDesc(i.command, 'cmd', ctx),
  async run(i, ctx) {
    const sh = cmdShell();
    if (!sh) throw new ToolError('cmd.exe is only available on Windows.');
    return runInShell(sh, i.command, ctx, timeoutOf(ctx, i.timeout), false);
  },
});

export const RunCommandTool = defineTool({
  name: 'RunCommand',
  description: 'Run a program directly with an argument array (no shell, so no globbing/piping/injection). Preferred for commands built from untrusted strings.',
  kind: 'execute',
  schema: z.object({ program: z.string(), args: z.array(z.string()).default([]), cwd: z.string().optional(), timeout: z.number().int().min(1000).max(600_000).optional() }),
  describe: (i, ctx) => shellDesc([i.program, ...(i.args ?? []).map((a) => (/\s/.test(a) ? JSON.stringify(a) : a))].join(' '), 'Run', ctx),
  async run(i, ctx) {
    const cwd = i.cwd ? rp(ctx, i.cwd).real : ctx.cwd;
    const t = timeoutOf(ctx, i.timeout);
    const r = await execProgram(i.program, i.args ?? [], { cwd, timeoutMs: t, signal: ctx.signal, env: ctx.services.settings?.env, onOutput: (c) => ctx.progress(c) }).catch((e) => {
      throw new ToolError(`Failed to start ${i.program}: ${(e as Error).message}`);
    });
    ctx.services.processes?.history.push({ command: `${i.program} ${(i.args ?? []).join(' ')}`, exitCode: r.exitCode, durationMs: r.durationMs, ts: Date.now(), agentId: ctx.agentId });
    return formatExec(r, t);
  },
});

const INTERPRETERS: Record<string, string[]> = {
  '.py': [process.platform === 'win32' ? 'python' : 'python3'],
  '.js': ['node'],
  '.mjs': ['node'],
  '.cjs': ['node'],
  '.ts': ['npx', '--no-install', 'tsx'],
  '.sh': ['bash'],
  '.ps1': ['pwsh', '-NoProfile', '-File'],
  '.rb': ['ruby'],
  '.php': ['php'],
  '.bat': ['cmd.exe', '/c'],
  '.cmd': ['cmd.exe', '/c'],
};

export const RunScriptTool = defineTool({
  name: 'RunScript',
  description: 'Run a script file with the interpreter matching its extension (.py, .js, .ts, .sh, .ps1, .rb, .php, .bat).',
  kind: 'execute',
  schema: z.object({ path: z.string(), args: z.array(z.string()).optional(), timeout: z.number().int().min(1000).max(600_000).optional() }),
  describe: (i, ctx) => {
    const r = rp(ctx, i.path);
    return { kind: 'execute', risk: r.inWorkspace ? 'medium' : 'high', readOnly: false, command: `script ${i.path} ${(i.args ?? []).join(' ')}`.trim(), summary: `Run script ${relDisplay(ctx, r.abs)}`, paths: [r] };
  },
  async run(i, ctx) {
    const r = rp(ctx, i.path);
    const interp = INTERPRETERS[path.extname(r.real).toLowerCase()];
    if (!interp) throw new ToolError(`No interpreter known for ${path.extname(r.real) || 'files without extension'}; use Bash.`);
    let [prog, ...pre] = interp;
    if (prog === 'pwsh' && !powershellShell()) throw new ToolError('PowerShell not installed.');
    if (prog === 'pwsh') prog = powershellShell()!.file;
    const t = timeoutOf(ctx, i.timeout);
    const res = await execProgram(prog!, [...pre, r.real, ...(i.args ?? [])], { cwd: ctx.cwd, timeoutMs: t, signal: ctx.signal, env: ctx.services.settings?.env, onOutput: (c) => ctx.progress(c) }).catch((e) => {
      throw new ToolError(`Failed to start ${prog}: ${(e as Error).message}`);
    });
    return formatExec(res, t);
  },
});

export const StartProcessTool = defineTool({
  name: 'StartProcess',
  description: 'Start a long-running background process (dev server, watcher, tail). Returns an id; use ProcessStatus to read new output and StopProcess to stop it. Processes are stopped when STELLA exits.',
  kind: 'execute',
  schema: z.object({ command: z.string(), shell: z.enum(['bash', 'powershell', 'cmd']).optional(), wait_ms: z.number().int().min(0).max(30_000).optional().describe('Wait this long and return initial output (default 1500)') }),
  describe: (i, ctx) => shellDesc(i.command, 'Start background', ctx),
  async run(i, ctx) {
    const sh = i.shell === 'powershell' ? powershellShell() : i.shell === 'cmd' ? cmdShell() : bashShell(ctx.services.settings?.shell) ?? powershellShell();
    if (!sh) throw new ToolError('No suitable shell available.');
    const p = ctx.services.processes.start(i.command, sh, ctx.services.shellCwd?.get(ctx.agentId) ?? ctx.cwd, ctx.services.settings?.env);
    await new Promise((r) => setTimeout(r, i.wait_ms ?? 1500));
    const out = ctx.services.processes.readNew(p.id);
    return { content: `Started ${p.id} (pid ${p.pid}) status=${p.status}${p.exitCode !== null ? ` exit=${p.exitCode}` : ''}\n${truncate(out, 8000) || '(no output yet)'}` };
  },
});

export const ProcessStatusTool = defineTool({
  name: 'ProcessStatus',
  description: 'List background processes, or show status and NEW output (since the last check) of one process.',
  kind: 'read',
  concurrencySafe: true,
  schema: z.object({ id: z.string().optional() }),
  describe: () => ({ kind: 'read', risk: 'low', readOnly: true, summary: 'Process status' }),
  async run(i, ctx) {
    const pm = ctx.services.processes;
    if (!i.id) {
      const list = pm.list();
      if (!list.length) return { content: 'No background processes.' };
      return { content: list.map((p: any) => `${p.id} pid=${p.pid} ${p.status}${p.exitCode !== null ? `(${p.exitCode})` : ''} ${Math.round((Date.now() - p.startedAt) / 1000)}s  ${p.command}`).join('\n') };
    }
    const p = pm.get(i.id);
    if (!p) throw new ToolError(`No process ${i.id}`);
    return { content: `${p.id} ${p.status}${p.exitCode !== null ? ` exit=${p.exitCode}` : ''}\n${truncate(pm.readNew(i.id), MAX_OUTPUT) || '(no new output)'}` };
  },
});

export const StopProcessTool = defineTool({
  name: 'StopProcess',
  description: 'Stop a background process started with StartProcess (kills the whole process tree).',
  kind: 'meta',
  schema: z.object({ id: z.string() }),
  describe: (i) => ({ kind: 'meta', risk: 'low', readOnly: false, summary: `Stop ${i.id}` }),
  async run(i, ctx) {
    const ok = ctx.services.processes.stop(i.id);
    return { content: ok ? `Stopped ${i.id}` : `${i.id} is not running`, isError: !ok };
  },
});

export const shellTools = [BashTool, PowerShellTool, CmdTool, RunCommandTool, RunScriptTool, StartProcessTool, ProcessStatusTool, StopProcessTool];

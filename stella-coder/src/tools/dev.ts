import path from 'node:path';
import { z } from 'zod';
import { analyzeShell } from '../permissions/shell.js';
import { shellQuote } from '../security/quote.js';
import { bashShell, cmdShell, execProgram, powershellShell } from './process.js';
import { formatExec } from './shell.js';
import { rp, relDisplay } from './fs.js';
import { defineTool, ToolError, type ToolContext } from './types.js';

async function runCmd(cmd: string, ctx: ToolContext, timeoutMs = 300_000) {
  const sh = bashShell(ctx.services.settings?.shell) ?? powershellShell() ?? cmdShell();
  if (!sh) throw new ToolError('No shell available');
  const r = await execProgram(sh.file, sh.args(cmd), { cwd: ctx.cwd, timeoutMs, signal: ctx.signal, env: ctx.services.settings?.env, onOutput: (c) => ctx.progress(c) });
  ctx.services.processes?.history.push({ command: cmd, exitCode: r.exitCode, durationMs: r.durationMs, ts: Date.now(), agentId: ctx.agentId });
  return formatExec(r, timeoutMs);
}

async function profileCmd(ctx: ToolContext, key: 'test' | 'lint' | 'format' | 'build' | 'typecheck'): Promise<string | undefined> {
  const p = await ctx.services.getProfile?.();
  return p?.commands?.[key];
}

const desc = (cmd: string | undefined, label: string) => {
  const a = analyzeShell(cmd ?? label);
  return { kind: 'execute' as const, risk: a.risk === 'low' ? ('medium' as const) : a.risk, readOnly: false, command: cmd ?? label, summary: `${label}${cmd ? `: ${cmd}` : ''}` };
};

export const TestRunnerTool = defineTool({
  name: 'TestRunner',
  description: "Run the project's tests (auto-detected: npm test, pytest, go test, cargo test, mvn test, dotnet test…). Optionally pass a filter (test name/file) or an explicit command.",
  kind: 'execute',
  schema: z.object({ command: z.string().optional(), filter: z.string().optional(), timeout: z.number().int().optional() }),
  describe: async (i, ctx) => desc(i.command ?? (await profileCmd(ctx, 'test')), 'Run tests'),
  async run(i, ctx) {
    let cmd = i.command ?? (await profileCmd(ctx, 'test'));
    if (!cmd) throw new ToolError('Could not detect a test command. Pass `command` explicitly.');
    if (i.filter) {
      const f = i.filter.replace(/["'`$\;&|]/g, '');
      if (/pytest/.test(cmd)) cmd += ` -k "${f}"`;
      else if (/go test/.test(cmd)) cmd += ` -run "${f}"`;
      else if (/cargo test/.test(cmd)) cmd += ` ${f}`;
      else if (/npm test|yarn test|pnpm test|bun test/.test(cmd)) cmd += ` -- ${f}`;
      else cmd += ` ${f}`;
    }
    return runCmd(cmd, ctx, i.timeout ?? 600_000);
  },
});

export const LinterTool = defineTool({
  name: 'Linter',
  description: 'Run the project linter (auto-detected: npm run lint, ruff, go vet, cargo clippy) or an explicit command.',
  kind: 'execute',
  schema: z.object({ command: z.string().optional(), fix: z.boolean().optional() }),
  describe: async (i, ctx) => desc(i.command ?? (await profileCmd(ctx, 'lint')), 'Lint'),
  async run(i, ctx) {
    let cmd = i.command ?? (await profileCmd(ctx, 'lint'));
    if (!cmd) throw new ToolError('No lint command detected. Pass `command`.');
    if (i.fix && /ruff check|eslint/.test(cmd)) cmd += ' --fix';
    return runCmd(cmd, ctx);
  },
});

export const FormatterTool = defineTool({
  name: 'Formatter',
  description: 'Run the project formatter (auto-detected: npm run format, ruff format, gofmt, cargo fmt) or an explicit command.',
  kind: 'execute',
  schema: z.object({ command: z.string().optional() }),
  describe: async (i, ctx) => desc(i.command ?? (await profileCmd(ctx, 'format')), 'Format'),
  async run(i, ctx) {
    const cmd = i.command ?? (await profileCmd(ctx, 'format'));
    if (!cmd) throw new ToolError('No format command detected. Pass `command`.');
    return runCmd(cmd, ctx);
  },
});

export const DiagnosticsTool = defineTool({
  name: 'Diagnostics',
  description: 'Check code for errors: syntax-check a single file (node --check, python -m py_compile, gofmt -e, JSON parse) or run the project type checker / build when no file is given.',
  kind: 'execute',
  schema: z.object({ file: z.string().optional(), kind: z.enum(['syntax', 'typecheck', 'build']).optional() }),
  describe: async (i, ctx) => {
    if (i.file) {
      const r = rp(ctx, i.file);
      return { kind: 'execute', risk: 'low', readOnly: true, summary: `Check ${relDisplay(ctx, r.abs)}`, paths: [r] };
    }
    return desc(await profileCmd(ctx, i.kind === 'build' ? 'build' : 'typecheck'), i.kind === 'build' ? 'Build' : 'Typecheck');
  },
  async run(i, ctx) {
    if (i.file) {
      const f = rp(ctx, i.file).real;
      const ext = path.extname(f).toLowerCase();
      const t = 60_000;
      if (ext === '.json') {
        const { readFile } = await import('node:fs/promises');
        try {
          JSON.parse(await readFile(f, 'utf8'));
          return { content: 'JSON is valid.' };
        } catch (e) {
          return { content: `Invalid JSON: ${(e as Error).message}`, isError: true };
        }
      }
      const map: Record<string, [string, string[]]> = {
        '.js': ['node', ['--check', f]],
        '.mjs': ['node', ['--check', f]],
        '.cjs': ['node', ['--check', f]],
        '.py': [process.platform === 'win32' ? 'python' : 'python3', ['-m', 'py_compile', f]],
        '.go': ['gofmt', ['-e', '-l', f]],
        '.rb': ['ruby', ['-c', f]],
        '.php': ['php', ['-l', f]],
        '.sh': ['bash', ['-n', f]],
      };
      if (ext === '.ts' || ext === '.tsx') {
        const sh = bashShell(ctx.services.settings?.shell) ?? powershellShell() ?? cmdShell();
        return runCmd(`npx --no-install tsc --noEmit --skipLibCheck --allowJs --jsx preserve ${shellQuote(f, sh?.kind)}`, ctx, 120_000);
      }
      const m = map[ext];
      if (!m) throw new ToolError(`No syntax checker for ${ext}; use typecheck/build.`);
      const r = await execProgram(m[0], m[1], { cwd: ctx.cwd, timeoutMs: t, signal: ctx.signal });
      const res = formatExec(r, t);
      if (!res.isError && !r.stdout.trim() && !r.stderr.trim()) res.content = `No syntax errors in ${relDisplay(ctx, f)}.`;
      return res;
    }
    const cmd = await profileCmd(ctx, i.kind === 'build' ? 'build' : 'typecheck');
    if (!cmd) throw new ToolError(`No ${i.kind ?? 'typecheck'} command detected for this project.`);
    return runCmd(cmd, ctx, 600_000);
  },
});

export const PackageManagerTool = defineTool({
  name: 'PackageManager',
  description: "Manage dependencies with the project's package manager (npm/pnpm/yarn/bun/pip/poetry/uv/cargo/go). Actions: install (all deps), add, remove, list, outdated.",
  kind: 'execute',
  schema: z.object({ action: z.enum(['install', 'add', 'remove', 'list', 'outdated']), packages: z.array(z.string().regex(/^[@\w./:=<>~^-]+$/)).optional(), dev: z.boolean().optional(), manager: z.string().optional() }),
  describe: async (i, ctx) => {
    const cmd = await buildPmCommand(i, ctx).catch(() => undefined);
    const ro = i.action === 'list' || i.action === 'outdated';
    return { kind: 'execute', risk: ro ? 'low' : 'high', readOnly: ro, command: cmd, summary: `Packages: ${cmd ?? i.action}` };
  },
  async run(i, ctx) {
    return runCmd(await buildPmCommand(i, ctx), ctx, 600_000);
  },
});

async function buildPmCommand(i: { action: string; packages?: string[]; dev?: boolean; manager?: string }, ctx: ToolContext): Promise<string> {
  const p = await ctx.services.getProfile?.();
  const pkgs = (i.packages ?? []).join(' ');
  let pm = i.manager ?? p?.packageManager;
  if (!pm) {
    const m: string[] = p?.manifests ?? [];
    if (m.includes('pyproject.toml') || m.includes('requirements.txt')) pm = m.includes('pyproject.toml') && /poetry/.test(String(m)) ? 'poetry' : 'pip';
    else if (m.includes('Cargo.toml')) pm = 'cargo';
    else if (m.includes('go.mod')) pm = 'go';
    else pm = 'npm';
  }
  if ((i.action === 'add' || i.action === 'remove') && !pkgs) throw new ToolError('packages required');
  switch (pm) {
    case 'npm':
      return { install: 'npm install', add: `npm install ${i.dev ? '-D ' : ''}${pkgs}`, remove: `npm uninstall ${pkgs}`, list: 'npm ls --depth=0', outdated: 'npm outdated' }[i.action]!;
    case 'pnpm':
    case 'yarn':
    case 'bun':
      return { install: `${pm} install`, add: `${pm} add ${i.dev ? '-D ' : ''}${pkgs}`, remove: `${pm} remove ${pkgs}`, list: `${pm} list --depth=0`, outdated: `${pm} outdated` }[i.action]!;
    case 'pip': {
      const py = process.platform === 'win32' ? 'python' : 'python3';
      return { install: `${py} -m pip install -r requirements.txt`, add: `${py} -m pip install ${pkgs}`, remove: `${py} -m pip uninstall -y ${pkgs}`, list: `${py} -m pip list`, outdated: `${py} -m pip list --outdated` }[i.action]!;
    }
    case 'poetry':
    case 'uv':
      return { install: `${pm} ${pm === 'uv' ? 'sync' : 'install'}`, add: `${pm} add ${i.dev ? (pm === 'uv' ? '--dev ' : '--group dev ') : ''}${pkgs}`, remove: `${pm} remove ${pkgs}`, list: pm === 'uv' ? 'uv pip list' : 'poetry show', outdated: pm === 'uv' ? 'uv pip list --outdated' : 'poetry show --outdated' }[i.action]!;
    case 'cargo':
      return { install: 'cargo fetch', add: `cargo add ${i.dev ? '--dev ' : ''}${pkgs}`, remove: `cargo remove ${pkgs}`, list: 'cargo tree --depth 1', outdated: 'cargo outdated' }[i.action]!;
    case 'go':
      return { install: 'go mod download', add: `go get ${pkgs}`, remove: `go mod tidy`, list: 'go list -m all', outdated: 'go list -u -m all' }[i.action]!;
    default:
      throw new ToolError(`Unsupported package manager ${pm}`);
  }
}

export const devTools = [TestRunnerTool, LinterTool, FormatterTool, DiagnosticsTool, PackageManagerTool];

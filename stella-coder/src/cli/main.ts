#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Runtime } from '../agent/runtime.js';
import type { AgentEvent } from '../agent/events.js';
import { PermissionModeSchema, setCredential, updateSettings, type PermissionMode } from '../config/settings.js';
import { findProjectRoot } from '../config/paths.js';
import { maskKey } from '../utils/redact.js';
import { runSlash, type CommandContext } from './commands.js';
import { renderMarkdown } from './markdown.js';
import { c } from './theme.js';

const VERSION = (() => {
  try {
    const pkg = JSON.parse(readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'package.json'), 'utf8'));
    return String(pkg.version);
  } catch {
    return '0.0.0';
  }
})();

interface Args {
  prompt?: string;
  print: boolean;
  outputFormat: 'text' | 'json' | 'stream-json';
  model?: string;
  mode?: PermissionMode;
  allowed: string[];
  disallowed: string[];
  resume?: string;
  trust?: boolean;
  cwd: string;
  maxTurns?: number;
  appendSystemPrompt?: string;
  noMcp: boolean;
  verbose: boolean;
  sub?: string[];
}

const HELP = `${c.brand('✦ STELLA CODER')} ${c.faint('v' + VERSION)} — autonomous AI coding agent

${c.bold('Usage')}
  stella [prompt]                  interactive session (optional first prompt)
  stella -p "prompt"               non-interactive: run the task, print the result, exit
  cat log.txt | stella -p "why does this fail?"

${c.bold('Options')}
  -p, --print                      non-interactive mode
  --output-format <fmt>            text (default) | json | stream-json   (with -p)
  -m, --model <model>              alias (opus, sonnet, haiku, gpt, gemini…) or provider:model
  --permission-mode <mode>         default | plan | acceptEdits | auto | bypassPermissions
  --plan                           start in plan mode
  --allowedTools <rules>           comma/space separated allow rules, e.g. "Bash(npm test:*),Edit"
  --disallowedTools <rules>        deny rules
  --dangerously-skip-permissions   bypass mode (disposable environments only)
  -c, --continue                   continue the most recent session
  -r, --resume [id]                resume a session (lists sessions without id)
  --cwd <dir>                      working directory
  --max-turns <n>                  limit model turns per prompt
  --append-system-prompt <text>    extra system instructions
  --trust                          trust this folder (project hooks/MCP)
  --no-mcp                         do not connect MCP servers
  -v, --version · -h, --help

${c.bold('Commands')}
  stella mcp list|add|remove|test …    manage MCP servers (same as /mcp)
  stella auth set <provider> <key>     store an API key (also: status, remove)
  stella sessions [search <q>]         list or search sessions
  stella doctor                        diagnose the installation
  stella config [get|set|path] …       settings

${c.bold('Environment')}
  ANTHROPIC_API_KEY · OPENAI_API_KEY · OPENROUTER_API_KEY · GROQ_API_KEY · GEMINI_API_KEY
  STELLA_MODEL (default model) · STELLA_HOME (data dir, default ~/.stella)
`;

function parseArgs(argv: string[]): Args {
  const a: Args = { print: false, outputFormat: 'text', allowed: [], disallowed: [], cwd: process.cwd(), noMcp: false, verbose: false };
  const rest: string[] = [];
  const list = (v: string | undefined) => (v ?? '').split(/[,\s]+(?![^()]*\))/).filter(Boolean);
  for (let i = 0; i < argv.length; i++) {
    const x = argv[i]!;
    const next = () => {
      const v = argv[++i];
      if (v === undefined) throw new Error(`${x} requires a value`);
      return v;
    };
    switch (x) {
      case '-p':
      case '--print':
        a.print = true;
        break;
      case '--output-format':
        a.outputFormat = next() as Args['outputFormat'];
        break;
      case '-m':
      case '--model':
        a.model = next();
        break;
      case '--permission-mode': {
        const m = PermissionModeSchema.safeParse(next());
        if (!m.success) throw new Error('Invalid --permission-mode');
        a.mode = m.data;
        break;
      }
      case '--plan':
        a.mode = 'plan';
        break;
      case '--dangerously-skip-permissions':
        a.mode = 'bypassPermissions';
        break;
      case '--allowedTools':
      case '--allowed-tools':
        a.allowed.push(...list(next()));
        break;
      case '--disallowedTools':
      case '--disallowed-tools':
        a.disallowed.push(...list(next()));
        break;
      case '-c':
      case '--continue':
        a.resume = 'last';
        break;
      case '-r':
      case '--resume':
        a.resume = argv[i + 1] && !argv[i + 1]!.startsWith('-') ? argv[++i] : '?';
        break;
      case '--cwd':
        a.cwd = path.resolve(next());
        break;
      case '--max-turns':
        a.maxTurns = Number(next());
        break;
      case '--append-system-prompt':
        a.appendSystemPrompt = next();
        break;
      case '--trust':
        a.trust = true;
        break;
      case '--no-mcp':
        a.noMcp = true;
        break;
      case '--verbose':
        a.verbose = true;
        break;
      case '-v':
      case '--version':
        process.stdout.write(VERSION + '\n');
        process.exit(0);
      case '-h':
      case '--help':
        process.stdout.write(HELP);
        process.exit(0);
      default:
        rest.push(x);
    }
  }
  if (rest.length && ['mcp', 'auth', 'sessions', 'doctor', 'config'].includes(rest[0]!) && !a.print) a.sub = rest;
  else if (rest.length) a.prompt = rest.join(' ');
  return a;
}

/**
 * Read piped stdin. If nothing arrives within a short grace period the pipe is assumed to be an
 * idle inherited handle (CI runners, IDE task runners) and ignored instead of blocking forever.
 */
async function readStdin(graceMs = 250): Promise<string> {
  if (process.stdin.isTTY) return '';
  return new Promise((resolve) => {
    const chunks: Buffer[] = [];
    let started = false;
    const done = () => {
      clearTimeout(timer);
      process.stdin.off('data', onData);
      process.stdin.pause();
      resolve(Buffer.concat(chunks).toString('utf8'));
    };
    const onData = (d: Buffer) => {
      started = true;
      chunks.push(d);
    };
    const timer = setTimeout(() => {
      if (!started) done();
    }, graceMs);
    process.stdin.on('data', onData);
    process.stdin.once('end', done);
    process.stdin.once('error', done);
  });
}

function plainCtx(rt: Runtime): CommandContext {
  return {
    rt,
    print: (t, level) => process.stdout.write((level === 'md' ? renderMarkdown(t) : level === 'error' ? c.err(t) : level === 'warn' ? c.warn(t) : t) + '\n'),
    submit: async (p) => {
      await runPrint(rt, p, 'text');
    },
    exit: () => process.exit(0),
  };
}

async function runSub(args: Args) {
  const [cmd, ...rest] = args.sub!;
  if (cmd === 'auth') {
    const [op, provider, key] = rest;
    if (op === 'set' && provider && key) {
      await setCredential(`${provider}.apiKey`, key);
      return console.log(`Saved ${provider} key ${maskKey(key)}`);
    }
    if (op === 'remove' && provider) {
      await setCredential(`${provider}.apiKey`, null);
      return console.log(`Removed ${provider} key`);
    }
    const rt = await Runtime.create({ cwd: args.cwd, connectMcp: false });
    for (const p of rt.registry.listProviders()) console.log(`${p.name.padEnd(11)} ${maskKey(await rt.registry.apiKeyFor(p.name))}`);
    return;
  }
  if (cmd === 'config' && rest[0] === 'set' && rest[1]) {
    const scope = rest.includes('--user') ? 'user' : rest.includes('--project') ? 'project' : 'local';
    const raw = rest.slice(2).filter((x) => !x.startsWith('--')).join(' ');
    let v: unknown = raw;
    try {
      v = JSON.parse(raw);
    } catch {
      /* string */
    }
    await updateSettings(scope, findProjectRoot(args.cwd), (s) => ({ ...s, [rest[1]!]: v }));
    return console.log(`Set ${rest[1]} (${scope})`);
  }
  const rt = await Runtime.create({ cwd: args.cwd, connectMcp: cmd === 'mcp' || cmd === 'doctor', trust: args.trust });
  if (cmd === 'mcp' || cmd === 'doctor') await rt.mcp.connectAll().catch(() => {});
  const map: Record<string, string> = { mcp: '/mcp', sessions: '/sessions', doctor: '/doctor', config: '/config' };
  await runSlash(`${map[cmd!]} ${rest.join(' ')}`, plainCtx(rt));
  await rt.shutdown();
}

/** Non-interactive execution: stream text (or JSON events) to stdout. */
async function runPrint(rt: Runtime, prompt: string, format: Args['outputFormat'], verbose = false): Promise<number> {
  let wroteText = false;
  const onEvent = (ev: AgentEvent) => {
    if (format === 'stream-json') {
      if (ev.type === 'text_delta' || ev.type === 'status' || ev.type === 'tool_progress') {
        if (!verbose && ev.type !== 'text_delta') return;
      }
      process.stdout.write(JSON.stringify(ev) + '\n');
      return;
    }
    if (format === 'text') {
      if (ev.type === 'text_delta' && ev.agentId === 'main') {
        process.stdout.write(ev.text);
        wroteText = true;
      } else if (ev.type === 'tool_call' && ev.agentId === 'main') process.stderr.write(c.faint(`⏺ ${ev.summary}\n`));
      else if (ev.type === 'tool_result' && ev.isError && ev.agentId === 'main') process.stderr.write(c.err(`  ⎿ ${ev.content.split('\n')[0]}\n`));
      else if (ev.type === 'notification' && ev.level !== 'info') process.stderr.write(c.warn(`${ev.text}\n`));
      else if (ev.type === 'assistant_message' && wroteText) process.stdout.write('\n');
    }
  };
  rt.events.on('event', onEvent);
  const started = Date.now();
  try {
    const r = await rt.submit(prompt);
    if (format === 'json') {
      process.stdout.write(
        JSON.stringify(
          {
            type: 'result',
            result: r?.text ?? '',
            stop_reason: r?.stopReason,
            session_id: rt.session.id,
            num_turns: r?.turns,
            tool_calls: r?.toolCalls,
            duration_ms: Date.now() - started,
            usage: r?.usage,
            total_cost_usd: rt.session.costUsd,
            model: `${rt.main.model.provider}:${rt.main.model.id}`,
          },
          null,
          2,
        ) + '\n',
      );
    } else if (format === 'stream-json') {
      process.stdout.write(JSON.stringify({ type: 'result', result: r?.text ?? '', session_id: rt.session.id, total_cost_usd: rt.session.costUsd, stop_reason: r?.stopReason }) + '\n');
    }
    return r?.stopReason === 'refusal' ? 3 : 0;
  } finally {
    rt.events.off('event', onEvent);
  }
}

async function main() {
  let args: Args;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (e) {
    process.stderr.write(c.err((e as Error).message) + '\n');
    process.exit(2);
  }
  if (args.sub) return runSub(args);

  const stdinText = !process.stdin.isTTY && (args.print || args.prompt) ? await readStdin() : '';
  if (stdinText) args.prompt = `${args.prompt ?? ''}\n\n<stdin>\n${stdinText}\n</stdin>`.trim();

  if (args.resume === '?') {
    const rt = await Runtime.create({ cwd: args.cwd, connectMcp: false });
    await runSlash('/resume', plainCtx(rt));
    process.stdout.write(c.faint('\nRun: stella --resume <id>\n'));
    return;
  }

  const rt = await Runtime.create({
    cwd: args.cwd,
    model: args.model,
    permissionMode: args.mode,
    allowedTools: args.allowed,
    disallowedTools: args.disallowed,
    resume: args.resume,
    trust: args.trust,
    interactive: !args.print,
    connectMcp: !args.noMcp,
    maxTurns: args.maxTurns,
    appendSystemPrompt: args.appendSystemPrompt,
  });

  const shutdown = async (code: number) => {
    await rt.shutdown();
    process.exit(code);
  };

  if (args.print) {
    for (const w of rt.warnings) process.stderr.write(c.warn(w) + '\n');
    if (!args.prompt) {
      process.stderr.write('No prompt given. Usage: stella -p "your task"\n');
      return shutdown(2);
    }
    process.on('SIGINT', () => rt.interrupt());
    if (!args.noMcp) await rt.mcp.connectAll().catch(() => {});
    try {
      if (args.prompt.trim().startsWith('/')) {
        await runSlash(args.prompt.trim(), plainCtx(rt));
        return shutdown(0);
      }
      const code = await runPrint(rt, args.prompt, args.outputFormat, args.verbose);
      return shutdown(code);
    } catch (e) {
      process.stderr.write(c.err(`Error: ${(e as Error).message}`) + '\n');
      return shutdown(1);
    }
  }

  if (!process.stdin.isTTY) {
    process.stderr.write('Interactive mode needs a TTY. Use -p for non-interactive runs.\n');
    return shutdown(2);
  }
  const { render } = await import('ink');
  const React = await import('react');
  const { App } = await import('./App.js');
  process.on('SIGTERM', () => void shutdown(0));
  render(React.createElement(App, { rt, initialPrompt: args.prompt, version: VERSION }), { exitOnCtrlC: false });
}

main().catch((e) => {
  process.stderr.write(c.err(`Fatal: ${(e as Error).stack ?? e}`) + '\n');
  process.exit(1);
});

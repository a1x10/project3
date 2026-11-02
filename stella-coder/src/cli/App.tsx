import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Box, Static, Text, useApp, useStdout } from 'ink';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import type { Runtime } from '../agent/runtime.js';
import type { AgentEvent, PermissionRequest } from '../agent/events.js';
import type { AskAnswer } from '../permissions/engine.js';
import type { PermissionMode } from '../config/settings.js';
import { stellaHome } from '../config/paths.js';
import { execProgram, bashShell, powershellShell } from '../tools/process.js';
import { truncate } from '../utils/fsutil.js';
import { completeCommand, runSlash, bar } from './commands.js';
import { completePath, expandMentions } from './mentions.js';
import { renderMarkdown } from './markdown.js';
import { fmtTokens, toolArgs, toolResultLines } from './format.js';
import { c, gradient, LOGO, SPINNER, SPINNER_ASCII, supportsUnicode, theme } from './theme.js';
import { PermissionDialog, PlanDialog, QuestionDialog } from './components/Dialogs.js';
import { PromptInput, type Suggestion } from './components/Input.js';

type Item = { id: number; text: string };

interface ActiveTool {
  id: string;
  agentId: string;
  name: string;
  args: string;
  progress: string;
  started: number;
}

type Dialog =
  | { kind: 'permission'; req: PermissionRequest; resolve(a: AskAnswer): void }
  | { kind: 'plan'; plan: string; resolve(a: any): void }
  | { kind: 'question'; question: string; options: string[]; resolve(a: string): void };

const MODES: PermissionMode[] = ['default', 'acceptEdits', 'plan', 'auto'];
const MODE_LABEL: Record<string, [string, string]> = {
  default: ['', theme.faint],
  acceptEdits: ['⏵⏵ accept edits on', theme.brand2],
  plan: ['⏸ plan mode on', theme.ok],
  auto: ['⏵⏵⏵ auto mode on', theme.warn],
  bypassPermissions: ['⚠ bypass permissions on', theme.err],
};

let itemSeq = 0;
const HISTORY_FILE = () => path.join(stellaHome(), 'history.jsonl');

export function App({ rt, initialPrompt, version }: { rt: Runtime; initialPrompt?: string; version: string }) {
  const { exit } = useApp();
  const { stdout } = useStdout();
  const width = Math.max(40, (stdout?.columns ?? 100) - 2);
  const unicode = useMemo(() => supportsUnicode(), []);
  const [items, setItems] = useState<Item[]>([{ id: itemSeq++, text: banner(rt, version, width) }]);
  const [streaming, setStreaming] = useState('');
  const [tools, setTools] = useState<Map<string, ActiveTool>>(new Map());
  const [subs, setSubs] = useState<Map<string, { name: string; description: string; status: string; last?: string }>>(new Map());
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [mode, setMode] = useState<string>(rt.permissions.mode);
  const [ctxInfo, setCtxInfo] = useState({ tokens: 0, window: rt.main.model.contextWindow });
  const [cost, setCost] = useState(rt.session.costUsd);
  const [todos, setTodos] = useState(rt.todos.get('main') ?? []);
  const [history, setHistory] = useState<string[]>([]);
  const [frame, setFrame] = useState(0);
  const [modelName, setModelName] = useState(rt.main.model.name);
  const startedAt = useRef(0);
  const streamRef = useRef('');

  const push = useCallback((text: string) => setItems((xs) => [...xs, { id: itemSeq++, text }]), []);
  const print = useCallback(
    (text: string, level: 'info' | 'warn' | 'error' | 'md' = 'info') => {
      const t = level === 'md' ? renderMarkdown(text, width) : level === 'error' ? c.err(text) : level === 'warn' ? c.warn(text) : text;
      push(t.split('\n').map((l) => '  ' + l).join('\n'));
    },
    [push, width],
  );

  const flushStreaming = useCallback(() => {
    const t = streamRef.current;
    if (t.trim()) {
      const md = renderMarkdown(t.trim(), width - 2).split('\n');
      push(md.map((l, i) => (i === 0 ? c.brand('✦ ') : '  ') + l).join('\n'));
    }
    streamRef.current = '';
    setStreaming('');
  }, [push, width]);

  // history
  useEffect(() => {
    fs.readFile(HISTORY_FILE(), 'utf8')
      .then((t) =>
        setHistory(
          t
            .split('\n')
            .filter(Boolean)
            .map((l) => {
              try {
                const j = JSON.parse(l);
                return j.project === rt.root ? (j.text as string) : null;
              } catch {
                return null;
              }
            })
            .filter((x): x is string => !!x)
            .slice(-200),
        ),
      )
      .catch(() => {});
  }, []);

  // spinner
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(() => setFrame((f) => f + 1), 120);
    return () => clearInterval(t);
  }, [busy]);

  // UI handlers for runtime
  useEffect(() => {
    rt.handlers.permission = (req) => new Promise<AskAnswer>((resolve) => setDialog({ kind: 'permission', req, resolve }));
    rt.handlers.planApproval = (plan) => new Promise((resolve) => setDialog({ kind: 'plan', plan, resolve }));
    rt.handlers.question = (question, options) => new Promise((resolve) => setDialog({ kind: 'question', question, options, resolve }));
    for (const w of rt.warnings) print(w, 'warn');
    rt.warnings.length = 0;
  }, []);

  // agent events
  useEffect(() => {
    const onEvent = (ev: AgentEvent) => {
      const isMain = ev.agentId === 'main';
      switch (ev.type) {
        case 'text_delta':
          if (isMain) {
            streamRef.current += ev.text;
            setStreaming(streamRef.current);
          }
          break;
        case 'text_reset':
          if (isMain) {
            streamRef.current = '';
            setStreaming('');
          }
          break;
        case 'status':
          if (isMain) setStatus(ev.text);
          else setSubs((m) => (m.has(ev.agentId) ? new Map(m).set(ev.agentId, { ...m.get(ev.agentId)!, last: ev.text }) : m));
          break;
        case 'tool_start':
          if (isMain) flushStreaming();
          break;
        case 'tool_call':
          if (!isMain) {
            setSubs((m) => (m.has(ev.agentId) ? new Map(m).set(ev.agentId, { ...m.get(ev.agentId)!, last: `${ev.name} ${toolArgs(ev.name, ev.input, rt.root)}` }) : m));
            break;
          }
          setTools((m) => new Map(m).set(ev.id, { id: ev.id, agentId: ev.agentId, name: ev.name, args: toolArgs(ev.name, ev.input, rt.root), progress: '', started: Date.now() }));
          break;
        case 'tool_progress':
          setTools((m) => {
            const t = m.get(ev.id);
            if (!t) return m;
            const progress = (t.progress + ev.text).slice(-2000);
            return new Map(m).set(ev.id, { ...t, progress });
          });
          break;
        case 'tool_result': {
          if (!isMain) break;
          setTools((m) => {
            const t = m.get(ev.id);
            const header = `${ev.isError ? c.err('⏺') : c.ok('⏺')} ${c.bold(ev.name)}${t?.args ? c.dim(`(${t.args})`) : ''}`;
            push([header, ...toolResultLines(ev.name, ev.content, ev.isError, ev.display, ev.durationMs, width - 8)].join('\n'));
            const n = new Map(m);
            n.delete(ev.id);
            return n;
          });
          break;
        }
        case 'permission':
          if (ev.decision === 'deny' && ev.reason !== 'user') print(`${c.err('⊘')} ${ev.summary} — ${ev.reason}`, 'info');
          break;
        case 'assistant_message':
          if (isMain) flushStreaming();
          break;
        case 'usage':
          if (isMain) setCtxInfo({ tokens: ev.contextTokens, window: ev.contextWindow });
          setCost(rt.session.costUsd);
          break;
        case 'compact':
          print(`${c.brand2('⟳')} Context compacted ${ev.auto ? '(auto) ' : ''}~${fmtTokens(ev.beforeTokens)} → ~${fmtTokens(ev.afterTokens)} tokens`);
          setCtxInfo((x) => ({ ...x, tokens: ev.afterTokens }));
          break;
        case 'notification':
          print(ev.level === 'info' ? c.dim(ev.text) : ev.text, ev.level === 'error' ? 'error' : ev.level === 'warn' ? 'warn' : 'info');
          break;
        case 'subagent':
          setSubs((m) => {
            const n = new Map(m);
            if (['completed', 'failed', 'cancelled'].includes(ev.status)) {
              n.delete(ev.runId);
              push(`${ev.status === 'completed' ? c.ok('◆') : c.err('◆')} ${c.brand('Agent')} ${c.bold(ev.name)} ${c.dim(ev.description)} ${c.faint(`· ${ev.status} · ${ev.toolCalls ?? 0} tool calls`)}`);
            } else n.set(ev.runId, { name: ev.name, description: ev.description, status: ev.status, last: m.get(ev.runId)?.last });
            return n;
          });
          break;
        case 'todos':
          if (isMain) setTodos(ev.todos as any);
          break;
        case 'mode':
          setMode(ev.mode);
          break;
        case 'turn_end':
          if (isMain) {
            flushStreaming();
            setStatus('');
          }
          break;
      }
    };
    rt.events.on('event', onEvent);
    return () => {
      rt.events.off('event', onEvent);
    };
  }, [flushStreaming, print, push, width]);

  const quit = useCallback(async () => {
    await rt.shutdown();
    exit();
    setTimeout(() => {
      process.stdout.write(`\n${c.faint('Resume this session with:')} ${c.brand2(`stella --resume ${rt.session.id}`)}\n`);
      process.exit(0);
    }, 50);
  }, []);

  const runAgent = useCallback(
    async (text: string) => {
      const { blocks, attached, skipped } = await expandMentions(text, rt);
      if (attached.length) print(c.faint(`  attached ${attached.join(', ')}`));
      if (skipped.length) print(c.warn(`  not attached (outside workspace, confidential or binary): ${skipped.join(', ')}`));
      setBusy(true);
      startedAt.current = Date.now();
      try {
        await rt.submit(blocks.length > 1 ? blocks : text);
      } catch (e) {
        print(`Error: ${(e as Error).message}`, 'error');
      } finally {
        setBusy(false);
        setTools(new Map());
        setCost(rt.session.costUsd);
        setModelName(rt.main.model.name);
      }
    },
    [print],
  );

  const ctx = useMemo(
    () => ({
      rt,
      print,
      submit: (p: string) => runAgent(p),
      exit: () => void quit(),
      clearScreen: () => {
        process.stdout.write('\x1b[2J\x1b[3J\x1b[H');
        setItems([{ id: itemSeq++, text: banner(rt, version, width) }]);
      },
    }),
    [print, runAgent],
  );

  const onSubmit = useCallback(
    async (value: string) => {
      const text = value.trim();
      setHistory((h) => [...h.filter((x) => x !== text), text].slice(-200));
      fs.mkdir(stellaHome(), { recursive: true })
        .then(() => fs.appendFile(HISTORY_FILE(), JSON.stringify({ project: rt.root, text, ts: Date.now() }) + '\n'))
        .catch(() => {});
      push(text.split('\n').map((l, i) => (i === 0 ? c.accent('❯ ') : '  ') + c.bold(l)).join('\n'));
      if (busy && !text.startsWith('/')) {
        await rt.submit(text);
        return;
      }
      if (text.startsWith('!')) return runShell(text.slice(1));
      if (text.startsWith('/')) {
        if (busy && !['/status', '/cost', '/context', '/todos', '/agents', '/help'].some((x) => text.startsWith(x))) return print('Wait for the current task to finish (or press esc) before running this command.', 'warn');
        await runSlash(text, ctx);
        setModelName(rt.main.model.name);
        setMode(rt.permissions.mode);
        setCost(rt.session.costUsd);
        return;
      }
      await runAgent(text);
    },
    [busy, ctx, runAgent],
  );

  const runShell = async (cmd: string) => {
    const sh = bashShell(rt.settings.shell) ?? powershellShell();
    if (!sh) return print('No shell available', 'error');
    setBusy(true);
    try {
      const r = await execProgram(sh.file, sh.args(cmd), { cwd: rt.cwd, timeoutMs: 600_000 });
      const out = truncate((r.stdout + (r.stderr ? '\n' + r.stderr : '')).trim(), 20_000);
      print((out ? c.dim(out) + '\n' : '') + (r.exitCode === 0 ? c.ok(`exit 0`) : c.err(`exit ${r.exitCode}`)));
      rt.main.messages.push({ role: 'user', content: [{ type: 'text', text: `<bash-input>${cmd}</bash-input>\n<bash-output exit="${r.exitCode}">\n${out}\n</bash-output>\n(The user ran this command themselves; use the output as context.)` }] });
    } finally {
      setBusy(false);
    }
  };

  const getSuggestions = useCallback(async (before: string): Promise<Suggestion[]> => {
    const cmd = /^\/([\w:-]*)$/.exec(before);
    if (cmd) return completeCommand(cmd[1]!, rt).map((x) => ({ value: '/' + x.name, label: '/' + x.name, description: x.description }));
    const at = /@([^\s]*)$/.exec(before);
    if (at) return (await completePath(at[1]!, rt.cwd)).map((p) => ({ value: '@' + p, label: p }));
    return [];
  }, []);

  const cycleMode = useCallback(() => {
    const cur = rt.permissions.mode;
    const next = MODES[(MODES.indexOf(cur as PermissionMode) + 1) % MODES.length]!;
    rt.setMode(next);
    setMode(next);
  }, []);

  useEffect(() => {
    if (initialPrompt) void onSubmit(initialPrompt);
  }, []);

  const spin = (unicode ? SPINNER : SPINNER_ASCII)[frame % (unicode ? SPINNER.length : SPINNER_ASCII.length)]!;
  const elapsed = busy ? Math.floor((Date.now() - startedAt.current) / 1000) : 0;
  const frac = ctxInfo.window ? ctxInfo.tokens / ctxInfo.window : 0;
  const [modeText, modeColor] = MODE_LABEL[mode] ?? ['', theme.faint];

  return (
    <Box flexDirection="column">
      <Static items={items}>{(it) => <Text key={it.id}>{it.text + '\n'}</Text>}</Static>

      {streaming ? (
        <Box flexDirection="column">
          <Text>
            {renderMarkdown(streaming, width - 2)
              .split('\n')
              .map((l, i) => (i === 0 ? c.brand('✦ ') : '  ') + l)
              .join('\n')}
          </Text>
        </Box>
      ) : null}

      {[...tools.values()].map((t) => (
        <Box key={t.id} flexDirection="column">
          <Text>
            <Text color={theme.brand}>{spin} </Text>
            <Text bold>{t.name}</Text>
            <Text color={theme.dim}>({t.args})</Text>
            <Text color={theme.faint}> {Math.floor((Date.now() - t.started) / 1000)}s</Text>
          </Text>
          {t.progress
            ? t.progress
                .split('\n')
                .filter(Boolean)
                .slice(-4)
                .map((l, i) => (
                  <Text key={i} color={theme.faint}>
                    {'     ' + l.slice(0, width - 6)}
                  </Text>
                ))
            : null}
        </Box>
      ))}

      {[...subs.entries()].map(([id, s]) => (
        <Text key={id}>
          <Text color={theme.accent}>{spin} </Text>
          <Text color={theme.brand} bold>
            {s.name}
          </Text>
          <Text color={theme.dim}> {s.description}</Text>
          <Text color={theme.faint}> {s.status === 'queued' ? '(queued)' : s.last ? `· ${s.last.slice(0, 60)}` : ''}</Text>
        </Text>
      ))}

      {todos.length > 0 && busy ? (
        <Box flexDirection="column" marginLeft={2}>
          {todos.slice(0, 10).map((t: any, i: number) => (
            <Text key={i} color={t.status === 'completed' ? theme.faint : t.status === 'in_progress' ? theme.brand : theme.dim} strikethrough={t.status === 'completed'}>
              {t.status === 'completed' ? '✔ ' : t.status === 'in_progress' ? '◐ ' : '○ '}
              {t.status === 'in_progress' && t.activeForm ? t.activeForm : t.content}
            </Text>
          ))}
        </Box>
      ) : null}

      {busy && !dialog ? (
        <Text>
          <Text color={theme.accent}>{spin} </Text>
          <Text color={theme.brand}>{status || 'Working…'}</Text>
          <Text color={theme.faint}> ({elapsed}s · esc to interrupt)</Text>
        </Text>
      ) : null}

      {dialog?.kind === 'permission' ? (
        <PermissionDialog
          req={dialog.req}
          onAnswer={(a) => {
            dialog.resolve(a);
            setDialog(null);
          }}
        />
      ) : null}
      {dialog?.kind === 'plan' ? (
        <PlanDialog
          plan={dialog.plan}
          onAnswer={(a) => {
            dialog.resolve(a);
            setDialog(null);
            if (a.decision === 'approve') setMode(a.mode);
          }}
        />
      ) : null}
      {dialog?.kind === 'question' ? (
        <QuestionDialog
          question={dialog.question}
          options={dialog.options}
          onAnswer={(a) => {
            dialog.resolve(a);
            setDialog(null);
          }}
        />
      ) : null}

      <PromptInput
        placeholder={busy ? 'Queue a message for STELLA…' : 'Ask STELLA to build, fix or explain anything…'}
        history={history}
        active={!dialog}
        busy={busy}
        modeLabel={modeText}
        modeColor={modeColor}
        onSubmit={(v) => void onSubmit(v)}
        onInterrupt={() => {
          rt.interrupt();
          setStatus('Interrupting…');
        }}
        onExitRequest={() => void quit()}
        onCycleMode={cycleMode}
        onClearScreen={() => ctx.clearScreen()}
        getSuggestions={getSuggestions}
      />
      <Text>
        {'  '}
        {c.brand('✦')} {c.dim(modelName)} {c.faint('·')} {bar(frac, 10)} {c.faint(`${Math.round(frac * 100)}% ctx`)} {c.faint('·')} {c.dim('$' + cost.toFixed(cost < 1 ? 3 : 2))} {c.faint('·')} {c.faint(truncateTitle(rt.session.title, 30))}
        {rt.mcp.list().some((s) => s.status === 'connected') ? c.faint(` · mcp ${rt.mcp.list().filter((s) => s.status === 'connected').length}`) : ''}
      </Text>
    </Box>
  );
}

function truncateTitle(t: string, n: number) {
  return t.length > n ? t.slice(0, n - 1) + '…' : t;
}

function banner(rt: Runtime, version: string, width: number): string {
  const m = rt.main.model;
  const lines: string[] = [];
  if (width >= 56) for (const l of LOGO) lines.push(gradient(l));
  else lines.push(gradient('  ✦ STELLA CODER'));
  lines.push(`  ${c.star('✦')} ${c.bold('STELLA CODER')} ${c.faint('v' + version)}  ${c.faint('autonomous AI coding agent')}`);
  lines.push('');
  lines.push(`  ${c.faint('model')}    ${c.brand2(m.name)} ${c.faint(`${m.provider}:${m.id}`)}`);
  lines.push(`  ${c.faint('project')}  ${rt.root}${rt.cwd !== rt.root ? c.faint(` (cwd ${path.relative(rt.root, rt.cwd)})`) : ''}`);
  lines.push(`  ${c.faint('session')}  ${rt.session.title === 'New session' ? c.faint('new') : rt.session.title} ${c.faint(rt.session.id)}`);
  if (rt.instructions.length) lines.push(`  ${c.faint('rules')}    ${rt.instructions.map((i) => path.basename(path.dirname(i.path)) + '/' + path.basename(i.path)).join(', ')}`);
  lines.push('');
  lines.push(`  ${c.faint('Tips:')} ${c.dim('/help')} ${c.faint('commands ·')} ${c.dim('/init')} ${c.faint('create STELLA.md ·')} ${c.dim('@file')} ${c.faint('attach ·')} ${c.dim('shift+tab')} ${c.faint('modes ·')} ${c.dim('esc')} ${c.faint('interrupt')}`);
  return lines.join('\n');
}

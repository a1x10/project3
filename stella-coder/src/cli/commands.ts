import { promises as fs } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import type { Runtime } from '../agent/runtime.js';
import { HOOK_EVENTS } from '../hooks/engine.js';
import { settingsFile, updateSettings, setCredential, PermissionModeSchema, type PermissionMode, type SettingsScope } from '../config/settings.js';
import { stellaHome } from '../config/paths.js';
import { costUsd } from '../providers/types.js';
import { git, gitStatus } from '../git/git.js';
import { maskKey } from '../utils/redact.js';
import { which } from '../utils/which.js';
import { bashShell, powershellShell } from '../tools/process.js';
import { exists } from '../utils/fsutil.js';
import { c } from './theme.js';

export interface CommandContext {
  rt: Runtime;
  print(text: string, level?: 'info' | 'warn' | 'error' | 'md'): void;
  submit(prompt: string): Promise<void>;
  exit(): void;
  clearScreen?(): void;
}

export interface SlashCommand {
  name: string;
  aliases?: string[];
  description: string;
  usage?: string;
  run(args: string, ctx: CommandContext): Promise<void> | void;
}

const fmtTok = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(2)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n));
const usd = (n: number) => `$${n < 0.01 && n > 0 ? n.toFixed(4) : n.toFixed(2)}`;

function words(args: string): string[] {
  const out: string[] = [];
  const re = /"([^"]*)"|'([^']*)'|(\S+)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(args))) out.push(m[1] ?? m[2] ?? m[3]!);
  return out;
}

export function bar(frac: number, width = 20): string {
  const f = Math.max(0, Math.min(1, frac));
  const full = Math.round(f * width);
  const color = f > 0.85 ? c.err : f > 0.6 ? c.warn : c.ok;
  return color('█'.repeat(full)) + c.faint('░'.repeat(width - full));
}

export const COMMANDS: SlashCommand[] = [
  {
    name: 'help',
    aliases: ['?'],
    description: 'Show commands and keyboard shortcuts',
    run(_a, ctx) {
      const lines = ['**Commands**', ...COMMANDS.map((x) => `- \`/${x.name}${x.usage ? ' ' + x.usage : ''}\` — ${x.description}`)];
      const custom = ctx.rt.skills.listCommands();
      if (custom.length) lines.push('', '**Custom commands**', ...custom.map((x) => `- \`/${x.name}${x.argumentHint ? ' ' + x.argumentHint : ''}\` — ${x.description} _(${x.scope})_`));
      const skills = ctx.rt.skills.list().filter((s) => s.userInvocable);
      if (skills.length) lines.push('', '**Skills** (run as /name)', ...skills.map((s) => `- \`/${s.name}\` — ${s.description}`));
      lines.push(
        '',
        '**Keys**',
        '- `Enter` send · `\\` + `Enter` or `Ctrl+J` new line · `↑/↓` history · `Tab` complete commands/@paths',
        '- `Esc` interrupt the agent · `Shift+Tab` cycle permission mode · `Ctrl+C` interrupt / exit · `Ctrl+L` clear screen',
        '- `@path` mentions a file (its contents are attached) · `!cmd` runs a shell command directly',
      );
      ctx.print(lines.join('\n'), 'md');
    },
  },
  {
    name: 'clear',
    aliases: ['new', 'reset'],
    description: 'Start a new conversation (the old one stays in /resume)',
    async run(_a, ctx) {
      await ctx.rt.clear();
      ctx.clearScreen?.();
      ctx.print(`New session ${ctx.rt.session.id}`);
    },
  },
  {
    name: 'compact',
    usage: '[instructions]',
    description: 'Summarize the conversation to free context',
    async run(a, ctx) {
      if (ctx.rt.main.messages.length < 2) return ctx.print('Nothing to compact yet.');
      ctx.print('Compacting…');
      const r = await ctx.rt.main.compact({ instructions: a || undefined });
      ctx.print(`Compacted: ~${fmtTok(r.before)} → ~${fmtTok(r.after)} tokens.`);
    },
  },
  {
    name: 'model',
    usage: '[alias|provider:model]',
    description: 'Show or switch the model',
    run(a, ctx) {
      if (a.trim()) {
        const m = ctx.rt.switchModel(a.trim());
        return ctx.print(`Model → **${m.name}** (\`${m.provider}:${m.id}\`) · ${fmtTok(m.contextWindow)} context · $${m.inputPrice}/$${m.outputPrice} per MTok${m.notes ? `\n_${m.notes}_` : ''}`, 'md');
      }
      const cur = ctx.rt.main.model;
      const aliases = ctx.rt.registry.aliasMap;
      const lines = [`Current: **${cur.name}** \`${cur.provider}:${cur.id}\``, '', '| model | provider | context | $ in/out per MTok | tools |', '|---|---|---|---|---|'];
      for (const m of ctx.rt.registry.listModels()) lines.push(`| ${m.id === cur.id ? '▸ ' : ''}${m.name} \`${m.provider}:${m.id}\` | ${m.provider} | ${fmtTok(m.contextWindow)} | ${m.inputPrice}/${m.outputPrice} | ${m.toolCalling ? 'yes' : 'no'} |`);
      lines.push('', `Aliases: ${Object.entries(aliases).map(([k, v]) => `\`${k}\`→${v}`).join(', ')}`, 'Any provider model works as `provider:model-id`, e.g. `ollama:qwen2.5-coder:14b`, `openrouter:anthropic/claude-sonnet-4.5`.');
      ctx.print(lines.join('\n'), 'md');
    },
  },
  {
    name: 'effort',
    usage: '[low|medium|high|xhigh|max]',
    description: 'Show or set reasoning effort (supported models)',
    run(a, ctx) {
      const v = a.trim();
      if (!v) return ctx.print(`Effort: ${ctx.rt.main.effort ?? '(not supported by this model)'}`);
      if (!['low', 'medium', 'high', 'xhigh', 'max'].includes(v)) return ctx.print('Use low, medium, high, xhigh or max', 'warn');
      if (!ctx.rt.main.model.supportsEffort) return ctx.print('This model does not support effort.', 'warn');
      ctx.rt.main.effort = v as any;
      ctx.print(`Effort → ${v}`);
    },
  },
  {
    name: 'status',
    description: 'Session, model, permissions, MCP and environment status',
    async run(_a, ctx) {
      const rt = ctx.rt;
      const m = rt.main.model;
      const g = await gitStatus(rt.root).catch(() => null);
      const lines = [
        `**Session** ${rt.session.title} \`${rt.session.id}\``,
        `**Model** ${m.name} \`${m.provider}:${m.id}\`${rt.main.effort ? ` · effort ${rt.main.effort}` : ''}`,
        `**Mode** ${rt.permissions.mode}`,
        `**Directory** ${rt.cwd}${rt.root !== rt.cwd ? ` (project root ${rt.root})` : ''}`,
        `**Git** ${g ? `${g.branch} · ${g.staged.length} staged, ${g.unstaged.length} unstaged, ${g.untracked.length} untracked` : 'not a repository'}`,
        `**Index** ${rt.index.isBuilt ? `${rt.index.size} files` : 'building…'}`,
        `**Instructions** ${rt.instructions.length ? rt.instructions.map((i) => path.relative(rt.root, i.path) || i.path).join(', ') : 'none (run /init)'}`,
        `**MCP** ${rt.mcp.list().map((s) => `${s.name}:${s.status}`).join(', ') || 'none'}`,
        `**Skills** ${rt.skills.list().length} · **Agents** ${rt.subagents.list().length} · **Hooks** ${rt.hooks.configured().length}`,
        `**Trusted** ${rt.trusted ? 'yes' : 'no'}`,
      ];
      ctx.print(lines.join('\n'), 'md');
    },
  },
  {
    name: 'cost',
    description: 'Token usage and cost for this session',
    run(_a, ctx) {
      const s = ctx.rt.session;
      const u = s.usage;
      const m = ctx.rt.main.model;
      ctx.print(
        [
          `**Total cost** ${usd(s.costUsd)}  (prices: ${m.name} $${m.inputPrice}/$${m.outputPrice} per MTok)`,
          `Input ${fmtTok(u.inputTokens)} · Output ${fmtTok(u.outputTokens)} · Cache read ${fmtTok(u.cacheReadTokens ?? 0)} · Cache write ${fmtTok(u.cacheWriteTokens ?? 0)}`,
          `Main agent this session: ${usd(ctx.rt.main.totalCost)} · subagents: ${usd(Math.max(0, s.costUsd - ctx.rt.main.totalCost))}`,
          m.inputPrice === 0 ? '_Model not in price catalog — costs shown as $0. Set prices in settings.providers.<name>.models._' : '',
        ].join('\n'),
        'md',
      );
    },
  },
  {
    name: 'context',
    description: 'Context window usage breakdown',
    async run(_a, ctx) {
      const { estimateTokens, estimateMessagesTokens } = await import('../utils/tokens.js');
      const rt = ctx.rt;
      const sys = estimateTokens(await rt.systemPrompt());
      const tools = estimateTokens(JSON.stringify(rt.allTools().map((t) => ({ n: t.name, d: t.description }))));
      const msgs = estimateMessagesTokens(rt.main.messages);
      const used = Math.max(rt.main.contextTokens(), sys + tools + msgs);
      const win = rt.main.model.contextWindow;
      ctx.print(
        [
          `${bar(used / win, 30)} ${fmtTok(used)} / ${fmtTok(win)} (${((used / win) * 100).toFixed(1)}%)`,
          `- System prompt & instructions: ~${fmtTok(sys)}`,
          `- Tool definitions (${rt.allTools().length}): ~${fmtTok(tools)}`,
          `- Messages (${rt.main.messages.length}): ~${fmtTok(msgs)}`,
          `- Auto-compact at ${Math.round((rt.settings.autoCompactThreshold ?? 0.8) * 100)}% of usable window`,
        ].join('\n'),
        'md',
      );
    },
  },
  {
    name: 'doctor',
    description: 'Diagnose installation, credentials and environment',
    async run(a, ctx) {
      const rt = ctx.rt;
      const ok = (b: boolean) => (b ? c.ok('✔') : c.err('✘'));
      const lines: string[] = [];
      const major = Number(process.versions.node.split('.')[0]);
      lines.push(`${ok(major >= 20)} Node ${process.versions.node} (need ≥ 20)`);
      lines.push(`${ok(true)} Platform ${process.platform} ${os.release()} · ${process.arch} · TTY ${process.stdout.isTTY ? 'yes' : 'no'} · ${process.stdout.columns ?? '?'} cols`);
      const sh = bashShell(rt.settings.shell);
      lines.push(`${ok(!!sh)} Bash shell: ${sh?.file ?? 'not found (Windows: install Git for Windows)'}`);
      lines.push(`${c.dim('•')} PowerShell: ${powershellShell()?.file ?? 'not found'}`);
      lines.push(`${ok(!!which('git'))} git: ${which('git') ?? 'not found'}`);
      lines.push(`${which('rg') ? ok(true) : c.warn('!')} ripgrep: ${which('rg') ?? 'not found (built-in search is used)'}`);
      for (const p of rt.registry.listProviders()) {
        const key = await rt.registry.apiKeyFor(p.name);
        const local = /localhost|127\.0\.0\.1/.test(p.baseUrl);
        lines.push(`${key || local ? ok(true) : c.faint('○')} provider ${p.name} (${p.type}) ${p.baseUrl} key=${local && !key ? 'not needed' : maskKey(key)}`);
      }
      try {
        const m = rt.registry.resolve();
        lines.push(`${ok(true)} default model ${m.provider}:${m.id}`);
      } catch (e) {
        lines.push(`${ok(false)} default model: ${(e as Error).message}`);
      }
      for (const e of rt.loaded.errors) lines.push(`${ok(false)} ${e}`);
      const writable = await fs.mkdir(stellaHome(), { recursive: true }).then(() => fs.access(stellaHome(), 2).then(() => true, () => false), () => false);
      lines.push(`${ok(writable)} data dir ${stellaHome()}`);
      lines.push(`${ok(rt.trusted)} workspace trust ${rt.trusted ? 'granted' : 'not granted (project hooks/MCP disabled)'}`);
      for (const s of rt.mcp.list()) lines.push(`${ok(s.status === 'connected')} MCP ${s.name}: ${s.status}${s.error ? ` — ${s.error.split('\n')[0]}` : ''}`);
      for (const e of rt.skills.errors) lines.push(`${c.warn('!')} ${e}`);
      if (a.includes('--network')) {
        for (const p of rt.registry.listProviders()) {
          const t0 = Date.now();
          const r = await fetch(p.baseUrl, { method: 'GET', signal: AbortSignal.timeout(5000) }).then((x) => `HTTP ${x.status}`, (e) => `unreachable (${(e as Error).message})`);
          lines.push(`${c.dim('•')} ${p.name}: ${r} in ${Date.now() - t0}ms`);
        }
      }
      ctx.print(lines.join('\n'));
    },
  },
  {
    name: 'config',
    usage: '[get <key> | set <key> <json> [--user|--project|--local] | path]',
    description: 'Show or edit settings',
    async run(a, ctx) {
      const [sub, key, ...rest] = words(a);
      let scope: SettingsScope = 'local';
      const valueParts = rest.filter((r) => {
        if (r === '--user') scope = 'user';
        else if (r === '--project') scope = 'project';
        else if (r === '--local') scope = 'local';
        else return true;
        return false;
      });
      if (!sub) return ctx.print('```json\n' + JSON.stringify({ ...ctx.rt.settings, providers: redactProviders(ctx.rt.settings.providers) }, null, 2) + '\n```', 'md');
      if (sub === 'path') return ctx.print(['user', 'project', 'local'].map((s) => `${s}: ${settingsFile(s as SettingsScope, ctx.rt.root)}`).join('\n'));
      if (sub === 'get') return ctx.print(JSON.stringify(getPath(ctx.rt.settings, key ?? ''), null, 2) ?? 'undefined');
      if (sub === 'set' && key) {
        const raw = valueParts.join(' ');
        let value: unknown = raw;
        try {
          value = JSON.parse(raw);
        } catch {
          /* string */
        }
        await updateSettings(scope, ctx.rt.root, (s) => setPath(s as Record<string, unknown>, key, value) as any);
        return ctx.print(`Set ${key} in ${scope} settings. Restart or /reload to apply everywhere.`);
      }
      ctx.print('Usage: /config [get <key> | set <key> <value> [--user|--project|--local] | path]', 'warn');
    },
  },
  {
    name: 'permissions',
    aliases: ['allowed-tools'],
    usage: '[allow|deny|ask <rule> | remove <rule> | mode <mode> | log]',
    description: 'Manage permission rules and mode',
    async run(a, ctx) {
      const [sub, ...rest] = words(a);
      const rule = rest.join(' ');
      const pe = ctx.rt.permissions;
      if (!sub) {
        const r = pe.listRules();
        return ctx.print(
          [`**Mode** ${pe.mode}`, `**Allow** ${r.allow.join(', ') || '—'}`, `**Ask** ${r.ask.join(', ') || '—'}`, `**Deny** ${r.deny.join(', ') || '—'}`, `**Session** ${r.session.join(', ') || '—'}`, '', 'Rule syntax: `Tool`, `Bash(npm test:*)`, `Edit(src/**)`, `Read(//etc/hosts)`, `WebFetch(domain:docs.rs)`, `mcp__server`'].join('\n'),
          'md',
        );
      }
      if (sub === 'mode') {
        const m = PermissionModeSchema.safeParse(rest[0]);
        if (!m.success) return ctx.print('Modes: default, plan, acceptEdits, auto, bypassPermissions', 'warn');
        ctx.rt.setMode(m.data);
        return ctx.print(`Permission mode → ${m.data}${m.data === 'bypassPermissions' ? c.err('  ⚠ every action runs without confirmation') : ''}`);
      }
      if (sub === 'log') return ctx.print(pe.log.slice(-30).map((l) => `${new Date(l.ts).toLocaleTimeString()} ${l.decision.padEnd(13)} ${l.tool} — ${l.summary} (${l.reason})`).join('\n') || 'No decisions yet.');
      if ((sub === 'allow' || sub === 'deny' || sub === 'ask') && rule) {
        pe.addRule(sub, rule);
        await updateSettings('local', ctx.rt.root, (s) => ({ ...s, permissions: { ...(s.permissions ?? {}), [sub]: [...new Set([...((s.permissions as any)?.[sub] ?? []), rule])] } }));
        return ctx.print(`Added ${sub} rule ${rule} (saved to .stella/settings.local.json)`);
      }
      if (sub === 'remove' && rule) {
        await updateSettings('local', ctx.rt.root, (s) => {
          const p: any = { ...(s.permissions ?? {}) };
          for (const k of ['allow', 'deny', 'ask']) p[k] = (p[k] ?? []).filter((x: string) => x !== rule);
          return { ...s, permissions: p };
        });
        return ctx.print(`Removed ${rule} from local settings (restart to drop it from this session).`);
      }
      ctx.print('Usage: /permissions [allow|deny|ask <rule> | remove <rule> | mode <mode> | log]', 'warn');
    },
  },
  {
    name: 'plan',
    usage: '[task]',
    description: 'Toggle plan mode (read-only analysis and planning)',
    async run(a, ctx) {
      const on = ctx.rt.permissions.mode !== 'plan';
      ctx.rt.setMode(on ? 'plan' : 'default');
      ctx.print(on ? 'Plan mode ON — STELLA will investigate read-only and present a plan for approval.' : 'Plan mode OFF (default mode).');
      if (on && a.trim()) await ctx.submit(a.trim());
    },
  },
  {
    name: 'memory',
    usage: '[list|add <type> <text>|edit <id> <text>|rm <id>|clear <type>|open]',
    description: 'View and manage long-term memory',
    async run(a, ctx) {
      const [sub, x, ...rest] = words(a);
      const mem = ctx.rt.memory;
      const types = ['user', 'project', 'technical', 'task', 'session'];
      if (!sub || sub === 'list') {
        const block = await mem.exportMarkdown();
        const files = ctx.rt.instructions.map((i) => `- ${i.path} (${i.scope})`).join('\n');
        return ctx.print(`${block || '_No memories yet._'}\n\n**Instruction files (STELLA.md)**\n${files || '- none'}`, 'md');
      }
      if (sub === 'add') {
        const type = types.includes(x ?? '') ? x! : 'project';
        const text = (types.includes(x ?? '') ? rest : [x, ...rest]).join(' ');
        const r = await mem.add(type as any, text, undefined, ctx.rt.session.id);
        ctx.rt.invalidatePrompt();
        return ctx.print(r.error ? r.error : r.duplicateOf ? `Already stored as [${r.duplicateOf.id}]` : `Saved [${r.item!.id}] (${type})`, r.error ? 'warn' : 'info');
      }
      if (sub === 'edit' && x) {
        const it = await mem.update(x, rest.join(' '));
        ctx.rt.invalidatePrompt();
        return ctx.print(it ? `Updated [${x}]` : `No memory ${x}`);
      }
      if ((sub === 'rm' || sub === 'delete') && x) {
        const ok = await mem.remove(x);
        ctx.rt.invalidatePrompt();
        return ctx.print(ok ? `Deleted [${x}]` : `No memory ${x}`);
      }
      if (sub === 'clear' && x && types.includes(x)) {
        const n = await mem.clear(x as any);
        ctx.rt.invalidatePrompt();
        return ctx.print(`Cleared ${n} ${x} memories.`);
      }
      if (sub === 'open') return ctx.print(`Project memory: ${path.join(ctx.rt.paths.memoryDir, 'memory.json')}\nUser memory: ${path.join(stellaHome(), 'memory.json')}\nProject instructions: ${path.join(ctx.rt.root, 'STELLA.md')}`);
      ctx.print('Usage: /memory [list|add <type> <text>|edit <id> <text>|rm <id>|clear <type>|open]', 'warn');
    },
  },
  {
    name: 'agents',
    usage: '[list|runs|cancel <id>|create <name> <description>]',
    description: 'Subagent types and running subagents',
    async run(a, ctx) {
      const [sub, x, ...rest] = words(a);
      const sm = ctx.rt.subagents;
      if (!sub || sub === 'list') return ctx.print(sm.list().map((d) => `- **${d.name}** _(${d.source}${d.permissionMode ? `, ${d.permissionMode}` : ''})_ — ${d.description}${d.tools ? `\n  tools: ${d.tools.join(', ')}` : ''}`).join('\n'), 'md');
      if (sub === 'runs') return ctx.print(sm.listRuns().map((r) => `${r.runId} ${r.status} ${r.toolCalls} tools ${Math.round((r.durationMs ?? Date.now() - r.startedAt) / 1000)}s ${usd(r.costUsd)} — ${r.description}`).join('\n') || 'No subagent runs yet.');
      if (sub === 'cancel' && x) return ctx.print(sm.cancel(x) ? `Cancelled ${x}` : `${x} is not running`);
      if (sub === 'create' && x) {
        const dir = path.join(ctx.rt.root, '.stella', 'agents');
        await fs.mkdir(dir, { recursive: true });
        const file = path.join(dir, `${x}.md`);
        if (await exists(file)) return ctx.print(`${file} already exists`, 'warn');
        await fs.writeFile(file, `---\nname: ${x}\ndescription: ${rest.join(' ') || 'Custom agent'}\ntools: Read, Grep, Glob, Edit, Bash\nmodel: inherit\n---\n\nYou are a specialized subagent. Describe its role, process and report format here.\n`);
        await sm.load();
        ctx.rt.invalidatePrompt();
        return ctx.print(`Created ${file}`);
      }
      ctx.print('Usage: /agents [list|runs|cancel <id>|create <name> <description>]', 'warn');
    },
  },
  {
    name: 'skills',
    usage: '[list|show <name>|create <name> <description> [--user]|delete <name>|reload]',
    description: 'Manage skills',
    async run(a, ctx) {
      const [sub, x, ...rest] = words(a);
      const sr = ctx.rt.skills;
      if (!sub || sub === 'list') return ctx.print(sr.list().map((s) => `- **${s.name}** _(${s.scope}${s.modelInvocable ? '' : ', manual'})_ — ${s.description}`).join('\n') || 'No skills.', 'md');
      if (sub === 'show' && x) {
        const s = sr.get(x);
        return ctx.print(s ? `${s.file}\n\n${s.body}` : `No skill ${x}`, s ? 'md' : 'warn');
      }
      if (sub === 'create' && x) {
        const user = rest.includes('--user');
        const file = await sr.create(user ? 'user' : 'project', x, rest.filter((r) => r !== '--user').join(' ') || `Skill ${x}`);
        ctx.rt.invalidatePrompt();
        return ctx.print(`Created ${file} — edit it to add instructions, references/ and scripts/.`);
      }
      if (sub === 'delete' && x) {
        const ok = await sr.remove(x);
        ctx.rt.invalidatePrompt();
        return ctx.print(ok ? `Deleted skill ${x}` : `Cannot delete ${x} (missing, builtin or plugin)`);
      }
      if (sub === 'reload') {
        await ctx.rt.reloadInstructions();
        return ctx.print(`Reloaded ${sr.list().length} skills.`);
      }
      ctx.print('Usage: /skills [list|show|create|delete|reload]', 'warn');
    },
  },
  {
    name: 'hooks',
    usage: '[list|history|events|add <event> <matcher> <command>]',
    description: 'Show configured hooks and recent runs',
    async run(a, ctx) {
      const [sub, ev, matcher, ...cmd] = words(a);
      const he = ctx.rt.hooks;
      if (!sub || sub === 'list') return ctx.print(he.configured().map((h) => `- ${h.event}${h.matcher ? ` [${h.matcher}]` : ''}: \`${h.command}\``).join('\n') || 'No hooks configured. Add them in settings.json under "hooks" or with /hooks add.', 'md');
      if (sub === 'events') return ctx.print(HOOK_EVENTS.join(', '));
      if (sub === 'history') return ctx.print(he.history.slice(-20).map((r) => `${new Date(r.ts).toLocaleTimeString()} ${r.event} exit=${r.exitCode}${r.timedOut ? ' TIMEOUT' : ''} ${r.durationMs}ms ${r.command}`).join('\n') || 'No hook runs yet.');
      if (sub === 'add' && ev && matcher && cmd.length) {
        if (!(HOOK_EVENTS as readonly string[]).includes(ev)) return ctx.print(`Unknown event. Events: ${HOOK_EVENTS.join(', ')}`, 'warn');
        await updateSettings('local', ctx.rt.root, (s) => ({ ...s, hooks: { ...(s.hooks ?? {}), [ev]: [...((s.hooks as any)?.[ev] ?? []), { matcher: matcher === '*' ? undefined : matcher, hooks: [{ type: 'command', command: cmd.join(' ') }] }] } }));
        return ctx.print(`Added ${ev} hook (local settings). Restart STELLA to activate it.`);
      }
      ctx.print('Usage: /hooks [list|history|events|add <event> <matcher|*> <command>]', 'warn');
    },
  },
  {
    name: 'mcp',
    usage: '[list|add <name> <command...>|add <name> --url <url>|remove <name>|test <name>|tools <name>]',
    description: 'Manage MCP servers',
    async run(a, ctx) {
      const [sub, name, ...rest] = words(a);
      const mm = ctx.rt.mcp;
      if (!sub || sub === 'list') {
        const list = mm.list();
        return ctx.print(list.length ? list.map((s) => `${s.status === 'connected' ? c.ok('●') : s.status === 'failed' ? c.err('●') : c.faint('○')} ${s.name} (${s.source}, ${s.config.type ?? (s.config.url ? 'http' : 'stdio')}) ${s.status} · ${s.tools.length} tools${s.error ? `\n    ${c.err(s.error.split('\n')[0]!)}` : ''}`).join('\n') : 'No MCP servers. Add one: /mcp add <name> <command> [args] or /mcp add <name> --url <url>');
      }
      if (sub === 'add' && name) {
        const urlIdx = rest.indexOf('--url');
        const cfg: any = urlIdx >= 0 ? { type: rest.includes('--sse') ? 'sse' : 'http', url: rest[urlIdx + 1] } : { type: 'stdio', command: rest[0], args: rest.slice(1) };
        const hdr = rest.indexOf('--header');
        if (hdr >= 0 && rest[hdr + 1]) {
          const [k, ...v] = rest[hdr + 1]!.split(':');
          cfg.headers = { [k!.trim()]: v.join(':').trim() };
        }
        if (!cfg.url && !cfg.command) return ctx.print('Provide a command or --url', 'warn');
        const scope: SettingsScope = rest.includes('--user') ? 'user' : rest.includes('--project') ? 'project' : 'local';
        if (cfg.args) cfg.args = cfg.args.filter((x: string) => !['--user', '--project', '--local'].includes(x));
        await updateSettings(scope, ctx.rt.root, (s) => ({ ...s, mcpServers: { ...(s.mcpServers ?? {}), [name]: cfg } }));
        mm.register(name, cfg, scope === 'user' ? 'user' : scope, true);
        const st = await mm.connect(name);
        return ctx.print(`Added ${name} (${scope}): ${st.status}${st.error ? ` — ${st.error}` : ` · ${st.tools.length} tools`}`);
      }
      if (sub === 'remove' && name) {
        for (const scope of ['local', 'project', 'user'] as SettingsScope[]) {
          await updateSettings(scope, ctx.rt.root, (s) => {
            if (!s.mcpServers?.[name]) return s;
            const { [name]: _drop, ...restS } = s.mcpServers;
            return { ...s, mcpServers: restS };
          });
        }
        await mm.remove(name);
        return ctx.print(`Removed ${name}`);
      }
      if ((sub === 'test' || sub === 'connect') && name) {
        const st = await mm.connect(name);
        return ctx.print(`${name}: ${st.status}${st.error ? `\n${st.error}` : `\n${st.tools.map((t) => `  - ${t.name}: ${(t.description ?? '').slice(0, 80)}`).join('\n')}`}`);
      }
      if (sub === 'tools' && name) {
        const s = mm.get(name);
        return ctx.print(s ? s.tools.map((t) => `- mcp__${name}__${t.name}: ${t.description ?? ''}`).join('\n') || 'No tools' : `No server ${name}`);
      }
      ctx.print('Usage: /mcp [list|add|remove|test|tools]', 'warn');
    },
  },
  {
    name: 'resume',
    aliases: ['continue'],
    usage: '[id|title]',
    description: 'Resume a previous session',
    async run(a, ctx) {
      if (!a.trim()) {
        const list = await ctx.rt.sessions.list();
        return ctx.print(list.slice(0, 20).map((s, i) => `${String(i + 1).padStart(2)}. ${c.brand2(s.id)} ${new Date(s.updatedAt).toLocaleString()} ${s.messageCount} msgs ${usd(s.costUsd)} — ${s.title}`).join('\n') + '\n\nResume with /resume <id or number>' || 'No sessions.');
      }
      const list = await ctx.rt.sessions.list();
      const n = Number(a.trim());
      const target = Number.isInteger(n) && n > 0 && n <= list.length ? list[n - 1]!.id : a.trim();
      await ctx.rt.resume(target);
      ctx.print(`Resumed "${ctx.rt.session.title}" (${ctx.rt.main.messages.length} messages).`);
    },
  },
  {
    name: 'sessions',
    usage: '[search <text>|delete <id>]',
    description: 'List, search or delete sessions',
    async run(a, ctx) {
      const [sub, ...rest] = words(a);
      if (sub === 'search') {
        const r = await ctx.rt.sessions.search(rest.join(' '));
        return ctx.print(r.map((x) => `${x.meta.id} — ${x.meta.title}\n   ${c.dim(x.snippet)}`).join('\n') || 'No matches.');
      }
      if (sub === 'delete' && rest[0]) {
        if (rest[0] === ctx.rt.session.id) return ctx.print('Cannot delete the active session.', 'warn');
        return ctx.print((await ctx.rt.sessions.delete(rest[0])) ? `Deleted ${rest[0]}` : 'Not found');
      }
      return COMMANDS.find((x) => x.name === 'resume')!.run('', ctx);
    },
  },
  {
    name: 'rename',
    usage: '<title>',
    description: 'Rename the current session',
    async run(a, ctx) {
      if (!a.trim()) return ctx.print('Usage: /rename <title>', 'warn');
      ctx.rt.session.title = a.trim().slice(0, 120);
      await ctx.rt.sessions.saveMeta(ctx.rt.session);
      ctx.print(`Session renamed to "${ctx.rt.session.title}"`);
    },
  },
  {
    name: 'rewind',
    aliases: ['undo', 'checkpoint'],
    usage: '[turn-number] [--force]',
    description: 'Restore files to the state before a turn (checkpoints)',
    async run(a, ctx) {
      const turns = await ctx.rt.checkpoints.listTurns();
      const withFiles = turns.filter((t) => t.files.length);
      if (!a.trim()) {
        if (!withFiles.length) return ctx.print('No file changes recorded in this session.');
        return ctx.print(withFiles.map((t) => `#${t.turnIndex} ${new Date(t.ts).toLocaleTimeString()} "${t.prompt.slice(0, 60)}" — ${t.files.map((f) => path.relative(ctx.rt.root, f)).join(', ')}`).join('\n') + '\n\n/rewind <#> restores files to the state BEFORE that turn. /undo last = most recent.');
      }
      const force = a.includes('--force');
      const arg = a.replace('--force', '').trim();
      const idx = arg === 'last' ? withFiles[withFiles.length - 1]?.turnIndex : Number(arg.replace('#', ''));
      if (idx === undefined || Number.isNaN(idx)) return ctx.print('Give a turn number from /rewind', 'warn');
      const r = await ctx.rt.checkpoints.rewind(idx, { force });
      const rel = (f: string) => path.relative(ctx.rt.root, f);
      const lines = [`Restored ${r.restored.length} file(s)${r.restored.length ? ': ' + r.restored.map(rel).join(', ') : ''}`];
      if (r.removed.length) lines.push(`Removed ${r.removed.length} file(s) created by the agent: ${r.removed.map(rel).join(', ')}`);
      if (r.conflicts.length) lines.push(c.warn(`Skipped ${r.conflicts.length} file(s) changed outside STELLA since: ${r.conflicts.map((x) => rel(x.file)).join(', ')}. Use --force to overwrite.`));
      for (const f of [...r.restored, ...r.removed]) ctx.rt.readState.forget(f);
      ctx.rt.main.messages.push({ role: 'user', content: [{ type: 'text', text: `<system-reminder>The user rewound files to before turn #${idx}. Files restored: ${[...r.restored, ...r.removed].map(rel).join(', ') || 'none'}. Re-read files before editing them.</system-reminder>` }] });
      ctx.print(lines.join('\n'));
    },
  },
  {
    name: 'diff',
    usage: '[--git]',
    description: 'Show changes made in this session (or git diff)',
    async run(a, ctx) {
      if (a.includes('--git')) {
        const r = await git(['diff', '--no-ext-diff', '--stat', '-p'], ctx.rt.root);
        return ctx.print('```diff\n' + (r.stdout || 'No changes.') + '\n```', 'md');
      }
      const d = await ctx.rt.checkpoints.diff(0, ctx.rt.root);
      ctx.print(d ? '```diff\n' + d + '\n```' : 'No changes made by STELLA in this session.', 'md');
    },
  },
  {
    name: 'todos',
    description: 'Show the current task list',
    run(_a, ctx) {
      const t = ctx.rt.todos.get('main') ?? [];
      ctx.print(t.length ? t.map((x) => `${x.status === 'completed' ? c.ok('✔') : x.status === 'in_progress' ? c.brand('◐') : c.faint('○')} ${x.content}`).join('\n') : 'No todos.');
    },
  },
  {
    name: 'processes',
    aliases: ['bashes', 'ps'],
    usage: '[kill <id>]',
    description: 'Background processes started by the agent; command history',
    run(a, ctx) {
      const [sub, id] = words(a);
      if (sub === 'kill' && id) return ctx.print(ctx.rt.processes.stop(id) ? `Stopped ${id}` : `${id} not running`);
      const list = ctx.rt.processes.list();
      const hist = ctx.rt.processes.history.slice(-10);
      ctx.print(
        [
          list.length ? list.map((p) => `${p.id} pid=${p.pid} ${p.status} ${p.command}`).join('\n') : 'No background processes.',
          '',
          'Recent commands:',
          ...hist.map((h) => `  ${h.exitCode === 0 ? c.ok('✔') : c.err('✘')} ${h.command.slice(0, 100)} (${(h.durationMs / 1000).toFixed(1)}s)`),
        ].join('\n'),
      );
    },
  },
  {
    name: 'trust',
    description: 'Trust this folder (enables project hooks, MCP servers and plugins)',
    async run(_a, ctx) {
      await ctx.rt.trustProject();
      ctx.print('Folder trusted. Restart STELLA to load project hooks and MCP servers.');
    },
  },
  {
    name: 'add-dir',
    usage: '<path>',
    description: 'Allow access to an additional directory',
    async run(a, ctx) {
      const p = path.resolve(ctx.rt.cwd, a.trim());
      if (!a.trim() || !(await exists(p))) return ctx.print('Usage: /add-dir <existing path>', 'warn');
      ctx.rt.roots.push(p);
      await updateSettings('local', ctx.rt.root, (s) => ({ ...s, permissions: { ...(s.permissions ?? {}), additionalDirectories: [...new Set([...(s.permissions?.additionalDirectories ?? []), p])] } }));
      ctx.print(`Added ${p} to the workspace.`);
    },
  },
  {
    name: 'login',
    aliases: ['auth'],
    usage: '<provider> <api-key>',
    description: 'Store an API key for a provider (~/.stella/credentials.json, mode 600)',
    async run(a, ctx) {
      const [prov, key] = words(a);
      if (!prov || !key) return ctx.print('Usage: /login <provider> <api-key>   (providers: ' + ctx.rt.registry.listProviders().map((p) => p.name).join(', ') + ')', 'warn');
      await setCredential(`${prov}.apiKey`, key);
      ctx.print(`Saved key for ${prov} (${maskKey(key)}).`);
    },
  },
  {
    name: 'init',
    description: 'Analyze the codebase and create STELLA.md project instructions',
    async run(_a, ctx) {
      const existing = await exists(path.join(ctx.rt.root, 'STELLA.md'));
      await ctx.submit(
        `Analyze this codebase and ${existing ? 'improve the existing' : 'create a'} STELLA.md file in the project root. It is read automatically at the start of every session, so it must help a future AI agent be productive immediately. Include:\n1. Commands: how to build, lint, run tests (incl. a single test), run the app.\n2. High-level architecture: the big-picture structure that requires reading several files to understand (main modules, data flow, entry points).\n3. Conventions and gotchas specific to this repo (style, patterns, things to avoid).\nBe concise and specific; do not list every file or invent anything you cannot verify. Look at README, manifests, CI config, existing CLAUDE.md/AGENTS.md/.cursorrules/copilot instructions. ${existing ? 'Keep valid content, fix outdated parts.' : ''} Start the file with "# STELLA.md".`,
      );
      await ctx.rt.reloadInstructions();
    },
  },
  {
    name: 'review',
    usage: '[branch|commit|path]',
    description: 'Review code changes for bugs and quality',
    async run(a, ctx) {
      await ctx.submit(
        `Review ${a.trim() ? `the changes in ${a.trim()}` : 'the current uncommitted changes (git diff HEAD, plus untracked files) — if there are none, the last commit'}. Read the full context of each changed file, not just the diff. Report, most severe first: correctness bugs, regressions, security issues, missing edge cases, missing tests; then optional maintainability suggestions. For each: file:line, what goes wrong in which scenario, and a concrete fix. Do not modify files. If everything looks good, say so briefly.`,
      );
    },
  },
  {
    name: 'commit',
    usage: '[extra instructions]',
    description: 'Create a git commit with a well-written message',
    async run(a, ctx) {
      await ctx.submit(
        `Create a git commit for the current changes. Steps: run GitStatus and GitDiff (staged and unstaged) and GitLog for the repo's message style. Stage only files that belong to this change (never secrets, .env, large binaries, build output). Write a message: imperative subject under 72 chars, blank line, short body explaining why. Then commit with GitCommit and show the result. Do not push. ${a}`,
      );
    },
  },
  {
    name: 'security-review',
    description: 'Audit the pending changes or the codebase for vulnerabilities',
    async run(a, ctx) {
      await ctx.submit(`Use the Task tool with subagent_type "security-auditor" to audit ${a.trim() || 'the current uncommitted changes (or the most security-sensitive parts of the codebase if there are none)'}. Then present the verified findings ranked by severity with file:line and fixes.`);
    },
  },
  {
    name: 'reload',
    description: 'Reload STELLA.md, skills, commands and agents',
    async run(_a, ctx) {
      await ctx.rt.reloadInstructions();
      ctx.print(`Reloaded: ${ctx.rt.instructions.length} instruction files, ${ctx.rt.skills.list().length} skills, ${ctx.rt.subagents.list().length} agents.`);
    },
  },
  {
    name: 'export',
    usage: '[file]',
    description: 'Export the conversation to Markdown',
    async run(a, ctx) {
      const { renderTranscript } = await import('../agent/agent.js');
      const file = path.resolve(ctx.rt.cwd, a.trim() || `stella-session-${ctx.rt.session.id}.md`);
      await fs.writeFile(file, `# ${ctx.rt.session.title}\n\n${renderTranscript(ctx.rt.main.messages, 100_000)}\n`);
      ctx.print(`Exported to ${file}`);
    },
  },
  {
    name: 'exit',
    aliases: ['quit', 'q'],
    description: 'Exit STELLA',
    run(_a, ctx) {
      ctx.exit();
    },
  },
];

export function findCommand(name: string): SlashCommand | undefined {
  return COMMANDS.find((x) => x.name === name || x.aliases?.includes(name));
}

/** Returns true if the input was handled as a command. */
export async function runSlash(input: string, ctx: CommandContext): Promise<boolean> {
  const m = /^\/([\w:-]+|\?)\s*([\s\S]*)$/.exec(input.trim());
  if (!m) return false;
  const [, name, args] = m as unknown as [string, string, string];
  const cmd = findCommand(name);
  if (cmd) {
    try {
      await cmd.run(args, ctx);
    } catch (e) {
      ctx.print(`/${name} failed: ${(e as Error).message}`, 'error');
    }
    return true;
  }
  const custom = ctx.rt.skills.getCommand(name);
  if (custom) {
    let body = custom.body.replace(/\$ARGUMENTS/g, args);
    args.split(/\s+/).forEach((v, i) => (body = body.replace(new RegExp(`\\$${i + 1}\\b`, 'g'), v)));
    await ctx.submit(body);
    return true;
  }
  const skill = ctx.rt.skills.get(name);
  if (skill && skill.userInvocable) {
    await ctx.submit(`${await ctx.rt.skills.render(skill, args)}\n\nFollow the skill above.${args ? ` Task: ${args}` : ''}`);
    return true;
  }
  ctx.print(`Unknown command /${name}. Type /help.`, 'warn');
  return true;
}

export function completeCommand(prefix: string, rt: Runtime): Array<{ name: string; description: string }> {
  const p = prefix.toLowerCase();
  const all = [
    ...COMMANDS.map((x) => ({ name: x.name, description: x.description })),
    ...rt.skills.listCommands().map((x) => ({ name: x.name, description: x.description })),
    ...rt.skills.list().filter((s) => s.userInvocable).map((s) => ({ name: s.name, description: `skill: ${s.description}` })),
  ];
  return all.filter((x) => x.name.startsWith(p)).slice(0, 12);
}

function redactProviders(p: any) {
  if (!p) return p;
  const out: any = {};
  for (const [k, v] of Object.entries<any>(p)) out[k] = { ...v, apiKey: v.apiKey ? maskKey(v.apiKey) : undefined };
  return out;
}

function getPath(obj: any, key: string): unknown {
  return key.split('.').filter(Boolean).reduce((o, k) => (o == null ? undefined : o[k]), obj);
}

function setPath(obj: Record<string, unknown>, key: string, value: unknown) {
  const parts = key.split('.');
  let o: any = obj;
  for (const p of parts.slice(0, -1)) o = o[p] ??= {};
  o[parts[parts.length - 1]!] = value;
  return obj;
}

export function costOf(rt: Runtime) {
  return costUsd(rt.main.model, rt.session.usage);
}

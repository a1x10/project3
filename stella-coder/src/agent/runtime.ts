import { EventEmitter } from 'node:events';
import path from 'node:path';
import { findProjectRoot, projectPaths, stellaHome, type ProjectPaths } from '../config/paths.js';
import { loadSettings, updateSettings, type LoadedSettings, type PermissionMode, type Settings } from '../config/settings.js';
import { IgnoreMatcher } from '../context/ignore.js';
import { ProjectIndex } from '../context/index.js';
import { instructionsBlock, loadInstructions, type InstructionFile } from '../context/instructions.js';
import { detectProject, profileSummary, type ProjectProfile } from '../context/project.js';
import { gitStatus } from '../git/git.js';
import { HookEngine } from '../hooks/engine.js';
import { loadMcpJson, McpManager } from '../mcp/manager.js';
import { MemoryStore } from '../memory/store.js';
import { PermissionEngine, parseRule, type AskAnswer } from '../permissions/engine.js';
import { loadPlugins, pluginContributions, type LoadedPlugin } from '../plugins/loader.js';
import { ModelRegistry } from '../providers/registry.js';
import type { ModelInfo } from '../providers/types.js';
import { CheckpointStore } from '../recovery/checkpoints.js';
import { SessionStore, type SessionMeta } from '../sessions/store.js';
import { SkillRegistry } from '../skills/registry.js';
import { BUILTIN_AGENTS, type AgentDefinition } from '../subagents/builtin.js';
import { FileLockManager, ReadState } from '../subagents/locks.js';
import { SubagentManager } from '../subagents/manager.js';
import { devTools } from '../tools/dev.js';
import { fsTools } from '../tools/fs.js';
import { gitTools } from '../tools/git.js';
import { metaTools, type TodoItem } from '../tools/meta.js';
import { bashShell, ProcessManager } from '../tools/process.js';
import { searchTools } from '../tools/search.js';
import { shellTools } from '../tools/shell.js';
import type { Tool, ToolServices } from '../tools/types.js';
import { webTools } from '../tools/web.js';
import type { ContentBlock } from '../types.js';
import { readJson, writeJson } from '../utils/fsutil.js';
import { AuditLog } from '../utils/logger.js';
import { Agent, type AgentHost, type RunResult } from './agent.js';
import type { AgentEvent, PermissionRequest } from './events.js';
import { buildSystemPrompt, CORE_PROMPT } from './prompt.js';

export interface RuntimeOptions {
  cwd: string;
  model?: string;
  permissionMode?: PermissionMode;
  allowedTools?: string[];
  disallowedTools?: string[];
  settings?: Settings;
  resume?: string | 'last';
  trust?: boolean;
  interactive?: boolean;
  connectMcp?: boolean;
  maxTurns?: number;
  appendSystemPrompt?: string;
}

export interface UIHandlers {
  permission?: (req: PermissionRequest) => Promise<AskAnswer>;
  planApproval?: (plan: string) => Promise<{ decision: 'approve' | 'edit' | 'reject'; mode?: PermissionMode; feedback?: string }>;
  question?: (question: string, options: string[]) => Promise<string | null>;
}

export const BUILTIN_TOOLS: Tool[] = [...fsTools, ...searchTools, ...shellTools, ...gitTools, ...webTools, ...devTools, ...metaTools];

const trustFile = () => path.join(stellaHome(), 'trusted.json');
export async function isTrusted(root: string): Promise<boolean> {
  const list = await readJson<string[]>(trustFile(), []);
  return list.includes(path.resolve(root));
}
export async function setTrusted(root: string): Promise<void> {
  const list = await readJson<string[]>(trustFile(), []);
  if (!list.includes(path.resolve(root))) list.push(path.resolve(root));
  await writeJson(trustFile(), list);
}

/** Wires every subsystem together and owns the main agent + session lifecycle. */
export class Runtime {
  readonly events = new EventEmitter();
  readonly handlers: UIHandlers = {};
  readonly cwd: string;
  readonly root: string;
  readonly paths: ProjectPaths;
  loaded!: LoadedSettings;
  settings!: Settings;
  registry!: ModelRegistry;
  permissions!: PermissionEngine;
  hooks!: HookEngine;
  mcp!: McpManager;
  skills!: SkillRegistry;
  memory!: MemoryStore;
  sessions!: SessionStore;
  checkpoints!: CheckpointStore;
  subagents!: SubagentManager;
  index!: ProjectIndex;
  ignore!: IgnoreMatcher;
  plugins: LoadedPlugin[] = [];
  readonly locks = new FileLockManager();
  readonly readState = new ReadState();
  readonly processes = new ProcessManager();
  readonly audit: AuditLog;
  readonly shellCwd = new Map<string, string>();
  readonly todos = new Map<string, TodoItem[]>();
  trusted = false;
  roots: string[] = [];
  session!: SessionMeta;
  main!: Agent;
  instructions: InstructionFile[] = [];
  private profile: ProjectProfile | null = null;
  private profilePromise: Promise<ProjectProfile> | null = null;
  private gitSummary = '';
  private promptCache: string | null = null;
  private askChain: Promise<unknown> = Promise.resolve();
  readonly warnings: string[] = [];
  services!: ToolServices;

  private constructor(private readonly opts: RuntimeOptions) {
    this.cwd = path.resolve(opts.cwd);
    this.root = findProjectRoot(this.cwd);
    this.paths = projectPaths(this.root);
    this.audit = new AuditLog(process.env.STELLA_NO_AUDIT ? null : this.paths.auditLog);
  }

  static async create(opts: RuntimeOptions): Promise<Runtime> {
    const rt = new Runtime(opts);
    await rt.init();
    return rt;
  }

  private async init() {
    const o = this.opts;
    this.loaded = await loadSettings(this.root, o.settings ?? {});
    this.warnings.push(...this.loaded.errors.map((e) => `Settings error: ${e}`));
    const projectHasExec = !!(this.loaded.layers.project.hooks || this.loaded.layers.local.hooks || this.loaded.layers.project.mcpServers || this.loaded.layers.local.mcpServers || Object.keys(await loadMcpJson(this.root)).length);
    this.trusted = o.trust === true || (await isTrusted(this.root)) || !projectHasExec;
    if (o.trust === true) await setTrusted(this.root).catch(() => {});
    if (!this.trusted) this.warnings.push('Project hooks/MCP servers are disabled until you trust this folder (/trust or --trust).');

    this.plugins = await loadPlugins(this.root, this.loaded.merged, this.trusted);
    const contrib = pluginContributions(this.plugins);
    const baseHooks = this.trusted ? this.loaded.merged.hooks ?? {} : this.loaded.layers.user.hooks ?? {};
    const hooks = { ...baseHooks };
    for (const [ev, list] of Object.entries(contrib.hooks)) hooks[ev] = [...(hooks[ev] ?? []), ...list];
    this.settings = { ...this.loaded.merged, hooks };
    for (const [k, v] of Object.entries(this.settings.env ?? {})) if (process.env[k] === undefined) process.env[k] = v;

    this.roots = [this.root, ...(this.settings.permissions?.additionalDirectories ?? []).map((d) => path.resolve(this.root, d))];
    this.registry = new ModelRegistry(this.settings);
    const rules = this.settings.permissions ?? {};
    this.permissions = new PermissionEngine({
      mode: o.permissionMode ?? rules.defaultMode ?? 'default',
      rules: { allow: [...(rules.allow ?? []), ...(o.allowedTools ?? [])], deny: [...(rules.deny ?? []), ...(o.disallowedTools ?? [])], ask: rules.ask ?? [] },
      audit: this.audit,
    });
    if (this.permissions.mode === 'bypassPermissions') this.warnings.push('BYPASS MODE: every action is allowed without confirmation except catastrophic ones. Use only in disposable environments.');

    this.ignore = new IgnoreMatcher(this.root, this.settings.ignore ?? []);
    this.index = new ProjectIndex(this.root, this.ignore, this.paths.indexCache);
    this.memory = new MemoryStore(this.paths.memoryDir);
    this.sessions = new SessionStore(this.paths.sessionsDir);
    this.skills = new SkillRegistry(this.root, [...contrib.skillDirs.map((dir) => ({ dir, scope: 'plugin' as const, kind: 'skills' as const })), ...contrib.commandDirs.map((dir) => ({ dir, scope: 'plugin' as const, kind: 'commands' as const }))]);
    await this.skills.load();
    this.hooks = new HookEngine(this.settings, { cwd: this.cwd, root: this.root, sessionId: () => this.session?.id ?? '', audit: this.audit, trusted: true });

    this.mcp = new McpManager(this.cwd);
    const userMcp = this.loaded.layers.user.mcpServers ?? {};
    for (const [n, c] of Object.entries(userMcp)) this.mcp.register(n, c, 'user', true);
    for (const [n, c] of Object.entries(this.loaded.layers.project.mcpServers ?? {})) this.mcp.register(n, c, 'project', this.trusted);
    for (const [n, c] of Object.entries(this.loaded.layers.local.mcpServers ?? {})) this.mcp.register(n, c, 'local', this.trusted);
    for (const [n, c] of Object.entries(await loadMcpJson(this.root))) if (!this.mcp.get(n)) this.mcp.register(n, c, 'mcp.json', this.trusted);
    for (const [n, c] of Object.entries(contrib.mcpServers)) this.mcp.register(n, c, 'plugin', true);

    this.instructions = await loadInstructions(this.root, this.cwd);
    this.services = this.buildServices();
    this.subagents = new SubagentManager(
      {
        createAgent: (def, runId, model, tools, mode) => this.createSubAgent(def, runId, model, tools, mode),
        resolveModel: (ref) => (ref ? this.registry.resolve(ref) : this.main.model),
        allTools: () => this.allTools(),
        hooks: this.hooks,
        releaseLocks: (id) => this.locks.releaseAll(id),
        emit: (ev) => this.emit(ev),
      },
      this.root,
      this.settings.maxSubagents ?? 4,
      contrib.agentDirs,
    );
    this.services.subagents = this.subagents;
    await this.subagents.load();

    const model = this.registry.resolve(o.model);
    await this.openSession(o.resume, model);
    this.index.ensure().catch(() => {});
    if (o.connectMcp !== false) this.mcp.connectAll().catch(() => {});
    this.gitSummary = await this.computeGitSummary();
    const start = await this.hooks.run('SessionStart', { source: o.resume ? 'resume' : 'startup' });
    if (start.additionalContext.length) this.startContext = start.additionalContext.join('\n');
    this.warnings.push(...start.messages);
  }

  private startContext = '';

  private buildServices(): ToolServices {
    const self = this;
    return {
      get settings() {
        return self.settings;
      },
      locks: this.locks,
      readState: this.readState,
      get checkpoints() {
        return self.checkpoints;
      },
      index: this.index,
      ignore: this.ignore,
      processes: this.processes,
      memory: this.memory,
      skills: this.skills,
      permissions: this.permissions,
      shellCwd: this.shellCwd,
      subagents: undefined,
      getProfile: () => this.getProfile(),
      setTodos: (agentId: string, todos: TodoItem[]) => {
        this.todos.set(agentId, todos);
        this.emit({ type: 'todos', agentId, todos });
        if (agentId === 'main') this.sessions.append(this.session.id, { v: 1, type: 'event', name: 'todos', data: todos, ts: Date.now() }).catch(() => {});
      },
      setPermissionMode: (m: PermissionMode) => this.setMode(m),
      askPlanApproval: (plan: string) => (this.handlers.planApproval ? this.serialize(() => this.handlers.planApproval!(plan)) : Promise.resolve(null)),
      askQuestion: (q: string, options: string[]) => (this.handlers.question ? this.serialize(() => this.handlers.question!(q, options)) : Promise.resolve(null)),
      sessionId: () => this.session?.id,
    };
  }

  private serialize<T>(fn: () => Promise<T>): Promise<T> {
    const p = this.askChain.then(fn, fn);
    this.askChain = p.catch(() => undefined);
    return p;
  }

  emit(ev: AgentEvent) {
    this.events.emit('event', ev);
  }

  /** Built-in (platform-enabled) tools + connected MCP tools, minus tools denied by name. */
  allTools(): Tool[] {
    const denied = new Set(this.permissions.listRules().deny.map(parseRule).filter((r) => !r.pattern).map((r) => r.tool));
    const tools = [...BUILTIN_TOOLS.filter((t) => !t.isEnabled || t.isEnabled(this.services)), ...this.mcp.tools()];
    return tools.filter((t) => !denied.has(t.name));
  }

  private host(): AgentHost {
    const self = this;
    return {
      registry: this.registry,
      permissions: this.permissions,
      hooks: this.hooks,
      services: this.services,
      settings: this.settings,
      audit: this.audit,
      cwd: this.cwd,
      root: this.root,
      roots: this.roots,
      emit: (ev) => this.emit(ev),
      get askPermission() {
        return self.handlers.permission ? (req: PermissionRequest) => self.serialize(() => self.handlers.permission!(req)) : undefined;
      },
      persistRule: (rule) => updateSettings('local', this.root, (s) => ({ ...s, permissions: { ...(s.permissions ?? {}), allow: [...new Set([...(s.permissions?.allow ?? []), rule])] } })),
      checkpoints: { beginTurn: (id, p) => this.checkpoints.beginTurn(id, p) },
    };
  }

  private async openSession(resume: string | undefined, model: ModelInfo) {
    let messages: import('../types.js').ChatMessage[] = [];
    let meta: SessionMeta | null = null;
    if (resume) {
      meta = resume === 'last' ? ((await this.sessions.list())[0] ?? null) : await this.sessions.findByPrefix(resume);
      if (!meta) throw new Error(`Session not found: ${resume}`);
      const loaded = await this.sessions.loadMessages(meta.id);
      messages = loaded.messages;
      if (Array.isArray(loaded.todos)) this.todos.set('main', loaded.todos as TodoItem[]);
      if (meta.status === 'active' && meta.pendingTask) this.warnings.push(`Previous run was interrupted while working on: "${meta.pendingTask}". Say "continue" to resume it.`);
      meta.status = 'idle';
      try {
        if (!this.opts.model && meta.model) model = this.registry.resolve(meta.model);
      } catch {
        /* keep requested model */
      }
    } else meta = await this.sessions.create(this.cwd, `${model.provider}:${model.id}`);
    this.session = meta;
    this.sessions.live = meta;
    this.checkpoints = new CheckpointStore(path.join(this.paths.checkpointsDir, meta.id));
    this.main = this.createMainAgent(model, messages);
  }

  private createMainAgent(model: ModelInfo, messages: import('../types.js').ChatMessage[]): Agent {
    return new Agent(this.host(), {
      id: 'main',
      model,
      isMain: true,
      messages,
      maxTurns: this.opts.maxTurns,
      tools: () => this.allTools(),
      systemPrompt: () => this.systemPrompt(),
      onRecord: async (rec) => {
        const ts = Date.now();
        if (rec.type === 'message') {
          await this.sessions.append(this.session.id, { v: 1, type: 'message', message: rec.message, ts });
          this.session.messageCount++;
          if (this.session.title === 'New session' && rec.message.role === 'user') {
            const t = rec.message.content.find((b) => b.type === 'text') as { text: string } | undefined;
            if (t && !t.text.startsWith('<')) this.session.title = t.text.replace(/\s+/g, ' ').slice(0, 80);
          }
        } else if (rec.type === 'compact') {
          await this.sessions.append(this.session.id, { v: 1, type: 'compact', summary: rec.summary, replacedCount: rec.replacedCount, ts });
          this.promptCache = null;
        } else {
          await this.sessions.append(this.session.id, { v: 1, type: 'usage', model: rec.model, usage: rec.usage, costUsd: rec.costUsd, ts });
          this.session.costUsd += rec.costUsd;
          const u = this.session.usage;
          u.inputTokens += rec.usage.inputTokens;
          u.outputTokens += rec.usage.outputTokens;
          u.cacheReadTokens = (u.cacheReadTokens ?? 0) + (rec.usage.cacheReadTokens ?? 0);
          u.cacheWriteTokens = (u.cacheWriteTokens ?? 0) + (rec.usage.cacheWriteTokens ?? 0);
        }
        await this.sessions.saveMeta(this.session);
      },
    });
  }

  private createSubAgent(def: AgentDefinition, runId: string, model: ModelInfo, tools: Tool[], mode?: PermissionMode): Agent {
    return new Agent(this.host(), {
      id: runId,
      model,
      tools: () => tools,
      maxTurns: def.maxTurns ?? 60,
      permissionMode: mode,
      effort: model.supportsEffort ? (this.settings.effort ?? 'medium') : undefined,
      systemPrompt: async () =>
        buildSystemPrompt({
          identity: `${def.prompt}`,
          cwd: this.cwd,
          root: this.root,
          model: `${model.name} (${model.id})`,
          shell: bashShell(this.settings.shell)?.file ?? 'none',
          projectSummary: await this.projectSummaryQuick(),
          instructions: instructionsBlock(this.instructions),
          mode: mode === 'plan' || this.permissions.mode === 'plan' ? 'plan' : this.permissions.mode,
          skills: this.skills.promptBlock(),
        }),
      onRecord: async (rec) => {
        if (rec.type === 'usage') {
          this.session.costUsd += rec.costUsd;
          this.session.usage.inputTokens += rec.usage.inputTokens;
          this.session.usage.outputTokens += rec.usage.outputTokens;
        }
      },
    });
  }

  async getProfile(): Promise<ProjectProfile> {
    if (this.profile) return this.profile;
    this.profilePromise ??= detectProject(this.root, this.index).then((p) => (this.profile = p));
    return this.profilePromise;
  }

  private async projectSummaryQuick(): Promise<string> {
    const p = await Promise.race([this.getProfile(), new Promise<null>((r) => setTimeout(() => r(null), 4000).unref())]);
    return p ? profileSummary(p) : `Project: ${path.basename(this.root)} (index still building)`;
  }

  private async computeGitSummary(): Promise<string> {
    const s = await gitStatus(this.root).catch(() => null);
    if (!s) return '';
    const changed = s.staged.length + s.unstaged.length + s.untracked.length;
    return `Branch: ${s.branch ?? 'detached'}${s.upstream ? ` (upstream ${s.upstream}, ahead ${s.ahead}, behind ${s.behind})` : ''}; ${changed ? `${changed} changed/untracked files at session start` : 'clean working tree at session start'}${s.conflicted.length ? `; ${s.conflicted.length} CONFLICTED files` : ''}.`;
  }

  async systemPrompt(): Promise<string> {
    if (this.promptCache) return this.promptCache;
    const m = this.main.model;
    this.promptCache = buildSystemPrompt({
      identity: CORE_PROMPT,
      cwd: this.cwd,
      root: this.root,
      model: `${m.name} (${m.provider}:${m.id})`,
      shell: bashShell(this.settings.shell)?.file ?? (process.platform === 'win32' ? 'powershell' : 'sh'),
      gitSummary: this.gitSummary,
      projectSummary: await this.projectSummaryQuick(),
      instructions: instructionsBlock(this.instructions),
      memory: await this.memory.promptBlock(),
      skills: this.skills.promptBlock(),
      agents: this.subagents.promptBlock(),
      mode: this.permissions.mode,
      extra: [this.startContext, this.opts.appendSystemPrompt].filter(Boolean).join('\n\n') || undefined,
    });
    return this.promptCache;
  }

  invalidatePrompt() {
    this.promptCache = null;
  }

  setMode(mode: PermissionMode) {
    this.permissions.setMode(mode);
    this.promptCache = null;
    this.emit({ type: 'mode', agentId: 'main', mode });
    this.sessions.append(this.session.id, { v: 1, type: 'event', name: 'mode', data: mode, ts: Date.now() }).catch(() => {});
  }

  /** Send a prompt. If the agent is busy, the text is queued and delivered mid-task. */
  async submit(input: string | ContentBlock[]): Promise<RunResult | null> {
    if (this.main.isRunning) {
      this.main.enqueue(typeof input === 'string' ? input : input.map((b) => (b.type === 'text' ? b.text : '')).join('\n'));
      this.emit({ type: 'notification', agentId: 'main', level: 'info', text: 'Message queued — it will be delivered to the agent at the next step.' });
      return null;
    }
    const prompt = typeof input === 'string' ? input : '';
    this.session.status = 'active';
    this.session.pendingTask = prompt.slice(0, 200);
    await this.sessions.saveMeta(this.session);
    try {
      return await this.main.run(input);
    } finally {
      this.session.status = 'idle';
      this.session.pendingTask = undefined;
      await this.sessions.saveMeta(this.session).catch(() => {});
    }
  }

  interrupt() {
    this.main.interrupt();
    this.subagents.cancelAll();
  }

  switchModel(ref: string): ModelInfo {
    const m = this.registry.resolve(ref);
    this.main.setModel(m);
    this.session.model = `${m.provider}:${m.id}`;
    this.promptCache = null;
    this.sessions.append(this.session.id, { v: 1, type: 'event', name: 'model_change', data: this.session.model, ts: Date.now() }).catch(() => {});
    this.sessions.saveMeta(this.session).catch(() => {});
    return m;
  }

  async clear(): Promise<void> {
    this.session.status = 'idle';
    await this.sessions.saveMeta(this.session);
    await this.openSession(undefined, this.main.model);
    this.todos.clear();
    this.promptCache = null;
    this.gitSummary = await this.computeGitSummary();
  }

  async resume(id: string): Promise<void> {
    await this.openSession(id, this.main.model);
    this.promptCache = null;
  }

  async reloadInstructions() {
    this.instructions = await loadInstructions(this.root, this.cwd);
    await this.skills.load();
    await this.subagents.load();
    this.promptCache = null;
  }

  async trustProject() {
    await setTrusted(this.root);
  }

  async shutdown() {
    this.processes.stopAll();
    this.subagents?.cancelAll();
    await this.mcp?.closeAll().catch(() => {});
    if (this.session) {
      this.session.status = this.main?.isRunning ? 'interrupted' : 'idle';
      await this.sessions.saveMeta(this.session).catch(() => {});
    }
  }
}

export { BUILTIN_AGENTS };

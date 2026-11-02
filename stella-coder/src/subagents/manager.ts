import { promises as fs } from 'node:fs';
import path from 'node:path';
import { stellaHome } from '../config/paths.js';
import type { PermissionMode } from '../config/settings.js';
import type { ModelInfo } from '../providers/types.js';
import type { Tool } from '../tools/types.js';
import { childController, Semaphore } from '../utils/async.js';
import { parseFrontmatter, toList } from '../utils/frontmatter.js';
import { BUILTIN_AGENTS, type AgentDefinition } from './builtin.js';
import type { Agent } from '../agent/agent.js';

export interface SubagentRun {
  runId: string;
  name: string;
  description: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  startedAt: number;
  endedAt?: number;
  durationMs?: number;
  toolCalls: number;
  costUsd: number;
  result?: string;
  error?: string;
  parentAgentId: string;
  controller: AbortController;
}

export interface SubagentFactory {
  createAgent(def: AgentDefinition, runId: string, model: ModelInfo, tools: Tool[], mode?: PermissionMode): Agent;
  resolveModel(ref?: string): ModelInfo;
  allTools(): Tool[];
  hooks: { run(event: 'SubagentStart' | 'SubagentStop', payload: Record<string, unknown>, signal?: AbortSignal): Promise<{ blocked: boolean; reason?: string }> };
  releaseLocks(agentId: string): void;
  emit(ev: any): void;
}

/** Spawns isolated agents with their own context, tools, permission mode and limits. */
export class SubagentManager {
  private defs = new Map<string, AgentDefinition>();
  private runs: SubagentRun[] = [];
  private sem: Semaphore;
  private seq = 0;
  timeoutMs = 20 * 60_000;

  constructor(
    private readonly factory: SubagentFactory,
    private readonly root: string,
    readonly maxConcurrent = 4,
    private readonly extraDirs: string[] = [],
  ) {
    this.sem = new Semaphore(maxConcurrent);
  }

  async load(): Promise<void> {
    this.defs.clear();
    for (const d of BUILTIN_AGENTS) this.defs.set(d.name, d);
    const dirs: Array<[string, AgentDefinition['source']]> = [[path.join(stellaHome(), 'agents'), 'user'], ...this.extraDirs.map((d) => [d, 'plugin'] as [string, AgentDefinition['source']]), [path.join(this.root, '.stella', 'agents'), 'project']];
    for (const [dir, source] of dirs) {
      let files: string[] = [];
      try {
        files = (await fs.readdir(dir)).filter((f) => f.endsWith('.md'));
      } catch {
        continue;
      }
      for (const f of files) {
        const raw = await fs.readFile(path.join(dir, f), 'utf8').catch(() => '');
        const { data, body } = parseFrontmatter<Record<string, unknown>>(raw);
        const name = String(data.name ?? f.replace(/\.md$/, ''));
        const tools = toList(data.tools);
        this.defs.set(name, {
          name,
          description: String(data.description ?? ''),
          prompt: body.trim() || BUILTIN_AGENTS[0]!.prompt,
          tools: tools.length ? tools : undefined,
          model: data.model ? String(data.model) : undefined,
          permissionMode: (data.permissionMode as PermissionMode) ?? undefined,
          maxTurns: typeof data.maxTurns === 'number' ? data.maxTurns : undefined,
          source,
        });
      }
    }
  }

  list(): AgentDefinition[] {
    return [...this.defs.values()];
  }
  get(name: string) {
    return this.defs.get(name);
  }
  listRuns(): Array<Omit<SubagentRun, 'controller'>> {
    return this.runs.map(({ controller: _c, ...r }) => r);
  }

  promptBlock(): string {
    return this.list()
      .map((d) => `- ${d.name}: ${d.description}${d.permissionMode === 'plan' ? ' (read-only)' : ''}`)
      .join('\n');
  }

  cancel(runId: string): boolean {
    const r = this.runs.find((x) => x.runId === runId);
    if (!r || (r.status !== 'running' && r.status !== 'queued')) return false;
    r.controller.abort();
    r.status = 'cancelled';
    return true;
  }

  cancelAll() {
    for (const r of this.runs) if (r.status === 'running' || r.status === 'queued') this.cancel(r.runId);
  }

  async run(req: { type: string; description: string; prompt: string; model?: string; parentAgentId: string; signal?: AbortSignal }): Promise<SubagentRun> {
    const def = this.defs.get(req.type) ?? this.defs.get(req.type.toLowerCase());
    const controller = childController(req.signal);
    const runId = `${def?.name ?? req.type}-${++this.seq}`;
    const run: SubagentRun = { runId, name: def?.name ?? req.type, description: req.description, status: 'queued', startedAt: Date.now(), toolCalls: 0, costUsd: 0, parentAgentId: req.parentAgentId, controller };
    this.runs.push(run);
    if (!def) {
      run.status = 'failed';
      run.error = `Unknown subagent type "${req.type}". Available: ${[...this.defs.keys()].join(', ')}`;
      return run;
    }
    if (req.parentAgentId !== 'main') {
      run.status = 'failed';
      run.error = 'Subagents cannot spawn further subagents.';
      return run;
    }
    this.factory.emit({ type: 'subagent', agentId: req.parentAgentId, runId, name: def.name, description: req.description, status: 'queued' });
    const release = await this.sem.acquire();
    if (controller.signal.aborted) {
      release();
      run.status = 'cancelled';
      return run;
    }
    run.status = 'running';
    run.startedAt = Date.now();
    this.factory.emit({ type: 'subagent', agentId: req.parentAgentId, runId, name: def.name, description: req.description, status: 'running' });
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    let agent: Agent | null = null;
    try {
      const start = await this.factory.hooks.run('SubagentStart', { agent_type: def.name, description: req.description, run_id: runId }, controller.signal);
      if (start.blocked) throw new Error(`Blocked by SubagentStart hook: ${start.reason}`);
      const model = this.factory.resolveModel(req.model ?? (def.model && def.model !== 'inherit' ? def.model : undefined));
      const all = this.factory.allTools().filter((t) => t.name !== 'Task' && t.name !== 'EnterPlanMode' && t.name !== 'ExitPlanMode' && t.name !== 'AskUserQuestion');
      const tools = def.tools ? all.filter((t) => def.tools!.includes(t.name) || def.tools!.some((p) => p.endsWith('*') && t.name.startsWith(p.slice(0, -1)))) : all;
      agent = this.factory.createAgent(def, runId, model, tools, def.permissionMode);
      const res = await agent.run(req.prompt, controller.signal);
      run.toolCalls = res.toolCalls;
      run.costUsd = res.costUsd;
      run.result = res.text;
      run.status = controller.signal.aborted ? 'cancelled' : res.stopReason === 'refusal' ? 'failed' : 'completed';
      if (run.status === 'cancelled') run.error = 'cancelled (interrupt or timeout)';
    } catch (e) {
      run.status = controller.signal.aborted ? 'cancelled' : 'failed';
      run.error = (e as Error).message;
    } finally {
      clearTimeout(timer);
      release();
      run.endedAt = Date.now();
      run.durationMs = run.endedAt - run.startedAt;
      if (agent) run.toolCalls = agent.toolCalls;
      this.factory.releaseLocks(runId);
      await this.factory.hooks.run('SubagentStop', { agent_type: def.name, run_id: runId, status: run.status }).catch(() => undefined);
      this.factory.emit({ type: 'subagent', agentId: req.parentAgentId, runId, name: def.name, description: req.description, status: run.status, toolCalls: run.toolCalls });
    }
    return run;
  }
}

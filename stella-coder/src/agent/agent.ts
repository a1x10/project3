import { z } from 'zod';
import type { PermissionMode, Settings } from '../config/settings.js';
import type { HookEngine } from '../hooks/engine.js';
import { PermissionEngine, type AskAnswer } from '../permissions/engine.js';
import { streamWithRetry } from '../providers/retry.js';
import type { ModelRegistry } from '../providers/registry.js';
import { costUsd, ProviderError, type Effort, type ModelInfo } from '../providers/types.js';
import { repairTranscript, summaryMessage } from '../sessions/store.js';
import { toolSpec, ToolError, type Tool, type ToolContext, type ToolResult, type ToolServices } from '../tools/types.js';
import type { ChatMessage, ContentBlock, StopReason, ToolResultBlock, ToolUseBlock, Usage } from '../types.js';
import { childController, isAbortError, Semaphore } from '../utils/async.js';
import { newId } from '../utils/ids.js';
import type { AuditLog } from '../utils/logger.js';
import { estimateMessagesTokens, estimateTokens } from '../utils/tokens.js';
import { truncate } from '../utils/fsutil.js';
import type { AgentEvent, PermissionRequest } from './events.js';
import { COMPACT_PROMPT } from './prompt.js';

export interface AgentHost {
  registry: ModelRegistry;
  permissions: PermissionEngine;
  hooks: HookEngine;
  services: ToolServices;
  settings: Settings;
  audit?: AuditLog;
  cwd: string;
  root: string;
  roots: string[];
  emit(ev: AgentEvent): void;
  askPermission?(req: PermissionRequest): Promise<AskAnswer>;
  persistRule?(rule: string): Promise<void>;
  checkpoints: { beginTurn(turnId: string, prompt: string): Promise<void> };
}

export interface AgentOptions {
  id: string;
  model: ModelInfo;
  systemPrompt: () => Promise<string>;
  tools: () => Tool[];
  maxTurns?: number;
  permissionMode?: PermissionMode;
  isMain?: boolean;
  messages?: ChatMessage[];
  onRecord?: (rec: { type: 'message'; message: ChatMessage } | { type: 'compact'; summary: string; replacedCount: number } | { type: 'usage'; model: string; usage: Usage; costUsd: number }) => void | Promise<void>;
  effort?: Effort;
}

export interface RunResult {
  text: string;
  stopReason: StopReason;
  turns: number;
  toolCalls: number;
  usage: Usage;
  costUsd: number;
}

/**
 * The agent loop: request → stream → execute tool calls (with validation, hooks, permissions,
 * parallelism) → feed results back → repeat until the model ends its turn. Handles retries,
 * interruption, queued user messages, refusals, truncated outputs and context compaction.
 */
export class Agent {
  readonly id: string;
  model: ModelInfo;
  messages: ChatMessage[];
  effort?: Effort;
  readonly totals: Usage = { inputTokens: 0, outputTokens: 0, cacheReadTokens: 0, cacheWriteTokens: 0 };
  totalCost = 0;
  private lastContext = { tokens: 0, atMessage: 0 };
  private queue: string[] = [];
  private controller: AbortController | null = null;
  private running = false;
  private stopHookBlocks = 0;
  toolCalls = 0;

  constructor(
    private readonly host: AgentHost,
    private readonly opts: AgentOptions,
  ) {
    this.id = opts.id;
    this.model = opts.model;
    this.messages = repairTranscript(opts.messages ?? []);
    this.effort = opts.effort ?? host.settings.effort ?? (opts.model.supportsEffort ? 'high' : undefined);
  }

  get isRunning() {
    return this.running;
  }

  /** Queue a message typed while the agent is working; delivered with the next tool results. */
  enqueue(text: string) {
    this.queue.push(text);
  }

  interrupt() {
    this.controller?.abort();
  }

  contextTokens(): number {
    const added = this.messages.slice(this.lastContext.atMessage);
    return this.lastContext.tokens + estimateMessagesTokens(added);
  }

  private emit(ev: Omit<AgentEvent, 'agentId'> & { type: AgentEvent['type'] }) {
    this.host.emit({ ...(ev as any), agentId: this.id });
  }

  private async record(message: ChatMessage) {
    this.messages.push(message);
    await this.opts.onRecord?.({ type: 'message', message });
  }

  async run(input: string | ContentBlock[], parentSignal?: AbortSignal): Promise<RunResult> {
    if (this.running) throw new Error('Agent is already running');
    this.running = true;
    this.stopHookBlocks = 0;
    const ctl = childController(parentSignal);
    this.controller = ctl;
    const turnId = newId('t');
    const promptText = typeof input === 'string' ? input : input.map((b) => (b.type === 'text' ? b.text : '')).join('');
    const startUsage = { ...this.totals };
    const startCost = this.totalCost;
    let turns = 0;
    let stopReason: StopReason = 'end_turn';
    let finalText = '';
    try {
      await this.host.checkpoints.beginTurn(turnId, promptText);
      this.emit({ type: 'turn_start', turnId, prompt: promptText } as any);
      const blocks: ContentBlock[] = typeof input === 'string' ? [{ type: 'text', text: input }] : input;
      if (this.opts.isMain) {
        const hook = await this.host.hooks.run('UserPromptSubmit', { prompt: promptText }, ctl.signal);
        for (const m of hook.messages) this.emit({ type: 'notification', level: 'info', text: m } as any);
        if (hook.blocked || hook.stop) {
          this.emit({ type: 'notification', level: 'warn', text: `Prompt blocked by hook: ${hook.reason ?? ''}` } as any);
          stopReason = 'end_turn';
          return this.result('', 'end_turn', 0, startUsage, startCost);
        }
        for (const c of hook.additionalContext) blocks.push({ type: 'text', text: `<system-reminder>\n${c}\n</system-reminder>` });
        const suggestion = this.host.services.skills?.suggest?.(promptText);
        if (suggestion) blocks.push({ type: 'text', text: `<system-reminder>The skill "${suggestion.name}" looks relevant to this request (${suggestion.description}). Load it with the Skill tool if it applies.</system-reminder>` });
      }
      await this.record({ role: 'user', content: blocks, meta: { ts: Date.now() } });

      const maxTurns = this.opts.maxTurns ?? this.host.settings.maxTurns ?? 200;
      let contextRetry = false;
      while (turns < maxTurns) {
        if (ctl.signal.aborted) {
          stopReason = 'aborted';
          break;
        }
        turns++;
        await this.maybeAutoCompact(ctl.signal);
        const tools = this.availableTools();
        let assistant: ChatMessage | null = null;
        let turnStop: StopReason = 'end_turn';
        let partialText = '';
        try {
          const res = await this.callModel(tools, ctl.signal, (t) => (partialText += t));
          assistant = res.message;
          turnStop = res.stopReason;
          contextRetry = false;
        } catch (e) {
          if (isAbortError(e) || ctl.signal.aborted) {
            if (partialText.trim()) await this.record({ role: 'assistant', content: [{ type: 'text', text: partialText + '\n\n[interrupted by user]' }] });
            stopReason = 'aborted';
            break;
          }
          if (e instanceof ProviderError && e.kind === 'context_length' && !contextRetry && this.messages.length > 2) {
            contextRetry = true;
            this.emit({ type: 'notification', level: 'warn', text: 'Context window exceeded — compacting and retrying.' } as any);
            await this.compact({ auto: true, signal: ctl.signal });
            turns--;
            continue;
          }
          throw e;
        }
        await this.record(assistant);
        this.emit({ type: 'assistant_message', message: assistant } as any);
        finalText = assistant.content.filter((b) => b.type === 'text').map((b: any) => b.text).join('');
        stopReason = turnStop;

        const uses = assistant.content.filter((b): b is ToolUseBlock => b.type === 'tool_use');
        if (turnStop === 'refusal') {
          this.emit({ type: 'notification', level: 'warn', text: 'The model declined this request (refusal).' } as any);
          if (uses.length) await this.record({ role: 'user', content: uses.map((u) => ({ type: 'tool_result', toolUseId: u.id, content: 'Not executed: the response was a refusal.', isError: true })) });
          break;
        }
        if (!uses.length) {
          if (turnStop === 'max_tokens') {
            this.emit({ type: 'notification', level: 'warn', text: 'Response hit the output token limit; asking the model to continue.' } as any);
            await this.record({ role: 'user', content: [{ type: 'text', text: 'Your previous response was cut off by the output limit. Continue exactly where you stopped (break large outputs into smaller steps).' }] });
            continue;
          }
          if (this.queue.length) {
            await this.record({ role: 'user', content: this.drainQueue() });
            continue;
          }
          if (this.opts.isMain) {
            const stop = await this.host.hooks.run('Stop', { last_message: finalText.slice(0, 4000), stop_hook_active: this.stopHookBlocks > 0 }, ctl.signal);
            if (stop.blocked && this.stopHookBlocks < 3) {
              this.stopHookBlocks++;
              await this.record({ role: 'user', content: [{ type: 'text', text: `<system-reminder>A Stop hook asked you to continue: ${stop.reason}</system-reminder>` }] });
              continue;
            }
          }
          break;
        }

        let results: ToolResultBlock[];
        if (turnStop === 'max_tokens') {
          results = uses.map((u) => ({ type: 'tool_result', toolUseId: u.id, content: 'Not executed: your output hit the token limit, so this tool input may be truncated. Retry with smaller pieces (e.g. write a large file in several Edit calls).', isError: true }));
        } else {
          results = await this.executeTools(uses, tools, turnId, ctl.signal);
        }
        const userBlocks: ContentBlock[] = [...results, ...this.drainQueue()];
        await this.record({ role: 'user', content: userBlocks });
        if (ctl.signal.aborted) {
          stopReason = 'aborted';
          break;
        }
        stopReason = 'tool_use';
      }
      if (turns >= maxTurns && stopReason === 'tool_use') {
        this.emit({ type: 'notification', level: 'warn', text: `Stopped after ${maxTurns} model turns (maxTurns).` } as any);
      }
      return this.result(finalText, stopReason, turns, startUsage, startCost);
    } finally {
      this.running = false;
      this.controller = null;
      this.emit({ type: 'turn_end', turnId, stopReason, text: finalText, turns } as any);
    }
  }

  private result(text: string, stopReason: StopReason, turns: number, startUsage: Usage, startCost: number): RunResult {
    return {
      text,
      stopReason,
      turns,
      toolCalls: this.toolCalls,
      usage: {
        inputTokens: this.totals.inputTokens - startUsage.inputTokens,
        outputTokens: this.totals.outputTokens - startUsage.outputTokens,
        cacheReadTokens: (this.totals.cacheReadTokens ?? 0) - (startUsage.cacheReadTokens ?? 0),
        cacheWriteTokens: (this.totals.cacheWriteTokens ?? 0) - (startUsage.cacheWriteTokens ?? 0),
      },
      costUsd: this.totalCost - startCost,
    };
  }

  private drainQueue(): ContentBlock[] {
    const q = this.queue.splice(0);
    return q.map((t) => ({ type: 'text', text: `<user-message-while-working>\n${t}\n</user-message-while-working>\nThe user sent this while you were working. Take it into account now.` }));
  }

  private availableTools(): Tool[] {
    const all = this.opts.tools();
    if (!this.model.toolCalling) return [];
    return all;
  }

  private async callModel(tools: Tool[], signal: AbortSignal, onText: (t: string) => void): Promise<{ message: ChatMessage; stopReason: StopReason }> {
    const provider = await this.host.registry.provider(this.model.provider);
    const system = await this.opts.systemPrompt();
    const maxTokens = Math.min(this.host.settings.maxOutputTokens ?? 64_000, this.model.maxOutput);
    this.emit({ type: 'status', text: 'Thinking…' } as any);
    const stream = streamWithRetry(
      provider,
      { model: this.model, system, messages: this.messages, tools: tools.map(toolSpec), maxTokens, effort: this.effort, signal },
      {
        onRetry: ({ attempt, delayMs, error }) => this.emit({ type: 'status', text: `${error.kind.replace('_', ' ')} — retrying in ${Math.ceil(delayMs / 1000)}s (attempt ${attempt})` } as any),
      },
    );
    for await (const ev of stream) {
      if ((ev as any).restart) {
        this.emit({ type: 'text_reset' } as any);
        continue;
      }
      switch (ev.type) {
        case 'text':
          if (ev.text) {
            onText(ev.text);
            this.emit({ type: 'text_delta', text: ev.text } as any);
          }
          break;
        case 'thinking':
          this.emit({ type: 'status', text: 'Reasoning…' } as any);
          break;
        case 'tool_start':
          this.emit({ type: 'tool_start', id: ev.id, name: ev.name } as any);
          this.emit({ type: 'status', text: `Preparing ${ev.name}…` } as any);
          break;
        case 'done': {
          const cost = costUsd(this.model, ev.usage);
          this.totals.inputTokens += ev.usage.inputTokens;
          this.totals.outputTokens += ev.usage.outputTokens;
          this.totals.cacheReadTokens = (this.totals.cacheReadTokens ?? 0) + (ev.usage.cacheReadTokens ?? 0);
          this.totals.cacheWriteTokens = (this.totals.cacheWriteTokens ?? 0) + (ev.usage.cacheWriteTokens ?? 0);
          this.totalCost += cost;
          const promptTokens = ev.usage.inputTokens + (ev.usage.cacheReadTokens ?? 0) + (ev.usage.cacheWriteTokens ?? 0);
          this.lastContext = { tokens: (promptTokens || estimateTokens(system) + estimateMessagesTokens(this.messages)) + ev.usage.outputTokens, atMessage: this.messages.length + 1 };
          await this.opts.onRecord?.({ type: 'usage', model: this.model.id, usage: ev.usage, costUsd: cost });
          this.emit({ type: 'usage', model: this.model.id, usage: ev.usage, costUsd: cost, contextTokens: this.lastContext.tokens, contextWindow: this.model.contextWindow, servedModel: ev.servedModel } as any);
          return { message: ev.message, stopReason: ev.stopReason };
        }
      }
    }
    throw new ProviderError('Stream ended without a final message', 'server');
  }

  /** Run tool calls: consecutive concurrency-safe calls in parallel, others sequentially. */
  private async executeTools(uses: ToolUseBlock[], tools: Tool[], turnId: string, signal: AbortSignal): Promise<ToolResultBlock[]> {
    const byName = new Map(tools.map((t) => [t.name, t]));
    const results = new Map<string, ToolResultBlock>();
    const batches: ToolUseBlock[][] = [];
    for (const u of uses) {
      const safe = byName.get(u.name)?.concurrencySafe;
      const last = batches[batches.length - 1];
      if (safe && last && last.every((x) => byName.get(x.name)?.concurrencySafe)) last.push(u);
      else batches.push([u]);
    }
    const sem = new Semaphore(8);
    for (const batch of batches) {
      if (signal.aborted) break;
      await Promise.all(batch.map((u) => sem.run(async () => results.set(u.id, await this.executeOne(u, byName.get(u.name), turnId, signal)))));
    }
    return uses.map((u) => results.get(u.id) ?? { type: 'tool_result', toolUseId: u.id, content: 'Interrupted by the user before this tool ran.', isError: true });
  }

  private async executeOne(use: ToolUseBlock, tool: Tool | undefined, turnId: string, signal: AbortSignal): Promise<ToolResultBlock> {
    const started = Date.now();
    this.toolCalls++;
    const fail = (content: string): ToolResultBlock => {
      this.emit({ type: 'tool_result', id: use.id, name: use.name, content, isError: true, durationMs: Date.now() - started } as any);
      return { type: 'tool_result', toolUseId: use.id, content, isError: true };
    };
    if (!tool) return fail(`Unknown tool "${use.name}". Available tools: ${this.availableTools().map((t) => t.name).join(', ')}`);
    if ((use.input as any)?.__invalid_json__ !== undefined) return fail('Tool input was not valid JSON. Re-issue the call with well-formed arguments.');

    let input: any = use.input;
    const parse = (raw: unknown) => {
      if (tool.inputJsonSchema) return raw && typeof raw === 'object' ? { success: true as const, data: raw } : { success: false as const, error: 'input must be an object' };
      const r = tool.schema.safeParse(raw);
      return r.success ? { success: true as const, data: r.data } : { success: false as const, error: formatZod(r.error) };
    };
    const parsed = parse(input);
    if (!parsed.success) return fail(`Invalid input for ${tool.name}: ${parsed.error}`);
    input = parsed.data;

    const ctx: ToolContext = {
      cwd: this.host.services.shellCwd?.get(this.id) ?? this.host.cwd,
      root: this.host.root,
      roots: this.host.roots,
      signal,
      agentId: this.id,
      turnId,
      services: this.host.services,
      progress: (text) => this.emit({ type: 'tool_progress', id: use.id, text } as any),
    };

    let desc;
    try {
      desc = await tool.describe(input, ctx);
    } catch (e) {
      return fail((e as Error).message);
    }
    this.emit({ type: 'tool_call', id: use.id, name: tool.name, input, summary: desc.summary } as any);

    // PreToolUse hooks may block, approve or rewrite the call.
    const pre = await this.host.hooks.run('PreToolUse', { tool_name: tool.name, tool_input: input, agent_id: this.id }, signal);
    for (const m of pre.messages) this.emit({ type: 'notification', level: 'info', text: m } as any);
    if (pre.blocked) return fail(`Blocked by PreToolUse hook: ${pre.reason}`);
    if (pre.updatedInput) {
      const re = parse(pre.updatedInput);
      if (!re.success) return fail(`Hook produced invalid input: ${re.error}`);
      input = re.data;
      desc = await tool.describe(input, ctx);
    }

    const decision = this.host.permissions.check(tool.name, desc, this.opts.permissionMode);
    let allowed = decision.behavior === 'allow';
    if (decision.behavior === 'deny') {
      this.emit({ type: 'permission', tool: tool.name, summary: desc.summary, decision: 'deny', reason: decision.reason } as any);
      return fail(`Permission denied: ${decision.reason}`);
    }
    if (decision.behavior === 'ask' && pre.decision === 'allow') allowed = true;
    if (decision.behavior === 'ask' && !allowed) {
      const ph = await this.host.hooks.run('PermissionRequest', { tool_name: tool.name, tool_input: input, reason: decision.reason }, signal);
      if (ph.decision === 'allow') allowed = true;
      else if (ph.blocked || ph.decision === 'deny') return fail(`Permission denied by hook: ${ph.reason ?? ''}`);
      else {
        if (!this.host.askPermission) {
          this.emit({ type: 'permission', tool: tool.name, summary: desc.summary, decision: 'deny', reason: 'no interactive user' } as any);
          return fail(`Permission required (${decision.reason}) but no user is available to approve "${desc.summary}". Allow it with --allowedTools or a permission rule, or choose another approach.`);
        }
        this.emit({ type: 'status', text: 'Waiting for permission…' } as any);
        const suggestedRule = PermissionEngine.suggestRule(tool.name, desc);
        const ans = await this.host.askPermission({ agentId: this.id, tool: tool.name, input, descriptor: desc, reason: decision.reason, suggestedRule });
        this.host.permissions.record(tool.name, desc, ans.decision, 'user');
        this.emit({ type: 'permission', tool: tool.name, summary: desc.summary, decision: ans.decision, reason: 'user' } as any);
        if (ans.decision === 'deny') return fail(`The user denied this action.${ans.feedback ? ` Feedback: ${ans.feedback}` : ' Do not retry it; ask how to proceed or take a different approach.'}`);
        if (ans.decision === 'allow_session') this.host.permissions.addSessionAllow(suggestedRule);
        if (ans.decision === 'allow_always') {
          this.host.permissions.addSessionAllow(suggestedRule);
          await this.host.persistRule?.(suggestedRule);
        }
        allowed = true;
      }
    }
    if (!allowed) return fail('Permission denied.');

    this.emit({ type: 'status', text: `Running ${tool.name}…` } as any);
    let res: ToolResult;
    try {
      res = await tool.run(input, ctx);
    } catch (e) {
      if (isAbortError(e) || signal.aborted) res = { content: 'Interrupted by the user.', isError: true };
      else res = { content: e instanceof ToolError ? e.message : `Tool error: ${(e as Error).message}`, isError: true };
    }
    const post = await this.host.hooks.run(res.isError ? 'PostToolFailure' : 'PostToolUse', { tool_name: tool.name, tool_input: input, tool_response: { content: truncate(res.content, 10_000), is_error: !!res.isError } }, signal);
    let content = res.content;
    if (post.blocked && post.reason) content += `\n\n<hook-feedback>${post.reason}</hook-feedback>`;
    for (const c of post.additionalContext) content += `\n\n<system-reminder>${c}</system-reminder>`;
    for (const m of post.messages) this.emit({ type: 'notification', level: 'info', text: m } as any);
    this.host.audit?.write('tool', { agent: this.id, tool: tool.name, summary: desc.summary, isError: !!res.isError, ms: Date.now() - started });
    this.emit({ type: 'tool_result', id: use.id, name: tool.name, content, isError: !!res.isError, display: res.display, durationMs: Date.now() - started, filesChanged: res.filesChanged, filesRead: res.filesRead } as any);
    return { type: 'tool_result', toolUseId: use.id, content: content || '(no output)', isError: res.isError };
  }

  private compactThreshold(): number {
    const t = this.host.settings.autoCompactThreshold ?? 0.8;
    const usable = Math.max(8_000, this.model.contextWindow - Math.min(this.model.maxOutput, 32_000));
    return Math.floor(usable * t);
  }

  private async maybeAutoCompact(signal: AbortSignal) {
    if (this.messages.length < 4) return;
    if (this.contextTokens() < this.compactThreshold()) return;
    this.emit({ type: 'notification', level: 'info', text: `Context ${Math.round((this.contextTokens() / this.model.contextWindow) * 100)}% full — auto-compacting.` } as any);
    await this.compact({ auto: true, signal });
  }

  /** Summarize history with the model and replace it with the summary. */
  async compact(opts: { auto?: boolean; instructions?: string; signal?: AbortSignal } = {}): Promise<{ before: number; after: number; summary: string }> {
    const before = this.contextTokens();
    const pre = await this.host.hooks.run('PreCompact', { trigger: opts.auto ? 'auto' : 'manual', custom_instructions: opts.instructions ?? '' }, opts.signal);
    if (pre.blocked) throw new Error(`Compaction blocked by hook: ${pre.reason}`);
    const transcript = renderTranscript(this.messages);
    const provider = await this.host.registry.provider(this.model.provider);
    let summary = '';
    this.emit({ type: 'status', text: 'Compacting conversation…' } as any);
    const prompt = `${COMPACT_PROMPT}${opts.instructions ? `\n\nAdditional instructions: ${opts.instructions}` : ''}${pre.additionalContext.length ? `\n\n${pre.additionalContext.join('\n')}` : ''}\n\n<transcript>\n${transcript}\n</transcript>`;
    for await (const ev of streamWithRetry(provider, {
      model: this.model,
      system: 'You are a precise technical summarizer for a coding agent. Produce faithful, specific summaries.',
      messages: [{ role: 'user', content: [{ type: 'text', text: prompt }] }],
      tools: [],
      maxTokens: Math.min(16_000, this.model.maxOutput),
      effort: 'low',
      signal: opts.signal,
    })) {
      if (ev.type === 'done') {
        summary = ev.message.content.filter((b) => b.type === 'text').map((b: any) => b.text).join('');
        const cost = costUsd(this.model, ev.usage);
        this.totalCost += cost;
        this.totals.inputTokens += ev.usage.inputTokens;
        this.totals.outputTokens += ev.usage.outputTokens;
        await this.opts.onRecord?.({ type: 'usage', model: this.model.id, usage: ev.usage, costUsd: cost });
      }
    }
    if (!summary.trim()) throw new Error('Compaction failed: empty summary');
    const files = new Set<string>();
    for (const m of this.messages) for (const b of m.content) if (b.type === 'tool_use' && typeof (b.input as any)?.file_path === 'string') files.add(String((b.input as any).file_path));
    const full = summary.trim() + (files.size ? `\n\nFiles touched in the compacted history: ${[...files].slice(-30).join(', ')} (re-read them before editing).` : '');
    const replaced = this.messages.length;
    this.messages = [summaryMessage(full)];
    this.lastContext = { tokens: 0, atMessage: 0 };
    await this.opts.onRecord?.({ type: 'compact', summary: full, replacedCount: replaced });
    const after = this.contextTokens();
    await this.host.hooks.run('PostCompact', { trigger: opts.auto ? 'auto' : 'manual', summary_tokens: after }, opts.signal);
    this.emit({ type: 'compact', beforeTokens: before, afterTokens: after, auto: !!opts.auto } as any);
    return { before, after, summary: full };
  }

  setModel(m: ModelInfo) {
    this.model = m;
    if (!m.supportsEffort) this.effort = undefined;
    else if (!this.effort) this.effort = this.host.settings.effort ?? 'high';
  }

  clear() {
    this.messages = [];
    this.lastContext = { tokens: 0, atMessage: 0 };
  }
}

function formatZod(err: z.ZodError): string {
  return err.issues.map((i) => `${i.path.join('.') || '(root)'}: ${i.message}`).join('; ');
}

export function renderTranscript(messages: ChatMessage[], maxToolChars = 2500): string {
  const out: string[] = [];
  for (const m of messages) {
    for (const b of m.content) {
      if (b.type === 'text') out.push(`${m.role === 'user' ? 'USER' : 'ASSISTANT'}: ${b.text}`);
      else if (b.type === 'tool_use') out.push(`ASSISTANT called ${b.name}(${truncate(JSON.stringify(b.input), 1500)})`);
      else if (b.type === 'tool_result') out.push(`TOOL RESULT${b.isError ? ' (error)' : ''}: ${truncate(b.content, maxToolChars)}`);
    }
  }
  const text = out.join('\n\n');
  return text.length > 600_000 ? truncate(text, 600_000) : text;
}

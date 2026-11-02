import { z } from 'zod';
import { defineTool, ToolError } from './types.js';

const meta = (summary: string) => ({ kind: 'meta' as const, risk: 'low' as const, readOnly: true, summary });

export interface TodoItem {
  content: string;
  status: 'pending' | 'in_progress' | 'completed';
  activeForm?: string;
}

export const TodoWriteTool = defineTool({
  name: 'TodoWrite',
  description:
    'Create and maintain a structured task list for the current work. Use it for multi-step tasks (3+ steps): write the full list, keep exactly one item in_progress, mark items completed immediately when done. Send the whole list each time.',
  kind: 'meta',
  concurrencySafe: false,
  schema: z.object({
    todos: z.array(z.object({ content: z.string().min(1), status: z.enum(['pending', 'in_progress', 'completed']), activeForm: z.string().optional() })),
  }),
  describe: (i) => meta(`Update todos (${i.todos.length})`),
  async run(i, ctx) {
    ctx.services.setTodos(ctx.agentId, i.todos);
    const done = i.todos.filter((t) => t.status === 'completed').length;
    const lines = i.todos.map((t) => `${t.status === 'completed' ? '[x]' : t.status === 'in_progress' ? '[~]' : '[ ]'} ${t.content}`);
    return { content: `Todo list updated (${done}/${i.todos.length} done). Keep it current as you work.`, display: { kind: 'todo', body: lines.join('\n') } };
  },
});

export const TaskTool = defineTool({
  name: 'Task',
  description:
    'Launch a subagent with its own context window to handle a self-contained task autonomously (exploration of a large codebase, a focused fix, writing tests, a review). Multiple Task calls in one message run in parallel. The subagent cannot see this conversation: give it a complete, specific prompt and say what to return. Its final report comes back as the tool result. Available agent types are listed in the system prompt.',
  kind: 'meta',
  concurrencySafe: true,
  schema: z.object({
    description: z.string().describe('Short (3-6 words) task label'),
    prompt: z.string().describe('Full instructions for the subagent'),
    subagent_type: z.string().optional().describe('Agent type, e.g. explorer, planner, coder, debugger, tester, reviewer, security-auditor, docs (default: general)'),
    model: z.string().optional().describe('Optional model override (alias or provider:model)'),
  }),
  describe: (i) => meta(`Subagent ${i.subagent_type ?? 'general'}: ${i.description}`),
  async run(i, ctx) {
    if (!ctx.services.subagents) throw new ToolError('Subagents are not available in this context.');
    const r = await ctx.services.subagents.run({ type: i.subagent_type ?? 'general', description: i.description, prompt: i.prompt, model: i.model, parentAgentId: ctx.agentId, signal: ctx.signal });
    return {
      content: r.status === 'completed' ? r.result || '(subagent returned no text)' : `Subagent ${r.status}: ${r.error ?? r.result ?? ''}`,
      isError: r.status !== 'completed',
      display: { kind: 'agent', title: `${r.name}: ${i.description}`, body: `${r.status} · ${r.toolCalls} tool calls · ${Math.round((r.durationMs ?? 0) / 1000)}s` },
    };
  },
});

export const SkillTool = defineTool({
  name: 'Skill',
  description: 'Load a skill (packaged instructions and resources for a type of task). Invoke it as soon as a listed skill matches the task, before starting the work.',
  kind: 'meta',
  concurrencySafe: true,
  schema: z.object({ name: z.string(), args: z.string().optional() }),
  describe: (i) => meta(`Load skill ${i.name}`),
  async run(i, ctx) {
    const s = ctx.services.skills.get(i.name);
    if (!s) throw new ToolError(`Unknown skill "${i.name}". Available: ${ctx.services.skills.list().map((x: any) => x.name).join(', ') || 'none'}`);
    if (!s.modelInvocable) throw new ToolError(`Skill ${i.name} can only be invoked by the user.`);
    return { content: await ctx.services.skills.render(s, i.args), display: { kind: 'text', title: `Loaded skill ${s.name}` } };
  },
});

export const MemoryTool = defineTool({
  name: 'Memory',
  description:
    'Persistent memory across sessions. Save durable facts only: user preferences (type=user), project knowledge (project), architecture decisions (technical), unfinished work (task). Never store secrets. Actions: add, update, delete, list. Check existing memories (in the system prompt) to avoid duplicates; update outdated ones.',
  kind: 'meta',
  schema: z.object({
    action: z.enum(['add', 'update', 'delete', 'list']),
    type: z.enum(['user', 'project', 'technical', 'task', 'session']).optional(),
    content: z.string().optional(),
    id: z.string().optional(),
  }),
  describe: (i) => ({ kind: 'meta', risk: 'low', readOnly: i.action === 'list', summary: `Memory ${i.action}${i.content ? `: ${i.content.slice(0, 60)}` : ''}` }),
  async run(i, ctx) {
    const mem = ctx.services.memory;
    switch (i.action) {
      case 'list': {
        const items = await mem.list(i.type);
        return { content: items.length ? items.map((m: any) => `[${m.id}] (${m.type}) ${m.content}`).join('\n') : 'No memories.' };
      }
      case 'add': {
        if (!i.content) throw new ToolError('content required');
        const r = await mem.add(i.type ?? 'project', i.content, undefined, ctx.services.sessionId?.());
        if (r.error) throw new ToolError(r.error);
        if (r.duplicateOf) return { content: `Already remembered as [${r.duplicateOf.id}]: ${r.duplicateOf.content}. Use update to change it.` };
        return { content: `Saved memory [${r.item!.id}] (${r.item!.type}).` };
      }
      case 'update': {
        if (!i.id || !i.content) throw new ToolError('id and content required');
        const it = await mem.update(i.id, i.content);
        if (!it) throw new ToolError(`No memory ${i.id}`);
        return { content: `Updated [${it.id}].` };
      }
      case 'delete': {
        if (!i.id) throw new ToolError('id required');
        return { content: (await mem.remove(i.id)) ? `Deleted [${i.id}].` : `No memory ${i.id}`, isError: false };
      }
    }
  },
});

export const ExitPlanModeTool = defineTool({
  name: 'ExitPlanMode',
  description:
    'Use in plan mode when your plan is ready. Present the plan (Markdown: goal, steps, files to change, risks, how it will be tested). The user can approve it (planning ends and you implement), request changes, or reject it.',
  kind: 'meta',
  schema: z.object({ plan: z.string().min(10) }),
  describe: () => meta('Present plan'),
  async run(i, ctx) {
    if (ctx.services.permissions.mode !== 'plan') return { content: 'Not in plan mode; proceed with the task.' };
    const ans = await ctx.services.askPlanApproval?.(i.plan);
    if (!ans) return { content: 'The plan could not be shown to the user (non-interactive). Stay in plan mode and end your turn with the plan as your final message.' };
    if (ans.decision === 'approve') {
      ctx.services.setPermissionMode(ans.mode ?? 'default');
      return { content: `User approved the plan. Permission mode is now "${ans.mode ?? 'default'}". Implement it now, keeping the todo list updated.` };
    }
    if (ans.decision === 'edit') return { content: `User wants changes to the plan:\n${ans.feedback ?? ''}\nRevise the plan and present it again with ExitPlanMode.` };
    return { content: `User rejected the plan${ans.feedback ? `: ${ans.feedback}` : ''}. Stop and ask what they want instead.` };
  },
});

export const EnterPlanModeTool = defineTool({
  name: 'EnterPlanMode',
  description: 'Switch to plan mode before a large or risky change: explore read-only, then present a plan with ExitPlanMode for approval.',
  kind: 'meta',
  schema: z.object({ reason: z.string().optional() }),
  describe: () => meta('Enter plan mode'),
  async run(_i, ctx) {
    ctx.services.setPermissionMode('plan');
    return { content: 'Plan mode active. Only read-only tools are allowed. Investigate, then call ExitPlanMode with the plan.' };
  },
});

export const AskUserQuestionTool = defineTool({
  name: 'AskUserQuestion',
  description: 'Ask the user a clarifying question with 2-4 options when a decision genuinely depends on their preference. Do not ask about things you can determine from the code.',
  kind: 'meta',
  schema: z.object({ question: z.string(), options: z.array(z.string()).min(2).max(4) }),
  describe: (i) => meta(`Ask: ${i.question}`),
  async run(i, ctx) {
    const a = await ctx.services.askQuestion?.(i.question, i.options);
    if (a === undefined || a === null) return { content: 'The user is not available to answer (non-interactive mode). Choose the most reasonable option, state the assumption, and continue.' };
    return { content: `User answered: ${a}` };
  },
});

export const metaTools = [TodoWriteTool, TaskTool, SkillTool, MemoryTool, EnterPlanModeTool, ExitPlanModeTool, AskUserQuestionTool];

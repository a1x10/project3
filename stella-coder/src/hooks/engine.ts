import type { Settings } from '../config/settings.js';
import { bashShell, cmdShell, execProgram, powershellShell } from '../tools/process.js';
import type { AuditLog } from '../utils/logger.js';
import { redact } from '../utils/redact.js';

export const HOOK_EVENTS = [
  'SessionStart',
  'UserPromptSubmit',
  'PreToolUse',
  'PostToolUse',
  'PostToolFailure',
  'PermissionRequest',
  'Notification',
  'Stop',
  'SubagentStart',
  'SubagentStop',
  'PreCompact',
  'PostCompact',
] as const;
export type HookEvent = (typeof HOOK_EVENTS)[number];

const TOOL_EVENTS = new Set<HookEvent>(['PreToolUse', 'PostToolUse', 'PostToolFailure', 'PermissionRequest']);

export interface HookOutcome {
  /** A hook asked to block the action (exit code 2 or decision=block/deny). */
  blocked: boolean;
  /** PermissionRequest/PreToolUse: explicit allow/deny decision. */
  decision?: 'allow' | 'deny' | 'ask';
  reason?: string;
  /** Extra context to feed to the model. */
  additionalContext: string[];
  /** Messages to show the user. */
  messages: string[];
  /** Hook requested that the agent stops (continue: false). */
  stop?: boolean;
  /** PreToolUse may rewrite the tool input. */
  updatedInput?: Record<string, unknown>;
  ran: number;
}

export interface HookRunRecord {
  ts: number;
  event: HookEvent;
  command: string;
  exitCode: number | null;
  durationMs: number;
  timedOut: boolean;
}

/**
 * Runs user-configured commands on agent lifecycle events. The JSON payload is passed on stdin.
 * Exit code 0 = success (stdout may be JSON with decision/reason/additionalContext), exit code 2 =
 * block (stderr is shown to the model), other codes = non-blocking error.
 */
export class HookEngine {
  readonly history: HookRunRecord[] = [];
  constructor(
    private settings: Settings,
    private readonly ctx: { cwd: string; root: string; sessionId: () => string; audit?: AuditLog; trusted: boolean; projectHookSources?: Set<string> },
  ) {}

  updateSettings(s: Settings) {
    this.settings = s;
  }

  configured(): Array<{ event: string; matcher?: string; command: string }> {
    const out: Array<{ event: string; matcher?: string; command: string }> = [];
    for (const [event, list] of Object.entries(this.settings.hooks ?? {})) for (const m of list) for (const h of m.hooks) out.push({ event, matcher: m.matcher, command: h.command });
    return out;
  }

  async run(event: HookEvent, payload: Record<string, unknown>, signal?: AbortSignal): Promise<HookOutcome> {
    const outcome: HookOutcome = { blocked: false, additionalContext: [], messages: [], ran: 0 };
    const matchers = this.settings.hooks?.[event] ?? [];
    if (!matchers.length) return outcome;
    if (!this.ctx.trusted) return outcome;
    const target = TOOL_EVENTS.has(event) ? String(payload.tool_name ?? '') : String(payload.source ?? payload.matcher_value ?? '');
    const input = JSON.stringify({ hook_event_name: event, session_id: this.ctx.sessionId(), cwd: this.ctx.cwd, project_dir: this.ctx.root, ...payload });
    const shell = bashShell(this.settings.shell) ?? powershellShell() ?? cmdShell();
    if (!shell) return outcome;
    for (const m of matchers) {
      if (m.matcher && m.matcher !== '*' && !safeRegex(m.matcher).test(target)) continue;
      for (const h of m.hooks) {
        const timeoutMs = Math.min((h.timeout ?? 60) * 1000, 600_000);
        const started = Date.now();
        let r;
        try {
          r = await execProgram(shell.file, shell.args(h.command), {
            cwd: this.ctx.root,
            timeoutMs,
            signal,
            input,
            env: { ...(this.settings.env ?? {}), STELLA_PROJECT_DIR: this.ctx.root, STELLA_HOOK_EVENT: event },
          });
        } catch (e) {
          outcome.messages.push(`Hook failed to start (${event}): ${(e as Error).message}`);
          continue;
        }
        outcome.ran++;
        const rec: HookRunRecord = { ts: started, event, command: h.command, exitCode: r.exitCode, durationMs: Date.now() - started, timedOut: r.timedOut };
        this.history.push(rec);
        if (this.history.length > 200) this.history.shift();
        this.ctx.audit?.write('hook', { ...rec, stderr: redact(r.stderr.slice(0, 2000)) });
        if (r.timedOut) {
          outcome.messages.push(`Hook timed out after ${timeoutMs / 1000}s (${event}): ${h.command}`);
          continue;
        }
        if (r.exitCode === 2) {
          outcome.blocked = true;
          outcome.reason = (r.stderr || r.stdout).trim() || `Blocked by ${event} hook`;
          continue;
        }
        if (r.exitCode !== 0) {
          outcome.messages.push(`Hook error (${event}, exit ${r.exitCode}): ${(r.stderr || r.stdout).trim().slice(0, 500)}`);
          continue;
        }
        const out = r.stdout.trim();
        if (!out) continue;
        let json: any = null;
        if (out.startsWith('{')) {
          try {
            json = JSON.parse(out);
          } catch {
            json = null;
          }
        }
        if (!json) {
          if (event === 'UserPromptSubmit' || event === 'SessionStart' || event === 'PostToolUse') outcome.additionalContext.push(out);
          else outcome.messages.push(out);
          continue;
        }
        const d = json.decision ?? json.permissionDecision ?? json.hookSpecificOutput?.permissionDecision;
        if (d === 'block' || d === 'deny') {
          outcome.blocked = true;
          outcome.decision = 'deny';
          outcome.reason = json.reason ?? json.permissionDecisionReason ?? `Blocked by ${event} hook`;
        } else if (d === 'approve' || d === 'allow') outcome.decision = 'allow';
        else if (d === 'ask') outcome.decision = 'ask';
        const ctxText = json.additionalContext ?? json.hookSpecificOutput?.additionalContext;
        if (ctxText) outcome.additionalContext.push(String(ctxText));
        if (json.systemMessage) outcome.messages.push(String(json.systemMessage));
        if (json.continue === false) {
          outcome.stop = true;
          outcome.reason = json.stopReason ?? outcome.reason;
        }
        if (json.updatedInput && typeof json.updatedInput === 'object') outcome.updatedInput = json.updatedInput;
      }
    }
    return outcome;
  }
}

function safeRegex(src: string): RegExp {
  try {
    return new RegExp(`^(?:${src})$`);
  } catch {
    return new RegExp(`^${src.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`);
  }
}

import picomatch from 'picomatch';
import type { PermissionMode } from '../config/settings.js';
import type { ResolvedPath } from '../security/paths.js';
import { expandHome } from '../security/paths.js';
import type { AuditLog } from '../utils/logger.js';
import { analyzeShell, baseCommand, type Risk, type ShellAnalysis } from './shell.js';

export type ToolKind = 'read' | 'write' | 'execute' | 'network' | 'meta' | 'agent';

/** What a tool tells the permission engine about one concrete invocation. */
export interface PermissionDescriptor {
  kind: ToolKind;
  risk: Risk;
  summary: string; // human readable: "Edit src/app.ts", "Run: npm test"
  paths?: ResolvedPath[];
  command?: string;
  domain?: string;
  /** True when the action never modifies state (reads, searches). */
  readOnly: boolean;
}

export type Decision = { behavior: 'allow' | 'deny' | 'ask'; reason: string; rule?: string };

export type AskAnswer = { decision: 'allow_once' | 'allow_session' | 'allow_always' | 'deny'; feedback?: string };

export interface PermissionRules {
  allow: string[];
  deny: string[];
  ask: string[];
}

interface ParsedRule {
  raw: string;
  tool: string;
  pattern?: string;
}

export function parseRule(raw: string): ParsedRule {
  const m = /^([A-Za-z0-9_\-*]+)(?:\((.*)\))?$/s.exec(raw.trim());
  if (!m) return { raw, tool: raw.trim() };
  return { raw, tool: m[1]!, pattern: m[2]?.trim() || undefined };
}

const FILE_TOOLS_WRITE = new Set(['Write', 'Edit', 'MultiEdit', 'Delete', 'Move', 'Copy', 'NotebookEdit']);
const FILE_TOOLS_READ = new Set(['Read', 'Glob', 'Grep', 'DirectoryTree', 'FileInfo', 'SymbolSearch', 'ReferenceSearch', 'SemanticSearch', 'DependencySearch']);
const SHELL_TOOLS = new Set(['Bash', 'PowerShell', 'Cmd', 'StartProcess', 'RunScript']);

function toolMatches(ruleTool: string, toolName: string): boolean {
  if (ruleTool === toolName || ruleTool === '*') return true;
  // "Edit" rules cover every file-mutating tool, "Read" covers every read tool (Claude Code semantics).
  if (ruleTool === 'Edit' && FILE_TOOLS_WRITE.has(toolName)) return true;
  if (ruleTool === 'Read' && FILE_TOOLS_READ.has(toolName)) return true;
  if (ruleTool === 'Bash' && SHELL_TOOLS.has(toolName)) return true;
  if (ruleTool.endsWith('*')) return toolName.startsWith(ruleTool.slice(0, -1));
  // mcp__server matches every tool of that server
  if (ruleTool.startsWith('mcp__') && toolName.startsWith(ruleTool + '__')) return true;
  return false;
}

/** Matches one shell segment against a Bash rule pattern: "npm test:*" (prefix) or glob "git *". */
export function commandMatches(pattern: string, segment: string): boolean {
  const cmd = baseCommand(segment).replace(/\s+/g, ' ').trim();
  if (pattern.endsWith(':*')) {
    const prefix = pattern.slice(0, -2).trim();
    return cmd === prefix || cmd.startsWith(prefix + ' ');
  }
  if (pattern.includes('*')) {
    const re = new RegExp('^' + pattern.split('*').map(escapeRe).join('.*') + '$');
    return re.test(cmd);
  }
  return cmd === pattern.trim();
}

function escapeRe(s: string) {
  return s.replace(/[.+?^${}()|[\]\\]/g, '\\$&');
}

function pathMatches(pattern: string, p: ResolvedPath): boolean {
  const pat = expandHome(pattern).replace(/\\/g, '/');
  const absPosix = p.real.replace(/\\/g, '/');
  if (pat.startsWith('//')) return picomatch(pat.slice(1), { dot: true })(absPosix);
  if (pat.startsWith('/') || /^[A-Za-z]:\//.test(pat)) return picomatch(pat, { dot: true, nocase: process.platform === 'win32' })(absPosix);
  if (p.relToRoot === null) return false;
  const rel = pat.startsWith('./') ? pat.slice(2) : pat;
  return picomatch(rel, { dot: true })(p.relToRoot) || picomatch(rel + '/**', { dot: true })(p.relToRoot);
}

export function ruleMatches(rule: ParsedRule, toolName: string, d: PermissionDescriptor, shell?: ShellAnalysis): boolean {
  if (!toolMatches(rule.tool, toolName)) return false;
  if (!rule.pattern) return true;
  const pat = rule.pattern;
  if (d.command !== undefined && SHELL_TOOLS.has(toolName)) {
    const a = shell ?? analyzeShell(d.command);
    // A pattern must cover EVERY segment, and never authorizes substitution or nested interpreters.
    if (a.hasSubstitution || a.nestedInterpreter) return false;
    return a.segments.length > 0 && a.segments.every((s) => commandMatches(pat, s));
  }
  if (pat.startsWith('domain:')) return !!d.domain && (d.domain === pat.slice(7) || d.domain.endsWith('.' + pat.slice(7)));
  if (d.paths?.length) return d.paths.every((p) => pathMatches(pat, p));
  return false;
}

/** For deny rules: a pattern matching ANY segment denies the whole command. */
function denyMatches(rule: ParsedRule, toolName: string, d: PermissionDescriptor, shell?: ShellAnalysis): boolean {
  if (!toolMatches(rule.tool, toolName)) return false;
  if (!rule.pattern) return true;
  if (d.command !== undefined && SHELL_TOOLS.has(toolName)) {
    const a = shell ?? analyzeShell(d.command);
    return a.segments.some((s) => commandMatches(rule.pattern!, s));
  }
  if (rule.pattern.startsWith('domain:')) return ruleMatches(rule, toolName, d);
  if (d.paths?.length) return d.paths.some((p) => pathMatches(rule.pattern!, p));
  return false;
}

const RESTRICTIVENESS: PermissionMode[] = ['plan', 'default', 'acceptEdits', 'auto', 'bypassPermissions'];

/** Pick the more restrictive of two modes (subagents can never be more permissive than the session). */
export function mostRestrictive(a: PermissionMode, b?: PermissionMode): PermissionMode {
  if (!b) return a;
  return RESTRICTIVENESS.indexOf(a) <= RESTRICTIVENESS.indexOf(b) ? a : b;
}

export interface PermissionEngineOptions {
  mode: PermissionMode;
  rules: PermissionRules;
  audit?: AuditLog;
}

/**
 * Central policy decision point. Order:
 *  deny rules → critical-risk guard → plan-mode guard → ask rules → allow rules →
 *  bypass → mode defaults (read-only auto-allow, acceptEdits, auto policy) → ask.
 */
export class PermissionEngine {
  mode: PermissionMode;
  private rules: { allow: ParsedRule[]; deny: ParsedRule[]; ask: ParsedRule[] };
  private sessionAllow: ParsedRule[] = [];
  private audit?: AuditLog;
  readonly log: Array<{ ts: number; tool: string; summary: string; decision: string; reason: string }> = [];

  constructor(opts: PermissionEngineOptions) {
    this.mode = opts.mode;
    this.audit = opts.audit;
    this.rules = {
      allow: opts.rules.allow.map(parseRule),
      deny: opts.rules.deny.map(parseRule),
      ask: opts.rules.ask.map(parseRule),
    };
  }

  setMode(mode: PermissionMode) {
    this.mode = mode;
  }

  addRule(kind: 'allow' | 'deny' | 'ask', raw: string) {
    this.rules[kind].push(parseRule(raw));
  }
  addSessionAllow(raw: string) {
    this.sessionAllow.push(parseRule(raw));
  }
  listRules() {
    return {
      allow: this.rules.allow.map((r) => r.raw),
      deny: this.rules.deny.map((r) => r.raw),
      ask: this.rules.ask.map((r) => r.raw),
      session: this.sessionAllow.map((r) => r.raw),
    };
  }

  check(toolName: string, d: PermissionDescriptor, modeOverride?: PermissionMode): Decision {
    const decision = this.decide(toolName, d, mostRestrictive(this.mode, modeOverride));
    this.record(toolName, d, decision.behavior, decision.reason);
    return decision;
  }

  record(toolName: string, d: PermissionDescriptor, decision: string, reason: string) {
    this.log.push({ ts: Date.now(), tool: toolName, summary: d.summary, decision, reason });
    if (this.log.length > 500) this.log.shift();
    this.audit?.write('permission', { tool: toolName, summary: d.summary, risk: d.risk, decision, reason, mode: this.mode });
  }

  private decide(toolName: string, d: PermissionDescriptor, mode: PermissionMode): Decision {
    const shell = d.command !== undefined ? analyzeShell(d.command) : undefined;

    for (const r of this.rules.deny) if (denyMatches(r, toolName, d, shell)) return { behavior: 'deny', reason: `denied by rule ${r.raw}`, rule: r.raw };

    if (d.paths?.some((p) => p.isSystem) && !d.readOnly) return { behavior: 'deny', reason: 'writes to system directories are blocked' };

    const explicitAllow = [...this.rules.allow, ...this.sessionAllow].find((r) => ruleMatches(r, toolName, d, shell));

    if (d.risk === 'critical' && !explicitAllow) return { behavior: 'deny', reason: `blocked catastrophic operation (${shell?.reasons.join(', ') || 'critical risk'})` };

    if (mode === 'plan' && !d.readOnly && d.kind !== 'meta') return { behavior: 'deny', reason: 'plan mode is active: only read-only actions are allowed. Present the plan with ExitPlanMode.' };

    for (const r of this.rules.ask) if (ruleMatches(r, toolName, d, shell)) return { behavior: 'ask', reason: `rule ${r.raw} requires confirmation`, rule: r.raw };

    if (explicitAllow) return { behavior: 'allow', reason: `allowed by rule ${explicitAllow.raw}`, rule: explicitAllow.raw };

    if (mode === 'bypassPermissions') return { behavior: 'allow', reason: 'bypass mode' };

    const outside = d.paths?.some((p) => !p.inWorkspace) ?? false;
    const confidential = d.paths?.some((p) => p.isConfidential) ?? false;

    if (d.kind === 'meta') return { behavior: 'allow', reason: 'internal tool' };
    if (confidential) return { behavior: 'ask', reason: 'file is marked confidential' };

    if (d.readOnly) {
      if (outside) return { behavior: 'ask', reason: 'reads outside the workspace' };
      if (d.kind === 'network') return mode === 'auto' ? { behavior: 'allow', reason: 'auto mode: network read' } : { behavior: 'ask', reason: 'network access' };
      return { behavior: 'allow', reason: 'read-only' };
    }

    if (outside) return { behavior: 'ask', reason: 'modifies files outside the workspace' };

    if (mode === 'acceptEdits' && d.kind === 'write' && d.risk !== 'high') return { behavior: 'allow', reason: 'acceptEdits mode' };

    if (mode === 'auto') {
      if (d.risk === 'low' || d.risk === 'medium') return { behavior: 'allow', reason: `auto mode: ${d.risk} risk` };
      return { behavior: 'ask', reason: `auto mode: ${d.risk} risk needs confirmation (${shell?.reasons.join(', ') ?? d.summary})` };
    }

    return { behavior: 'ask', reason: shell?.reasons.length ? shell.reasons.join(', ') : `${d.kind} action` };
  }

  /** Suggest a reusable rule for "always allow" answers. */
  static suggestRule(toolName: string, d: PermissionDescriptor): string {
    if (d.command !== undefined) {
      const a = analyzeShell(d.command);
      const first = baseCommand(a.segments[0] ?? d.command).split(/\s+/).slice(0, 2).join(' ');
      return a.segments.length === 1 && !a.hasSubstitution ? `${toolName}(${first}:*)` : `${toolName}(${d.command})`;
    }
    if (d.domain) return `${toolName}(domain:${d.domain})`;
    if (d.paths?.length === 1 && d.paths[0]!.relToRoot !== null) {
      const rel = d.paths[0]!.relToRoot!;
      const dir = rel.includes('/') ? rel.slice(0, rel.lastIndexOf('/')) + '/**' : rel;
      return `${toolName}(${dir})`;
    }
    return toolName;
  }
}

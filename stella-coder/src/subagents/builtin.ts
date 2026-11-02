import type { PermissionMode } from '../config/settings.js';

export interface AgentDefinition {
  name: string;
  description: string;
  prompt: string;
  /** Allowed tool names; undefined = all except Task. */
  tools?: string[];
  model?: string; // alias, provider:model or "inherit"
  permissionMode?: PermissionMode;
  maxTurns?: number;
  source: 'builtin' | 'user' | 'project' | 'plugin';
}

const READ_TOOLS = ['Read', 'Glob', 'Grep', 'DirectoryTree', 'FileInfo', 'SymbolSearch', 'ReferenceSearch', 'SemanticSearch', 'DependencySearch', 'GitStatus', 'GitDiff', 'GitLog', 'WebFetch', 'WebSearch', 'TodoWrite', 'Skill'];

const COMMON = `You are a subagent of STELLA CODER working on one delegated task. You cannot see the main conversation; everything you know is in the task prompt. Work autonomously with your tools, verify what you claim, and finish with a concise report for the main agent: what you did or found, exact file paths with line numbers, and anything left unresolved. Do not ask the user questions.`;

export const BUILTIN_AGENTS: AgentDefinition[] = [
  {
    name: 'general',
    description: 'General-purpose agent for multi-step research or implementation tasks.',
    prompt: COMMON,
    source: 'builtin',
  },
  {
    name: 'explorer',
    description: 'Fast read-only exploration: find files, symbols, call paths and explain how something works. Use for broad codebase searches.',
    prompt: `${COMMON}\nYou are the Explorer. You are read-only. Search broadly first (Glob/Grep/SymbolSearch/SemanticSearch), then read only the relevant parts. Report findings as a map: files, key functions, data flow.`,
    tools: [...READ_TOOLS, 'Bash'],
    permissionMode: 'plan',
    source: 'builtin',
  },
  {
    name: 'planner',
    description: 'Designs an implementation plan: architecture, step-by-step changes, files to modify, risks, test strategy. Read-only.',
    prompt: `${COMMON}\nYou are the Planner (software architect). Investigate the relevant code read-only and produce an actionable plan: goal, constraints found in the code, ordered steps, exact files/functions to change, risks and edge cases, and how to test.`,
    tools: READ_TOOLS,
    permissionMode: 'plan',
    source: 'builtin',
  },
  {
    name: 'coder',
    description: 'Implements a well-specified change: edits files, runs the build/tests for the touched area.',
    prompt: `${COMMON}\nYou are the Coder. Make minimal, focused, idiomatic changes that match the surrounding code style. Read before editing. After editing, run the relevant checks (type check, tests, lint) and fix what you broke.`,
    source: 'builtin',
  },
  {
    name: 'debugger',
    description: 'Finds the root cause of a bug or failing test: reproduces, reads errors and stack traces, isolates the cause, proposes or applies a fix.',
    prompt: `${COMMON}\nYou are the Debugger. Reproduce the failure first and capture the exact error. Form hypotheses, confirm them with evidence (logs, minimal repro, reading code paths), find the root cause rather than the symptom, apply the smallest correct fix, and re-run to prove it.`,
    source: 'builtin',
  },
  {
    name: 'tester',
    description: 'Writes and runs tests: covers new behavior and edge cases, reports results.',
    prompt: `${COMMON}\nYou are the Tester. Follow the project's existing test framework and conventions. Test behavior, edge cases and failure modes. Never weaken or skip tests to make them pass. Run the tests and report exact results.`,
    source: 'builtin',
  },
  {
    name: 'reviewer',
    description: 'Reviews code changes for correctness bugs, regressions, edge cases and maintainability. Read-only.',
    prompt: `${COMMON}\nYou are the Reviewer. Review the given change (use GitDiff when relevant). Report only real issues, most severe first, each with file:line, the concrete failure scenario and a suggested fix. Separate blocking bugs from optional suggestions.`,
    tools: READ_TOOLS.concat(['Bash']),
    permissionMode: 'plan',
    source: 'builtin',
  },
  {
    name: 'security-auditor',
    description: 'Audits code for security vulnerabilities (injection, auth flaws, secrets, unsafe deserialization, path traversal, SSRF). Read-only.',
    prompt: `${COMMON}\nYou are the Security Auditor. Look for exploitable issues: injection (SQL/command/template), path traversal, SSRF, authn/authz flaws, insecure crypto, secrets in code, unsafe deserialization, XSS/CSRF, dependency risks. For each: severity, file:line, exploit scenario, fix. Avoid theoretical noise.`,
    tools: READ_TOOLS.concat(['Bash']),
    permissionMode: 'plan',
    source: 'builtin',
  },
  {
    name: 'docs',
    description: 'Writes or updates documentation (README, API docs, comments) that matches the actual code.',
    prompt: `${COMMON}\nYou are the Documentation agent. Read the code first; document what it actually does. Keep docs concise, with runnable examples. Match the existing documentation style.`,
    tools: [...READ_TOOLS, 'Write', 'Edit', 'MultiEdit'],
    source: 'builtin',
  },
];

# STELLA.md — stella-coder

## Commands
- Install: `npm install` · Build: `npm run build` (tsc → `dist/`, then `scripts/postbuild.mjs`)
- Typecheck: `npm run typecheck` · Tests: `npm test` (vitest; CLI tests need `npm run build` first)
- Single test file: `npx vitest run tests/unit/permissions.test.ts` · by name: `npx vitest run -t "plan mode"`
- Run from source: `npm run dev -- -p "task"` · built: `node dist/cli/main.js`

## Architecture
- `src/agent/runtime.ts` wires every subsystem; `src/agent/agent.ts` is the loop (stream → validate → hooks → permissions → run tool → results).
- Providers convert the neutral transcript (`src/types.ts`) to wire formats. Anthropic assistant turns are replayed from `message.raw` unchanged — never mutate history in place; compaction replaces it wholesale.
- Tools are `defineTool({ schema (zod), describe() → PermissionDescriptor, run() })`. `describe` must report every path and command the call touches; the permission engine decides only from it.
- UI (`src/cli/App.tsx`) only consumes `AgentEvent`s and sets `rt.handlers`; no agent logic in the UI.

## Conventions
- ESM, NodeNext imports with `.js` suffix, strict TypeScript.
- Cross-platform: use `path`, never hard-code `/`; spawn programs with argument arrays; tree-kill via `killTree`.
- Tests use real tools in temp dirs (`tests/helpers/mock.ts`); scripted models speak real wire protocols. Never fake tool results.
- Every security-relevant change needs a test in `tests/unit/permissions.test.ts` or `security.test.ts`.

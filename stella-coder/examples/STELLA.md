# STELLA.md

## Commands
- Install: `pnpm install`
- Dev server: `pnpm dev` (http://localhost:5173)
- Tests: `pnpm test` · single test: `pnpm test -- -t "name"`
- Lint/format: `pnpm lint` · `pnpm format`

## Architecture
- `src/api/` — tRPC routers; each router validates input with zod and calls `src/services/`.
- `src/services/` — business logic; no direct DB access outside `src/db/`.
- `src/db/` — Drizzle schema and migrations (`pnpm db:generate`).

## Conventions
- TypeScript strict, no `any` in new code. Named exports only.
- Every bug fix comes with a regression test.
- Never commit `.env*`; secrets come from `process.env`.
@docs/style-guide.md

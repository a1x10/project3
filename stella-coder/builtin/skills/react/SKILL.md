---
name: react
description: Building and refactoring React components, hooks, state management and React project structure (Vite, Next.js, CRA).
when_to_use: the task touches .jsx/.tsx components, hooks, React state, or React tooling
---
# React development

1. Detect the stack first: React version, framework (Next.js app/pages router, Vite, Remix), TypeScript, styling (CSS modules, Tailwind, styled-components), state (Context, Redux Toolkit, Zustand, React Query), test setup (Vitest/Jest + Testing Library).
2. Follow existing conventions: file naming, component folder layout, default vs named exports, prop typing style.
3. Components: function components + hooks; keep them small; derive state instead of duplicating it; lift state only as far as needed; memoize (`useMemo`/`useCallback`/`React.memo`) only for measured problems or referential stability needs.
4. Effects: every `useEffect` needs correct dependencies and cleanup; never fetch in render; prefer the project's data layer (React Query/SWR/server components) over ad-hoc effects.
5. Keys: stable ids, never array indexes for dynamic lists.
6. Accessibility: semantic elements, labels for inputs, keyboard handlers for clickable non-buttons, alt text.
7. Next.js: respect server vs client components (`'use client'`), don't import server-only code into client components, use the framework's routing/data APIs.
8. Verify: type check (`tsc --noEmit`), lint, run component tests; for UI changes, run the dev server with StartProcess and check the console for errors.

---
name: frontend
description: HTML/CSS/JS frontend work — layout, responsive design, accessibility, bundlers, performance, Vue/Svelte/Angular basics.
when_to_use: changes to markup, styles, client-side scripts or frontend build config
---
# Frontend development

1. Identify the framework and build tool (Vite, webpack, Next, Nuxt, SvelteKit, Angular CLI) and the styling system before writing code.
2. Semantic HTML first; CSS: reuse existing tokens/variables/utility classes; mobile-first responsive layout with flex/grid; avoid magic numbers and `!important`.
3. Accessibility: labels, focus states, color contrast, `aria-*` only when semantics are insufficient, keyboard navigation.
4. Performance: lazy-load heavy modules/images, avoid layout thrash, debounce expensive handlers, keep bundle additions justified.
5. State and events: no global mutable state unless the app already uses a store; clean up listeners/timers.
6. Verify: build (`npm run build`), lint, run the dev server (StartProcess) and check for console errors; test at narrow and wide widths when layout changed.

// Make the CLI entry executable and ensure it has a shebang (cross-platform no-op on Windows).
import { readFileSync, writeFileSync, chmodSync, existsSync } from 'node:fs';
const entry = new URL('../dist/cli/main.js', import.meta.url);
if (existsSync(entry)) {
  let src = readFileSync(entry, 'utf8');
  if (!src.startsWith('#!')) src = '#!/usr/bin/env node\n' + src;
  writeFileSync(entry, src);
  try { chmodSync(entry, 0o755); } catch { /* windows */ }
}

// Bundle the shared FreeLLMAPI router manager (repo: ../tools) so dist/ is self-contained.
import { copyFileSync, mkdirSync } from 'node:fs';
const routerSrc = new URL('../../tools/freellmapi-router.mjs', import.meta.url);
if (existsSync(routerSrc)) {
  mkdirSync(new URL('../dist/router/', import.meta.url), { recursive: true });
  copyFileSync(routerSrc, new URL('../dist/router/freellmapi.mjs', import.meta.url));
}

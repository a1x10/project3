// Make the CLI entry executable and ensure it has a shebang (cross-platform no-op on Windows).
import { readFileSync, writeFileSync, chmodSync, existsSync } from 'node:fs';
const entry = new URL('../dist/cli/main.js', import.meta.url);
if (existsSync(entry)) {
  let src = readFileSync(entry, 'utf8');
  if (!src.startsWith('#!')) src = '#!/usr/bin/env node\n' + src;
  writeFileSync(entry, src);
  try { chmodSync(entry, 0o755); } catch { /* windows */ }
}

#!/usr/bin/env node
// Сборка установщика Windows: electron-builder (папка) + нативный makensis.
// Работает на Windows (нужен NSIS: https://nsis.sourceforge.io) и Linux (apt install nsis) — wine не нужен.
import { execSync } from 'node:child_process';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const { version } = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8'));
const run = (cmd) => execSync(cmd, { cwd: ROOT, stdio: 'inherit' });
run('npx electron-builder --win dir --x64 -c.win.signAndEditExecutable=false');
const out = path.join(ROOT, 'dist', `Stella-Assistant-Setup-${version}.exe`);
run(`makensis -V2 "-DSRC=${path.join(ROOT, 'dist', 'win-unpacked')}" "-DOUT=${out}" -DVERSION=${version} "-DICON=${path.join(ROOT, 'assets', 'icons', 'icon.ico')}" "${path.join(ROOT, 'build', 'installer.nsi')}"`);
console.log('Готово:', out);

'use strict';
// Реальные системные вызовы для исполнителя инструментов.
const { spawn, execFile } = require('child_process');
const { encodePs } = require('./computer/input');

function exec(cmd, args, { timeout = 20000, cwd } = {}) {
  return new Promise((resolve) => {
    execFile(cmd, args, { timeout, cwd, windowsHide: true, maxBuffer: 10 * 1024 * 1024, encoding: 'utf8' }, (err, stdout, stderr) => {
      if (err) resolve({ code: err.code ?? 1, stdout: stdout || '', stderr: stderr || err.message, timedOut: !!err.killed });
      else resolve({ code: 0, stdout, stderr });
    });
  });
}

function runShell(command, { cwd, timeout = 60000 } = {}) {
  if (process.platform === 'win32') {
    const script = '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $OutputEncoding = [System.Text.Encoding]::UTF8\n' + command;
    return exec('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', encodePs(script)], { cwd, timeout });
  }
  const sh = process.platform === 'darwin' ? '/bin/zsh' : '/bin/bash';
  return exec(sh, ['-lc', command], { cwd, timeout });
}

function spawnDetached(cmd, args = []) {
  return new Promise((resolve, reject) => {
    try {
      const p = spawn(cmd, args, { detached: true, stdio: 'ignore', shell: process.platform !== 'win32' });
      p.on('error', (e) => reject(new Error(`Не удалось запустить «${cmd}»: ${e.message}`)));
      setTimeout(() => { p.unref(); resolve(); }, 400);
    } catch (e) { reject(e); }
  });
}

module.exports = { exec, runShell, spawnDetached };

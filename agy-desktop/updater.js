// Stella.exe auto-update: checks release/version.json on GitHub, downloads the new exe in the background,
// verifies its SHA-256, then replaces itself after a restart (one click).
const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');
const { spawn } = require('child_process');

let H = { log: () => {}, send: () => {}, version: '0.0.0' };
let ready = null;            // { version, file }
const DEFAULT_URL = 'https://raw.githubusercontent.com/a1x10/project3/claude/happy-ritchie-vx32ws/agy-desktop/release/version.json';

function updateUrl() {
  try { return JSON.parse(fs.readFileSync(path.join(__dirname, 'config.json'), 'utf8')).updateUrl || DEFAULT_URL; } catch { return DEFAULT_URL; }
}
const newer = (a, b) => { const x = String(a).split('.').map(Number), y = String(b).split('.').map(Number); for (let i = 0; i < 3; i++) { if ((x[i] || 0) > (y[i] || 0)) return true; if ((x[i] || 0) < (y[i] || 0)) return false; } return false; };

async function check() {
  const exe = process.env.PORTABLE_EXECUTABLE_FILE;            // only the portable Stella.exe can update itself
  if (!exe || (process.platform !== 'win32' && !process.env.STELLA_UPDATE_TEST)) return null;
  try {
    const r = await fetch(updateUrl() + '?t=' + Date.now(), { signal: AbortSignal.timeout(20000) });
    if (!r.ok) return null;
    const v = await r.json();
    if (!v.version || !newer(v.version, H.version) || !/^[0-9a-f]{64}$/.test(v.sha256 || '')) return null;
    if (ready && ready.version === v.version) return ready;
    H.log('update: downloading', v.version);
    const target = path.join(path.dirname(exe), 'Stella.update.exe');
    const res = await fetch(v.url, { signal: AbortSignal.timeout(15 * 60 * 1000) });
    if (!res.ok) throw new Error('download ' + res.status);
    const buf = Buffer.from(await res.arrayBuffer());
    const sum = crypto.createHash('sha256').update(buf).digest('hex');
    if (sum !== v.sha256) throw new Error('checksum mismatch — update rejected');
    fs.writeFileSync(target, buf);
    ready = { version: v.version, file: target, notes: v.notes || '' };
    H.send('update:ready', { version: v.version, notes: v.notes || '' });
    return ready;
  } catch (e) { H.log('update check failed', e.message); return null; }
}

// replace Stella.exe once this instance (and the portable launcher) has exited, then start it again
function apply() {
  const exe = process.env.PORTABLE_EXECUTABLE_FILE;
  if (!ready || !exe) return false;
  const cmd = path.join(os.tmpdir(), 'stella-update.cmd');
  fs.writeFileSync(cmd, [
    '@echo off',
    'set N=0',
    ':retry',
    'timeout /t 1 /nobreak >nul',
    `move /y "${ready.file}" "${exe}" >nul 2>&1 && goto done`,
    'set /a N+=1',
    'if %N% lss 90 goto retry',
    'exit /b 1',
    ':done',
    `start "" "${exe}"`,
    'del "%~f0"'
  ].join('\r\n'));
  spawn('cmd.exe', ['/c', cmd], { detached: true, stdio: 'ignore', windowsHide: true }).unref();
  return true;
}

function init(hooks) {
  H = Object.assign(H, hooks);
  setTimeout(check, 30 * 1000);
  setInterval(check, 6 * 3600 * 1000);
}

module.exports = { init, check, apply };

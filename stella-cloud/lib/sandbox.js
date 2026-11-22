// Where an account's agent runs.
//   docker  — its own container per account (default when Docker is available and we are root):
//             non-root user, no Linux capabilities, no-new-privileges, memory/CPU/process limits,
//             only the account's home is mounted. The agent cannot ask the host system for anything.
//   systemd — separate Linux user + systemd scope limits (fallback)
//   none    — dev mode
const fs = require('fs');
const path = require('path');
const { execFileSync, execSync, spawn } = require('child_process');

const IMAGE = process.env.STELLA_AGENT_IMAGE || 'stella-agent:latest';
const APP = path.join(__dirname, '..');
const lim = () => ({ mem: process.env.STELLA_LIMIT_MEM || '2G', cpu: process.env.STELLA_LIMIT_CPU || '100%', tasks: process.env.STELLA_LIMIT_TASKS || '256' });

let modeCache = null;
function has(cmd) { try { execSync('command -v ' + cmd, { shell: '/bin/bash', stdio: 'ignore' }); return true; } catch { return false; } }
function mode() {
  if (modeCache) return modeCache;
  const want = process.env.STELLA_SANDBOX || 'auto';
  const root = typeof process.getuid === 'function' && process.getuid() === 0;
  let dockerOk = false;
  if (root && want !== 'systemd' && want !== 'none' && has('docker')) {
    try { execFileSync('docker', ['image', 'inspect', IMAGE], { stdio: 'ignore', timeout: 15000 }); dockerOk = true; } catch {}
  }
  if (dockerOk && (want === 'auto' || want === 'docker')) modeCache = 'docker';
  else if (root && want !== 'none' && fs.existsSync('/run/systemd/system') && has('systemd-run')) modeCache = 'systemd';
  else modeCache = 'none';
  if (want === 'docker' && modeCache !== 'docker') console.error('[sandbox] STELLA_SANDBOX=docker, но образ ' + IMAGE + ' не найден — запустите install.sh');
  console.log('[sandbox] mode:', modeCache);
  return modeCache;
}

const cname = u => 'stella-' + u.name;
const HOME_IN = '/home/agent';

// docker CPU quota from "100%" -> "1.0"
const cpus = s => String(Math.max(0.1, (parseFloat(s) || 100) / 100));

// isolated network for agent containers: no traffic between containers (icc=false);
// stella-firewall.sh blocks it from the host itself, private ranges and cloud metadata
const NET = 'stella-net';
let netReady = false;
function ensureNetwork() {
  if (netReady) return;
  try { execFileSync('docker', ['network', 'inspect', NET], { stdio: 'ignore', timeout: 15000 }); }
  catch {
    execFileSync('docker', ['network', 'create', '--driver', 'bridge', '--subnet', '172.30.0.0/16',
      '-o', 'com.docker.network.bridge.name=stella0', '-o', 'com.docker.network.bridge.enable_icc=false', NET], { stdio: 'ignore', timeout: 30000 });
  }
  netReady = true;
}

function ensureContainer(u) {
  const name = cname(u);
  ensureNetwork();
  let state = '';
  try { state = execFileSync('docker', ['inspect', '-f', '{{.State.Running}} {{json .NetworkSettings.Networks}}', name], { encoding: 'utf8', timeout: 15000 }).trim(); } catch {}
  if (state && !state.includes('"' + NET + '"')) { removeContainer(u); state = ''; }   // created before the isolated network existed
  if (state.startsWith('true')) return name;
  if (state.startsWith('false')) { execFileSync('docker', ['start', name], { stdio: 'ignore', timeout: 30000 }); return name; }
  const L = lim();
  const args = ['run', '-d', '--init', '--network', NET, '--name', name, '--hostname', name, '--restart', 'unless-stopped',
    '--user', `${u.uid}:${u.gid}`,
    '--memory', L.mem, '--memory-swap', L.mem, '--cpus', cpus(L.cpu), '--pids-limit', L.tasks,
    '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
    '--tmpfs', '/tmp:rw,size=512m,mode=1777',
    '-v', `${u.home}:${HOME_IN}`,
    '-v', `${path.join(APP, 'mcp-whatsapp.js')}:/opt/stella/mcp-whatsapp.js:ro`,
    '-e', `HOME=${HOME_IN}`, '-e', 'LANG=C.UTF-8',
    '--label', 'stella.account=' + u.name];
  if (fs.existsSync('/usr/local/bin/agy')) args.push('-v', '/usr/local/bin/agy:/usr/local/bin/agy:ro');
  args.push(IMAGE, 'sleep', 'infinity');
  execFileSync('docker', args, { stdio: 'ignore', timeout: 60000 });
  return name;
}

function removeContainer(u) { try { execFileSync('docker', ['rm', '-f', cname(u)], { stdio: 'ignore', timeout: 30000 }); } catch {} }

// translate a host path inside the account home to the container path
const toIn = (u, p) => p.startsWith(u.home) ? HOME_IN + p.slice(u.home.length) : p;

/**
 * Build a command that runs `bin args` for this account.
 * returns { cmd, args, opts, kill() }
 */
function wrap(u, bin, args, { env = {}, cwd, runId, tty = false } = {}) {
  const m = mode();
  cwd = cwd || path.join(u.home, 'workspace');
  if (m === 'docker' && u.uid != null) {
    const name = ensureContainer(u);
    const id = runId || Math.random().toString(36).slice(2);
    const e = [];
    for (const [k, v] of Object.entries(env)) if (v != null) e.push('-e', `${k}=${v}`);
    const inner = path.basename(bin) === 'agy' ? 'agy' : bin;      // agy is on PATH inside the container
    return {
      cmd: 'docker',
      args: ['exec', tty ? '-it' : '-i', '-w', toIn(u, cwd), '-e', `HOME=${HOME_IN}`, '-e', `PATH=${HOME_IN}/.local/bin:/usr/local/bin:/usr/bin:/bin`, ...e, name,
        // own session/process group, so "stop" also kills everything the agent started (builds, scripts…)
        'setsid', '-w', 'sh', '-c', `echo $$ > /tmp/.stella-run-${id}; exec "$0" "$@"`, inner, ...args],
      opts: { cwd: '/', uid: undefined, gid: undefined },
      kill: () => { try { execFileSync('docker', ['exec', name, 'sh', '-c', `P=$(cat /tmp/.stella-run-${id}) && { kill -TERM -$P 2>/dev/null; sleep 2; kill -KILL -$P 2>/dev/null; }; rm -f /tmp/.stella-run-${id}`], { stdio: 'ignore', timeout: 15000 }); } catch {} }
    };
  }
  if (m === 'systemd' && u.uid != null) {
    const L = lim();
    return {
      cmd: 'systemd-run',
      args: ['--quiet', '--scope', '--collect', `--uid=${u.uid}`, `--gid=${u.gid}`, '-p', `MemoryMax=${L.mem}`, '-p', `CPUQuota=${L.cpu}`, '-p', `TasksMax=${L.tasks}`, '--', bin, ...args],
      opts: { cwd, uid: undefined, gid: undefined },
      kill: null
    };
  }
  return { cmd: bin, args, opts: { cwd, uid: u.uid, gid: u.gid }, kill: null };
}

// how the agent's WhatsApp MCP server is started (inside the container it reaches Stella via the public HTTPS URL)
function mcpServer(u, port) {
  if (mode() === 'docker') {
    const url = process.env.STELLA_PUBLIC_URL || `http://host.docker.internal:${port}`;
    return { command: 'node', args: ['/opt/stella/mcp-whatsapp.js'], env: { STELLA_URL: url, STELLA_TOKEN: u.mcpToken } };
  }
  return { command: process.execPath, args: [path.join(APP, 'mcp-whatsapp.js')], env: { STELLA_URL: `http://127.0.0.1:${port}`, STELLA_TOKEN: u.mcpToken } };
}

module.exports = { mode, wrap, ensureContainer, removeContainer, mcpServer, IMAGE, HOME_IN, toIn };

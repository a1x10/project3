'use strict';
const path = require('path');
const os = require('os');

/** Инструменты, которые только читают информацию. */
const SAFE_TOOLS = new Set([
  'list_directory', 'read_file', 'search_files', 'take_screenshot', 'get_screen_info', 'list_windows',
  'list_processes', 'system_info', 'clipboard_read', 'notify', 'set_timer', 'remember_fact', 'play_animation',
  'get_datetime', 'open_url', 'web_search', 'media_control', 'set_volume', 'get_cursor_position', 'wait', 'ui_list_elements',
]);

/** Инструменты, которые всегда требуют подтверждения. */
const ALWAYS_CONFIRM = new Set(['power_action']);

const DANGEROUS_PATTERNS = [
  /\brm\s+(-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r)\b/i,
  /\brm\s+-[a-z]*r[a-z]*\s+(\/|~|\*|\$HOME)/i,
  /\bmkfs(\.\w+)?\b/i,
  /\bdd\s+if=/i,
  /\bformat(\.com)?\s+[a-z]:/i,
  /\bdiskpart\b/i,
  /\bdel\s+(\/[a-z]\s+)*\/s\b/i,
  /\brd\s+\/s\b|\brmdir\s+\/s\b/i,
  /remove-item[^|;]*-recurse/i,
  /\bshutdown\b|\bStop-Computer\b|\bRestart-Computer\b|\breboot\b|\bpoweroff\b|\bhalt\b/i,
  /\breg(\.exe)?\s+delete\b|Remove-ItemProperty/i,
  /\bbcdedit\b|\bcipher\s+\/w\b|\bvssadmin\s+delete\b|\bwbadmin\s+delete\b/i,
  /:\(\)\s*\{\s*:\|:&\s*\};:/, // fork bomb
  /\bchmod\s+(-R\s+)?[0-7]*\s+\/(\s|$)|\bchown\s+-R\s+\S+\s+\/(\s|$)/i,
  />\s*\/dev\/sd[a-z]/i,
  /Set-ExecutionPolicy\s+Unrestricted/i,
  /\bnet\s+user\s+\S+\s+\/delete\b/i,
  /\bsudo\b/i,
  /\b(curl|wget|iwr|Invoke-WebRequest)\b[^|]*\|\s*(sh|bash|iex|Invoke-Expression)\b/i,
  /\bInvoke-Expression\b|\biex\s*\(/i,
  /\btakeown\b|\bicacls\b[^|]*\/grant/i,
];

const SYSTEM_DIRS_WIN = ['c:\\windows', 'c:\\program files', 'c:\\program files (x86)', 'c:\\programdata'];
const SYSTEM_DIRS_NIX = ['/bin', '/sbin', '/usr', '/etc', '/boot', '/lib', '/lib64', '/sys', '/proc', '/dev', '/var', '/System', '/Library', '/Applications'];

function isDangerousCommand(cmd) {
  const c = String(cmd || '');
  return DANGEROUS_PATTERNS.some((re) => re.test(c));
}

function isSystemPath(p, platform = process.platform) {
  if (!p) return false;
  const norm = platform === 'win32' ? path.win32.resolve(String(p)).toLowerCase() : path.posix.resolve(String(p));
  if (platform === 'win32') return SYSTEM_DIRS_WIN.some((d) => norm === d || norm.startsWith(d + '\\')) || /^[a-z]:\\?$/.test(norm);
  return norm === '/' || SYSTEM_DIRS_NIX.some((d) => norm === d || norm.startsWith(d + '/'));
}

/**
 * Классификация риска вызова инструмента.
 * @returns {{level:'safe'|'risky'|'danger', reason:string}}
 */
function classify(tool, args = {}, platform = process.platform) {
  if (ALWAYS_CONFIRM.has(tool)) return { level: 'danger', reason: 'Действие с питанием компьютера' };
  if (tool === 'run_command') {
    if (isDangerousCommand(args.command)) return { level: 'danger', reason: 'Потенциально разрушительная команда' };
    return { level: 'risky', reason: 'Выполнение команды в терминале' };
  }
  if (tool === 'delete_path') {
    if (isSystemPath(args.path, platform)) return { level: 'danger', reason: 'Удаление в системной папке' };
    if (isHome(args.path, platform)) return { level: 'danger', reason: 'Удаление домашней папки' };
    return { level: 'risky', reason: 'Удаление файла (в корзину)' };
  }
  if (tool === 'write_file' || tool === 'move_path' || tool === 'copy_path' || tool === 'create_folder') {
    const target = args.path || args.destination;
    if (isSystemPath(target, platform) || isSystemPath(args.source, platform)) return { level: 'danger', reason: 'Изменение системных файлов' };
    return { level: 'risky', reason: 'Изменение файлов' };
  }
  if (tool === 'kill_process') return { level: 'risky', reason: 'Завершение процесса' };
  if (SAFE_TOOLS.has(tool)) return { level: 'safe', reason: 'Только чтение / безопасное действие' };
  return { level: 'risky', reason: 'Действие на компьютере' };
}

function isHome(p, platform) {
  if (!p) return false;
  const home = os.homedir();
  const r = platform === 'win32' ? path.win32.resolve(String(p)).toLowerCase() : path.posix.resolve(String(p));
  const h = platform === 'win32' ? path.win32.resolve(home).toLowerCase() : path.posix.resolve(home);
  return r === h;
}

/**
 * Нужно ли спрашивать подтверждение в данном режиме.
 * confirm_all — всё, кроме безопасного чтения; confirm_risky — рискованное и опасное; autonomous — только опасное.
 */
const NEVER_CONFIRM = new Set(['play_animation', 'remember_fact', 'get_datetime', 'notify', 'set_timer', 'wait', 'get_cursor_position']);

function needsConfirmation(level, mode, tool = '') {
  if (level === 'danger') return true;
  if (NEVER_CONFIRM.has(tool)) return false;
  if (mode === 'autonomous') return false;
  if (mode === 'confirm_all') return true;
  return level === 'risky';
}

module.exports = { classify, needsConfirmation, NEVER_CONFIRM, isDangerousCommand, isSystemPath, SAFE_TOOLS, DANGEROUS_PATTERNS };

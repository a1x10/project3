/**
 * Static analysis of shell commands for permission decisions.
 * The goal is not to emulate a shell, but to make sure an allow-rule for one command can never
 * authorize a different one smuggled in via chaining, substitution, or nested interpreters.
 */

export type Risk = 'low' | 'medium' | 'high' | 'critical';

export interface ShellAnalysis {
  segments: string[]; // individual simple commands
  hasSubstitution: boolean; // $(...), `...`, <(...), >(...)
  hasRedirectWrite: boolean; // > or >> to a file (not /dev/null)
  nestedInterpreter: boolean; // sh -c, bash -c, eval, powershell -Command, node -e, python -c
  risk: Risk;
  readOnly: boolean;
  reasons: string[];
}

/** Split on ; && || | & and newlines, respecting quotes. */
export function splitCommand(cmd: string): { segments: string[]; hasSubstitution: boolean; hasRedirectWrite: boolean } {
  const segments: string[] = [];
  let cur = '';
  let q: '"' | "'" | null = null;
  let hasSubstitution = false;
  let hasRedirectWrite = false;
  for (let i = 0; i < cmd.length; i++) {
    const c = cmd[i]!;
    const n = cmd[i + 1];
    if (q) {
      if (c === '\\' && q === '"' && n !== undefined) {
        cur += c + n;
        i++;
        continue;
      }
      if (q === '"' && ((c === '$' && n === '(') || c === '`')) hasSubstitution = true;
      if (c === q) q = null;
      cur += c;
      continue;
    }
    if (c === '\\' && n !== undefined) {
      cur += c + n;
      i++;
      continue;
    }
    if (c === '"' || c === "'") {
      q = c;
      cur += c;
      continue;
    }
    if ((c === '$' && n === '(') || c === '`' || ((c === '<' || c === '>') && n === '(')) hasSubstitution = true;
    if (c === '>' && n !== '(') {
      const rest = cmd.slice(i + 1).replace(/^>?\s*/, '');
      if (!/^(&\d|\/dev\/null|nul\b|\$null)/i.test(rest) && cmd[i - 1] !== '2' && !(cmd[i - 1] === '&')) hasRedirectWrite = true;
      else if (cmd[i - 1] === '2' && !/^(\/dev\/null|&1|nul\b)/i.test(rest)) hasRedirectWrite = true;
    }
    const two = c + (n ?? '');
    if (two === '&&' || two === '||') {
      push();
      i++;
      continue;
    }
    if (c === ';' || c === '\n' || c === '|' || (c === '&' && cmd[i - 1] !== '>' && n !== '>')) {
      push();
      continue;
    }
    cur += c;
  }
  push();
  return { segments, hasSubstitution, hasRedirectWrite };
  function push() {
    const s = cur.trim();
    if (s) segments.push(s);
    cur = '';
  }
}

/** Strip leading env assignments (FOO=bar cmd) and wrappers like `time`, `nice`. */
export function baseCommand(segment: string): string {
  let s = segment.trim();
  for (;;) {
    const m = /^([A-Za-z_][A-Za-z0-9_]*=("[^"]*"|'[^']*'|\S*)\s+)/.exec(s);
    if (!m) break;
    s = s.slice(m[1]!.length);
  }
  s = s.replace(/^(time|nice|nohup|command)\s+/, '');
  return s;
}

const READ_ONLY = [
  /^(ls|dir|pwd|cat|type|head|tail|less|more|wc|grep|rg|egrep|fgrep|ag|tree|file|stat|du|df|which|where|whereis|whoami|uname|date|echo|printf|env|printenv|basename|dirname|realpath|readlink|sort|uniq|cut|tr|diff|cmp|md5sum|sha1sum|sha256sum|true|false|test|\[)(\s|$)/,
  /^find\s(?!.*\s-(exec|execdir|delete|ok|fprint)\b)/,
  /^find$/,
  /^git\s+(status|diff|log|show|branch(\s+(-a|-r|--list|-v|-vv))*\s*$|rev-parse|ls-files|blame|remote(\s+-v)?\s*$|describe|shortlog|tag\s*$|config\s+--get|grep|stash\s+list)/,
  /^(node|npm|npx|pnpm|yarn|python3?|pip3?|go|cargo|rustc|java|javac|dotnet|ruby|php|tsc|deno|bun)\s+(--version|-v|-V|version)\s*$/,
  /^npm\s+(ls|list|view|outdated|config\s+get)\b/,
  /^(Get-ChildItem|Get-Content|Get-Location|Select-String|Get-Item|Test-Path|Resolve-Path|gci|gc|sls)(\s|$)/i,
];

const CRITICAL: Array<[RegExp, string]> = [
  [/\brm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)+(-[a-zA-Z]+\s+)*(\/|~|\$HOME|\/\*|~\/\*|\.\.?\/?\s*$|\*)(\s|$)/, 'recursive delete of root/home/cwd'],
  [/\brm\s+.*--no-preserve-root/, 'rm --no-preserve-root'],
  [/\bmkfs(\.\w+)?\b/, 'filesystem format'],
  [/\bdd\s+.*\bof=\/dev\//, 'raw disk write'],
  [/:\(\)\s*\{\s*:\|:&\s*\};:/, 'fork bomb'],
  [/\b(shutdown|reboot|halt|poweroff|init\s+0)\b/, 'system power control'],
  [/\bchmod\s+(-R\s+)?[0-7]*777\s+\/(\s|$)/, 'chmod 777 on /'],
  [/\bformat\s+[a-z]:/i, 'drive format'],
  [/Remove-Item\s+.*-Recurse.*\s([A-Za-z]:\\?\s*$|[A-Za-z]:\\\*|~|\$HOME)/i, 'recursive delete of drive/home'],
  [/\b(rd|rmdir)\s+\/s\s+(\/q\s+)?[a-z]:\\?\s*$/i, 'recursive delete of drive'],
  [/>\s*\/dev\/sd[a-z]/, 'raw disk write'],
  [/\bgit\s+push\s+.*(--force|-f)\b.*\b(main|master)\b/, 'force push to main'],
];

const HIGH: Array<[RegExp, string]> = [
  [/\brm\s/, 'file deletion'],
  [/\b(rmdir|unlink|shred)\b/, 'file deletion'],
  [/\b(del|erase|Remove-Item|ri)\s/i, 'file deletion'],
  [/\bsudo\b|\bdoas\b|\brunas\b/, 'privilege escalation'],
  [/\b(curl|wget|iwr|Invoke-WebRequest)\b.*\|\s*(sh|bash|zsh|python3?|node|iex|Invoke-Expression)\b/i, 'piping download into interpreter'],
  [/\b(npm|pnpm|yarn|bun)\s+(i|install|add|uninstall|remove|rm|update|upgrade|publish|link)\b/, 'package installation/publish'],
  [/\b(pip3?|pipx|uv)\s+(install|uninstall)\b|\bpoetry\s+(add|remove)\b|\bcargo\s+(install|add)\b|\bgo\s+install\b|\bgem\s+install\b|\bapt(-get)?\s|\bbrew\s+(install|uninstall)\b|\bchoco\s|\bwinget\s/, 'package installation'],
  [/\bgit\s+(push|reset\s+--hard|clean\s+-[a-z]*f|checkout\s+--\s|restore\s|rebase|branch\s+-[dD]|filter-branch|reflog\s+expire|stash\s+(drop|clear))/, 'destructive or remote git operation'],
  [/\b(chmod|chown|chgrp|icacls|takeown)\b/, 'permission change'],
  [/\b(kill|pkill|killall|taskkill|Stop-Process)\b/, 'process termination'],
  [/\b(systemctl|service|launchctl|sc\.exe|reg\s+(add|delete)|Set-ItemProperty|setx)\b/i, 'system configuration'],
  [/\bdocker\s+(rm|rmi|system\s+prune|volume\s+rm)|\bkubectl\s+(delete|apply)/, 'container/cluster mutation'],
  [/\b(mv|move|Move-Item)\s/i, 'move/rename files'],
  [/\b(crontab|at)\s/, 'scheduled job change'],
  [/\b(ssh|scp|rsync|ftp|sftp|nc|ncat|telnet)\b/, 'remote access'],
];

const NESTED = /\b(sh|bash|zsh|fish|dash|ksh|cmd(\.exe)?|pwsh|powershell(\.exe)?)\s+(-[a-zA-Z]*c\b|\/c\b|-Command\b|-EncodedCommand\b|-e\b)|\beval\b|\b(node|deno|bun)\s+(-e|--eval|-p)\b|\b(python3?|ruby|perl|php)\s+-[ce]\b|\bxargs\b|\bInvoke-Expression\b|\biex\b|\bfind\b.*\s-(exec|execdir)\b|\bsource\b|^\.\s/i;

export function analyzeShell(cmd: string): ShellAnalysis {
  const { segments, hasSubstitution, hasRedirectWrite } = splitCommand(cmd);
  const reasons: string[] = [];
  let risk: Risk = 'low';
  const bump = (r: Risk, why: string) => {
    const order: Risk[] = ['low', 'medium', 'high', 'critical'];
    if (order.indexOf(r) > order.indexOf(risk)) risk = r;
    reasons.push(why);
  };
  const nestedInterpreter = segments.some((s) => NESTED.test(baseCommand(s)));
  for (const [re, why] of CRITICAL) if (re.test(cmd)) bump('critical', why);
  for (const seg of segments) {
    const b = baseCommand(seg);
    for (const [re, why] of HIGH) if (re.test(b)) bump('high', why);
  }
  if (hasSubstitution) bump('high', 'command substitution');
  if (nestedInterpreter) bump('high', 'nested interpreter / eval');
  const readOnly = !hasSubstitution && !hasRedirectWrite && !nestedInterpreter && segments.length > 0 && segments.every((s) => READ_ONLY.some((re) => re.test(baseCommand(s))));
  if (!readOnly && risk === 'low') bump('medium', hasRedirectWrite ? 'writes via redirection' : 'executes a program');
  return { segments, hasSubstitution, hasRedirectWrite, nestedInterpreter, risk, readOnly, reasons };
}

import chalk from 'chalk';

/** STELLA palette: deep violet → star blue, with warm accents. */
export const theme = {
  brand: '#A78BFA',
  brand2: '#60A5FA',
  accent: '#F472B6',
  star: '#FDE68A',
  text: '#E5E7EB',
  dim: '#9CA3AF',
  faint: '#6B7280',
  ok: '#34D399',
  warn: '#FBBF24',
  err: '#F87171',
  add: '#22C55E',
  del: '#EF4444',
  code: '#C4B5FD',
  border: '#4C1D95',
  tool: '#93C5FD',
  user: '#F9A8D4',
};

export const c = {
  brand: chalk.hex(theme.brand),
  brand2: chalk.hex(theme.brand2),
  accent: chalk.hex(theme.accent),
  star: chalk.hex(theme.star),
  dim: chalk.hex(theme.dim),
  faint: chalk.hex(theme.faint),
  ok: chalk.hex(theme.ok),
  warn: chalk.hex(theme.warn),
  err: chalk.hex(theme.err),
  add: chalk.hex(theme.add),
  del: chalk.hex(theme.del),
  code: chalk.hex(theme.code),
  tool: chalk.hex(theme.tool),
  bold: chalk.bold,
  italic: chalk.italic,
};

/** Horizontal gradient for the logo. */
export function gradient(text: string, from = [167, 139, 250], to = [96, 165, 250]): string {
  const chars = [...text];
  const n = Math.max(1, chars.length - 1);
  return chars
    .map((ch, i) => {
      const t = i / n;
      const r = Math.round(from[0]! + (to[0]! - from[0]!) * t);
      const g = Math.round(from[1]! + (to[1]! - from[1]!) * t);
      const b = Math.round(from[2]! + (to[2]! - from[2]!) * t);
      return chalk.rgb(r, g, b)(ch);
    })
    .join('');
}

export const LOGO = [
  '  ███████╗████████╗███████╗██╗     ██╗      █████╗ ',
  '  ██╔════╝╚══██╔══╝██╔════╝██║     ██║     ██╔══██╗',
  '  ███████╗   ██║   █████╗  ██║     ██║     ███████║',
  '  ╚════██║   ██║   ██╔══╝  ██║     ██║     ██╔══██║',
  '  ███████║   ██║   ███████╗███████╗███████╗██║  ██║',
  '  ╚══════╝   ╚═╝   ╚══════╝╚══════╝╚══════╝╚═╝  ╚═╝',
];

export const SPINNER = ['✶', '✸', '✹', '✺', '✹', '✸'];
export const SPINNER_ASCII = ['-', '\\', '|', '/'];

export function supportsUnicode(): boolean {
  if (process.platform !== 'win32') return process.env.TERM !== 'linux';
  return !!process.env.WT_SESSION || !!process.env.TERM_PROGRAM || process.env.ConEmuTask === '{cmd::Cmder}' || process.env.TERM === 'xterm-256color';
}

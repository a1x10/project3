import chalk from 'chalk';
import { c } from './theme.js';

const KEYWORDS = new Set(
  'abstract as async await break case catch class const continue def default del delete do elif else enum export extends false final finally fn for from func function go if impl import in interface is lambda let match mod module mut new nil none not null or package pass private protected pub public raise return self static struct super switch this throw true try type typeof undefined use var void while with yield'.split(' '),
);

/** Very small, fast syntax highlighter (keywords, strings, numbers, comments). */
export function highlight(code: string, lang = ''): string {
  if (/^(diff|patch)$/.test(lang)) return code.split('\n').map((l) => (l.startsWith('+') ? c.add(l) : l.startsWith('-') ? c.del(l) : l.startsWith('@@') ? c.brand2(l) : l)).join('\n');
  if (/^(json)$/.test(lang)) return code.replace(/("(?:[^"\\]|\\.)*")(\s*:)?|\b(-?\d+(?:\.\d+)?)\b|\b(true|false|null)\b/g, (m, s, colon, n, k) => (s ? (colon ? c.brand2(s) + colon : c.ok(s)) : n ? c.star(n) : k ? c.accent(k) : m));
  const commentRe = /^(\s*)(\/\/.*|#(?!include|!).*|--\s.*)$/;
  return code
    .split('\n')
    .map((line) => {
      const cm = commentRe.exec(line);
      if (cm && !/^(md|markdown|text)$/.test(lang)) return cm[1] + c.faint(cm[2]!);
      return line.replace(/("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`)|\b(\d+(?:\.\d+)?)\b|\b([A-Za-z_]\w*)\b(?=\s*\()|\b([A-Za-z_]\w*)\b/g, (m, str, num, call, word) => {
        if (str) return c.ok(str);
        if (num) return c.star(num);
        if (call) return KEYWORDS.has(call) ? c.accent(call) : c.brand2(call);
        if (word && KEYWORDS.has(word)) return c.accent(word);
        return m;
      });
    })
    .join('\n');
}

function inline(s: string): string {
  return s
    .replace(/`([^`]+)`/g, (_m, t) => c.code(t))
    .replace(/\*\*([^*]+)\*\*/g, (_m, t) => chalk.bold(t))
    .replace(/(^|[^\w*])\*([^*\n]+)\*(?!\w)/g, (_m, p, t) => p + chalk.italic(t))
    .replace(/(^|[^\w_])_([^_\n]+)_(?!\w)/g, (_m, p, t) => p + chalk.italic(t))
    .replace(/~~([^~]+)~~/g, (_m, t) => chalk.strikethrough(t))
    .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, (_m, t, u) => `${chalk.underline(t)} ${c.faint(`(${u})`)}`);
}

/** Render Markdown to ANSI for the terminal. Streaming-safe (unterminated fences are fine). */
export function renderMarkdown(md: string, width = 100): string {
  const lines = md.replace(/\r\n/g, '\n').split('\n');
  const out: string[] = [];
  let inCode = false;
  let lang = '';
  let buf: string[] = [];
  const flushCode = () => {
    const body = highlight(buf.join('\n'), lang);
    const label = lang ? c.faint(` ${lang} `) : '';
    out.push(c.faint('╭─') + label + c.faint('─'.repeat(Math.max(0, Math.min(width, 60) - 4 - (lang ? lang.length + 2 : 0)))));
    for (const l of body.split('\n')) out.push(c.faint('│ ') + l);
    out.push(c.faint('╰' + '─'.repeat(Math.max(10, Math.min(width, 60) - 2))));
    buf = [];
  };
  for (const raw of lines) {
    const fence = /^\s*(```|~~~)\s*([\w+#.-]*)/.exec(raw);
    if (fence) {
      if (inCode) {
        flushCode();
        inCode = false;
      } else {
        inCode = true;
        lang = fence[2] ?? '';
      }
      continue;
    }
    if (inCode) {
      buf.push(raw);
      continue;
    }
    const h = /^(#{1,6})\s+(.*)$/.exec(raw);
    if (h) {
      const level = h[1]!.length;
      const text = inline(h[2]!);
      out.push(level === 1 ? chalk.bold(c.brand(text)) : level === 2 ? chalk.bold(c.brand2(text)) : chalk.bold(text));
      continue;
    }
    if (/^\s*([-*_])\s*\1\s*\1[\s\-*_]*$/.test(raw)) {
      out.push(c.faint('─'.repeat(Math.min(width, 60))));
      continue;
    }
    const li = /^(\s*)([-*+]|\d+[.)])\s+(\[[ xX]\]\s+)?(.*)$/.exec(raw);
    if (li) {
      const indent = li[1]!;
      const bullet = /\d/.test(li[2]!) ? c.brand2(li[2]!) : c.brand('•');
      const box = li[3] ? (/x/i.test(li[3]) ? c.ok('☑ ') : c.dim('☐ ')) : '';
      out.push(`${indent}${bullet} ${box}${inline(li[4]!)}`);
      continue;
    }
    const bq = /^\s*>\s?(.*)$/.exec(raw);
    if (bq) {
      out.push(c.faint('▎ ') + c.dim(inline(bq[1]!)));
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(raw)) {
      if (/^\s*\|[\s:|-]+\|\s*$/.test(raw)) continue;
      out.push(
        raw
          .trim()
          .slice(1, -1)
          .split('|')
          .map((cell) => ' ' + inline(cell.trim()) + ' ')
          .join(c.faint('│')),
      );
      continue;
    }
    out.push(inline(raw));
  }
  if (inCode) flushCode();
  return out.join('\n');
}

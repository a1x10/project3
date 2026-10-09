// Текстовые утилиты: очистка HTML из дневника, разбиение длинных сообщений, Markdown -> WhatsApp.

const ENTITIES = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ', laquo: '«', raquo: '»', ndash: '–', mdash: '—', hellip: '…', deg: '°', times: '×', divide: '÷', sup2: '²', sup3: '³', frac12: '½', minus: '−', le: '≤', ge: '≥', ne: '≠' };

export function decodeEntities(text) {
  return text.replace(/&(#x[0-9a-f]+|#\d+|[a-z0-9]+);/gi, (all, code) => {
    if (code[0] === '#') {
      const n = code[1].toLowerCase() === 'x' ? parseInt(code.slice(2), 16) : parseInt(code.slice(1), 10);
      return Number.isFinite(n) && n > 0 && n < 0x110000 ? String.fromCodePoint(n) : all;
    }
    return ENTITIES[code.toLowerCase()] ?? all;
  });
}

// Текст ДЗ из BilimClass иногда приходит в HTML из редактора — превращаем в обычный текст
export function htmlToText(value) {
  if (value == null) return '';
  let text = String(value);
  if (/<[a-z/][^>]*>/i.test(text)) {
    text = text
      .replace(/<\s*br\s*\/?>/gi, '\n')
      .replace(/<\s*li[^>]*>/gi, '\n• ')
      .replace(/<\/\s*(p|div|h\d|tr|ul|ol)\s*>/gi, '\n')
      .replace(/<[^>]+>/g, '');
  }
  return decodeEntities(text)
    .replace(/\r/g, '')
    .replace(/[ \t ]+/g, ' ')
    .replace(/ *\n */g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

export function truncate(text, max) {
  if (text.length <= max) return text;
  return `${text.slice(0, Math.max(0, max - 1)).trimEnd()}…`;
}

// Разбиваем длинный текст на части по абзацам, чтобы не превышать лимит
export function splitMessage(text, limit = 3500) {
  if (text.length <= limit) return [text];
  const parts = [];
  let current = '';
  const flush = () => {
    if (current.trim()) parts.push(current.trim());
    current = '';
  };
  for (const block of text.split('\n\n')) {
    const candidate = current ? `${current}\n\n${block}` : block;
    if (candidate.length <= limit) {
      current = candidate;
      continue;
    }
    flush();
    if (block.length <= limit) {
      current = block;
      continue;
    }
    // очень длинный абзац — режем по строкам, а если и строка огромная — по символам
    for (const line of block.split('\n')) {
      const next = current ? `${current}\n${line}` : line;
      if (next.length <= limit) {
        current = next;
      } else {
        flush();
        for (let i = 0; i < line.length; i += limit) {
          const chunk = line.slice(i, i + limit);
          if (chunk.length === limit) parts.push(chunk);
          else current = chunk;
        }
      }
    }
  }
  flush();
  return parts;
}

// Для сравнения строк: нижний регистр, ё->е, без пунктуации
export function normalize(text) {
  return String(text || '')
    .toLowerCase()
    .replace(/ё/g, 'е')
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

const SUPERSCRIPT = { 0: '⁰', 1: '¹', 2: '²', 3: '³', 4: '⁴', 5: '⁵', 6: '⁶', 7: '⁷', 8: '⁸', 9: '⁹', '-': '⁻', '+': '⁺', n: 'ⁿ', x: 'ˣ' };
const toSuper = (s) => [...s].map((c) => SUPERSCRIPT[c] ?? c).join('');

// Простая конвертация LaTeX-формул в читабельный текст (WhatsApp формулы не рендерит)
export function latexToText(text) {
  let out = text
    .replace(/\$\$([\s\S]+?)\$\$/g, '$1')
    .replace(/\\\[([\s\S]+?)\\\]/g, '$1')
    .replace(/\\\(([\s\S]+?)\\\)/g, '$1')
    .replace(/(^|[^\\$])\$([^$\n]+?)\$/g, '$1$2');
  for (let i = 0; i < 3; i += 1) {
    out = out
      .replace(/\\[dt]?frac\{([^{}]*)\}\{([^{}]*)\}/g, '($1)/($2)')
      .replace(/\\sqrt\[(\w+)\]\{([^{}]*)\}/g, '$1√($2)')
      .replace(/\\sqrt\{([^{}]*)\}/g, '√($1)')
      .replace(/\\(?:text|mathrm|mathbf|operatorname)\{([^{}]*)\}/g, '$1');
  }
  out = out
    .replace(/\(([a-zA-Z0-9.]+)\)\/\(([a-zA-Z0-9.]+)\)/g, '$1/$2')
    .replace(/\\cdot/g, '·')
    .replace(/\\times/g, '×')
    .replace(/\\div/g, '÷')
    .replace(/\\pm/g, '±')
    .replace(/\\le(q)?/g, '≤')
    .replace(/\\ge(q)?/g, '≥')
    .replace(/\\neq?/g, '≠')
    .replace(/\\approx/g, '≈')
    .replace(/\\infty/g, '∞')
    .replace(/\\pi/g, 'π')
    .replace(/\\alpha/g, 'α')
    .replace(/\\beta/g, 'β')
    .replace(/\\Delta/g, 'Δ')
    .replace(/\\degree|\^\{?\\circ\}?/g, '°')
    .replace(/\\(?:left|right)\s*/g, '')
    .replace(/\\[,;!: ]/g, ' ')
    .replace(/\^\{([0-9+\-nx]+)\}/g, (_, p) => toSuper(p))
    .replace(/\^([0-9])/g, (_, p) => toSuper(p))
    .replace(/_\{([^{}]+)\}/g, '$1')
    .replace(/\\\\/g, '\n');
  return out;
}

// Markdown от нейросети -> разметка WhatsApp (*жирный*, _курсив_, ~зачёркнутый~, ```код```)
export function markdownToWhatsApp(text) {
  let out = String(text || '').replace(/<think>[\s\S]*?<\/think>/gi, '');
  out = latexToText(out);
  out = out
    .replace(/^#{1,6}\s*(.+?)\s*#*$/gm, '*$1*')
    .replace(/\*\*\*(.+?)\*\*\*/g, '*_$1_*')
    .replace(/\*\*(.+?)\*\*/g, '*$1*')
    .replace(/__(.+?)__/g, '*$1*')
    .replace(/~~(.+?)~~/g, '~$1~')
    .replace(/^\s*[-*]\s+/gm, '• ')
    .replace(/^\s*>\s?/gm, '> ')
    .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '$1 ($2)')
    .replace(/^\s*\|?\s*:?-{3,}.*$/gm, '')
    .replace(/\*\*/g, '')
    .replace(/\n{3,}/g, '\n\n');
  return out.trim();
}

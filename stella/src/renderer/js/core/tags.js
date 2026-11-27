// Разбор тегов эмоций/действий в ответах ассистента и нарезка текста на фразы для озвучки.
export const EMOTIONS = ['happy', 'sad', 'angry', 'surprised', 'relaxed', 'neutral', 'love', 'thinking', 'shy', 'smug'];
export const ACTIONS = ['wave', 'dance', 'nod', 'shake', 'think', 'jump', 'bow', 'clap', 'stretch', 'spin', 'point', 'heart', 'laugh', 'shrug', 'victory', 'sleepy'];
const ALL = new Set([...EMOTIONS, ...ACTIONS]);

const TAG_RE = /\[([a-zA-Z_]{2,16})\]/g;

/** Извлекает известные теги из текста. Неизвестные [слова] оставляет. */
export function parseTags(text) {
  const emotions = [], actions = [];
  const clean = String(text ?? '').replace(TAG_RE, (m, name) => {
    const n = name.toLowerCase();
    if (!ALL.has(n)) return m;
    (EMOTIONS.includes(n) ? emotions : actions).push(n);
    return '';
  }).replace(/[ \t]{2,}/g, ' ').replace(/^\s+/, '').replace(/ +([,.!?…])/g, '$1');
  return { clean: clean.trim(), emotions, actions };
}

export function stripTags(text) { return parseTags(text).clean; }

/**
 * Потоковый нарезчик: принимает токены, отдаёт готовые предложения для TTS и найденные теги.
 * Теги могут приходить разорванными между токенами: «[da» + «nce]».
 */
export class SpeechChunker {
  constructor({ minChars = 18, maxChars = 220 } = {}) {
    this.buf = '';
    this.minChars = minChars;
    this.maxChars = maxChars;
    this.inCode = false;
  }

  push(token) {
    this.buf += token;
    const tags = [];
    const sentences = [];
    // извлекаем полностью пришедшие теги
    this.buf = this.buf.replace(TAG_RE, (m, name) => {
      const n = name.toLowerCase();
      if (!ALL.has(n)) return m;
      tags.push({ type: EMOTIONS.includes(n) ? 'emotion' : 'action', name: n });
      return '';
    });
    for (;;) {
      const cut = this._findCut();
      if (cut < 0) break;
      const s = this.buf.slice(0, cut).trim();
      this.buf = this.buf.slice(cut);
      if (s) sentences.push(s);
    }
    return { sentences, tags };
  }

  _findCut() {
    // незакрытая квадратная скобка в конце — ждём продолжения тега
    const text = this.buf;
    // блоки кода не режем
    const fences = (text.match(/```/g) || []).length;
    if (fences % 2 === 1) return -1;
    const re = /([.!?…]+["»)]*)(\s+|$)|\n+/g;
    let m;
    while ((m = re.exec(text))) {
      const end = m.index + m[0].length;
      if (m[2] === '' && end === text.length && !/\n/.test(m[0])) return -1; // знак в самом конце — может быть «...»
      if (end >= this.minChars || /\n/.test(m[0])) return end;
    }
    if (text.length > this.maxChars) {
      const sp = text.lastIndexOf(' ', this.maxChars);
      return sp > this.minChars ? sp + 1 : this.maxChars;
    }
    return -1;
  }

  flush() {
    const rest = this.buf.trim();
    this.buf = '';
    const { clean } = parseTags(rest);
    return clean ? [clean] : [];
  }
}

/** Подходит ли фрагмент для озвучки (не только код/символы). */
export function isSpeakable(s) {
  const t = String(s || '').replace(/```[\s\S]*?```/g, '').replace(/[^\p{L}\p{N}]/gu, '');
  return t.length >= 2;
}

// Распознавание обращения по имени («Стелла, …», «Эй, Марк …»).
export function normalize(s) {
  return String(s || '').toLowerCase().replace(/ё/g, 'е').replace(/[^\p{L}\p{N}\s]/gu, ' ').replace(/\s+/g, ' ').trim();
}

export function levenshtein(a, b) {
  if (a === b) return 0;
  const m = a.length, n = b.length;
  if (!m) return n; if (!n) return m;
  let prev = Array.from({ length: n + 1 }, (_, j) => j);
  for (let i = 1; i <= m; i++) {
    const cur = [i];
    for (let j = 1; j <= n; j++) cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    prev = cur;
  }
  return prev[n];
}

// реальные слова, похожие на имена, — никогда не считаем обращением
const CONFUSABLE = new Set(['стена', 'стены', 'стене', 'стену', 'стелю', 'стели', 'мрак', 'марка', 'марки', 'маркер', 'мак', 'парк', 'барк', 'stall', 'still', 'steel', 'mask', 'park']);

function similar(word, target) {
  if (word === target) return true;
  if (CONFUSABLE.has(word)) return false;
  if (target.length <= 3) return false;
  const d = levenshtein(word, target);
  return d <= (target.length >= 6 ? 2 : 1);
}

const FILLERS = new Set(['эй', 'хей', 'hey', 'ok', 'окей', 'ну', 'слушай', 'привет', 'алло', 'дорогая', 'дорогой']);

/**
 * Ищет имя ассистента в начале фразы (среди первых 3 слов).
 * @returns {{matched:boolean, command:string, onlyName:boolean}}
 */
export function detectWakeWord(transcript, names) {
  const words = normalize(transcript).split(' ').filter(Boolean);
  const targets = names.map(normalize).filter((n) => !n.includes(' '));
  for (let i = 0; i < Math.min(words.length, 3); i++) {
    const w = words[i];
    if (targets.some((t) => similar(w, t))) {
      if (words.slice(0, i).some((x) => !FILLERS.has(x))) continue;
      const command = words.slice(i + 1).join(' ');
      return { matched: true, command, onlyName: !command };
    }
  }
  return { matched: false, command: '', onlyName: false };
}

/** Упоминается ли имя где-то в тексте (для реакции аватара в чате). */
export function mentionsName(text, names) {
  const words = normalize(text).split(' ');
  const targets = names.map(normalize).filter((n) => !n.includes(' '));
  return words.some((w) => targets.some((t) => similar(w, t)));
}

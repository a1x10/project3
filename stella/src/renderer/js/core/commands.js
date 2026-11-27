// Пользовательские команды: фраза-триггер → список действий (без ИИ).
import { normalize } from './wakeword.js';

export const ACTION_TYPES = [
  ['say', 'Сказать фразу', 'Текст, который произнесёт ассистент'],
  ['animation', 'Анимация', 'wave, dance, jump, heart, bow…'],
  ['emotion', 'Эмоция', 'happy, sad, surprised, love…'],
  ['open_url', 'Открыть сайт', 'https://youtube.com'],
  ['web_search', 'Поиск в интернете', 'Что искать (можно {query})'],
  ['launch_app', 'Запустить приложение', 'telegram, chrome, notepad…'],
  ['open_path', 'Открыть файл/папку', '~/Downloads'],
  ['run_command', 'Команда терминала', 'Get-Date / ls ~'],
  ['press_keys', 'Нажать клавиши', 'ctrl+shift+esc'],
  ['type_text', 'Напечатать текст', 'Текст для ввода'],
  ['media_control', 'Медиа', 'play_pause, next, previous, mute…'],
  ['set_volume', 'Громкость', '0–100'],
  ['wait', 'Пауза (мс)', '1000'],
];

/**
 * Ищет команду, подходящую под фразу пользователя.
 * {query} в триггере захватывает остаток фразы: «найди {query}».
 * @returns {{command, query:string}|null}
 */
export function matchCommand(text, commands, mode = 'contains', names = []) {
  let t = normalize(text);
  // убираем обращение по имени в начале: «Стелла, открой ютуб»
  for (const n of names.map(normalize)) if (n && t.startsWith(n + ' ')) { t = t.slice(n.length + 1); break; }
  if (!t) return null;
  let best = null;
  for (const c of commands || []) {
    if (c.enabled === false) continue;
    for (const raw of c.triggers || []) {
      const hasQuery = raw.includes('{query}');
      const trig = normalize(raw.replace('{query}', ' qqqq '));
      if (!trig) continue;
      if (hasQuery) {
        const [pre, post] = trig.split('qqqq').map((x) => x.trim());
        const okPre = mode === 'exact' ? t.startsWith(pre) : t.includes(pre);
        if (!okPre) continue;
        let rest = t.slice(t.indexOf(pre) + pre.length).trim();
        if (post) { const i = rest.lastIndexOf(post); if (i < 0) continue; rest = rest.slice(0, i).trim(); }
        if (!rest) continue;
        const score = pre.length + (post?.length || 0);
        if (!best || score > best.score) best = { command: c, query: rest, score };
      } else {
        const ok = mode === 'exact' ? t === trig : (` ${t} `).includes(` ${trig} `);
        if (ok && (!best || trig.length > best.score)) best = { command: c, query: '', score: trig.length };
      }
    }
  }
  return best ? { command: best.command, query: best.query } : null;
}

/** Подставляет {query} в значения действий. */
export function resolveActions(command, query = '') {
  return command.actions.map((a) => ({ ...a, value: String(a.value ?? '').replace(/\{query\}/g, query) }));
}

/** Аргументы инструмента для действия команды (null — действие выполняется в интерфейсе). */
export function actionToTool(a) {
  const v = a.value;
  switch (a.type) {
    case 'open_url': return { name: 'open_url', args: { url: v } };
    case 'web_search': return { name: 'web_search', args: { query: v } };
    case 'launch_app': return { name: 'launch_app', args: { name: v } };
    case 'open_path': return { name: 'open_path', args: { path: v } };
    case 'run_command': return { name: 'run_command', args: { command: v } };
    case 'press_keys': return { name: 'press_keys', args: { keys: v } };
    case 'type_text': return { name: 'type_text', args: { text: v } };
    case 'media_control': return { name: 'media_control', args: { action: v } };
    case 'set_volume': return { name: 'set_volume', args: { level: Number(v) } };
    default: return null;
  }
}

export const EXAMPLE_COMMANDS = [
  { name: 'YouTube', triggers: ['открой ютуб', 'включи ютуб', 'open youtube'], actions: [{ type: 'say', value: 'Открываю YouTube!' }, { type: 'animation', value: 'point' }, { type: 'open_url', value: 'https://www.youtube.com' }] },
  { name: 'Найти в интернете', triggers: ['найди {query}', 'загугли {query}'], actions: [{ type: 'say', value: 'Ищу: {query}' }, { type: 'web_search', value: '{query}' }] },
  { name: 'Танец', triggers: ['станцуй', 'потанцуй', 'танцуй'], actions: [{ type: 'emotion', value: 'happy' }, { type: 'animation', value: 'dance' }, { type: 'say', value: 'Смотри, как я умею!' }] },
  { name: 'Пауза музыки', triggers: ['пауза', 'стоп музыка', 'продолжи музыку'], actions: [{ type: 'media_control', value: 'play_pause' }, { type: 'animation', value: 'nod' }] },
  { name: 'Диспетчер задач', triggers: ['открой диспетчер задач'], actions: [{ type: 'press_keys', value: 'ctrl+shift+esc' }, { type: 'say', value: 'Готово.' }] },
];

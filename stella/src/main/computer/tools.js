'use strict';
const path = require('path');
const os = require('os');
const input = require('./input');

const fn = (name, description, properties = {}, required = []) => ({
  type: 'function',
  function: { name, description, parameters: { type: 'object', properties, required, additionalProperties: false } },
});
const str = (description, extra = {}) => ({ type: 'string', description, ...extra });
const num = (description, extra = {}) => ({ type: 'number', description, ...extra });
const bool = (description) => ({ type: 'boolean', description });

const XY = { x: num('X на последнем скриншоте (пиксели)'), y: num('Y на последнем скриншоте (пиксели)') };

const TOOL_DEFS = [
  fn('run_command', 'Выполнить команду в терминале (PowerShell на Windows, bash/zsh на Linux/macOS). Возвращает вывод.', {
    command: str('Команда'), cwd: str('Рабочая папка (необязательно)'),
  }, ['command']),
  fn('launch_app', 'Запустить приложение по имени (например: notepad, calc, chrome, telegram, spotify, code, explorer).', { name: str('Имя приложения') }, ['name']),
  fn('open_url', 'Открыть ссылку в браузере по умолчанию.', { url: str('http(s)-ссылка') }, ['url']),
  fn('web_search', 'Открыть поиск в браузере.', { query: str('Запрос'), engine: str('google | yandex | youtube | bing | duckduckgo', { enum: ['google', 'yandex', 'youtube', 'bing', 'duckduckgo'] }) }, ['query']),
  fn('open_path', 'Открыть файл или папку в программе по умолчанию (проводник, просмотрщик и т.д.).', { path: str('Путь') }, ['path']),
  fn('list_directory', 'Показать содержимое папки.', { path: str('Путь (~ — домашняя папка)'), show_hidden: bool('Показывать скрытые') }, ['path']),
  fn('read_file', 'Прочитать текстовый файл (до 100 КБ).', { path: str('Путь к файлу') }, ['path']),
  fn('write_file', 'Создать или перезаписать текстовый файл.', { path: str('Путь'), content: str('Содержимое'), append: bool('Дописать в конец вместо перезаписи') }, ['path', 'content']),
  fn('create_folder', 'Создать папку (с промежуточными).', { path: str('Путь') }, ['path']),
  fn('move_path', 'Переместить или переименовать файл/папку.', { source: str('Откуда'), destination: str('Куда') }, ['source', 'destination']),
  fn('copy_path', 'Скопировать файл/папку.', { source: str('Откуда'), destination: str('Куда') }, ['source', 'destination']),
  fn('delete_path', 'Удалить файл или папку (в корзину).', { path: str('Путь') }, ['path']),
  fn('search_files', 'Найти файлы по части имени.', { query: str('Часть имени файла'), path: str('Где искать (по умолчанию — домашняя папка)'), max_results: num('Максимум результатов') }, ['query']),
  fn('take_screenshot', 'Сделать скриншот экрана, чтобы увидеть, что на нём. Координаты для мыши берутся с этого скриншота.', { display: num('Номер монитора (0 — основной)') }),
  fn('get_screen_info', 'Информация о мониторах (разрешение, масштаб).'),
  fn('get_cursor_position', 'Текущая позиция курсора мыши.'),
  fn('mouse_move', 'Переместить курсор мыши.', { ...XY }, ['x', 'y']),
  fn('mouse_click', 'Кликнуть мышью (если x,y не указаны — в текущей позиции).', { ...XY, button: str('left | right | middle', { enum: ['left', 'right', 'middle'] }), double: bool('Двойной клик') }),
  fn('mouse_scroll', 'Прокрутить колесо мыши. Положительное — вверх, отрицательное — вниз.', { amount: num('Количество щелчков колеса') }, ['amount']),
  fn('mouse_drag', 'Перетащить мышью из одной точки в другую.', { from_x: num('X начала'), from_y: num('Y начала'), to_x: num('X конца'), to_y: num('Y конца') }, ['from_x', 'from_y', 'to_x', 'to_y']),
  fn('type_text', 'Напечатать текст с клавиатуры в активное окно.', { text: str('Текст') }, ['text']),
  fn('press_keys', 'Нажать клавишу или сочетание, например "enter", "ctrl+c", "alt+tab", "win+d", "ctrl+shift+esc".', { keys: str('Сочетание клавиш') }, ['keys']),
  fn('hold_keys', 'Удерживать клавишу или сочетание заданное время — для игр (движение WASD, бег shift+w, прыжок space).', { keys: str('Клавиши, например "w" или "shift+w"'), ms: num('Сколько миллисекунд держать (30–10000)') }, ['keys', 'ms']),
  fn('mouse_move_relative', 'Сдвинуть мышь относительно текущего положения — поворот камеры в 3D-играх.', { dx: num('Сдвиг по X'), dy: num('Сдвиг по Y') }, ['dx', 'dy']),
  fn('ui_list_elements', 'Windows: список кнопок, полей и пунктов меню активного окна с координатами центра. Быстрее и точнее скриншота для обычных программ.', { filter: str('Часть названия для фильтра (необязательно)') }),
  fn('ui_click', 'Windows: нажать на кнопку/пункт/ссылку активного окна по её названию.', { name: str('Название элемента (как в ui_list_elements)') }, ['name']),
  fn('agent_task', 'Передать большую задачу внешнему агенту. Сейчас поддерживается Google Antigravity (ИИ-среда для программирования): Стелла откроет её и вставит задачу в чат агента. Antigravity — отдельный продукт Google, не скрывай это от пользователя.', { agent: str('antigravity', { enum: ['antigravity'] }), task: str('Подробное описание задачи для агента') }, ['agent', 'task']),
  fn('list_windows', 'Список открытых окон.'),
  fn('focus_window', 'Переключиться на окно по части заголовка или имени программы.', { title: str('Заголовок или имя') }, ['title']),
  fn('list_processes', 'Список запущенных процессов (топ по памяти).'),
  fn('kill_process', 'Завершить процесс по PID или имени.', { pid: num('PID'), name: str('Имя процесса (например chrome.exe)') }),
  fn('system_info', 'Сведения о системе: ОС, процессор, память, время работы, пути к папкам пользователя.'),
  fn('clipboard_read', 'Прочитать текст из буфера обмена.'),
  fn('clipboard_write', 'Записать текст в буфер обмена.', { text: str('Текст') }, ['text']),
  fn('notify', 'Показать системное уведомление.', { title: str('Заголовок'), text: str('Текст') }, ['text']),
  fn('set_timer', 'Поставить таймер/напоминание. По истечении ты напомнишь голосом.', { seconds: num('Через сколько секунд'), message: str('О чём напомнить') }, ['seconds', 'message']),
  fn('media_control', 'Управление воспроизведением музыки/видео и громкостью.', { action: str('play_pause | next | previous | stop | volume_up | volume_down | mute', { enum: ['play_pause', 'next', 'previous', 'stop', 'volume_up', 'volume_down', 'mute'] }) }, ['action']),
  fn('set_volume', 'Установить системную громкость 0–100.', { level: num('Громкость 0–100') }, ['level']),
  fn('lock_screen', 'Заблокировать компьютер.'),
  fn('power_action', 'Выключить, перезагрузить, усыпить компьютер или отменить запланированное выключение.', { action: str('shutdown | restart | sleep | logout | cancel', { enum: ['shutdown', 'restart', 'sleep', 'logout', 'cancel'] }), delay_seconds: num('Задержка в секундах (по умолчанию 30)') }, ['action']),
  fn('wait', 'Подождать N секунд (до 30), например пока загрузится программа.', { seconds: num('Секунды') }, ['seconds']),
  fn('get_datetime', 'Текущие дата и время.'),
  fn('remember_fact', 'Запомнить важный факт о пользователе навсегда.', { fact: str('Факт') }, ['fact']),
  fn('play_animation', 'Выполнить движение своим 3D-телом.', { animation: str('wave | dance | nod | shake | think | jump | bow | clap | stretch | spin | point | heart | laugh | shrug | victory | sleepy'), emotion: str('happy | sad | angry | surprised | relaxed | neutral | love | thinking | shy | smug') }, ['animation']),
];

const TOOL_NAMES = TOOL_DEFS.map((t) => t.function.name);

const LABELS = {
  run_command: 'Команда', launch_app: 'Запуск приложения', open_url: 'Открыть ссылку', web_search: 'Поиск в интернете', open_path: 'Открыть файл/папку',
  list_directory: 'Содержимое папки', read_file: 'Чтение файла', write_file: 'Запись файла', create_folder: 'Создание папки', move_path: 'Перемещение',
  copy_path: 'Копирование', delete_path: 'Удаление', search_files: 'Поиск файлов', take_screenshot: 'Скриншот', get_screen_info: 'Экраны',
  get_cursor_position: 'Позиция курсора', mouse_move: 'Движение мыши', mouse_click: 'Клик', mouse_scroll: 'Прокрутка', mouse_drag: 'Перетаскивание',
  type_text: 'Ввод текста', press_keys: 'Клавиши', list_windows: 'Список окон', focus_window: 'Переключение окна', list_processes: 'Процессы',
  kill_process: 'Завершение процесса', system_info: 'Сведения о системе', clipboard_read: 'Чтение буфера', clipboard_write: 'Запись в буфер',
  notify: 'Уведомление', set_timer: 'Таймер', media_control: 'Медиа', set_volume: 'Громкость', lock_screen: 'Блокировка', power_action: 'Питание',
  hold_keys: 'Удержание клавиш', mouse_move_relative: 'Поворот мышью', ui_list_elements: 'Элементы окна', ui_click: 'Нажатие на элемент', agent_task: 'Задача агенту',
  wait: 'Ожидание', get_datetime: 'Дата и время', remember_fact: 'Запоминание', play_animation: 'Движение',
};

const MAX_OUTPUT = 8000;
function truncate(s, n = MAX_OUTPUT) { s = String(s ?? ''); return s.length > n ? s.slice(0, n) + `\n…[обрезано, всего ${s.length} символов]` : s; }

function expandPath(p, home = os.homedir()) {
  if (p === undefined || p === null || p === '') throw new Error('Не указан путь');
  let s = String(p).trim().replace(/^["']|["']$/g, '');
  const aliases = { '~': home, 'рабочий стол': path.join(home, 'Desktop'), desktop: path.join(home, 'Desktop'), 'загрузки': path.join(home, 'Downloads'), downloads: path.join(home, 'Downloads'), 'документы': path.join(home, 'Documents'), documents: path.join(home, 'Documents') };
  const low = s.toLowerCase();
  if (aliases[low]) return aliases[low];
  if (s === '~' || s.startsWith('~/') || s.startsWith('~\\')) s = path.join(home, s.slice(1));
  s = s.replace(/%USERPROFILE%/gi, home).replace(/\$HOME/g, home);
  return path.isAbsolute(s) ? path.normalize(s) : path.resolve(home, s);
}

function fmtSize(n) {
  if (n < 1024) return n + ' Б';
  if (n < 1024 ** 2) return (n / 1024).toFixed(1) + ' КБ';
  if (n < 1024 ** 3) return (n / 1024 ** 2).toFixed(1) + ' МБ';
  return (n / 1024 ** 3).toFixed(2) + ' ГБ';
}

function searchUrl(query, engine = 'google') {
  const q = encodeURIComponent(String(query || '').trim());
  if (!q) throw new Error('Пустой запрос');
  return {
    google: `https://www.google.com/search?q=${q}`, yandex: `https://yandex.ru/search/?text=${q}`, youtube: `https://www.youtube.com/results?search_query=${q}`,
    bing: `https://www.bing.com/search?q=${q}`, duckduckgo: `https://duckduckgo.com/?q=${q}`,
  }[engine] || `https://www.google.com/search?q=${q}`;
}

function validateUrl(url) {
  let u;
  try { u = new URL(String(url).trim()); } catch { try { u = new URL('https://' + String(url).trim()); } catch { throw new Error('Некорректная ссылка'); } }
  if (!['http:', 'https:', 'mailto:'].includes(u.protocol)) throw new Error('Разрешены только http, https и mailto ссылки');
  return u.toString();
}

/**
 * Создаёт исполнитель инструментов.
 * @param {object} deps внедряемые зависимости (для тестов можно подменить)
 */
function createExecutor(deps) {
  const platform = deps.platform || process.platform;
  const home = deps.homedir || os.homedir();
  const fsp = deps.fs;
  const state = { lastShot: null, timers: new Map() };

  async function execBuilt(built, timeoutMs = 20000) {
    const r = await deps.exec(built.cmd, built.args, { timeout: timeoutMs });
    if (r.code && r.code !== 0) {
      const err = (r.stderr || r.stdout || '').trim();
      if (/not found|не найден|ENOENT/i.test(err) || r.code === 'ENOENT') {
        const hint = platform === 'linux' ? ' Установите xdotool/wmctrl (sudo apt install xdotool wmctrl).' : '';
        throw new Error(`Не удалось выполнить ${built.cmd}.${hint} ${err}`.trim());
      }
      throw new Error(err || `Код выхода ${r.code}`);
    }
    return (r.stdout || '').trim();
  }

  function mapXY(x, y) {
    const s = state.lastShot;
    if (!s) return { x: Math.round(x), y: Math.round(y) };
    return { x: Math.round(s.offsetX + x * s.scaleX), y: Math.round(s.offsetY + y * s.scaleY) };
  }

  async function walk(dir, query, max, out, depth = 0, budget = { n: 0 }) {
    if (depth > 7 || out.length >= max || budget.n > 30000) return;
    let entries;
    try { entries = await fsp.readdir(dir, { withFileTypes: true }); } catch { return; }
    for (const e of entries) {
      budget.n++;
      if (out.length >= max) return;
      const full = path.join(dir, e.name);
      if (e.name.toLowerCase().includes(query)) out.push((e.isDirectory() ? '📁 ' : '📄 ') + full);
      if (e.isDirectory() && !e.name.startsWith('.') && !['node_modules', 'AppData', 'Library', '$Recycle.Bin', 'Windows', 'proc', 'sys'].includes(e.name)) {
        await walk(full, query, max, out, depth + 1, budget);
      }
    }
  }

  const handlers = {
    async run_command({ command, cwd }) {
      if (!command || !String(command).trim()) throw new Error('Пустая команда');
      const r = await deps.runShell(String(command), { cwd: cwd ? expandPath(cwd, home) : home, timeout: (deps.getSettings?.().commandTimeout || 60) * 1000 });
      const out = [r.stdout && r.stdout.trim(), r.stderr && r.stderr.trim() ? 'STDERR:\n' + r.stderr.trim() : ''].filter(Boolean).join('\n');
      return `Код выхода: ${r.code ?? 0}${r.timedOut ? ' (превышено время ожидания)' : ''}\n${truncate(out || '(нет вывода)')}`;
    },
    async launch_app({ name }) {
      const n = String(name || '').trim();
      if (!n) throw new Error('Не указано приложение');
      if (platform === 'win32') {
        const script = `$n=${input.psQuote(n)}; try { Start-Process $n -ErrorAction Stop; 'OK' } catch { $l = Get-ChildItem -Path "$env:APPDATA\\Microsoft\\Windows\\Start Menu","$env:ProgramData\\Microsoft\\Windows\\Start Menu" -Recurse -Filter *.lnk -ErrorAction SilentlyContinue | Where-Object { $_.BaseName -like "*$n*" } | Select-Object -First 1; if ($l) { Start-Process $l.FullName; "OK: $($l.BaseName)" } else { $a = Get-StartApps | Where-Object { $_.Name -like "*$n*" } | Select-Object -First 1; if ($a) { Start-Process "shell:AppsFolder\\$($a.AppID)"; "OK: $($a.Name)" } else { 'NOT_FOUND' } } }`;
        const out = await execBuilt({ cmd: 'powershell.exe', args: ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', input.encodePs(script)] });
        if (out.includes('NOT_FOUND')) throw new Error(`Приложение «${n}» не найдено`);
        return `Приложение «${n}» запущено. ${out.replace(/^OK:?\s*/, '')}`.trim();
      }
      if (platform === 'darwin') { await execBuilt({ cmd: 'open', args: ['-a', n] }); return `Приложение «${n}» запущено`; }
      await deps.spawnDetached(n, []);
      return `Приложение «${n}» запущено`;
    },
    async open_url({ url }) { const u = validateUrl(url); await deps.shell.openExternal(u); return `Открыто: ${u}`; },
    async web_search({ query, engine }) { const u = searchUrl(query, engine); await deps.shell.openExternal(u); return `Открыт поиск: ${query}`; },
    async open_path({ path: p }) {
      const full = expandPath(p, home);
      const err = await deps.shell.openPath(full);
      if (err) throw new Error(err);
      return `Открыто: ${full}`;
    },
    async list_directory({ path: p, show_hidden }) {
      const full = expandPath(p, home);
      const entries = await fsp.readdir(full, { withFileTypes: true });
      const rows = [];
      for (const e of entries) {
        if (!show_hidden && e.name.startsWith('.')) continue;
        let size = '';
        if (e.isFile()) { try { size = ' — ' + fmtSize((await fsp.stat(path.join(full, e.name))).size); } catch { /* */ } }
        rows.push((e.isDirectory() ? '📁 ' : '📄 ') + e.name + size);
        if (rows.length >= 300) { rows.push('…(показаны первые 300)'); break; }
      }
      rows.sort((a, b) => (a.startsWith('📁') === b.startsWith('📁') ? a.localeCompare(b) : a.startsWith('📁') ? -1 : 1));
      return `${full}\n${rows.join('\n') || '(папка пуста)'}`;
    },
    async read_file({ path: p }) {
      const full = expandPath(p, home);
      const st = await fsp.stat(full);
      if (st.isDirectory()) throw new Error('Это папка, используйте list_directory');
      if (st.size > 1024 * 1024 * 20) throw new Error(`Файл слишком большой (${fmtSize(st.size)})`);
      const buf = await fsp.readFile(full);
      if (buf.subarray(0, 8000).includes(0)) return `Двоичный файл (${fmtSize(st.size)}), содержимое не показано.`;
      return truncate(buf.toString('utf8'), 100000);
    },
    async write_file({ path: p, content, append }) {
      const full = expandPath(p, home);
      await fsp.mkdir(path.dirname(full), { recursive: true });
      if (append) await fsp.appendFile(full, String(content ?? ''), 'utf8');
      else await fsp.writeFile(full, String(content ?? ''), 'utf8');
      return `${append ? 'Дописано в' : 'Сохранено'}: ${full} (${Buffer.byteLength(String(content ?? ''))} байт)`;
    },
    async create_folder({ path: p }) { const full = expandPath(p, home); await fsp.mkdir(full, { recursive: true }); return `Папка создана: ${full}`; },
    async move_path({ source, destination }) {
      const s = expandPath(source, home), d = expandPath(destination, home);
      await fsp.mkdir(path.dirname(d), { recursive: true });
      await fsp.rename(s, d);
      return `Перемещено: ${s} → ${d}`;
    },
    async copy_path({ source, destination }) {
      const s = expandPath(source, home), d = expandPath(destination, home);
      await fsp.mkdir(path.dirname(d), { recursive: true });
      await fsp.cp(s, d, { recursive: true, errorOnExist: false });
      return `Скопировано: ${s} → ${d}`;
    },
    async delete_path({ path: p }) {
      const full = expandPath(p, home);
      await fsp.stat(full);
      await deps.shell.trashItem(full);
      return `Перемещено в корзину: ${full}`;
    },
    async search_files({ query, path: p, max_results }) {
      const q = String(query || '').toLowerCase().trim();
      if (!q) throw new Error('Пустой запрос');
      const root = p ? expandPath(p, home) : home;
      const out = [];
      await walk(root, q, Math.min(Number(max_results) || 30, 200), out);
      return out.length ? `Найдено ${out.length}:\n${out.join('\n')}` : `Ничего не найдено по «${query}» в ${root}`;
    },
    async take_screenshot({ display } = {}) {
      const shot = await deps.screenshot(Number(display) || 0);
      const factor = platform === 'darwin' ? 1 : shot.scaleFactor;
      state.lastShot = {
        scaleX: (shot.bounds.width * factor) / shot.width,
        scaleY: (shot.bounds.height * factor) / shot.height,
        offsetX: shot.bounds.x * factor, offsetY: shot.bounds.y * factor,
      };
      return { text: `Скриншот ${shot.width}×${shot.height}. Указывай координаты мыши в пикселях этого изображения.`, image: shot.dataUrl };
    },
    async get_screen_info() {
      const d = await deps.screenInfo();
      return d.map((s, i) => `Монитор ${i}${s.primary ? ' (основной)' : ''}: ${s.bounds.width}×${s.bounds.height}, масштаб ${s.scaleFactor}, позиция ${s.bounds.x},${s.bounds.y}`).join('\n');
    },
    async get_cursor_position() { const p = await deps.cursorPosition(); return `Курсор: ${p.x}, ${p.y} (экранные координаты)`; },
    async mouse_move({ x, y }) { const p = mapXY(x, y); await execBuilt(input.buildMouseMove(platform, p.x, p.y)); return `Курсор перемещён в ${x}, ${y}`; },
    async mouse_click({ x, y, button = 'left', double = false }) {
      const p = x !== undefined && y !== undefined ? mapXY(x, y) : {};
      await execBuilt(input.buildClick(platform, { ...p, button, double }));
      return `${double ? 'Двойной клик' : 'Клик'} (${button})${x !== undefined ? ` в ${x}, ${y}` : ''}`;
    },
    async mouse_scroll({ amount }) { await execBuilt(input.buildScroll(platform, amount)); return `Прокручено на ${amount}`; },
    async mouse_drag({ from_x, from_y, to_x, to_y }) {
      await execBuilt(input.buildDrag(platform, mapXY(from_x, from_y), mapXY(to_x, to_y)));
      return `Перетащено из ${from_x},${from_y} в ${to_x},${to_y}`;
    },
    async type_text({ text }) { await execBuilt(input.buildTypeText(platform, text), 60000); return `Напечатано ${String(text).length} символов`; },
    async press_keys({ keys }) { await execBuilt(input.buildKeyCombo(platform, keys)); return `Нажато: ${keys}`; },
    async hold_keys({ keys, ms }) { await execBuilt(input.buildHoldKeys(platform, keys, ms), 15000); return `Удерживала ${keys} ${ms} мс`; },
    async mouse_move_relative({ dx, dy }) { await execBuilt(input.buildMouseRelative(platform, dx, dy)); return `Мышь сдвинута на ${dx}, ${dy}`; },
    async ui_list_elements({ filter } = {}) { const out = await execBuilt(input.buildUiList(platform, filter), 30000); return truncate(out || 'Элементы не найдены') + '\nКоординаты — экранные пиксели; для клика используйте ui_click по названию.'; },
    async ui_click({ name }) {
      const out = await execBuilt(input.buildUiClick(platform, name), 30000);
      if (out.includes('NOT_FOUND')) throw new Error(`Элемент «${name}» не найден в активном окне. Посмотрите список через ui_list_elements.`);
      return out.replace('INVOKED: ', 'Нажато: ').replace('CLICKED: ', 'Клик по: ');
    },
    async agent_task({ agent = 'antigravity', task }) {
      if (agent !== 'antigravity') throw new Error('Неизвестный агент');
      if (!String(task || '').trim()) throw new Error('Пустая задача');
      try { await handlers.launch_app({ name: 'Antigravity' }); }
      catch { throw new Error('Antigravity не установлена. Предложи пользователю открыть Мастерская → Агенты и установить её (antigravity.google).'); }
      await new Promise((r) => setTimeout(r, 6000));
      try { await execBuilt(input.buildFocusWindow(platform, 'Antigravity')); } catch { /* окно могло уже быть активным */ }
      deps.clipboard.writeText(String(task));
      await execBuilt(input.buildKeyCombo(platform, platform === 'darwin' ? 'cmd+l' : 'ctrl+l'));
      await new Promise((r) => setTimeout(r, 800));
      await execBuilt(input.buildKeyCombo(platform, platform === 'darwin' ? 'cmd+v' : 'ctrl+v'));
      await new Promise((r) => setTimeout(r, 300));
      await execBuilt(input.buildKeyCombo(platform, 'enter'));
      return 'Antigravity открыта, задача вставлена в панель агента (Ctrl+L) и отправлена. Проверь скриншотом, что агент начал работу; если панель не открылась — нажми на поле чата агента и вставь задачу (она в буфере обмена).';
    },
    async list_windows() { return truncate(await execBuilt(input.buildListWindows(platform))) || 'Окон не найдено'; },
    async focus_window({ title }) {
      const out = await execBuilt(input.buildFocusWindow(platform, title));
      if (out.includes('NOT_FOUND')) throw new Error(`Окно «${title}» не найдено`);
      return `Переключено на «${title}»`;
    },
    async list_processes() {
      if (platform === 'win32') {
        const out = await execBuilt({ cmd: 'powershell.exe', args: ['-NoProfile', '-Command', 'Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 50 Id, ProcessName, @{n="MB";e={[math]::Round($_.WorkingSet64/1MB)}} | Format-Table -AutoSize | Out-String -Width 200'] });
        return truncate(out);
      }
      const out = await execBuilt({ cmd: 'ps', args: platform === 'darwin' ? ['-Ao', 'pid,pcpu,pmem,comm', '-m'] : ['-eo', 'pid,pcpu,pmem,comm', '--sort=-pmem'] });
      return truncate(out.split('\n').slice(0, 51).join('\n'));
    },
    async kill_process({ pid, name }) {
      if (pid) { deps.killPid(Number(pid)); return `Процесс ${pid} завершён`; }
      if (!name) throw new Error('Укажите pid или name');
      const n = String(name);
      if (platform === 'win32') await execBuilt({ cmd: 'taskkill', args: ['/IM', n.endsWith('.exe') ? n : n + '.exe', '/F'] });
      else await execBuilt({ cmd: 'pkill', args: ['-f', n] });
      return `Процесс «${n}» завершён`;
    },
    async system_info() {
      const cpus = os.cpus();
      return [
        `ОС: ${os.type()} ${os.release()} (${platform}, ${os.arch()})`,
        `Компьютер: ${os.hostname()}, пользователь: ${os.userInfo().username}`,
        `Процессор: ${cpus[0]?.model || '?'} × ${cpus.length}`,
        `Память: свободно ${fmtSize(os.freemem())} из ${fmtSize(os.totalmem())}`,
        `Время работы: ${Math.floor(os.uptime() / 3600)} ч ${Math.floor((os.uptime() % 3600) / 60)} мин`,
        `Домашняя папка: ${home}`,
        `Рабочий стол: ${path.join(home, 'Desktop')}`,
        `Документы: ${path.join(home, 'Documents')}`,
        `Загрузки: ${path.join(home, 'Downloads')}`,
      ].join('\n');
    },
    async clipboard_read() { const t = deps.clipboard.readText(); return t ? truncate(t) : '(буфер обмена пуст)'; },
    async clipboard_write({ text }) { deps.clipboard.writeText(String(text ?? '')); return 'Текст скопирован в буфер обмена'; },
    async notify({ title, text }) { deps.notify(title || 'Стелла', String(text)); return 'Уведомление показано'; },
    async set_timer({ seconds, message }) {
      const s = Number(seconds);
      if (!Number.isFinite(s) || s <= 0 || s > 7 * 24 * 3600) throw new Error('Время таймера: от 1 секунды до 7 дней');
      const id = 't' + Date.now().toString(36);
      const h = setTimeout(() => { state.timers.delete(id); deps.onTimer?.(String(message || 'Время вышло!')); }, s * 1000);
      if (h.unref) h.unref();
      state.timers.set(id, h);
      const when = new Date(Date.now() + s * 1000);
      return `Таймер установлен на ${when.toLocaleTimeString('ru-RU')}: «${message}»`;
    },
    async media_control({ action }) { await execBuilt(input.buildMedia(platform, action)); return `Медиа: ${action}`; },
    async set_volume({ level }) { await execBuilt(input.buildSetVolume(platform, level), 30000); return `Громкость: ${level}%`; },
    async lock_screen() {
      const b = platform === 'win32' ? { cmd: 'rundll32.exe', args: ['user32.dll,LockWorkStation'] }
        : platform === 'darwin' ? { cmd: 'pmset', args: ['displaysleepnow'] } : { cmd: 'loginctl', args: ['lock-session'] };
      await execBuilt(b); return 'Компьютер заблокирован';
    },
    async power_action({ action, delay_seconds }) {
      const d = Math.max(0, Math.round(Number(delay_seconds ?? 30)));
      const map = {
        win32: { shutdown: ['shutdown', ['/s', '/t', String(d)]], restart: ['shutdown', ['/r', '/t', String(d)]], sleep: ['rundll32.exe', ['powrprof.dll,SetSuspendState', '0,1,0']], logout: ['shutdown', ['/l']], cancel: ['shutdown', ['/a']] },
        darwin: { shutdown: ['osascript', ['-e', 'tell app "System Events" to shut down']], restart: ['osascript', ['-e', 'tell app "System Events" to restart']], sleep: ['pmset', ['sleepnow']], logout: ['osascript', ['-e', 'tell app "System Events" to log out']], cancel: ['killall', ['shutdown']] },
        linux: { shutdown: ['shutdown', ['-h', `+${Math.ceil(d / 60)}`]], restart: ['shutdown', ['-r', `+${Math.ceil(d / 60)}`]], sleep: ['systemctl', ['suspend']], logout: ['loginctl', ['terminate-user', os.userInfo().username]], cancel: ['shutdown', ['-c']] },
      }[platform] || {};
      const c = map[action];
      if (!c) throw new Error('Неизвестное действие питания');
      await execBuilt({ cmd: c[0], args: c[1] });
      return { cancel: 'Выключение отменено', shutdown: `Выключение через ${d} с`, restart: `Перезагрузка через ${d} с`, sleep: 'Спящий режим', logout: 'Выход из системы' }[action];
    },
    async wait({ seconds }) { const s = Math.min(30, Math.max(0, Number(seconds) || 1)); await new Promise((r) => setTimeout(r, s * 1000)); return `Подождала ${s} с`; },
    async get_datetime() { const n = deps.now ? deps.now() : new Date(); return n.toLocaleString('ru-RU', { dateStyle: 'full', timeStyle: 'medium' }); },
    async remember_fact({ fact }) { deps.store.addMemory(fact); deps.onMemory?.(); return `Запомнила: ${fact}`; },
    async play_animation({ animation, emotion }) { deps.avatar?.({ animation, emotion }); return `Выполняю: ${animation}`; },
  };

  async function execute(name, args = {}) {
    const h = handlers[name];
    if (!h) return { ok: false, output: `Неизвестный инструмент: ${name}` };
    try {
      const res = await h(args || {});
      if (res && typeof res === 'object') return { ok: true, output: res.text, image: res.image };
      return { ok: true, output: String(res ?? 'Готово') };
    } catch (e) {
      return { ok: false, output: `Ошибка: ${e.message || e}` };
    }
  }

  return { execute, handlers, state, mapXY, cancelTimers: () => { for (const h of state.timers.values()) clearTimeout(h); state.timers.clear(); } };
}

module.exports = { TOOL_DEFS, TOOL_NAMES, LABELS, createExecutor, expandPath, searchUrl, validateUrl, truncate, fmtSize };

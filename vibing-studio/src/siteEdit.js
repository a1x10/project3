/**
 * Editing an existing site instead of regenerating it.
 *
 * The model answers with SEARCH/REPLACE and INSERT_* blocks:
 *   <<<<<<< SEARCH | INSERT_AFTER | INSERT_BEFORE
 *   anchor / old code
 *   =======
 *   new code
 *   >>>>>>> REPLACE | END
 * We parse them, apply them to the current HTML and keep a per-block result.
 */

const OPEN = /^<{5,9}[ \t]*(SEARCH|INSERT_AFTER|INSERT_BEFORE)[ \t]*$/;
const MID = /^={5,9}[ \t]*$/;
const CLOSE = /^>{5,9}[ \t]*(?:REPLACE|END)?[ \t]*$/;

const trimNl = (s) => s.replace(/^\n+|\n+$/g, "");

export function parseEdits(raw) {
  // models like to wrap blocks in ``` fences: drop those fences
  const text = raw
    .replace(/^[ \t]*```[\w-]*[ \t]*\n(?=<{5,9}[ \t]*(?:SEARCH|INSERT_AFTER|INSERT_BEFORE))/gm, "")
    .replace(/(^>{5,9}[ \t]*(?:REPLACE|END)?[ \t]*)\n[ \t]*```[ \t]*$/gm, "$1");

  const segs = [];
  const blocks = [];
  let buf = [];
  let state = "text";
  let cur = null;

  const flush = () => {
    const t = buf.join("\n");
    if (t.trim()) segs.push({ type: "text", text: t });
    buf = [];
  };
  const seal = (complete) => {
    cur.search = trimNl(cur.searchL.join("\n"));
    cur.replace = trimNl(cur.replL.join("\n"));
    cur.complete = complete;
    delete cur.searchL;
    delete cur.replL;
    segs.push(cur);
    if (complete) blocks.push(cur);
    cur = null;
  };

  for (const line of text.split("\n")) {
    if (state === "text") {
      const m = OPEN.exec(line);
      if (m) {
        flush();
        cur = { type: "edit", op: m[1], searchL: [], replL: [] };
        state = "search";
      } else buf.push(line);
    } else if (state === "search") {
      if (MID.test(line)) state = "repl";
      else cur.searchL.push(line);
    } else if (CLOSE.test(line)) {
      seal(true);
      state = "text";
    } else cur.replL.push(line);
  }
  const open = !!cur;
  if (cur) seal(false);
  else flush();
  return { segs, blocks, open };
}

/** Whitespace-insensitive search: compares only non-space characters. */
function stripMap(s) {
  let out = "";
  const map = [];
  for (let i = 0; i < s.length; i++) {
    if (!/\s/.test(s[i])) {
      out += s[i];
      map.push(i);
    }
  }
  return { out, map };
}

function findSpan(doc, search) {
  if (!search || !search.trim()) return null;
  for (const s of [search, search.trim()]) {
    const i = doc.indexOf(s);
    if (i >= 0) return { start: i, end: i + s.length, how: "exact", many: doc.indexOf(s, i + 1) >= 0 };
  }
  const needle = search.replace(/\s+/g, "");
  const { out, map } = stripMap(doc);
  const j = out.indexOf(needle);
  if (j < 0) return null;
  return {
    start: map[j],
    end: map[j + needle.length - 1] + 1,
    how: "fuzzy",
    many: out.indexOf(needle, j + 1) >= 0,
  };
}

/** [[CODE_1]] -> the exact code the user pasted. */
export function expandCode(text, codes) {
  return text.replace(/\[\[\s*CODE_(\d+)\s*\]\]/g, (m, n) => (codes[n - 1] !== undefined ? codes[n - 1] : m));
}

export function applyEdits(doc, blocks, codes = []) {
  let out = doc;
  const results = [];
  for (const b of blocks) {
    const repl = expandCode(b.replace, codes);
    const span = findSpan(out, b.search);
    if (!span) {
      results.push({ ok: false });
      continue;
    }
    if (b.op === "INSERT_AFTER") out = out.slice(0, span.end) + "\n" + repl + out.slice(span.end);
    else if (b.op === "INSERT_BEFORE") out = out.slice(0, span.start) + repl + "\n" + out.slice(span.start);
    else out = out.slice(0, span.start) + repl + out.slice(span.end);
    results.push({ ok: true, how: span.how, many: span.many });
  }
  return { doc: out, results };
}

/** Shrink a big page so it fits the model context (comments, indentation, blank lines). */
export function compactHtml(html) {
  return html
    .replace(/<!--[\s\S]*?-->/g, "")
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .join("\n");
}

/**
 * Long code blocks the user pasted are replaced with [[CODE_n]] in the prompt
 * (saves context and guarantees the code is inserted byte-for-byte).
 */
export function protectUserCode(content, limit = 600) {
  const codes = [];
  const text = content.replace(/```([\w+-]*)[ \t]*\n([\s\S]*?)```/g, (m, lang, code) => {
    code = code.replace(/\n$/, "");
    if (code.length < limit) return m;
    codes.push(code);
    const lines = code.split("\n");
    return (
      `[[CODE_${codes.length}]] (${lang || "код"}, ${lines.length} строк, начало:\n` +
      lines.slice(0, 6).join("\n") +
      "\n…)"
    );
  });
  return { text, codes };
}

/** Keyless photo source for the model: any English keyword gives a real photo. */
export const IMAGE_RULES =
  "КАРТИНКИ: никогда не пиши заглушки вроде [Место для картинки]. Вставляй реальные <img> с адресом " +
  "https://loremflickr.com/ШИРИНА/ВЫСОТА/ключевое-слово?lock=N (ключевое слово по-английски, например coffee, office, mountain; " +
  "у каждой картинки свой номер N, чтобы фото не повторялись), например " +
  "<img src=\"https://loremflickr.com/800/600/coffee?lock=1\" alt=\"Кофе\" class=\"w-full h-64 object-cover\" loading=\"lazy\">. " +
  "Если пользователь дал список своих картинок — используй ИХ адреса.";

/** Text put in front of the user's request: the picked element and the attached photos. */
export function buildContext({ selected = "", images = [] }) {
  let out = "";
  if (selected) {
    const code = compactHtml(selected).slice(0, 1500);
    out += `Я хочу изменить этот блок страницы (правь именно его):\n\`\`\`html\n${code}\n\`\`\`\n\n`;
  }
  if (images.length) {
    out +=
      "Мои картинки (вставляй в <img> эти адреса вместо заглушек):\n" +
      images.map((im, i) => `${i + 1}. ${im.url} — ${im.alt || "фото"}`).join("\n") +
      "\n\n";
  }
  return out;
}

const EDIT_RULES = `Ты — экспертный редактор сайта. Ниже ТЕКУЩИЙ код сайта. Пользователь просит что-то изменить. НЕ переписывай сайт целиком — выдай только точечные правки блоками.

Если в сайте еще нет Tailwind или Lucide, ты можешь добавить их в <head> через блоки вставки.

Замена:
<<<<<<< SEARCH
точный фрагмент из текущего кода
=======
новый код
>>>>>>> REPLACE

Вставка после или перед найденной строкой:
<<<<<<< INSERT_AFTER
строка-якорь из текущего кода
=======
код для вставки
>>>>>>> END

Правила:
1. Используй Tailwind CSS для стилизации, если это уместно.
2. Иконки Lucide добавляй так: <i data-lucide="имя-иконки"></i>.
3. Фрагмент в SEARCH и якорь копируй из текущего кода дословно.
4. Пустая часть после ======= в блоке SEARCH означает удаление.
5. Новый CSS вставляй перед </style> (или создай его), новый JS — перед </body>.
5а. Tailwind подключай так: <script src="https://cdn.tailwindcss.com"></script> (INSERT_BEFORE на </head>). Lucide: <script src="https://unpkg.com/lucide@latest"></script> в <head>, а перед </body> добавь <script>lucide.createIcons();</script>. Если Lucide уже есть, а иконки добавлены новые — убедись, что lucide.createIcons() вызывается в конце.
5б. ${IMAGE_RULES}
6. Сохраняй атрибуты data-v* и style с translate/width — это ручные правки пользователя.
7. Если правок много, старайся объединять их логически.
После правок добавь 1-2 предложения о том, что изменено.`;


export function buildEditSystem(site, requests) {
  const hist = requests.length ? "\n\nРанее пользователь просил:\n" + requests.map((r, i) => `${i + 1}. ${r}`).join("\n") : "";
  return `${EDIT_RULES}${hist}\n\nТЕКУЩИЙ КОД САЙТА:\n\`\`\`html\n${site}\n\`\`\``;
}
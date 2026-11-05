// Prompts and parsing for the 3D Pro mode: the model only picks a template and writes content + palette as JSON.
import { FONTS, ICONS, SECTION_IDS, normalizeSpec } from "./render.js";
import { TEMPLATES_3D } from "./templates3d.js";

const SCHEMA = `{
  "template": "id шаблона из списка",
  "font": "необязательно: ${Object.keys(FONTS).join(" | ")}",
  "palette": { "bg": "#hex фон", "surface": "#hex карточки", "text": "#hex текст", "muted": "#hex второстепенный текст", "accent": "#hex главный акцент", "accent2": "#hex второй акцент" },
  "brand": "название",
  "hero": { "eyebrow": "короткая плашка над заголовком", "title": "сильный заголовок 3–7 слов", "highlight": "1–3 слова из title, которые подсветить градиентом", "subtitle": "1–2 предложения выгоды", "cta": "главная кнопка", "cta2": "вторая кнопка" },
  "stats": [{ "value": "12 000+", "label": "клиентов" }],
  "features": { "title": "", "subtitle": "", "items": [{ "icon": "имя иконки", "title": "", "text": "" }] },
  "showcase": { "title": "", "text": "", "items": [{ "tag": "", "title": "", "text": "" }] },
  "steps": { "title": "", "items": [{ "title": "", "text": "" }] },
  "testimonials": { "title": "", "items": [{ "quote": "", "name": "", "role": "" }] },
  "pricing": { "title": "", "subtitle": "", "plans": [{ "name": "", "price": "", "period": "/мес", "features": [""], "cta": "", "featured": false }] },
  "faq": { "title": "", "items": [{ "q": "", "a": "" }] },
  "cta": { "title": "", "text": "", "button": "" },
  "contact": { "title": "", "email": "", "phone": "", "address": "", "hours": "" },
  "footer": { "text": "" },
  "sections": ["порядок секций из: ${SECTION_IDS.join(", ")}"]
}`;

const catalog = () => TEMPLATES_3D.map((t) => `- ${t.id} — ${t.name}: ${t.desc} Подходит для: ${t.bestFor}.`).join("\n");

const RULES =
  "Правила:\n" +
  "• Выбери ОДИН шаблон, который лучше всего подходит под нишу (смотри «Подходит для»). Дизайн, 3D и анимации уже готовы — ты пишешь только тексты и подбираешь цвета.\n" +
  "• Тексты — на языке пользователя, живые и конкретные, под его бизнес: цифры, выгоды, реальные формулировки. Без «Lorem ipsum», без плейсхолдеров и без выдуманных громких брендов-клиентов.\n" +
  "• Если пользователь назвал название, город, телефон, цены — используй их точно. Чего не знаешь — пиши правдоподобно, но нейтрально.\n" +
  "• Палитра: 6 цветов в #hex, гармоничных нише. Тёмный фон для технологий, ночных и премиальных тем; светлый — для медицины, детских, «чистых» тем. Текст должен хорошо читаться на фоне. Если пользователь назвал цвета — используй их.\n" +
  "• Включай только нужные секции (sections), 5–8 штук. Нет цен — не добавляй pricing. Иконки — только из списка.\n" +
  "• features: 3 или 6 пунктов; stats: 3–4; testimonials: 2–3; faq: 2–5.\n" +
  "• Ответь ТОЛЬКО JSON в блоке ```json ... ``` и после него одно короткое предложение, что сделано.";

export function buildProCreatePrompt() {
  return (
    "Ты — арт-директор веб-студии. Пользователь описывает сайт, а ты собираешь его из профессиональных 3D-шаблонов.\n\n" +
    "Шаблоны:\n" + catalog() + "\n\n" +
    "Иконки: " + ICONS.join(", ") + "\n\n" +
    "Формат ответа:\n" + SCHEMA + "\n\n" + RULES
  );
}

export function buildProEditPrompt(spec) {
  const { palette, ...rest } = spec;
  const pal = Object.fromEntries(["bg", "surface", "text", "muted", "accent", "accent2"].map((k) => [k, palette[k]]));
  return (
    "Ты — арт-директор веб-студии. Сайт собран из 3D-шаблона; ты меняешь его по просьбе пользователя, редактируя JSON.\n\n" +
    "Шаблоны (можно сменить, если пользователь просит другой стиль):\n" + catalog() + "\n\n" +
    "Иконки: " + ICONS.join(", ") + "\n\n" +
    "ТЕКУЩИЙ JSON САЙТА:\n```json\n" + JSON.stringify({ ...rest, palette: pal }, null, 1) + "\n```\n\n" +
    "Измени ТОЛЬКО то, о чём просят (тексты, цвета, секции, шаблон, шрифт), остальное оставь как есть. " +
    "Верни ПОЛНЫЙ обновлённый JSON в блоке ```json ... ``` и одно короткое предложение, что изменено.\n\n" + RULES
  );
}

/** Pull the JSON object out of a model answer (```json fence, any fence, or the outermost braces). */
export function extractJson(text) {
  const src = String(text || "").replace(/<think>[\s\S]*?(<\/think>|$)/g, "");
  const fences = [...src.matchAll(/```(?:json)?\s*\n?([\s\S]*?)```/g)].map((m) => m[1]);
  const candidates = [...fences];
  const a = src.indexOf("{");
  const b = src.lastIndexOf("}");
  if (a >= 0 && b > a) candidates.push(src.slice(a, b + 1));
  for (const c of candidates) {
    const obj = tryParse(c);
    if (obj && typeof obj === "object" && !Array.isArray(obj)) return obj;
  }
  return null;
}

function tryParse(s) {
  try {
    return JSON.parse(s);
  } catch {
    // common model slips: trailing commas, comments
    try {
      return JSON.parse(s.replace(/\/\/[^\n"]*$/gm, "").replace(/,\s*([}\]])/g, "$1"));
    } catch {
      return null;
    }
  }
}

/** Text after the JSON block, shown in the chat as the assistant's comment. */
export function commentAfterJson(text) {
  const src = String(text || "").replace(/<think>[\s\S]*?(<\/think>|$)/g, "");
  const i = src.lastIndexOf("```");
  const tail = i >= 0 ? src.slice(i + 3) : "";
  return tail.trim().slice(0, 400);
}

/** Model answer → normalized spec (AI specs never fall back to demo content), or null. */
export function specFromAnswer(text) {
  const obj = extractJson(text);
  if (!obj || (!obj.hero && !obj.brand && !obj.template)) return null;
  return normalizeSpec(obj, { demo: false });
}

// Собирает презентацию Stella Pocket Rescue в стиле Apple: 20 слайдов, заметки докладчика
// и список анимаций (anim.json), который потом дописывает в слайды animate.py.
//
// Запуск: node presentation/build.js   (картинки готовит presentation/assets.py)
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");
const { applyTheme } = require(process.env.PPTX_SKILL
  ? path.join(process.env.PPTX_SKILL, "scripts/apply_theme.js")
  : "/root/.claude/skills/synced/662e4784-4c20-48f8-85e8-dc71af5298bd_09b862a5-2b59-424a-8131-aabad5feb501/pptx/scripts/apply_theme.js");

const A = (f) => path.join(__dirname, "assets", f);
const OUT = path.join(__dirname, "Stella_Pocket_Rescue.pptx");

const THEME = {
  name: "Stella Keynote",
  headFontFace: "Arial",
  bodyFontFace: "Arial",
  colors: {
    dk1: "000000", lt1: "FFFFFF", dk2: "1C1C1E", lt2: "F5F5F7",
    accent1: "FF453A", accent2: "FF9F0A", accent3: "30D158", accent4: "0A84FF", accent5: "BF5AF2", accent6: "86868B",
    hlink: "0A84FF", folHlink: "BF5AF2",
  },
};

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "Stella Pocket Rescue";
pres.author = "Моисеев Алексей";
const C = pres.SchemeColor;
const INK = C.background2, GRAY = C.accent6, CARD = C.text2;
const RED = C.accent1, ORANGE = C.accent2, GREEN = C.accent3, BLUE = C.accent4, VIOLET = C.accent5;
const W = 13.333, M = 0.75;

pres.defineSlideMaster({
  title: "Темный",
  background: { color: "000000" },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: M, y: 0.55, w: W - 2 * M, h: 0.95,
    fontFace: "Arial", fontSize: 40, bold: true, color: INK, align: "left", valign: "top", margin: 0 }, text: "" } }],
});
pres.defineSlideMaster({ title: "Сцена", background: { color: "000000" } });

const ANIM = []; // по слайду: [[ [имя, эффект], ... ], ...] шаги появления
let slide, steps, n = 0;

function newSlide(master, section, notes, bg) {
  if (section) pres.addSection({ title: section });
  slide = pres.addSlide({ masterName: master, sectionTitle: section || currentSection });
  if (section) currentSection = section;
  steps = [];
  ANIM.push(steps);
  n += 1;
  if (bg) slide.addImage({ path: A(bg), x: 0, y: 0, w: W, h: 7.5, objectName: "!!bg", altText: "Фон" });
  slide.addNotes(notes);
}
let currentSection = "";

// имя объекта уникально в пределах слайда; "!!" делает его общим для перехода «Трансформация»
let uid = 0;
const nm = (base) => `${base}_${++uid}`;
function step(...items) { steps.push(items); }

function text(t, o) {
  const name = o.name || nm("t");
  slide.addText(t, { isTextBox: true, margin: 0, fontFace: "Arial", color: INK, valign: "top", ...o, objectName: name, name: undefined });
  return name;
}
const ALT = { "box.png": "Коробка Stella Pocket Rescue", "box_exploded.png": "Корпус коробки в разобранном виде",
  "phone_chat.png": "Чат пострадавшего на телефоне", "win_console.png": "Консоль спасателя", "win_dossier.png": "Досье вызова в консоли спасателя" };
function img(file, o) {
  const name = o.name || nm("img");
  const altText = ALT[file] || (file.startsWith("bg_") ? "Фон" : "Иконка");
  slide.addImage({ path: A(file), altText, ...o, objectName: name, name: undefined });
  return name;
}
function rrect(o) {
  const name = o.name || nm("card");
  slide.addShape(pres.ShapeType.roundRect, { rectRadius: 0.22, fill: { color: CARD }, line: { color: CARD, width: 0 }, ...o, objectName: name, name: undefined });
  return name;
}
function circle(o) {
  const name = o.name || nm("dot");
  slide.addShape(pres.ShapeType.ellipse, { line: { color: CARD, width: 0 }, ...o, objectName: name, name: undefined });
  return name;
}
// иконка в цветном круге: возвращает имена круга и иконки
function badge(icon, x, y, d, color, tint = 40) {
  const c = circle({ x, y, w: d, h: d, fill: { color, transparency: tint } });
  const k = d * 0.56;
  const i = img(`i_${icon}.png`, { x: x + (d - k) / 2, y: y + (d - k) / 2, w: k, h: k });
  return [c, i];
}
function title(t) { slide.addText(t, { placeholder: "title" }); }
function eyebrow(t, color, o = {}) { return text(t, { x: M, y: 0.8, w: 8, h: 0.4, fontSize: 18, bold: true, color, ...o }); }

const BOX_RATIO = 566 / 830, PHONE_RATIO = 912 / 1852, WIN_C = 1091 / 1600, WIN_D = 1065 / 1600, EXPL_RATIO = 659 / 665;

// 1. Титул
newSlide("Сцена", "Начало",
  "Здравствуйте! Меня зовут Алексей Моисеев, я учусь в 7 «В» классе школы №70. Мой проект называется Stella Pocket Rescue. " +
  "Это небольшая коробка, через которую пострадавшие могут написать спасателям, даже когда нет интернета и мобильной связи.",
  "bg_red.jpg");
const s1e = eyebrow("Научный проект · 2026", ORANGE, { y: 1.25 });
const s1t = text([{ text: "Stella Pocket", options: { breakLine: true } }, { text: "Rescue", options: { color: RED } }],
  { x: M, y: 1.75, w: 6.9, h: 2.4, fontSize: 66, bold: true, lineSpacingMultiple: 0.9 });
const s1s = text("Автономный узел связи с искусственным интеллектом для помощи пострадавшим при ЧС",
  { x: M, y: 4.25, w: 6.6, h: 1.0, fontSize: 20, color: GRAY });
const s1b = img("box.png", { x: 7.45, y: 1.95, w: 5.3, h: 5.3 * BOX_RATIO, name: "!!box" });
const s1a = text([
  { text: "Моисеев Алексей Михайлович, 7 «В» класс", options: { color: INK, bold: true, breakLine: true } },
  { text: "Научный руководитель: Альбина Манатовна", options: { breakLine: true } },
  { text: "КГУ «Общеобразовательная школа №70», Алматы" }],
  { x: M, y: 5.75, w: 7.5, h: 1.1, fontSize: 15, color: GRAY, lineSpacingMultiple: 1.15 });
step([s1e, "fade"], [s1t, "rise"]); step([s1s, "fade"]); step([s1b, "zoom"]); step([s1a, "fade"]);

// 2. Заявление
newSlide("Сцена", "Проблема",
  "Представьте землетрясение. Дома повреждены, люди могут оказаться под завалами. И почти сразу пропадает связь: " +
  "вышки не работают, интернета нет. Человек рядом, но сообщить о себе не может.", "bg_dim.jpg");
const s2a = text("Когда земля трясется,", { x: M, y: 2.35, w: 11.8, h: 1.2, fontSize: 60, bold: true });
const s2b = text("первой пропадает связь.", { x: M, y: 3.55, w: 11.8, h: 1.2, fontSize: 60, bold: true, color: RED });
step([s2a, "rise"]); step([s2b, "rise"]);

// 3. Проблема
newSlide("Темный", null,
  "Из-за этого появляются три проблемы. Первая: связь пропадает. Вторая: никто не знает, где человек и что с ним. " +
  "Третья: спасатели не знают, кому помогать первым, ведь вызовов может быть много.", "bg_dim.jpg");
title("Проблема");
[["tower_off", RED, "Связь пропадает", "Вышки и интернет часто перестают работать первыми."],
 ["pin_question", ORANGE, "Никто не знает, где вы", "Человек под завалами не может сообщить, где он и что случилось."],
 ["queue", BLUE, "Кому помогать первым", "Спасатели не знают, где хуже всего и кого искать в первую очередь."]]
  .forEach(([icon, col, h, t], i) => {
    const x = M + i * 4.05;
    const card = rrect({ x, y: 2.0, w: 3.75, h: 3.85 });
    const [c, ic] = badge(icon, x + 0.4, 2.4, 1.0, col);
    const hh = text(h, { x: x + 0.4, y: 3.7, w: 3.0, h: 0.9, fontSize: 24, bold: true });
    const tt = text(t, { x: x + 0.4, y: 4.65, w: 3.0, h: 1.4, fontSize: 17, color: GRAY });
    step([card, "rise"], [c, "rise"], [ic, "rise"], [hh, "rise"], [tt, "rise"]);
  });

// 4. Цель
newSlide("Сцена", "Исследование",
  "Поэтому цель моего проекта: создать узел связи с искусственным интеллектом, который работает без интернета.", "bg_violet.jpg");
const s4e = eyebrow("Цель", ORANGE, { y: 2.0 });
const s4t = text("Создать узел связи с ИИ, который работает без интернета.", { x: M, y: 2.5, w: 8.6, h: 2.6, fontSize: 48, bold: true });
const [s4c, s4i] = badge("wifi", 9.95, 2.45, 2.6, RED, 30);
step([s4e, "fade"], [s4t, "rise"]); step([s4c, "zoom"], [s4i, "zoom"]);

// 5. Задачи
newSlide("Темный", null,
  "Чтобы достичь цели, я поставил четыре задачи: собрать узел на плате Orange Pi, сделать чат для пострадавших, " +
  "научить ИИ понимать сообщения и сделать консоль для спасателей.", "bg_dim.jpg");
title("Задачи");
[["01", "Собрать узел на плате Orange Pi"], ["02", "Сделать чат для пострадавших"],
 ["03", "Научить ИИ понимать сообщения"], ["04", "Сделать консоль спасателя"]].forEach(([num, t], i) => {
  const x = M + (i % 2) * 6.05, y = 1.95 + Math.floor(i / 2) * 2.55;
  const card = rrect({ x, y, w: 5.75, h: 2.25 });
  const nn = text(num, { x: x + 0.45, y: y + 0.35, w: 1.6, h: 0.8, fontSize: 40, bold: true, color: RED });
  const tt = text(t, { x: x + 0.45, y: y + 1.2, w: 4.9, h: 0.8, fontSize: 24, bold: true });
  step([card, "zoom"], [nn, "zoom"], [tt, "fade"]);
});

// 6. Гипотеза
newSlide("Сцена", null,
  "Моя гипотеза: если дать людям локальный чат с искусственным интеллектом, спасатели быстрее найдут тех, кому хуже всего.", "bg_blue.jpg");
const s6e = eyebrow("Гипотеза", BLUE, { y: 2.3 });
const s6t = text("Если дать людям локальный чат с ИИ, спасатели быстрее найдут тех, кому хуже всего.",
  { x: M, y: 2.8, w: 10.6, h: 2.6, fontSize: 42, bold: true });
step([s6e, "fade"]); step([s6t, "rise"]);

// 7. Одна коробка
newSlide("Сцена", "Решение",
  "Мое решение: одна коробка. Внутри плата Orange Pi. Коробка сама раздает сеть Wi-Fi, держит чат и запускает свой ИИ. " +
  "Ей не нужны ни интернет, ни сотовые вышки.", "bg_red_center.jpg");
const s7t = text("Одна коробка.", { x: M, y: 0.6, w: W - 2 * M, h: 1.1, fontSize: 64, bold: true, align: "center" });
const s7b = img("box.png", { x: 3.55, y: 1.75, w: 6.2, h: 6.2 * BOX_RATIO, name: "!!box" });
const s7f = [["wifi", "Своя сеть Wi-Fi"], ["ai_chat", "Свой чат"], ["chip", "Свой ИИ"]].map(([icon, t], i) => {
  const x = [2.15, 5.65, 8.7][i];
  const ic = img(`i_${icon}.png`, { x, y: 6.3, w: 0.5, h: 0.5 });
  const tt = text(t, { x: x + 0.65, y: 6.33, w: 2.5, h: 0.5, fontSize: 20, bold: true, color: GRAY });
  return [ic, tt];
});
step([s7t, "fade"]); step([s7b, "zoom"]); s7f.forEach(([a, b]) => step([a, "fade"], [b, "fade"]));

// 8. Как это работает
newSlide("Темный", null,
  "Как это работает. Пострадавший подключается к Wi-Fi коробки. Коробка принимает сообщение без интернета. " +
  "Стелла, ИИ-помощница, понимает адрес, сколько людей и какие травмы. Спасатель видит всех по срочности.", "bg_dim.jpg");
title("Как это работает");
const flow = [["phone", BLUE, "Пострадавший", "Подключается к Wi-Fi коробки"],
  [null, RED, "Коробка", "Работает без интернета и сотовой связи"],
  ["ai_chat", VIOLET, "Стелла", "Понимает адрес, людей и травмы"],
  ["rescuer", ORANGE, "Спасатель", "Видит всех по срочности"]];
flow.forEach(([icon, col, h, t], i) => {
  const cx = 1.95 + i * 3.15, d = 1.7, y = 2.25;
  const c = circle({ x: cx - d / 2, y, w: d, h: d, fill: { color: col, transparency: 72 }, line: { color: col, width: 1.5 } });
  let ic;
  if (icon) ic = img(`i_${icon}.png`, { x: cx - 0.45, y: y + 0.4, w: 0.9, h: 0.9 });
  else ic = img("box.png", { x: cx - 0.68, y: y + 0.48, w: 1.36, h: 1.36 * BOX_RATIO, name: "!!box" });
  const hh = text(h, { x: cx - 1.45, y: 4.25, w: 2.9, h: 0.6, fontSize: 24, bold: true, align: "center" });
  const tt = text(t, { x: cx - 1.45, y: 4.9, w: 2.9, h: 1.1, fontSize: 17, color: GRAY, align: "center" });
  step([c, "zoom"], [ic, "zoom"], [hh, "fade"], [tt, "fade"]);
  if (i < 3) {
    const ar = nm("arrow");
    slide.addShape(pres.ShapeType.line, { x: cx + 1.0, y: y + d / 2, w: 1.15, h: 0, line: { color: GRAY, width: 2, endArrowType: "triangle" }, objectName: ar });
    step([ar, "wipe"]);
  }
});

// 9. Чат без приложения
newSlide("Сцена", "Как устроено",
  "Вот что видит пострадавший. Он подключается к открытой сети SOS-STELLA-RESCUE, и чат открывается сам. " +
  "Ничего скачивать не нужно. В чате сразу появляются подсказки первой помощи, а кнопкой можно отправить свое место.", "bg_blue.jpg");
const s9e = eyebrow("Для пострадавшего", BLUE, { y: 0.9 });
const s9t = text([{ text: "Подключился к Wi-Fi.", options: { breakLine: true } }, { text: "Чат открылся сам.", options: { color: GRAY } }],
  { x: M, y: 1.4, w: 7.4, h: 1.8, fontSize: 44, bold: true });
const s9r = [["wifi", "Приложение не нужно: все работает в браузере"], ["first_aid", "Подсказки первой помощи сразу в чате"], ["map", "Кнопка «Мое местоположение»"]]
  .map(([icon, t], i) => {
    const y = 3.75 + i * 0.95;
    const [c, ic] = badge(icon, M, y, 0.7, BLUE, 55);
    const tt = text(t, { x: M + 0.95, y: y + 0.13, w: 6.3, h: 0.5, fontSize: 20 });
    return [c, ic, tt];
  });
const s9p = img("phone_chat.png", { x: 8.75, y: 0.45, w: 6.6 * PHONE_RATIO, h: 6.6, name: "!!phone" });
step([s9e, "fade"], [s9t, "rise"]); step([s9p, "rise"]); s9r.forEach(([a, b, c]) => step([a, "zoom"], [b, "zoom"], [c, "fade"]));

// 10. Стелла
newSlide("Сцена", null,
  "Отвечает Стелла, ИИ-помощница коробки. Я задал ей правила: отвечать сразу и коротко, задавать один уточняющий вопрос, " +
  "подсказывать первую помощь и никогда не ставить диагнозы и не обещать время приезда.", "bg_violet.jpg");
const s10p = img("phone_chat.png", { x: 0.95, y: 0.45, w: 6.6 * PHONE_RATIO, h: 6.6, name: "!!phone" });
const s10e = eyebrow("ИИ-помощница", VIOLET, { x: 5.3, y: 0.9 });
const s10t = text("Стелла отвечает как диспетчер", { x: 5.3, y: 1.4, w: 7.3, h: 1.6, fontSize: 40, bold: true });
const s10r = [["clock", "Отвечает сразу и коротко"], ["question", "Задает один уточняющий вопрос"],
  ["first_aid", "Подсказывает первую помощь"], ["ban", "Не ставит диагнозы и не обещает время приезда"]]
  .map(([icon, t], i) => {
    const y = 3.2 + i * 0.95;
    const [c, ic] = badge(icon, 5.3, y, 0.7, VIOLET, 55);
    const tt = text(t, { x: 6.25, y: y + 0.13, w: 6.4, h: 0.5, fontSize: 20 });
    return [c, ic, tt];
  });
step([s10e, "fade"], [s10t, "rise"]); s10r.forEach(([a, b, c]) => step([a, "zoom"], [b, "zoom"], [c, "fade"]));

// 11. Три уровня ИИ
newSlide("Темный", null,
  "У Стеллы три уровня. Если есть интернет, отвечает облачная модель Claude. Если интернета нет, работает модель прямо на плате. " +
  "А если и она недоступна, отвечают правила сортировки. Коробка сама проверяет, что доступно, и переключается без человека.", "bg_dim.jpg");
title("Три уровня ИИ");
[["cloud", BLUE, "1", "Облако Claude", "Когда у коробки есть интернет"],
 ["chip", VIOLET, "2", "Модель на плате", "Когда интернета нет: работает прямо на Orange Pi"],
 ["rules", GREEN, "3", "Правила сортировки", "Если модель недоступна. Отвечают всегда"]].forEach(([icon, col, num, h, t], i) => {
  const x = M + i * 4.1;
  const card = rrect({ x, y: 1.95, w: 3.6, h: 3.65 });
  const [c, ic] = badge(icon, x + 0.4, 2.35, 1.0, col);
  const nn = text(num, { x: x + 2.6, y: 2.35, w: 0.6, h: 0.8, fontSize: 36, bold: true, color: col, align: "right" });
  const hh = text(h, { x: x + 0.4, y: 3.6, w: 2.9, h: 0.9, fontSize: 22, bold: true });
  const tt = text(t, { x: x + 0.4, y: 4.5, w: 2.9, h: 1.0, fontSize: 17, color: GRAY });
  step([card, "rise"], [c, "rise"], [ic, "rise"], [nn, "rise"], [hh, "rise"], [tt, "rise"]);
  if (i < 2) {
    const ar = nm("arrow");
    slide.addShape(pres.ShapeType.line, { x: x + 3.65, y: 3.77, w: 0.4, h: 0, line: { color: GRAY, width: 2, endArrowType: "triangle" }, objectName: ar });
    step([ar, "wipe"]);
  }
});
const s11c = text("Коробка сама проверяет, что доступно, и переключается без участия человека.",
  { x: M, y: 6.0, w: W - 2 * M, h: 0.6, fontSize: 20, color: GRAY });
step([s11c, "fade"]);

// 12. Сортировка
newSlide("Темный", null,
  "Главное для спасателя: кого спасать первым. Стелла ищет в сообщении признаки и ставит один из четырех приоритетов. " +
  "Например, «без сознания» или «под завалом» сразу дают «Критично». Она понимает отрицания: «не ранен» не считается травмой.", "bg_red.jpg");
title("Кого спасать первым");
[["Критично", RED, "не дышит, без сознания, сильное кровотечение, под завалом, пожар или газ"],
 ["Срочно", ORANGE, "перелом, кровотечение, ожог, травма головы, не может выйти"],
 ["Легкий", GREEN, "все целы, в безопасности"],
 ["Нет данных", GRAY, "пока непонятно: Стелла задаст уточняющий вопрос"]].forEach(([label, col, t], i) => {
  const y = 1.9 + i * 1.02;
  const chip = rrect({ x: M, y, w: 2.6, h: 0.72, rectRadius: 0.36, fill: { color: col }, line: { color: col, width: 0 }, name: `!!p${i}` });
  const ct = text(label, { x: M, y, w: 2.6, h: 0.72, fontSize: 22, bold: true, color: "FFFFFF", align: "center", valign: "middle" });
  const tt = text(t, { x: M + 3.0, y: y + 0.12, w: 8.8, h: 0.6, fontSize: 20 });
  step([chip, "zoom"], [ct, "zoom"], [tt, "fade"]);
});
const s12n = text("Отрицания понимаются: «не ранен» не считается травмой.", { x: M, y: 6.15, w: 11.8, h: 0.5, fontSize: 18, color: GRAY });
step([s12n, "fade"]);

// 13. Адрес из сообщения
newSlide("Темный", null,
  "Люди пишут адрес как получится. Стелла сама находит в обычном сообщении улицу, дом, этаж, квартиру и число людей. " +
  "Спасатель сразу видит готовый адрес и не тратит время на переписку.", "bg_blue.jpg");
title("Адрес из обычного сообщения");
const s13m = rrect({ x: 4.6, y: 1.85, w: 8.0, h: 1.05, rectRadius: 0.4, fill: { color: BLUE }, line: { color: BLUE, width: 0 } });
const s13mt = text("Мы на улице Жандосова 58, 2 этаж, квартира 14. Нас трое",
  { x: 4.95, y: 1.85, w: 7.4, h: 1.05, fontSize: 22, color: "FFFFFF", valign: "middle" });
step([s13m, "rise"], [s13mt, "rise"]);
let fx = M;
[["Улица", "Жандосова"], ["Дом", "58"], ["Этаж", "2"], ["Квартира", "14"], ["Людей", "3"]].forEach(([k, v], i) => {
  const cw = i === 0 ? 3.1 : 2.0, x = fx;
  fx += cw + 0.22;
  const card = rrect({ x, y: 3.55, w: cw, h: 1.65 });
  const kk = text(k, { x: x + 0.3, y: 3.8, w: cw - 0.5, h: 0.4, fontSize: 16, color: GRAY });
  const vv = text(v, { x: x + 0.3, y: 4.25, w: cw - 0.45, h: 0.7, fontSize: 32, bold: true });
  step([card, "zoom"], [kk, "zoom"], [vv, "zoom"]);
});
const s13c = text("Еще Стелла находит подъезд и ориентиры: «возле школы», «у магазина».",
  { x: M, y: 5.7, w: 11.8, h: 0.6, fontSize: 20, color: GRAY });
step([s13c, "fade"]);

// 14. Консоль
newSlide("Сцена", null,
  "Это консоль спасателя. В нее можно войти только по PIN-коду. Сверху счетчики по срочности, ниже состояние ИИ, " +
  "радар и все устройства, которые подключились к коробке.", "bg_dim.jpg");
const s14e = eyebrow("Для спасателя", ORANGE, { y: 1.1, w: 3.6 });
const s14t = text("Консоль спасателя", { x: M, y: 1.6, w: 3.6, h: 1.6, fontSize: 40, bold: true });
const s14s = text("Все вызовы по срочности, радар и состояние ИИ. Вход только по PIN-коду.",
  { x: M, y: 3.35, w: 3.5, h: 2.0, fontSize: 19, color: GRAY });
const s14w = img("win_console.png", { x: 4.65, y: 0.95, w: 8.2, h: 8.2 * WIN_C, name: "!!win" });
step([s14e, "fade"], [s14t, "rise"], [s14s, "fade"]); step([s14w, "rise"]);

// 15. Досье
newSlide("Сцена", null,
  "Спасатель открывает вызов и видит досье: адрес, сколько людей, заряд телефона и всю переписку. " +
  "Он меняет статус, например «группа выехала», и может написать пострадавшему напрямую.", "bg_dim.jpg");
const s15w = img("win_dossier.png", { x: 0.5, y: 0.95, w: 8.2, h: 8.2 * WIN_D, name: "!!win" });
const s15e = eyebrow("Досье вызова", ORANGE, { x: 9.15, y: 1.1, w: 3.6 });
const s15t = text("Все о вызове на одном экране", { x: 9.15, y: 1.6, w: 3.7, h: 2.2, fontSize: 36, bold: true });
const s15s = text("Адрес, число людей, заряд телефона, переписка. Спасатель меняет статус и отвечает напрямую.",
  { x: 9.15, y: 3.85, w: 3.6, h: 2.3, fontSize: 19, color: GRAY });
step([s15e, "fade"], [s15t, "rise"]); step([s15s, "fade"]);

// 16. Надежность
newSlide("Темный", "Надежность и результаты",
  "Я позаботился о надежности. Если ИИ недоступен, все равно отвечают правила. Сторож питания замечает перезагрузки из-за слабого блока питания " +
  "и включает щадящий режим. Для жюри есть страница проверки узла. А консоль защищена PIN-кодом.", "bg_green.jpg");
title("Работает, даже когда что-то отказало");
[["rules", GREEN, "Резерв отвечает всегда", "Если ИИ недоступен, человек все равно получит ответ по правилам."],
 ["bolt", ORANGE, "Сторож питания", "Замечает перезагрузки из-за слабого питания и включает щадящий режим."],
 ["check_list", BLUE, "Проверка узла", "Страница для жюри проверяет сеть, ИИ и сайт коробки."],
 ["lock", VIOLET, "Вход по PIN-коду", "Консоль спасателя закрыта, подбор PIN блокируется."]].forEach(([icon, col, h, t], i) => {
  const x = M + (i % 2) * 6.05, y = 1.95 + Math.floor(i / 2) * 2.4;
  const card = rrect({ x, y, w: 5.75, h: 2.1 });
  const [c, ic] = badge(icon, x + 0.35, y + 0.35, 0.95, col);
  const hh = text(h, { x: x + 1.55, y: y + 0.35, w: 3.95, h: 0.5, fontSize: 22, bold: true });
  const tt = text(t, { x: x + 1.55, y: y + 0.9, w: 3.95, h: 1.0, fontSize: 16, color: GRAY });
  step([card, "rise"], [c, "rise"], [ic, "rise"], [hh, "rise"], [tt, "rise"]);
});

// 17. Из чего сделано
newSlide("Темный", null,
  "Из чего сделана коробка. Внутри плата Orange Pi 4 LTS с процессором RK3399 и 4 гигабайтами памяти. Она раздает свою сеть Wi-Fi. " +
  "Корпус я сделал как модель для 3D-печати. Программа написана на Python, а модель на плате запускается через llama.cpp.", "bg_dim.jpg");
title("Из чего сделано");
const s17i = img("box_exploded.png", { x: 0.9, y: 1.75, w: 4.6, h: 4.6 * EXPL_RATIO });
step([s17i, "zoom"]);
[["Orange Pi 4 LTS", "Процессор RK3399, 4 ГБ памяти"], ["Своя сеть Wi-Fi", "SOS-STELLA-RESCUE, чат открывается сам"],
 ["Корпус", "Модель для 3D-печати"]].forEach(([h, t], i) => {
  const y = 1.85 + i * 1.05;
  const hh = text(h, { x: 6.1, y, w: 6.5, h: 0.5, fontSize: 24, bold: true });
  const tt = text(t, { x: 6.1, y: y + 0.48, w: 6.5, h: 0.45, fontSize: 17, color: GRAY });
  step([hh, "rise"], [tt, "rise"]);
});
const chips = ["Python", "FastAPI", "SQLite", "nginx", "hostapd", "dnsmasq", "llama.cpp", "Claude API"];
const chipNames = [];
let cx = 6.1, cy = 5.25;
chips.forEach((t) => {
  const w = 0.32 + t.length * 0.13;
  if (cx + w > 12.6) { cx = 6.1; cy += 0.62; }
  chipNames.push(rrect({ x: cx, y: cy, w, h: 0.48, rectRadius: 0.24, fill: { color: "2C2C2E" }, line: { color: "2C2C2E", width: 0 } }));
  chipNames.push(text(t, { x: cx, y: cy, w, h: 0.48, fontSize: 15, bold: true, align: "center", valign: "middle" }));
  cx += w + 0.15;
});
step(...chipNames.map((x) => [x, "fade"]));

// 18. Результаты
newSlide("Сцена", null,
  "Результаты. Прототип работает на настоящей плате. Для чата не нужен интернет. У ИИ три уровня, у вызовов четыре уровня срочности. " +
  "Программу проверяют больше двухсот автотестов. Вывод: узел помогает связаться со спасателями, когда связи нет.", "bg_red.jpg");
const s18t = text("Результаты", { x: M, y: 0.55, w: 8, h: 0.95, fontSize: 40, bold: true });
step([s18t, "fade"]);
[["0", RED, "интернета нужно, чтобы работал чат"], ["3", BLUE, "уровня ИИ"], ["4", ORANGE, "уровня срочности"], ["200+", GREEN, "автотестов проверяют программу"]]
  .forEach(([num, col, t], i) => {
    const x = M + i * 3.0;
    const nn = text(num, { x, y: 1.85, w: 2.8, h: 1.4, fontSize: 80, bold: true, color: col });
    const tt = text(t, { x, y: 3.3, w: 2.6, h: 1.0, fontSize: 18, color: GRAY });
    step([nn, "zoom"], [tt, "fade"]);
  });
const s18c = text([{ text: "Вывод: ", options: { color: GRAY } }, { text: "узел помогает связаться со спасателями, когда связи нет. Прототип работает на настоящей плате." }],
  { x: M, y: 4.9, w: 11.6, h: 1.3, fontSize: 26, bold: true });
step([s18c, "rise"]);

// 19. Что дальше
newSlide("Темный", "Финал",
  "Что дальше. Я хочу соединить несколько коробок в одну сеть, добавить аккумулятор и солнечную панель, " +
  "сделать карту вызовов для спасателей и голосовые сообщения, но только с согласия человека.", "bg_violet.jpg");
title("Что дальше");
[["mesh", BLUE, "Несколько коробок в одну сеть"], ["battery_sun", GREEN, "Аккумулятор и солнечная панель"],
 ["map", ORANGE, "Карта вызовов для спасателей"], ["mic", VIOLET, "Голосовые сообщения, только с согласия человека"]].forEach(([icon, col, t], i) => {
  const x = M + (i % 2) * 6.05, y = 1.95 + Math.floor(i / 2) * 2.4;
  const card = rrect({ x, y, w: 5.75, h: 2.1 });
  const [c, ic] = badge(icon, x + 0.4, y + 0.5, 1.1, col);
  const tt = text(t, { x: x + 1.85, y: y + 0.55, w: 3.6, h: 1.0, fontSize: 22, bold: true, valign: "middle" });
  step([card, "zoom"], [c, "zoom"], [ic, "zoom"], [tt, "fade"]);
});

// 20. Спасибо
newSlide("Сцена", null,
  "Спасибо за внимание! Коробка стоит здесь, ее можно попробовать: подключитесь к сети SOS-STELLA-RESCUE и напишите в чат. Готов ответить на вопросы.",
  "bg_red.jpg");
const s20t = text([{ text: "Спасибо", options: { breakLine: true } }, { text: "за внимание", options: { color: GRAY } }],
  { x: M, y: 1.8, w: 6.9, h: 2.4, fontSize: 64, bold: true, lineSpacingMultiple: 0.9 });
const s20s = text([{ text: "Попробуйте сами: подключитесь к Wi-Fi", options: { breakLine: true } }, { text: "SOS-STELLA-RESCUE", options: { color: INK, bold: true } }],
  { x: M, y: 4.45, w: 6.6, h: 0.9, fontSize: 20, color: GRAY });
const s20b = img("box.png", { x: 7.45, y: 1.95, w: 5.3, h: 5.3 * BOX_RATIO, name: "!!box" });
const s20a = text("Моисеев Алексей · Stella Pocket Rescue · 2026", { x: M, y: 6.3, w: 7.5, h: 0.5, fontSize: 15, color: GRAY });
step([s20t, "rise"]); step([s20s, "fade"], [s20a, "fade"]);

(async () => {
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  fs.writeFileSync(path.join(__dirname, "anim.json"), JSON.stringify(ANIM, null, 1));
  console.log("слайдов:", n, "→", OUT);
})();

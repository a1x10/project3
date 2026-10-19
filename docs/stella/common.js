/* Стелла — рекламная страница. Общее для film.js и landing.js: настройки и помощники для DOM.
   Страница живёт на том же адресе, что и панель управления, поэтому строго: только свой код (CSP),
   без вставки HTML-строк в DOM (Trusted Types это запрещают) — элементы создаются через h()/svg(). */
(function () {
  "use strict";

  // Куда ведут кнопки. BOT — @username бота в Telegram (без @).
  // SUPPORT — контакт техподдержки для подписки (@username, ссылка t.me/… или https://…); пусто — ведём к боту.
  const CONFIG = Object.freeze({
    BOT: "stella_ai_beta_bot",
    SUPPORT: "",
  });

  const tgLink = (v) => {
    const s = String(v || "").trim();
    if (!s) return "";
    if (/^https:\/\//i.test(s)) return s;
    return "https://t.me/" + s.replace(/^@/, "").replace(/^t\.me\//i, "");
  };

  const FIELD_PROPS = new Set(["value", "checked", "disabled", "hidden", "tabIndex", "id", "className", "title"]);

  // h("div", {class: "a b", text: "…", href: "…", onclick: fn, style: {transform: "…"}}, ...kids)
  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    apply(el, props);
    append(el, kids);
    return el;
  }

  // svg("path", {d: "…", fill: "…"}, ...kids) — элементы SVG
  function svg(tag, props, ...kids) {
    const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    apply(el, props);
    append(el, kids);
    return el;
  }

  function apply(el, props) {
    for (const [k, v] of Object.entries(props || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.setAttribute("class", v);
      else if (k === "text") el.textContent = String(v);
      else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
      else if (k === "dataset" && typeof v === "object") Object.assign(el.dataset, v);
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
      else if (FIELD_PROPS.has(k) && !(el instanceof SVGElement)) el[k] = v;
      else if (k !== "style") el.setAttribute(k, v === true ? "" : String(v));
    }
  }

  function append(el, kids) {
    for (const kid of kids.flat(Infinity)) {
      if (kid === null || kid === undefined || kid === false) continue;
      el.append(kid instanceof Node ? kid : String(kid));
    }
  }

  const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  window.Stella = Object.freeze({
    CONFIG,
    botUrl: tgLink(CONFIG.BOT),
    supportUrl: tgLink(CONFIG.SUPPORT) || tgLink(CONFIG.BOT),
    h,
    svg,
    reducedMotion,
  });

  // Все ссылки с data-link="bot" / data-link="support" — на нужный адрес (в HTML уже стоит запасной).
  document.addEventListener("DOMContentLoaded", () => {
    for (const a of document.querySelectorAll("a[data-link]")) {
      const url = a.dataset.link === "support" ? window.Stella.supportUrl : window.Stella.botUrl;
      if (url) a.href = url;
    }
  });
})();

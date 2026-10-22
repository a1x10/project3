/* Стелла · панель — логика интерфейса.
 * Безопасность: DOM строится только через createElement + textContent (никакого HTML
 * из строк), токен живёт только в sessionStorage, запросы — без cookies и кэша, с таймаутом. */
"use strict";

(() => {
  // ---------- константы ----------
  const API = "/admin/api";
  const TIMEOUT_MS = 20000;
  const IDLE_MS = 30 * 60 * 1000;
  const OVERVIEW_EVERY = 30000;
  const LOG_EVERY = 10000;
  const ABOUT_MAX = 4000;
  // trusted — сервер, на котором уже был успешный вход: чужой адрес из ссылки без предупреждения не принимаем
  const K = { server: "stella.server", trusted: "stella.trusted", token: "stella.token", exp: "stella.token_exp", active: "stella.last_active", tab: "stella.tab" };
  const TABS = ["overview", "chats", "people", "keys", "settings", "log"];
  const CHIME = new Map([["off", "выкл"], ["rare", "редко"], ["normal", "обычно"], ["chatty", "болтушка"]]);
  const KINDS = new Map([
    ["sticker", "стикер"], ["image", "фото"], ["photo", "фото"], ["video", "видео"], ["gif", "гифка"],
    ["audio", "аудио"], ["voice", "голосовое"], ["ptt", "голосовое"], ["document", "файл"], ["file", "файл"],
    ["location", "место"], ["contact", "контакт"], ["poll", "опрос"], ["reaction", "реакция"],
    ["deleted", "удалено"], ["system", "служебное"],
  ]);
  const ERR_TEXT = {
    400: "Неверный запрос", 403: "Нет доступа", 404: "Не найдено", 409: "Данные изменились — обновите",
    413: "Слишком длинный текст", 422: "Неверные данные", 429: "Слишком часто — подождите немного",
  };
  const NO_SERVER = "Сервер не отвечает. Проверьте адрес и что бот запущен";
  const FIELD_PROPS = new Set(["value", "checked", "disabled", "hidden", "readOnly", "maxLength", "rows", "tabIndex"]);

  const $ = (id) => document.getElementById(id);
  const S = {
    server: "", tab: "overview", chats: null, chat: null, chatSeq: 0, peopleChatId: null, peopleSeq: 0,
    settings: null, settingCtl: [], settingsDirty: false, log: [], logAuto: false, keys: null, keysUI: null, keysSeq: 0,
    lastOverview: 0, lastLog: 0, lastActive: 0, lastSaved: 0, loading: { overview: false, log: false },
    beat: 0, lockTimer: 0, lockUntil: 0, toastTimer: 0, p1: "", loginBusy: false, uid: 0,
  };
  let memToken = ""; // только если sessionStorage недоступен (приватный режим)

  // ---------- DOM-помощники (только textContent) ----------
  const clean = (kids) => kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false);
  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = String(v);
      else if (FIELD_PROPS.has(k)) el[k] = v;
      else el.setAttribute(k, v === true ? "" : String(v));
    }
    for (const kid of clean(kids)) el.append(kid instanceof Node ? kid : String(kid));
    return el;
  }
  const setKids = (box, ...kids) => box.replaceChildren(...clean(kids));
  // SVG-иконки: только createElementNS + setAttribute, пути — константы из кода
  const SVG_NS = "http://www.w3.org/2000/svg";
  const STAR = "M32 6c2 14 6 22 26 26-20 4-24 12-26 26-2-14-6-22-26-26 20-4 24-12 26-26z";
  const ICONS = {
    wa: ["M20 12a8 8 0 0 1-11.6 7.1L4 20l1-4.1A8 8 0 1 1 20 12z", "M9.5 9.5c0 2.5 2.5 5 5 5"],
    chip: ["M7 7h10v10H7z", "M10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4"],
    coin: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M14.8 9.2c-.5-.8-1.5-1.2-2.8-1.2-1.7 0-2.8.8-2.8 2s1.1 1.7 2.8 2 2.8.8 2.8 2-1.1 2-2.8 2c-1.3 0-2.4-.5-2.9-1.3M12 6.5V8M12 16v1.5"],
    chats: ["M4 5h16v11H10l-5 4v-4H4z"],
    clock: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M12 7v5l3 2"],
    globe: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M3 12h18", "M12 3c2.5 2.7 3.8 5.7 3.8 9s-1.3 6.3-3.8 9c-2.5-2.7-3.8-5.7-3.8-9S9.5 5.7 12 3z"],
    key: ["M8 19.5a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9z", "M11.2 11.8 20 3", "M16.5 6.5l2.5 2.5M14 9l2 2"],
    ext: ["M14 4h6v6", "M20 4l-9 9", "M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"],
    plus: ["M12 5v14M5 12h14"],
    info: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M12 11v5M12 8h.01"],
    group: ["M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z", "M2.5 20c.8-3.6 3.4-5.5 6.5-5.5s5.7 1.9 6.5 5.5", "M16 4.8a3.3 3.3 0 0 1 0 6.4", "M18 14.8c1.8.7 3 2.4 3.5 5.2"],
    chev: ["M9 6l6 6-6 6"],
    swap: ["M4 8h13l-3-3M20 16H7l3 3"],
  };
  function icon(name, cls) {
    const svg = document.createElementNS(SVG_NS, "svg");
    const star = name === "star";
    svg.setAttribute("viewBox", star ? "0 0 64 64" : "0 0 24 24");
    svg.setAttribute("class", "ico" + (cls ? " " + cls : ""));
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    if (!star) {
      [["fill", "none"], ["stroke", "currentColor"], ["stroke-width", "1.8"], ["stroke-linecap", "round"], ["stroke-linejoin", "round"]]
        .forEach(([k, v]) => svg.setAttribute(k, v));
    }
    for (const d of star ? [STAR] : ICONS[name] || []) {
      const path = document.createElementNS(SVG_NS, "path");
      path.setAttribute("d", d);
      if (star) path.setAttribute("fill", "currentColor");
      svg.append(path);
    }
    return svg;
  }
  // Пустое состояние: звёздочка + текст (+ необязательная подсказка)
  const emptyBox = (text, sub) => h("div", { class: "placeholder empty" },
    h("span", { class: "empty-mark" }, icon("star")), h("p", { class: "empty-title", text }), sub ? h("p", { class: "empty-sub", text: sub }) : null);
  const showEmpty = (box, text, sub) => { box.removeAttribute("aria-busy"); box.replaceChildren(emptyBox(text, sub)); };
  // Скелетон на время загрузки: kind — tiles | list | msgs | form | log
  function showSkeleton(box, kind, n) {
    const count = n || (kind === "tiles" ? 6 : kind === "msgs" ? 6 : 5);
    const one = (i) => {
      if (kind === "tiles") return h("div", { class: "skel-tile" + (i < 2 ? " wide" : "") }, h("i", { class: "skel w30" }), h("i", { class: "skel big w60" }), h("i", { class: "skel w80" }));
      if (kind === "msgs") return h("div", { class: "skel-msg" + (i % 3 === 1 ? " right" : "") }, h("i", { class: "skel w60" }), h("i", { class: "skel w80" }));
      if (kind === "log") return h("i", { class: "skel line " + ["w80", "w60", "w90", "w70"][i % 4] });
      return h("div", { class: "skel-row" }, kind === "form" ? null : h("i", { class: "skel ava" }),
        h("div", { class: "skel-lines" }, h("i", { class: "skel w60" }), h("i", { class: "skel w80" })));
    };
    box.setAttribute("aria-busy", "true");
    box.replaceChildren(h("div", { class: `skeleton skel-${kind}` },
      h("span", { class: "sr-only", text: "Загрузка…" }), Array.from({ length: count }, (_, i) => one(i))));
  }
  const loaded = (box) => box.removeAttribute("aria-busy");
  // Аватар-инициалы: цвет — по хэшу имени (классы av-0…av-5, без style)
  function avatar(name, extra) {
    const words = String(name || "?").replace(/[^\p{L}\p{N}\s]/gu, " ").trim().split(/\s+/).filter(Boolean);
    const ini = words.length > 1 ? [...words[0]][0] + [...words[1]][0] : [...(words[0] || "?")][0];
    let hash = 0;
    for (const ch of String(name || "")) hash = (hash * 31 + ch.codePointAt(0)) >>> 0;
    return h("span", { class: `avatar av-${hash % 6}${extra ? " " + extra : ""}`, "aria-hidden": "true", text: ini.toUpperCase() });
  }
  function plural(n, forms) {
    const a = Math.abs(n) % 100, b = a % 10;
    return forms[a > 10 && a < 20 ? 2 : b === 1 ? 0 : b >= 2 && b <= 4 ? 1 : 2];
  }
  const on = (id, ev, fn) => $(id).addEventListener(ev, fn);
  const setVal = (ids, v) => ids.forEach((id) => { $(id).value = v; });

  // ---------- хранилища (могут бросать исключения — всё в try) ----------
  function storage(name) {
    return {
      get(k) { try { return window[name].getItem(k); } catch (_) { return null; } },
      set(k, v) { try { window[name].setItem(k, String(v)); return true; } catch (_) { return false; } },
      del(k) { try { window[name].removeItem(k); } catch (_) { /* недоступно */ } },
    };
  }
  const local = storage("localStorage");
  const sess = storage("sessionStorage");
  const getToken = () => sess.get(K.token) || memToken;
  function setToken(token, expiresIn) {
    memToken = sess.set(K.token, token) ? "" : token;
    const sec = Number(expiresIn);
    if (sec > 0) sess.set(K.exp, Date.now() + sec * 1000); else sess.del(K.exp);
  }
  function clearToken() {
    memToken = "";
    [K.token, K.exp, K.active].forEach((k) => sess.del(k));
  }

  // ---------- форматирование ----------
  const pad = (n) => String(n).padStart(2, "0");
  const clip = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);
  const usd = (n) => "$" + (Number(n) || 0).toFixed(2);
  const valueText = (v) => (v === null || v === undefined ? "" : typeof v === "object" ? JSON.stringify(v) : String(v));
  const chimeText = (lvl) => CHIME.get(lvl) || "по умолчанию";
  function toDate(iso) {
    const t = iso ? Date.parse(iso) : NaN;
    return Number.isFinite(t) ? new Date(t) : null;
  }
  // «HH:MM» сегодня, «вчера HH:MM», «завтра HH:MM», иначе «DD.MM HH:MM» — в местном времени
  function fmtTime(iso, withSec) {
    const d = toDate(iso);
    if (!d) return "";
    const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}${withSec ? ":" + pad(d.getSeconds()) : ""}`;
    const n = new Date();
    const off = Math.round((new Date(d.getFullYear(), d.getMonth(), d.getDate()) - new Date(n.getFullYear(), n.getMonth(), n.getDate())) / 864e5);
    if (off === 0) return hm;
    if (off === -1) return `вчера ${hm}`;
    if (off === 1) return `завтра ${hm}`;
    return `${pad(d.getDate())}.${pad(d.getMonth() + 1)} ${hm}`;
  }
  function ago(iso) {
    const d = toDate(iso);
    if (!d) return "";
    const s = (Date.now() - d.getTime()) / 1000;
    if (s < 60) return "только что";
    if (s < 3600) return `${Math.floor(s / 60)} мин назад`;
    if (s < 6 * 3600) return `${Math.floor(s / 3600)} ч назад`;
    return fmtTime(iso);
  }
  function fmtDur(sec) {
    const t = Math.max(0, Math.floor(Number(sec) || 0));
    const d = Math.floor(t / 86400), hr = Math.floor((t % 86400) / 3600), m = Math.floor((t % 3600) / 60);
    return d ? `${d} д ${hr} ч` : hr ? `${hr} ч ${m} мин` : `${m} мин`;
  }
  function switchText(v, after) { // LLM_SWITCH_AT — дата, с которой бот берёт запасную модель (или выключает её)
    const s = String(v);
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
    if (!m) return s;
    const n = new Date();
    const today = `${n.getFullYear()}-${pad(n.getMonth() + 1)}-${pad(n.getDate())}`;
    const what = after === "off" ? " — модель выключится, баланс не тратится" : " — запасная модель";
    return `с ${m[3]}.${m[2]}.${m[1]}` + (s.slice(0, 10) <= today ? " (уже действует)" : what);
  }
  function hostOf(url) {
    try {
      const u = new URL(url);
      return u.host + (u.pathname !== "/" ? u.pathname : "");
    } catch (_) { return String(url); }
  }

  // ---------- адрес сервера ----------
  function normServer(raw) {
    let s = String(raw || "").trim();
    if (!s) return null;
    if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(s)) s = "https://" + s;
    let u;
    try { u = new URL(s); } catch (_) { return null; }
    const isLocal = u.hostname === "localhost" || u.hostname === "127.0.0.1";
    if (u.username || u.password) return null;
    if (u.protocol !== "https:" && !(u.protocol === "http:" && isLocal)) return null;
    return (u.origin + u.pathname).replace(/\/+$/, "");
  }
  // Порядок: панель отдаёт сам бот → его origin; иначе #server=… → localStorage → спросить.
  function resolveServer() {
    let notice = null, fromHash = null;
    const m = /(?:^#|&)server=([^&]*)/.exec(location.hash || "");
    if (m) {
      try { fromHash = normServer(decodeURIComponent(m[1])); } catch (_) { fromHash = null; }
      history.replaceState(history.state, "", location.pathname + location.search);
      if (!fromHash) notice = ["Адрес сервера в ссылке не подходит (нужен https://). Введите его вручную.", "bad"];
    }
    const saved = normServer(local.get(K.server));
    const onPages = /\.github\.io$/i.test(location.hostname);
    if (/\/panel(\/|$)/.test(location.pathname) && !onPages && /^https?:$/.test(location.protocol)) {
      return { server: location.origin, notice: null };
    }
    if (!fromHash) return { server: saved || "", notice };
    const trusted = normServer(local.get(K.trusted));
    if (fromHash !== trusted) {
      // Ссылку мог прислать кто угодно: адрес не запоминаем до успешного входа и всегда показываем полностью
      notice = [`Внимание: адрес сервера взят из ссылки — ${fromHash}. Вводите пароли, только если это адрес из сообщения Стеллы вам в WhatsApp.`, "warn"];
    }
    return { server: fromHash, notice, untrusted: fromHash !== trusted };
  }
  function setServer(url, remember = true) {
    if (url !== S.server) clearToken(); // токен другого сервера не годится
    S.server = url;
    if (remember) local.set(K.server, url);
  }

  // ---------- сеть ----------
  class ApiError extends Error {
    constructor(status, code, detail, handled) {
      super(code || "error");
      Object.assign(this, { status, code: code ? String(code) : "", detail: detail ? String(detail) : "", handled: Boolean(handled) });
    }
  }
  async function request(method, path, body, token) {
    if (!S.server) throw new ApiError(0, "network");
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
    const headers = { Accept: "application/json" };
    const init = { method, headers, credentials: "omit", cache: "no-store", mode: "cors", redirect: "error", referrerPolicy: "no-referrer", signal: ctrl.signal };
    if (body !== undefined) { headers["Content-Type"] = "application/json"; init.body = JSON.stringify(body); }
    if (token) headers.Authorization = "Bearer " + token;
    try {
      const res = await fetch(S.server + API + path, init);
      let data = null;
      try { data = await res.json(); } catch (_) { data = null; }
      return { status: res.status, ok: res.ok, data: data && typeof data === "object" ? data : null };
    } catch (_) {
      throw new ApiError(0, ctrl.signal.aborted ? "timeout" : "network");
    } finally {
      clearTimeout(timer);
    }
  }
  // Запрос с токеном. Любой 401 → стираем токен и возвращаемся ко входу.
  async function api(method, path, body) {
    const token = getToken();
    if (!token) { expire(); throw new ApiError(401, "unauthorized", "", true); }
    const r = await request(method, path, body === undefined && method !== "GET" && method !== "DELETE" ? {} : body, token);
    if (r.status === 401) {
      if (getToken() === token) expire(); // 401 на старый токен после нового входа игнорируем
      throw new ApiError(401, "unauthorized", "", true);
    }
    if (!r.ok) throw new ApiError(r.status, r.data && r.data.error, r.data && r.data.detail);
    return r.data || {};
  }
  function errText(e) {
    if (!(e instanceof ApiError)) return "Что-то пошло не так. Попробуйте ещё раз";
    if (e.status === 0) return e.code === "timeout" ? "Сервер долго не отвечает. Попробуйте ещё раз" : NO_SERVER;
    if (e.detail) return clip(e.detail, 200);
    const base = ERR_TEXT[e.status] || (e.status >= 500 ? "Ошибка на сервере" : "Не получилось");
    return `${base} (${/^[\w.-]{1,40}$/.test(e.code) ? e.code : "код " + e.status})`;
  }
  const showError = (e) => { if (!(e && e.handled)) toast(errText(e), "bad"); };
  function toast(text, kind) {
    const el = $("toast");
    el.textContent = text;
    el.className = "toast" + (kind ? " " + kind : "");
    el.hidden = false;
    clearTimeout(S.toastTimer);
    S.toastTimer = setTimeout(() => { el.hidden = true; }, kind === "bad" ? 6000 : 3000);
  }
  // Блокирует элементы на время запроса (нет двойных нажатий); первый — тот, что нажали.
  async function busy(els, fn) {
    const list = (Array.isArray(els) ? els : [els]).filter(Boolean);
    if (!list.length || list[0].disabled) return undefined;
    const prev = list.map((el) => el.disabled);
    list.forEach((el) => { el.disabled = true; });
    list[0].setAttribute("aria-busy", "true");
    try {
      return await fn();
    } catch (e) {
      showError(e);
      return undefined;
    } finally {
      list.forEach((el, i) => { el.disabled = prev[i]; });
      list[0].removeAttribute("aria-busy");
    }
  }

  // ---------- вход: два шага в интерфейсе, один запрос ----------
  function setLoginMsg(text, kind) {
    const el = $("login-msg");
    el.textContent = text || "";
    el.className = "login-msg" + (kind ? " " + kind : "");
    el.hidden = !text;
  }
  function renderServerBox(edit) {
    const editing = Boolean(edit) || !S.server;
    $("server-show").hidden = !S.server;
    $("server-host").textContent = S.server ? hostOf(S.server) : "";
    $("server-change").hidden = editing;
    $("server-field").hidden = !editing;
    if (editing) $("server-input").value = S.server || "";
  }
  function goStep(n) {
    $("step1").hidden = n !== 1;
    $("step2").hidden = n !== 2;
    $("p2").value = "";
    if (n === 1) S.p1 = "";
    const target = n === 2 ? $("p2") : S.server ? $("p1") : $("server-input");
    setTimeout(() => target.focus(), 0);
  }
  const isLocked = () => S.lockUntil > Date.now();
  function lockFor(sec) {
    const s = Math.max(1, Math.ceil(Number(sec) || 60));
    S.lockUntil = Date.now() + s * 1000;
    setLoginMsg(`Слишком много попыток. Подождите ${Math.ceil(s / 60)} мин.`, "bad");
    clearInterval(S.lockTimer);
    S.lockTimer = setInterval(updateLock, 1000);
    updateLock();
  }
  function updateLock() {
    const left = Math.ceil((S.lockUntil - Date.now()) / 1000);
    const locked = left > 0;
    $("step1-btn").disabled = $("step2-btn").disabled = locked || S.loginBusy;
    $("lock-timer").hidden = !locked;
    if (locked) {
      $("lock-timer").textContent = `Можно снова через ${Math.floor(left / 60)}:${pad(left % 60)}`;
    } else if (S.lockTimer) {
      clearInterval(S.lockTimer);
      S.lockTimer = S.lockUntil = 0;
      setLoginMsg("Можно попробовать снова", "");
    }
  }
  function onStep1(e) {
    e.preventDefault();
    if (S.loginBusy || isLocked()) return;
    if (!$("server-field").hidden) {
      const s = normServer($("server-input").value);
      if (!s) {
        setLoginMsg("Адрес сервера должен начинаться с https:// (или http://localhost)", "bad");
        $("server-input").focus();
        return;
      }
      setServer(s);
      renderServerBox(false);
    }
    if (!$("p1").value) { setLoginMsg("Введите пароль 1", "bad"); $("p1").focus(); return; }
    S.p1 = $("p1").value;
    $("p1").value = "";
    setLoginMsg("", "");
    goStep(2);
  }
  async function onStep2(e) {
    e.preventDefault();
    if (S.loginBusy || isLocked()) return;
    if (!S.p1) { goStep(1); return; }
    if (!$("p2").value) { setLoginMsg("Введите пароль 2", "bad"); $("p2").focus(); return; }
    let body = { p1: S.p1, p2: $("p2").value };
    S.p1 = "";
    setVal(["p1", "p2"], "");
    S.loginBusy = true;
    updateLock();
    setLoginMsg("Проверяю…", "");
    let r = null;
    try { r = await request("POST", "/login", body, null); } catch (_) { r = null; }
    body = null; // пароли больше нигде не держим
    S.loginBusy = false;
    const data = (r && r.data) || {};
    if (r && r.status === 200 && typeof data.token === "string" && data.token) {
      setToken(data.token, data.expires_in);
      local.set(K.server, S.server); // вход удался — этому адресу можно доверять
      local.set(K.trusted, S.server);
      setLoginMsg("", "");
      enterApp();
      return;
    }
    goStep(1); // какой из паролей неверен — не сообщаем
    if (r && r.status === 429) { lockFor(data.retry_after); return; }
    if (!r) setLoginMsg(NO_SERVER, "bad");
    else if (r.status === 401) setLoginMsg("Неверные пароли", "bad");
    else if (r.status === 503) setLoginMsg("Панель выключена на сервере (не заданы пароли в .env)", "bad");
    else setLoginMsg(`Не получилось войти (код ${r.status})${data.detail ? ": " + clip(String(data.detail), 160) : ""}`, "bad");
    updateLock();
  }
  function showLogin(msg, kind) {
    stopApp();
    $("app").hidden = true;
    $("login").hidden = false;
    $("p1").value = "";
    renderServerBox(false);
    setLoginMsg(msg, kind);
    goStep(1);
    updateLock();
  }
  // Убираем из памяти и DOM всё, что относится к сессии.
  function stopApp() {
    clearInterval(S.beat);
    Object.assign(S, {
      beat: 0, chats: null, chat: null, chatSeq: S.chatSeq + 1, peopleSeq: S.peopleSeq + 1, peopleChatId: null,
      settings: null, settingCtl: [], settingsDirty: false, log: [], logAuto: false,
    });
    Object.assign(S, { keys: null, keysUI: null, keysSeq: S.keysSeq + 1 });
    ["ov-body", "chats-list", "chat-msgs", "people-list", "people-chat", "settings-body", "log-list", "keys-body"].forEach((id) => $(id).replaceChildren());
    $("hdr-dot").className = "dot";
    setVal(["send-text", "about-text", "log-filter"], "");
    $("about-notes").textContent = "";
    $("log-auto").checked = false;
    $("chat-view").hidden = true;
    $("chats-list-view").hidden = false;
    $("settings-dirty").hidden = true;
    if (history.state && history.state.stellaChat) history.replaceState(null, "");
  }
  function enterApp() {
    $("login").hidden = true;
    $("app").hidden = false;
    $("hdr-host").textContent = hostOf(S.server);
    S.lastActive = Date.now();
    S.lastSaved = 0;
    markActive();
    clearInterval(S.beat);
    S.beat = setInterval(heartbeat, 1000);
    const saved = sess.get(K.tab);
    selectTab(TABS.includes(saved) ? saved : "overview", false);
  }
  function expire() {
    clearToken();
    if (!$("app").hidden) showLogin("Сессия закончилась, войдите снова", "bad");
  }
  function idleLogout() {
    const token = getToken();
    clearToken();
    if (token) request("POST", "/logout", {}, token).catch(() => { /* ошибки не важны */ });
    showLogin("Вы вышли автоматически: 30 минут без действий", "");
  }
  async function logout() {
    await busy($("logout-btn"), async () => {
      const token = getToken();
      clearToken();
      if (token) await request("POST", "/logout", {}, token).catch(() => { /* всё равно выходим */ });
    });
    showLogin("Вы вышли", "ok");
  }
  async function logoutAll() {
    if (!confirm("Выйти на всех устройствах? Потом нужно будет снова ввести пароли.")) return;
    const ok = await busy($("logout-all"), async () => { await api("POST", "/logout_all"); return true; });
    if (ok) { clearToken(); showLogin("Вы вышли на всех устройствах", "ok"); }
  }

  // ---------- активность и таймеры ----------
  function markActive() {
    if ($("app").hidden) return;
    const now = Date.now();
    if (S.lastActive && now - S.lastActive > IDLE_MS) { idleLogout(); return; }
    S.lastActive = now;
    if (now - S.lastSaved > 5000) { S.lastSaved = now; sess.set(K.active, now); }
  }
  function heartbeat() {
    if ($("app").hidden) return;
    const now = Date.now();
    if (now - S.lastActive > IDLE_MS) { idleLogout(); return; }
    const exp = Number(sess.get(K.exp)) || 0;
    if (exp && now > exp) { expire(); return; }
    if (document.visibilityState !== "visible") return;
    if (S.tab === "overview" && now - S.lastOverview >= OVERVIEW_EVERY) loadOverview(true);
    if (S.tab === "log" && S.logAuto && now - S.lastLog >= LOG_EVERY) loadLog(true);
  }

  // ---------- вкладки ----------
  function selectTab(name, focus) {
    S.tab = name;
    sess.set(K.tab, name);
    for (const t of TABS) {
      $("tab-" + t).setAttribute("aria-selected", t === name ? "true" : "false");
      $("tab-" + t).tabIndex = t === name ? 0 : -1;
      $("panel-" + t).hidden = t !== name;
    }
    if (focus) $("tab-" + name).focus();
    window.scrollTo(0, 0);
    if (name === "overview") loadOverview(false);
    else if (name === "chats") { if (S.chat) loadMessages(); else loadChats(); }
    else if (name === "people") loadPeopleTab();
    else if (name === "keys") loadKeys(false);
    else if (name === "settings") { if (!S.settingsDirty) loadSettings(); }
    else if (name === "log") loadLog(false);
  }
  function onTabKey(e) {
    const i = TABS.indexOf(S.tab);
    const map = { ArrowRight: (i + 1) % TABS.length, ArrowLeft: (i + TABS.length - 1) % TABS.length, Home: 0, End: TABS.length - 1 };
    if (!(e.key in map)) return;
    e.preventDefault();
    selectTab(TABS[map[e.key]], true);
  }

  // ---------- 1. Обзор ----------
  const BACKENDS = new Map([
    ["off", "выключена"], ["groq", "Groq"], ["openrouter", "OpenRouter"], ["gemini", "Google Gemini"], ["openai", "OpenAI"],
    ["agent_sdk", "Claude · Agent SDK"], ["messages_api", "Claude · Messages API"],
  ]);
  const backendName = (b) => BACKENDS.get(String(b || "")) || String(b || "—");
  const tile = (cls, ico, label, ...kids) => h("div", { class: "tile " + cls },
    h("div", { class: "tile-label" }, icon(ico), h("span", { text: label })), kids);
  async function loadOverview(silent) {
    if (S.loading.overview) return;
    S.loading.overview = true;
    S.lastOverview = Date.now();
    const box = $("ov-body");
    if (!box.firstChild) showSkeleton(box, "tiles");
    try {
      renderOverview(await api("GET", "/status"));
    } catch (e) {
      if (e.handled) return;
      if (!silent) showError(e);
      if (!box.querySelector(".tile")) showEmpty(box, "Не удалось загрузить", "Проверьте связь и нажмите «Обновить».");
    } finally {
      S.loading.overview = false;
    }
  }
  function renderOverview(st) {
    const wa = String(st.whatsapp || "неизвестно");
    const waCls = wa === "open" ? "ok" : wa === "connecting" ? "warn" : "bad";
    const waText = wa === "open" ? "на связи" : wa === "connecting" ? "подключается…" : `нет связи (${wa})`;
    $("hdr-dot").className = "dot " + waCls;
    const spend = Number(st.spend_today_usd) || 0;
    const budget = Number(st.daily_budget_usd) || 0;
    const over = Boolean(st.over_budget);
    const off = st.llm_backend === "off";
    const pct = budget > 0 ? Math.min(100, (spend / budget) * 100) : over ? 100 : 0;
    const fill = h("span");
    fill.style.width = pct.toFixed(1) + "%"; // CSSOM, а не атрибут style — CSP это разрешает
    const bar = h("div", {
      class: "bar" + (over ? " over" : pct >= 80 ? " high" : ""), role: "progressbar", "aria-label": "Потрачено от дневного бюджета",
      "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(Math.round(pct)),
    }, fill);
    // Главный итог: одна фраза о самом важном
    const [tone, head] = waCls === "bad" ? ["bad", "Нет связи с WhatsApp"]
      : over ? ["bad", "Дневной бюджет исчерпан"]
        : waCls === "warn" ? ["warn", "WhatsApp подключается"]
          : off ? ["warn", "Модель выключена"]
            : ["ok", "Стелла на связи"];
    const sub = off ? "Отвечать не будет, баланс не тратится" : `Отвечает через ${backendName(st.llm_backend)}`;
    const chats = Number(st.chats) || 0;
    setKids($("ov-body"),
      st.weak_passwords
        ? h("div", { class: "notice", role: "note", text: "Пароли панели короткие или только из цифр — смените их в .env на длинные (держится только на блокировке подбора)" })
        : null,
      st.own_lid_known === false
        ? h("div", { class: "notice", role: "note", text: "Стелла пока не знает свой LID — @упоминания в некоторых группах может не видеть" })
        : null,
      h("div", { class: `hero tone-${tone}` },
        h("span", { class: "hero-mark" }, icon("star")),
        h("div", { class: "hero-text" },
          h("p", { class: "hero-kicker", text: `работает ${fmtDur(st.uptime_s)}` }),
          h("h3", { class: "hero-title", text: head }),
          h("p", { class: "hero-sub", text: sub }))),
      h("div", { class: "tiles" },
        tile("t-model wide", "chip", "Модель",
          h("div", { class: "tile-value" }, off ? h("span", { class: "pill warn", text: "выключена" }) : backendName(st.llm_backend)),
          off ? h("p", { class: "tile-sub", text: "Отвечать не будет — баланс не тратится" }) : null,
          !off && st.llm_model ? h("p", { class: "mono-chip", text: String(st.llm_model) }) : null,
          !off && st.llm_effort ? h("p", { class: "tile-sub", text: `усилие: ${st.llm_effort}` }) : null,
          st.switch_at ? h("p", { class: "tile-sub switch", text: `Смена модели ${switchText(st.switch_at, st.backend_after)}` }) : null),
        tile("t-spend wide" + (over ? " is-bad" : ""), "coin", "Расходы сегодня",
          h("div", { class: "tile-value" }, h("span", { class: "num", text: usd(spend) }),
            h("span", { class: "of", text: budget > 0 ? ` из ${usd(budget)}` : " · без лимита" })),
          budget > 0 ? bar : null,
          h("p", { class: "tile-sub", text: over ? "бюджет превышен — Стелла экономит" : budget > 0 ? `осталось ${usd(Math.max(0, budget - spend))} · ${Math.round(pct)}%` : "дневной лимит не задан" })),
        tile("t-wa", "wa", "WhatsApp", h("div", { class: "tile-value" }, h("span", { class: `pill ${waCls}`, text: waText }))),
        tile("t-chats", "chats", "Чаты",
          h("div", { class: "tile-value" }, h("span", { class: "num", text: String(chats) })),
          h("p", { class: "tile-sub", text: `${Number(st.groups) || 0} ${plural(Number(st.groups) || 0, ["группа", "группы", "групп"])} · ${Number(st.dms) || 0} ${plural(Number(st.dms) || 0, ["личка", "лички", "личек"])}` })),
        tile("t-tunnel wide", "globe", "Туннель",
          h("div", { class: "tile-value" }, st.tunnel_url ? h("span", { class: "host-val", text: hostOf(String(st.tunnel_url)) }) : h("span", { class: "muted", text: "не запущен" })),
          h("p", { class: "tile-sub", text: st.tunnel_url ? "через него открывается эта панель" : "панель открыта напрямую" }))),
      h("p", { class: "updated muted small", text: `Обновлено в ${fmtTime(new Date().toISOString(), true)} · каждые 30 с` }));
    loaded($("ov-body"));
  }
  async function bulkAction(btn, path, question, done) {
    if (!confirm(question)) return;
    await busy(btn, async () => {
      const r = await api("POST", path);
      toast(done(Number(r.count) || 0));
      loadOverview(true);
      if (S.chats) loadChats();
    });
  }

  // ---------- 2. Чаты ----------
  const chatPath = (id, tail) => `/chats/${encodeURIComponent(String(id))}${tail || ""}`;
  const msgTime = (c) => (toDate(c.last_message_at) || 0) - 0;
  const sortChats = (list) => list.slice().sort((a, b) =>
    (Number(Boolean(b.is_group)) - Number(Boolean(a.is_group))) || (msgTime(b) - msgTime(a)) ||
    String(a.title || "").localeCompare(String(b.title || ""), "ru"));
  function pauseInfo(c) {
    const until = toDate(c.paused_until);
    if (until && until.getTime() > Date.now()) return (c.paused_by_owner ? "ты пишешь сам · до " : "пауза до ") + fmtTime(c.paused_until);
    return c.paused_by_owner && !c.paused_until ? "ты пишешь сам" : "";
  }
  const grudgeBadge = (c) => (Number(c.grudges) > 0 ? h("span", { class: "badge bad", text: `обиды: ${Number(c.grudges)}` }) : null);

  async function loadChats() {
    const box = $("chats-list");
    if (!S.chats) showSkeleton(box, "list");
    try {
      const r = await api("GET", "/chats");
      S.chats = sortChats(Array.isArray(r.chats) ? r.chats : []);
      renderChats();
      fillPeopleSelect();
    } catch (e) {
      if (e.handled) return S.chats;
      showError(e);
      if (!S.chats) showEmpty(box, "Не удалось загрузить", "Проверьте связь и нажмите «Обновить».");
    }
    return S.chats;
  }
  function renderChats() {
    const box = $("chats-list");
    if (!S.chats || !S.chats.length) { showEmpty(box, "Чатов пока нет", "Добавьте Стеллу в группу или напишите ей в личку — чат появится здесь."); return; }
    const section = (title, list) => (list.length
      ? [h("h3", { class: "list-title" }, h("span", { text: title }), h("span", { class: "count", text: String(list.length) })), h("ul", { class: "list" }, list.map(chatItem))]
      : null);
    loaded(box);
    setKids(box, section("Группы", S.chats.filter((c) => c.is_group)), section("Личные", S.chats.filter((c) => !c.is_group)));
  }
  function chatItem(c) {
    const pause = pauseInfo(c);
    const meta = [`режим: ${chimeText(c.chime_level)}`,
      c.last_bot_at ? `ответ: ${ago(c.last_bot_at)}` : "ещё не отвечала"].join(" · ");
    const title = c.title || "Без названия";
    const btn = h("button", { type: "button", class: "chat-item" + (pause ? " is-paused" : "") },
      avatar(title, c.is_group ? "group" : ""),
      h("div", { class: "chat-item-body" },
        h("div", { class: "name-row" }, h("span", { class: "name", text: title }),
          c.last_message_at ? h("span", { class: "when", text: ago(c.last_message_at) }) : null),
        h("div", { class: "meta", text: meta }),
        h("div", { class: "badges" }, pause ? h("span", { class: "badge warn", text: pause }) : null, grudgeBadge(c))),
      icon("chev", "chev-r"));
    btn.addEventListener("click", () => openChat(c.id));
    return h("li", null, btn);
  }
  function openChat(id) {
    const c = (S.chats || []).find((x) => x.id === id);
    if (!c) return;
    Object.assign(S, { chat: c, chatSeq: S.chatSeq + 1, peopleChatId: c.id });
    $("chats-list-view").hidden = true;
    $("chat-view").hidden = false;
    if (!(history.state && history.state.stellaChat)) history.pushState({ stellaChat: true }, "");
    setVal(["send-text", "about-text"], "");
    $("about-text").disabled = $("about-save").disabled = true; // пока «Про чат» не загрузился
    $("about-notes").textContent = "Загрузка…";
    updateAboutCount();
    showSkeleton($("chat-msgs"), "msgs");
    renderChatHead();
    window.scrollTo(0, 0);
    loadMessages();
    loadAbout();
  }
  function closeChat() {
    Object.assign(S, { chat: null, chatSeq: S.chatSeq + 1 });
    $("chat-view").hidden = true;
    $("chats-list-view").hidden = false;
    $("chat-msgs").replaceChildren();
    setVal(["send-text", "about-text"], "");
    $("about-notes").textContent = "";
    if (S.chats) renderChats();
    loadChats();
  }
  // Системная кнопка «назад» на телефоне тоже закрывает чат (через popstate).
  function backToList() {
    if (history.state && history.state.stellaChat) history.back(); else closeChat();
  }
  function renderChatHead() {
    const c = S.chat;
    if (!c) return;
    $("chat-title").textContent = c.title || "Без названия";
    $("chat-sub").textContent = [c.is_group ? `группа · участников: ${Number(c.members) || 0}` : "личка", c.jid_masked || ""]
      .filter(Boolean).join(" · ");
    const pause = pauseInfo(c);
    setKids($("chat-badges"),
      pause ? h("span", { class: "badge warn", text: pause }) : null,
      h("span", { class: "badge accent", text: `режим: ${chimeText(c.chime_level)}` }),
      grudgeBadge(c),
      c.last_bot_at ? h("span", { class: "badge", text: `ответ: ${ago(c.last_bot_at)}` }) : null);
    $("unpause-btn").disabled = !pause;
    $("chime-select").value = CHIME.has(c.chime_level) ? c.chime_level : "";
  }
  async function loadMessages() {
    const c = S.chat, seq = S.chatSeq, box = $("chat-msgs");
    if (!c) return;
    try {
      const r = await api("GET", chatPath(c.id, "/messages?limit=60"));
      if (seq === S.chatSeq) renderMessages(Array.isArray(r.messages) ? r.messages : []);
    } catch (e) {
      if (seq !== S.chatSeq || e.handled) return;
      showError(e);
      if (!box.querySelector(".msg")) showEmpty(box, "Не удалось загрузить сообщения", "Нажмите ↻ вверху, чтобы попробовать снова.");
    }
  }
  function renderMessages(list) {
    const box = $("chat-msgs");
    if (!list.length) { showEmpty(box, "Сообщений пока нет", "Здесь появится переписка — и ваши сообщения от имени Стеллы."); return; }
    loaded(box);
    setKids(box, list.map((m) => {
      const mine = m.role === "assistant";
      const kind = m.kind && m.kind !== "text" ? `[${KINDS.get(m.kind) || String(m.kind)}]` : "";
      return h("div", { class: "msg " + (mine ? "assistant" : "user") },
        !mine && m.sender ? h("div", { class: "sender", text: m.sender }) : null,
        kind ? h("span", { class: "kind", text: kind }) : null,
        m.text ? h("div", { class: "text", text: m.text }) : null,
        h("div", { class: "time", text: fmtTime(m.at) }));
    }));
    box.scrollTop = box.scrollHeight;
  }
  async function onSend(e) {
    e.preventDefault();
    const c = S.chat, ta = $("send-text"), text = ta.value.trim();
    if (!c || $("send-btn").disabled) return;
    if (!text) { toast("Напишите текст", "bad"); ta.focus(); return; }
    if (!confirm(`Стелла отправит в «${c.title || "чат"}»:\n\n${clip(text, 300)}`)) return;
    const seq = S.chatSeq;
    await busy([$("send-btn"), ta], async () => {
      await api("POST", chatPath(c.id, "/send"), { text });
      if (seq === S.chatSeq) ta.value = "";
      toast("Отправлено");
      setTimeout(() => { if (seq === S.chatSeq) loadMessages(); }, 1500);
    });
  }
  // Действие в «Управлении»: на время запроса блокируем все кнопки карточки.
  async function chatAction(el, fn) {
    const c = S.chat;
    if (!c) return;
    const others = [...$("chat-controls").querySelectorAll("button, select")].filter((x) => x !== el);
    await busy([el, ...others], () => fn(c));
    if (S.chat === c) renderChatHead();
  }
  const onPause = (btn) => chatAction(btn, async (c) => {
    const minutes = Number(btn.dataset.pause);
    const r = await api("POST", chatPath(c.id, "/pause"), { minutes });
    c.paused_until = r.paused_until || new Date(Date.now() + minutes * 60000).toISOString();
    c.paused_by_owner = false;
    toast(`Пауза до ${fmtTime(c.paused_until)}`);
  });
  const onUnpause = () => chatAction($("unpause-btn"), async (c) => {
    await api("POST", chatPath(c.id, "/unpause"));
    c.paused_until = null;
    c.paused_by_owner = false;
    toast("Пауза снята");
  });
  function onChime() {
    const level = $("chime-select").value;
    if (!CHIME.has(level)) return;
    chatAction($("chime-select"), async (c) => {
      await api("POST", chatPath(c.id, "/chime"), { level });
      c.chime_level = level;
      toast(`Режим: ${CHIME.get(level)}`);
    });
  }
  const onPoke = () => chatAction($("poke-btn"), async (c) => {
    const seq = S.chatSeq;
    let r;
    try {
      r = await api("POST", chatPath(c.id, "/poke"));
    } catch (e) {
      if (e.status !== 0 || e.code !== "timeout") throw e;
      toast("Сервер долго отвечает — возможно, она ещё пишет. Обновите чат чуть позже");
      return;
    }
    if (r.queued) {
      toast("Стелла придумывает, что написать — загляните в чат через минуту");
      setTimeout(() => { if (seq === S.chatSeq) loadMessages(); }, 30000);
      return;
    }
    toast(r.sent ? "Стелла написала в чат" : "Чат на паузе или ей нечего сказать");
    if (r.sent) setTimeout(() => { if (seq === S.chatSeq) loadMessages(); }, 2000);
  });
  async function loadAbout() {
    const c = S.chat, seq = S.chatSeq;
    if (!c) return;
    try {
      const r = await api("GET", chatPath(c.id, "/about"));
      if (seq !== S.chatSeq) return;
      $("about-text").value = valueText(r.about);
      $("about-text").disabled = $("about-save").disabled = false;
      $("about-notes").textContent = r.notes ? valueText(r.notes) : "Пока пусто";
      updateAboutCount();
    } catch (e) {
      if (seq !== S.chatSeq || e.handled) return;
      $("about-notes").textContent = "Не удалось загрузить — нажмите ↻";
      showError(e);
    }
  }
  const updateAboutCount = () => { $("about-count").textContent = `${$("about-text").value.length} / ${ABOUT_MAX}`; };
  function onAboutSave() {
    const c = S.chat, ta = $("about-text");
    if (!c) return;
    if (ta.value.length > ABOUT_MAX) { toast(`Слишком длинно: максимум ${ABOUT_MAX} символов`, "bad"); return; }
    busy([$("about-save"), ta], async () => {
      await api("PUT", chatPath(c.id, "/about"), { about: ta.value });
      toast("Сохранено");
    });
  }
  const onChatRefresh = () => busy($("chat-refresh"), async () => {
    await loadMessages();
    if ($("about-text").disabled) await loadAbout();
    const list = await loadChats();
    const fresh = S.chat && list ? list.find((x) => x.id === S.chat.id) : null;
    if (fresh) { S.chat = fresh; renderChatHead(); }
  });

  // ---------- 3. Люди ----------
  function fillPeopleSelect() {
    const sel = $("people-chat"), list = S.chats || [];
    if (S.peopleChatId === null || !list.some((c) => c.id === S.peopleChatId)) S.peopleChatId = list.length ? list[0].id : null;
    setKids(sel, list.map((c) => h("option", { value: String(c.id), text: `${c.title || "Без названия"} (${c.is_group ? "группа" : "личка"})` })));
    if (S.peopleChatId !== null) sel.value = String(S.peopleChatId);
    sel.disabled = !list.length;
  }
  async function loadPeopleTab() {
    if (!S.chats) await loadChats(); else fillPeopleSelect();
    if (S.chats && S.chats.length) await loadPeople();
    else showEmpty($("people-list"), S.chats ? "Пока никого нет" : "Не удалось загрузить список чатов", S.chats ? "Люди появятся, когда в чатах начнут писать." : "Нажмите «Обновить».");
  }
  async function loadPeople() {
    const id = S.peopleChatId, box = $("people-list");
    if (id === null) { showEmpty(box, "Пока никого нет"); return; }
    const seq = ++S.peopleSeq;
    showSkeleton(box, "list");
    try {
      const r = await api("GET", chatPath(id, "/people"));
      if (seq !== S.peopleSeq) return;
      const people = (Array.isArray(r.people) ? r.people : []).slice()
        .sort((a, b) => (Number(b.msg_count) || 0) - (Number(a.msg_count) || 0));
      loaded(box);
      if (people.length) setKids(box, people.map((p) => personCard(id, p)));
      else showEmpty(box, "Пока никого нет", "Стелла запоминает людей, которые пишут в этом чате.");
    } catch (e) {
      if (seq !== S.peopleSeq || e.handled) return;
      showError(e);
      showEmpty(box, "Не удалось загрузить");
    }
  }
  const personName = (p) => p.name || p.push_name || p.ref || "Без имени";
  function personCard(chatId, p) {
    const bodyId = `person-body-${++S.uid}`;
    const body = h("div", { class: "person-body", id: bodyId, hidden: true });
    const head = h("button", { type: "button", class: "person-head", "aria-expanded": "false", "aria-controls": bodyId },
      avatar(personName(p)),
      h("div", { class: "who" }, h("div", { class: "name-row" }, h("span", { class: "name", text: personName(p) }), personBadge(p)),
        h("div", { class: "meta", text: personMeta(p) })),
      h("span", { class: "chev", "aria-hidden": "true" }));
    head.addEventListener("click", () => {
      const open = head.getAttribute("aria-expanded") !== "true";
      head.setAttribute("aria-expanded", open ? "true" : "false");
      body.hidden = !open;
      if (open && !body.firstChild) renderPersonBody(body, chatId, p);
    });
    return h("div", { class: "person" }, head, body);
  }
  function personBadge(p) {
    const pl = p.plan && typeof p.plan === "object" ? p.plan : null;
    if (!pl || pl.ended) return null;
    if (pl.admin) return h("span", { class: "badge", text: "админ" });
    if (pl.kind === "unlimited") return h("span", { class: "badge accent", text: "подписка" });
    return pl.kind === "limit" ? h("span", { class: "badge", text: "свой лимит" }) : null;
  }
  function personMeta(p) {
    const pl = p.plan && typeof p.plan === "object" ? p.plan : null;
    const plan = !pl || pl.admin ? "" : pl.kind === "unlimited" ? "⭐ подписка" : pl.kind === "limit" ? `лимит ${Number(pl.limit) || 0}/день` : "";
    return [p.nickname ? `прозвище: ${p.nickname}` : "", p.push_name && p.push_name !== p.name ? `в WhatsApp: ${p.push_name}` : "",
      p.phone_masked || "", `сообщений: ${Number(p.msg_count) || 0}`, plan].filter(Boolean).join(" · ");
  }
  // ---------- подписка: сколько ответов в день Стелла даёт человеку ----------
  const PLAN_KINDS = [["free", "Бесплатно (общий лимит)"], ["unlimited", "Подписка — без лимита"], ["limit", "Свой лимит в день"]];
  function fmtDay(sec) {
    const d = new Date(Number(sec) * 1000);
    return Number.isFinite(d.getTime()) ? `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()}` : "";
  }
  function planText(pl) {
    if (pl.admin) return "Владелец или админ бота — всегда без лимита";
    const until = pl.kind === "free" ? "" : pl.until ? ` до ${fmtDay(pl.until)}` : " навсегда";
    const daily = Number(pl.daily) || 0;
    const what = pl.kind === "unlimited" ? `Подписка без лимита${until}`
      : pl.kind === "limit" ? `Свой лимит: ${Number(pl.limit) || 0} в день${until}`
      : daily > 0 ? `Бесплатно: ${daily} ответов в день` : "Бесплатно, без лимита";
    const ended = pl.ended && pl.until ? ` (подписка закончилась ${fmtDay(pl.until)})` : "";
    return `${what}${ended}. Сегодня ответила: ${Number(pl.used_today) || 0}${daily > 0 ? ` из ${daily}` : ""}`;
  }
  function planSection(p, personPath, rerender) {
    const pl = p.plan && typeof p.plan === "object" ? p.plan : null;
    if (!pl) return null;
    const status = h("p", { class: "plan-status", text: planText(pl) });
    if (pl.admin) return h("div", {}, status);
    const ids = [`plan-kind-${++S.uid}`, `plan-days-${++S.uid}`, `plan-limit-${++S.uid}`];
    const kindSel = h("select", { id: ids[0] }, PLAN_KINDS.map(([v, t]) => h("option", { value: v, text: t })));
    kindSel.value = pl.kind === "unlimited" || pl.kind === "limit" ? pl.kind : "free";
    const left = pl.kind !== "free" && pl.until ? Math.max(1, Math.ceil((Number(pl.until) * 1000 - Date.now()) / 864e5)) : null;
    const daysIn = h("input", { type: "number", id: ids[1], min: 0, max: 3650, step: 1, inputMode: "numeric",
      value: String(left ?? (pl.kind === "free" ? 30 : 0)) });
    const limitIn = h("input", { type: "number", id: ids[2], min: 1, max: 10000, step: 1, inputMode: "numeric",
      value: String(Number(pl.limit) || 100) });
    const daysBox = h("div", {}, h("label", { for: ids[1], text: "На сколько дней (0 — навсегда)" }), daysIn);
    const limitBox = h("div", {}, h("label", { for: ids[2], text: "Ответов в день" }), limitIn);
    const sync = () => { daysBox.hidden = kindSel.value === "free"; limitBox.hidden = kindSel.value !== "limit"; };
    kindSel.addEventListener("change", sync);
    sync();
    const saveBtn = h("button", { type: "button", class: "btn primary", text: "Сохранить подписку" });
    saveBtn.addEventListener("click", () => busy(saveBtn, async () => {
      const kind = kindSel.value, days = Number(daysIn.value || 0), limit = Number(limitIn.value || 0);
      if (kind !== "free" && !(Number.isInteger(days) && days >= 0 && days <= 3650)) {
        toast("Дней: от 0 до 3650 (0 — навсегда)", "bad"); daysIn.focus(); return;
      }
      if (kind === "limit" && !(Number.isInteger(limit) && limit >= 1 && limit <= 10000)) {
        toast("Ответов в день: от 1 до 10000", "bad"); limitIn.focus(); return;
      }
      const r = await api("PUT", personPath("/plan"), { kind, days: kind === "free" ? 0 : days, limit: kind === "limit" ? limit : 0 });
      if (r.plan && typeof r.plan === "object") p.plan = r.plan;
      toast(kind === "free" ? "Подписка снята" : kind === "unlimited" ? "Подписка выдана" : "Лимит сохранён");
      rerender();
    }));
    return h("div", {}, status,
      h("div", { class: "plan-grid" }, h("div", {}, h("label", { for: ids[0], text: "Что выдать" }), kindSel), daysBox, limitBox),
      h("div", { class: "btn-row" }, saveBtn),
      h("p", { class: "muted small", text: "Кончится лимит — Стелла напишет, что нужно купить подписку, и даст контакт техподдержки. "
        + "Общий лимит для всех без подписки, текст и контакт — во вкладке «Настройки» (строки «Подписки: …»)." }));
  }
  // Что поменялось в анкете. Удалённое поле уходит как "" — сервер его стирает.
  function profileDiff(profile, recs) {
    const now = new Map();
    for (const r of recs) {
      const k = r.keyIn.value.trim(), v = r.valIn.value.trim();
      if (!k && v) return { err: r.keyIn };
      if (k) now.set(k, v);
    }
    const has = (k) => Object.prototype.hasOwnProperty.call(profile, k);
    const fields = Object.create(null);
    for (const k of Object.keys(profile)) if (!now.has(k)) fields[k] = "";
    for (const [k, v] of now) if (has(k) ? valueText(profile[k]).trim() !== v : v !== "") fields[k] = v;
    return { fields };
  }
  function renderPersonBody(body, chatId, p) {
    const profile = p.profile && typeof p.profile === "object" && !Array.isArray(p.profile) ? p.profile : {};
    const personPath = (tail) => chatPath(chatId, `/people/${encodeURIComponent(String(p.id))}${tail}`);
    const rows = h("div", { class: "kv-rows" });
    let recs = [];
    const addRow = (key, value, existing) => {
      const keyIn = h("input", { type: "text", value: key, readOnly: existing, maxLength: 64, placeholder: "поле", autocomplete: "off",
        "aria-label": existing ? `Поле «${key}»` : "Название нового поля" });
      const valIn = h("input", { type: "text", value, maxLength: 2000, placeholder: "значение", autocomplete: "off",
        "aria-label": existing ? `Значение поля «${key}»` : "Значение нового поля" });
      const del = h("button", { type: "button", class: "btn", text: "✕", title: "Убрать поле", "aria-label": `Убрать поле ${key}`.trim() });
      const rec = { row: h("div", { class: "kv-row" }, keyIn, valIn, del), keyIn, valIn };
      del.addEventListener("click", () => { rec.row.remove(); recs = recs.filter((x) => x !== rec); });
      recs.push(rec);
      rows.append(rec.row);
      return keyIn;
    };
    Object.entries(profile).forEach(([k, v]) => addRow(k, valueText(v), true));

    const addBtn = h("button", { type: "button", class: "btn", text: "Добавить поле" });
    addBtn.addEventListener("click", () => addRow("", "", false).focus());
    const saveBtn = h("button", { type: "button", class: "btn primary", text: "Сохранить анкету" });
    saveBtn.addEventListener("click", () => busy(saveBtn, async () => {
      const { fields, err } = profileDiff(profile, recs);
      if (err) { toast("Укажите название поля", "bad"); err.focus(); return; }
      if (!Object.keys(fields).length) { toast("Нет изменений"); return; }
      const r = await api("PUT", personPath("/profile"), { fields });
      if (r.profile && typeof r.profile === "object") p.profile = r.profile;
      else {
        const next = { ...profile };
        Object.keys(fields).forEach((k) => { if (fields[k] === "") delete next[k]; else next[k] = fields[k]; });
        p.profile = next;
      }
      toast("Анкета сохранена");
      renderPersonBody(body, chatId, p);
    }));
    const facts = Array.isArray(p.facts) ? p.facts : [];
    const forgetBtn = h("button", { type: "button", class: "btn danger wide", text: "Забыть все факты", disabled: !facts.length });
    forgetBtn.addEventListener("click", () => {
      if (!confirm(`Стелла забудет все факты про «${personName(p)}». Продолжить?`)) return;
      busy(forgetBtn, async () => {
        const r = await api("DELETE", personPath("/facts"));
        p.facts = [];
        toast(`Забыто фактов: ${Number(r.deleted) || 0}`);
        renderPersonBody(body, chatId, p);
      });
    });
    const rerender = () => {
      const meta = body.parentElement && body.parentElement.querySelector(".person-head .meta");
      if (meta) meta.textContent = personMeta(p);
      renderPersonBody(body, chatId, p);
    };
    const plan = planSection(p, personPath, rerender);
    setKids(body,
      plan ? h("h4", { class: "sub-title", text: "Подписка" }) : null,
      plan,
      h("h4", { class: "sub-title", text: "Анкета" }),
      recs.length ? null : h("p", { class: "muted small", text: "Пока пусто — можно добавить поле" }),
      rows,
      h("div", { class: "btn-row" }, addBtn, saveBtn),
      h("h4", { class: "sub-title", text: `Факты (${facts.length})` }),
      facts.length ? h("ul", { class: "facts" }, facts.map((f) => h("li", { text: valueText(f) })))
        : h("p", { class: "muted small", text: "Пока пусто" }),
      forgetBtn);
  }

  // ---------- 4. Ключи API: несколько ключей на сервис, активная модель ----------
  const PROVIDER_LOOK = new Map([["groq", "Gq"], ["openrouter", "OR"], ["gemini", "Ge"], ["openai", "AI"]]);
  const CLAUDE_BACKENDS = [["agent_sdk", "Claude · Agent SDK"], ["messages_api", "Claude · Messages API"]];
  const CUSTOM = "\u0000custom"; // значение пункта «Другая модель…» — не может совпасть с именем модели
  const keyPath = (id, tail) => `/keys/${encodeURIComponent(String(id))}${tail || ""}`;
  const safeUrl = (u) => (/^https:\/\/[^\s"'<>]+$/i.test(String(u || "")) ? String(u) : "");
  const providerIni = (p) => PROVIDER_LOOK.get(p.id) || String(p.name || p.id || "?").slice(0, 2);
  const providerCls = (id) => (PROVIDER_LOOK.has(id) ? `pv-${id}` : "pv-other");
  function keyStatus(k) {
    if (k.disabled) return ["выключен", "off"];
    const cd = toDate(k.cooldown_until);
    if (cd && cd.getTime() > Date.now()) return [`пауза до ${fmtTime(k.cooldown_until)}`, "warn"];
    if (k.last_error) return ["ошибка", "bad"];
    return ["работает", "ok"];
  }
  async function loadKeys(silent) {
    const box = $("keys-body"), seq = ++S.keysSeq;
    if (!S.keys) showSkeleton(box, "list", 4);
    try {
      const r = await api("GET", "/keys");
      if (seq !== S.keysSeq) return;
      S.keys = {
        providers: (Array.isArray(r.providers) ? r.providers : []).filter((p) => p && p.id),
        keys: (Array.isArray(r.keys) ? r.keys : []).filter((k) => k && k.id),
        active: r.active && typeof r.active === "object" ? r.active : {},
      };
      renderKeys();
    } catch (e) {
      if (seq !== S.keysSeq || e.handled) return;
      if (e.status === 404) { // сервер ещё старый — раздела нет
        S.keys = null;
        showEmpty(box, "Раздел ключей пока не включён на сервере",
          "Обновите бота до новой версии — и здесь можно будет добавлять ключи Groq, OpenRouter, Gemini и OpenAI и переключать модель.");
        return;
      }
      if (!silent) showError(e);
      if (!S.keys) showEmpty(box, "Не удалось загрузить ключи", "Проверьте связь и нажмите «Обновить».");
    }
  }
  function renderKeys() {
    const box = $("keys-body");
    const ui = { active: h("div", { class: "card active-card" }), list: h("div", { class: "providers" }) };
    S.keysUI = ui;
    loaded(box);
    setKids(box,
      ui.active,
      addKeyCard(ui),
      h("div", { class: "info-note", role: "note" }, icon("swap"),
        h("p", { text: "Несколько ключей одного сервиса работают по очереди: когда у одного кончается лимит, Стелла сама переключается на следующий." })),
      h("h3", { class: "list-title" }, h("span", { text: "Сервисы" }), h("span", { class: "count", text: String(S.keys.providers.length) })),
      ui.list);
    renderActive();
    renderKeyList();
  }
  // --- активная модель ---
  function backendChoices() {
    const list = S.keys.providers.map((p) => [String(p.id), String(p.name || p.id)]);
    for (const [id, name] of CLAUDE_BACKENDS) if (!list.some(([x]) => x === id)) list.push([id, name]);
    return list;
  }
  function renderActive() {
    const ui = S.keysUI, a = S.keys.active || {};
    const cur = String(a.backend || "");
    const ids = [`act-pv-${++S.uid}`, `act-model-${++S.uid}`, `act-custom-${++S.uid}`];
    const pvSel = h("select", { id: ids[0] }, backendChoices().map(([v, t]) => h("option", { value: v, text: t })));
    if (backendChoices().some(([v]) => v === cur)) pvSel.value = cur;
    const modelSel = h("select", { id: ids[1] });
    const custom = h("input", { type: "text", id: ids[2], maxLength: 200, autocomplete: "off", autocapitalize: "off", spellcheck: "false", placeholder: "например, openai/gpt-oss-120b" });
    const modelBox = h("div", {}, h("label", { for: ids[1], text: "Модель" }), modelSel);
    const customBox = h("div", {}, h("label", { for: ids[2], text: "Своя модель" }), custom);
    const fillModels = () => {
      const p = S.keys.providers.find((x) => String(x.id) === pvSel.value);
      const models = p && Array.isArray(p.models) ? p.models.map(String) : [];
      const def = p && p.default_model ? String(p.default_model) : "";
      if (def && !models.includes(def)) models.unshift(def);
      const opts = [h("option", { value: "", text: def ? `по умолчанию (${def})` : "по умолчанию" })];
      models.forEach((m) => opts.push(h("option", { value: m, text: m })));
      opts.push(h("option", { value: CUSTOM, text: "Другая модель…" }));
      setKids(modelSel, opts);
      const want = pvSel.value === cur ? String(a.model || "") : "";
      if (!want) modelSel.value = "";
      else if (models.includes(want)) modelSel.value = want;
      else { modelSel.value = CUSTOM; custom.value = want; }
      customBox.hidden = modelSel.value !== CUSTOM;
    };
    pvSel.addEventListener("change", () => { custom.value = ""; fillModels(); });
    modelSel.addEventListener("change", () => { customBox.hidden = modelSel.value !== CUSTOM; if (!customBox.hidden) custom.focus(); });
    fillModels();
    const useBtn = h("button", { type: "button", class: "btn primary" }, icon("star"), h("span", { text: "Использовать сейчас" }));
    useBtn.addEventListener("click", () => busy([useBtn, pvSel, modelSel, custom], async () => {
      const model = modelSel.value === CUSTOM ? custom.value.trim() : modelSel.value;
      if (modelSel.value === CUSTOM && !model) { toast("Впишите название модели", "bad"); custom.focus(); return; }
      const body = { backend: pvSel.value };
      if (model) body.model = model;
      const r = await api("PUT", "/keys/active", body);
      if (!S.keys) return;
      S.keys.active = r.active && typeof r.active === "object" ? r.active : { backend: body.backend, model: model || null };
      S.lastOverview = 0; // обзор обновится при следующем открытии
      toast(`Теперь Стелла отвечает через ${backendName(S.keys.active.backend)}`);
      renderActive();
    }));
    const off = cur === "off" || !cur;
    setKids(ui.active,
      h("div", { class: "card-head" },
        h("h3", { class: "card-title", text: "Активная модель" }),
        h("span", { class: "pill " + (off ? "warn" : "ok"), text: off ? "выключена" : "работает" })),
      h("div", { class: "active-now" },
        h("span", { class: "active-mark" }, icon("star")),
        h("div", { class: "active-text" },
          h("div", { class: "active-name", text: off ? "Модель выключена" : backendName(cur) }),
          a.model && !off ? h("div", { class: "mono-chip", text: String(a.model) }) : null,
          a.backend_after && a.backend_after !== cur
            ? h("div", { class: "muted small", text: `по расписанию потом: ${backendName(a.backend_after)}` }) : null)),
      h("div", { class: "form-grid" }, h("div", {}, h("label", { for: ids[0], text: "Сервис" }), pvSel), modelBox, customBox),
      h("div", { class: "btn-row" }, useBtn),
      h("p", { class: "muted small", text: "Переключает Стеллу сразу, без перезапуска. Для Groq, OpenRouter, Gemini и OpenAI нужен хотя бы один включённый ключ." }));
  }
  // --- добавить ключ ---
  function addKeyCard(ui) {
    const ids = [`add-pv-${++S.uid}`, `add-key-${++S.uid}`, `add-label-${++S.uid}`];
    const pvSel = h("select", { id: ids[0] }, S.keys.providers.map((p) => h("option", { value: String(p.id), text: String(p.name || p.id) })));
    const keyIn = h("input", { type: "password", id: ids[1], autocomplete: "off", autocapitalize: "off", spellcheck: "false", maxLength: 400, placeholder: "вставьте ключ", "aria-describedby": `${ids[1]}-hint` });
    const labelIn = h("input", { type: "text", id: ids[2], autocomplete: "off", maxLength: 60, placeholder: "например, основной" });
    const result = h("div", { class: "test-result", role: "status", "aria-live": "polite", hidden: true });
    const submit = h("button", { type: "submit", class: "btn primary" }, icon("plus"), h("span", { text: "Добавить и проверить" }));
    const hint = h("p", { class: "hint", id: `${ids[1]}-hint` });
    const syncHint = () => {
      const p = S.keys && S.keys.providers.find((x) => String(x.id) === pvSel.value);
      hint.textContent = p && p.hint ? String(p.hint) : "Ключ хранится только на сервере. Здесь потом будет видно только его начало и конец.";
    };
    pvSel.addEventListener("change", syncHint);
    syncHint();
    const showResult = (kind, title, detail) => {
      result.hidden = false;
      result.className = `test-result ${kind}`;
      setKids(result, h("b", { text: title }), detail ? h("span", { text: clip(String(detail), 300) }) : null);
    };
    const form = h("form", { class: "card add-card", novalidate: true },
      h("div", { class: "card-head" }, h("h3", { class: "card-title", text: "Добавить ключ" }), icon("key", "head-ico")),
      h("div", { class: "form-grid" },
        h("div", {}, h("label", { for: ids[0], text: "Сервис" }), pvSel),
        h("div", { class: "span-2" }, h("label", { for: ids[1], text: "Ключ API" }), keyIn, hint),
        h("div", {}, h("label", { for: ids[2] }, "Подпись ", h("span", { class: "opt", text: "— необязательно" })), labelIn)),
      h("div", { class: "btn-row" }, submit),
      result);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (submit.disabled) return;
      const key = keyIn.value.trim();
      if (!pvSel.value) { toast("Выберите сервис", "bad"); return; }
      if (!key) { toast("Вставьте ключ", "bad"); keyIn.focus(); return; }
      const body = { provider: pvSel.value, key };
      if (labelIn.value.trim()) body.label = labelIn.value.trim();
      keyIn.value = ""; // ключ в поле не держим — ни при успехе, ни при ошибке
      const els = [submit, pvSel, keyIn, labelIn];
      els.forEach((el) => { el.disabled = true; });
      submit.setAttribute("aria-busy", "true");
      showResult("wait", "Проверяю ключ…", "");
      try {
        const r = await api("POST", "/keys", body);
        body.key = "";
        const t = r.test && typeof r.test === "object" ? r.test : null;
        if (!t || t.ok) showResult("ok", "Ключ добавлен и работает", t && t.detail);
        else showResult("bad", "Ключ добавлен, но проверка не прошла", t.detail);
        labelIn.value = "";
        if (S.keys && r.key && r.key.id) {
          S.keys.keys = S.keys.keys.filter((k) => k.id !== r.key.id).concat([r.key]);
          renderKeyList();
        } else loadKeys(true);
      } catch (err) {
        body.key = "";
        if (err.handled) return;
        showResult("bad", "Ключ не добавлен", errText(err));
      } finally {
        els.forEach((el) => { el.disabled = false; });
        submit.removeAttribute("aria-busy");
      }
    });
    ui.addProvider = pvSel;
    ui.addKey = keyIn;
    return form;
  }
  // --- карточки сервисов со списком ключей ---
  function renderKeyList() {
    const ui = S.keysUI;
    if (!ui || !S.keys) return;
    const known = new Set(S.keys.providers.map((p) => String(p.id)));
    const groups = S.keys.providers.map((p) => [p, S.keys.keys.filter((k) => String(k.provider) === String(p.id))]);
    const others = S.keys.keys.filter((k) => !known.has(String(k.provider)));
    if (others.length) groups.push([{ id: "", name: "Другие" }, others]);
    if (!groups.length) { setKids(ui.list, emptyBox("Сервер не прислал список сервисов")); return; }
    setKids(ui.list, groups.map(([p, keys]) => providerCard(p, keys)));
  }
  function providerCard(p, keys) {
    const url = safeUrl(p.signup_url);
    const works = keys.filter((k) => keyStatus(k)[1] === "ok").length;
    const addBtn = p.id ? h("button", { type: "button", class: "btn small ghost" }, icon("plus"), h("span", { text: "Ключ" })) : null;
    if (addBtn) {
      addBtn.addEventListener("click", () => {
        const ui = S.keysUI;
        if (!ui) return;
        ui.addProvider.value = String(p.id);
        ui.addProvider.dispatchEvent(new Event("change"));
        ui.addKey.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
        ui.addKey.focus({ preventScroll: true });
      });
    }
    const active = S.keys.active && String(S.keys.active.backend) === String(p.id);
    return h("article", { class: "card provider " + providerCls(String(p.id)) },
      h("div", { class: "provider-head" },
        h("span", { class: "pv-ini", "aria-hidden": "true", text: providerIni(p) }),
        h("div", { class: "provider-title" },
          h("div", { class: "name-row" }, h("h4", { class: "provider-name", text: String(p.name || p.id) }),
            active ? h("span", { class: "badge accent", text: "активен" }) : null),
          h("div", { class: "muted small", text: keys.length
            ? `${keys.length} ${plural(keys.length, ["ключ", "ключа", "ключей"])} · работает ${works}`
            : "ключей нет" })),
        addBtn),
      p.hint ? h("p", { class: "provider-hint", text: String(p.hint) }) : null,
      url ? h("a", { class: "ext-link", href: url, target: "_blank", rel: "noopener noreferrer" },
        h("span", { text: "Как получить ключ" }), icon("ext")) : null,
      keys.length ? h("ul", { class: "key-list" }, keys.map(keyItem)) : null);
  }
  function keyItem(k) {
    const [stText, stCls] = keyStatus(k);
    const label = k.label ? String(k.label) : "";
    const name = `${String(k.masked || "ключ")}${label ? ` (${label})` : ""}`;
    const testBtn = h("button", { type: "button", class: "btn small", text: "Проверить" });
    const toggleBtn = h("button", { type: "button", class: "btn small", text: k.disabled ? "Включить" : "Выключить" });
    const delBtn = h("button", { type: "button", class: "btn small danger", text: "Удалить" });
    const all = [testBtn, toggleBtn, delBtn];
    const replaceKey = (nk) => {
      if (!S.keys || !nk || !nk.id) return;
      S.keys.keys = S.keys.keys.map((x) => (x.id === nk.id ? nk : x));
    };
    testBtn.addEventListener("click", () => busy(all, async () => {
      const r = await api("POST", keyPath(k.id, "/test"));
      toast(r.ok ? `Ключ работает${r.detail ? ": " + clip(String(r.detail), 120) : ""}` : `Ключ не работает${r.detail ? ": " + clip(String(r.detail), 160) : ""}`, r.ok ? "" : "bad");
      if (r.key && r.key.id) { replaceKey(r.key); renderKeyList(); } else loadKeys(true);
    }));
    toggleBtn.addEventListener("click", () => busy(all, async () => {
      const r = await api("PATCH", keyPath(k.id), { disabled: !k.disabled });
      replaceKey(r.key && r.key.id ? r.key : { ...k, disabled: !k.disabled });
      toast(k.disabled ? "Ключ включён" : "Ключ выключен — Стелла его пропускает");
      renderKeyList();
    }));
    delBtn.addEventListener("click", () => {
      if (!confirm(`Удалить ключ ${name}? Вернуть его можно, только добавив заново.`)) return;
      busy(all, async () => {
        await api("DELETE", keyPath(k.id));
        if (S.keys) S.keys.keys = S.keys.keys.filter((x) => x.id !== k.id);
        toast("Ключ удалён");
        renderKeyList();
      });
    });
    const meta = [`использований: ${Number(k.uses) || 0}`,
      k.last_used ? `последний раз ${ago(k.last_used)}` : "ещё не использовался",
      k.added_at ? `добавлен ${fmtTime(k.added_at)}` : ""].filter(Boolean).join(" · ");
    return h("li", { class: "key-item" + (k.disabled ? " is-off" : "") },
      h("div", { class: "key-top" },
        h("div", { class: "key-id" },
          h("code", { class: "key-mask", text: String(k.masked || "••••") }),
          label ? h("span", { class: "key-label", text: label }) : null),
        h("span", { class: `pill ${stCls}`, text: stText })),
      k.last_error && !k.disabled ? h("p", { class: "key-err", text: clip(String(k.last_error), 300) }) : null,
      h("p", { class: "key-meta", text: meta }),
      h("div", { class: "key-actions" }, all));
  }

  // ---------- 5. Настройки (форма строится по описаниям с сервера) ----------
  function setDirty(v) {
    S.settingsDirty = v;
    $("settings-dirty").hidden = !v;
  }
  async function loadSettings() {
    const box = $("settings-body");
    if (!S.settings) showSkeleton(box, "form", 6);
    try {
      const r = await api("GET", "/settings");
      renderSettings(Array.isArray(r.settings) ? r.settings : []);
    } catch (e) {
      if (e.handled) return;
      showError(e);
      if (!S.settings) showEmpty(box, "Не удалось загрузить");
    }
  }
  function renderSettings(list) {
    S.settings = list;
    S.settingCtl = [];
    setDirty(false);
    loaded($("settings-body"));
    if (list.length) setKids($("settings-body"), list.map(settingField));
    else showEmpty($("settings-body"), "Настроек нет");
  }
  function settingField(d, i) {
    const id = `set-${i}`;
    const hintId = d.hint ? `${id}-hint` : null;
    const common = { id, "aria-describedby": hintId };
    let el;
    if (d.type === "bool") {
      el = h("input", { type: "checkbox", checked: Boolean(d.value), ...common });
    } else if (d.type === "select") {
      const cur = valueText(d.value);
      const opts = (Array.isArray(d.options) ? d.options : []).map(String);
      if (!opts.includes(cur)) opts.unshift(cur);
      el = h("select", common, opts.map((o) => h("option", { value: o, text: o === "" ? "—" : o })));
      el.value = cur;
    } else if (d.type === "number") {
      el = h("input", { type: "number", step: "any", min: d.min ?? null, max: d.max ?? null, value: valueText(d.value), ...common });
    } else {
      const v = valueText(d.value);
      el = v.length > 80 || v.includes("\n")
        ? h("textarea", { rows: 3, value: v, ...common })
        : h("input", { type: "text", value: v, autocomplete: "off", ...common });
    }
    el.addEventListener("input", () => setDirty(true));
    el.addEventListener("change", () => setDirty(true));
    S.settingCtl.push({ d, el });
    const label = String(d.label || d.key), keyTag = h("span", { class: "key", text: String(d.key) });
    return h("div", { class: "setting" },
      d.type === "bool" ? h("label", { class: "check switch", for: id }, el, h("span", { class: "check-text" }, h("span", { text: label }), keyTag)) : h("label", { for: id }, label, keyTag),
      d.type === "bool" ? null : el,
      hintId ? h("p", { class: "hint", id: hintId, text: String(d.hint) }) : null);
  }
  function readSetting({ d, el }) {
    const label = d.label || d.key;
    if (d.type === "bool") return { v: el.checked };
    if (d.type !== "number") return { v: el.value };
    const raw = el.value.trim(), n = Number(raw);
    if (raw === "" || !Number.isFinite(n)) return { err: `«${label}»: нужно число` };
    const lo = d.min ?? null, hi = d.max ?? null;
    if ((lo !== null && n < lo) || (hi !== null && n > hi)) return { err: `«${label}»: от ${lo ?? "…"} до ${hi ?? "…"}` };
    return { v: n };
  }
  function sameValue(d, v) {
    if (d.type === "bool") return Boolean(d.value) === v;
    if (d.type === "number") return d.value !== null && d.value !== "" && Number(d.value) === v;
    return valueText(d.value) === v;
  }
  async function saveSettings() {
    const changed = Object.create(null);
    for (const ctl of S.settingCtl) {
      const r = readSetting(ctl);
      if (r.err) { toast(r.err, "bad"); ctl.el.focus(); return; }
      if (!sameValue(ctl.d, r.v)) changed[ctl.d.key] = r.v;
    }
    if (!Object.keys(changed).length) { toast("Нечего сохранять"); setDirty(false); return; }
    await busy($("settings-save"), async () => {
      const r = await api("PUT", "/settings", changed); // уходят только изменённые ключи
      if (Array.isArray(r.settings)) renderSettings(r.settings);
      else { setDirty(false); await loadSettings(); }
      toast("Сохранено");
    });
  }

  // ---------- 6. Журнал ----------
  async function loadLog(silent) {
    if (S.loading.log) return;
    S.loading.log = true;
    S.lastLog = Date.now();
    const box = $("log-list");
    if (!S.log.length) showSkeleton(box, "log", 12);
    try {
      const r = await api("GET", "/log?limit=200");
      S.log = Array.isArray(r.lines) ? r.lines : [];
      renderLog();
    } catch (e) {
      if (e.handled) return;
      if (!silent) showError(e);
      if (!S.log.length) showEmpty(box, "Не удалось загрузить");
    } finally {
      S.loading.log = false;
    }
  }
  function renderLog() {
    const box = $("log-list");
    const atBottom = !box.querySelector(".log-line") || box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    const q = $("log-filter").value.trim().toLowerCase();
    const lines = q ? S.log.filter((l) => `${l.level} ${l.text}`.toLowerCase().includes(q)) : S.log;
    if (!lines.length) { showEmpty(box, S.log.length ? "Ничего не найдено" : "Журнал пуст", S.log.length ? "Попробуйте другое слово." : ""); return; }
    loaded(box);
    setKids(box, lines.map((l) => {
      const up = String(l.level || "INFO").toUpperCase();
      const lv = /^[A-Z]{1,10}$/.test(up) ? up : "INFO"; // уровень попадает в имя класса — только буквы
      return h("div", { class: `log-line lvl-${lv}` },
        h("span", { class: "t", text: fmtTime(l.at, true) }), " ",
        h("span", { class: "l", text: lv }), " ",
        h("span", { class: "m", text: valueText(l.text) }));
    }));
    if (atBottom) box.scrollTop = box.scrollHeight;
  }

  // ---------- события ----------
  function bindEvents() {
    on("step1", "submit", onStep1);
    on("step2", "submit", onStep2);
    on("step2-back", "click", () => { setLoginMsg("", ""); goStep(1); });
    on("server-change", "click", () => { renderServerBox(true); $("server-input").focus(); });
    on("logout-btn", "click", logout);
    on("logout-all", "click", logoutAll);
    TABS.forEach((t) => on("tab-" + t, "click", () => {
      if (t === S.tab && t === "chats" && S.chat) backToList(); else selectTab(t, false);
    }));
    document.querySelector(".tabs").addEventListener("keydown", onTabKey);

    on("ov-refresh", "click", (e) => busy(e.currentTarget, () => loadOverview(false)));
    on("ov-unpause-all", "click", (e) => bulkAction(e.currentTarget, "/actions/unpause_all",
      "Снять паузу во всех чатах?", (n) => `Пауз снято: ${n}`));
    on("ov-forgive-all", "click", (e) => bulkAction(e.currentTarget, "/actions/forgive_all",
      "Стелла перестанет обижаться на всех. Продолжить?", (n) => `Обид снято: ${n}`));

    on("chats-refresh", "click", (e) => busy(e.currentTarget, loadChats));
    on("chat-back", "click", backToList);
    on("chat-refresh", "click", onChatRefresh);
    on("send-form", "submit", onSend);
    on("send-text", "keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) onSend(e); });
    document.querySelectorAll("#chat-controls [data-pause]").forEach((b) => b.addEventListener("click", () => onPause(b)));
    on("unpause-btn", "click", onUnpause);
    on("chime-select", "change", onChime);
    on("poke-btn", "click", onPoke);
    on("about-text", "input", updateAboutCount);
    on("about-save", "click", onAboutSave);

    on("people-chat", "change", (e) => { S.peopleChatId = Number(e.target.value); loadPeople(); });
    on("people-refresh", "click", (e) => busy(e.currentTarget, async () => { await loadChats(); await loadPeople(); }));
    on("keys-refresh", "click", (e) => busy(e.currentTarget, () => loadKeys(false)));
    on("settings-save", "click", saveSettings);
    on("settings-refresh", "click", (e) => {
      if (S.settingsDirty && !confirm("Есть несохранённые изменения. Сбросить их?")) return;
      busy(e.currentTarget, loadSettings);
    });
    on("log-refresh", "click", (e) => busy(e.currentTarget, () => loadLog(false)));
    on("log-filter", "input", renderLog);
    on("log-auto", "change", (e) => { S.logAuto = e.target.checked; if (S.logAuto) loadLog(true); });
    on("toast", "click", () => { $("toast").hidden = true; });

    // Активность — только действия человека (не scroll: его вызывает и автопрокрутка).
    ["pointerdown", "keydown", "wheel", "touchstart"].forEach((ev) =>
      document.addEventListener(ev, markActive, { passive: true, capture: true }));
    document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") heartbeat(); });
    window.addEventListener("popstate", () => { if (S.chat) closeChat(); });
  }

  // ---------- запуск ----------
  function init() {
    if (window.top !== window.self) { // защита от кликджекинга: внутри чужой страницы не работаем
      document.body.replaceChildren(h("p", { class: "noscript", text: "Панель нельзя открывать внутри другой страницы." }));
      return;
    }
    const prevSaved = normServer(local.get(K.server));
    const { server, notice, untrusted } = resolveServer();
    S.server = server;
    if (server && !untrusted) local.set(K.server, server);
    if (server !== prevSaved) clearToken();
    bindEvents();
    const token = getToken();
    if (!token || !server) { showLogin(notice ? notice[0] : "", notice ? notice[1] : ""); return; }
    const last = Number(sess.get(K.active)) || 0, exp = Number(sess.get(K.exp)) || 0;
    if (last && Date.now() - last > IDLE_MS) {
      clearToken();
      request("POST", "/logout", {}, token).catch(() => { /* ошибки не важны */ });
      showLogin("Вы вышли автоматически: 30 минут без действий", "");
    } else if (exp && Date.now() > exp) {
      clearToken();
      showLogin("Сессия закончилась, войдите снова", "bad");
    } else {
      enterApp();
    }
  }

  init();
})();

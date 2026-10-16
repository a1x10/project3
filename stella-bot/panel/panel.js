/* Стелла · панель — логика интерфейса.
 * Правила безопасности: DOM строится только через createElement + textContent
 * (никакого HTML из строк), токен живёт только в sessionStorage, все запросы —
 * без cookies, без кэша, с таймаутом. */
"use strict";

(() => {
  // ---------- константы ----------
  const API = "/admin/api";
  const TIMEOUT_MS = 20000;
  const IDLE_MS = 30 * 60 * 1000;
  const OVERVIEW_EVERY = 30000;
  const LOG_EVERY = 10000;
  const ABOUT_MAX = 4000;
  const K = {
    server: "stella.server", token: "stella.token", exp: "stella.token_exp",
    active: "stella.last_active", tab: "stella.tab",
  };
  const TABS = ["overview", "chats", "people", "settings", "log"];
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
  const FIELD_PROPS = new Set(["value", "checked", "disabled", "hidden", "readOnly", "maxLength", "rows", "tabIndex"]);

  const $ = (id) => document.getElementById(id);

  const S = {
    server: "", tab: "overview",
    chats: null, chat: null, chatSeq: 0,
    peopleChatId: null, peopleSeq: 0,
    settings: null, settingCtl: [], settingsDirty: false,
    log: [], logAuto: false,
    lastOverview: 0, lastLog: 0, lastActive: 0, lastSaved: 0,
    loading: { overview: false, log: false },
    beat: 0, lockTimer: 0, lockUntil: 0, toastTimer: 0,
    p1: "", loginBusy: false, uid: 0,
  };
  let memToken = ""; // запасной вариант, только если sessionStorage недоступен

  // ---------- DOM-помощники (только textContent) ----------
  const clean = (kids) => kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false);

  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = String(v);
      else if (k === "on") for (const [ev, fn] of Object.entries(v)) el.addEventListener(ev, fn);
      else if (FIELD_PROPS.has(k)) el[k] = v;
      else el.setAttribute(k, v === true ? "" : String(v));
    }
    for (const kid of clean(kids)) el.append(kid instanceof Node ? kid : String(kid));
    return el;
  }
  const setKids = (box, ...kids) => box.replaceChildren(...clean(kids));
  const showEmpty = (box, text) => box.replaceChildren(h("p", { class: "placeholder", text }));

  // ---------- хранилища (в приватном режиме могут бросать исключения) ----------
  function storage(name) {
    return {
      get(k) { try { return window[name].getItem(k); } catch (_) { return null; } },
      set(k, v) { try { window[name].setItem(k, String(v)); return true; } catch (_) { return false; } },
      del(k) { try { window[name].removeItem(k); } catch (_) { /* хранилище недоступно */ } },
    };
  }
  const local = storage("localStorage");
  const sess = storage("sessionStorage");

  const getToken = () => sess.get(K.token) || memToken;
  function setToken(token, expiresIn) {
    memToken = sess.set(K.token, token) ? "" : token;
    const sec = Number(expiresIn);
    if (sec > 0) sess.set(K.exp, Date.now() + sec * 1000);
    else sess.del(K.exp);
  }
  function clearToken() {
    memToken = "";
    sess.del(K.token);
    sess.del(K.exp);
    sess.del(K.active);
  }

  // ---------- форматирование ----------
  const pad = (n) => String(n).padStart(2, "0");
  const clip = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);
  const usd = (n) => "$" + (Number(n) || 0).toFixed(2);
  const valueText = (v) => (v === null || v === undefined ? "" : typeof v === "object" ? JSON.stringify(v) : String(v));
  const chimeText = (lvl) => CHIME.get(lvl) || "по умолчанию";

  function toDate(iso) {
    if (!iso) return null;
    const t = Date.parse(iso);
    return Number.isFinite(t) ? new Date(t) : null;
  }
  function dayOffset(d) {
    const n = new Date();
    const a = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const b = new Date(n.getFullYear(), n.getMonth(), n.getDate());
    return Math.round((a - b) / 86400000);
  }
  // «HH:MM» сегодня, «вчера HH:MM», «завтра HH:MM», иначе «DD.MM HH:MM» — по местному времени
  function fmtTime(iso, withSec) {
    const d = toDate(iso);
    if (!d) return "";
    const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}${withSec ? ":" + pad(d.getSeconds()) : ""}`;
    const off = dayOffset(d);
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
    if (d) return `${d} д ${hr} ч`;
    if (hr) return `${hr} ч ${m} мин`;
    return `${m} мин`;
  }
  function switchText(v) {
    const s = String(v);
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
    if (!m) return s;
    const n = new Date();
    const today = `${n.getFullYear()}-${pad(n.getMonth() + 1)}-${pad(n.getDate())}`;
    const day = `${m[3]}.${m[2]}.${m[1]}`;
    return s.slice(0, 10) <= today ? `с ${day} (уже действует)` : `с ${day} — запасная модель`;
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

  function resolveServer() {
    let notice = null;
    let fromHash = null;
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
    if (fromHash) {
      if (saved && saved !== fromHash) {
        notice = [`Адрес сервера взят из ссылки: ${hostOf(fromHash)}. Вводите пароли, только если это ваш бот.`, "warn"];
      }
      return { server: fromHash, notice };
    }
    return { server: saved || "", notice };
  }

  function setServer(url) {
    if (url !== S.server) clearToken(); // токен от другого сервера не годится
    S.server = url;
    local.set(K.server, url);
  }

  // ---------- сеть ----------
  class ApiError extends Error {
    constructor(status, code, detail) {
      super(code || "error");
      this.status = status;
      this.code = code ? String(code) : "";
      this.detail = detail ? String(detail) : "";
      this.handled = false;
    }
  }

  async function request(method, path, body, token) {
    if (!S.server) throw new ApiError(0, "network");
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
    const headers = { Accept: "application/json" };
    const init = {
      method, headers, credentials: "omit", cache: "no-store", mode: "cors",
      redirect: "error", referrerPolicy: "no-referrer", signal: ctrl.signal,
    };
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
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

  // Запрос с токеном. 401 → выход на экран входа.
  async function api(method, path, body) {
    const token = getToken();
    if (!token) {
      expire();
      const e = new ApiError(401, "unauthorized");
      e.handled = true;
      throw e;
    }
    const payload = body === undefined && (method === "POST" || method === "PUT") ? {} : body;
    const r = await request(method, path, payload, token);
    if (r.status === 401) {
      if (getToken() === token) expire();
      const e = new ApiError(401, "unauthorized");
      e.handled = true;
      throw e;
    }
    if (!r.ok) throw new ApiError(r.status, r.data && r.data.error, r.data && r.data.detail);
    return r.data || {};
  }

  function errText(e) {
    if (!(e instanceof ApiError)) return "Что-то пошло не так. Попробуйте ещё раз";
    if (e.status === 0) {
      return e.code === "timeout"
        ? "Сервер долго не отвечает. Попробуйте ещё раз"
        : "Сервер не отвечает. Проверьте адрес и что бот запущен";
    }
    if (e.detail) return clip(e.detail, 200);
    const base = ERR_TEXT[e.status] || (e.status >= 500 ? "Ошибка на сервере" : "Не получилось");
    const code = /^[\w.-]{1,40}$/.test(e.code) ? e.code : `код ${e.status}`;
    return `${base} (${code})`;
  }
  function showError(e) {
    if (e && e.handled) return;
    toast(errText(e), "bad");
  }

  function toast(text, kind) {
    const el = $("toast");
    el.textContent = text;
    el.className = "toast" + (kind ? " " + kind : "");
    el.hidden = false;
    clearTimeout(S.toastTimer);
    S.toastTimer = setTimeout(() => { el.hidden = true; }, kind === "bad" ? 6000 : 3000);
  }

  // Блокирует кнопки на время запроса (защита от двойного нажатия).
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

  // ---------- вход ----------
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
    const target = n === 2 ? $("p2") : !S.server ? $("server-input") : $("p1");
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
    $("step1-btn").disabled = locked || S.loginBusy;
    $("step2-btn").disabled = locked || S.loginBusy;
    const t = $("lock-timer");
    t.hidden = !locked;
    if (locked) {
      t.textContent = `Можно снова через ${Math.floor(left / 60)}:${pad(left % 60)}`;
    } else if (S.lockTimer) {
      clearInterval(S.lockTimer);
      S.lockTimer = 0;
      S.lockUntil = 0;
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
    const v = $("p1").value;
    if (!v) {
      setLoginMsg("Введите пароль 1", "bad");
      $("p1").focus();
      return;
    }
    S.p1 = v;
    $("p1").value = "";
    setLoginMsg("", "");
    goStep(2);
  }

  async function onStep2(e) {
    e.preventDefault();
    if (S.loginBusy || isLocked()) return;
    if (!S.p1) { goStep(1); return; }
    if (!$("p2").value) {
      setLoginMsg("Введите пароль 2", "bad");
      $("p2").focus();
      return;
    }
    let body = { p1: S.p1, p2: $("p2").value };
    S.p1 = "";
    $("p1").value = "";
    $("p2").value = "";
    S.loginBusy = true;
    updateLock();
    setLoginMsg("Проверяю…", "");
    let r = null;
    try {
      r = await request("POST", "/login", body, null);
    } catch (_) {
      r = null;
    } finally {
      body = null; // пароли больше нигде не храним
      S.loginBusy = false;
    }
    if (!r) {
      setLoginMsg("Сервер не отвечает. Проверьте адрес и что бот запущен", "bad");
    } else if (r.status === 200 && r.data && typeof r.data.token === "string" && r.data.token) {
      setToken(r.data.token, r.data.expires_in);
      setLoginMsg("", "");
      enterApp();
      return;
    } else if (r.status === 429) {
      goStep(1);
      lockFor(r.data && r.data.retry_after);
      return;
    } else if (r.status === 401) {
      setLoginMsg("Неверные пароли", "bad");
    } else if (r.status === 503) {
      setLoginMsg("Панель выключена на сервере (не заданы пароли в .env)", "bad");
    } else {
      const detail = r.data && r.data.detail ? ": " + clip(String(r.data.detail), 160) : "";
      setLoginMsg(`Не получилось войти (код ${r.status})${detail}`, "bad");
    }
    goStep(1);
    updateLock();
  }

  function showLogin(msg, kind) {
    stopApp();
    $("app").hidden = true;
    $("login").hidden = false;
    $("p1").value = "";
    $("p2").value = "";
    S.p1 = "";
    renderServerBox(false);
    setLoginMsg(msg, kind);
    goStep(1);
    updateLock();
  }

  // Убираем из DOM и памяти всё, что относится к сессии.
  function stopApp() {
    clearInterval(S.beat);
    S.beat = 0;
    S.chats = null;
    S.chat = null;
    S.chatSeq += 1;
    S.peopleSeq += 1;
    S.settings = null;
    S.settingCtl = [];
    S.settingsDirty = false;
    S.log = [];
    S.logAuto = false;
    S.peopleChatId = null;
    ["ov-body", "chats-list", "chat-msgs", "people-list", "people-chat", "settings-body", "log-list"]
      .forEach((id) => $(id).replaceChildren());
    ["send-text", "about-text", "log-filter"].forEach((id) => { $(id).value = ""; });
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
    if (token) request("POST", "/logout", {}, token).catch(() => { /* не важно */ });
    showLogin("Вы вышли автоматически: 30 минут без действий", "");
  }

  async function logout() {
    await busy($("logout-btn"), async () => {
      const token = getToken();
      clearToken();
      if (token) {
        try { await request("POST", "/logout", {}, token); } catch (_) { /* всё равно выходим */ }
      }
    });
    showLogin("Вы вышли", "ok");
  }

  async function logoutAll() {
    if (!confirm("Выйти на всех устройствах? Потом нужно будет снова ввести пароли.")) return;
    const ok = await busy($("logout-all"), async () => {
      await api("POST", "/logout_all");
      return true;
    });
    if (ok) {
      clearToken();
      showLogin("Вы вышли на всех устройствах", "ok");
    }
  }

  // ---------- активность и таймеры ----------
  function markActive() {
    if ($("app").hidden) return;
    const now = Date.now();
    if (S.lastActive && now - S.lastActive > IDLE_MS) { idleLogout(); return; }
    S.lastActive = now;
    if (now - S.lastSaved > 5000) {
      S.lastSaved = now;
      sess.set(K.active, now);
    }
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
      const on = t === name;
      const b = $("tab-" + t);
      b.setAttribute("aria-selected", on ? "true" : "false");
      b.tabIndex = on ? 0 : -1;
      $("panel-" + t).hidden = !on;
    }
    if (focus) $("tab-" + name).focus();
    window.scrollTo(0, 0);
    if (name === "overview") loadOverview(false);
    else if (name === "chats") { if (S.chat) loadMessages(); else loadChats(); }
    else if (name === "people") loadPeopleTab();
    else if (name === "settings") { if (!S.settingsDirty) loadSettings(); }
    else if (name === "log") loadLog(false);
  }

  function onTabKey(e) {
    const i = TABS.indexOf(S.tab);
    let j = -1;
    if (e.key === "ArrowRight") j = (i + 1) % TABS.length;
    else if (e.key === "ArrowLeft") j = (i + TABS.length - 1) % TABS.length;
    else if (e.key === "Home") j = 0;
    else if (e.key === "End") j = TABS.length - 1;
    if (j < 0) return;
    e.preventDefault();
    selectTab(TABS[j], true);
  }

  // ---------- 1. Обзор ----------
  const kv = (label, value) => h("div", { class: "kv" }, h("dt", { text: label }), h("dd", null, value));
  const stat = (n, label) => h("div", { class: "stat" }, h("b", { text: String(Number(n) || 0) }), h("span", { text: label }));

  async function loadOverview(silent) {
    if (S.loading.overview) return;
    S.loading.overview = true;
    S.lastOverview = Date.now();
    const box = $("ov-body");
    if (!box.firstChild) showEmpty(box, "Загрузка…");
    try {
      renderOverview(await api("GET", "/status"));
    } catch (e) {
      if (e.handled) return;
      if (!silent) showError(e);
      if (!box.querySelector(".card")) showEmpty(box, "Не удалось загрузить. Нажмите «Обновить».");
    } finally {
      S.loading.overview = false;
    }
  }

  function renderOverview(st) {
    const wa = String(st.whatsapp || "неизвестно");
    const waCls = wa === "open" ? "ok" : wa === "connecting" ? "warn" : "bad";
    const waText = wa === "open" ? "на связи" : wa === "connecting" ? "подключается…" : `нет связи (${wa})`;
    const spend = Number(st.spend_today_usd) || 0;
    const budget = Number(st.daily_budget_usd) || 0;
    const over = Boolean(st.over_budget);
    const pct = budget > 0 ? Math.min(100, (spend / budget) * 100) : over ? 100 : 0;
    const fill = h("span");
    fill.style.width = pct.toFixed(1) + "%"; // CSSOM, не атрибут style — CSP это разрешает
    const bar = h("div", {
      class: "bar" + (over ? " over" : ""), role: "progressbar", "aria-label": "Потрачено от дневного бюджета",
      "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(Math.round(pct)),
    }, fill);

    setKids($("ov-body"),
      st.own_lid_known === false
        ? h("div", { class: "notice", role: "note", text: "Стелла пока не знает свой LID — @упоминания в некоторых группах может не видеть" })
        : null,
      h("div", { class: "card" },
        h("h3", { class: "card-title", text: "Состояние" }),
        h("dl", null,
          kv("WhatsApp", h("span", { class: `pill ${waCls}`, text: waText })),
          kv("Модель", st.llm_model || "—"),
          kv("Усилие", st.llm_effort || "—"),
          kv("Бэкенд", st.llm_backend || "—"),
          st.switch_at ? kv("Смена модели", switchText(st.switch_at)) : null,
          kv("Работает", fmtDur(st.uptime_s)),
          st.tunnel_url ? kv("Туннель", hostOf(String(st.tunnel_url))) : null)),
      h("div", { class: "card" },
        h("div", { class: "card-head" },
          h("h3", { class: "card-title", text: "Расходы сегодня" }),
          over ? h("span", { class: "pill bad", text: "бюджет превышен" }) : null),
        h("p", { class: "big", text: budget > 0 ? `${usd(spend)} из ${usd(budget)}` : `${usd(spend)} · без лимита` }),
        budget > 0 ? bar : null),
      h("div", { class: "card" },
        h("h3", { class: "card-title", text: "Чаты" }),
        h("div", { class: "stats" }, stat(st.groups, "группы"), stat(st.dms, "лички"), stat(st.chats, "всего"))),
      h("p", { class: "updated muted small", text: `Обновлено в ${fmtTime(new Date().toISOString(), true)}` }));
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

  function sortChats(list) {
    const at = (c) => (toDate(c.last_message_at) || 0) - 0;
    return list.slice().sort((a, b) =>
      (Number(Boolean(b.is_group)) - Number(Boolean(a.is_group))) || (at(b) - at(a)) ||
      String(a.title || "").localeCompare(String(b.title || ""), "ru"));
  }

  function pauseInfo(c) {
    const until = toDate(c.paused_until);
    if (until && until.getTime() > Date.now()) {
      return c.paused_by_owner ? `ты пишешь сам · до ${fmtTime(c.paused_until)}` : `пауза до ${fmtTime(c.paused_until)}`;
    }
    if (c.paused_by_owner && !c.paused_until) return "ты пишешь сам";
    return "";
  }

  async function loadChats() {
    const box = $("chats-list");
    if (!S.chats) showEmpty(box, "Загрузка…");
    try {
      const r = await api("GET", "/chats");
      S.chats = sortChats(Array.isArray(r.chats) ? r.chats : []);
      renderChats();
      fillPeopleSelect();
    } catch (e) {
      if (e.handled) return S.chats;
      showError(e);
      if (!S.chats) showEmpty(box, "Не удалось загрузить. Нажмите «Обновить».");
    }
    return S.chats;
  }

  function renderChats() {
    const box = $("chats-list");
    if (!S.chats || !S.chats.length) { showEmpty(box, "Пока пусто"); return; }
    const section = (title, list) => (list.length
      ? [h("h3", { class: "list-title", text: `${title} · ${list.length}` }), h("ul", { class: "list" }, list.map(chatItem))]
      : null);
    setKids(box, section("Группы", S.chats.filter((c) => c.is_group)), section("Личные", S.chats.filter((c) => !c.is_group)));
  }

  function chatItem(c) {
    const pause = pauseInfo(c);
    const meta = [
      c.is_group ? "группа" : "личка",
      `режим: ${chimeText(c.chime_level)}`,
      c.last_bot_at ? `ответ: ${ago(c.last_bot_at)}` : "ещё не отвечала",
    ].join(" · ");
    const btn = h("button", { type: "button", class: "chat-item" },
      h("div", { class: "name", text: c.title || "Без названия" }),
      h("div", { class: "meta", text: meta }),
      h("div", { class: "badges" },
        pause ? h("span", { class: "badge warn", text: pause }) : null,
        Number(c.grudges) > 0 ? h("span", { class: "badge bad", text: `обиды: ${Number(c.grudges)}` }) : null));
    btn.addEventListener("click", () => openChat(c.id));
    return h("li", null, btn);
  }

  function openChat(id) {
    const c = (S.chats || []).find((x) => x.id === id);
    if (!c) return;
    S.chat = c;
    S.chatSeq += 1;
    S.peopleChatId = c.id;
    $("chats-list-view").hidden = true;
    $("chat-view").hidden = false;
    if (!(history.state && history.state.stellaChat)) history.pushState({ stellaChat: true }, "");
    $("send-text").value = "";
    $("about-text").value = "";
    $("about-text").disabled = true;
    $("about-save").disabled = true;
    updateAboutCount();
    $("about-notes").textContent = "Загрузка…";
    showEmpty($("chat-msgs"), "Загрузка…");
    renderChatHead();
    window.scrollTo(0, 0);
    loadMessages();
    loadAbout();
  }

  function closeChat() {
    S.chat = null;
    S.chatSeq += 1;
    $("chat-view").hidden = true;
    $("chats-list-view").hidden = false;
    $("chat-msgs").replaceChildren();
    $("send-text").value = "";
    $("about-text").value = "";
    $("about-notes").textContent = "";
    if (S.chats) renderChats();
    loadChats();
  }

  function backToList() {
    if (history.state && history.state.stellaChat) history.back(); // popstate закроет чат
    else closeChat();
  }

  function renderChatHead() {
    const c = S.chat;
    if (!c) return;
    $("chat-title").textContent = c.title || "Без названия";
    $("chat-sub").textContent = [
      c.is_group ? `группа · участников: ${Number(c.members) || 0}` : "личка",
      c.jid_masked || "",
    ].filter(Boolean).join(" · ");
    const pause = pauseInfo(c);
    setKids($("chat-badges"),
      pause ? h("span", { class: "badge warn", text: pause }) : null,
      h("span", { class: "badge accent", text: `режим: ${chimeText(c.chime_level)}` }),
      Number(c.grudges) > 0 ? h("span", { class: "badge bad", text: `обиды: ${Number(c.grudges)}` }) : null,
      c.last_bot_at ? h("span", { class: "badge", text: `ответ: ${ago(c.last_bot_at)}` }) : null);
    $("unpause-btn").disabled = !pause;
    $("chime-select").value = CHIME.has(c.chime_level) ? c.chime_level : "";
  }

  async function loadMessages() {
    const c = S.chat;
    if (!c) return;
    const seq = S.chatSeq;
    const box = $("chat-msgs");
    try {
      const r = await api("GET", chatPath(c.id, "/messages?limit=60"));
      if (seq !== S.chatSeq) return;
      renderMessages(Array.isArray(r.messages) ? r.messages : []);
    } catch (e) {
      if (seq !== S.chatSeq || e.handled) return;
      showError(e);
      if (!box.querySelector(".msg")) showEmpty(box, "Не удалось загрузить сообщения");
    }
  }

  function renderMessages(list) {
    const box = $("chat-msgs");
    if (!list.length) { showEmpty(box, "Пока пусто"); return; }
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
    const c = S.chat;
    if (!c) return;
    const ta = $("send-text");
    const text = ta.value.trim();
    if (!text) { toast("Напишите текст", "bad"); ta.focus(); return; }
    if ($("send-btn").disabled) return;
    if (!confirm(`Стелла отправит в «${c.title || "чат"}»:\n\n${clip(text, 300)}`)) return;
    const seq = S.chatSeq;
    await busy([$("send-btn"), ta], async () => {
      await api("POST", chatPath(c.id, "/send"), { text });
      if (seq === S.chatSeq) ta.value = "";
      toast("Отправлено");
      setTimeout(() => { if (seq === S.chatSeq) loadMessages(); }, 1500);
    });
  }

  // Действие в карточке «Управление»: блокируем все её кнопки на время запроса.
  async function chatAction(el, fn) {
    const c = S.chat;
    if (!c) return;
    const others = [...$("chat-controls").querySelectorAll("button, select")].filter((x) => x !== el);
    await busy([el, ...others], () => fn(c));
    if (S.chat === c) renderChatHead();
  }

  function onPause(btn) {
    const minutes = Number(btn.dataset.pause);
    chatAction(btn, async (c) => {
      const r = await api("POST", chatPath(c.id, "/pause"), { minutes });
      c.paused_until = r.paused_until || new Date(Date.now() + minutes * 60000).toISOString();
      c.paused_by_owner = false;
      toast(`Пауза до ${fmtTime(c.paused_until)}`);
    });
  }

  function onUnpause() {
    chatAction($("unpause-btn"), async (c) => {
      await api("POST", chatPath(c.id, "/unpause"));
      c.paused_until = null;
      c.paused_by_owner = false;
      toast("Пауза снята");
    });
  }

  function onChime() {
    const sel = $("chime-select");
    const level = sel.value;
    if (!CHIME.has(level)) return;
    chatAction(sel, async (c) => {
      await api("POST", chatPath(c.id, "/chime"), { level });
      c.chime_level = level;
      toast(`Режим: ${CHIME.get(level)}`);
    });
  }

  function onPoke() {
    chatAction($("poke-btn"), async (c) => {
      const seq = S.chatSeq;
      let r;
      try {
        r = await api("POST", chatPath(c.id, "/poke"));
      } catch (e) {
        if (e.status === 0 && e.code === "timeout") {
          toast("Сервер долго отвечает — возможно, она ещё пишет. Обновите чат чуть позже");
          return;
        }
        throw e;
      }
      toast(r.sent ? "Стелла написала в чат" : "Стелла решила пока промолчать");
      if (r.sent) setTimeout(() => { if (seq === S.chatSeq) loadMessages(); }, 2000);
    });
  }

  async function loadAbout() {
    const c = S.chat;
    if (!c) return;
    const seq = S.chatSeq;
    try {
      const r = await api("GET", chatPath(c.id, "/about"));
      if (seq !== S.chatSeq) return;
      $("about-text").value = valueText(r.about);
      $("about-text").disabled = false;
      $("about-save").disabled = false;
      $("about-notes").textContent = r.notes ? valueText(r.notes) : "Пока пусто";
      updateAboutCount();
    } catch (e) {
      if (seq !== S.chatSeq || e.handled) return;
      $("about-notes").textContent = "Не удалось загрузить — нажмите ↻";
      showError(e);
    }
  }

  function updateAboutCount() {
    $("about-count").textContent = `${$("about-text").value.length} / ${ABOUT_MAX}`;
  }

  function onAboutSave() {
    const c = S.chat;
    if (!c) return;
    const ta = $("about-text");
    const about = ta.value;
    if (about.length > ABOUT_MAX) { toast(`Слишком длинно: максимум ${ABOUT_MAX} символов`, "bad"); return; }
    busy([$("about-save"), ta], async () => {
      await api("PUT", chatPath(c.id, "/about"), { about });
      toast("Сохранено");
    });
  }

  function onChatRefresh() {
    busy($("chat-refresh"), async () => {
      await loadMessages();
      if ($("about-text").disabled) await loadAbout();
      const list = await loadChats();
      if (S.chat && list) {
        const fresh = list.find((x) => x.id === S.chat.id);
        if (fresh) { S.chat = fresh; renderChatHead(); }
      }
    });
  }

  // ---------- 3. Люди ----------
  function fillPeopleSelect() {
    const sel = $("people-chat");
    const list = S.chats || [];
    if (S.peopleChatId === null || !list.some((c) => c.id === S.peopleChatId)) {
      S.peopleChatId = list.length ? list[0].id : null;
    }
    setKids(sel, list.map((c) => h("option", {
      value: String(c.id), text: `${c.title || "Без названия"} (${c.is_group ? "группа" : "личка"})`,
    })));
    if (S.peopleChatId !== null) sel.value = String(S.peopleChatId);
    sel.disabled = !list.length;
  }

  async function loadPeopleTab() {
    if (!S.chats) await loadChats();
    else fillPeopleSelect();
    if (!S.chats || !S.chats.length) {
      showEmpty($("people-list"), S.chats ? "Пока пусто — нет чатов" : "Не удалось загрузить список чатов");
      return;
    }
    await loadPeople();
  }

  async function loadPeople() {
    const id = S.peopleChatId;
    const box = $("people-list");
    if (id === null) { showEmpty(box, "Пока пусто"); return; }
    const seq = ++S.peopleSeq;
    showEmpty(box, "Загрузка…");
    try {
      const r = await api("GET", chatPath(id, "/people"));
      if (seq !== S.peopleSeq) return;
      const people = (Array.isArray(r.people) ? r.people : [])
        .slice().sort((a, b) => (Number(b.msg_count) || 0) - (Number(a.msg_count) || 0));
      if (!people.length) { showEmpty(box, "Пока пусто"); return; }
      setKids(box, people.map((p) => personCard(id, p)));
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
    const meta = [
      p.nickname ? `прозвище: ${p.nickname}` : "",
      p.push_name && p.push_name !== p.name ? `в WhatsApp: ${p.push_name}` : "",
      p.phone_masked || "",
      `сообщений: ${Number(p.msg_count) || 0}`,
    ].filter(Boolean).join(" · ");
    const head = h("button", { type: "button", class: "person-head", "aria-expanded": "false", "aria-controls": bodyId },
      h("div", { class: "who" }, h("div", { class: "name", text: personName(p) }), h("div", { class: "meta", text: meta })),
      h("span", { class: "chev", "aria-hidden": "true", text: "▾" }));
    head.addEventListener("click", () => {
      const open = head.getAttribute("aria-expanded") !== "true";
      head.setAttribute("aria-expanded", open ? "true" : "false");
      body.hidden = !open;
      if (open && !body.firstChild) renderPersonBody(body, chatId, p);
    });
    return h("div", { class: "person" }, head, body);
  }

  function renderPersonBody(body, chatId, p) {
    const profile = p.profile && typeof p.profile === "object" && !Array.isArray(p.profile) ? p.profile : {};
    const personPath = (tail) => chatPath(chatId, `/people/${encodeURIComponent(String(p.id))}${tail}`);
    const rows = h("div", { class: "kv-rows" });
    let recs = [];

    const addRow = (key, value, existing) => {
      const keyIn = h("input", {
        type: "text", value: key, readOnly: existing, maxLength: 64, placeholder: "поле",
        autocomplete: "off", "aria-label": existing ? `Поле «${key}»` : "Название нового поля",
      });
      const valIn = h("input", {
        type: "text", value, maxLength: 2000, placeholder: "значение",
        autocomplete: "off", "aria-label": existing ? `Значение поля «${key}»` : "Значение нового поля",
      });
      const del = h("button", { type: "button", class: "btn", text: "✕", title: "Убрать поле", "aria-label": `Убрать поле ${key}`.trim() });
      const row = h("div", { class: "kv-row" }, keyIn, valIn, del);
      const rec = { row, keyIn, valIn };
      del.addEventListener("click", () => { row.remove(); recs = recs.filter((x) => x !== rec); });
      recs.push(rec);
      rows.append(row);
      return keyIn;
    };
    for (const [k, v] of Object.entries(profile)) addRow(k, valueText(v), true);

    const addBtn = h("button", { type: "button", class: "btn", text: "Добавить поле" });
    addBtn.addEventListener("click", () => addRow("", "", false).focus());

    const saveBtn = h("button", { type: "button", class: "btn primary", text: "Сохранить анкету" });
    saveBtn.addEventListener("click", () => busy(saveBtn, async () => {
      const now = new Map();
      for (const r of recs) {
        const k = r.keyIn.value.trim();
        const v = r.valIn.value.trim();
        if (!k) {
          if (v) { toast("Укажите название поля", "bad"); r.keyIn.focus(); return; }
          continue;
        }
        now.set(k, v);
      }
      const has = (k) => Object.prototype.hasOwnProperty.call(profile, k);
      const fields = Object.create(null);
      for (const k of Object.keys(profile)) if (!now.has(k)) fields[k] = ""; // пустая строка = удалить
      for (const [k, v] of now) {
        if (has(k) ? valueText(profile[k]).trim() !== v : v !== "") fields[k] = v;
      }
      if (!Object.keys(fields).length) { toast("Нет изменений"); return; }
      const r = await api("PUT", personPath("/profile"), { fields });
      if (r.profile && typeof r.profile === "object") p.profile = r.profile;
      else {
        const next = { ...profile };
        for (const k of Object.keys(fields)) { if (fields[k] === "") delete next[k]; else next[k] = fields[k]; }
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

    setKids(body,
      h("h4", { class: "sub-title", text: "Анкета" }),
      recs.length ? null : h("p", { class: "muted small", text: "Пока пусто — можно добавить поле" }),
      rows,
      h("div", { class: "btn-row" }, addBtn, saveBtn),
      h("h4", { class: "sub-title", text: `Факты (${facts.length})` }),
      facts.length
        ? h("ul", { class: "facts" }, facts.map((f) => h("li", { text: valueText(f) })))
        : h("p", { class: "muted small", text: "Пока пусто" }),
      forgetBtn);
  }

  // ---------- 4. Настройки ----------
  function setDirty(on) {
    S.settingsDirty = on;
    $("settings-dirty").hidden = !on;
  }

  async function loadSettings() {
    const box = $("settings-body");
    if (!S.settings) showEmpty(box, "Загрузка…");
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
    const box = $("settings-body");
    if (!list.length) { showEmpty(box, "Пока пусто"); return; }
    setKids(box, list.map((d, i) => settingField(d, i)));
  }

  function settingField(d, i) {
    const id = `set-${i}`;
    const hintId = d.hint ? `${id}-hint` : null;
    const label = String(d.label || d.key);
    const keyTag = h("span", { class: "key", text: String(d.key) });
    let el;
    if (d.type === "bool") {
      el = h("input", { type: "checkbox", id, checked: Boolean(d.value), "aria-describedby": hintId });
    } else if (d.type === "select") {
      const opts = (Array.isArray(d.options) ? d.options : []).map(String);
      const cur = valueText(d.value);
      if (!opts.includes(cur)) opts.unshift(cur);
      el = h("select", { id, "aria-describedby": hintId }, opts.map((o) => h("option", { value: o, text: o === "" ? "—" : o })));
      el.value = cur;
    } else if (d.type === "number") {
      el = h("input", {
        type: "number", id, step: "any", min: d.min ?? null, max: d.max ?? null,
        value: valueText(d.value), "aria-describedby": hintId,
      });
    } else {
      const v = valueText(d.value);
      el = v.length > 80 || v.includes("\n")
        ? h("textarea", { id, rows: 3, value: v, "aria-describedby": hintId })
        : h("input", { type: "text", id, value: v, autocomplete: "off", "aria-describedby": hintId });
    }
    el.addEventListener("input", () => setDirty(true));
    el.addEventListener("change", () => setDirty(true));
    S.settingCtl.push({ d, el });
    const head = d.type === "bool"
      ? h("label", { class: "check", for: id }, el, h("span", { text: label }), keyTag)
      : h("label", { for: id }, label, keyTag);
    return h("div", { class: "setting" },
      head,
      d.type === "bool" ? null : el,
      hintId ? h("p", { class: "hint", id: hintId, text: String(d.hint) }) : null);
  }

  function readSetting({ d, el }) {
    const label = d.label || d.key;
    if (d.type === "bool") return { v: el.checked };
    if (d.type === "number") {
      const raw = el.value.trim();
      if (raw === "") return { err: `Заполните «${label}» (нужно число)` };
      const n = Number(raw);
      if (!Number.isFinite(n)) return { err: `«${label}»: нужно число` };
      const lo = d.min ?? null, hi = d.max ?? null;
      if ((lo !== null && n < lo) || (hi !== null && n > hi)) {
        return { err: `«${label}»: от ${lo ?? "…"} до ${hi ?? "…"}` };
      }
      return { v: n };
    }
    return { v: el.value };
  }

  function sameValue(d, v) {
    if (d.type === "bool") return Boolean(d.value) === v;
    if (d.type === "number") return Number(d.value) === v && d.value !== null && d.value !== "";
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
      const r = await api("PUT", "/settings", changed);
      if (Array.isArray(r.settings)) renderSettings(r.settings);
      else { setDirty(false); await loadSettings(); }
      toast("Сохранено");
    });
  }

  // ---------- 5. Журнал ----------
  async function loadLog(silent) {
    if (S.loading.log) return;
    S.loading.log = true;
    S.lastLog = Date.now();
    const box = $("log-list");
    if (!S.log.length) showEmpty(box, "Загрузка…");
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
    const hadLines = Boolean(box.querySelector(".log-line"));
    const atBottom = !hadLines || box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    const q = $("log-filter").value.trim().toLowerCase();
    const lines = q ? S.log.filter((l) => `${l.level} ${l.text}`.toLowerCase().includes(q)) : S.log;
    if (!lines.length) { showEmpty(box, S.log.length ? "Ничего не найдено" : "Пока пусто"); return; }
    setKids(box, lines.map((l) => {
      const up = String(l.level || "INFO").toUpperCase();
      const lv = /^[A-Z]{1,10}$/.test(up) ? up : "INFO";
      return h("div", { class: `log-line lvl-${lv}` },
        h("span", { class: "t", text: fmtTime(l.at, true) }), " ",
        h("span", { class: "l", text: lv }), " ",
        h("span", { class: "m", text: valueText(l.text) }));
    }));
    if (atBottom) box.scrollTop = box.scrollHeight;
  }

  // ---------- привязка событий ----------
  function bindEvents() {
    $("step1").addEventListener("submit", onStep1);
    $("step2").addEventListener("submit", onStep2);
    $("step2-back").addEventListener("click", () => { setLoginMsg("", ""); goStep(1); });
    $("server-change").addEventListener("click", () => { renderServerBox(true); $("server-input").focus(); });

    $("logout-btn").addEventListener("click", logout);
    $("logout-all").addEventListener("click", logoutAll);
    for (const t of TABS) {
      $("tab-" + t).addEventListener("click", () => {
        if (t === S.tab && t === "chats" && S.chat) backToList();
        else selectTab(t, false);
      });
    }
    document.querySelector(".tabs").addEventListener("keydown", onTabKey);

    $("ov-refresh").addEventListener("click", (e) => busy(e.currentTarget, () => loadOverview(false)));
    $("ov-unpause-all").addEventListener("click", (e) => bulkAction(e.currentTarget, "/actions/unpause_all",
      "Снять паузу во всех чатах?", (n) => `Пауз снято: ${n}`));
    $("ov-forgive-all").addEventListener("click", (e) => bulkAction(e.currentTarget, "/actions/forgive_all",
      "Стелла перестанет обижаться на всех. Продолжить?", (n) => `Обид снято: ${n}`));

    $("chats-refresh").addEventListener("click", (e) => busy(e.currentTarget, loadChats));
    $("chat-back").addEventListener("click", backToList);
    $("chat-refresh").addEventListener("click", onChatRefresh);
    $("send-form").addEventListener("submit", onSend);
    $("send-text").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) onSend(e);
    });
    document.querySelectorAll("#chat-controls [data-pause]").forEach((b) => b.addEventListener("click", () => onPause(b)));
    $("unpause-btn").addEventListener("click", onUnpause);
    $("chime-select").addEventListener("change", onChime);
    $("poke-btn").addEventListener("click", onPoke);
    $("about-text").addEventListener("input", updateAboutCount);
    $("about-save").addEventListener("click", onAboutSave);

    $("people-chat").addEventListener("change", (e) => {
      S.peopleChatId = Number(e.target.value);
      loadPeople();
    });
    $("people-refresh").addEventListener("click", (e) => busy(e.currentTarget, async () => {
      await loadChats();
      await loadPeople();
    }));

    $("settings-save").addEventListener("click", saveSettings);
    $("settings-refresh").addEventListener("click", (e) => {
      if (S.settingsDirty && !confirm("Есть несохранённые изменения. Сбросить их?")) return;
      busy(e.currentTarget, loadSettings);
    });

    $("log-refresh").addEventListener("click", (e) => busy(e.currentTarget, () => loadLog(false)));
    $("log-filter").addEventListener("input", renderLog);
    $("log-auto").addEventListener("change", (e) => {
      S.logAuto = e.target.checked;
      if (S.logAuto) loadLog(true);
    });

    $("toast").addEventListener("click", () => { $("toast").hidden = true; });

    // Только настоящие действия человека (не scroll — его вызывает и автопрокрутка).
    ["pointerdown", "keydown", "wheel", "touchstart"].forEach((ev) =>
      document.addEventListener(ev, markActive, { passive: true, capture: true }));
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") heartbeat();
    });
    window.addEventListener("popstate", () => { if (S.chat) closeChat(); });
  }

  // ---------- запуск ----------
  function init() {
    if (window.top !== window.self) {
      // Защита от кликджекинга: внутри чужой страницы не работаем.
      document.body.replaceChildren(h("p", { class: "noscript", text: "Панель нельзя открывать внутри другой страницы." }));
      return;
    }
    const prevSaved = normServer(local.get(K.server));
    const { server, notice } = resolveServer();
    S.server = server;
    if (server) local.set(K.server, server);
    if (server !== prevSaved) clearToken();
    bindEvents();

    const token = getToken();
    if (token && server) {
      const last = Number(sess.get(K.active)) || 0;
      const exp = Number(sess.get(K.exp)) || 0;
      const now = Date.now();
      if (last && now - last > IDLE_MS) {
        clearToken();
        request("POST", "/logout", {}, token).catch(() => { /* не важно */ });
        showLogin("Вы вышли автоматически: 30 минут без действий", "");
      } else if (exp && now > exp) {
        clearToken();
        showLogin("Сессия закончилась, войдите снова", "bad");
      } else {
        enterApp();
      }
      return;
    }
    showLogin(notice ? notice[0] : "", notice ? notice[1] : "");
  }

  init();
})();

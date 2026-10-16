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
  const K = { server: "stella.server", token: "stella.token", exp: "stella.token_exp", active: "stella.last_active", tab: "stella.tab" };
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
  const NO_SERVER = "Сервер не отвечает. Проверьте адрес и что бот запущен";
  const FIELD_PROPS = new Set(["value", "checked", "disabled", "hidden", "readOnly", "maxLength", "rows", "tabIndex"]);

  const $ = (id) => document.getElementById(id);
  const S = {
    server: "", tab: "overview", chats: null, chat: null, chatSeq: 0, peopleChatId: null, peopleSeq: 0,
    settings: null, settingCtl: [], settingsDirty: false, log: [], logAuto: false,
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
  const showEmpty = (box, text) => box.replaceChildren(h("p", { class: "placeholder", text }));
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
  function switchText(v) { // LLM_SWITCH_AT — дата, с которой бот берёт запасную модель
    const s = String(v);
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
    if (!m) return s;
    const n = new Date();
    const today = `${n.getFullYear()}-${pad(n.getMonth() + 1)}-${pad(n.getDate())}`;
    return `с ${m[3]}.${m[2]}.${m[1]}` + (s.slice(0, 10) <= today ? " (уже действует)" : " — запасная модель");
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
    if (saved && saved !== fromHash) notice = [`Адрес сервера взят из ссылки: ${hostOf(fromHash)}. Вводите пароли, только если это ваш бот.`, "warn"];
    return { server: fromHash, notice };
  }
  function setServer(url) {
    if (url !== S.server) clearToken(); // токен другого сервера не годится
    S.server = url;
    local.set(K.server, url);
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
    ["ov-body", "chats-list", "chat-msgs", "people-list", "people-chat", "settings-body", "log-list"].forEach((id) => $(id).replaceChildren());
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
    fill.style.width = pct.toFixed(1) + "%"; // CSSOM, а не атрибут style — CSP это разрешает
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
    const meta = [c.is_group ? "группа" : "личка", `режим: ${chimeText(c.chime_level)}`,
      c.last_bot_at ? `ответ: ${ago(c.last_bot_at)}` : "ещё не отвечала"].join(" · ");
    const btn = h("button", { type: "button", class: "chat-item" },
      h("div", { class: "name", text: c.title || "Без названия" }),
      h("div", { class: "meta", text: meta }),
      h("div", { class: "badges" }, pause ? h("span", { class: "badge warn", text: pause }) : null, grudgeBadge(c)));
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
    showEmpty($("chat-msgs"), "Загрузка…");
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
    else showEmpty($("people-list"), S.chats ? "Пока пусто — нет чатов" : "Не удалось загрузить список чатов");
  }
  async function loadPeople() {
    const id = S.peopleChatId, box = $("people-list");
    if (id === null) { showEmpty(box, "Пока пусто"); return; }
    const seq = ++S.peopleSeq;
    showEmpty(box, "Загрузка…");
    try {
      const r = await api("GET", chatPath(id, "/people"));
      if (seq !== S.peopleSeq) return;
      const people = (Array.isArray(r.people) ? r.people : []).slice()
        .sort((a, b) => (Number(b.msg_count) || 0) - (Number(a.msg_count) || 0));
      if (people.length) setKids(box, people.map((p) => personCard(id, p)));
      else showEmpty(box, "Пока пусто");
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
    const meta = [p.nickname ? `прозвище: ${p.nickname}` : "", p.push_name && p.push_name !== p.name ? `в WhatsApp: ${p.push_name}` : "",
      p.phone_masked || "", `сообщений: ${Number(p.msg_count) || 0}`].filter(Boolean).join(" · ");
    const head = h("button", { type: "button", class: "person-head", "aria-expanded": "false", "aria-controls": bodyId },
      h("div", { class: "who" }, h("div", { class: "name", text: personName(p) }), h("div", { class: "meta", text: meta })),
      h("span", { class: "chev", "aria-hidden": "true" }));
    head.addEventListener("click", () => {
      const open = head.getAttribute("aria-expanded") !== "true";
      head.setAttribute("aria-expanded", open ? "true" : "false");
      body.hidden = !open;
      if (open && !body.firstChild) renderPersonBody(body, chatId, p);
    });
    return h("div", { class: "person" }, head, body);
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
    setKids(body,
      h("h4", { class: "sub-title", text: "Анкета" }),
      recs.length ? null : h("p", { class: "muted small", text: "Пока пусто — можно добавить поле" }),
      rows,
      h("div", { class: "btn-row" }, addBtn, saveBtn),
      h("h4", { class: "sub-title", text: `Факты (${facts.length})` }),
      facts.length ? h("ul", { class: "facts" }, facts.map((f) => h("li", { text: valueText(f) })))
        : h("p", { class: "muted small", text: "Пока пусто" }),
      forgetBtn);
  }

  // ---------- 4. Настройки (форма строится по описаниям с сервера) ----------
  function setDirty(v) {
    S.settingsDirty = v;
    $("settings-dirty").hidden = !v;
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
    if (list.length) setKids($("settings-body"), list.map(settingField));
    else showEmpty($("settings-body"), "Пока пусто");
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
      d.type === "bool" ? h("label", { class: "check", for: id }, el, h("span", { text: label }), keyTag) : h("label", { for: id }, label, keyTag),
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
    const atBottom = !box.querySelector(".log-line") || box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    const q = $("log-filter").value.trim().toLowerCase();
    const lines = q ? S.log.filter((l) => `${l.level} ${l.text}`.toLowerCase().includes(q)) : S.log;
    if (!lines.length) { showEmpty(box, S.log.length ? "Ничего не найдено" : "Пока пусто"); return; }
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
    const { server, notice } = resolveServer();
    S.server = server;
    if (server) local.set(K.server, server);
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

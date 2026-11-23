// Aura v2.1 — Always-On Multi-Agent Browser Engine
// Credit-Saving Local Automation + Hover Quick Answer + OpenRouter + CDP + Tab Groups + Offscreen

chrome.sidePanel
  .setPanelBehavior({ openPanelOnActionClick: true })
  .catch(() => {});

const agents = new Map();
const attachedDebuggerTabs = new Set();

chrome.debugger.onDetach.addListener((source) => {
  if (source?.tabId != null) {
    attachedDebuggerTabs.delete(source.tabId);
  }
});

function broadcast(payload) {
  chrome.runtime.sendMessage({ type: "AGENT_EVENT", ...payload }).catch(() => {});
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function isRestrictedUrl(url = "") {
  return (
    !url ||
    url.startsWith("chrome://") ||
    url.startsWith("chrome-extension://") ||
    url.startsWith("edge://") ||
    url.startsWith("about:") ||
    url.startsWith("https://chromewebstore.google.com")
  );
}

async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  return tab || null;
}

// =========================================================
// OFFSCREEN SOUND ENGINE
// =========================================================
async function ensureOffscreen() {
  try {
    if (await chrome.offscreen.hasDocument()) return true;
    await chrome.offscreen.createDocument({
      url: "offscreen.html",
      reasons: ["AUDIO_PLAYBACK"],
      justification: "Воспроизведение мягких системных звуков завершения задач AI-агентов",
    });
    return true;
  } catch (_) {
    return false;
  }
}

async function playAgentSound(kind) {
  const ready = await ensureOffscreen();
  if (!ready) return;
  chrome.runtime.sendMessage({ target: "offscreen", type: "PLAY_SOUND", kind }).catch(() => {});
}

// =========================================================
// SYSTEM NOTIFICATIONS
// =========================================================
function sendNotification(title, message) {
  try {
    chrome.notifications.create({
      type: "basic",
      iconUrl: "icons/icon128.png",
      title,
      message: String(message || "").slice(0, 200),
      priority: 1,
    });
  } catch (_) {}
}

// =========================================================
// CHROME TAB GROUPS
// =========================================================
function hexToTabGroupColor(hex = "#007aff") {
  const map = {
    "#007aff": "blue",
    "#af52de": "purple",
    "#ff2d55": "pink",
    "#34c759": "green",
    "#ff9500": "orange",
    "#32ade6": "cyan",
  };
  return map[String(hex).toLowerCase()] || "blue";
}

async function assignTabToAgentGroup(agent, tabId) {
  try {
    const groupOpts = { tabIds: [tabId] };
    if (agent.groupId != null) {
      try {
        await chrome.tabGroups.get(agent.groupId);
        groupOpts.groupId = agent.groupId;
      } catch (_) {
        agent.groupId = null;
      }
    }
    const groupId = await chrome.tabs.group(groupOpts);
    agent.groupId = groupId;
    await chrome.tabGroups.update(groupId, {
      title: agent.name,
      color: hexToTabGroupColor(agent.color),
      collapsed: false,
    });
  } catch (_) {}
}

// =========================================================
// CHROME DEBUGGER (CDP) + CONSOLE & NETWORK INSPECTION
// =========================================================
const tabDebugLogs = new Map();

chrome.debugger.onEvent.addListener((source, method, params) => {
  const tabId = source?.tabId;
  if (tabId == null) return;
  let logs = tabDebugLogs.get(tabId);
  if (!logs) {
    logs = [];
    tabDebugLogs.set(tabId, logs);
  }
  if (method === "Runtime.consoleAPICalled" && params?.type === "error") {
    const txt = (params.args || []).map((a) => a.value ?? a.description ?? "").join(" ").slice(0, 140);
    if (txt) logs.push(`CONSOLE_ERR: ${txt}`);
  } else if (method === "Network.responseReceived" && params?.response?.status >= 400) {
    logs.push(`HTTP_${params.response.status}: ${String(params.response.url || "").slice(0, 100)}`);
  }
  if (logs.length > 10) logs.splice(0, logs.length - 10);
});

async function attachDebugger(tabId) {
  if (attachedDebuggerTabs.has(tabId)) return true;
  try {
    await chrome.debugger.attach({ tabId }, "1.3");
    attachedDebuggerTabs.add(tabId);
    await chrome.debugger.sendCommand({ tabId }, "Runtime.enable").catch(() => {});
    await chrome.debugger.sendCommand({ tabId }, "Network.enable").catch(() => {});
    return true;
  } catch (_) {
    return false;
  }
}

async function detachDebuggerIfUnused(tabId) {
  if (!attachedDebuggerTabs.has(tabId)) return;
  for (const a of agents.values()) {
    if (a.running && a.tabId === tabId) return;
  }
  try {
    await chrome.debugger.detach({ tabId });
  } catch (_) {}
  attachedDebuggerTabs.delete(tabId);
}

async function cdpCaptureScreenshot(tabId) {
  if (!attachedDebuggerTabs.has(tabId)) return null;
  try {
    const res = await chrome.debugger.sendCommand({ tabId }, "Page.captureScreenshot", {
      format: "jpeg",
      quality: 60,
    });
    if (res?.data) return `data:image/jpeg;base64,${res.data}`;
  } catch (_) {}
  return null;
}

async function cdpTrustedClick(tabId, x, y) {
  if (!attachedDebuggerTabs.has(tabId)) return false;
  try {
    await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
    await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
      type: "mousePressed",
      x,
      y,
      button: "left",
      clickCount: 1,
    });
    await sleep(45);
    await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
      type: "mouseReleased",
      x,
      y,
      button: "left",
      clickCount: 1,
    });
    return true;
  } catch (_) {
    return false;
  }
}

// =========================================================
// CONTENT SCRIPT & TAB HELPERS
// =========================================================
async function ensureContentScript(tabId, url) {
  if (isRestrictedUrl(url)) return false;
  try {
    const ping = await chrome.tabs.sendMessage(tabId, { type: "PING" });
    if (ping?.ok) return true;
  } catch (_) {}
  try {
    await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
    await sleep(120);
    return true;
  } catch (_) {
    return false;
  }
}

async function waitForTabComplete(tabId, agent, timeoutMs = 12000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (agent.stopRequested) return;
    try {
      const tab = await chrome.tabs.get(tabId);
      if (tab.status === "complete") {
        await sleep(420);
        return;
      }
    } catch (_) {
      return;
    }
    await sleep(240);
  }
}

async function safeHideOverlay(tabId, agentId) {
  if (!tabId) return;
  try {
    await chrome.tabs.sendMessage(tabId, { type: "HIDE_OVERLAY", agentId });
  } catch (_) {}
}

async function captureScreenshotSmart(tab, useDebugger, withSom = true) {
  if (!tab || isRestrictedUrl(tab.url)) return null;
  if (withSom) {
    await chrome.tabs.sendMessage(tab.id, { type: "SHOW_SOM_LABELS" }).catch(() => {});
    await sleep(60);
  }
  let shot = null;
  try {
    if (useDebugger && attachedDebuggerTabs.has(tab.id)) {
      shot = await cdpCaptureScreenshot(tab.id);
    }
    if (!shot && tab.active) {
      shot = await chrome.tabs.captureVisibleTab(tab.windowId, { format: "jpeg", quality: 60 });
    }
  } catch (_) {}
  if (withSom) {
    await chrome.tabs.sendMessage(tab.id, { type: "HIDE_SOM_LABELS" }).catch(() => {});
  }
  return shot;
}

// =========================================================
// ZERO-CREDIT LOCAL AUTOMATION ROUTER (SAVES OPENROUTER CREDITS!)
// =========================================================
const SITE_SHORTCUTS = {
  youtube: "https://www.youtube.com",
  ютуб: "https://www.youtube.com",
  google: "https://www.google.com",
  гугл: "https://www.google.com",
  yandex: "https://ya.ru",
  яндекс: "https://ya.ru",
  vk: "https://vk.com",
  вк: "https://vk.com",
  telegram: "https://web.telegram.org",
  телеграм: "https://web.telegram.org",
  wikipedia: "https://ru.wikipedia.org",
  википедия: "https://ru.wikipedia.org",
  github: "https://github.com",
  гитхаб: "https://github.com",
  gmail: "https://mail.google.com",
  дневник: "https://dnevnik.ru",
  мэш: "https://school.mos.ru",
};

async function tryLocalAutomation(prompt, agent, tab) {
  const p = String(prompt || "").trim();
  const lower = p.toLowerCase();

  // 1. Direct URL or known site shortcut ("открой youtube", "открой https://...")
  const openMatch = lower.match(/^(?:открой|перейди\s+на|зайди\s+на|open)\s+(.+)$/i);
  if (openMatch && !lower.includes(" и ")) {
    const target = openMatch[1].trim().replace(/[.,!?]+$/, "");
    let url = SITE_SHORTCUTS[target] || null;
    if (!url && /^[a-z0-9.-]+\.[a-z]{2,}(\/\S*)?$/i.test(target)) {
      url = `https://${target}`;
    } else if (!url && /^https?:\/\//i.test(target)) {
      url = target;
    }
    if (url) {
      const created = await chrome.tabs.create({ url, active: true });
      agent.tabId = created.id;
      await assignTabToAgentGroup(agent, created.id);
      return `Открыл ${url} (локально, 0 кредитов).`;
    }
  }

  // 2. Direct search ("найди в гугле ...", "поищи ...")
  const searchMatch = p.match(/^(?:найди\s+в\s+гугле|поищи|загугли|search)\s+(.+)$/i);
  if (searchMatch && !lower.includes(" и ")) {
    const q = encodeURIComponent(searchMatch[1].trim());
    const created = await chrome.tabs.create({ url: `https://www.google.com/search?q=${q}`, active: true });
    agent.tabId = created.id;
    await assignTabToAgentGroup(agent, created.id);
    return `Открыл поиск по запросу «${searchMatch[1].trim()}» (локально, 0 кредитов).`;
  }

  // 3. Simple scroll ("пролистай вниз" / "листай вверх")
  if (/^(?:пролистай|листай|скролль|scroll)\s+(вниз|вверх|down|up)$/i.test(lower)) {
    const dir = /вверх|up/i.test(lower) ? "up" : "down";
    const ok = await ensureContentScript(tab.id, tab.url);
    if (ok) {
      await chrome.tabs.sendMessage(tab.id, {
        type: "EXECUTE_ACTION",
        action: { type: "scroll", direction: dir, amount: 650 },
        agentId: agent.id,
        agentName: agent.name,
        agentColor: agent.color,
      });
      return `Прокрутил страницу ${dir === "up" ? "вверх" : "вниз"} (0 кредитов).`;
    }
  }

  // 4. Go back ("назад" / "вернись назад")
  if (/^(?:назад|вернись\s+назад|go\s+back)$/i.test(lower)) {
    await chrome.tabs.goBack(tab.id).catch(() => {});
    return "Вернулся на предыдущую страницу (0 кредитов).";
  }

  // 5. Direct click by visible text ("нажми <текст>")
  const clickMatch = p.match(/^(?:нажми|кликни|click)\s+(?:на\s+)?["«]?([^"»]+)["»]?$/i);
  if (clickMatch && !lower.includes(" и ")) {
    const ok = await ensureContentScript(tab.id, tab.url);
    if (ok) {
      const res = await chrome.tabs
        .sendMessage(tab.id, {
          type: "LOCAL_CLICK_TEXT",
          query: clickMatch[1].trim(),
          agentId: agent.id,
          agentName: agent.name,
          agentColor: agent.color,
        })
        .catch(() => null);
      if (res?.ok) {
        playAgentSound("click");
        return `Нажал на «${clickMatch[1].trim()}» (локально, 0 кредитов).`;
      }
    }
  }

  return null;
}

// =========================================================
// BULLETPROOF JSON EXTRACTOR & REPAIRER
// =========================================================
function extractBalancedJson(text) {
  let start = -1;
  let depth = 0;
  let inString = false;
  let escaped = false;

  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inString) {
      if (escaped) escaped = false;
      else if (ch === "\\") escaped = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') {
      inString = true;
    } else if (ch === "{") {
      if (depth === 0) start = i;
      depth++;
    } else if (ch === "}") {
      if (depth > 0) {
        depth--;
        if (depth === 0 && start !== -1) return text.slice(start, i + 1);
      }
    }
  }

  if (start !== -1) {
    let partial = text.slice(start);
    if (inString) partial += '"';
    while (depth > 0) {
      partial += "}";
      depth--;
    }
    return partial;
  }
  return text;
}

function repairJsonString(raw) {
  let s = String(raw || "")
    .replace(/^\uFEFF/, "")
    .replace(/[\u201C\u201D]/g, '"')
    .trim();

  let out = "";
  let inStr = false;
  let esc = false;
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (inStr) {
      if (esc) {
        out += ch;
        esc = false;
      } else if (ch === "\\") {
        out += ch;
        esc = true;
      } else if (ch === '"') {
        out += ch;
        inStr = false;
      } else if (ch === "\n") out += "\\n";
      else if (ch === "\r") out += "\\r";
      else if (ch === "\t") out += "\\t";
      else if (ch.charCodeAt(0) < 0x20) out += " ";
      else out += ch;
    } else {
      if (ch === '"') inStr = true;
      out += ch;
    }
  }

  return out.replace(/,\s*([}\]])/g, "$1");
}

function normalizeDecision(obj) {
  if (!obj || typeof obj !== "object") return null;

  let action = obj.action;
  if (!action && typeof obj.type === "string") action = { ...obj };
  if (typeof action === "string") action = { type: action };
  if (!action || typeof action !== "object" || !action.type) return null;

  if (action.elementId != null && action.elementId !== "") {
    const num = Number(action.elementId);
    if (!Number.isNaN(num)) action.elementId = num;
  }

  return {
    thought: typeof obj.thought === "string" ? obj.thought : "",
    status: typeof obj.status === "string" ? obj.status : "Выполняю...",
    action,
  };
}

function regexFallbackExtract(rawText) {
  const typeMatch = rawText.match(
    /"type"\s*:\s*"(click|type|hover|scroll|press_key|open_tab|switch_tab|navigate|go_back|download|wait|done|ask_user)"/i
  );
  if (!typeMatch) return null;

  const action = { type: typeMatch[1].toLowerCase() };
  const idMatch = rawText.match(/"elementId"\s*:\s*"?(\d+)"?/i);
  if (idMatch) action.elementId = Number(idMatch[1]);

  const textMatch = rawText.match(/"text"\s*:\s*"((?:\\.|[^"\\])*)"/i);
  if (textMatch) action.text = textMatch[1].replace(/\\n/g, "\n").replace(/\\"/g, '"');

  const urlMatch = rawText.match(/"url"\s*:\s*"((?:\\.|[^"\\])*)"/i);
  if (urlMatch) action.url = urlMatch[1];

  const dirMatch = rawText.match(/"direction"\s*:\s*"(up|down)"/i);
  if (dirMatch) action.direction = dirMatch[1].toLowerCase();

  const summaryMatch = rawText.match(/"summary"\s*:\s*"((?:\\.|[^"\\])*)"/i);
  if (summaryMatch) action.summary = summaryMatch[1].replace(/\\n/g, "\n").replace(/\\"/g, '"');

  const questionMatch = rawText.match(/"question"\s*:\s*"((?:\\.|[^"\\])*)"/i);
  if (questionMatch) action.question = questionMatch[1].replace(/\\n/g, "\n").replace(/\\"/g, '"');

  const thoughtMatch = rawText.match(/"thought"\s*:\s*"((?:\\.|[^"\\])*)"/i);
  const statusMatch = rawText.match(/"status"\s*:\s*"((?:\\.|[^"\\])*)"/i);

  return {
    thought: thoughtMatch ? thoughtMatch[1].replace(/\\n/g, "\n").replace(/\\"/g, '"') : "",
    status: statusMatch ? statusMatch[1] : "Выполняю шаг...",
    action,
  };
}

function parseAgentJson(rawText) {
  if (!rawText || typeof rawText !== "string") return null;

  const candidates = [];
  const fenceRegex = /```(?:json)?\s*([\s\S]*?)```/gi;
  let m;
  while ((m = fenceRegex.exec(rawText)) !== null) candidates.push(m[1].trim());
  candidates.push(extractBalancedJson(rawText));
  candidates.push(rawText.trim());

  for (const cand of candidates) {
    try {
      const parsed = normalizeDecision(JSON.parse(cand));
      if (parsed) return parsed;
    } catch (_) {}

    try {
      const repaired = repairJsonString(extractBalancedJson(cand));
      const parsed = normalizeDecision(JSON.parse(repaired));
      if (parsed) return parsed;
    } catch (_) {}
  }

  return regexFallbackExtract(rawText);
}

// =========================================================
// SYSTEM PROMPT & OPENROUTER API
// =========================================================
const FAST_DEEPSEEK_MODEL = "deepseek/deepseek-chat";
const AUTO_AGENT_PALETTE = [
  { name: "Nova", color: "#af52de" },
  { name: "Vega", color: "#ff2d55" },
  { name: "Lumi", color: "#34c759" },
  { name: "Orion", color: "#ff9500" },
  { name: "Aria", color: "#32ade6" },
];
let autoSpawnCounter = 0;

function buildSystemPrompt(agentName) {
  return `Ты — ${agentName}, автономный AI-агент в браузере Chrome. Отвечай СТРОГО одним валидным JSON-объектом:
{"thought":"Коротко","status":"Статус до 35 символов","action":{"type":"click|double_click|right_click|drag_drop|type|hover|scroll|press_key|modify_dom|open_tab|switch_tab|navigate|go_back|download|spawn_agent|wait|done|ask_user"}}

Параметры action:
- click: {"type":"click","elementId":12}
- double_click: {"type":"double_click","elementId":12}
- right_click: {"type":"right_click","elementId":12}
- drag_drop: {"type":"drag_drop","fromElementId":4,"toElementId":9}
- type: {"type":"type","elementId":5,"text":"...","clearFirst":true,"pressEnter":false}
- hover: {"type":"hover","elementId":8}
- scroll: {"type":"scroll","direction":"down","amount":550}
- press_key: {"type":"press_key","key":"Enter"}
- modify_dom: {"type":"modify_dom","css":"body{...}","hideSelector":".ads","targetSelector":"body","insertHtml":"<div>...</div>"}
- open_tab: {"type":"open_tab","url":"https://..."}
- switch_tab: {"type":"switch_tab","tabId":123}
- navigate: {"type":"navigate","url":"https://..."}
- go_back: {"type":"go_back"}
- download: {"type":"download","url":"https://..."}
- spawn_agent: {"type":"spawn_agent","name":"Nova","prompt":"Подзадача для параллельного агента","url":"https://..."}
- wait: {"type":"wait","ms":1200}
- ask_user: {"type":"ask_user","question":"..."}
- done: {"type":"done","summary":"Краткий и чёткий итог на русском"}

Правила: не используй переносы строк внутри JSON-строк. На скриншотах элементы пронумерованы бейджами Set-of-Mark (используй их ID). Если задачу можно ускорить параллельно — используй spawn_agent.`;
}

async function callOpenRouter({ apiKey, proxyUrl = "", model, messages, tryJsonFormat = true, maxTokens = 2048 }) {
  const endpoint = proxyUrl && /^https?:\/\//i.test(proxyUrl.trim())
    ? proxyUrl.trim()
    : "https://openrouter.ai/api/v1/chat/completions";

  const body = {
    model,
    messages,
    temperature: 0.15,
    max_tokens: maxTokens,
  };
  if (tryJsonFormat) body.response_format = { type: "json_object" };

  const headers = {
    "Content-Type": "application/json",
    "HTTP-Referer": "https://a1x10.github.io/stella-ai",
    "X-Title": "Stella Multi-Agent Browser",
  };
  if (apiKey) headers.Authorization = `Bearer ${apiKey}`;

  const res = await fetch(endpoint, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const errBody = await res.text().catch(() => "");
    let detail = errBody;
    try {
      const parsed = JSON.parse(errBody);
      detail = parsed?.error?.message || errBody;
    } catch (_) {}

    if (tryJsonFormat && (res.status === 400 || /response_format|json_object/i.test(detail))) {
      return callOpenRouter({ apiKey, proxyUrl, model, messages, tryJsonFormat: false, maxTokens });
    }
    throw new Error(`OpenRouter HTTP ${res.status}: ${detail}`);
  }

  const data = await res.json();
  const msg = data?.choices?.[0]?.message;
  const content = msg?.content;
  if (typeof content === "string" && content.trim()) return content;
  if (Array.isArray(content)) {
    const joined = content.map((p) => (typeof p === "string" ? p : p?.text || "")).join("\n").trim();
    if (joined) return joined;
  }
  // Fallback for reasoning models if content was cut off
  if (typeof msg?.reasoning === "string" && msg.reasoning.trim()) {
    return msg.reasoning.trim();
  }
  throw new Error("Модель вернула пустой ответ (попробуйте другую модель или проверьте баланс OpenRouter)");
}

// =========================================================
// ALWAYS-ON QUICK HOVER ANSWER (ULTRA-CHEAP DEEPSEEK + CACHE)
// =========================================================
async function handleQuickAnswer(question, options = []) {
  const cleanQ = String(question || "").trim();
  if (!cleanQ) return { ok: false, error: "Пустой вопрос" };

  const cacheKey = `${cleanQ}::${(options || []).join("|")}`.slice(0, 300);
  const stored = await chrome.storage.local.get(["auraSettings", "auraAnswerCache"]);
  const cache = stored?.auraAnswerCache || {};

  if (cache[cacheKey]) {
    return { ok: true, answer: cache[cacheKey], cached: true };
  }

  const s = stored?.auraSettings || {};
  const apiKey = (s.apiKey || "").trim();
  const proxyUrl = (s.proxyUrl || (!apiKey ? "https://stella-openrouter-proxy.stella-ai-a1x10.workers.dev" : "")).trim();
  if (!apiKey && !proxyUrl) {
    return { ok: false, error: "Добавьте OpenRouter API ключ или Proxy URL в настройках Стеллы" };
  }

  const fallbackModel =
    s.model === "custom" && s.customModel?.trim()
      ? s.customModel.trim()
      : s.model && s.model !== "custom"
      ? s.model
      : "google/gemini-2.5-flash";

  const prompt = options?.length
    ? `Вопрос: ${cleanQ}\nВарианты: ${options.join(" | ")}\nНапиши ТОЛЬКО правильный вариант ответа (максимум 1-2 коротких предложения, без воды).`
    : `Вопрос: ${cleanQ}\nДай максимально короткий и точный ответ на русском (1-2 предложения, без лишних вступлений).`;

  const msgs = [
    { role: "system", content: "Ты мгновенно даёшь точные, сверхкороткие ответы на вопросы на русском. Без markdown и лишних слов." },
    { role: "user", content: prompt },
  ];

  // Use ultra-cheap instant DeepSeek V3 first; fallback to user's model if unavailable
  let raw = "";
  try {
    raw = await callOpenRouter({
      apiKey,
      proxyUrl,
      model: FAST_DEEPSEEK_MODEL,
      tryJsonFormat: false,
      maxTokens: 320,
      messages: msgs,
    });
  } catch (_) {
    raw = await callOpenRouter({
      apiKey,
      proxyUrl,
      model: fallbackModel,
      tryJsonFormat: false,
      maxTokens: 1024,
      messages: msgs,
    });
  }

  const answer = String(raw || "").trim();
  if (answer) {
    cache[cacheKey] = answer;
    const keys = Object.keys(cache);
    if (keys.length > 150) delete cache[keys[0]];
    await chrome.storage.local.set({ auraAnswerCache: cache });
    return { ok: true, answer, cached: false };
  }
  return { ok: false, error: "Не удалось получить ответ" };
}

// =========================================================
// AUTO MULTI-AGENT ORCHESTRATOR (DECIDES WHEN TO SPAWN AGENTS)
// =========================================================
function spawnHelperAgent({ name, prompt, startUrl, settings }) {
  const preset = AUTO_AGENT_PALETTE[autoSpawnCounter % AUTO_AGENT_PALETTE.length];
  autoSpawnCounter++;
  const agentId = `agent-auto-${Date.now()}-${autoSpawnCounter}`;
  const agentName = (name && String(name).trim().slice(0, 18)) || preset.name;
  const agentColor = preset.color;

  broadcast({
    event: "spawned",
    agentId,
    agentName,
    agentColor,
    prompt,
  });

  runAgentTask({
    agentId,
    agentName,
    agentColor,
    openNewTab: true,
    startUrl: startUrl || null,
    prompt,
    settings,
  });

  return { agentId, agentName };
}

const DEFAULT_CLOUD_PROXY = "https://stella-openrouter-proxy.stella-ai-a1x10.workers.dev";

async function planMultiAgentSplit(prompt, apiKey, proxyUrl = "") {
  const lower = String(prompt || "").toLowerCase();
  // Quick heuristic: only invoke the ultra-cheap DeepSeek planner if the prompt looks multi-part or explicitly mentions multiple agents/tabs
  const looksMulti =
    /несколько\s+агент|агентов|\b[2-5]\s*агент|параллельно|одновременно|в\s+другой\s+вкладке|в\s+разных\s+вкладках|еще\s+одного|раздели|а\s+ещё|а\s+еще|,\s*а\s+|;\s*/i.test(
      lower
    ) || prompt.length > 85;

  const effProxy = proxyUrl || (!apiKey ? DEFAULT_CLOUD_PROXY : "");
  if (!looksMulti || (!apiKey && !effProxy)) return null;

  try {
    const raw = await callOpenRouter({
      apiKey,
      proxyUrl: effProxy,
      model: FAST_DEEPSEEK_MODEL,
      tryJsonFormat: true,
      maxTokens: 450,
      messages: [
        {
          role: "system",
          content:
            'Ты планировщик браузерных агентов. Реши, нужна ли 1 задача или лучше запустить 2-4 параллельных агента (например, пользователь просит несколько агентов или дал независимые задачи на разных сайтах/вкладках). Верни ТОЛЬКО JSON: {"agents":[{"name":"Стелла","prompt":"конкретная задача","openNewTab":false,"url":""}]}. Если достаточно 1 агента — верни массив из 1 элемента. Максимум 4 агента. Придумывай короткие имена (Стелла, Nova, Vega, Lumi).',
        },
        { role: "user", content: prompt },
      ],
    });

    const parsed = JSON.parse(repairJsonString(extractBalancedJson(raw)));
    if (Array.isArray(parsed?.agents) && parsed.agents.length >= 2) {
      return parsed.agents.slice(0, 4).filter((a) => a && a.prompt);
    }
  } catch (_) {}
  return null;
}

// =========================================================
// PARALLEL AGENT EXECUTION LOOP (ECONOMY + SMART VISION)
// =========================================================
async function runAgentTask({ agentId, agentName, agentColor, openNewTab, startUrl = null, prompt, settings }) {
  const prev = agents.get(agentId);
  const runId = (prev?.runId || 0) + 1;

  const agent = {
    id: agentId,
    name: agentName || "Стелла",
    color: agentColor || "#007aff",
    running: true,
    stopRequested: false,
    runId,
    tabId: null,
    groupId: prev?.groupId ?? null,
  };
  agents.set(agentId, agent);

  const {
    apiKey = "",
    proxyUrl: rawProxyUrl = "",
    model = FAST_DEEPSEEK_MODEL,
    useVision = false,
    useDebugger = true,
    safetyGate = true,
    edgeGlow = true,
    showCursor = true,
    maxSteps = 20,
  } = settings;
  const proxyUrl = (rawProxyUrl || (!apiKey.trim() ? DEFAULT_CLOUD_PROXY : "")).trim();

  const history = [];
  let lastOverlayTabId = null;
  let lastDebugTabId = null;
  let lastActionFailed = false;

  broadcast({ agentId, event: "started", status: "Выполняю..." });
  playAgentSound("start");

  try {
    let initialTab;
    if (openNewTab || startUrl) {
      let targetUrl = startUrl || "https://www.google.com";
      if (!/^https?:\/\//i.test(targetUrl)) targetUrl = `https://${targetUrl}`;
      initialTab = await chrome.tabs.create({ url: targetUrl, active: !openNewTab });
      agent.tabId = initialTab.id;
      await assignTabToAgentGroup(agent, initialTab.id);
      await waitForTabComplete(initialTab.id, agent);
    } else {
      initialTab = await getActiveTab();
      if (!initialTab) throw new Error("Не найдена активная вкладка браузера");
      agent.tabId = initialTab.id;
      await assignTabToAgentGroup(agent, initialTab.id);
    }

    // 1. Try ZERO-CREDIT local automation first!
    const localResult = await tryLocalAutomation(prompt, agent, initialTab);
    if (localResult) {
      playAgentSound("done");
      broadcast({ agentId, event: "done", step: 1, summary: localResult });
      return;
    }

    if (!apiKey.trim() && !proxyUrl.trim()) {
      agent.running = false;
      broadcast({
        agentId,
        event: "error",
        message: "Для сложной задачи нужен OpenRouter API ключ или Proxy URL (настройки ⚙️).",
      });
      return;
    }

    // 2. Smart AI Loop (DOM-first economy; Vision only when forced or DOM is sparse/failed)
    for (let step = 1; step <= maxSteps; step++) {
      if (agent.stopRequested || agent.runId !== runId) break;

      let tab;
      try {
        tab = await chrome.tabs.get(agent.tabId);
      } catch (_) {
        tab = await getActiveTab();
        if (!tab) throw new Error("Вкладка агента была закрыта");
        agent.tabId = tab.id;
      }

      if (lastOverlayTabId && lastOverlayTabId !== tab.id) {
        await safeHideOverlay(lastOverlayTabId, agent.id);
      }
      if (lastDebugTabId && lastDebugTabId !== tab.id) {
        await detachDebuggerIfUnused(lastDebugTabId);
        lastDebugTabId = null;
      }

      const canInject = await ensureContentScript(tab.id, tab.url);

      if (useDebugger && !isRestrictedUrl(tab.url)) {
        const attached = await attachDebugger(tab.id);
        if (attached) lastDebugTabId = tab.id;
      }

      if (canInject) {
        lastOverlayTabId = tab.id;
        await chrome.tabs
          .sendMessage(tab.id, {
            type: "SHOW_OVERLAY",
            options: {
              agentId: agent.id,
              agentName: agent.name,
              agentColor: agent.color,
              edgeGlow,
              showCursor,
              status: `Шаг ${step}...`,
            },
          })
          .catch(() => {});
      }

      broadcast({
        agentId,
        event: "status",
        state: "thinking",
        step,
        status: `Шаг ${step}: Анализирую...`,
      });

      const allTabs = await chrome.tabs.query({ currentWindow: true });
      const openTabsSummary = allTabs.map((t) => ({
        id: t.id,
        me: t.id === tab.id ? 1 : 0,
        title: (t.title || "").slice(0, 45),
        url: (t.url || "").slice(0, 90),
      }));

      let pageObs = null;
      if (canInject) {
        try {
          const obsRes = await chrome.tabs.sendMessage(tab.id, { type: "OBSERVE_PAGE" });
          if (obsRes?.ok) pageObs = obsRes.data;
        } catch (_) {}
      }

      // Smart Vision-on-Demand: only spend image tokens if Vision toggle is ON OR DOM is empty/failed
      const needScreenshot =
        useVision ||
        lastActionFailed ||
        (pageObs && pageObs.elements.length < 3 && pageObs.pageText.length < 80);

      let screenshotUrl = null;
      if (needScreenshot) {
        screenshotUrl = await captureScreenshotSmart(tab, useDebugger);
      }

      const debugLogs = tabDebugLogs.get(tab.id) || [];
      const observationText = [
        `ЦЕЛЬ: ${prompt}`,
        `ШАГ: ${step}/${maxSteps} | URL: ${tab.url || ""}`,
        `ВКЛАДКИ: ${JSON.stringify(openTabsSummary)}`,
        history.length ? `ИСТОРИЯ:\n${history.slice(-6).join("\n")}` : "",
        debugLogs.length ? `ОШИБКИ КОНСОЛИ/СЕТИ:\n${debugLogs.slice(-4).join("\n")}` : "",
        pageObs
          ? `ЭЛЕМЕНТЫ: ${JSON.stringify(pageObs.elements)}\nТЕКСТ: ${pageObs.pageText}`
          : "Системная страница без DOM. Используй navigate или open_tab.",
      ]
        .filter(Boolean)
        .join("\n");

      const userContent = screenshotUrl
        ? [
            { type: "text", text: observationText },
            { type: "image_url", image_url: { url: screenshotUrl } },
          ]
        : observationText;

      const messages = [
        { role: "system", content: buildSystemPrompt(agent.name) },
        { role: "user", content: userContent },
      ];

      let decision = null;
      let lastRaw = "";

      for (let attempt = 0; attempt < 3; attempt++) {
        if (agent.stopRequested || agent.runId !== runId) break;
        const attemptMessages =
          attempt === 0
            ? messages
            : [
                ...messages,
                { role: "assistant", content: lastRaw.slice(0, 300) },
                { role: "user", content: 'Верни ТОЛЬКО валидный JSON {"thought":"...","status":"...","action":{"type":"..."}}.' },
              ];

        try {
          lastRaw = await callOpenRouter({
            apiKey: apiKey.trim(),
            proxyUrl: proxyUrl.trim(),
            model,
            messages: attemptMessages,
          });
        } catch (err) {
          if (screenshotUrl && /image|vision|multimodal|content/i.test(String(err.message))) {
            screenshotUrl = null;
            lastRaw = await callOpenRouter({
              apiKey: apiKey.trim(),
              proxyUrl: proxyUrl.trim(),
              model,
              messages: [
                { role: "system", content: buildSystemPrompt(agent.name) },
                { role: "user", content: observationText },
              ],
            });
          } else {
            throw err;
          }
        }

        decision = parseAgentJson(lastRaw);
        if (decision) break;
        await sleep(250);
      }

      if (agent.stopRequested || agent.runId !== runId) break;

      if (!decision) {
        decision = {
          thought: "",
          status: "Повторяю...",
          action: { type: "wait", ms: 700 },
        };
      }

      const { thought = "", status = "Выполняю...", action } = decision;

      // Broadcast lightweight status only (keeps chat clean — no step/screenshot spam!)
      broadcast({
        agentId,
        event: "status",
        state: "acting",
        step,
        status: status || thought.slice(0, 40) || "Выполняю...",
      });

      if (canInject) {
        await chrome.tabs
          .sendMessage(tab.id, {
            type: "UPDATE_ISLAND",
            text: status || thought.slice(0, 42),
            tag: action.type,
            agentId: agent.id,
            agentName: agent.name,
            agentColor: agent.color,
          })
          .catch(() => {});
      }

      if (action.type === "done") {
        const summary = action.summary || thought || "Готово!";
        playAgentSound("done");
        sendNotification(`✅ ${agent.name}`, summary);
        broadcast({ agentId, event: "done", step, summary });
        break;
      }

      if (action.type === "ask_user") {
        const question = action.question || thought || "Нужна ваша помощь.";
        playAgentSound("notify");
        sendNotification(`💬 ${agent.name}`, question);
        broadcast({ agentId, event: "ask_user", step, question });
        break;
      }

      // Safety Gate: pause before sensitive actions (payment, delete, transfer, checkout)
      if (safetyGate && ["click", "double_click"].includes(action.type) && pageObs?.elements) {
        const targetEl = pageObs.elements.find((e) => e.id === Number(action.elementId));
        const targetLabel = `${targetEl?.text || ""} ${targetEl?.aria || ""} ${action.label || ""}`.toLowerCase();
        if (/(оплат|купить|перевест|удалить\s+аккаунт|удалить\s+вс|подтвердить\s+заказ|pay\s+now|checkout|purchase|delete\s+account)/i.test(targetLabel)) {
          const warnMsg = `🛡️ Требуется подтверждение: агент собирается нажать «${(targetEl?.text || action.label || "кнопку").slice(0, 50)}». Подтвердите действие вручную на странице.`;
          playAgentSound("notify");
          sendNotification(`🛡️ ${agent.name} — проверка безопасности`, warnMsg);
          broadcast({ agentId, event: "ask_user", step, question: warnMsg });
          break;
        }
      }

      let actionResult = { ok: true };

      if (action.type === "open_tab") {
        let url = action.url || "https://www.google.com";
        if (!/^https?:\/\//i.test(url)) url = `https://${url}`;
        const created = await chrome.tabs.create({ url, active: true });
        agent.tabId = created.id;
        await assignTabToAgentGroup(agent, created.id);
        await waitForTabComplete(created.id, agent);
      } else if (action.type === "switch_tab") {
        const targetId = Number(action.tabId);
        await chrome.tabs.update(targetId, { active: true });
        agent.tabId = targetId;
        await sleep(360);
      } else if (action.type === "navigate") {
        let url = action.url || "https://www.google.com";
        if (!/^https?:\/\//i.test(url)) url = `https://${url}`;
        await chrome.tabs.update(tab.id, { url });
        await waitForTabComplete(tab.id, agent);
      } else if (action.type === "go_back") {
        await chrome.tabs.goBack(tab.id).catch(() => {});
        await waitForTabComplete(tab.id, agent);
      } else if (action.type === "download") {
        if (action.url) {
          await chrome.downloads.download({ url: action.url, filename: action.filename || undefined, saveAs: false });
        } else {
          actionResult = { ok: false, error: "Нет url" };
        }
      } else if (action.type === "spawn_agent") {
        if (action.prompt) {
          const spawned = spawnHelperAgent({
            name: action.name,
            prompt: action.prompt,
            startUrl: action.url || null,
            settings,
          });
          actionResult = { ok: true, spawned };
        } else {
          actionResult = { ok: false, error: "Нет prompt для нового агента" };
        }
      } else if (action.type === "wait") {
        await sleep(Math.min(5000, Math.max(300, Number(action.ms) || 900)));
      } else {
        if (!canInject) {
          actionResult = { ok: false, error: "Системная страница" };
        } else {
          actionResult = await chrome.tabs
            .sendMessage(tab.id, {
              type: "EXECUTE_ACTION",
              action,
              agentId: agent.id,
              agentName: agent.name,
              agentColor: agent.color,
            })
            .catch((e) => ({ ok: false, error: String(e?.message || e) }));

          if (action.type === "click" && actionResult?.ok && typeof actionResult.x === "number") {
            playAgentSound("click");
            if (useDebugger && attachedDebuggerTabs.has(tab.id) && action.trusted) {
              await cdpTrustedClick(tab.id, actionResult.x, actionResult.y);
            }
          }
          await sleep(440);
        }
      }

      lastActionFailed = !actionResult?.ok;
      history.push(`${step}:${action.type}(${action.elementId ?? action.url ?? ""})=${actionResult?.ok ? "OK" : "ERR"}`);

      if (step === maxSteps) {
        playAgentSound("done");
        sendNotification(`✅ ${agent.name}`, "Достигнут лимит шагов.");
        broadcast({ agentId, event: "done", step, summary: "Достигнут лимит шагов." });
      }
    }

    if (agent.stopRequested) {
      broadcast({ agentId, event: "stopped", message: `${agent.name} остановлен.` });
    }
  } catch (err) {
    broadcast({ agentId, event: "error", message: String(err?.message || err) });
  } finally {
    agent.running = false;
    if (lastOverlayTabId) await safeHideOverlay(lastOverlayTabId, agent.id);
    if (agent.tabId && agent.tabId !== lastOverlayTabId) await safeHideOverlay(agent.tabId, agent.id);
    if (lastDebugTabId) await detachDebuggerIfUnused(lastDebugTabId);
  }
}

// =========================================================
// RUNTIME MESSAGE ROUTER
// =========================================================
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.target === "offscreen") return;

  (async () => {
    if (msg.type === "QUICK_ANSWER") {
      try {
        const res = await handleQuickAnswer(msg.question, msg.options);
        sendResponse(res);
      } catch (err) {
        sendResponse({ ok: false, error: String(err?.message || err) });
      }
      return;
    }

    if (msg.type === "START_AGENT") {
      const agentId = msg.agentId || "agent-1";
      const existing = agents.get(agentId);
      if (existing?.running) {
        sendResponse({ ok: false, error: "Агент уже занят. Нажми +, чтобы создать ещё одного." });
        return;
      }
      sendResponse({ ok: true });

      const s = msg.settings || {};
      const autoMulti = s.autoMultiAgent !== false;

      if (autoMulti && (s.apiKey?.trim() || s.proxyUrl?.trim() || DEFAULT_CLOUD_PROXY)) {
        broadcast({ agentId, event: "started", status: "Планирую агентов..." });
        const plan = await planMultiAgentSplit(msg.prompt, (s.apiKey || "").trim(), (s.proxyUrl || "").trim());
        if (plan && plan.length >= 2) {
          // Run first subtask on current agent, and auto-spawn parallel helper agents for the rest!
          const first = plan[0];
          const extraNames = [];
          for (let i = 1; i < plan.length; i++) {
            const sub = plan[i];
            const res = spawnHelperAgent({
              name: sub.name,
              prompt: sub.prompt,
              startUrl: sub.url || null,
              settings: s,
            });
            extraNames.push(res.agentName);
          }
          broadcast({
            agentId,
            event: "status",
            state: "acting",
            step: 1,
            status: `Запустил команду: ${extraNames.join(", ")}`,
          });
          runAgentTask({
            agentId,
            agentName: msg.agentName || "Стелла",
            agentColor: msg.agentColor || "#007aff",
            openNewTab: !!msg.openNewTab || !!first.openNewTab,
            startUrl: first.url || null,
            prompt: first.prompt,
            settings: s,
          });
          return;
        }
      }

      runAgentTask({
        agentId,
        agentName: msg.agentName || "Стелла",
        agentColor: msg.agentColor || "#007aff",
        openNewTab: !!msg.openNewTab,
        prompt: msg.prompt,
        settings: s,
      });
      return;
    }

    if (msg.type === "STOP_AGENT") {
      const agent = agents.get(msg.agentId);
      if (agent) {
        agent.stopRequested = true;
        agent.running = false;
        if (agent.tabId) {
          await safeHideOverlay(agent.tabId, agent.id);
          await detachDebuggerIfUnused(agent.tabId);
        }
      }
      sendResponse({ ok: true });
      return;
    }

    if (msg.type === "STOP_ALL_AGENTS") {
      for (const agent of agents.values()) {
        agent.stopRequested = true;
        agent.running = false;
        if (agent.tabId) {
          await safeHideOverlay(agent.tabId, agent.id);
          await detachDebuggerIfUnused(agent.tabId);
        }
      }
      sendResponse({ ok: true });
      return;
    }

    if (msg.type === "RUN_DEMO_MOTION") {
      const tab = await getActiveTab();
      if (!tab || isRestrictedUrl(tab.url)) {
        sendResponse({ ok: false, error: "Откройте любой обычный сайт (например, google.com)." });
        return;
      }
      const ok = await ensureContentScript(tab.id, tab.url);
      if (!ok) {
        sendResponse({ ok: false, error: "Обновите страницу и попробуйте снова." });
        return;
      }
      playAgentSound("start");
      const res = await chrome.tabs.sendMessage(tab.id, { type: "DEMO_MOTION" }).catch((e) => ({
        ok: false,
        error: String(e?.message || e),
      }));
      sendResponse(res);
      return;
    }

    if (msg.type === "START_REC") {
      const tab = await getActiveTab();
      if (!tab || isRestrictedUrl(tab.url)) {
        sendResponse({ ok: false, error: "Откройте обычный сайт для записи сценария." });
        return;
      }
      await ensureContentScript(tab.id, tab.url);
      const res = await chrome.tabs.sendMessage(tab.id, { type: "START_RECORDING" }).catch((e) => ({ ok: false, error: String(e) }));
      sendResponse(res);
      return;
    }

    if (msg.type === "STOP_REC") {
      const tab = await getActiveTab();
      if (!tab) {
        sendResponse({ ok: false, error: "Нет активной вкладки" });
        return;
      }
      const res = await chrome.tabs.sendMessage(tab.id, { type: "STOP_RECORDING" }).catch((e) => ({ ok: false, error: String(e) }));
      if (res?.ok && res.steps?.length) {
        const stored = await chrome.storage.local.get("stellaMacros");
        const macros = stored?.stellaMacros || [];
        macros.unshift({
          id: `macro-${Date.now()}`,
          name: msg.name || res.title?.slice(0, 28) || "Сценарий",
          url: res.url,
          steps: res.steps,
        });
        await chrome.storage.local.set({ stellaMacros: macros.slice(0, 20) });
      }
      sendResponse(res);
      return;
    }

    if (msg.type === "PLAY_MACRO") {
      const tab = await getActiveTab();
      if (!tab || isRestrictedUrl(tab.url)) {
        sendResponse({ ok: false, error: "Откройте сайт для запуска сценария." });
        return;
      }
      await ensureContentScript(tab.id, tab.url);
      playAgentSound("start");
      const res = await chrome.tabs.sendMessage(tab.id, { type: "REPLAY_MACRO", steps: msg.steps || [] }).catch((e) => ({
        ok: false,
        error: String(e),
      }));
      if (res?.ok) playAgentSound("done");
      sendResponse(res);
      return;
    }

    if (msg.type === "CREATE_SCHEDULE") {
      const id = `stella-sched-${Date.now()}`;
      const periodMinutes = Math.max(1, Number(msg.periodMinutes) || 60);
      const stored = await chrome.storage.local.get("stellaSchedules");
      const list = stored?.stellaSchedules || [];
      const item = { id, prompt: msg.prompt, periodMinutes };
      list.push(item);
      await chrome.storage.local.set({ stellaSchedules: list });
      chrome.alarms.create(id, { periodInMinutes: periodMinutes });
      sendResponse({ ok: true, item });
      return;
    }

    if (msg.type === "DELETE_SCHEDULE") {
      await chrome.alarms.clear(msg.id);
      const stored = await chrome.storage.local.get("stellaSchedules");
      const list = (stored?.stellaSchedules || []).filter((s) => s.id !== msg.id);
      await chrome.storage.local.set({ stellaSchedules: list });
      sendResponse({ ok: true });
      return;
    }
  })();

  return true;
});

// =========================================================
// SCHEDULED TASKS ENGINE (chrome.alarms)
// =========================================================
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (!alarm?.name?.startsWith("stella-sched-")) return;
  const stored = await chrome.storage.local.get(["stellaSchedules", "auraSettings"]);
  const sched = (stored?.stellaSchedules || []).find((s) => s.id === alarm.name);
  if (!sched) return;

  const s = stored?.auraSettings || {};
  const model =
    s.model === "custom" && s.customModel?.trim()
      ? s.customModel.trim()
      : s.model && s.model !== "custom"
      ? s.model
      : FAST_DEEPSEEK_MODEL;

  sendNotification("⏰ Стелла — запуск по расписанию", sched.prompt);
  runAgentTask({
    agentId: `sched-${Date.now()}`,
    agentName: "Стелла",
    agentColor: "#007aff",
    openNewTab: true,
    prompt: sched.prompt,
    settings: { ...s, model },
  });
});

// Aura Multi-Agent Side Panel Controller

const DEFAULT_SETTINGS = {
  apiKey: "",
  proxyUrl: "https://stella-openrouter-proxy.stella-ai-a1x10.workers.dev",
  model: "deepseek/deepseek-chat",
  customModel: "",
  useVision: false,
  useDebugger: true,
  autoMultiAgent: true,
  hoverAnswer: true,
  safetyGate: true,
  edgeGlow: true,
  showCursor: true,
  maxSteps: 20,
};

const AGENT_PRESETS = [
  { name: "Стелла", color: "#007aff" },
  { name: "Nova", color: "#af52de" },
  { name: "Vega", color: "#ff2d55" },
  { name: "Lumi", color: "#34c759" },
  { name: "Orion", color: "#ff9500" },
  { name: "Aria", color: "#32ade6" },
];

let settings = { ...DEFAULT_SETTINGS };
let agentCounter = 1;

// Multi-agent local UI store
const agentProfiles = new Map();
let activeAgentId = "agent-1";

function createAgentProfile({ id, name, color, openNewTab = false }) {
  const profile = {
    id,
    name,
    color,
    openNewTab,
    running: false,
    state: "idle",
    badge: "Готов",
    step: 0,
    islandText: "Думаю...",
    feed: [], // { kind: 'user' | 'step', ... }
  };
  agentProfiles.set(id, profile);
  return profile;
}

createAgentProfile({
  id: "agent-1",
  name: AGENT_PRESETS[0].name,
  color: AGENT_PRESETS[0].color,
  openNewTab: false,
});

// DOM elements
const body = document.body;
const activeAgentTitle = document.getElementById("activeAgentTitle");
const statusBadge = document.getElementById("statusBadge");
const modelPillText = document.getElementById("modelPillText");
const agentsListEl = document.getElementById("agentsList");
const addAgentBtn = document.getElementById("addAgentBtn");

const liveIsland = document.getElementById("liveIsland");
const islandPulse = document.getElementById("islandPulse");
const islandStep = document.getElementById("islandStep");
const islandText = document.getElementById("islandText");
const islandStopBtn = document.getElementById("islandStopBtn");

const heroWelcome = document.getElementById("heroWelcome");
const heroOrbTrigger = document.getElementById("heroOrbTrigger");
const feedList = document.getElementById("feedList");
const timelineStage = document.getElementById("timelineStage");

const promptInput = document.getElementById("promptInput");
const sendBtn = document.getElementById("sendBtn");
const iconSend = sendBtn.querySelector(".icon-send");
const iconStop = sendBtn.querySelector(".icon-stop");
const visionToggle = document.getElementById("visionToggle");
const visionDot = visionToggle.querySelector(".chip-dot");
const modelPill = document.getElementById("modelPill");

const recordBtn = document.getElementById("recordBtn");
const demoMotionBtn = document.getElementById("demoMotionBtn");
const clearChatBtn = document.getElementById("clearChatBtn");
const settingsBtn = document.getElementById("settingsBtn");

// New Agent Sheet
const newAgentSheet = document.getElementById("newAgentSheet");
const closeNewAgentBtn = document.getElementById("closeNewAgentBtn");
const newAgentNameInput = document.getElementById("newAgentNameInput");
const newAgentNewTabToggle = document.getElementById("newAgentNewTabToggle");
const confirmNewAgentBtn = document.getElementById("confirmNewAgentBtn");

// Settings Sheet
const settingsSheet = document.getElementById("settingsSheet");
const closeSettingsBtn = document.getElementById("closeSettingsBtn");
const apiKeyInput = document.getElementById("apiKeyInput");
const proxyUrlInput = document.getElementById("proxyUrlInput");
const toggleKeyVisBtn = document.getElementById("toggleKeyVisBtn");
const modelSelect = document.getElementById("modelSelect");
const customModelGroup = document.getElementById("customModelGroup");
const customModelInput = document.getElementById("customModelInput");
const autoMultiToggle = document.getElementById("autoMultiToggle");
const hoverAnswerToggle = document.getElementById("hoverAnswerToggle");
const debuggerToggle = document.getElementById("debuggerToggle");
const edgeGlowToggle = document.getElementById("edgeGlowToggle");
const cursorToggle = document.getElementById("cursorToggle");
const safetyGateToggle = document.getElementById("safetyGateToggle");
const maxStepsRange = document.getElementById("maxStepsRange");
const maxStepsVal = document.getElementById("maxStepsVal");
const macrosListEl = document.getElementById("macrosList");
const schedPromptInput = document.getElementById("schedPromptInput");
const schedMinInput = document.getElementById("schedMinInput");
const addSchedBtn = document.getElementById("addSchedBtn");
const schedulesListEl = document.getElementById("schedulesList");
const saveSettingsBtn = document.getElementById("saveSettingsBtn");

let isRecordingMacro = false;

// =========================================================
// HELPERS
// =========================================================
function getActiveAgent() {
  return agentProfiles.get(activeAgentId);
}

function getEffectiveModel() {
  if (settings.model === "custom" && settings.customModel.trim()) {
    return settings.customModel.trim();
  }
  return settings.model === "custom" ? "google/gemini-2.5-flash" : settings.model;
}

function getShortModelName(modelId) {
  const parts = String(modelId).split("/");
  const name = parts[parts.length - 1] || modelId;
  return name
    .replace(/-/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .slice(0, 22);
}

function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function scrollFeedToBottom() {
  requestAnimationFrame(() => {
    timelineStage.scrollTop = timelineStage.scrollHeight;
  });
}

function formatActionDetail(action) {
  if (!action) return "";
  if (action.type === "click") {
    return action.label
      ? `${action.label}${action.elementId ? ` (#${action.elementId})` : ""}`
      : `Элемент #${action.elementId ?? `${action.x},${action.y}`}`;
  }
  if (action.type === "type") return `Поле #${action.elementId}: "${action.text}"`;
  if (action.type === "open_tab" || action.type === "navigate") return action.url || "";
  if (action.type === "switch_tab") return `Вкладка #${action.tabId}`;
  if (action.type === "scroll") return `${action.direction === "up" ? "Вверх" : "Вниз"} на ${action.amount || 550}px`;
  if (action.type === "hover") return `Элемент #${action.elementId}`;
  return "";
}

// =========================================================
// RENDERING MULTI-AGENT UI
// =========================================================
function renderAgentsBar() {
  agentsListEl.innerHTML = "";
  for (const agent of agentProfiles.values()) {
    const pill = document.createElement("button");
    pill.className = `agent-pill${agent.id === activeAgentId ? " active" : ""}${agent.running ? " running" : ""}`;
    pill.innerHTML = `
      <span class="agent-dot" style="background: ${agent.color}; box-shadow: 0 0 8px ${agent.color}88;"></span>
      <span>${escapeHtml(agent.name)}</span>
      ${agentProfiles.size > 1 ? `<span class="agent-close" data-close-id="${agent.id}" title="Удалить агента">×</span>` : ""}
    `;
    pill.addEventListener("click", (e) => {
      const closeId = e.target?.getAttribute?.("data-close-id");
      if (closeId) {
        e.stopPropagation();
        removeAgent(closeId);
        return;
      }
      selectAgent(agent.id);
    });
    agentsListEl.appendChild(pill);
  }
}

function renderActiveAgentView() {
  const agent = getActiveAgent();
  if (!agent) return;

  activeAgentTitle.textContent = agent.name;
  statusBadge.textContent = agent.badge;
  body.setAttribute("data-state", agent.state);
  promptInput.placeholder = `Задача для ${agent.name}...`;

  sendBtn.classList.toggle("is-running", agent.running);
  iconSend.classList.toggle("hidden", agent.running);
  iconStop.classList.toggle("hidden", !agent.running);

  liveIsland.classList.toggle("hidden", !agent.running);
  if (agent.running) {
    islandPulse.style.background = agent.color;
    islandStep.textContent = agent.step ? `Шаг ${agent.step}` : "Старт";
    islandText.textContent = agent.islandText || "Думаю...";
  }

  feedList.innerHTML = "";
  if (agent.feed.length === 0) {
    heroWelcome.classList.remove("hidden");
  } else {
    heroWelcome.classList.add("hidden");
    for (const item of agent.feed) {
      appendFeedItemDOM(item);
    }
    scrollFeedToBottom();
  }

  renderAgentsBar();
}

function appendFeedItemDOM(item) {
  if (item.kind === "user") {
    const el = document.createElement("div");
    el.className = "msg-user";
    el.textContent = item.text;
    feedList.appendChild(el);
    return;
  }

  const card = document.createElement("div");
  card.className = `step-card ${item.variant || ""}`;
  let html = `
    <div class="step-header">
      <span class="step-action-pill">${escapeHtml(item.title)}</span>
      ${item.step ? `<span class="step-num">Шаг ${escapeHtml(item.step)}</span>` : ""}
    </div>
  `;
  if (item.thought) html += `<div class="step-thought">${escapeHtml(item.thought)}</div>`;
  if (item.detail) html += `<div class="step-detail">${escapeHtml(item.detail)}</div>`;
  if (item.screenshot) html += `<div class="step-shot-wrap"><img src="${item.screenshot}" alt="Скриншот" /></div>`;
  card.innerHTML = html;
  feedList.appendChild(card);
}

function pushFeedItem(agentId, item) {
  const agent = agentProfiles.get(agentId);
  if (!agent) return;
  agent.feed.push(item);
  if (agentId === activeAgentId) {
    heroWelcome.classList.add("hidden");
    appendFeedItemDOM(item);
    scrollFeedToBottom();
  }
}

function selectAgent(id) {
  if (!agentProfiles.has(id)) return;
  activeAgentId = id;
  renderActiveAgentView();
}

async function removeAgent(id) {
  const agent = agentProfiles.get(id);
  if (!agent || agentProfiles.size <= 1) return;
  if (agent.running) {
    await chrome.runtime.sendMessage({ type: "STOP_AGENT", agentId: id });
  }
  agentProfiles.delete(id);
  if (activeAgentId === id) {
    activeAgentId = agentProfiles.keys().next().value;
  }
  renderActiveAgentView();
}

// =========================================================
// SETTINGS
// =========================================================
async function loadSettings() {
  const stored = await chrome.storage.local.get("auraSettings");
  if (stored?.auraSettings) {
    settings = { ...DEFAULT_SETTINGS, ...stored.auraSettings };
  }
  syncSettingsToUI();
}

function syncSettingsToUI() {
  const effModel = getEffectiveModel();
  modelPillText.textContent = getShortModelName(effModel);
  visionDot.classList.toggle("active", !!settings.useVision);

  apiKeyInput.value = settings.apiKey || "";
  proxyUrlInput.value = settings.proxyUrl || "";
  const isPreset = Array.from(modelSelect.options).some((o) => o.value === settings.model);
  modelSelect.value = isPreset ? settings.model : "custom";
  customModelInput.value = isPreset ? settings.customModel || "" : settings.model;
  customModelGroup.classList.toggle("hidden", modelSelect.value !== "custom");

  autoMultiToggle.checked = settings.autoMultiAgent !== false;
  hoverAnswerToggle.checked = settings.hoverAnswer !== false;
  debuggerToggle.checked = settings.useDebugger !== false;
  edgeGlowToggle.checked = settings.edgeGlow !== false;
  cursorToggle.checked = settings.showCursor !== false;
  safetyGateToggle.checked = settings.safetyGate !== false;
  maxStepsRange.value = String(settings.maxSteps || 20);
  maxStepsVal.textContent = String(settings.maxSteps || 20);
}

async function saveSettings() {
  settings = {
    ...settings,
    apiKey: apiKeyInput.value.trim(),
    proxyUrl: proxyUrlInput.value.trim(),
    model: modelSelect.value,
    customModel: customModelInput.value.trim(),
    autoMultiAgent: autoMultiToggle.checked,
    hoverAnswer: hoverAnswerToggle.checked,
    useDebugger: debuggerToggle.checked,
    edgeGlow: edgeGlowToggle.checked,
    showCursor: cursorToggle.checked,
    safetyGate: safetyGateToggle.checked,
    maxSteps: Number(maxStepsRange.value) || 20,
  };
  await chrome.storage.local.set({ auraSettings: settings });
  syncSettingsToUI();
  settingsSheet.classList.add("hidden");
}

async function refreshMacrosAndSchedules() {
  const stored = await chrome.storage.local.get(["stellaMacros", "stellaSchedules"]);
  const macros = stored?.stellaMacros || [];
  const scheds = stored?.stellaSchedules || [];

  if (!macros.length) {
    macrosListEl.textContent = "Нажмите ● в шапке, чтобы записать сценарий.";
  } else {
    macrosListEl.innerHTML = "";
    macros.slice(0, 6).forEach((m) => {
      const row = document.createElement("div");
      row.style.cssText = "display:flex;align-items:center;justify-content:space-between;gap:6px;margin-top:5px;";
      row.innerHTML = `<span style="font-size:12px;color:#1d1d1f;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">▶ ${escapeHtml(m.name)} (${m.steps.length})</span>`;
      const btn = document.createElement("button");
      btn.className = "ghost-btn";
      btn.textContent = "Запуск";
      btn.addEventListener("click", async () => {
        settingsSheet.classList.add("hidden");
        await chrome.runtime.sendMessage({ type: "PLAY_MACRO", steps: m.steps });
      });
      row.appendChild(btn);
      macrosListEl.appendChild(row);
    });
  }

  if (!scheds.length) {
    schedulesListEl.textContent = "Нет активных расписаний";
  } else {
    schedulesListEl.innerHTML = "";
    scheds.forEach((s) => {
      const row = document.createElement("div");
      row.style.cssText = "display:flex;align-items:center;justify-content:space-between;gap:6px;margin-top:5px;";
      row.innerHTML = `<span style="font-size:12px;color:#1d1d1f;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">⏰ ${escapeHtml(s.prompt)} (каждые ${s.periodMinutes} мин)</span>`;
      const del = document.createElement("button");
      del.className = "ghost-btn";
      del.textContent = "×";
      del.addEventListener("click", async () => {
        await chrome.runtime.sendMessage({ type: "DELETE_SCHEDULE", id: s.id });
        refreshMacrosAndSchedules();
      });
      row.appendChild(del);
      schedulesListEl.appendChild(row);
    });
  }
}

function openSettings() {
  syncSettingsToUI();
  refreshMacrosAndSchedules();
  settingsSheet.classList.remove("hidden");
}

function openNewAgentModal() {
  const preset = AGENT_PRESETS[agentCounter % AGENT_PRESETS.length];
  newAgentNameInput.value = preset.name;
  newAgentNewTabToggle.checked = true;
  newAgentSheet.classList.remove("hidden");
  setTimeout(() => {
    newAgentNameInput.focus();
    newAgentNameInput.select();
  }, 80);
}

function confirmCreateAgent() {
  const preset = AGENT_PRESETS[agentCounter % AGENT_PRESETS.length];
  const name = newAgentNameInput.value.trim() || preset.name;
  agentCounter++;
  const id = `agent-${Date.now()}-${agentCounter}`;
  createAgentProfile({
    id,
    name,
    color: preset.color,
    openNewTab: newAgentNewTabToggle.checked,
  });
  activeAgentId = id;
  newAgentSheet.classList.add("hidden");
  renderActiveAgentView();
  promptInput.focus();
}

// =========================================================
// START / STOP AGENT
// =========================================================
async function startTask() {
  const agent = getActiveAgent();
  if (!agent) return;
  const prompt = promptInput.value.trim();
  if (!prompt) return;

  promptInput.value = "";
  autoResizeTextarea();

  pushFeedItem(agent.id, { kind: "user", text: prompt });

  agent.running = true;
  agent.state = "thinking";
  agent.badge = "Работает";
  agent.step = 0;
  agent.islandText = "Выполняю...";
  renderActiveAgentView();

  const res = await chrome.runtime.sendMessage({
    type: "START_AGENT",
    agentId: agent.id,
    agentName: agent.name,
    agentColor: agent.color,
    openNewTab: agent.openNewTab,
    prompt,
    settings: {
      apiKey: settings.apiKey,
      proxyUrl: settings.proxyUrl,
      model: getEffectiveModel(),
      useVision: settings.useVision,
      useDebugger: settings.useDebugger,
      autoMultiAgent: settings.autoMultiAgent,
      safetyGate: settings.safetyGate,
      edgeGlow: settings.edgeGlow,
      showCursor: settings.showCursor,
      maxSteps: settings.maxSteps,
    },
  });

  // Only auto-open a fresh tab on the first run of this new agent
  agent.openNewTab = false;

  if (res && !res.ok) {
    agent.running = false;
    agent.state = "idle";
    agent.badge = "Готов";
    pushFeedItem(agent.id, {
      kind: "step",
      title: "⚠️ Ошибка",
      thought: res.error || "Не удалось запустить агента",
      variant: "is-error",
    });
    renderActiveAgentView();
  }
}

async function stopActiveAgent() {
  const agent = getActiveAgent();
  if (!agent) return;
  await chrome.runtime.sendMessage({ type: "STOP_AGENT", agentId: agent.id });
  agent.running = false;
  agent.state = "idle";
  agent.badge = "Готов";
  renderActiveAgentView();
}

async function triggerDemoMotion() {
  const res = await chrome.runtime.sendMessage({ type: "RUN_DEMO_MOTION" });
  if (res && !res.ok) {
    pushFeedItem(activeAgentId, {
      kind: "step",
      title: "✨ Демо",
      thought: res.error || "Откройте любой обычный сайт, чтобы увидеть анимацию двух агентов.",
    });
  }
}

// =========================================================
// LIVE EVENTS FROM BACKGROUND WORKER
// =========================================================
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type !== "AGENT_EVENT") return;

  if (msg.event === "spawned") {
    if (!agentProfiles.has(msg.agentId)) {
      const created = createAgentProfile({
        id: msg.agentId,
        name: msg.agentName || "Nova",
        color: msg.agentColor || "#af52de",
        openNewTab: false,
      });
      created.running = true;
      created.state = "thinking";
      created.badge = "Работает";
      created.islandText = "Запуск...";
      if (msg.prompt) {
        created.feed.push({ kind: "user", text: msg.prompt });
      }
      renderAgentsBar();
    }
    return;
  }

  const agentId = msg.agentId || activeAgentId;
  const agent = agentProfiles.get(agentId);
  if (!agent) return;

  switch (msg.event) {
    case "started":
      agent.running = true;
      agent.state = "thinking";
      agent.badge = "Думает";
      agent.islandText = msg.status || "Запуск...";
      break;

    case "status":
      agent.running = true;
      agent.state = msg.state || "thinking";
      agent.badge = msg.state === "acting" ? "Действует" : "Думает";
      if (msg.step) agent.step = msg.step;
      if (msg.status) agent.islandText = msg.status;
      break;

    case "step":
      agent.running = true;
      agent.state = "acting";
      agent.badge = "Действует";
      agent.step = msg.step || agent.step;
      agent.islandText = msg.status || msg.title || "Выполняю...";
      break;

    case "done":
      agent.running = false;
      agent.state = "done";
      agent.badge = "Готово";
      pushFeedItem(agentId, {
        kind: "step",
        title: "✅ Готово",
        step: msg.step,
        thought: msg.summary,
        variant: "is-done",
      });
      break;

    case "ask_user":
      agent.running = false;
      agent.state = "idle";
      agent.badge = "Ждёт вас";
      pushFeedItem(agentId, {
        kind: "step",
        title: "💬 Вопрос",
        step: msg.step,
        thought: msg.question,
      });
      break;

    case "stopped":
      agent.running = false;
      agent.state = "idle";
      agent.badge = "Готов";
      pushFeedItem(agentId, {
        kind: "step",
        title: "⏹️ Остановлено",
        thought: msg.message || "Агент остановлен.",
      });
      break;

    case "error":
      agent.running = false;
      agent.state = "idle";
      agent.badge = "Ошибка";
      pushFeedItem(agentId, {
        kind: "step",
        title: "⚠️ Ошибка",
        thought: msg.message || "Произошла ошибка.",
        variant: "is-error",
      });
      break;
  }

  if (agentId === activeAgentId) {
    renderActiveAgentView();
  } else {
    renderAgentsBar();
  }
});

// =========================================================
// EVENT LISTENERS
// =========================================================
function autoResizeTextarea() {
  promptInput.style.height = "auto";
  promptInput.style.height = `${Math.min(120, promptInput.scrollHeight)}px`;
}

promptInput.addEventListener("input", autoResizeTextarea);

promptInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    const agent = getActiveAgent();
    if (agent && !agent.running) startTask();
  }
});

sendBtn.addEventListener("click", () => {
  const agent = getActiveAgent();
  if (agent?.running) stopActiveAgent();
  else startTask();
});

islandStopBtn.addEventListener("click", stopActiveAgent);
addAgentBtn.addEventListener("click", openNewAgentModal);
closeNewAgentBtn.addEventListener("click", () => newAgentSheet.classList.add("hidden"));
confirmNewAgentBtn.addEventListener("click", confirmCreateAgent);

newAgentNameInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    confirmCreateAgent();
  }
});

newAgentSheet.addEventListener("click", (e) => {
  if (e.target === newAgentSheet) newAgentSheet.classList.add("hidden");
});

visionToggle.addEventListener("click", async () => {
  settings.useVision = !settings.useVision;
  visionDot.classList.toggle("active", settings.useVision);
  await chrome.storage.local.set({ auraSettings: settings });
});

modelPill.addEventListener("click", openSettings);
settingsBtn.addEventListener("click", openSettings);
closeSettingsBtn.addEventListener("click", () => settingsSheet.classList.add("hidden"));
saveSettingsBtn.addEventListener("click", saveSettings);

settingsSheet.addEventListener("click", (e) => {
  if (e.target === settingsSheet) settingsSheet.classList.add("hidden");
});

toggleKeyVisBtn.addEventListener("click", () => {
  const isPass = apiKeyInput.type === "password";
  apiKeyInput.type = isPass ? "text" : "password";
  toggleKeyVisBtn.textContent = isPass ? "Скрыть" : "Показать";
});

modelSelect.addEventListener("change", () => {
  customModelGroup.classList.toggle("hidden", modelSelect.value !== "custom");
});

maxStepsRange.addEventListener("input", () => {
  maxStepsVal.textContent = maxStepsRange.value;
});

demoMotionBtn.addEventListener("click", triggerDemoMotion);
heroOrbTrigger.addEventListener("click", triggerDemoMotion);

recordBtn.addEventListener("click", async () => {
  if (!isRecordingMacro) {
    const res = await chrome.runtime.sendMessage({ type: "START_REC" });
    if (res?.ok) {
      isRecordingMacro = true;
      recordBtn.style.color = "#ff2d55";
      recordBtn.title = "Остановить и сохранить сценарий";
    } else if (res?.error) {
      pushFeedItem(activeAgentId, { kind: "step", title: "● Запись", thought: res.error });
    }
  } else {
    isRecordingMacro = false;
    recordBtn.style.color = "";
    recordBtn.title = "Записать сценарий (0 кредитов)";
    const res = await chrome.runtime.sendMessage({ type: "STOP_REC" });
    if (res?.ok) {
      pushFeedItem(activeAgentId, {
        kind: "step",
        title: "✅ Сценарий сохранён",
        thought: `Записано шагов: ${res.steps?.length || 0}. Запускайте его в настройках (⚙️) с 0 тратой кредитов.`,
        variant: "is-done",
      });
    }
  }
});

addSchedBtn.addEventListener("click", async () => {
  const prompt = schedPromptInput.value.trim();
  const periodMinutes = Number(schedMinInput.value) || 60;
  if (!prompt) return;
  await chrome.runtime.sendMessage({ type: "CREATE_SCHEDULE", prompt, periodMinutes });
  schedPromptInput.value = "";
  refreshMacrosAndSchedules();
});

clearChatBtn.addEventListener("click", () => {
  const agent = getActiveAgent();
  if (!agent) return;
  agent.feed = [];
  if (!agent.running) {
    agent.state = "idle";
    agent.badge = "Готов";
  }
  renderActiveAgentView();
});

// Init
loadSettings();
renderActiveAgentView();

// =========================================================
// STELLA CLOUD ACCOUNT & PROFILE SYNC
// =========================================================
const CLOUD_BASE = "https://stella-openrouter-proxy.stella-ai-a1x10.workers.dev";
const accountSignedOut = document.getElementById("accountSignedOut");
const accountSignedIn = document.getElementById("accountSignedIn");
const authEmailInput = document.getElementById("authEmailInput");
const authPassInput = document.getElementById("authPassInput");
const authCountrySelect = document.getElementById("authCountrySelect");
const extLoginBtn = document.getElementById("extLoginBtn");
const extRegBtn = document.getElementById("extRegBtn");
const extLogoutBtn = document.getElementById("extLogoutBtn");
const authMsg = document.getElementById("authMsg");
const authUserLabel = document.getElementById("authUserLabel");
const authRegionLabel = document.getElementById("authRegionLabel");

const authGateOverlay = document.getElementById("authGateOverlay");
const gateTitle = document.getElementById("gateTitle");
const gateSub = document.getElementById("gateSub");
const gateChoiceView = document.getElementById("gateChoiceView");
const gateLoginView = document.getElementById("gateLoginView");
const gateRegView = document.getElementById("gateRegView");
const gateStatusMsg = document.getElementById("gateStatusMsg");

function showGateStep(step) {
  gateStatusMsg.textContent = "";
  gateChoiceView.classList.toggle("hidden", step !== "choice");
  gateLoginView.classList.toggle("hidden", step !== "login");
  gateRegView.classList.toggle("hidden", step !== "register");
  if (step === "choice") {
    gateTitle.textContent = "Пройдите регистрацию для начала";
    gateSub.textContent = "Создайте профиль или войдите, чтобы использовать агента Стеллу.";
  } else if (step === "login") {
    gateTitle.textContent = "Вход в Стеллу";
    gateSub.textContent = "Введите Email и пароль от вашего профиля.";
  } else if (step === "register") {
    gateTitle.textContent = "Регистрация профиля";
    gateSub.textContent = "Укажите страну для подбора нужных сервисов и MCP.";
  }
}

function renderAuthUI(account) {
  if (account?.token && account?.user) {
    authGateOverlay?.classList.add("hidden");
    accountSignedOut.classList.add("hidden");
    accountSignedIn.classList.remove("hidden");
    authUserLabel.textContent = `${account.user.name} (${account.user.email})`;
    const regionMap = { KZ: "🇰🇿 Казахстан", RU: "🇷🇺 Россия", OTHER: "🌍 Global" };
    authRegionLabel.textContent = `${regionMap[account.user.country] || account.user.country} • ${(account.user.presets || []).slice(0, 3).join(", ")}`;
  } else {
    showGateStep("choice");
    authGateOverlay?.classList.remove("hidden");
    accountSignedOut.classList.remove("hidden");
    accountSignedIn.classList.add("hidden");
  }
}

document.getElementById("gateChooseLoginBtn")?.addEventListener("click", () => showGateStep("login"));
document.getElementById("gateChooseRegBtn")?.addEventListener("click", () => showGateStep("register"));
document.querySelectorAll("[data-gate-back]").forEach((b) => b.addEventListener("click", () => showGateStep("choice")));

document.getElementById("gateGoogleBtn")?.addEventListener("click", () => {
  chrome.tabs.create({ url: "https://a1x10.github.io/stella-ai/account.html" });
});

document.getElementById("gateQuickBtn")?.addEventListener("click", async () => {
  gateStatusMsg.textContent = "Создаю профиль в 1 клик...";
  try {
    const res = await fetch(`${CLOUD_BASE}/api/auth/quick`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider: "quick", name: "Пользователь Стеллы", country: "RU" }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      gateStatusMsg.textContent = data.error || "Ошибка входа";
      return;
    }
    const account = { token: data.token, user: data.user };
    await chrome.storage.local.set({ stellaAccount: account });
    renderAuthUI(account);
  } catch (e) {
    gateStatusMsg.textContent = "Ошибка сети: " + String(e.message || e);
  }
});

document.getElementById("gateLoginSubmitBtn")?.addEventListener("click", async () => {
  const email = document.getElementById("gateLoginEmail").value.trim();
  const password = document.getElementById("gateLoginPass").value;
  gateStatusMsg.textContent = "Выполняю вход...";
  try {
    const res = await fetch(`${CLOUD_BASE}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      gateStatusMsg.textContent = data.error || "Неверный email или пароль";
      return;
    }
    const account = { token: data.token, user: data.user };
    await chrome.storage.local.set({ stellaAccount: account });
    renderAuthUI(account);
  } catch (e) {
    gateStatusMsg.textContent = "Ошибка сети: " + String(e.message || e);
  }
});

document.getElementById("gateRegSubmitBtn")?.addEventListener("click", async () => {
  const name = document.getElementById("gateRegName").value.trim();
  const email = document.getElementById("gateRegEmail").value.trim();
  const password = document.getElementById("gateRegPass").value;
  const country = document.getElementById("gateRegCountry").value;
  const consent = document.getElementById("gateRegConsent").checked;
  gateStatusMsg.textContent = "Создаю профиль...";
  try {
    const res = await fetch(`${CLOUD_BASE}/api/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, email, password, country, consent }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      gateStatusMsg.textContent = data.error || "Ошибка регистрации";
      return;
    }
    const account = { token: data.token, user: data.user };
    await chrome.storage.local.set({ stellaAccount: account });
    renderAuthUI(account);
  } catch (e) {
    gateStatusMsg.textContent = "Ошибка сети: " + String(e.message || e);
  }
});

chrome.storage.local.get("stellaAccount", (res) => renderAuthUI(res?.stellaAccount));

async function doExtAuth(mode) {
  const email = authEmailInput.value.trim();
  const password = authPassInput.value;
  const country = authCountrySelect.value;
  authMsg.textContent = "Подключаюсь к Stella Cloud...";
  try {
    const res = await fetch(`${CLOUD_BASE}/api/auth/${mode}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, country, consent: true }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      authMsg.textContent = data.error || "Ошибка авторизации";
      return;
    }
    const account = { token: data.token, user: data.user };
    await chrome.storage.local.set({ stellaAccount: account });
    authMsg.textContent = "";
    renderAuthUI(account);
  } catch (e) {
    authMsg.textContent = "Нет связи с облаком: " + String(e.message || e);
  }
}

extLoginBtn?.addEventListener("click", () => doExtAuth("login"));
extRegBtn?.addEventListener("click", () => doExtAuth("register"));
extLogoutBtn?.addEventListener("click", async () => {
  await chrome.storage.local.remove("stellaAccount");
  renderAuthUI(null);
});

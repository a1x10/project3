// Multi-Provider AI Engine Manager
const PROVIDERS_KEY = "vibing_ai_providers";
const CONFIG_VERSION = 2;

export const PRESET_PROVIDERS = [
  {
    id: "freellmapi",
    name: "FreeLLMAPI (бесплатные модели)",
    shortName: "FreeLLMAPI",
    type: "openai",
    // Proxied by Vite (/llm -> http://localhost:3001, see vite.config.js) so the browser never hits CORS.
    url: "/llm/v1/chat/completions",
    defaultModel: "auto:smart",
    models: ["auto:smart", "auto", "auto:fast", "qwen/qwen3.8-max:free", "glm-5.3:free", "deepseek/deepseek-v4-flash-0731free:free", "nvidia/nemotron-3-ultra-550b-a55b:free"],
    requiresKey: false,
    optionalKey: true,
    canListModels: true,
    placeholder: "необязательно — установщик сохранил ключ, его подставит сервер",
    instructions:
      "FreeLLMAPI — самохостящийся роутер: один ключ, сотни бесплатных моделей, автоматический переход на другую модель при лимитах.\n" +
      "Если вы ставили всё через install.sh / install.cmd, роутер уже установлен, запускается вместе со студией, а ключ подставляется сервером — поле ключа можно оставить пустым.\n" +
      "1. Установите роутер: curl -fsSL https://freellmapi.co/install.sh | bash (нужен Docker). Он запустится на http://localhost:3001.\n" +
      "2. В дашборде роутера на странице Keys добавьте ключи провайдеров (Groq, Gemini, OpenRouter и др.).\n" +
      "3. Скопируйте единый ключ freellmapi-… из шапки страницы Keys и вставьте сюда.\n" +
      "Модель auto:smart — роутер выберет самую сильную доступную модель, auto:fast — самую быструю. Кнопка «Загрузить модели» покажет весь каталог.\n" +
      "Роутер на другом адресе? Запускайте приложение с FREELLMAPI_URL=http://host:port npm run dev или укажите полный URL эндпоинта ниже.",
    docUrl: "https://freellmapi.co/ru/models",
  },
  {
    id: "local",
    canListModels: true,
    name: "Локальный GPT-OSS 20B",
    type: "local",
    url: "http://localhost:8080/v1/chat/completions",
    defaultModel: "gpt-oss-20b",
    models: ["gpt-oss-20b", "Qwen3.6-14B"],
    requiresKey: false,
    placeholder: "Ключ не требуется (Локальный GPU/RAM инференс)",
    instructions: "Модель запущена локально на вашем ПК (FastAPI + llama-cpp CUDA). Никаких ключей и интернета не требуется.",
  },
  {
    id: "openai",
    canListModels: true,
    name: "OpenAI (ChatGPT)",
    type: "openai",
    url: "https://api.openai.com/v1/chat/completions",
    defaultModel: "gpt-5-mini",
    models: ["gpt-5-mini", "gpt-5", "gpt-4.1", "gpt-4o-mini"],
    requiresKey: true,
    placeholder: "sk-proj-...",
    instructions: "1. Перейдите на platform.openai.com -> API keys.\n2. Создайте новый секретный ключ (Create new secret key).\n3. Вставьте его сюда.",
    docUrl: "https://platform.openai.com/api-keys",
  },
  {
    id: "anthropic",
    name: "Anthropic (Claude)",
    type: "anthropic",
    url: "https://api.anthropic.com/v1/messages",
    defaultModel: "claude-sonnet-5-5",
    models: ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"],
    requiresKey: true,
    placeholder: "sk-ant-api03-...",
    instructions: "1. Откройте console.anthropic.com -> API Keys.\n2. Нажмите Create Key и скопируйте значение.\n3. Вставьте ключ для доступа к моделям Claude (по умолчанию Claude Sonnet 5.5).",
    docUrl: "https://console.anthropic.com/settings/keys",
  },
  {
    id: "gemini",
    canListModels: true,
    name: "Google (Gemini)",
    type: "gemini",
    url: "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    defaultModel: "gemini-2.5-flash",
    models: ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash", "gemini-1.5-flash"],
    requiresKey: true,
    placeholder: "AIzaSy...",
    instructions: "1. Зайдите на aistudio.google.com -> Get API key.\n2. Создайте бесплатный ключ в Google AI Studio.\n3. Вставьте ключ сюда. Рекомендуемая быстрая модель: gemini-2.5-flash.",
    docUrl: "https://aistudio.google.com/app/apikey",
  },
  {
    id: "qwen",
    canListModels: true,
    name: "Qwen (DashScope / Alibaba)",
    type: "qwen",
    url: "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
    defaultModel: "qwen-max",
    models: ["qwen-max", "qwen-plus", "qwen-turbo", "qwen-2.5-coder-32b"],
    requiresKey: true,
    placeholder: "sk-...",
    instructions: "1. Войдите в консоль Alibaba Cloud DashScope (bailian.console.aliyun.com).\n2. Создайте API Key в разделе API Keys Management.\n3. Поддерживает сильнейшие кодинг-модели Qwen Coder.",
    docUrl: "https://dashscope.console.aliyun.com/",
  },
  {
    id: "kimi",
    canListModels: true,
    name: "Kimi (Moonshot AI)",
    type: "kimi",
    url: "https://api.moonshot.cn/v1/chat/completions",
    defaultModel: "moonshot-v1-32k",
    models: ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
    requiresKey: true,
    placeholder: "sk-...",
    instructions: "1. Зайдите на platform.moonshot.cn -> API Key.\n2. Сгенерируйте токен доступа к длинноконтекстной модели Kimi.\n3. Вставьте в поле ввода.",
    docUrl: "https://platform.moonshot.cn/",
  },
  {
    id: "custom",
    canListModels: true,
    name: "Кастомный API (OpenAI-compatible / Ollama / OpenRouter)",
    type: "custom",
    url: "http://localhost:11434/v1/chat/completions",
    defaultModel: "custom-model",
    models: ["custom-model", "deepseek-r1", "llama-3.3-70b"],
    requiresKey: false,
    placeholder: "Bearer sk-... или оставьте пустым для локальной Ollama",
    instructions: "Любой провайдер со стандартным OpenAI REST API: OpenRouter, Ollama, Groq, Together AI, vLLM или персональный сервер.",
  },
];

function defaultEntry(preset) {
  return { apiKey: "", model: preset.defaultModel, customUrl: "" };
}

export function defaultProviderConfig() {
  return {
    version: CONFIG_VERSION,
    activeProviderId: "freellmapi",
    providers: Object.fromEntries(PRESET_PROVIDERS.map((p) => [p.id, defaultEntry(p)])),
  };
}

/** Load the saved config, adding new presets and migrating old versions. */
export function getProviderConfig() {
  let cfg;
  try {
    const raw = localStorage.getItem(PROVIDERS_KEY);
    cfg = raw ? JSON.parse(raw) : null;
  } catch {
    cfg = null;
  }
  if (!cfg || typeof cfg !== "object") return defaultProviderConfig();
  cfg.providers = cfg.providers && typeof cfg.providers === "object" ? cfg.providers : {};
  for (const p of PRESET_PROVIDERS) if (!cfg.providers[p.id]) cfg.providers[p.id] = defaultEntry(p);
  if ((cfg.version || 1) < CONFIG_VERSION) {
    // v1 defaulted to the bundled local server; switch untouched configs to FreeLLMAPI.
    const local = cfg.providers.local || {};
    if (!cfg.activeProviderId || (cfg.activeProviderId === "local" && !local.customUrl)) cfg.activeProviderId = "freellmapi";
    // retired model ids from v1 presets
    const a = cfg.providers.anthropic;
    if (a && /^claude-3/.test(a.model || "")) a.model = "claude-sonnet-5-5";
    cfg.version = CONFIG_VERSION;
    saveProviderConfig(cfg);
  }
  if (!PRESET_PROVIDERS.some((p) => p.id === cfg.activeProviderId)) cfg.activeProviderId = "freellmapi";
  return cfg;
}

export function getPreset(id) {
  return PRESET_PROVIDERS.find((p) => p.id === id) || PRESET_PROVIDERS[0];
}

export function saveProviderConfig(cfg) {
  try {
    localStorage.setItem(PROVIDERS_KEY, JSON.stringify(cfg));
  } catch (e) {
    console.error("Save provider config error:", e);
  }
}

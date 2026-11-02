// Multi-Provider AI Engine Manager
const PROVIDERS_KEY = "vibing_ai_providers";

export const PRESET_PROVIDERS = [
  {
    id: "local",
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
    name: "OpenAI (ChatGPT)",
    type: "openai",
    url: "https://api.openai.com/v1/chat/completions",
    defaultModel: "gpt-4o",
    models: ["gpt-4o", "gpt-4o-mini", "o1-preview", "o3-mini"],
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
    defaultModel: "claude-3-7-sonnet-20250219",
    models: ["claude-3-7-sonnet-20250219", "claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"],
    requiresKey: true,
    placeholder: "sk-ant-api03-...",
    instructions: "1. Откройте console.anthropic.com -> API Keys.\n2. Нажмите Create Key и скопируйте значение.\n3. Вставьте ключ для доступа к моделям Claude 3.7 Sonnet.",
    docUrl: "https://console.anthropic.com/settings/keys",
  },
  {
    id: "gemini",
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

export function getProviderConfig() {
  try {
    const raw = localStorage.getItem(PROVIDERS_KEY);
    if (!raw) {
      return {
        activeProviderId: "local",
        providers: {
          local: { apiKey: "", model: "gpt-oss-20b", customUrl: "" },
          openai: { apiKey: "", model: "gpt-4o", customUrl: "" },
          anthropic: { apiKey: "", model: "claude-3-7-sonnet-20250219", customUrl: "" },
          gemini: { apiKey: "", model: "gemini-2.5-flash", customUrl: "" },
          qwen: { apiKey: "", model: "qwen-max", customUrl: "" },
          kimi: { apiKey: "", model: "moonshot-v1-32k", customUrl: "" },
          custom: { apiKey: "", model: "custom-model", customUrl: "http://localhost:11434/v1/chat/completions" },
        },
      };
    }
    return JSON.parse(raw);
  } catch {
    return {
      activeProviderId: "local",
      providers: {},
    };
  }
}

export function saveProviderConfig(cfg) {
  try {
    localStorage.setItem(PROVIDERS_KEY, JSON.stringify(cfg));
  } catch (e) {
    console.error("Save provider config error:", e);
  }
}

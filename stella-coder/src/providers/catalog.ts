import type { ModelInfo } from './types.js';

/**
 * Built-in model catalog. Prices are USD per 1M tokens (first-party list prices at time of
 * writing — override per model in settings.providers.<name>.models when they change).
 */
const A = (id: string, name: string, ctx: number, inP: number, outP: number, extra: Partial<ModelInfo> = {}): ModelInfo => ({
  id,
  provider: 'anthropic',
  name,
  contextWindow: ctx,
  maxOutput: 128_000,
  inputPrice: inP,
  outputPrice: outP,
  toolCalling: true,
  streaming: true,
  supportsEffort: true,
  ...extra,
});

export const BUILTIN_MODELS: ModelInfo[] = [
  A('claude-opus-5-5', 'Claude Opus 5.5', 1_000_000, 4, 20, { cacheReadPrice: 0.2, fallbacks: true }),
  A('claude-sonnet-5-5', 'Claude Sonnet 5.5', 1_000_000, 2, 10, { cacheReadPrice: 0.2, fallbacks: true }),
  A('claude-haiku-5-5', 'Claude Haiku 5.5', 1_000_000, 0.1, 0.5),
  A('claude-fable-5-1', 'Claude Fable 5.1', 1_000_000, 10, 50, { cacheReadPrice: 0.25, fallbacks: true }),
  A('claude-opus-5', 'Claude Opus 5', 1_000_000, 5, 25, { fallbacks: true }),
  A('claude-sonnet-4-6', 'Claude Sonnet 4.6', 1_000_000, 3, 15, { explicitAdaptive: true, maxOutput: 64_000 }),
  A('claude-haiku-4-5', 'Claude Haiku 4.5', 200_000, 1, 5, { supportsEffort: false, maxOutput: 64_000 }),

  // FreeLLMAPI router (self-hosted, OpenAI-compatible): virtual models pick a free upstream per request.
  { id: 'auto:smart', provider: 'freellmapi', name: 'FreeLLMAPI auto:smart', contextWindow: 128_000, maxOutput: 16_384, inputPrice: 0, outputPrice: 0, toolCalling: true, streaming: true, notes: 'Router picks the strongest available free model; limits depend on the routed model.' },
  { id: 'auto', provider: 'freellmapi', name: 'FreeLLMAPI auto', contextWindow: 128_000, maxOutput: 16_384, inputPrice: 0, outputPrice: 0, toolCalling: true, streaming: true },
  { id: 'auto:fast', provider: 'freellmapi', name: 'FreeLLMAPI auto:fast', contextWindow: 128_000, maxOutput: 16_384, inputPrice: 0, outputPrice: 0, toolCalling: true, streaming: true },

  // Stella Cloud (your own server: accounts via Telegram, owner's prompt and limits, FreeLLMAPI behind it).
  { id: 'auto', provider: 'cloud', name: 'Stella Cloud auto', contextWindow: 128_000, maxOutput: 16_384, inputPrice: 0, outputPrice: 0, toolCalling: true, streaming: true, notes: 'Routed by the Stella Cloud server; sign in with: stella-coder login <url>' },
  { id: 'auto:smart', provider: 'cloud', name: 'Stella Cloud auto:smart', contextWindow: 128_000, maxOutput: 16_384, inputPrice: 0, outputPrice: 0, toolCalling: true, streaming: true },
  { id: 'auto:fast', provider: 'cloud', name: 'Stella Cloud auto:fast', contextWindow: 128_000, maxOutput: 16_384, inputPrice: 0, outputPrice: 0, toolCalling: true, streaming: true },

  { id: 'gpt-5', provider: 'openai', name: 'GPT-5', contextWindow: 400_000, maxOutput: 128_000, inputPrice: 1.25, outputPrice: 10, toolCalling: true, streaming: true },
  { id: 'gpt-5-mini', provider: 'openai', name: 'GPT-5 mini', contextWindow: 400_000, maxOutput: 128_000, inputPrice: 0.25, outputPrice: 2, toolCalling: true, streaming: true },
  { id: 'gpt-4.1', provider: 'openai', name: 'GPT-4.1', contextWindow: 1_000_000, maxOutput: 32_768, inputPrice: 2, outputPrice: 8, toolCalling: true, streaming: true },
  { id: 'gpt-4o-mini', provider: 'openai', name: 'GPT-4o mini', contextWindow: 128_000, maxOutput: 16_384, inputPrice: 0.15, outputPrice: 0.6, toolCalling: true, streaming: true },

  { id: 'gemini-2.5-pro', provider: 'gemini', name: 'Gemini 2.5 Pro', contextWindow: 1_048_576, maxOutput: 65_536, inputPrice: 1.25, outputPrice: 10, toolCalling: true, streaming: true },
  { id: 'gemini-2.5-flash', provider: 'gemini', name: 'Gemini 2.5 Flash', contextWindow: 1_048_576, maxOutput: 65_536, inputPrice: 0.3, outputPrice: 2.5, toolCalling: true, streaming: true },

  { id: 'llama-3.3-70b-versatile', provider: 'groq', name: 'Llama 3.3 70B (Groq)', contextWindow: 131_072, maxOutput: 32_768, inputPrice: 0.59, outputPrice: 0.79, toolCalling: true, streaming: true },
  { id: 'openai/gpt-oss-120b', provider: 'groq', name: 'GPT-OSS 120B (Groq)', contextWindow: 131_072, maxOutput: 32_768, inputPrice: 0.15, outputPrice: 0.75, toolCalling: true, streaming: true },
];

export const DEFAULT_ALIASES: Record<string, string> = {
  cloud: 'cloud:auto',
  free: 'freellmapi:auto:smart',
  'free-fast': 'freellmapi:auto:fast',
  opus: 'anthropic:claude-opus-5-5',
  sonnet: 'anthropic:claude-sonnet-5-5',
  haiku: 'anthropic:claude-haiku-5-5',
  fable: 'anthropic:claude-fable-5-1',
  gpt: 'openai:gpt-5',
  'gpt-mini': 'openai:gpt-5-mini',
  gemini: 'gemini:gemini-2.5-pro',
  flash: 'gemini:gemini-2.5-flash',
  groq: 'groq:llama-3.3-70b-versatile',
};

export const DEFAULT_MODEL = 'freellmapi:auto:smart';

/** Built-in provider endpoints; all OpenAI-compatible except anthropic and gemini. */
export const BUILTIN_PROVIDERS: Record<string, { type: 'anthropic' | 'openai' | 'gemini'; baseUrl: string; apiKeyEnv?: string }> = {
  anthropic: { type: 'anthropic', baseUrl: 'https://api.anthropic.com', apiKeyEnv: 'ANTHROPIC_API_KEY' },
  openai: { type: 'openai', baseUrl: 'https://api.openai.com/v1', apiKeyEnv: 'OPENAI_API_KEY' },
  openrouter: { type: 'openai', baseUrl: 'https://openrouter.ai/api/v1', apiKeyEnv: 'OPENROUTER_API_KEY' },
  groq: { type: 'openai', baseUrl: 'https://api.groq.com/openai/v1', apiKeyEnv: 'GROQ_API_KEY' },
  gemini: { type: 'gemini', baseUrl: 'https://generativelanguage.googleapis.com', apiKeyEnv: 'GEMINI_API_KEY' },
  ollama: { type: 'openai', baseUrl: 'http://localhost:11434/v1' },
  cloud: { type: 'openai', baseUrl: '', apiKeyEnv: 'STELLA_CLOUD_API_KEY' },
  freellmapi: { type: 'openai', baseUrl: process.env.FREELLMAPI_BASE_URL ?? 'http://localhost:3001/v1', apiKeyEnv: 'FREELLMAPI_API_KEY' },
};

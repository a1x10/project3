import type { Settings } from '../config/settings.js';
import { getCredential } from '../config/settings.js';
import { AnthropicProvider } from './anthropic.js';
import { BUILTIN_MODELS, BUILTIN_PROVIDERS, DEFAULT_ALIASES, DEFAULT_MODEL } from './catalog.js';
import { GeminiProvider } from './gemini.js';
import { OpenAICompatProvider } from './openai.js';
import type { LLMProvider, ModelInfo, ProviderType } from './types.js';

export interface ProviderDef {
  name: string;
  type: ProviderType;
  baseUrl: string;
  apiKeyEnv?: string;
  apiKey?: string;
  headers?: Record<string, string>;
}

/**
 * Resolves model references ("opus", "anthropic:claude-opus-5-5", "ollama:qwen2.5-coder",
 * "openrouter:anthropic/claude-sonnet-4.5") to a ModelInfo and builds provider adapters.
 */
export class ModelRegistry {
  private providers = new Map<string, ProviderDef>();
  private models: ModelInfo[] = [];
  private aliases: Record<string, string>;
  private instances = new Map<string, LLMProvider>();

  constructor(private readonly settings: Settings) {
    for (const [name, p] of Object.entries(BUILTIN_PROVIDERS)) this.providers.set(name, { name, ...p });
    if (process.env.FREELLMAPI_BASE_URL) this.providers.get('freellmapi')!.baseUrl = process.env.FREELLMAPI_BASE_URL;
    for (const [name, p] of Object.entries(settings.providers ?? {})) {
      const base = this.providers.get(name);
      this.providers.set(name, {
        name,
        type: p.type,
        baseUrl: p.baseUrl ?? base?.baseUrl ?? '',
        apiKeyEnv: p.apiKeyEnv ?? base?.apiKeyEnv,
        apiKey: p.apiKey,
        headers: p.headers,
      });
    }
    this.models = [...BUILTIN_MODELS];
    for (const [name, p] of Object.entries(settings.providers ?? {})) {
      for (const m of p.models ?? []) {
        const existing = this.models.findIndex((x) => x.provider === name && x.id === m.id);
        const merged: ModelInfo = {
          ...(existing >= 0 ? this.models[existing]! : genericModel(name, m.id)),
          ...stripUndef(m),
          provider: name,
        } as ModelInfo;
        if (existing >= 0) this.models[existing] = merged;
        else this.models.push(merged);
      }
    }
    this.aliases = { ...DEFAULT_ALIASES, ...(settings.modelAliases ?? {}) };
  }

  listModels(): ModelInfo[] {
    return this.models;
  }
  listProviders(): ProviderDef[] {
    return [...this.providers.values()];
  }
  get aliasMap(): Record<string, string> {
    return this.aliases;
  }

  defaultModelRef(): string {
    return this.settings.model ?? process.env.STELLA_MODEL ?? DEFAULT_MODEL;
  }

  resolve(ref?: string): ModelInfo {
    let r = (ref ?? this.defaultModelRef()).trim();
    for (let i = 0; i < 5 && this.aliases[r]; i++) r = this.aliases[r]!;
    let provider: string | undefined;
    let id = r;
    const colon = r.indexOf(':');
    if (colon > 0 && this.providers.has(r.slice(0, colon))) {
      provider = r.slice(0, colon);
      id = r.slice(colon + 1);
    }
    const found = this.models.find((m) => m.id === id && (!provider || m.provider === provider));
    if (found) return found;
    if (!provider) {
      if (/^claude-/.test(id)) provider = 'anthropic';
      else if (/^gemini-/.test(id)) provider = 'gemini';
      else if (/^(gpt-|o\d)/.test(id)) provider = 'openai';
      else throw new Error(`Unknown model "${r}". Use provider:model (providers: ${[...this.providers.keys()].join(', ')}).`);
    }
    return genericModel(provider, id);
  }

  async apiKeyFor(name: string): Promise<string | undefined> {
    const def = this.providers.get(name);
    if (!def) return undefined;
    if (def.apiKey) return def.apiKey;
    if (def.apiKeyEnv && process.env[def.apiKeyEnv]) return process.env[def.apiKeyEnv];
    return getCredential(`${name}.apiKey`);
  }

  async provider(name: string): Promise<LLMProvider> {
    const cached = this.instances.get(name);
    if (cached) return cached;
    const def = this.providers.get(name);
    if (!def) throw new Error(`Unknown provider "${name}"`);
    const apiKey = await this.apiKeyFor(name);
    let p: LLMProvider;
    switch (def.type) {
      case 'anthropic': {
        const authToken = !apiKey ? process.env.ANTHROPIC_AUTH_TOKEN : undefined;
        if (!apiKey && !authToken) throw new Error(`No API key for provider "${name}". Set ${def.apiKeyEnv ?? 'an API key'} or run: stella auth set ${name}`);
        p = new AnthropicProvider({ name, apiKey, authToken, baseUrl: process.env.ANTHROPIC_BASE_URL ?? def.baseUrl, headers: def.headers, fallbacks: this.settings.anthropicFallbacks });
        break;
      }
      case 'gemini':
        if (!apiKey) throw new Error(`No API key for provider "${name}". Set ${def.apiKeyEnv ?? 'GEMINI_API_KEY'} or run: stella auth set ${name}`);
        p = new GeminiProvider({ name, baseUrl: def.baseUrl, apiKey, headers: def.headers });
        break;
      default:
        if (!apiKey && !/localhost|127\.0\.0\.1/.test(def.baseUrl)) throw new Error(`No API key for provider "${name}". Set ${def.apiKeyEnv ?? 'an API key'} or run: stella auth set ${name}`);
        p = new OpenAICompatProvider({ name, baseUrl: def.baseUrl, apiKey, headers: def.headers });
    }
    this.instances.set(name, p);
    return p;
  }
}

function genericModel(provider: string, id: string): ModelInfo {
  return {
    id,
    provider,
    name: id,
    contextWindow: provider === 'ollama' ? 32_768 : 128_000,
    maxOutput: provider === 'ollama' ? 8192 : 16_384,
    inputPrice: 0,
    outputPrice: 0,
    toolCalling: true,
    streaming: true,
    notes: 'Not in built-in catalog: limits/prices are defaults; override in settings.',
  };
}

function stripUndef<T extends object>(o: T): Partial<T> {
  return Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined)) as Partial<T>;
}

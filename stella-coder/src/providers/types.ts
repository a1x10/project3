import type { ChatMessage, StopReason, ToolSpec, Usage } from '../types.js';

export type ProviderType = 'anthropic' | 'openai' | 'gemini';
export type Effort = 'low' | 'medium' | 'high' | 'xhigh' | 'max';

export interface ModelInfo {
  /** Wire id sent to the provider API. */
  id: string;
  /** Provider config key (anthropic, openai, openrouter, groq, gemini, ollama, or custom). */
  provider: string;
  name: string;
  contextWindow: number;
  maxOutput: number;
  /** USD per 1M tokens. */
  inputPrice: number;
  outputPrice: number;
  cacheReadPrice?: number;
  toolCalling: boolean;
  streaming: boolean;
  supportsEffort?: boolean;
  /** Anthropic: whether `thinking` must be set explicitly to adaptive. */
  explicitAdaptive?: boolean;
  /** Anthropic: model accepts server-side refusal fallbacks. */
  fallbacks?: boolean;
  notes?: string;
}

export interface StreamRequest {
  model: ModelInfo;
  system: string;
  messages: ChatMessage[];
  tools: ToolSpec[];
  maxTokens: number;
  effort?: Effort;
  signal?: AbortSignal;
}

export type ProviderEvent =
  | { type: 'text'; text: string }
  | { type: 'thinking' }
  | { type: 'tool_start'; id: string; name: string }
  | { type: 'tool_input_delta'; id: string; delta: string }
  | { type: 'done'; message: ChatMessage; usage: Usage; stopReason: StopReason; servedModel?: string };

export interface LLMProvider {
  readonly name: string;
  readonly type: ProviderType;
  stream(req: StreamRequest): AsyncGenerator<ProviderEvent>;
}

export type ProviderErrorKind = 'auth' | 'rate_limit' | 'overloaded' | 'context_length' | 'bad_request' | 'network' | 'server' | 'invalid_output' | 'not_found' | 'unknown';

export class ProviderError extends Error {
  constructor(
    message: string,
    readonly kind: ProviderErrorKind,
    readonly status?: number,
    readonly retryAfterMs?: number,
  ) {
    super(message);
    this.name = 'ProviderError';
  }
  get retryable(): boolean {
    return ['rate_limit', 'overloaded', 'network', 'server', 'invalid_output'].includes(this.kind);
  }
}

export function classifyStatus(status: number, body: string): ProviderErrorKind {
  if (status === 401 || status === 403) return 'auth';
  if (status === 404) return 'not_found';
  if (status === 429) return 'rate_limit';
  if (status === 529 || status === 503) return 'overloaded';
  if (status >= 500) return 'server';
  if (/context|too long|maximum.*tokens|prompt is too long|token limit/i.test(body)) return 'context_length';
  return 'bad_request';
}

export function parseRetryAfter(h: string | null | undefined): number | undefined {
  if (!h) return undefined;
  const s = Number(h);
  if (!Number.isNaN(s)) return s * 1000;
  const d = Date.parse(h);
  return Number.isNaN(d) ? undefined : Math.max(0, d - Date.now());
}

export function costUsd(model: ModelInfo, u: Usage): number {
  const read = u.cacheReadTokens ?? 0;
  const write = u.cacheWriteTokens ?? 0;
  const cacheReadPrice = model.cacheReadPrice ?? model.inputPrice * 0.1;
  return (u.inputTokens * model.inputPrice + write * model.inputPrice * 1.25 + read * cacheReadPrice + u.outputTokens * model.outputPrice) / 1e6;
}

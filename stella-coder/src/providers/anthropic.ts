import Anthropic from '@anthropic-ai/sdk';
import type { ChatMessage, ContentBlock, StopReason, ToolUseBlock, Usage } from '../types.js';
import { ProviderError, classifyStatus, parseRetryAfter, type LLMProvider, type ProviderEvent, type StreamRequest } from './types.js';

export interface AnthropicOptions {
  name: string;
  apiKey?: string;
  authToken?: string;
  baseUrl?: string;
  headers?: Record<string, string>;
  /** Server-side refusal fallbacks (`fallbacks: "default"`) on models that support them. */
  fallbacks?: boolean;
}

const FALLBACK_BETA = 'server-side-fallback-2026-07-01';

/**
 * Anthropic adapter built on the official SDK (streaming Messages API).
 * - Assistant turns are replayed from `raw` unchanged (thinking blocks keep their signatures).
 * - Tools use eager input streaming; inputs are validated by the tool engine before execution.
 * - Prompt caching via top-level automatic cache_control.
 */
export class AnthropicProvider implements LLMProvider {
  readonly type = 'anthropic' as const;
  readonly name: string;
  private client: Anthropic;
  private fallbacks: boolean;

  constructor(opts: AnthropicOptions) {
    this.name = opts.name;
    this.fallbacks = opts.fallbacks ?? true;
    this.client = new Anthropic({
      apiKey: opts.apiKey ?? null,
      authToken: opts.authToken ?? null,
      baseURL: opts.baseUrl,
      defaultHeaders: opts.headers,
      maxRetries: 0, // retries are handled by STELLA's retry layer so the UI can show them
    });
  }

  toWire(messages: ChatMessage[]): Anthropic.MessageParam[] {
    return messages.map((m) => {
      if (m.role === 'assistant' && m.raw?.provider === 'anthropic' && m.raw.content.length) {
        return { role: 'assistant', content: m.raw.content as Anthropic.ContentBlockParam[] };
      }
      return { role: m.role, content: m.content.map(blockToWire) };
    });
  }

  async *stream(req: StreamRequest): AsyncGenerator<ProviderEvent> {
    const tools = req.tools.map((t) => ({
      name: t.name,
      description: t.description,
      input_schema: t.inputSchema as Anthropic.Tool.InputSchema,
      eager_input_streaming: true,
    }));
    const params: Record<string, unknown> = {
      model: req.model.id,
      max_tokens: Math.min(req.maxTokens, req.model.maxOutput),
      system: req.system,
      messages: this.toWire(req.messages),
      cache_control: { type: 'ephemeral' },
    };
    if (tools.length) params.tools = tools;
    if (req.model.supportsEffort && req.effort) params.output_config = { effort: req.effort };
    if (req.model.explicitAdaptive) params.thinking = { type: 'adaptive' };

    const useFallbacks = this.fallbacks && !!req.model.fallbacks;
    let stream: AsyncIterable<any> & { finalMessage(): Promise<any> };
    try {
      if (useFallbacks) {
        stream = this.client.beta.messages.stream({ ...(params as any), betas: [FALLBACK_BETA], fallbacks: 'default' }, { signal: req.signal }) as any;
      } else {
        stream = this.client.messages.stream(params as any, { signal: req.signal }) as any;
      }
    } catch (e) {
      throw mapError(e);
    }

    const toolIds = new Map<number, string>();
    let final: any;
    try {
      for await (const ev of stream) {
        if (ev.type === 'content_block_start') {
          const b = ev.content_block;
          if (b.type === 'tool_use') {
            toolIds.set(ev.index, b.id);
            yield { type: 'tool_start', id: b.id, name: b.name };
          } else if (b.type === 'thinking' || b.type === 'redacted_thinking') {
            yield { type: 'thinking' };
          }
        } else if (ev.type === 'content_block_delta') {
          if (ev.delta.type === 'text_delta') yield { type: 'text', text: ev.delta.text };
          else if (ev.delta.type === 'input_json_delta') {
            const id = toolIds.get(ev.index);
            if (id) yield { type: 'tool_input_delta', id, delta: ev.delta.partial_json };
          }
        }
      }
      final = await stream.finalMessage();
    } catch (e) {
      throw mapError(e);
    }

    const content: ContentBlock[] = [];
    for (const b of final.content as any[]) {
      if (b.type === 'text') content.push({ type: 'text', text: b.text });
      else if (b.type === 'tool_use') content.push({ type: 'tool_use', id: b.id, name: b.name, input: (b.input ?? {}) as Record<string, unknown> } satisfies ToolUseBlock);
    }
    const u = final.usage ?? {};
    const usage: Usage = {
      inputTokens: u.input_tokens ?? 0,
      outputTokens: u.output_tokens ?? 0,
      cacheReadTokens: u.cache_read_input_tokens ?? 0,
      cacheWriteTokens: u.cache_creation_input_tokens ?? 0,
    };
    yield {
      type: 'done',
      message: { role: 'assistant', content, raw: { provider: 'anthropic', model: req.model.id, content: final.content } },
      usage,
      stopReason: mapStop(final.stop_reason),
      servedModel: final.model,
    };
  }
}

function blockToWire(b: ContentBlock): Anthropic.ContentBlockParam {
  switch (b.type) {
    case 'text':
      return { type: 'text', text: b.text || ' ' };
    case 'tool_use':
      return { type: 'tool_use', id: b.id, name: b.name, input: b.input };
    case 'tool_result':
      return { type: 'tool_result', tool_use_id: b.toolUseId, content: b.content || '(empty)', is_error: b.isError || undefined };
    case 'image':
      return { type: 'image', source: { type: 'base64', media_type: b.mediaType as 'image/png', data: b.data } };
  }
}

function mapStop(s: string | null | undefined): StopReason {
  switch (s) {
    case 'tool_use':
    case 'max_tokens':
    case 'refusal':
    case 'stop_sequence':
    case 'pause_turn':
      return s;
    case 'model_context_window_exceeded':
      return 'max_tokens';
    default:
      return 'end_turn';
  }
}

function mapError(e: unknown): Error {
  if (e instanceof Anthropic.APIUserAbortError) {
    const err = new Error('Request aborted');
    err.name = 'AbortError';
    return err;
  }
  if (e instanceof Anthropic.APIConnectionError) return new ProviderError(`Connection error: ${e.message}`, 'network');
  if (e instanceof Anthropic.APIError) {
    const status = e.status ?? 0;
    const msg = e.message ?? String(e);
    const retryAfter = parseRetryAfter((e.headers as Headers | undefined)?.get?.('retry-after'));
    return new ProviderError(`Anthropic API ${status}: ${msg}`, classifyStatus(status, msg), status, retryAfter);
  }
  if (e instanceof Error && e.name === 'AbortError') return e;
  // JSON produced by eager input streaming that the SDK could not parse: retry the turn.
  if (e instanceof Error && /JSON|Unexpected token|Unterminated/i.test(e.message)) return new ProviderError(`Malformed tool input from model: ${e.message}`, 'invalid_output');
  return e instanceof Error ? e : new Error(String(e));
}

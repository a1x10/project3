import type { ChatMessage, ContentBlock, StopReason, Usage } from '../types.js';
import { sseEvents } from './sse.js';
import { ProviderError, classifyStatus, parseRetryAfter, type LLMProvider, type ProviderEvent, type StreamRequest } from './types.js';

export interface GeminiOptions {
  name: string;
  baseUrl: string;
  apiKey?: string;
  headers?: Record<string, string>;
}

const UNSUPPORTED_SCHEMA_KEYS = new Set(['$schema', 'additionalProperties', '$ref', 'definitions', '$defs', 'exclusiveMinimum', 'exclusiveMaximum', 'propertyNames', 'const', 'default', 'examples']);

/** Gemini accepts an OpenAPI-subset schema; strip what it rejects. */
export function sanitizeSchema(s: unknown): unknown {
  if (Array.isArray(s)) return s.map(sanitizeSchema);
  if (!s || typeof s !== 'object') return s;
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(s as Record<string, unknown>)) {
    if (UNSUPPORTED_SCHEMA_KEYS.has(k)) continue;
    if (k === 'anyOf' && Array.isArray(v)) {
      const nonNull = v.filter((x: any) => x?.type !== 'null');
      if (nonNull.length === 1) {
        Object.assign(out, sanitizeSchema(nonNull[0]) as object, { nullable: true });
        continue;
      }
    }
    if (k === 'type' && Array.isArray(v)) {
      const t = v.filter((x) => x !== 'null');
      out.type = t[0] ?? 'string';
      if (t.length !== v.length) out.nullable = true;
      continue;
    }
    out[k] = sanitizeSchema(v);
  }
  return out;
}

/** Native Google Gemini (Generative Language API) adapter with streaming + function calling. */
export class GeminiProvider implements LLMProvider {
  readonly type = 'gemini' as const;
  readonly name: string;
  constructor(private readonly opts: GeminiOptions) {
    this.name = opts.name;
  }

  toWire(messages: ChatMessage[]): any[] {
    const nameById = new Map<string, string>();
    const contents: any[] = [];
    for (const m of messages) {
      const parts: any[] = [];
      for (const b of m.content) {
        if (b.type === 'text' && b.text) parts.push({ text: b.text });
        else if (b.type === 'image') parts.push({ inlineData: { mimeType: b.mediaType, data: b.data } });
        else if (b.type === 'tool_use') {
          nameById.set(b.id, b.name);
          parts.push({ functionCall: { name: b.name, args: b.input ?? {} } });
        } else if (b.type === 'tool_result') {
          parts.push({
            functionResponse: {
              name: nameById.get(b.toolUseId) ?? 'tool',
              response: b.isError ? { error: b.content } : { result: b.content },
            },
          });
        }
      }
      if (!parts.length) parts.push({ text: ' ' });
      contents.push({ role: m.role === 'assistant' ? 'model' : 'user', parts });
    }
    return contents;
  }

  async *stream(req: StreamRequest): AsyncGenerator<ProviderEvent> {
    const body: Record<string, unknown> = {
      contents: this.toWire(req.messages),
      generationConfig: { maxOutputTokens: Math.min(req.maxTokens, req.model.maxOutput) },
    };
    if (req.system) body.systemInstruction = { parts: [{ text: req.system }] };
    if (req.tools.length && req.model.toolCalling) {
      body.tools = [{ functionDeclarations: req.tools.map((t) => ({ name: t.name, description: t.description, parameters: sanitizeSchema(t.inputSchema) })) }];
    }
    const url = `${this.opts.baseUrl.replace(/\/$/, '')}/v1beta/models/${encodeURIComponent(req.model.id)}:streamGenerateContent?alt=sse`;
    let res: Response;
    try {
      res = await fetch(url, {
        method: 'POST',
        headers: { 'content-type': 'application/json', ...(this.opts.apiKey ? { 'x-goog-api-key': this.opts.apiKey } : {}), ...(this.opts.headers ?? {}) },
        body: JSON.stringify(body),
        signal: req.signal,
      });
    } catch (e) {
      if ((e as Error).name === 'AbortError') throw e;
      throw new ProviderError(`Connection error (${this.name}): ${(e as Error).message}`, 'network');
    }
    if (!res.ok || !res.body) {
      const text = await res.text().catch(() => '');
      throw new ProviderError(`Gemini API ${res.status}: ${text.slice(0, 500)}`, classifyStatus(res.status, text), res.status, parseRetryAfter(res.headers.get('retry-after')));
    }
    let text = '';
    const calls: { id: string; name: string; args: Record<string, unknown> }[] = [];
    const usage: Usage = { inputTokens: 0, outputTokens: 0 };
    let finish = '';
    let n = 0;
    for await (const ev of sseEvents(res.body, req.signal)) {
      let chunk: any;
      try {
        chunk = JSON.parse(ev.data);
      } catch {
        continue;
      }
      if (chunk.error) throw new ProviderError(`Gemini: ${chunk.error.message}`, 'server');
      if (chunk.usageMetadata) {
        usage.inputTokens = chunk.usageMetadata.promptTokenCount ?? usage.inputTokens;
        usage.outputTokens = (chunk.usageMetadata.candidatesTokenCount ?? 0) + (chunk.usageMetadata.thoughtsTokenCount ?? 0);
        usage.cacheReadTokens = chunk.usageMetadata.cachedContentTokenCount ?? 0;
      }
      const cand = chunk.candidates?.[0];
      if (!cand) continue;
      for (const p of cand.content?.parts ?? []) {
        if (p.thought) {
          yield { type: 'thinking' };
          continue;
        }
        if (typeof p.text === 'string' && p.text) {
          text += p.text;
          yield { type: 'text', text: p.text };
        }
        if (p.functionCall) {
          const id = p.functionCall.id ?? `gcall_${Date.now().toString(36)}_${n++}`;
          calls.push({ id, name: p.functionCall.name, args: p.functionCall.args ?? {} });
          yield { type: 'tool_start', id, name: p.functionCall.name };
          yield { type: 'tool_input_delta', id, delta: JSON.stringify(p.functionCall.args ?? {}) };
        }
      }
      if (cand.finishReason) finish = cand.finishReason;
    }
    const content: ContentBlock[] = [];
    if (text) content.push({ type: 'text', text });
    for (const c of calls) content.push({ type: 'tool_use', id: c.id, name: c.name, input: c.args });
    const stop: StopReason = calls.length ? 'tool_use' : finish === 'MAX_TOKENS' ? 'max_tokens' : finish === 'SAFETY' ? 'refusal' : 'end_turn';
    yield { type: 'done', message: { role: 'assistant', content }, usage, stopReason: stop };
  }
}

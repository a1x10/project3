import type { ChatMessage, ContentBlock, StopReason, Usage } from '../types.js';
import { sseEvents } from './sse.js';
import { ProviderError, classifyStatus, parseRetryAfter, type LLMProvider, type ProviderEvent, type StreamRequest } from './types.js';

export interface OpenAIOptions {
  name: string;
  baseUrl: string;
  apiKey?: string;
  headers?: Record<string, string>;
}

/**
 * Adapter for the OpenAI Chat Completions wire format. Covers OpenAI, OpenRouter, Groq,
 * Ollama (/v1), LM Studio, vLLM and any other OpenAI-compatible endpoint.
 */
export class OpenAICompatProvider implements LLMProvider {
  readonly type = 'openai' as const;
  readonly name: string;
  constructor(private readonly opts: OpenAIOptions) {
    this.name = opts.name;
  }

  toWire(system: string, messages: ChatMessage[]): any[] {
    const out: any[] = [];
    if (system) out.push({ role: 'system', content: system });
    for (const m of messages) {
      if (m.role === 'user') {
        const results = m.content.filter((b) => b.type === 'tool_result');
        for (const r of results) {
          if (r.type === 'tool_result') out.push({ role: 'tool', tool_call_id: r.toolUseId, content: (r.isError ? 'ERROR: ' : '') + (r.content || '(empty)') });
        }
        const parts = m.content.filter((b) => b.type === 'text' || b.type === 'image');
        if (parts.length) {
          const hasImage = parts.some((p) => p.type === 'image');
          out.push({
            role: 'user',
            content: hasImage
              ? parts.map((p) => (p.type === 'text' ? { type: 'text', text: p.text } : { type: 'image_url', image_url: { url: `data:${(p as any).mediaType};base64,${(p as any).data}` } }))
              : parts.map((p) => (p as any).text).join('\n'),
          });
        }
      } else {
        const text = m.content.filter((b) => b.type === 'text').map((b) => (b as any).text).join('');
        const calls = m.content.filter((b) => b.type === 'tool_use');
        const msg: any = { role: 'assistant', content: text || null };
        if (calls.length) {
          msg.tool_calls = calls.map((c: any) => ({ id: c.id, type: 'function', function: { name: c.name, arguments: JSON.stringify(c.input ?? {}) } }));
        }
        out.push(msg);
      }
    }
    return out;
  }

  async *stream(req: StreamRequest): AsyncGenerator<ProviderEvent> {
    const isOpenAI = /api\.openai\.com/.test(this.opts.baseUrl);
    const body: Record<string, unknown> = {
      model: req.model.id,
      messages: this.toWire(req.system, req.messages),
      stream: true,
      stream_options: { include_usage: true },
    };
    const maxTok = Math.min(req.maxTokens, req.model.maxOutput);
    if (isOpenAI) body.max_completion_tokens = maxTok;
    else body.max_tokens = maxTok;
    if (req.tools.length && req.model.toolCalling) {
      body.tools = req.tools.map((t) => ({ type: 'function', function: { name: t.name, description: t.description, parameters: t.inputSchema } }));
    }

    let res: Response;
    try {
      res = await fetch(this.opts.baseUrl.replace(/\/$/, '') + '/chat/completions', {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          ...(this.opts.apiKey ? { authorization: `Bearer ${this.opts.apiKey}` } : {}),
          ...(this.opts.headers ?? {}),
        },
        body: JSON.stringify(body),
        signal: req.signal,
      });
    } catch (e) {
      if ((e as Error).name === 'AbortError') throw e;
      throw new ProviderError(`Connection error (${this.name}): ${(e as Error).message}`, 'network');
    }
    if (!res.ok || !res.body) {
      const text = await res.text().catch(() => '');
      throw new ProviderError(`${this.name} API ${res.status}: ${text.slice(0, 500)}`, classifyStatus(res.status, text), res.status, parseRetryAfter(res.headers.get('retry-after')));
    }

    let text = '';
    const calls = new Map<number, { id: string; name: string; args: string }>();
    let finish: string | null = null;
    const usage: Usage = { inputTokens: 0, outputTokens: 0 };

    for await (const ev of sseEvents(res.body, req.signal)) {
      if (ev.data === '[DONE]') break;
      let chunk: any;
      try {
        chunk = JSON.parse(ev.data);
      } catch {
        continue;
      }
      if (chunk.error) throw new ProviderError(`${this.name}: ${chunk.error.message ?? JSON.stringify(chunk.error)}`, 'server');
      if (chunk.usage) {
        usage.inputTokens = chunk.usage.prompt_tokens ?? usage.inputTokens;
        usage.outputTokens = chunk.usage.completion_tokens ?? usage.outputTokens;
        usage.cacheReadTokens = chunk.usage.prompt_tokens_details?.cached_tokens ?? 0;
        if (usage.cacheReadTokens) usage.inputTokens -= usage.cacheReadTokens;
      }
      const choice = chunk.choices?.[0];
      if (!choice) continue;
      const d = choice.delta ?? {};
      if (d.reasoning || d.reasoning_content) yield { type: 'thinking' };
      if (typeof d.content === 'string' && d.content) {
        text += d.content;
        yield { type: 'text', text: d.content };
      }
      for (const tc of d.tool_calls ?? []) {
        const idx = tc.index ?? 0;
        let cur = calls.get(idx);
        if (!cur) {
          cur = { id: tc.id ?? `call_${idx}_${Date.now().toString(36)}`, name: tc.function?.name ?? '', args: '' };
          calls.set(idx, cur);
          if (cur.name) yield { type: 'tool_start', id: cur.id, name: cur.name };
        } else if (tc.function?.name && !cur.name) {
          cur.name = tc.function.name;
          yield { type: 'tool_start', id: cur.id, name: cur.name };
        }
        if (tc.function?.arguments) {
          cur.args += tc.function.arguments;
          yield { type: 'tool_input_delta', id: cur.id, delta: tc.function.arguments };
        }
      }
      if (choice.finish_reason) finish = choice.finish_reason;
    }

    const content: ContentBlock[] = [];
    if (text) content.push({ type: 'text', text });
    for (const c of [...calls.entries()].sort((a, b) => a[0] - b[0]).map((e) => e[1])) {
      let input: Record<string, unknown> = {};
      try {
        input = c.args.trim() ? JSON.parse(c.args) : {};
      } catch {
        input = { __invalid_json__: c.args };
      }
      content.push({ type: 'tool_use', id: c.id, name: c.name, input });
    }
    const stop: StopReason = calls.size ? 'tool_use' : finish === 'length' ? 'max_tokens' : finish === 'content_filter' ? 'refusal' : 'end_turn';
    yield { type: 'done', message: { role: 'assistant', content }, usage, stopReason: stop };
  }
}

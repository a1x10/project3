import { describe, expect, it } from 'vitest';
import { ModelRegistry } from '../../src/providers/registry.js';
import { sanitizeSchema } from '../../src/providers/gemini.js';
import { OpenAICompatProvider } from '../../src/providers/openai.js';
import { costUsd, classifyStatus } from '../../src/providers/types.js';
import { repairTranscript } from '../../src/sessions/store.js';

describe('model registry', () => {
  it('resolves aliases, provider prefixes and catalog models', () => {
    const r = new ModelRegistry({});
    expect(r.resolve('opus').id).toBe('claude-opus-5-5');
    expect(r.resolve()).toMatchObject({ provider: 'freellmapi', id: 'auto:smart' });
    expect(r.resolve('freellmapi:qwen/qwen3.8-max:free')).toMatchObject({ provider: 'freellmapi', id: 'qwen/qwen3.8-max:free' });
    expect(r.resolve('sonnet').provider).toBe('anthropic');
    expect(r.resolve('gemini').provider).toBe('gemini');
    expect(r.resolve('ollama:qwen2.5-coder:14b')).toMatchObject({ provider: 'ollama', id: 'qwen2.5-coder:14b' });
    expect(r.resolve('openrouter:anthropic/claude-sonnet-4.5').provider).toBe('openrouter');
    expect(r.resolve('gpt-5').provider).toBe('openai');
    expect(() => r.resolve('nonsense-model')).toThrow(/Unknown model/);
  });
  it('applies custom providers, model overrides and aliases from settings', () => {
    const r = new ModelRegistry({ providers: { lmstudio: { type: 'openai', baseUrl: 'http://localhost:1234/v1', models: [{ id: 'local', contextWindow: 8192, inputPrice: 0 }] } }, modelAliases: { fast: 'lmstudio:local' } });
    expect(r.resolve('fast')).toMatchObject({ provider: 'lmstudio', contextWindow: 8192 });
  });
  it('computes cost including cache pricing', () => {
    const m = new ModelRegistry({}).resolve('opus');
    expect(costUsd(m, { inputTokens: 1_000_000, outputTokens: 1_000_000 })).toBeCloseTo(24);
    expect(costUsd(m, { inputTokens: 0, outputTokens: 0, cacheReadTokens: 1_000_000 })).toBeCloseTo(0.2);
  });
  it('classifies HTTP errors', () => {
    expect(classifyStatus(429, '')).toBe('rate_limit');
    expect(classifyStatus(529, '')).toBe('overloaded');
    expect(classifyStatus(400, 'prompt is too long: 300000 tokens')).toBe('context_length');
    expect(classifyStatus(401, '')).toBe('auth');
  });
});

describe('wire conversion', () => {
  it('converts transcripts to OpenAI messages with tool calls/results', () => {
    const p = new OpenAICompatProvider({ name: 'x', baseUrl: 'http://x' });
    const wire = p.toWire('SYS', [
      { role: 'user', content: [{ type: 'text', text: 'hi' }] },
      { role: 'assistant', content: [{ type: 'text', text: 'calling' }, { type: 'tool_use', id: 't1', name: 'Read', input: { file_path: 'a' } }] },
      { role: 'user', content: [{ type: 'tool_result', toolUseId: 't1', content: 'data', isError: true }] },
    ]);
    expect(wire[0]).toEqual({ role: 'system', content: 'SYS' });
    expect(wire[2].tool_calls[0].function).toEqual({ name: 'Read', arguments: '{"file_path":"a"}' });
    expect(wire[3]).toEqual({ role: 'tool', tool_call_id: 't1', content: 'ERROR: data' });
  });
  it('sanitizes JSON schema for Gemini', () => {
    const s = sanitizeSchema({ $schema: 'x', type: 'object', additionalProperties: false, properties: { a: { type: ['string', 'null'] }, b: { anyOf: [{ type: 'number' }, { type: 'null' }] } } }) as any;
    expect(s.$schema).toBeUndefined();
    expect(s.additionalProperties).toBeUndefined();
    expect(s.properties.a).toEqual({ type: 'string', nullable: true });
    expect(s.properties.b).toEqual({ type: 'number', nullable: true });
  });
  it('repairs transcripts with dangling tool calls', () => {
    const fixed = repairTranscript([
      { role: 'user', content: [{ type: 'text', text: 'x' }] },
      { role: 'assistant', content: [{ type: 'tool_use', id: 'a', name: 'Read', input: {} }] },
    ]);
    expect(fixed).toHaveLength(3);
    expect(fixed[2]!.content[0]).toMatchObject({ type: 'tool_result', toolUseId: 'a', isError: true });
  });
});

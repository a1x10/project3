import { isAbortError, sleep } from '../utils/async.js';
import { ProviderError, type LLMProvider, type ProviderEvent, type StreamRequest } from './types.js';

export interface RetryOptions {
  maxRetries?: number;
  baseDelayMs?: number;
  onRetry?: (info: { attempt: number; delayMs: number; error: ProviderError }) => void;
}

/**
 * Retries transient failures (429/5xx/overload/network/malformed tool JSON) with exponential
 * backoff honoring retry-after. A retry only happens if nothing was streamed yet, or if the
 * failure was malformed tool output (the partial turn is discarded and re-issued).
 */
export async function* streamWithRetry(provider: LLMProvider, req: StreamRequest, opts: RetryOptions = {}): AsyncGenerator<ProviderEvent & { restart?: boolean }> {
  const max = opts.maxRetries ?? 4;
  const base = opts.baseDelayMs ?? 1000;
  for (let attempt = 0; ; attempt++) {
    let emitted = false;
    try {
      for await (const ev of provider.stream(req)) {
        emitted = true;
        yield ev;
      }
      return;
    } catch (e) {
      if (isAbortError(e) || req.signal?.aborted) throw e;
      const pe = e instanceof ProviderError ? e : null;
      const canRetry = pe && pe.retryable && attempt < max && (!emitted || pe.kind === 'invalid_output');
      if (!canRetry) throw e;
      const delay = Math.min(60_000, pe.retryAfterMs ?? base * 2 ** attempt + Math.random() * 250);
      opts.onRetry?.({ attempt: attempt + 1, delayMs: delay, error: pe });
      await sleep(delay, req.signal);
      if (emitted) yield { type: 'text', text: '', restart: true } as any;
    }
  }
}

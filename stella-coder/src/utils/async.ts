export function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(abortError());
    const t = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(t);
      reject(abortError());
    };
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

export function abortError(msg = 'Operation aborted'): Error {
  const e = new Error(msg);
  e.name = 'AbortError';
  return e;
}

export function isAbortError(e: unknown): boolean {
  return !!e && typeof e === 'object' && ((e as Error).name === 'AbortError' || (e as Error).name === 'APIUserAbortError');
}

/** Counting semaphore to bound parallelism (subagents, indexing, tool batches). */
export class Semaphore {
  private queue: Array<() => void> = [];
  private active = 0;
  constructor(private readonly max: number) {}
  async acquire(): Promise<() => void> {
    if (this.active < this.max) {
      this.active++;
      return () => this.release();
    }
    await new Promise<void>((r) => this.queue.push(r));
    this.active++;
    return () => this.release();
  }
  private release() {
    this.active--;
    const next = this.queue.shift();
    if (next) next();
  }
  get inUse() {
    return this.active;
  }
  async run<T>(fn: () => Promise<T>): Promise<T> {
    const rel = await this.acquire();
    try {
      return await fn();
    } finally {
      rel();
    }
  }
}

/** Link a child AbortController to a parent signal. */
export function childController(parent?: AbortSignal): AbortController {
  const c = new AbortController();
  if (parent) {
    if (parent.aborted) c.abort(parent.reason);
    else parent.addEventListener('abort', () => c.abort(parent.reason), { once: true });
  }
  return c;
}

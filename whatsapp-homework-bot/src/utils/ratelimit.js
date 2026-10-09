// Ограничение частоты: не больше limit событий за windowMs для каждого ключа.
export class RateLimiter {
  constructor(limit, windowMs) {
    this.limit = limit;
    this.windowMs = windowMs;
    this.hits = new Map();
  }

  recent(key, now = Date.now()) {
    const list = (this.hits.get(key) || []).filter((t) => now - t < this.windowMs);
    if (list.length) this.hits.set(key, list);
    else this.hits.delete(key);
    return list;
  }

  // true — можно, событие засчитано; false — лимит исчерпан
  take(key, now = Date.now()) {
    const list = this.recent(key, now);
    if (list.length >= this.limit) return false;
    list.push(now);
    this.hits.set(key, list);
    return true;
  }

  // Через сколько миллисекунд освободится место
  retryIn(key, now = Date.now()) {
    const list = this.recent(key, now);
    if (list.length < this.limit) return 0;
    return this.windowMs - (now - list[0]);
  }
}

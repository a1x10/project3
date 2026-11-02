import type { Config } from './config.js';

/**
 * Upstream credentials. Either a fixed UPSTREAM_API_KEY, or — for the bundled FreeLLMAPI
 * router — the unified key fetched through its dashboard API with the admin account created by
 * FreeLLMAPI's declarative startup config (FREEAPI_CONFIG_JSON).
 */
export class Upstream {
  private key: string;
  private fetching: Promise<string> | null = null;
  lastError = '';
  private keylessDone = false;

  constructor(private readonly cfg: Config) {
    this.key = cfg.upstreamApiKey;
  }

  get baseUrl() {
    return this.cfg.upstreamBaseUrl;
  }

  async apiKey(refresh = false): Promise<string> {
    if (this.key && !refresh) return this.key;
    if (!this.cfg.routerUrl || !this.cfg.routerAdminEmail || !this.cfg.routerAdminPassword) return this.key;
    this.fetching ??= this.fetchRouterKey().finally(() => (this.fetching = null));
    return this.fetching;
  }

  private async fetchRouterKey(): Promise<string> {
    const base = this.cfg.routerUrl;
    try {
      const login = await fetch(`${base}/api/auth/login`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ email: this.cfg.routerAdminEmail, password: this.cfg.routerAdminPassword }),
        signal: AbortSignal.timeout(15_000),
      });
      const lj: any = await login.json().catch(() => null);
      if (!login.ok || !lj?.token) throw new Error(lj?.error?.message || `login HTTP ${login.status}`);
      const k = await fetch(`${base}/api/settings/api-key`, { headers: { authorization: `Bearer ${lj.token}` }, signal: AbortSignal.timeout(15_000) });
      const kj: any = await k.json().catch(() => null);
      if (!k.ok || !kj?.apiKey) throw new Error(kj?.error?.message || `api-key HTTP ${k.status}`);
      this.key = kj.apiKey;
      if (!this.keylessDone) {
        this.keylessDone = true;
        await this.enableKeyless(base, lj.token).catch((e) => console.error('[upstream] keyless providers:', (e as Error).message));
      }
      this.lastError = '';
      return this.key;
    } catch (e) {
      this.lastError = `FreeLLMAPI: ${(e as Error).message}`;
      return this.key;
    }
  }

  /** Switch on FreeLLMAPI providers that need no API key, so models answer right after deployment. */
  private async enableKeyless(base: string, token: string) {
    if (!this.cfg.routerKeyless.length) return;
    const h = { authorization: `Bearer ${token}`, 'content-type': 'application/json' };
    const pr = await fetch(`${base}/api/keys/providers`, { headers: h, signal: AbortSignal.timeout(15_000) });
    const pj: any = await pr.json().catch(() => null);
    const list: any[] = Array.isArray(pj?.providers) ? pj.providers : [];
    for (const platform of this.cfg.routerKeyless) {
      const p = list.find((x) => x.platform === platform);
      if (!p || !p.keyless || p.configured) continue;
      const r = await fetch(`${base}/api/keys`, { method: 'POST', headers: h, body: JSON.stringify({ platform }), signal: AbortSignal.timeout(15_000) });
      if (r.ok) console.log(`[upstream] FreeLLMAPI: включён бесплатный провайдер без ключа «${p.name ?? platform}»`);
    }
  }

  async headers(refresh = false): Promise<Record<string, string>> {
    const key = await this.apiKey(refresh);
    return key ? { authorization: `Bearer ${key}` } : {};
  }

  async models(): Promise<string[]> {
    const res = await fetch(`${this.baseUrl}/models`, { headers: await this.headers(), signal: AbortSignal.timeout(15_000) });
    if (res.status === 401) {
      const again = await fetch(`${this.baseUrl}/models`, { headers: await this.headers(true), signal: AbortSignal.timeout(15_000) });
      if (!again.ok) throw new Error(`upstream /models HTTP ${again.status}`);
      return ids(await again.json());
    }
    if (!res.ok) throw new Error(`upstream /models HTTP ${res.status}`);
    return ids(await res.json());
  }

  async health(): Promise<{ ok: boolean; models?: number; error?: string; keySource: string }> {
    const keySource = this.cfg.upstreamApiKey ? 'UPSTREAM_API_KEY' : this.cfg.routerAdminEmail ? 'FreeLLMAPI (авто)' : 'нет ключа';
    try {
      const m = await this.models();
      return { ok: true, models: m.length, keySource };
    } catch (e) {
      return { ok: false, error: this.lastError || (e as Error).message, keySource };
    }
  }
}

function ids(j: any): string[] {
  const items = Array.isArray(j) ? j : j?.data ?? j?.models ?? [];
  return items.map((m: any) => (typeof m === 'string' ? m : m.id || m.name)).filter(Boolean);
}

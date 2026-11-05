// Stella Cloud client: Telegram sign-in (device flow), account info, models.
// All AI requests go through the owner's Stella Cloud server; the app never holds provider keys.
//
// In the Windows app (Electron) the API key is kept by the main process, encrypted with the OS
// keychain (safeStorage); in a plain browser build it falls back to localStorage.

const CRED_KEY = "stella-cloud-credentials";
const URL_KEY = "stella-cloud-url";

const desktop = () => (typeof window !== "undefined" ? window.stellaDesktop : undefined);

export const DEFAULT_CLOUD_URL = (import.meta.env?.VITE_CLOUD_URL || "").replace(/\/$/, "");

export function cloudUrl() {
  const d = desktop();
  let saved = "";
  try {
    saved = localStorage.getItem(URL_KEY) || "";
  } catch {
    /* storage unavailable */
  }
  const fromWindow = typeof window !== "undefined" && window.location?.protocol?.startsWith("http") ? window.location.origin : "";
  return (saved || d?.cloudUrl || DEFAULT_CLOUD_URL || fromWindow).replace(/\/$/, "");
}

export function setCloudUrl(url) {
  try {
    const v = String(url || "").trim().replace(/\/$/, "");
    if (v) localStorage.setItem(URL_KEY, v);
    else localStorage.removeItem(URL_KEY);
  } catch {
    /* ignore */
  }
}

export async function loadCredentials() {
  const d = desktop();
  try {
    const raw = d?.secureGet ? await d.secureGet(CRED_KEY) : localStorage.getItem(CRED_KEY);
    const c = raw ? JSON.parse(raw) : null;
    return c && c.apiKey ? c : null;
  } catch {
    return null;
  }
}

export async function saveCredentials(c) {
  const d = desktop();
  const raw = c ? JSON.stringify(c) : "";
  try {
    if (d?.secureSet) await d.secureSet(CRED_KEY, raw);
    else if (raw) localStorage.setItem(CRED_KEY, raw);
    else localStorage.removeItem(CRED_KEY);
  } catch {
    /* ignore */
  }
}

export class CloudError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function call(path, { method, body, apiKey, base = cloudUrl() } = {}) {
  if (!base) throw new CloudError(0, "Не указан адрес сервера Stella Cloud");
  let res;
  try {
    res = await fetch(base + path, {
      method: method || (body ? "POST" : "GET"),
      headers: { ...(body ? { "Content-Type": "application/json" } : {}), ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}), "X-Stella-Client": "studio" },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    throw new CloudError(0, `Сервер ${base} недоступен (${e.message})`);
  }
  let json = null;
  try {
    json = await res.json();
  } catch {
    /* not json */
  }
  if (!res.ok) throw new CloudError(res.status, json?.error?.message || `HTTP ${res.status}`);
  return json;
}

export function deviceName() {
  const d = desktop();
  if (d?.deviceName) return d.deviceName;
  const ua = typeof navigator !== "undefined" ? navigator.userAgent : "";
  return /Windows/.test(ua) ? "Windows" : /Mac/.test(ua) ? "macOS" : /Linux/.test(ua) ? "Linux" : "Браузер";
}

export const startLogin = (base) => call("/api/auth/start", { body: { client: "studio", kind: "apikey", device: deviceName() }, base });
export const pollLogin = (id, base) => call(`/api/auth/poll?id=${encodeURIComponent(id)}`, { base });
export const fetchMe = (apiKey) => call("/api/me", { apiKey });
export const publicConfig = (base) => call("/api/config", { base });

export async function logout(apiKey) {
  if (apiKey) await call("/api/auth/logout", { method: "POST", body: {}, apiKey }).catch(() => undefined);
  await saveCredentials(null);
}


/** Target for llmClient.streamChat: the cloud gateway speaks the OpenAI protocol. */
export function cloudTarget(apiKey, model) {
  return { url: `${cloudUrl()}/v1/chat/completions`, model: model || "auto:smart", apiKey };
}

export function openExternal(url) {
  const d = desktop();
  if (d?.openExternal) d.openExternal(url);
  else window.open(url, "_blank", "noopener");
}

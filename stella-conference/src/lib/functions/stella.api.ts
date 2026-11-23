import { invoke } from "@tauri-apps/api/core";
import { safeLocalStorage } from "../storage";
import { STORAGE_KEYS } from "@/config";
import { STELLA_SERVER_PLACEHOLDER } from "@/config/ai-providers.constants";

// The original hosted (paid) API of Pluely is not used in Stella Conference.
export async function shouldUseStellaAPI(): Promise<boolean> {
  return false;
}

export interface StellaConfig {
  server: string;
  token: string;
  user: string;
}

// Stella.exe starts this app with the account's server and token (environment, never on the command line)
export async function getStellaConfig(): Promise<StellaConfig | null> {
  try {
    const c = await invoke<StellaConfig>("stella_config");
    return c && c.server && c.token ? c : null;
  } catch {
    return null;
  }
}

export function stellaUrl(url: string, vars: Record<string, string>): string {
  if (!url.startsWith(STELLA_SERVER_PLACEHOLDER)) return url;
  const server = (vars.SERVER || "").replace(/\/+$/, "");
  return server + url.slice(STELLA_SERVER_PLACEHOLDER.length);
}

// select the Stella providers (Gemini through the Stella server) with this account's token
export async function applyStellaConfig(): Promise<boolean> {
  const c = await getStellaConfig();
  if (!c) return false;
  const vars = { server: c.server, api_key: c.token };
  const ai = { provider: "stella", variables: { ...vars, model: "gemini-flash-latest" } };
  const stt = { provider: "stella-stt", variables: { ...vars, model: "gemini-flash-lite-latest" } };
  const keep = (key: string, def: { provider: string; variables: Record<string, string> }) => {
    try {
      const cur = JSON.parse(safeLocalStorage.getItem(key) || "null");
      // keep the user's model choice, always refresh server + token
      if (cur && cur.provider === def.provider) return { ...def, variables: { ...def.variables, model: cur.variables?.model || def.variables.model, ...vars } };
    } catch {}
    return def;
  };
  safeLocalStorage.setItem(STORAGE_KEYS.SELECTED_AI_PROVIDER, JSON.stringify(keep(STORAGE_KEYS.SELECTED_AI_PROVIDER, ai)));
  safeLocalStorage.setItem(STORAGE_KEYS.SELECTED_STT_PROVIDER, JSON.stringify(keep(STORAGE_KEYS.SELECTED_STT_PROVIDER, stt)));
  safeLocalStorage.setItem(STORAGE_KEYS.STELLA_API_ENABLED, "false");
  return true;
}

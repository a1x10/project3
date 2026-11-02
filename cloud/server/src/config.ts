import path from 'node:path';

export interface Config {
  port: number;
  host: string;
  /** Public base URL of the site (https://ai.example.com) — used in bot messages and links. */
  publicUrl: string;
  dbPath: string;
  webDir: string;
  /** Installers offered on the site (Vibing AI Studio .exe etc.). */
  downloadsDir: string;
  /** Optional fixed bot username (otherwise taken from getMe). */
  botUsername: string;
  /** Telegram */
  botToken: string;
  telegramApiUrl: string;
  /** Telegram user ids that become administrators. */
  adminTgIds: number[];
  /** Upstream OpenAI-compatible API (FreeLLMAPI router by default). */
  upstreamBaseUrl: string;
  upstreamApiKey: string;
  /** FreeLLMAPI dashboard (to fetch the unified key automatically). */
  routerUrl: string;
  routerAdminEmail: string;
  routerAdminPassword: string;
  /** Initial values; editable later in the admin panel. */
  defaultSystemPrompt: string;
  defaultModel: string;
  sessionTtlDays: number;
  loginTtlSec: number;
  /** Max request body for /v1 (bytes). */
  maxBodyBytes: number;
}

const num = (v: string | undefined, d: number) => (v && !Number.isNaN(Number(v)) ? Number(v) : d);

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const port = num(env.PORT, 8080);
  const routerUrl = (env.ROUTER_URL || '').replace(/\/$/, '');
  return {
    port,
    host: env.HOST || '0.0.0.0',
    publicUrl: (env.PUBLIC_URL || `http://localhost:${port}`).replace(/\/$/, ''),
    dbPath: env.DATABASE_PATH || path.resolve('data', 'stella-cloud.db'),
    webDir: env.WEB_DIR || path.resolve('..', 'web', 'dist'),
    downloadsDir: env.DOWNLOADS_DIR || path.resolve('data', 'downloads'),
    botUsername: (env.TELEGRAM_BOT_USERNAME || '').replace(/^@/, ''),
    botToken: env.TELEGRAM_BOT_TOKEN || '',
    telegramApiUrl: (env.TELEGRAM_API_URL || 'https://api.telegram.org').replace(/\/$/, ''),
    adminTgIds: (env.ADMIN_TELEGRAM_IDS || '')
      .split(/[\s,]+/)
      .map((s) => Number(s.trim()))
      .filter((n) => Number.isInteger(n) && n > 0),
    upstreamBaseUrl: (env.UPSTREAM_BASE_URL || (routerUrl ? `${routerUrl}/v1` : 'http://localhost:3001/v1')).replace(/\/$/, ''),
    upstreamApiKey: env.UPSTREAM_API_KEY || '',
    routerUrl,
    routerAdminEmail: env.ROUTER_ADMIN_EMAIL || '',
    routerAdminPassword: env.ROUTER_ADMIN_PASSWORD || '',
    defaultSystemPrompt: env.SYSTEM_PROMPT || '',
    defaultModel: env.DEFAULT_MODEL || 'auto:smart',
    sessionTtlDays: num(env.SESSION_TTL_DAYS, 30),
    loginTtlSec: num(env.LOGIN_TTL_SEC, 600),
    maxBodyBytes: num(env.MAX_BODY_BYTES, 20 * 1024 * 1024),
  };
}

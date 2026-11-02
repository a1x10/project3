import path from 'node:path';
import { z } from 'zod';
import { readJson, writeJson } from '../utils/fsutil.js';
import { stellaHome } from './paths.js';

export const PermissionModeSchema = z.enum(['default', 'plan', 'acceptEdits', 'auto', 'bypassPermissions']);
export type PermissionMode = z.infer<typeof PermissionModeSchema>;

const HookCommandSchema = z.object({
  type: z.literal('command').default('command'),
  command: z.string(),
  timeout: z.number().positive().optional(), // seconds
});
const HookMatcherSchema = z.object({
  matcher: z.string().optional(),
  hooks: z.array(HookCommandSchema),
});

export const McpServerConfigSchema = z.object({
  type: z.enum(['stdio', 'http', 'sse']).optional(),
  command: z.string().optional(),
  args: z.array(z.string()).optional(),
  env: z.record(z.string(), z.string()).optional(),
  cwd: z.string().optional(),
  url: z.string().optional(),
  headers: z.record(z.string(), z.string()).optional(),
  enabled: z.boolean().optional(),
  timeout: z.number().optional(),
});
export type McpServerConfig = z.infer<typeof McpServerConfigSchema>;

const ModelOverrideSchema = z.object({
  id: z.string(),
  name: z.string().optional(),
  contextWindow: z.number().optional(),
  maxOutput: z.number().optional(),
  inputPrice: z.number().optional(),
  outputPrice: z.number().optional(),
  toolCalling: z.boolean().optional(),
  streaming: z.boolean().optional(),
});

const ProviderConfigSchema = z.object({
  type: z.enum(['anthropic', 'openai', 'gemini']),
  baseUrl: z.string().optional(),
  apiKeyEnv: z.string().optional(),
  apiKey: z.string().optional(),
  headers: z.record(z.string(), z.string()).optional(),
  models: z.array(ModelOverrideSchema).optional(),
});
export type ProviderConfig = z.infer<typeof ProviderConfigSchema>;

export const SettingsSchema = z
  .object({
    model: z.string().optional(),
    smallModel: z.string().optional(),
    effort: z.enum(['low', 'medium', 'high', 'xhigh', 'max']).optional(),
    maxOutputTokens: z.number().optional(),
    anthropicFallbacks: z.boolean().optional(),
    providers: z.record(z.string(), ProviderConfigSchema).optional(),
    modelAliases: z.record(z.string(), z.string()).optional(),
    permissions: z
      .object({
        defaultMode: PermissionModeSchema.optional(),
        allow: z.array(z.string()).optional(),
        deny: z.array(z.string()).optional(),
        ask: z.array(z.string()).optional(),
        additionalDirectories: z.array(z.string()).optional(),
        confidential: z.array(z.string()).optional(),
      })
      .optional(),
    hooks: z.record(z.string(), z.array(HookMatcherSchema)).optional(),
    mcpServers: z.record(z.string(), McpServerConfigSchema).optional(),
    ignore: z.array(z.string()).optional(),
    env: z.record(z.string(), z.string()).optional(),
    maxSubagents: z.number().int().positive().optional(),
    maxTurns: z.number().int().positive().optional(),
    autoCompactThreshold: z.number().min(0.1).max(0.99).optional(),
    webSearch: z.object({ provider: z.enum(['duckduckgo', 'brave', 'tavily']), apiKeyEnv: z.string().optional() }).optional(),
    shell: z.string().optional(),
    commandTimeoutMs: z.number().optional(),
    theme: z.enum(['dark', 'light']).optional(),
    enabledPlugins: z.array(z.string()).optional(),
  })
  .passthrough();
export type Settings = z.infer<typeof SettingsSchema>;

export type SettingsScope = 'user' | 'project' | 'local';

export function settingsFile(scope: SettingsScope, root: string): string {
  switch (scope) {
    case 'user':
      return path.join(stellaHome(), 'settings.json');
    case 'project':
      return path.join(root, '.stella', 'settings.json');
    case 'local':
      return path.join(root, '.stella', 'settings.local.json');
  }
}

export interface LoadedSettings {
  merged: Settings;
  layers: Record<SettingsScope, Settings>;
  errors: string[];
}

async function loadLayer(file: string, errors: string[]): Promise<Settings> {
  const raw = await readJson<unknown>(file, {});
  const r = SettingsSchema.safeParse(raw);
  if (!r.success) {
    errors.push(`${file}: ${r.error.issues.map((i) => `${i.path.join('.')}: ${i.message}`).join('; ')}`);
    return {};
  }
  return r.data;
}

/** Deep merge: objects merge, permission/ignore arrays concatenate, scalars override. */
export function mergeSettings(...layers: Settings[]): Settings {
  const out: Record<string, unknown> = {};
  for (const layer of layers) {
    for (const [k, v] of Object.entries(layer)) {
      if (v === undefined) continue;
      const prev = out[k];
      if (Array.isArray(v) && Array.isArray(prev)) out[k] = [...new Set([...prev, ...v])];
      else if (isObj(v) && isObj(prev)) out[k] = mergeSettings(prev as Settings, v as Settings);
      else out[k] = v;
    }
  }
  return out as Settings;
}

function isObj(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === 'object' && !Array.isArray(v);
}

export async function loadSettings(root: string, overrides: Settings = {}): Promise<LoadedSettings> {
  const errors: string[] = [];
  const user = await loadLayer(settingsFile('user', root), errors);
  const project = await loadLayer(settingsFile('project', root), errors);
  const local = await loadLayer(settingsFile('local', root), errors);
  return { merged: mergeSettings(user, project, local, overrides), layers: { user, project, local }, errors };
}

export async function updateSettings(scope: SettingsScope, root: string, mutate: (s: Settings) => Settings | void): Promise<void> {
  const file = settingsFile(scope, root);
  const current = await readJson<Settings>(file, {});
  const next = mutate(current) ?? current;
  await writeJson(file, next);
}

/** Credentials live in a separate 0600 file and never inside settings that may be committed. */
export function credentialsFile(): string {
  return path.join(stellaHome(), 'credentials.json');
}

export async function getCredential(name: string): Promise<string | undefined> {
  const creds = await readJson<Record<string, string>>(credentialsFile(), {});
  return creds[name];
}

export async function setCredential(name: string, value: string | null): Promise<void> {
  const creds = await readJson<Record<string, string>>(credentialsFile(), {});
  if (value === null) delete creds[name];
  else creds[name] = value;
  await writeJson(credentialsFile(), creds, 0o600);
}

import { promises as fs } from 'node:fs';
import path from 'node:path';
import { stellaHome } from '../config/paths.js';
import type { McpServerConfig, Settings } from '../config/settings.js';
import { readJson } from '../utils/fsutil.js';

export interface PluginManifest {
  name: string;
  version?: string;
  description?: string;
  skills?: string;
  commands?: string;
  agents?: string;
  hooks?: Settings['hooks'];
  mcpServers?: Record<string, McpServerConfig>;
}

export interface LoadedPlugin {
  manifest: PluginManifest;
  dir: string;
  scope: 'user' | 'project';
  enabled: boolean;
}

/**
 * Plugins bundle skills, slash commands, agents, hooks and MCP servers in one directory with a
 * plugin.json manifest. Locations: ~/.stella/plugins/<name>, <project>/.stella/plugins/<name>.
 */
export async function loadPlugins(root: string, settings: Settings, projectTrusted: boolean): Promise<LoadedPlugin[]> {
  const out: LoadedPlugin[] = [];
  const enabledList = settings.enabledPlugins;
  for (const [base, scope] of [
    [path.join(stellaHome(), 'plugins'), 'user'],
    [path.join(root, '.stella', 'plugins'), 'project'],
  ] as const) {
    let dirs: string[] = [];
    try {
      dirs = await fs.readdir(base);
    } catch {
      continue;
    }
    for (const d of dirs) {
      const dir = path.join(base, d);
      const manifest = await readJson<PluginManifest | null>(path.join(dir, 'plugin.json'), null);
      if (!manifest?.name) continue;
      const enabled = (scope === 'user' || projectTrusted) && (!enabledList || enabledList.includes(manifest.name));
      out.push({ manifest, dir, scope, enabled });
    }
  }
  return out;
}

export function pluginContributions(plugins: LoadedPlugin[]) {
  const skillDirs: string[] = [];
  const commandDirs: string[] = [];
  const agentDirs: string[] = [];
  const hooks: NonNullable<Settings['hooks']> = {};
  const mcpServers: Record<string, McpServerConfig> = {};
  for (const p of plugins.filter((x) => x.enabled)) {
    skillDirs.push(path.join(p.dir, p.manifest.skills ?? 'skills'));
    commandDirs.push(path.join(p.dir, p.manifest.commands ?? 'commands'));
    agentDirs.push(path.join(p.dir, p.manifest.agents ?? 'agents'));
    for (const [ev, list] of Object.entries(p.manifest.hooks ?? {})) {
      hooks[ev] = [...(hooks[ev] ?? []), ...list.map((m) => ({ ...m, hooks: m.hooks.map((h) => ({ ...h, command: h.command.replace(/\$\{PLUGIN_DIR\}/g, p.dir) })) }))];
    }
    for (const [name, cfg] of Object.entries(p.manifest.mcpServers ?? {})) {
      mcpServers[`${p.manifest.name}:${name}`] = { ...cfg, command: cfg.command?.replace(/\$\{PLUGIN_DIR\}/g, p.dir), args: cfg.args?.map((a) => a.replace(/\$\{PLUGIN_DIR\}/g, p.dir)) };
    }
  }
  return { skillDirs, commandDirs, agentDirs, hooks, mcpServers };
}

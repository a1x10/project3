import { promises as fs } from 'node:fs';
import path from 'node:path';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import { SSEClientTransport } from '@modelcontextprotocol/sdk/client/sse.js';
import { z } from 'zod';
import type { McpServerConfig } from '../config/settings.js';
import { truncate } from '../utils/fsutil.js';
import type { Tool, ToolResult } from '../tools/types.js';

export type McpStatus = 'pending' | 'connecting' | 'connected' | 'failed' | 'disabled' | 'untrusted';

export interface McpServerState {
  name: string;
  config: McpServerConfig;
  source: 'user' | 'project' | 'local' | 'mcp.json' | 'plugin';
  status: McpStatus;
  error?: string;
  tools: Array<{ name: string; description?: string; inputSchema?: Record<string, unknown>; readOnly?: boolean }>;
  client?: Client;
  transport?: { close(): Promise<void> };
  stderr?: string;
}

export function expandEnv(s: string): string {
  return s.replace(/\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}/g, (_m, name, def) => process.env[name] ?? def ?? '');
}

export async function loadMcpJson(root: string): Promise<Record<string, McpServerConfig>> {
  try {
    const j = JSON.parse(await fs.readFile(path.join(root, '.mcp.json'), 'utf8'));
    return j.mcpServers ?? {};
  } catch {
    return {};
  }
}

/** Connects to MCP servers (stdio, Streamable HTTP, legacy SSE) and exposes their tools. */
export class McpManager {
  private servers = new Map<string, McpServerState>();
  private onChange?: () => void;

  constructor(private readonly cwd: string) {}

  setOnChange(fn: () => void) {
    this.onChange = fn;
  }

  register(name: string, config: McpServerConfig, source: McpServerState['source'], trusted: boolean) {
    const disabled = config.enabled === false;
    this.servers.set(name, { name, config, source, status: disabled ? 'disabled' : !trusted ? 'untrusted' : 'pending', tools: [] });
  }

  list(): McpServerState[] {
    return [...this.servers.values()];
  }
  get(name: string) {
    return this.servers.get(name);
  }

  async connectAll(timeoutMs = 20_000): Promise<void> {
    await Promise.all(this.list().filter((s) => s.status === 'pending').map((s) => this.connect(s.name, timeoutMs).catch(() => {})));
  }

  async connect(name: string, timeoutMs = 20_000): Promise<McpServerState> {
    const s = this.servers.get(name);
    if (!s) throw new Error(`Unknown MCP server ${name}`);
    await this.disconnect(name);
    s.status = 'connecting';
    s.error = undefined;
    this.onChange?.();
    const cfg = s.config;
    const client = new Client({ name: 'stella-coder', version: '0.1.0' }, { capabilities: {} });
    try {
      const type = cfg.type ?? (cfg.url ? 'http' : 'stdio');
      let transport: any;
      if (type === 'stdio') {
        if (!cfg.command) throw new Error('stdio server requires "command"');
        const env: Record<string, string> = {};
        for (const [k, v] of Object.entries(process.env)) if (v !== undefined) env[k] = v;
        for (const [k, v] of Object.entries(cfg.env ?? {})) env[k] = expandEnv(v);
        transport = new StdioClientTransport({ command: expandEnv(cfg.command), args: (cfg.args ?? []).map(expandEnv), env, cwd: cfg.cwd ?? this.cwd, stderr: 'pipe' });
        const errStream = (transport as StdioClientTransport).stderr;
        errStream?.on('data', (d: Buffer) => {
          s.stderr = ((s.stderr ?? '') + d.toString()).slice(-4000);
        });
      } else {
        if (!cfg.url) throw new Error(`${type} server requires "url"`);
        const headers: Record<string, string> = {};
        for (const [k, v] of Object.entries(cfg.headers ?? {})) headers[k] = expandEnv(v);
        const url = new URL(expandEnv(cfg.url));
        transport = type === 'sse' ? new SSEClientTransport(url, { requestInit: { headers } }) : new StreamableHTTPClientTransport(url, { requestInit: { headers } });
      }
      await withTimeout(client.connect(transport), cfg.timeout ?? timeoutMs, `connect to ${name}`);
      const res = await withTimeout(client.listTools(), cfg.timeout ?? timeoutMs, `list tools of ${name}`);
      s.tools = res.tools.map((t: any) => ({ name: t.name, description: t.description, inputSchema: t.inputSchema, readOnly: t.annotations?.readOnlyHint === true }));
      s.client = client;
      s.transport = transport;
      s.status = 'connected';
    } catch (e) {
      s.status = 'failed';
      s.error = (e as Error).message + (s.stderr ? `\n${s.stderr.slice(-800)}` : '');
      try {
        await client.close();
      } catch {
        /* ignore */
      }
    }
    this.onChange?.();
    return s;
  }

  async disconnect(name: string) {
    const s = this.servers.get(name);
    if (!s?.client) return;
    try {
      await s.client.close();
    } catch {
      /* ignore */
    }
    s.client = undefined;
    s.transport = undefined;
    s.tools = [];
    s.status = 'pending';
  }

  async remove(name: string) {
    await this.disconnect(name);
    this.servers.delete(name);
    this.onChange?.();
  }

  async closeAll() {
    await Promise.all(this.list().map((s) => this.disconnect(s.name)));
  }

  async callTool(server: string, tool: string, args: Record<string, unknown>, signal?: AbortSignal): Promise<ToolResult> {
    const s = this.servers.get(server);
    if (!s?.client || s.status !== 'connected') return { content: `MCP server ${server} is not connected (${s?.status ?? 'unknown'}).`, isError: true };
    const res: any = await s.client.callTool({ name: tool, arguments: args }, undefined, { signal, timeout: 300_000 });
    const parts: string[] = [];
    for (const c of res.content ?? []) {
      if (c.type === 'text') parts.push(c.text);
      else if (c.type === 'image') parts.push(`[image ${c.mimeType}, ${Math.round((c.data?.length ?? 0) * 0.75)} bytes]`);
      else if (c.type === 'resource') parts.push(c.resource?.text ?? `[resource ${c.resource?.uri}]`);
      else if (c.type === 'resource_link') parts.push(`[resource link ${c.uri}]`);
      else parts.push(JSON.stringify(c));
    }
    if (res.structuredContent && !parts.length) parts.push(JSON.stringify(res.structuredContent, null, 2));
    return { content: truncate(parts.join('\n') || '(empty result)', 50_000), isError: !!res.isError };
  }

  /** Expose connected MCP tools as STELLA tools named mcp__<server>__<tool>. */
  tools(): Tool[] {
    const out: Tool[] = [];
    for (const s of this.list()) {
      if (s.status !== 'connected') continue;
      for (const t of s.tools) {
        const fullName = `mcp__${sanitize(s.name)}__${sanitize(t.name)}`.slice(0, 64);
        out.push({
          name: fullName,
          description: `[MCP ${s.name}] ${t.description ?? t.name}`.slice(0, 1024),
          schema: z.record(z.string(), z.any()),
          inputJsonSchema: (t.inputSchema as Record<string, unknown>) ?? { type: 'object', properties: {} },
          kind: t.readOnly ? 'read' : 'execute',
          concurrencySafe: !!t.readOnly,
          describe: () => ({ kind: t.readOnly ? 'read' : 'execute', risk: 'medium', readOnly: false, summary: `MCP ${s.name}.${t.name}` }),
          run: (input, ctx) => this.callTool(s.name, t.name, input as Record<string, unknown>, ctx.signal),
        });
      }
    }
    return out;
  }
}

function sanitize(s: string) {
  return s.replace(/[^A-Za-z0-9_-]/g, '_');
}

function withTimeout<T>(p: Promise<T>, ms: number, what: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error(`Timed out after ${ms}ms: ${what}`)), ms);
    p.then(
      (v) => {
        clearTimeout(t);
        resolve(v);
      },
      (e) => {
        clearTimeout(t);
        reject(e);
      },
    );
  });
}

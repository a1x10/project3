import { z } from 'zod';
import type { PermissionDescriptor, ToolKind } from '../permissions/engine.js';
import type { ToolSpec } from '../types.js';

export interface ToolDisplay {
  kind: 'diff' | 'text' | 'command' | 'files' | 'agent' | 'todo' | 'none';
  title?: string;
  body?: string;
  added?: number;
  removed?: number;
}

export interface ToolResult {
  content: string;
  isError?: boolean;
  display?: ToolDisplay;
  /** Files read/modified, used for UI and checkpoints. */
  filesRead?: string[];
  filesChanged?: string[];
}

/** Services the tools can use. Implemented by the Runtime (see agent/runtime.ts). */
export interface ToolServices {
  [key: string]: any;
}

export interface ToolContext {
  cwd: string;
  root: string;
  roots: string[];
  signal: AbortSignal;
  agentId: string;
  /** Current turn id (checkpoint grouping). */
  turnId: string;
  services: ToolServices;
  /** Stream partial output (stdout lines etc.) to the UI. */
  progress(text: string): void;
}

export interface Tool<I = any> {
  name: string;
  description: string;
  schema: z.ZodType<I>;
  kind: ToolKind;
  /** True if calls can run concurrently with other concurrency-safe calls. */
  concurrencySafe?: boolean;
  /** Hidden from the model unless enabled (e.g. platform specific). */
  isEnabled?(services: ToolServices): boolean;
  /** Raw JSON Schema (MCP tools). When set it is sent to the model instead of the zod schema. */
  inputJsonSchema?: Record<string, unknown>;
  describe(input: I, ctx: ToolContext): PermissionDescriptor | Promise<PermissionDescriptor>;
  run(input: I, ctx: ToolContext): Promise<ToolResult>;
}

export function defineTool<S extends z.ZodType>(t: Omit<Tool<z.infer<S>>, 'schema'> & { schema: S }): Tool<z.infer<S>> {
  return t as Tool<z.infer<S>>;
}

export function toolSpec(t: Tool): ToolSpec {
  if (t.inputJsonSchema) return { name: t.name, description: t.description, inputSchema: { type: 'object', properties: {}, ...t.inputJsonSchema } };
  const json = z.toJSONSchema(t.schema, { target: 'draft-7', unrepresentable: 'any' }) as Record<string, unknown>;
  delete json.$schema;
  if (json.type !== 'object') return { name: t.name, description: t.description, inputSchema: { type: 'object', properties: {} } };
  return { name: t.name, description: t.description, inputSchema: json };
}

export class ToolError extends Error {}

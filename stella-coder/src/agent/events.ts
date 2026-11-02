import type { ChatMessage, StopReason, Usage } from '../types.js';
import type { ToolDisplay } from '../tools/types.js';
import type { PermissionDescriptor } from '../permissions/engine.js';

/** Everything the agent does is published as events; the CLI (and tests) subscribe. */
export type AgentEvent =
  | { type: 'turn_start'; agentId: string; turnId: string; prompt: string }
  | { type: 'status'; agentId: string; text: string }
  | { type: 'text_delta'; agentId: string; text: string }
  | { type: 'text_reset'; agentId: string }
  | { type: 'tool_start'; agentId: string; id: string; name: string }
  | { type: 'tool_call'; agentId: string; id: string; name: string; input: Record<string, unknown>; summary: string }
  | { type: 'tool_progress'; agentId: string; id: string; text: string }
  | { type: 'tool_result'; agentId: string; id: string; name: string; content: string; isError: boolean; display?: ToolDisplay; durationMs: number; filesChanged?: string[]; filesRead?: string[] }
  | { type: 'permission'; agentId: string; tool: string; summary: string; decision: string; reason: string }
  | { type: 'assistant_message'; agentId: string; message: ChatMessage }
  | { type: 'usage'; agentId: string; model: string; usage: Usage; costUsd: number; contextTokens: number; contextWindow: number; servedModel?: string }
  | { type: 'compact'; agentId: string; beforeTokens: number; afterTokens: number; auto: boolean }
  | { type: 'notification'; agentId: string; level: 'info' | 'warn' | 'error'; text: string }
  | { type: 'subagent'; agentId: string; runId: string; name: string; description: string; status: string; toolCalls?: number }
  | { type: 'todos'; agentId: string; todos: Array<{ content: string; status: string; activeForm?: string }> }
  | { type: 'mode'; agentId: string; mode: string }
  | { type: 'turn_end'; agentId: string; turnId: string; stopReason: StopReason; text: string; turns: number };

export interface PermissionRequest {
  agentId: string;
  tool: string;
  input: Record<string, unknown>;
  descriptor: PermissionDescriptor;
  reason: string;
  suggestedRule: string;
}

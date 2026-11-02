/**
 * Provider-neutral conversation model used across STELLA.
 * Every provider adapter converts to/from these shapes.
 */

export interface TextBlock {
  type: 'text';
  text: string;
}

export interface ToolUseBlock {
  type: 'tool_use';
  id: string;
  name: string;
  input: Record<string, unknown>;
}

export interface ToolResultBlock {
  type: 'tool_result';
  toolUseId: string;
  content: string;
  isError?: boolean;
}

export interface ImageBlock {
  type: 'image';
  mediaType: string;
  data: string; // base64
}

export type ContentBlock = TextBlock | ToolUseBlock | ToolResultBlock | ImageBlock;

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: ContentBlock[];
  /**
   * Opaque, provider-specific copy of the assistant content exactly as it was returned
   * (e.g. Anthropic thinking blocks with signatures). Adapters of the same provider replay
   * it unchanged; other adapters fall back to `content`.
   */
  raw?: { provider: string; model: string; content: unknown[] };
  /** Marks synthetic messages (compaction summaries, reminders). */
  meta?: { kind?: 'compact-summary' | 'reminder' | 'command'; ts?: number };
}

export interface Usage {
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens?: number;
  cacheWriteTokens?: number;
}

export type StopReason = 'end_turn' | 'tool_use' | 'max_tokens' | 'refusal' | 'stop_sequence' | 'pause_turn' | 'error' | 'aborted';

export interface ToolSpec {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>; // JSON Schema object
}

export function textOf(msg: ChatMessage): string {
  return msg.content
    .filter((b): b is TextBlock => b.type === 'text')
    .map((b) => b.text)
    .join('');
}

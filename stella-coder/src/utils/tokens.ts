import type { ChatMessage, ContentBlock } from '../types.js';

/**
 * Fast token estimator. Exact counts come from provider usage reports; this heuristic is used
 * for planning (context-window gauge, compaction threshold) before a request is sent.
 * ~4 chars/token for English/code, CJK/Cyrillic weigh more.
 */
export function estimateTokens(text: string): number {
  if (!text) return 0;
  let ascii = 0;
  let other = 0;
  for (let i = 0; i < text.length; i++) {
    if (text.charCodeAt(i) < 128) ascii++;
    else other++;
  }
  return Math.ceil(ascii / 4 + other / 1.6);
}

export function estimateBlockTokens(b: ContentBlock): number {
  switch (b.type) {
    case 'text':
      return estimateTokens(b.text);
    case 'tool_use':
      return estimateTokens(b.name) + estimateTokens(JSON.stringify(b.input)) + 8;
    case 'tool_result':
      return estimateTokens(b.content) + 8;
    case 'image':
      return 1600;
  }
}

export function estimateMessagesTokens(messages: ChatMessage[]): number {
  let n = 0;
  for (const m of messages) {
    n += 4;
    for (const b of m.content) n += estimateBlockTokens(b);
  }
  return n;
}

#!/usr/bin/env node
// Stella WhatsApp MCP server (stdio, newline-delimited JSON-RPC 2.0).
// The WhatsApp connection itself lives in the Stella Cloud server; this process only
// forwards tool calls to it:  STELLA_URL (e.g. http://127.0.0.1:8787) + STELLA_TOKEN.
const URL_BASE = (process.env.STELLA_URL || 'http://127.0.0.1:8787').replace(/\/$/, '');
const TOKEN = process.env.STELLA_TOKEN || '';

const TOOLS = [
  {
    name: 'list_chats',
    description: "List the user's WhatsApp chats (most recent first) with contact names and the last message. Use it to find the right contact (e.g. the user's wife may be saved as 'Жена', 'Любимая', a first name…).",
    inputSchema: { type: 'object', properties: { query: { type: 'string', description: 'Optional part of a name to filter by' }, limit: { type: 'number' } } }
  },
  {
    name: 'read_chat',
    description: 'Read recent messages of one WhatsApp chat. "me" = the user.',
    inputSchema: { type: 'object', properties: { contact: { type: 'string', description: 'Contact/chat name, phone number or JID' }, limit: { type: 'number', description: 'How many last messages (default 40)' } }, required: ['contact'] }
  },
  {
    name: 'writing_style',
    description: "Examples of messages the USER wrote (optionally to a specific contact). Read them before writing on the user's behalf and imitate the style exactly (language, length, punctuation, emoji, slang, capitalization).",
    inputSchema: { type: 'object', properties: { contact: { type: 'string' } } }
  },
  {
    name: 'send_message',
    description: "Send a WhatsApp message from the user's account. ONLY use when the user explicitly asked to message this person. Write it in the user's own style. If a reply is expected, Stella forwards the answer to the user's phone/PC automatically.",
    inputSchema: { type: 'object', properties: { contact: { type: 'string' }, text: { type: 'string' }, expect_reply: { type: 'boolean', description: 'Default true' } }, required: ['contact', 'text'] }
  },
  {
    name: 'wait_for_reply',
    description: 'Wait for the next incoming message in a chat (long-poll). Returns null on timeout — then tell the user you will forward the answer when it comes.',
    inputSchema: { type: 'object', properties: { contact: { type: 'string' }, timeout_seconds: { type: 'number', description: 'Default 300, max 900' } }, required: ['contact'] }
  }
];

async function call(name, args) {
  const r = await fetch(URL_BASE + '/api/mcp/' + name, {
    method: 'POST',
    headers: { 'content-type': 'application/json', authorization: 'Bearer ' + TOKEN },
    body: JSON.stringify(args || {}),
    signal: AbortSignal.timeout(960000)
  });
  const j = await r.json().catch(() => ({ error: 'bad response ' + r.status }));
  if (!r.ok || j.error) throw new Error(j.error || ('HTTP ' + r.status));
  return j.result;
}

function reply(id, result) { process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id, result }) + '\n'); }
function fail(id, code, message) { process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id, error: { code, message } }) + '\n'); }

async function onMessage(msg) {
  const { id, method, params } = msg;
  if (method === 'initialize') {
    return reply(id, {
      protocolVersion: (params && params.protocolVersion) || '2025-06-18',
      capabilities: { tools: {} },
      serverInfo: { name: 'stella-whatsapp', version: '1.0.0' }
    });
  }
  if (method === 'notifications/initialized' || (method && method.startsWith('notifications/'))) return;
  if (method === 'ping') return reply(id, {});
  if (method === 'tools/list') return reply(id, { tools: TOOLS });
  if (method === 'tools/call') {
    const name = params && params.name;
    if (!TOOLS.some(t => t.name === name)) return fail(id, -32602, 'unknown tool ' + name);
    try {
      const result = await call(name, (params && params.arguments) || {});
      return reply(id, { content: [{ type: 'text', text: typeof result === 'string' ? result : JSON.stringify(result, null, 2) }] });
    } catch (e) {
      return reply(id, { content: [{ type: 'text', text: 'Error: ' + e.message }], isError: true });
    }
  }
  if (id !== undefined) fail(id, -32601, 'method not found: ' + method);
}

let buf = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', d => {
  buf += d;
  let i;
  while ((i = buf.indexOf('\n')) >= 0) {
    const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
    if (!line) continue;
    let msg; try { msg = JSON.parse(line); } catch { continue; }
    inflight++;
    onMessage(msg).catch(e => { if (msg.id !== undefined) fail(msg.id, -32603, e.message); }).finally(() => { inflight--; if (ended && !inflight) process.exit(0); });
  }
});
let inflight = 0, ended = false;
process.stdin.on('end', () => { ended = true; if (!inflight) process.exit(0); });

#!/usr/bin/env node
// Stella desktop MCP server (stdio). A resident process: every tool call is one local HTTP request
// to Stella (127.0.0.1, token from bridge.json) — no PowerShell/cmd start per action, screenshots come back inline.
const fs = require('fs');
const path = require('path');
const os = require('os');
const http = require('http');

const BRIDGE = process.env.STELLA_BRIDGE || path.join(process.env.APPDATA || os.homedir(), 'agy-desktop', 'bridge.json');
const shot = { type: 'boolean', description: 'Return a fresh screenshot in the same call (saves a round-trip).' };
const xy = { x: { type: 'number' }, y: { type: 'number' } };
const TOOLS = [
  { name: 'list_elements', description: 'FASTEST way to act: list buttons, fields, links, menu items of the active window (Windows UI Automation) with names and positions. Then use click_element. No screenshot needed.', inputSchema: { type: 'object', properties: {} } },
  { name: 'click_element', description: 'Click a UI element of the active window by its name (or index from list_elements).', inputSchema: { type: 'object', properties: { name: { type: 'string' }, index: { type: 'number' }, double: { type: 'boolean' }, button: { type: 'string', enum: ['left', 'right'] }, screenshot: shot } } },
  { name: 'screenshot', description: "Screenshot of the user's real screen, returned as an image. Coordinates in other tools use this image's pixels.", inputSchema: { type: 'object', properties: {} } },
  { name: 'click', description: 'Click at image coordinates.', inputSchema: { type: 'object', properties: Object.assign({}, xy, { button: { type: 'string', enum: ['left', 'right'] }, double: { type: 'boolean' }, screenshot: shot }), required: ['x', 'y'] } },
  { name: 'type_text', description: 'Type text into the focused field (any language). enter:true presses Enter after.', inputSchema: { type: 'object', properties: { text: { type: 'string' }, enter: { type: 'boolean' }, screenshot: shot }, required: ['text'] } },
  { name: 'press_keys', description: 'Press a key or combination, e.g. "enter", "ctrl+s", "alt+tab", "win+d", "ctrl+shift+t".', inputSchema: { type: 'object', properties: { keys: { type: 'string' }, screenshot: shot }, required: ['keys'] } },
  { name: 'scroll', description: 'Scroll at a point. amount > 0 scrolls down, < 0 up (notches).', inputSchema: { type: 'object', properties: Object.assign({}, xy, { amount: { type: 'number' }, screenshot: shot }), required: ['x', 'y'] } },
  { name: 'drag', description: 'Drag with the left mouse button.', inputSchema: { type: 'object', properties: { x1: { type: 'number' }, y1: { type: 'number' }, x2: { type: 'number' }, y2: { type: 'number' }, screenshot: shot }, required: ['x1', 'y1', 'x2', 'y2'] } },
  { name: 'move', description: 'Move the mouse.', inputSchema: { type: 'object', properties: Object.assign({}, xy, { screenshot: shot }), required: ['x', 'y'] } },
  { name: 'wait', description: 'Wait (ms, max 15000), e.g. for an app to open.', inputSchema: { type: 'object', properties: { ms: { type: 'number' }, screenshot: shot } } },
  { name: 'actions', description: 'Run several steps in ONE call: steps = [{"action":"click","x":..,"y":..}, {"action":"type_text","text":"..","enter":true}, {"action":"press_keys","keys":"ctrl+s"}, {"action":"click_element","name":"OK"}, {"action":"wait","ms":500}]. Optional pause_ms per step. screenshot:true returns the final screen.', inputSchema: { type: 'object', properties: { steps: { type: 'array', items: { type: 'object' } }, screenshot: shot }, required: ['steps'] } },
  { name: 'open', description: "Open a file, folder or URL on the user's real screen with its default app.", inputSchema: { type: 'object', properties: { target: { type: 'string' } }, required: ['target'] } },
  { name: 'browser', description: 'Make sure the agent Chrome is open on the user screen (optionally at a URL). Then use the stella-browser tools.', inputSchema: { type: 'object', properties: { url: { type: 'string' } } } }
];

function bridge() { return JSON.parse(fs.readFileSync(BRIDGE, 'utf8')); }
function callStella(tool, args) {
  return new Promise((resolve, reject) => {
    let b; try { b = bridge(); } catch { return reject(new Error('Stella is not running (no bridge). Ask the user to open Stella.')); }
    const body = JSON.stringify({ tool, args });
    const req = http.request({ host: '127.0.0.1', port: b.port, path: '/call', method: 'POST', headers: { authorization: 'Bearer ' + b.token, 'content-type': 'application/json', 'content-length': Buffer.byteLength(body) }, timeout: 120000 }, res => {
      let d = ''; res.setEncoding('utf8'); res.on('data', c => d += c);
      res.on('end', () => { try { resolve(JSON.parse(d)); } catch { reject(new Error('bad answer from Stella (' + res.statusCode + ')')); } });
    });
    req.on('error', e => reject(new Error('Stella is not reachable: ' + e.message)));
    req.on('timeout', () => req.destroy(new Error('timeout')));
    req.end(body);
  });
}

const out = o => process.stdout.write(JSON.stringify(o) + '\n');
async function onMessage(m) {
  if (m.method === 'initialize') return out({ jsonrpc: '2.0', id: m.id, result: { protocolVersion: (m.params && m.params.protocolVersion) || '2025-06-18', capabilities: { tools: {} }, serverInfo: { name: 'stella-desktop', version: '2.0.0' } } });
  if (!m.method || m.method.startsWith('notifications/')) return;
  if (m.method === 'ping') return out({ jsonrpc: '2.0', id: m.id, result: {} });
  if (m.method === 'tools/list') return out({ jsonrpc: '2.0', id: m.id, result: { tools: TOOLS } });
  if (m.method === 'tools/call') {
    const { name, arguments: args } = m.params || {};
    try {
      const r = await callStella(name, args || {});
      const content = [{ type: 'text', text: String(r.text || (r.ok ? 'ok' : 'error')) }];
      if (r.image && r.image.data) content.push({ type: 'image', data: r.image.data, mimeType: r.image.mime || 'image/jpeg' });
      return out({ jsonrpc: '2.0', id: m.id, result: { content, isError: !r.ok } });
    } catch (e) {
      return out({ jsonrpc: '2.0', id: m.id, result: { content: [{ type: 'text', text: 'Error: ' + e.message }], isError: true } });
    }
  }
  if (m.id !== undefined) out({ jsonrpc: '2.0', id: m.id, error: { code: -32601, message: 'method not found' } });
}

let buf = '', inflight = 0, ended = false;
process.stdin.setEncoding('utf8');
process.stdin.on('data', d => {
  buf += d; let i;
  while ((i = buf.indexOf('\n')) >= 0) {
    const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
    if (!line) continue;
    let m; try { m = JSON.parse(line); } catch { continue; }
    inflight++;
    onMessage(m).finally(() => { inflight--; if (ended && !inflight) process.exit(0); });
  }
});
process.stdin.on('end', () => { ended = true; if (!inflight) process.exit(0); });

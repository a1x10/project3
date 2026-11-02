// Minimal real MCP server used by tests (stdio by default, Streamable HTTP with --http <port>).
import http from 'node:http';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { z } from 'zod';

function build() {
  const server = new McpServer({ name: 'calc', version: '1.0.0' });
  server.registerTool('add', { description: 'Add two numbers', inputSchema: { a: z.number(), b: z.number() } }, async ({ a, b }) => ({ content: [{ type: 'text', text: String(a + b) }] }));
  server.registerTool('fail', { description: 'Always fails', inputSchema: {} }, async () => ({ isError: true, content: [{ type: 'text', text: 'boom' }] }));
  return server;
}

const idx = process.argv.indexOf('--http');
if (idx > 0) {
  const port = Number(process.argv[idx + 1] ?? 0);
  const srv = http.createServer(async (req, res) => {
    if (req.headers.authorization !== 'Bearer secret-token') {
      res.writeHead(401).end('unauthorized');
      return;
    }
    const chunks = [];
    for await (const c of req) chunks.push(c);
    const body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString()) : undefined;
    const server = build();
    const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
    res.on('close', () => {
      transport.close();
      server.close();
    });
    await server.connect(transport);
    await transport.handleRequest(req, res, body);
  });
  srv.listen(port, '127.0.0.1', () => process.stdout.write(`LISTENING ${srv.address().port}\n`));
} else {
  await build().connect(new StdioServerTransport());
}

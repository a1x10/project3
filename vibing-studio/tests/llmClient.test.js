import http from "node:http";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { buildRequest, parseChunk, streamChat } from "../src/llmClient.js";

const msgs = [
  { role: "system", content: "SYS" },
  { role: "user", content: "hi" },
];

describe("buildRequest", () => {
  it("OpenAI format, bearer key, usage in stream", () => {
    const target = { url: "https://ai.example.com/v1/chat/completions", model: "auto", apiKey: "sk-stella-k" };
    const { url, init } = buildRequest({ target, messages: msgs, maxTokens: 100, temperature: 0.7 });
    const body = JSON.parse(init.body);
    expect(url).toBe(target.url);
    expect(init.headers.Authorization).toBe("Bearer sk-stella-k");
    expect(body).toMatchObject({ model: "auto", stream: true, max_tokens: 100, temperature: 0.7, stream_options: { include_usage: true } });
    expect(body.messages[0]).toEqual({ role: "system", content: "SYS" });
  });
});

describe("parseChunk", () => {
  it("reads tokens, usage and errors", () => {
    expect(parseChunk({ choices: [{ delta: { content: "a" } }] }).token).toBe("a");
    expect(parseChunk({ choices: [], usage: { prompt_tokens: 5, completion_tokens: 7 } }).usage).toEqual({ input: 5, output: 7 });
    expect(parseChunk({ error: { message: "rate limited" } }).error).toBe("rate limited");
  });
});

describe("streaming against a real HTTP server", () => {
  let srv;
  let base = "";
  beforeAll(async () => {
    srv = http.createServer(async (req, res) => {
      for await (const _ of req);
      if (req.headers.authorization !== "Bearer sk-stella-ok") {
        res.writeHead(429, { "content-type": "application/json" }).end(JSON.stringify({ error: { message: "Дневной лимит запросов исчерпан" } }));
        return;
      }
      res.writeHead(200, { "content-type": "text/event-stream", "x-routed-via": "groq/llama-3.3-70b-versatile" });
      for (const w of ["Привет", ", ", "мир"]) res.write(`data: ${JSON.stringify({ choices: [{ delta: { content: w } }] })}\n\n`);
      res.write(`data: ${JSON.stringify({ choices: [], usage: { prompt_tokens: 11, completion_tokens: 3 } })}\n\n`);
      res.end("data: [DONE]\n\n");
    });
    await new Promise((r) => srv.listen(0, "127.0.0.1", r));
    base = `http://127.0.0.1:${srv.address().port}`;
  });
  afterAll(() => srv.close());

  it("streams tokens, reports usage and the routed model", async () => {
    const parts = [];
    const r = await streamChat({ target: { url: `${base}/v1/chat/completions`, model: "auto", apiKey: "sk-stella-ok" }, messages: msgs, maxTokens: 10, onToken: (t) => parts.push(t) });
    expect(r.text).toBe("Привет, мир");
    expect(parts).toEqual(["Привет", "Привет, ", "Привет, мир"]);
    expect(r.usage).toEqual({ input: 11, output: 3 });
    expect(r.routedVia).toBe("groq/llama-3.3-70b-versatile");
  });
  it("surfaces HTTP status and the server message", async () => {
    const err = await streamChat({ target: { url: `${base}/v1/chat/completions`, model: "auto", apiKey: "bad" }, messages: msgs, maxTokens: 5 }).catch((e) => e);
    expect(err.status).toBe(429);
    expect(err.detail).toContain("лимит");
  });
  it("reports unreachable servers clearly", async () => {
    await expect(streamChat({ target: { url: "http://127.0.0.1:9/v1/chat/completions", model: "auto", apiKey: "x" }, messages: msgs, maxTokens: 5 })).rejects.toThrow(/нет соединения/);
  });
});

import http from "node:http";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { buildRequest, listModels, parseChunk, resolveTarget, streamChat, testConnection } from "../src/llmClient.js";
import { getPreset } from "../src/providerStore.js";

const msgs = [
  { role: "system", content: "SYS" },
  { role: "user", content: "hi" },
];

describe("buildRequest", () => {
  it("FreeLLMAPI: OpenAI format, bearer key, proxied URL, usage in stream", () => {
    const preset = getPreset("freellmapi");
    const target = resolveTarget(preset, { apiKey: "freellmapi-k", model: "" });
    expect(target).toEqual({ url: "/llm/v1/chat/completions", model: "auto:smart", apiKey: "freellmapi-k" });
    const { url, init } = buildRequest({ preset, target, messages: msgs, maxTokens: 100, temperature: 0.7 });
    const body = JSON.parse(init.body);
    expect(url).toBe("/llm/v1/chat/completions");
    expect(init.headers.Authorization).toBe("Bearer freellmapi-k");
    expect(body).toMatchObject({ model: "auto:smart", stream: true, max_tokens: 100, temperature: 0.7, stream_options: { include_usage: true } });
    expect(body.messages[0]).toEqual({ role: "system", content: "SYS" });
  });
  it("Anthropic: native Messages body with separate system and browser header", () => {
    const preset = getPreset("anthropic");
    const target = resolveTarget(preset, { apiKey: "sk-ant-x" });
    const { init } = buildRequest({ preset, target, messages: [...msgs, { role: "user", content: "again" }], maxTokens: 50, temperature: 0.7 });
    const body = JSON.parse(init.body);
    expect(init.headers["x-api-key"]).toBe("sk-ant-x");
    expect(init.headers["anthropic-dangerous-direct-browser-access"]).toBe("true");
    expect(body.system).toBe("SYS");
    expect(body.messages).toEqual([{ role: "user", content: "hi\n\nagain" }]);
    expect(body.temperature).toBeUndefined();
    expect(body.model).toBe("claude-sonnet-5-5");
  });
  it("OpenAI: max_completion_tokens and no temperature for gpt-5", () => {
    const preset = getPreset("openai");
    const { init } = buildRequest({ preset, target: resolveTarget(preset, { apiKey: "k" }), messages: msgs, maxTokens: 10, temperature: 0.3 });
    const body = JSON.parse(init.body);
    expect(body.max_completion_tokens).toBe(10);
    expect(body.max_tokens).toBeUndefined();
    expect(body.temperature).toBeUndefined();
  });
  it("local server uses the URL from the chat header", () => {
    expect(resolveTarget(getPreset("local"), {}, "http://127.0.0.1:9000/").url).toBe("http://127.0.0.1:9000/v1/chat/completions");
  });
});

describe("parseChunk", () => {
  it("understands OpenAI, Anthropic and the local server", () => {
    expect(parseChunk({ choices: [{ delta: { content: "a" } }] }).token).toBe("a");
    expect(parseChunk({ type: "content_block_delta", delta: { type: "text_delta", text: "b" } }).token).toBe("b");
    expect(parseChunk({ token: "c" }).token).toBe("c");
    expect(parseChunk({ choices: [], usage: { prompt_tokens: 5, completion_tokens: 7 } }).usage).toEqual({ input: 5, output: 7 });
    expect(parseChunk({ error: { message: "rate limited" } }).error).toBe("rate limited");
  });
});

describe("streaming against a real HTTP server (FreeLLMAPI wire format)", () => {
  let srv;
  let base = "";
  const seen = [];
  beforeAll(async () => {
    srv = http.createServer(async (req, res) => {
      let b = "";
      for await (const c of req) b += c;
      seen.push({ url: req.url, auth: req.headers.authorization, body: b ? JSON.parse(b) : null });
      if (req.url === "/v1/models") {
        res.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify({ data: [{ id: "auto" }, { id: "glm-5.3:free" }] }));
        return;
      }
      if (req.headers.authorization !== "Bearer freellmapi-ok") {
        res.writeHead(401, { "content-type": "application/json" }).end(JSON.stringify({ error: { message: "invalid key" } }));
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
    const preset = getPreset("freellmapi");
    const target = resolveTarget(preset, { apiKey: "freellmapi-ok", customUrl: `${base}/v1/chat/completions` });
    const parts = [];
    const r = await streamChat({ preset, target, messages: msgs, maxTokens: 10, onToken: (t) => parts.push(t) });
    expect(r.text).toBe("Привет, мир");
    expect(parts).toEqual(["Привет", "Привет, ", "Привет, мир"]);
    expect(r.usage).toEqual({ input: 11, output: 3 });
    expect(r.routedVia).toBe("groq/llama-3.3-70b-versatile");
    expect(await listModels(preset, target)).toEqual(["auto", "glm-5.3:free"]);
    const t = await testConnection(preset, target);
    expect(t.ok).toBe(true);
  });
  it("surfaces HTTP errors with the server message", async () => {
    const preset = getPreset("freellmapi");
    const target = resolveTarget(preset, { apiKey: "wrong", customUrl: `${base}/v1/chat/completions` });
    await expect(streamChat({ preset, target, messages: msgs, maxTokens: 5 })).rejects.toThrow(/HTTP 401: invalid key/);
  });
  it("reports unreachable servers clearly", async () => {
    const preset = getPreset("freellmapi");
    const target = resolveTarget(preset, { apiKey: "x", customUrl: "http://127.0.0.1:9/v1/chat/completions" });
    await expect(streamChat({ preset, target, messages: msgs, maxTokens: 5 })).rejects.toThrow(/нет соединения/);
  });
});

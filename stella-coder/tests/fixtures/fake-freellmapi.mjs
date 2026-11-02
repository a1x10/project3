// Fake FreeLLMAPI router implementing the endpoints the installer and STELLA use.
import http from "node:http";
import fs from "node:fs";
const port = Number(process.env.PORT || 3001);
const stateFile = process.env.FAKE_STATE;
const load = () => { try { return JSON.parse(fs.readFileSync(stateFile, "utf8")); } catch { return { users: [], keys: [] }; } };
const save = (s) => stateFile && fs.writeFileSync(stateFile, JSON.stringify(s));
const UNIFIED = "freellmapi-fake-unified-key";
const sessions = new Set();
const SETUP_CODE = "ABCD-1234";
if (process.env.FAKE_REQUIRE_CODE) console.log(`\n  First-run setup code: ${SETUP_CODE}\n`);
const PROVIDERS = [
  { platform: "kilo", name: "Kilo Gateway", kind: "chat", keyless: true },
  { platform: "ovh", name: "OVH AI Endpoints", kind: "chat", keyless: true },
  { platform: "groq", name: "Groq", kind: "chat", keyless: false },
  { platform: "brave", name: "Brave Search", kind: "search", keyless: true },
];
const send = (res, code, obj) => res.writeHead(code, { "content-type": "application/json" }).end(JSON.stringify(obj));
http.createServer(async (req, res) => {
  let b = "";
  for await (const c of req) b += c;
  const body = b ? JSON.parse(b) : {};
  const st = load();
  const bearer = (req.headers.authorization || "").replace(/^Bearer\s+/i, "");
  const url = req.url.split("?")[0];
  if (url === "/api/ping") return send(res, 200, { status: "ok", timestamp: new Date().toISOString() });
  if (url === "/api/auth/status") {
    if (process.env.FAKE_HTML_STATUS) return res.writeHead(200, { "content-type": "text/html" }).end("<!doctype html><html><body>dashboard</body></html>");
    return send(res, 200, { needsSetup: st.users.length === 0, authenticated: sessions.has(bearer) });
  }
  if (url === "/api/auth/setup" && req.method === "POST") {
    if (st.users.length) return send(res, 409, { error: { message: "Setup already completed. Use login instead." } });
    if (process.env.FAKE_REQUIRE_CODE && body.setupCode !== SETUP_CODE)
      return send(res, 403, { error: { message: "A setup code is required to create the first account from a remote device. Check the server logs for the code, or open the dashboard from a browser on the machine running FreeLLMAPI.", type: "setup_code_required" } });
    if (!/@/.test(body.email || "") || (body.password || "").length < 8) return send(res, 400, { error: { message: "bad signup" } });
    st.users.push({ email: body.email, password: body.password }); save(st);
    const t = "sess-" + Math.random(); sessions.add(t); return send(res, 201, { token: t, email: body.email });
  }
  if (url === "/api/auth/login" && req.method === "POST") {
    if (!st.users.some((u) => u.email === body.email && u.password === body.password)) return send(res, 401, { error: { message: "Invalid email or password" } });
    const t = "sess-" + Math.random(); sessions.add(t); return send(res, 200, { token: t, email: body.email });
  }
  if (url.startsWith("/api/")) {
    if (!sessions.has(bearer)) return send(res, 401, { error: { message: "auth required" } });
    if (url === "/api/settings/api-key") return send(res, 200, { apiKey: UNIFIED });
    if (url === "/api/keys/providers") return send(res, 200, { providers: PROVIDERS.map((p) => ({ ...p, configured: st.keys.some((k) => k.platform === p.platform) })) });
    if (url === "/api/keys" && req.method === "POST") { st.keys.push({ platform: body.platform, key: body.key || "no-key" }); save(st); return send(res, 201, { ok: true }); }
    return send(res, 404, { error: { message: "nope" } });
  }
  if (url.startsWith("/v1/")) {
    if (bearer !== UNIFIED) return send(res, 401, { error: { message: "invalid unified key" } });
    if (url === "/v1/models") return send(res, 200, { data: [{ id: "auto:smart" }] });
    if (url === "/v1/chat/completions") {
      res.writeHead(200, { "content-type": "text/event-stream", "x-routed-via": "kilo/fake-free-model" });
      res.write(`data: ${JSON.stringify({ choices: [{ delta: { content: "router says hi" } }] })}\n\n`);
      res.write(`data: ${JSON.stringify({ choices: [{ delta: {}, finish_reason: "stop" }] })}\n\n`);
      return res.end("data: [DONE]\n\n");
    }
  }
  send(res, 404, { error: { message: "not found" } });
}).listen(port, "127.0.0.1");

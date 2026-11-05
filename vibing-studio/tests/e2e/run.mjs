// End-to-end: the real Stella Cloud server (../cloud/server) + a fake Telegram Bot API + a fake
// model server, driven through the built Studio UI — in Chromium (default) or in the Electron
// desktop app (E2E_ELECTRON=1; on Linux run under xvfb-run).
// Usage: npm run build && npm run e2e
import http from "node:http";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const pw = require(process.env.PLAYWRIGHT_PATH || "playwright");
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const serverDir = path.resolve(root, "../cloud/server");
const shots = path.join(root, "test-results");
fs.mkdirSync(shots, { recursive: true });
const ELECTRON = process.env.E2E_ELECTRON === "1";

const SITE = `Вот сайт:
\`\`\`html
<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><title>Кофейня</title>
<style>body{font-family:sans-serif;background:#1b1410;color:#f5e6d3;margin:0}header{padding:48px;text-align:center}h1{font-size:44px;margin:0}section{padding:24px 48px}.card{background:#2a1f18;border-radius:16px;padding:20px;margin:12px 0}</style></head>
<body>
<header><h1 id="title">Кофейня Тест</h1><p>Свежая обжарка каждый день</p></header>
<section><div class="card">Эспрессо — 150 ₽</div><div class="card">Капучино — 220 ₽</div></section>
</body></html>
\`\`\`
Тёплый лендинг кофейни.`;
const EDIT = `Меняю заголовок.
<<<<<<< SEARCH
<h1 id="title">Кофейня Тест</h1>
=======
<h1 id="title">Кофейня Обновлено</h1>
>>>>>>> REPLACE
Готово: заголовок обновлён.`;

const PRO_SPEC = {
  template: "warm-bistro",
  brand: "Зерно Казань",
  palette: { bg: "#140d09", surface: "#231811", text: "#fbf1e6", muted: "#c7ab92", accent: "#d4a373", accent2: "#f4d6a0" },
  hero: { eyebrow: "Кофейня в центре Казани", title: "Кофе, ради которого просыпаются", highlight: "просыпаются", subtitle: "Своя обжарка и свежая выпечка.", cta: "Забронировать", cta2: "Меню" },
  stats: [{ value: "12", label: "сортов" }],
  features: { title: "Почему мы", items: [{ icon: "coffee", title: "Своя обжарка", text: "Каждую неделю." }] },
  contact: { title: "Ждём вас", phone: "+7 843 000-00-00", address: "Казань, ул. Баумана, 1" },
  sections: ["stats", "features", "contact"],
};
const PRO_SITE = "```json\n" + JSON.stringify(PRO_SPEC) + "\n```\nСобрал сайт кофейни на шаблоне Warm Bistro.";
const PRO_EDIT = "```json\n" + JSON.stringify({ ...PRO_SPEC, hero: { ...PRO_SPEC.hero, title: "Лучший кофе Казани", highlight: "Казани" } }) + "\n```\nОбновил заголовок.";

const readBody = async (req) => {
  let b = "";
  for await (const c of req) b += c;
  try {
    return b ? JSON.parse(b) : {};
  } catch {
    return {};
  }
};
const listen = (srv) => new Promise((r) => srv.listen(0, "127.0.0.1", () => r(`http://127.0.0.1:${srv.address().port}`)));

// ---- fake model server (stands in for FreeLLMAPI)
const upstreamRequests = [];
const upstream = http.createServer(async (req, res) => {
  const body = await readBody(req);
  if (req.headers.authorization !== "Bearer router-key") return res.writeHead(401).end("{}");
  if (req.url === "/v1/models") return res.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify({ data: [{ id: "auto" }, { id: "auto:smart" }] }));
  upstreamRequests.push(body);
  const sys = body.messages.map((m) => (m.role === "system" ? m.content : "")).join("\n");
  const pro = sys.includes("арт-директор");
  const text = pro ? (sys.includes("ТЕКУЩИЙ JSON САЙТА") ? PRO_EDIT : PRO_SITE) : sys.includes("ТЕКУЩИЙ КОД САЙТА") ? EDIT : SITE;
  res.writeHead(200, { "content-type": "text/event-stream", "x-routed-via": "groq/llama-3.3-70b-versatile" });
  for (let i = 0; i < text.length; i += 40) {
    res.write(`data: ${JSON.stringify({ choices: [{ delta: { content: text.slice(i, i + 40) } }] })}\n\n`);
    await new Promise((r) => setTimeout(r, 5));
  }
  res.write(`data: ${JSON.stringify({ choices: [], usage: { prompt_tokens: 900, completion_tokens: 300 } })}\n\n`);
  res.end("data: [DONE]\n\n");
});

// ---- fake Telegram Bot API
const tgSent = [];
const tgQueue = [];
let tgWaiter = null;
let updateId = 1;
const telegram = http.createServer(async (req, res) => {
  const method = req.url.split("/").pop();
  const params = await readBody(req);
  const reply = (result) => !res.headersSent && res.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify({ ok: true, result }));
  if (method === "getMe") return reply({ id: 1, is_bot: true, username: "stella_e2e_bot" });
  if (method === "getUpdates") {
    const take = () => {
      tgWaiter = null;
      reply(tgQueue.splice(0));
    };
    if (tgQueue.length) return take();
    const t = setTimeout(take, 300);
    tgWaiter = () => (clearTimeout(t), take());
    return;
  }
  tgSent.push({ method, params });
  reply(method === "sendMessage" ? { message_id: tgSent.length } : true);
});
const tgPush = (u) => {
  tgQueue.push({ update_id: updateId++, ...u });
  tgWaiter?.();
};
const from = { id: 5150, first_name: "Анна", username: "anna", is_bot: false };
const say = (text) => tgPush({ message: { message_id: updateId, from, chat: { id: from.id, type: "private" }, text } });
const press = (data) => tgPush({ callback_query: { id: `cb${updateId}`, from, data, message: { message_id: 1, chat: { id: from.id, type: "private" } } } });
async function waitTg(pred, ms = 8000) {
  const end = Date.now() + ms;
  for (;;) {
    const m = tgSent.find(pred);
    if (m) return m;
    if (Date.now() > end) throw new Error("telegram: timeout; sent=" + JSON.stringify(tgSent.map((s) => s.params.text)));
    await new Promise((r) => setTimeout(r, 50));
  }
}

const upstreamUrl = await listen(upstream);
const tgUrl = await listen(telegram);

// ---- the real Stella Cloud server
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "studio-e2e-"));
const cloudPort = 18000 + Math.floor(Math.random() * 1000);
const cloudUrl = `http://127.0.0.1:${cloudPort}`;
const cloud = spawn(process.execPath, ["--disable-warning=ExperimentalWarning", "--import", "tsx", "src/main.ts"], {
  cwd: serverDir,
  env: {
    ...process.env,
    PORT: String(cloudPort),
    HOST: "127.0.0.1",
    PUBLIC_URL: cloudUrl,
    DATABASE_PATH: path.join(tmp, "cloud.db"),
    TELEGRAM_BOT_TOKEN: "E2E",
    TELEGRAM_API_URL: tgUrl,
    ADMIN_TELEGRAM_IDS: "1",
    UPSTREAM_BASE_URL: `${upstreamUrl}/v1`,
    UPSTREAM_API_KEY: "router-key",
    SYSTEM_PROMPT: "OWNER-PROMPT: ты ассистент Stella.",
  },
  stdio: ["ignore", "pipe", "pipe"],
});
let cloudLog = "";
cloud.stdout.on("data", (d) => (cloudLog += d));
cloud.stderr.on("data", (d) => (cloudLog += d));
for (let i = 0; ; i++) {
  try {
    const r = await fetch(`${cloudUrl}/api/health`);
    if ((await r.json()).botUsername) break;
  } catch {
    /* starting */
  }
  if (i > 100) throw new Error("cloud server did not start:\n" + cloudLog);
  await new Promise((r) => setTimeout(r, 200));
}

// ---- the app: Electron, or the same build in Chromium served by vite preview
let browser;
let electronApp;
let preview;
let page;
const userData = path.join(tmp, "electron-user-data");
// Offline runs: serve three.js / lucide from a local folder (E2E_CDN_DIR) instead of the CDNs.
async function routeCdn(target) {
  const dir = process.env.E2E_CDN_DIR;
  if (!dir) return;
  const file = (n) => fs.readFileSync(path.join(dir, n));
  await target.route(/cdn\.jsdelivr\.net|unpkg\.com|fonts\.(googleapis|gstatic)\.com/, (r) => {
    const u = r.request().url();
    const js = { contentType: "application/javascript", headers: { "access-control-allow-origin": "*" } };
    if (u.includes("three.module")) return r.fulfill({ body: file("three.module.min.js"), ...js });
    if (u.includes("RoomEnvironment")) return r.fulfill({ body: file("RoomEnvironment.js"), ...js });
    if (u.includes("lucide")) return r.fulfill({ body: file("lucide.min.js"), ...js });
    return r.abort();
  });
}

async function openApp() {
  if (ELECTRON) {
    electronApp = await pw._electron.launch({
      executablePath: require("electron"),
      args: [root, ...(process.platform === "linux" ? ["--no-sandbox"] : [])],
      env: { ...process.env, STELLA_CLOUD_URL: cloudUrl, STUDIO_USER_DATA: userData, STUDIO_E2E: "1" },
    });
    page = await electronApp.firstWindow();
    await routeCdn(page);
    await page.setViewportSize({ width: 1440, height: 900 }).catch(() => undefined);
  } else {
    if (!preview) {
      const port = 3417;
      preview = spawn(process.execPath, [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--port", String(port), "--strictPort"], { cwd: root, stdio: ["ignore", "pipe", "pipe"] });
      await new Promise((resolve, reject) => {
        const t = setTimeout(() => reject(new Error("vite preview did not start")), 20000);
        preview.stdout.on("data", (d) => /Local/.test(String(d)) && (clearTimeout(t), resolve()));
        preview.on("exit", (c) => reject(new Error("vite preview exited " + c)));
      });
      browser = await pw.chromium.launch();
      const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
      await ctx.addInitScript((u) => {
        if (window.top !== window) return; // the sandboxed site preview iframe
        if (!localStorage.getItem("stella-cloud-url")) localStorage.setItem("stella-cloud-url", u);
        window.open = (url) => ((window.__opened = [...(window.__opened || []), url]), null);
      }, cloudUrl);
      await routeCdn(ctx);
      page = await ctx.newPage();
      page.__port = port;
    }
    await page.goto(`http://127.0.0.1:3417/`);
  }
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("dialog", (d) => d.accept());
}
async function closeApp() {
  if (electronApp) await electronApp.close();
  electronApp = null;
}

const errors = [];
let failed = false;
const step = (name) => console.log(`✓ ${name}${ELECTRON ? " [electron]" : ""}`);
try {
  await openApp();
  await page.getByText("Vibing AI Studio").first().waitFor();
  const code = (await page.getByTestId("login-code").textContent({ timeout: 15000 })).trim();
  step("app starts with the Telegram sign-in dialog and a code");

  say(`/login ${code}`);
  const offer = await waitTg((m) => m.method === "sendMessage" && JSON.stringify(m.params.reply_markup || "").includes("approve:"));
  if (!offer.params.text.includes(code)) throw new Error("bot did not show the code");
  press(offer.params.reply_markup.inline_keyboard[0][0].callback_data);
  await page.locator(".user-name-label").filter({ hasText: "Анна" }).waitFor({ timeout: 15000 });
  await page.locator(".user-plan-pill").filter({ hasText: "Free" }).waitFor();
  step("approved in Telegram → signed in, plan from the server shown");
  await page.screenshot({ path: path.join(shots, `1-signed-in${ELECTRON ? "-electron" : ""}.png`) });

  const box = page.locator(".composer textarea");
  const frame = page.frameLocator("iframe.pv-frame");

  // 3D Pro (default): the model returns only JSON (template + texts + palette)
  await box.fill("Сделай сайт кофейни «Зерно» в Казани");
  await box.press("Enter");
  await frame.locator("h1").filter({ hasText: "Кофе, ради которого" }).waitFor({ timeout: 20000 });
  await frame.locator("#hero3d").waitFor({ state: "attached" });
  await page.locator(".probar").waitFor();
  await page.getByText("Шаблон:").first().waitFor();
  if (!upstreamRequests.at(-1).messages.some((m) => m.role === "system" && m.content.includes("warm-bistro"))) throw new Error("3D Pro prompt missing the template catalog");
  step("3D Pro: AI picked the template and wrote the content, site rendered with a WebGL hero");
  await page.waitForTimeout(1500);
  await page.screenshot({ path: path.join(shots, `2-pro-site${ELECTRON ? "-electron" : ""}.png`) });

  await page.getByRole("button", { name: "Палитра Мята" }).click();
  for (let i = 0; ; i++) {
    const bg = await frame.locator("body").evaluate((b) => getComputedStyle(b).backgroundColor).catch(() => "");
    if (bg === "rgb(242, 251, 247)") break;
    if (i > 50) throw new Error("palette was not applied, body background: " + bg);
    await page.waitForTimeout(200);
  }
  await frame.locator("h1").filter({ hasText: "Кофе, ради которого" }).waitFor();
  if (await page.locator(".probar select option[value='kinetic-fit']").count()) throw new Error("users must not be able to pick a template");
  if (await page.getByText(/Шаблоны · 3D Pro|Галерея шаблонов/).count()) throw new Error("template gallery must be gone");
  step("one-click palette keeps the texts; templates are chosen only by the AI");

  await box.fill("Сделай заголовок про лучший кофе Казани");
  await box.press("Enter");
  await frame.locator("h1").filter({ hasText: "Лучший кофе Казани" }).waitFor({ timeout: 20000 });
  if (!upstreamRequests.at(-1).messages[0].content.includes("ТЕКУЩИЙ JSON САЙТА")) throw new Error("3D Pro edit did not send the current spec");
  step("3D Pro edit: the AI changed only the content of the current spec");

  await page.locator(".plan-limit-counter").filter({ hasText: "48 ост." }).waitFor({ timeout: 10000 });
  const firstReq = upstreamRequests[0];
  if (!firstReq.messages[0].content.startsWith("OWNER-PROMPT")) throw new Error("owner prompt was not injected: " + firstReq.messages[0].content.slice(0, 80));
  step("owner prompt injected by the server; usage counter updates (48 left)");

  // restart: still signed in, project kept
  if (ELECTRON) {
    await closeApp();
    await openApp();
  } else await page.reload();
  await page.locator(".user-name-label").filter({ hasText: "Анна" }).waitFor({ timeout: 15000 });
  await page.frameLocator("iframe.pv-frame").locator("h1").filter({ hasText: "Лучший кофе Казани" }).waitFor();
  await page.locator(".probar").waitFor();
  if (ELECTRON) {
    const vault = fs.readFileSync(path.join(userData, "credentials.bin"));
    if (vault.length < 10) throw new Error("credential vault empty");
  }
  step("after restart: still signed in, project restored");

  // the owner bans the user in Telegram → the app drops the session
  say("/start"); // nothing: user 5150 is not admin; admin is tg id 1
  const adminFrom = { id: 1, first_name: "Owner", username: "owner", is_bot: false };
  tgPush({ message: { message_id: updateId, from: adminFrom, chat: { id: 1, type: "private" }, text: "/start" } });
  await waitTg((m) => m.params.chat_id === 1);
  tgPush({ message: { message_id: updateId, from: adminFrom, chat: { id: 1, type: "private" }, text: "/ban @anna" } });
  await waitTg((m) => m.params.chat_id === 1 && /Заблокирован/.test(m.params.text || ""));
  const box2 = page.locator(".composer textarea");
  await box2.fill("Ещё правку");
  await box2.press("Enter");
  await page.getByTestId("login-code").waitFor({ timeout: 15000 });
  step("account banned by the admin in Telegram → app returns to sign-in");

  if (errors.length) throw new Error("page errors: " + errors.join(" | "));
  step("no uncaught page errors");
} catch (e) {
  failed = true;
  console.error("✗ " + e.message);
  await page?.screenshot({ path: path.join(shots, `failure${ELECTRON ? "-electron" : ""}.png`) }).catch(() => undefined);
} finally {
  await closeApp().catch(() => undefined);
  await browser?.close();
  preview?.kill();
  cloud.kill();
  upstream.close();
  telegram.close();
  upstream.closeAllConnections?.();
  telegram.closeAllConnections?.();
}
process.exit(failed ? 1 : 0);

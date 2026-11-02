// End-to-end check in a real browser: built app + `vite preview` (with the /llm proxy) against a
// local server speaking the FreeLLMAPI/OpenAI streaming protocol.
// Usage: npm run build && npm run e2e   (needs Playwright with Chromium installed)
import http from "node:http";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { mkdirSync } from "node:fs";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const shots = path.join(root, "test-results");
mkdirSync(shots, { recursive: true });

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

const requests = [];
const mock = http.createServer(async (req, res) => {
  let b = "";
  for await (const c of req) b += c;
  requests.push({ url: req.url, auth: req.headers.authorization, body: b ? JSON.parse(b) : null });
  if (req.headers.authorization !== "Bearer freellmapi-e2e") {
    res.writeHead(401, { "content-type": "application/json" }).end(JSON.stringify({ error: { message: "bad key" } }));
    return;
  }
  if (req.url === "/v1/models") {
    res.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify({ data: [{ id: "auto:smart" }, { id: "glm-5.3:free" }] }));
    return;
  }
  const body = JSON.parse(b);
  const sys = body.messages.find((m) => m.role === "system")?.content || "";
  const text = body.max_tokens <= 16 ? "ок" : sys.includes("ТЕКУЩИЙ КОД САЙТА") ? EDIT : SITE;
  res.writeHead(200, { "content-type": "text/event-stream", "x-routed-via": "groq/llama-3.3-70b-versatile" });
  for (let i = 0; i < text.length; i += 40) {
    res.write(`data: ${JSON.stringify({ choices: [{ delta: { content: text.slice(i, i + 40) } }] })}\n\n`);
    await new Promise((r) => setTimeout(r, 5));
  }
  res.write(`data: ${JSON.stringify({ choices: [], usage: { prompt_tokens: 900, completion_tokens: 300 } })}\n\n`);
  res.end("data: [DONE]\n\n");
});
await new Promise((r) => mock.listen(0, "127.0.0.1", r));
const mockUrl = `http://127.0.0.1:${mock.address().port}`;

const port = 3417;
const preview = spawn(process.execPath, [path.join(root, "node_modules/vite/bin/vite.js"), "preview", "--port", String(port), "--strictPort"], {
  cwd: root,
  env: { ...process.env, FREELLMAPI_URL: mockUrl },
  stdio: ["ignore", "pipe", "pipe"],
});
await new Promise((resolve, reject) => {
  const t = setTimeout(() => reject(new Error("vite preview did not start")), 20000);
  preview.stdout.on("data", (d) => /Local/.test(String(d)) && (clearTimeout(t), resolve()));
  preview.on("exit", (c) => reject(new Error("vite preview exited " + c)));
});

const browser = await chromium.launch();
let failed = false;
const step = (name) => console.log("✓ " + name);
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("dialog", (d) => d.accept());
  await page.goto(`http://127.0.0.1:${port}/`);
  await page.getByText("Vibing AI Studio").first().waitFor();
  step("app loads");

  await page.getByRole("button", { name: "Вход / Регистрация" }).click();
  await page.getByRole("button", { name: "Зарегистрироваться" }).click();
  await page.getByText("станет владельцем").waitFor();
  const inputs = page.locator(".auth-modal input");
  await inputs.nth(0).fill("owner");
  await inputs.nth(1).fill("owner@example.com");
  await inputs.nth(2).fill("super-secret-1");
  await page.getByRole("button", { name: "Создать аккаунт" }).click();
  await page.getByText("Админка").waitFor();
  const stored = await page.evaluate(() => localStorage.getItem("vibing_users"));
  if (stored.includes("super-secret-1")) throw new Error("password stored in plain text");
  step("first account is the owner/admin, password hashed");

  await page.getByRole("button", { name: /AI: FreeLLMAPI/ }).click();
  await page.locator(".provider-modal input[type=password]").fill("freellmapi-e2e");
  await page.getByRole("button", { name: "Загрузить модели" }).click();
  await page.getByText("Загружено моделей: 2").waitFor();
  await page.getByRole("button", { name: "Проверить подключение" }).click();
  await page.getByText(/Работает: ответ «ок»/).waitFor();
  await page.getByText(/groq\/llama-3.3-70b-versatile/).first().waitFor();
  step("provider modal: key, model list and connection test via /llm proxy");
  await page.screenshot({ path: path.join(shots, "1-provider.png") });
  await page.locator(".provider-modal .modal-close").click();

  const box = page.locator(".composer textarea");
  await box.fill("Сделай лендинг кофейни");
  await box.press("Enter");
  const frame = page.frameLocator("iframe.pv-frame");
  await frame.locator("#title").filter({ hasText: "Кофейня Тест" }).waitFor({ timeout: 20000 });
  await page.getByText("auto:smart → groq/llama-3.3-70b-versatile").waitFor();
  step("site generated, streamed into the preview, routed model shown");
  await page.screenshot({ path: path.join(shots, "2-site.png") });

  await page.getByText("Правлю текущий сайт").waitFor();
  await box.fill("Поменяй заголовок");
  await box.press("Enter");
  await frame.locator("#title").filter({ hasText: "Кофейня Обновлено" }).waitFor({ timeout: 20000 });
  await page.getByText("Применено правок: 1 из 1").waitFor();
  step("edit mode applies SEARCH/REPLACE to the live site");
  await page.screenshot({ path: path.join(shots, "3-edit.png") });

  const chat = requests.filter((r) => r.url === "/v1/chat/completions" && r.body.max_tokens > 16);
  if (chat.length !== 2 || chat.some((r) => r.body.model !== "auto:smart" || !r.body.stream)) throw new Error("unexpected requests: " + JSON.stringify(chat.map((c) => c.body.model)));
  if (!chat[1].body.messages[0].content.includes("Кофейня Тест")) throw new Error("edit request did not include current site");
  step("requests: model auto:smart, streaming, current site sent for edits");

  await page.reload();
  await frame.locator("#title").filter({ hasText: "Кофейня Обновлено" }).waitFor();
  await page.getByText("Поменяй заголовок").waitFor();
  step("project, chat and site persist across reload");

  // plan self-upgrade is blocked for a regular user
  await page.getByRole("button", { name: "Выйти" }).click();
  await page.getByRole("button", { name: "Вход / Регистрация" }).click();
  await page.getByRole("button", { name: "Зарегистрироваться" }).click();
  await inputs.nth(0).fill("guest_user");
  await inputs.nth(1).fill("guest@example.com");
  await inputs.nth(2).fill("guest-pass-1");
  await page.getByRole("button", { name: "Создать аккаунт" }).click();
  await page.locator(".user-plan-pill").click();
  if ((await page.getByRole("button", { name: "Выбрать план" }).count()) !== 0) throw new Error("regular user can self-select a paid plan");
  await page.getByRole("button", { name: "По ключу активации" }).first().waitFor();
  step("regular users cannot self-upgrade to paid plans");

  if (errors.length) throw new Error("page errors: " + errors.join(" | "));
  step("no uncaught page errors");
} catch (e) {
  failed = true;
  console.error("✗ " + e.message);
} finally {
  await browser.close();
  preview.kill();
  mock.close();
}
process.exit(failed ? 1 : 0);

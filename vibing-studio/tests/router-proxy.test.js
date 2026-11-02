import { spawnSync } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, describe, expect, it } from "vitest";
import { createServer } from "vite";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const fakeRouter = path.resolve(root, "../stella-coder/tests/fixtures/fake-freellmapi.mjs");

const freePort = () =>
  new Promise((r) => {
    const s = net.createServer().listen(0, "127.0.0.1", () => {
      const p = s.address().port;
      s.close(() => r(p));
    });
  });

let cleanup = () => {};
afterAll(() => cleanup());

describe.skipIf(process.platform === "win32")("dev server + FreeLLMAPI", () => {
  it("starts an installed-but-stopped router and injects the saved key into /llm requests", async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "vibing-router-"));
    const port = await freePort();
    const routerDir = path.join(dir, "freellmapi");
    fs.mkdirSync(routerDir);
    fs.writeFileSync(path.join(routerDir, "docker-compose.yml"), "services: {}\n");
    fs.writeFileSync(path.join(routerDir, ".env"), "ENCRYPTION_KEY=" + "a".repeat(64) + "\n");
    const bin = path.join(dir, "bin");
    fs.mkdirSync(bin);
    fs.writeFileSync(
      path.join(bin, "docker"),
      `#!/bin/sh\nif [ "$2" = "up" ]; then PORT=${port} nohup "${process.execPath}" "${fakeRouter}" >/dev/null 2>&1 & echo $! > "${dir}/pid"; fi\nexit 0\n`,
      { mode: 0o755 }
    );
    const home = path.join(dir, "stella");
    fs.mkdirSync(home);
    fs.writeFileSync(path.join(home, "credentials.json"), JSON.stringify({ "freellmapi.apiKey": "freellmapi-fake-unified-key" }));
    Object.assign(process.env, { PATH: `${bin}:${process.env.PATH}`, FREELLMAPI_DIR: routerDir, FREELLMAPI_URL: `http://127.0.0.1:${port}`, STELLA_HOME: home, FREELLMAPI_API_KEY: "" });
    const devPort = await freePort();
    const server = await createServer({ root, configFile: path.join(root, "vite.config.js"), logLevel: "silent", server: { port: devPort, strictPort: true } });
    await server.listen();
    cleanup = async () => {
      await server.close();
      try {
        process.kill(Number(fs.readFileSync(path.join(dir, "pid"), "utf8")));
      } catch {
        /* gone */
      }
    };
    let res;
    for (let i = 0; i < 40; i++) {
      res = await fetch(`http://127.0.0.1:${devPort}/llm/v1/models`).catch(() => null);
      if (res && res.status !== 502 && res.status !== 500) break;
      await new Promise((r) => setTimeout(r, 250));
    }
    expect(res.status).toBe(200);
    expect((await res.json()).data[0].id).toBe("auto:smart");
    const chat = await fetch(`http://127.0.0.1:${devPort}/llm/v1/chat/completions`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ model: "auto:smart", messages: [], stream: true }) });
    expect(await chat.text()).toContain("router says hi");
    expect(spawnSync("true").status).toBe(0);
  }, 30000);
});

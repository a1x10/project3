import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { existsSync } from "node:fs";

// /llm/* is proxied to the FreeLLMAPI router, so the browser talks to the same origin (no CORS).
// Override the router address with FREELLMAPI_URL=http://host:port.
// The unified router key is added here, server-side, from FREELLMAPI_API_KEY or
// ~/.stella/credentials.json (written by the installer) — it never reaches the browser.
const routerModule = new URL("../tools/freellmapi-router.mjs", import.meta.url);

async function loadRouter() {
  if (!existsSync(routerModule)) return null;
  try {
    return await import(routerModule.href);
  } catch {
    return null;
  }
}

/** Start the local router (if installed) when the dev/preview server starts. */
function freellmapiRouter(target) {
  const local = /^https?:\/\/(localhost|127\.0\.0\.1)(?::(\d+))?\/?$/.exec(target);
  const boot = async (logger) => {
    if (!local || process.env.STELLA_NO_ROUTER_AUTOSTART || (process.env.VITEST && !process.env.FREELLMAPI_DIR)) return;
    const mod = await loadRouter();
    if (!mod) return;
    const cfg = mod.routerConfig({ ...process.env, FREELLMAPI_PORT: local[2] || "80" });
    if (await mod.ping(cfg)) return;
    if (!mod.installedMode(cfg)) {
      logger.warn(`FreeLLMAPI не найден на ${target}. Установите его: ../install.sh (Windows: ..\\install.cmd)`);
      return;
    }
    logger.info("Запускаю роутер FreeLLMAPI…");
    const r = await mod.ensure(cfg, {});
    if (r.running) logger.info(`FreeLLMAPI работает: ${cfg.url}`);
    else logger.warn(`Роутер FreeLLMAPI не запустился: ${r.reason}`);
  };
  return {
    name: "freellmapi-router",
    configureServer(server) {
      boot(server.config.logger);
    },
    configurePreviewServer(server) {
      boot(server.config.logger);
    },
  };
}

export default defineConfig(async ({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), ""), ...process.env };
  const target = (env.FREELLMAPI_URL || "http://localhost:3001").replace(/\/$/, "");
  const mod = await loadRouter();
  const routerKey = () => env.FREELLMAPI_API_KEY || mod?.readRouterKey?.() || "";
  const proxy = {
    "/llm": {
      target,
      changeOrigin: true,
      rewrite: (p) => p.replace(/^\/llm/, ""),
      configure(proxyServer) {
        proxyServer.on("proxyReq", (proxyReq, req) => {
          const key = routerKey();
          if (key && !req.headers.authorization) proxyReq.setHeader("authorization", `Bearer ${key}`);
        });
      },
    },
  };
  return {
    plugins: [react(), freellmapiRouter(target)],
    server: { host: "0.0.0.0", port: 3000, strictPort: true, proxy },
    preview: { host: "0.0.0.0", port: 3000, strictPort: true, proxy },
    test: { environment: "node", include: ["tests/**/*.test.js"], setupFiles: ["tests/setup-storage.js"] },
  };
});

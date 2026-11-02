import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// /llm/* is proxied to the FreeLLMAPI router, so the browser talks to the same origin (no CORS).
// Override the router address with FREELLMAPI_URL=http://host:port.
export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), ""), ...process.env };
  const target = env.FREELLMAPI_URL || "http://localhost:3001";
  const proxy = {
    "/llm": {
      target,
      changeOrigin: true,
      rewrite: (p) => p.replace(/^\/llm/, ""),
    },
  };
  return {
    plugins: [react()],
    server: { host: "0.0.0.0", port: 3000, strictPort: true, proxy },
    preview: { host: "0.0.0.0", port: 3000, strictPort: true, proxy },
    test: { environment: "node", include: ["tests/**/*.test.js"], setupFiles: ["tests/setup-storage.js"] },
  };
});

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vibing AI Studio talks only to a Stella Cloud server (sign-in via Telegram, models via its /v1 gateway).
// Default server for builds: VITE_CLOUD_URL=https://ai.example.com npm run build
// base "./" lets the same build run from file:// inside the Windows app (Electron).
export default defineConfig({
  base: "./",
  plugins: [react()],
  server: { host: "0.0.0.0", port: 3000, strictPort: true },
  preview: { host: "0.0.0.0", port: 3000, strictPort: true },
  test: { environment: "node", include: ["tests/**/*.test.js"], setupFiles: ["tests/setup-storage.js"] },
});

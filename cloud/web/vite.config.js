import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// In dev, API calls go to a locally running cloud server (cd ../server && npm run dev).
const target = process.env.STELLA_CLOUD_URL || 'http://localhost:8080';
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': target, '/v1': target, '/downloads': target } },
});

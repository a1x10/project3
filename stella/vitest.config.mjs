import { defineConfig } from 'vitest/config';
export default defineConfig({
  test: {
    include: ['tests/**/*.test.{js,mjs}'],
    environment: 'node',
    testTimeout: 20000,
  },
});

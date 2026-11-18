// Все настройки берутся из переменных окружения (или файла .env).
import fs from 'node:fs';

if (fs.existsSync('.env')) {
  for (const line of fs.readFileSync('.env', 'utf8').split('\n')) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
    if (m && process.env[m[1]] === undefined) process.env[m[1]] = m[2].replace(/^["']|["']$/g, '');
  }
}

const env = process.env;
export const config = {
  port: Number(env.PORT || 3000),
  mock: env.HF_MOCK === '1',                       // тестовый режим без реального GPU
  mcpUrl: env.HF_MCP_URL || 'https://mcp.higgsfield.ai/mcp',
  gpuType: env.GPU_TYPE || 'RTX-PRO-6000',         // один GPU на всех
  maxCreditsPerHour: Number(env.MAX_CREDITS_PER_HOUR || 98),
  imageModel: env.IMAGE_MODEL || 'qwen-image',
  videoModel: env.VIDEO_MODEL || 'wan-2-2-t2v-a14b',
  idleSeconds: Number(env.IDLE_SECONDS || 60),     // простой -> выключение
  maxQueuedPerUser: Number(env.MAX_QUEUED_PER_USER || 3),
  inviteCode: env.INVITE_CODE || '',               // если задан — регистрация только по коду
  secret: env.SESSION_SECRET || 'change-me-' + Math.random().toString(36).slice(2),
};

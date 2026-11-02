import { createApp } from './app.js';
import { loadConfig } from './config.js';

const cfg = loadConfig();
const app = createApp(cfg);
const port = await app.listen();
console.log(`Stella Cloud слушает http://${cfg.host}:${port} (публичный адрес ${cfg.publicUrl})`);
console.log(`Модели: ${cfg.upstreamBaseUrl}${cfg.botToken ? '' : ' · TELEGRAM_BOT_TOKEN не задан — регистрация через бота отключена'}`);

let stopping = false;
const stop = async (sig: string) => {
  if (stopping) return;
  stopping = true;
  console.log(`${sig}: остановка…`);
  const t = setTimeout(() => process.exit(0), 5000);
  t.unref();
  await app.close().catch(() => undefined);
  process.exit(0);
};
process.on('SIGINT', () => void stop('SIGINT'));
process.on('SIGTERM', () => void stop('SIGTERM'));

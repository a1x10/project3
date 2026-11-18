// Единая точка запуска: создаёт .env, при первом запуске подключает Higgsfield, затем стартует сайт.
import fs from 'node:fs';
import crypto from 'node:crypto';

if (process.argv.includes('--mock')) process.env.HF_MOCK = '1';

if (!fs.existsSync('.env')) {
  const tpl = fs.readFileSync('.env.example', 'utf8')
    .replace(/^SESSION_SECRET=.*$/m, 'SESSION_SECRET=' + crypto.randomBytes(32).toString('hex'));
  fs.writeFileSync('.env', tpl);
  console.log('Создан файл .env с настройками (его можно отредактировать).');
}

const { config } = await import('./config.js');
const { loadTokens } = await import('./higgsfield.js');

if (!config.mock && !loadTokens()) {
  console.log('\n=== Первый запуск: подключаем ваш аккаунт Higgsfield ===');
  const { connect } = await import('./connect.js');
  try { await connect(); }
  catch (e) { console.error('\n❌ Не удалось подключить Higgsfield:', e.message, '\nПопробуйте ещё раз: npm start'); process.exit(1); }
}

await import('./server.js');

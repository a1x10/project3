#!/usr/bin/env node
// Генератор SLT-ключей для разработчика STELLS.
//   npm run keygen            -> 1 ключ
//   npm run keygen -- 10      -> 10 ключей
//   node tools/keygen.js check SLT-XXXX-XXXX-XXXX-XXXX
// Секрет берётся из key-secret.json (тот же файл читает приложение).
'use strict';
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
let SECRET = process.env.STELLS_KEY_SECRET || 'stells-l3xn0-change-me';
try { const v = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'key-secret.json'), 'utf8')); if (v) SECRET = String(v); } catch { /* по умолчанию */ }
const B32 = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';

function sig(payload) {
  const h = crypto.createHmac('sha256', SECRET).update(payload).digest();
  let s = '';
  for (let i = 0; i < 4; i++) s += B32[h[i] % 32];
  return s;
}
function gen() {
  const rnd = crypto.randomBytes(12);
  let p = '';
  for (const b of rnd) p += B32[b % 32];
  return `SLT-${p.slice(0, 4)}-${p.slice(4, 8)}-${p.slice(8, 12)}-${sig(p)}`;
}

const [cmd, arg] = process.argv.slice(2);
if (cmd === 'check') {
  const m = String(arg || '').toUpperCase().match(/^SLT-(\w{4})-(\w{4})-(\w{4})-(\w{4})$/);
  console.log(m && sig(m[1] + m[2] + m[3]) === m[4] ? 'Ключ действителен' : 'Ключ НЕдействителен');
} else {
  const n = Math.max(1, Math.min(1000, Number(cmd) || 1));
  for (let i = 0; i < n; i++) console.log(gen());
}

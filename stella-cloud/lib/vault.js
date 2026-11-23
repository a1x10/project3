// Secrets at rest (service passwords): AES-256-GCM with a key stored separately from the data.
// Key: STELLA_SECRET_KEY (hex, 64 chars) or /var/lib/stella/secret.key (0600, created on first use).
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { DATA } = require('./store');

let KEY = null;
function key() {
  if (KEY) return KEY;
  if (/^[0-9a-f]{64}$/i.test(process.env.STELLA_SECRET_KEY || '')) return (KEY = Buffer.from(process.env.STELLA_SECRET_KEY, 'hex'));
  const f = path.join(DATA, 'secret.key');
  if (!fs.existsSync(f)) fs.writeFileSync(f, crypto.randomBytes(32).toString('hex'), { mode: 0o600 });
  return (KEY = Buffer.from(fs.readFileSync(f, 'utf8').trim(), 'hex'));
}
function seal(plain, aad = '') {
  const iv = crypto.randomBytes(12);
  const c = crypto.createCipheriv('aes-256-gcm', key(), iv);
  if (aad) c.setAAD(Buffer.from(aad));
  const data = Buffer.concat([c.update(String(plain), 'utf8'), c.final()]);
  return 'v1:' + Buffer.concat([iv, c.getAuthTag(), data]).toString('base64');
}
function open(sealed, aad = '') {
  if (!sealed || !String(sealed).startsWith('v1:')) return '';
  const b = Buffer.from(String(sealed).slice(3), 'base64');
  const d = crypto.createDecipheriv('aes-256-gcm', key(), b.subarray(0, 12));
  d.setAuthTag(b.subarray(12, 28));
  if (aad) d.setAAD(Buffer.from(aad));
  return Buffer.concat([d.update(b.subarray(28)), d.final()]).toString('utf8');
}
module.exports = { seal, open };

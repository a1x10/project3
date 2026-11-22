// Tiny JSON-file storage with atomic writes and debounced saving.
const fs = require('fs');
const path = require('path');

const DATA = process.env.STELLA_DATA || path.join(__dirname, '..', 'data');
fs.mkdirSync(DATA, { recursive: true, mode: 0o700 });

function readJson(file, def) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return def; }
}
function writeJson(file, val) {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const tmp = file + '.' + process.pid + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(val), { mode: 0o600 });
  fs.renameSync(tmp, file);
}

const timers = new Map();
function saveLater(file, getVal, ms = 800) {
  clearTimeout(timers.get(file));
  timers.set(file, setTimeout(() => { timers.delete(file); try { writeJson(file, getVal()); } catch (e) { console.error('save', file, e.message); } }, ms));
}
function flushAll() { /* timers fire on their own; used on shutdown */ }

module.exports = { DATA, readJson, writeJson, saveLater, flushAll };

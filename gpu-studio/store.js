// Простое хранилище в JSON-файле: пользователи и задачи.
import fs from 'node:fs';
const FILE = 'data/db.json';
fs.mkdirSync('data', { recursive: true });
export const db = fs.existsSync(FILE) ? JSON.parse(fs.readFileSync(FILE, 'utf8')) : {};
db.users ??= []; db.jobs ??= []; db.meta ??= {};
let timer = null;
export function saveDb() {
  clearTimeout(timer);
  timer = setTimeout(() => {
    fs.writeFileSync(FILE + '.tmp', JSON.stringify(db, null, 1));
    fs.renameSync(FILE + '.tmp', FILE);
  }, 200);
}

// Одноразовое подключение аккаунта Higgsfield к серверу (делает владелец сайта).
// Способ 1: код устройства — откройте ссылку на любом устройстве и подтвердите.
// Способ 2 (если первый не сработал): обычный вход через браузер на этом же компьютере.
import http from 'node:http';
import crypto from 'node:crypto';
import readline from 'node:readline';
import { OAUTH, saveTokens, tokenFromResponse, callTool } from './higgsfield.js';

const RESOURCE = 'https://mcp.higgsfield.ai/mcp';
const REDIRECT = 'http://127.0.0.1:8976/callback';
const form = o => new URLSearchParams(o);
const post = async (url, body, json = false) => {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'content-type': json ? 'application/json' : 'application/x-www-form-urlencoded', accept: 'application/json' },
    body: json ? JSON.stringify(body) : form(body),
  });
  return { ok: r.ok, status: r.status, j: await r.json().catch(() => ({})) };
};

async function register() {
  const r = await post(OAUTH.register, {
    client_name: 'GPU Studio (self-hosted)',
    redirect_uris: [REDIRECT],
    grant_types: ['authorization_code', 'refresh_token', 'urn:ietf:params:oauth:grant-type:device_code'],
    response_types: ['code'],
    token_endpoint_auth_method: 'none',
    scope: OAUTH.scope,
  }, true);
  if (!r.ok || !r.j.client_id) throw new Error('Регистрация клиента не удалась: ' + JSON.stringify(r.j));
  return { clientId: r.j.client_id, device: (r.j.grant_types || []).some(g => g.includes('device_code')) };
}

async function deviceFlow(clientId) {
  const d = await post(OAUTH.device, { client_id: clientId, scope: OAUTH.scope, resource: RESOURCE });
  if (!d.ok || !d.j.device_code) throw new Error('device flow недоступен: ' + JSON.stringify(d.j));
  console.log('\nОткройте ссылку и подтвердите вход в Higgsfield:');
  console.log('  ' + (d.j.verification_uri_complete || d.j.verification_uri));
  if (!d.j.verification_uri_complete) console.log('  Код: ' + d.j.user_code);
  let interval = (d.j.interval || 5) * 1000;
  const until = Date.now() + (d.j.expires_in || 600) * 1000;
  while (Date.now() < until) {
    await new Promise(r => setTimeout(r, interval));
    const t = await post(OAUTH.token, { grant_type: 'urn:ietf:params:oauth:grant-type:device_code', device_code: d.j.device_code, client_id: clientId });
    if (t.ok && t.j.access_token) return t.j;
    if (t.j.error === 'slow_down') interval += 5000;
    else if (t.j.error !== 'authorization_pending') throw new Error('Вход отклонён: ' + JSON.stringify(t.j));
  }
  throw new Error('Время на подтверждение вышло');
}

async function browserFlow(clientId) {
  const verifier = crypto.randomBytes(32).toString('base64url');
  const challenge = crypto.createHash('sha256').update(verifier).digest('base64url');
  const stateParam = crypto.randomBytes(16).toString('hex');
  const url = OAUTH.authorize + '?' + form({
    response_type: 'code', client_id: clientId, redirect_uri: REDIRECT, scope: OAUTH.scope,
    code_challenge: challenge, code_challenge_method: 'S256', state: stateParam, resource: RESOURCE,
  });
  console.log('\n1) Откройте эту ссылку в браузере и войдите в Higgsfield:\n\n' + url + '\n');
  console.log('2) Если сайт запущен на этом же компьютере — всё подхватится само.');
  console.log('   Если на удалённом сервере — браузер покажет ошибку "не удаётся открыть 127.0.0.1".');
  console.log('   Скопируйте адрес из адресной строки (начинается с http://127.0.0.1:8976/callback?...) и вставьте сюда:\n');
  const code = await new Promise((resolve, reject) => {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    const finish = (u) => {
      srv.close(); rl.close();
      u.searchParams.get('state') === stateParam && u.searchParams.get('code')
        ? resolve(u.searchParams.get('code')) : reject(new Error('Ошибка входа: ' + u.search));
    };
    const srv = http.createServer((req, res) => {
      const u = new URL(req.url, REDIRECT);
      if (u.pathname !== '/callback') return res.end();
      res.end('Готово! Можно закрыть вкладку.');
      finish(u);
    }).listen(8976, '127.0.0.1');
    rl.on('line', line => { try { if (line.trim()) finish(new URL(line.trim())); } catch { console.log('Это не похоже на адрес, попробуйте ещё раз:'); } });
  });
  const t = await post(OAUTH.token, { grant_type: 'authorization_code', code, redirect_uri: REDIRECT, client_id: clientId, code_verifier: verifier });
  if (!t.ok || !t.j.access_token) throw new Error('Обмен кода не удался: ' + JSON.stringify(t.j));
  return t.j;
}

export async function connect() {
  const { clientId, device } = await register();
  let tok = null;
  if (device) { try { tok = await deviceFlow(clientId); } catch (e) { console.log('\n' + e.message); } }
  if (!tok) tok = await browserFlow(clientId);
  saveTokens(tokenFromResponse(clientId, tok));
  const bal = await callTool('balance');
  console.log('\n✅ Higgsfield подключён. Баланс:', bal.credits ?? JSON.stringify(bal));
}

if (process.argv[1] && process.argv[1].endsWith('connect.js')) {
  connect().then(() => process.exit(0), e => { console.error('\n❌', e.message); process.exit(1); });
}

// Панель управления: вход, каркас, маршруты разделов, живые события от бота.
import { $, $$, ago, emit, get, h, on, post, toast } from './lib.js';

const VIEWS = {
  overview: { title: 'Обзор', load: () => import('./views/overview.js') },
  chats: { title: 'Переписка', sub: 'Личные чаты учеников с ботом и обращения к нему в группе', load: () => import('./views/chats.js') },
  homework: { title: 'Домашка', sub: 'Что сейчас в дневнике — и как это увидит класс', load: () => import('./views/homework.js') },
  schedule: { title: 'График', sub: 'Когда бот присылает ДЗ в группу', load: () => import('./views/schedule.js') },
  ai: { title: 'ИИ-помощник', sub: 'Как бот отвечает на вопросы', load: () => import('./views/ai.js') },
  access: { title: 'Ключи и доступ', sub: 'Ключи ИИ, вход в дневник, WhatsApp, безопасность панели', load: () => import('./views/access.js') },
  alerts: { title: 'Уведомления', sub: 'Технические события — только для админов', load: () => import('./views/alerts.js') },
  terminal: { title: 'Терминал', sub: 'Команды бота и живой журнал', load: () => import('./views/terminal.js') },
};

const state = { overview: null, cleanup: null, route: '', events: null, alertsSeen: 0 };
export const app = state;

// --- тема ---
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $('#theme use')?.setAttribute('href', theme === 'dark' ? '#i-sun' : '#i-moon');
  $('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#06080d' : '#f3f5fa');
}
let theme = 'dark';
try {
  theme = localStorage.getItem('hwb-theme') || (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
} catch {
  /* хранилище недоступно */
}
applyTheme(theme);

// --- вход ---
async function showAuth(reason) {
  clearInterval(state.timer); // без входа не опрашиваем бота (иначе форма входа сбрасывалась бы каждые 30 с)
  state.events?.close();
  state.events = null;
  if (!$('#auth').hidden && !reason) return; // форма входа уже на экране — не сбрасываем введённое
  $('#shell').hidden = true;
  $('#auth').hidden = false;
  let methods = { password: true, whatsapp: true };
  try {
    methods = (await get('/api/auth/me')).methods;
  } catch {
    /* бот недоступен — покажем форму всё равно */
  }
  const tabs = $$('.auth-tabs button');
  const errorBox = $('.auth-error');
  const showError = (text) => {
    errorBox.textContent = text;
    errorBox.hidden = !text;
  };
  const select = (tab) => {
    for (const b of tabs) b.setAttribute('aria-selected', String(b.dataset.tab === tab));
    for (const f of $$('.auth-form')) f.hidden = f.dataset.form !== tab;
    showError('');
    (tab === 'password' ? $('#auth-password') : $('.auth-form[data-form="code"] .btn'))?.focus();
  };
  for (const b of tabs) b.onclick = () => select(b.dataset.tab);
  $('.auth-tabs').hidden = !(methods.password && methods.whatsapp);
  if (!methods.password && !methods.whatsapp) {
    showError('Вход не настроен: задайте ADMIN_PANEL_PASSWORD или ADMIN_NUMBERS в .env и перезапустите бота.');
  }
  select(methods.password ? 'password' : 'code');
  if (reason === 'expired') showError('Ссылка для входа устарела или уже использована. Напишите боту !панель ещё раз.');

  $('.auth-form[data-form="password"]').onsubmit = async (e) => {
    e.preventDefault();
    const btn = e.submitter;
    btn.classList.add('is-loading');
    try {
      await post('/api/auth/login', { password: $('#auth-password').value });
      $('#auth-password').value = '';
      boot();
    } catch (error) {
      showError(error.message);
      $('#auth-password').select();
    } finally {
      btn.classList.remove('is-loading');
    }
  };
  const codeForm = $('.auth-form[data-form="code"]');
  codeForm.querySelector('[data-action="send-code"]').onclick = async (e) => {
    const btn = e.currentTarget;
    btn.classList.add('is-loading');
    try {
      const r = await post('/api/auth/code');
      codeForm.querySelector('.code-step').hidden = false;
      $('.auth-code-hint').textContent = `Код отправлен в WhatsApp (админов: ${r.sentTo}). Действует 5 минут.`;
      btn.hidden = true;
      $('#auth-code').focus();
      showError('');
    } catch (error) {
      showError(error.message);
    } finally {
      btn.classList.remove('is-loading');
    }
  };
  codeForm.onsubmit = async (e) => {
    e.preventDefault();
    const btn = e.submitter;
    btn?.classList.add('is-loading');
    try {
      await post('/api/auth/code/verify', { code: $('#auth-code').value });
      boot();
    } catch (error) {
      showError(error.message);
    } finally {
      btn?.classList.remove('is-loading');
    }
  };
}

// --- каркас ---
function setupShell() {
  $('#auth').hidden = true;
  $('#shell').hidden = false;
  $('#theme').onclick = () => {
    theme = theme === 'dark' ? 'light' : 'dark';
    applyTheme(theme);
    try {
      localStorage.setItem('hwb-theme', theme);
    } catch {
      /* не сохраняем */
    }
    emit('theme', theme);
  };
  $('#logout').onclick = async () => {
    await post('/api/auth/logout').catch(() => {});
    location.hash = '';
    showAuth();
  };
  const side = $('#side');
  const scrim = $('#scrim');
  const closeMenu = () => {
    side.classList.remove('open');
    scrim.hidden = true;
  };
  $('#menu').onclick = () => {
    side.classList.add('open');
    scrim.hidden = false;
  };
  scrim.onclick = closeMenu;
  for (const a of $$('.side-nav a')) a.addEventListener('click', closeMenu);
}

function pill(dotClass, text, title) {
  return h('span.pill', { title }, h(`i.dot.${dotClass}`), text);
}

export function renderStatus(o = state.overview) {
  if (!o) return;
  $('#bot-name').textContent = o.bot.name || 'Бот ДЗ';
  $('#bot-class').textContent = o.bilim.className ? `${o.bilim.className} · ${o.bilim.schoolName || 'панель'}` : 'панель управления';
  const wa = o.whatsapp;
  const waOk = wa.status === 'open';
  $('#pills').replaceChildren(
    pill(waOk ? 'ok.live' : wa.status === 'qr' ? 'warn' : 'err', waOk ? 'WhatsApp' : wa.status === 'qr' ? 'WhatsApp: нужна привязка' : 'WhatsApp: нет связи', waOk ? `на связи с ${new Date(wa.connectedSince).toLocaleString('ru-RU')}` : ''),
    pill(o.bilim.ok ? (o.bilim.mode === 'site' ? 'warn' : 'ok') : 'err', o.bilim.ok ? (o.bilim.mode === 'site' ? 'Дневник: через сайт' : 'Дневник') : 'Дневник: ошибка', o.bilim.error || `обновлён ${ago(o.bilim.lastSyncAt)}`),
    pill(o.ai.enabled ? 'ok' : 'warn', o.ai.enabled ? 'ИИ' : 'ИИ выкл', o.ai.key ? `ключ: ${o.ai.key}` : ''),
  );
  const status = $('#side-status');
  status.replaceChildren(h(`i.dot.${waOk ? 'ok.live' : 'err'}`), h('span', waOk ? `Бот на связи · ${o.groups.length} гр.` : 'WhatsApp не на связи'));
  setUnread(o.inbox.unread);
  const fresh = (o.alerts || []).filter((a) => a.level !== 'ok' && a.at > Date.now() - 24 * 3600 * 1000).length;
  const badge = $('#alerts-count');
  badge.textContent = String(fresh);
  badge.hidden = !fresh || state.route === 'alerts';
}

export function setUnread(n) {
  const badge = $('#unread');
  badge.textContent = n > 99 ? '99+' : String(n);
  badge.hidden = !n;
  document.title = n ? `(${n}) Панель — Бот ДЗ` : 'Панель — Бот ДЗ';
}

export async function refreshOverview() {
  try {
    state.overview = await get('/api/overview');
    renderStatus();
    emit('overview', state.overview);
  } catch {
    /* сеть — попробуем позже */
  }
  return state.overview;
}

// --- живые события ---
function connectEvents() {
  state.events?.close();
  const es = new EventSource('/api/events');
  state.events = es;
  const relay = (name) => es.addEventListener(name, (e) => {
    try {
      emit(`sse:${name}`, JSON.parse(e.data));
    } catch {
      /* битое событие */
    }
  });
  for (const name of ['log', 'alert', 'chat', 'read', 'chatState', 'wa', 'settings']) relay(name);
  es.onerror = () => {
    // сервер перезапускается или сессия истекла — проверим вход
    setTimeout(async () => {
      if (es.readyState === EventSource.CLOSED) {
        try {
          const me = await get('/api/auth/me');
          if (!me.authenticated) showAuth();
          else connectEvents();
        } catch {
          setTimeout(connectEvents, 4000);
        }
      }
    }, 1500);
  };
}

on('sse:alert', (a) => {
  toast(a.text, a.level === 'ok' ? 'ok' : a.level === 'error' ? 'err' : 'warn', 7000);
  refreshOverview();
});
on('sse:wa', () => refreshOverview());
on('sse:chat', (e) => {
  if (e.message.dir === 'in' && state.route !== 'chats') {
    toast(`💬 ${e.chat.name}: ${e.message.text || 'медиа'}`.slice(0, 140), 'ok', 5000);
  }
  if (state.overview) {
    state.overview.inbox.unread = Math.max(0, state.overview.inbox.unread + (e.message.dir === 'in' ? 1 : 0));
    setUnread(state.overview.inbox.unread);
  }
});
on('sse:read', () => refreshOverview());
on('unauthorized', () => showAuth());

// --- маршруты ---
async function route() {
  const [name = 'overview', ...params] = location.hash.replace(/^#\/?/, '').split('/').map(decodeURIComponent);
  const view = VIEWS[name] ? name : 'overview';
  if (state.cleanup) {
    try {
      state.cleanup();
    } catch {
      /* ignore */
    }
    state.cleanup = null;
  }
  document.querySelector('.savebar')?.remove();
  state.route = view;
  for (const a of $$('.side-nav a')) a.classList.toggle('active', a.dataset.route === view);
  $('#page-title').textContent = VIEWS[view].title;
  $('#page-sub').textContent = VIEWS[view].sub || '';
  if (view === 'alerts') $('#alerts-count').hidden = true;
  const root = $('#view');
  root.replaceChildren(h('div.grid.g4', [1, 2, 3, 4].map(() => h('div.skeleton', { style: { height: '120px' } }))));
  root.style.animation = 'none';
  void root.offsetWidth;
  root.style.animation = '';
  try {
    const mod = await VIEWS[view].load();
    if (state.route !== view) return;
    const container = h('div');
    root.replaceChildren(container);
    const cleanup = (await mod.render(container, { params, app: state, refreshOverview })) || null;
    // пока раздел загружался, перешли в другой — сразу снимаем его подписки
    if (state.route !== view || !container.isConnected) cleanup?.();
    else state.cleanup = cleanup;
  } catch (error) {
    root.replaceChildren(h('div.empty', h('b', 'Не удалось открыть раздел'), error.message));
  }
}

async function boot() {
  let me;
  try {
    me = await get('/api/auth/me');
  } catch (error) {
    $('#auth').hidden = false;
    $('.auth-error').textContent = error.message;
    $('.auth-error').hidden = false;
    return;
  }
  if (!me.authenticated) {
    showAuth(new URLSearchParams(location.search).get('login'));
    return;
  }
  setupShell();
  await refreshOverview();
  connectEvents();
  window.onhashchange = route;
  route();
  clearInterval(state.timer);
  state.timer = setInterval(refreshOverview, 30000);
}

boot();

import { escapeHtml } from '../core/markdown.js';
import { icon } from './icons.js';

export const $ = (s, r = document) => r.querySelector(s);
export const $$ = (s, r = document) => [...r.querySelectorAll(s)];
export { escapeHtml };

export function h(html) {
  const t = document.createElement('template');
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

export function toast(message, type = 'info', ms = 3800) {
  const root = $('#toasts');
  const el = h(`<div class="toast ${type}">${icon(type === 'error' ? 'alert' : type === 'success' ? 'check' : 'info', 16)}<span>${escapeHtml(message)}</span></div>`);
  root.appendChild(el);
  requestAnimationFrame(() => el.classList.add('show'));
  setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.remove(), 300); }, ms);
}

/** Модальное окно. Возвращает Promise с результатом кнопки. */
export function modal({ title, body = '', buttons = [{ label: 'OK', value: true, primary: true }], className = '', dismissValue = false }) {
  return new Promise((resolve) => {
    const el = h(`<div class="modal-backdrop"><div class="modal ${className}"><h3>${title}</h3><div class="modal-body"></div><div class="modal-btns"></div></div></div>`);
    const bodyEl = $('.modal-body', el);
    if (typeof body === 'string') bodyEl.innerHTML = body; else bodyEl.appendChild(body);
    const close = (v) => { el.classList.remove('show'); setTimeout(() => el.remove(), 200); document.removeEventListener('keydown', onKey); resolve(v); };
    for (const b of buttons) {
      const btn = h(`<button class="btn ${b.primary ? 'primary' : ''} ${b.danger ? 'danger' : ''}">${escapeHtml(b.label)}</button>`);
      btn.onclick = () => close(typeof b.value === 'function' ? b.value(el) : b.value);
      $('.modal-btns', el).appendChild(btn);
    }
    el.addEventListener('mousedown', (e) => { if (e.target === el) close(dismissValue); });
    const onKey = (e) => { if (e.key === 'Escape') close(dismissValue); };
    document.addEventListener('keydown', onKey);
    $('#modal-root').appendChild(el);
    requestAnimationFrame(() => el.classList.add('show'));
    setTimeout(() => el.querySelector('input,textarea,.btn.primary')?.focus(), 50);
  });
}

export function timeAgo(ts) {
  const d = (Date.now() - ts) / 1000;
  if (d < 60) return 'только что';
  if (d < 3600) return `${Math.floor(d / 60)} мин назад`;
  if (d < 86400) return `${Math.floor(d / 3600)} ч назад`;
  return new Date(ts).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' });
}

export function plural(n, one, few, many) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return few;
  return many;
}

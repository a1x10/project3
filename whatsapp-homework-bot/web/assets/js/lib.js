// Общие инструменты панели: построение DOM без innerHTML (защита от XSS), запросы к API, тосты, окна, форматирование.

// h('div.card#id', { onclick, dataset, ... }, 'текст', child, [дети]) → элемент
export function h(tag, attrs, ...children) {
  const [, name = 'div', rest = ''] = /^([a-z0-9-]*)(.*)$/i.exec(tag);
  const el = document.createElement(name || 'div');
  for (const part of rest.match(/[.#][^.#]+/g) || []) {
    if (part[0] === '.') el.classList.add(...part.slice(1).split(/\s+/).filter(Boolean));
    else el.id = part.slice(1);
  }
  if (attrs && (typeof attrs !== 'object' || attrs instanceof Node || Array.isArray(attrs))) {
    children.unshift(attrs);
    attrs = null;
  }
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (k === 'style' && typeof v === 'object') {
      for (const [prop, value] of Object.entries(v)) {
        if (prop.startsWith('--')) el.style.setProperty(prop, value);
        else el.style[prop] = value;
      }
    }
    else if (k === 'class') el.className = [el.className, v].filter(Boolean).join(' ');
    else if (k === 'value') el.value = v;
    else if (k in el && typeof v !== 'string') el[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

const SVG = 'http://www.w3.org/2000/svg';
export function icon(name, cls = '') {
  const svg = document.createElementNS(SVG, 'svg');
  if (cls) svg.setAttribute('class', cls);
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS(SVG, 'use');
  use.setAttribute('href', `#i-${name}`);
  svg.append(use);
  return svg;
}

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

// --- API ---
export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

export const bus = new EventTarget();
export const emit = (type, detail) => bus.dispatchEvent(new CustomEvent(type, { detail }));
export const on = (type, fn) => {
  const handler = (e) => fn(e.detail);
  bus.addEventListener(type, handler);
  return () => bus.removeEventListener(type, handler);
};

export async function api(method, path, body) {
  let res;
  try {
    res = await fetch(path, {
      method,
      headers: { 'Content-Type': 'application/json', 'X-HWB': '1' },
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: 'same-origin',
      cache: 'no-store',
    });
  } catch {
    throw new ApiError('Нет связи с ботом. Проверьте, что он запущен.', 0);
  }
  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (res.status === 401 && !path.startsWith('/api/auth/')) emit('unauthorized');
  if (!res.ok) throw new ApiError(data?.error || `Ошибка ${res.status}`, res.status);
  return data;
}
export const get = (path) => api('GET', path);
export const post = (path, body = {}) => api('POST', path, body);
export const put = (path, body = {}) => api('PUT', path, body);
export const del = (path) => api('DELETE', path);

// кнопка «крутится», пока идёт действие; ошибки — тостом
export async function busy(button, fn) {
  button?.classList.add('is-loading');
  if (button) button.disabled = true;
  try {
    return await fn();
  } catch (error) {
    toast(error.message, 'err');
    return undefined;
  } finally {
    button?.classList.remove('is-loading');
    if (button) button.disabled = false;
  }
}

// --- тосты ---
export function toast(text, kind = 'ok', ms = 4200) {
  const box = $('#toasts');
  const el = h(`div.toast.${kind}`, { role: 'status' }, icon(kind === 'ok' ? 'check' : kind === 'err' ? 'x' : 'bell'), h('span', text));
  box.append(el);
  setTimeout(() => {
    el.classList.add('out');
    setTimeout(() => el.remove(), 320);
  }, ms);
}

// --- модальные окна ---
export function modal({ title, body, actions = [], wide = false, onClose }) {
  const dlg = $('#modal');
  dlg.className = `modal${wide ? ' wide' : ''}`;
  dlg.replaceChildren(
    h('div.modal-h', h('h3', title), h('button.btn.btn-icon.btn-ghost.btn-sm', { type: 'button', 'aria-label': 'Закрыть', onclick: () => dlg.close() }, icon('x'))),
    h('div.modal-b', body),
    actions.length ? h('div.modal-f', actions) : null,
  );
  const close = () => {
    dlg.removeEventListener('close', close);
    onClose?.();
  };
  dlg.addEventListener('close', close);
  if (!dlg.open) dlg.showModal();
  return dlg;
}

export function confirmDialog({ title, text, ok = 'Подтвердить', danger = false, input = null }) {
  return new Promise((resolve) => {
    let answered = false;
    const field = input ? h('input.input', { placeholder: input.placeholder || '', autocomplete: 'off' }) : null;
    const done = (value) => {
      answered = true;
      resolve(value);
      $('#modal').close();
    };
    modal({
      title,
      body: h('div.fields', h('p', { style: { margin: 0, color: 'var(--text-2)' } }, text), input ? h('div.field', h('label.label', input.label), field, input.hint ? h('p.hint', input.hint) : null) : null),
      actions: [
        h('button.btn', { type: 'button', onclick: () => done(false) }, 'Отмена'),
        h(`button.btn.${danger ? 'btn-danger' : 'btn-primary'}`, { type: 'button', onclick: () => done(input ? field.value : true) }, ok),
      ],
      onClose: () => {
        if (!answered) resolve(false);
      },
    });
    field?.focus();
  });
}

// --- форматирование ---
const pad = (n) => String(n).padStart(2, '0');
export function ago(ts) {
  if (!ts) return '—';
  const s = Math.round((Date.now() - ts) / 1000);
  if (s < 45) return 'только что';
  if (s < 3600) return `${Math.round(s / 60)} мин назад`;
  if (s < 86400) return `${Math.round(s / 3600)} ч назад`;
  if (s < 7 * 86400) return `${Math.round(s / 86400)} д назад`;
  return new Date(ts).toLocaleDateString('ru-RU');
}
export const clock = (ts) => {
  const d = new Date(ts);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
export function shortWhen(ts) {
  const d = new Date(ts);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) return clock(ts);
  const y = new Date(now);
  y.setDate(now.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return 'вчера';
  return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' });
}
export function dayLabel(ts) {
  const d = new Date(ts);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) return 'Сегодня';
  const y = new Date(now);
  y.setDate(now.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return 'Вчера';
  return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', weekday: 'long' });
}
export const WEEKDAYS = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье'];
export const WD = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
export const MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
// сегодняшняя дата по часам этого устройства, YYYY-MM-DD
export const todayLocal = () => {
  const t = new Date();
  return `${t.getFullYear()}-${pad(t.getMonth() + 1)}-${pad(t.getDate())}`;
};
export const isoWeekday = (iso) => ((new Date(`${iso}T00:00:00Z`).getUTCDay() + 6) % 7) + 1;
export const addDaysIso = (iso, n) => new Date(Date.parse(`${iso}T00:00:00Z`) + n * 86400000).toISOString().slice(0, 10);
export const humanDate = (iso) => `${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]}`;
export const dm = (iso) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}`;

// цвет аватарки по имени
export function avatarColor(seed) {
  let hash = 0;
  for (const ch of String(seed)) hash = (hash * 31 + ch.codePointAt(0)) | 0;
  const hues = [152, 190, 262, 330, 28, 205, 170, 285];
  return `hsl(${hues[Math.abs(hash) % hues.length]} 58% 42%)`;
}
export function initials(name) {
  const words = String(name || '?').replace(/[^\p{L}\p{N}\s]/gu, ' ').trim().split(/\s+/);
  return (words[0]?.[0] || '?').toUpperCase() + (words[1]?.[0] || '').toUpperCase();
}

// --- элементы форм ---
export function toggle(checked, onchange, label = '') {
  const input = h('input', { type: 'checkbox', checked: Boolean(checked), 'aria-label': label, onchange: (e) => onchange(e.target.checked) });
  return h('label.switch', input, h('span'));
}

export function segmented(options, value, onchange, { cls = '' } = {}) {
  const wrap = h(`div.seg${cls ? `.${cls}` : ''}`, { role: 'group' });
  const render = (current) => {
    for (const btn of wrap.children) btn.setAttribute('aria-pressed', String(btn.dataset.value === String(current)));
  };
  for (const [val, text, extra] of options) {
    wrap.append(h('button', { type: 'button', dataset: { value: String(val) }, class: extra || '', onclick: () => {
      render(val);
      onchange(val);
    } }, text));
  }
  render(value);
  wrap.set = render;
  return wrap;
}

export function card(title, { sub, right, body, note, cls = '' } = {}) {
  return h(`section.card${cls ? `.${cls}` : ''}`,
    title ? h('header.card-h', h('h3', title), sub ? h('span.sub', sub) : null, right ? h('div.right', right) : null) : null,
    h('div.card-b', body),
    note ? h('div.card-note', note) : null,
  );
}

export function emptyState(title, text) {
  return h('div.empty', h('b', title), text);
}

// Панель «Сохранить изменения» для форм настроек
export function saveBar({ onSave, onReset }) {
  let bar = null;
  return {
    show() {
      if (bar) return;
      const save = h('button.btn.btn-primary', { type: 'button', onclick: async () => {
        await busy(save, onSave);
      } }, icon('check'), 'Сохранить');
      bar = h('div.savebar', h('span', 'Есть несохранённые изменения'), h('button.btn', { type: 'button', onclick: () => onReset() }, 'Отменить'), save);
      document.body.append(bar);
    },
    hide() {
      bar?.remove();
      bar = null;
    },
  };
}

// Конструктор страниц в стиле «левое меню + карточки настроек».
import { $, $$, h, escapeHtml } from './dom.js';
import { icon } from './icons.js';

export function pageHead(title, { tabs, active, search } = {}) {
  const right = tabs
    ? `<div class="seg-tabs">${tabs.map(([id, l]) => `<button data-ptab="${id}" class="${id === active ? 'active' : ''}">${l}</button>`).join('')}</div>`
    : search ? `<label class="search">${icon('search')}<input data-search placeholder="${escapeHtml(search)}"></label>` : '';
  return `<div class="page-head"><h1>${escapeHtml(title)}</h1>${right}</div>`;
}

/**
 * @param {HTMLElement} root
 * @param {{title:string, tabs?:Array, active?:string, onTab?:Function, search?:string, sections:Array<{id,icon,label,soon?,html}>}} o
 */
export function renderSettingsPage(root, o) {
  const scrollTop = root.querySelector('.content')?.scrollTop || 0;
  root.innerHTML = pageHead(o.title, o) + `
    <div class="page-body">
      <nav class="subnav">${o.sections.map((s, i) => `<button data-sec="${s.id}" class="${i === 0 ? 'active' : ''}">${icon(s.icon)}<span>${escapeHtml(s.label)}</span>${s.soon ? '<span class="soon">скоро</span>' : ''}</button>`).join('')}</nav>
      <div class="content">${o.sections.map((s) => `<section class="panel" id="sec-${s.id}"><h2 class="panel-title">${icon(s.icon, 22)} ${escapeHtml(s.label)}</h2>${s.desc ? `<p class="panel-desc">${s.desc}</p>` : ''}${s.html}</section>`).join('')}</div>
    </div>`;
  const content = $('.content', root);
  content.scrollTop = scrollTop;
  $$('.subnav button', root).forEach((b) => b.onclick = () => {
    const el = $('#sec-' + b.dataset.sec, root);
    content.scrollTo({ top: el.offsetTop - content.offsetTop, behavior: 'smooth' });
  });
  const spy = () => {
    let cur = o.sections[0].id;
    for (const s of o.sections) { const el = $('#sec-' + s.id, root); if (el.offsetTop - content.offsetTop - 40 <= content.scrollTop) cur = s.id; }
    $$('.subnav button', root).forEach((b) => b.classList.toggle('active', b.dataset.sec === cur));
  };
  content.addEventListener('scroll', spy);
  $$('[data-ptab]', root).forEach((b) => b.onclick = () => o.onTab?.(b.dataset.ptab));
  const search = $('[data-search]', root);
  if (search) search.addEventListener('input', () => {
    const q = search.value.trim().toLowerCase();
    $$('.set', root).forEach((s) => { s.style.display = !q || s.textContent.toLowerCase().includes(q) ? '' : 'none'; });
    $$('.panel', root).forEach((p) => { p.style.display = !q || [...p.querySelectorAll('.set')].some((s) => s.style.display !== 'none') ? '' : 'none'; });
  });
  $$('.adv', root).forEach((a) => a.onclick = () => a.nextElementSibling.classList.toggle('show'));
  return root;
}

// ---- Блоки настроек (возвращают HTML) ----
export const block = (title, desc, inner, ic) => `<div class="set"><h3>${ic ? icon(ic, 20) : ''}${title}</h3>${desc ? `<p>${desc}</p>` : ''}${inner}</div>`;
export const sw = (s, key, title, desc) => `<div class="set"><div class="set-row"><div class="lbl"><b>${title}</b>${desc ? `<small>${desc}</small>` : ''}</div><label class="switch"><input type="checkbox" data-key="${key}" ${s[key] ? 'checked' : ''}><span></span></label></div></div>`;
export const range = (s, key, title, desc, min, max, step, pct = false) => block(title, desc, `<div class="range-wrap"><input class="range" type="range" min="${min}" max="${max}" step="${step}" value="${s[key]}" data-key="${key}" ${pct ? 'data-pct' : ''}><span class="range-val" data-val="${key}">${pct ? Math.round(s[key] * 100) + '%' : s[key]}</span></div>`);
export const select = (s, key, title, desc, options, cls = '') => block(title, desc, `<select class="select ${cls}" data-key="${key}">${options.map(([v, l]) => `<option value="${escapeHtml(v)}" ${String(s[key]) === String(v) ? 'selected' : ''}>${escapeHtml(l)}</option>`).join('')}</select>`);
export const adv = (inner) => `<div class="adv">${icon('settings', 14)} Расширенные настройки ${icon('chevron', 14)}</div><div class="adv-body">${inner}</div>`;

/** Автосохранение всех полей с data-key. */
export function bindKeys(root, ctx, onChange) {
  const save = async (patch) => { await ctx.updateSettings(patch); onChange?.(patch); };
  $$('input[type=checkbox][data-key]', root).forEach((el) => el.addEventListener('change', () => save({ [el.dataset.key]: el.checked })));
  $$('input[type=range][data-key]', root).forEach((el) => {
    const out = $(`[data-val="${el.dataset.key}"]`, root);
    el.addEventListener('input', () => { if (out) out.textContent = el.hasAttribute('data-pct') ? Math.round(el.value * 100) + '%' : el.value; });
    el.addEventListener('change', () => save({ [el.dataset.key]: Number(el.value) }));
  });
  $$('select[data-key], textarea[data-key], input.input[data-key]', root).forEach((el) => el.addEventListener('change', () => save({ [el.dataset.key]: el.value })));
}

export function keyField(id, s, hasKey, placeholder) {
  return `<input class="input" type="password" id="${id}" placeholder="${hasKey ? '••••••••••••••••••••••' : placeholder}" autocomplete="off">
    <div class="note ${hasKey ? 'ok' : ''}">${hasKey ? icon('check', 14) + ' Ключ сохранён — введи новый, чтобы заменить' : 'Ключ не задан'}</div>`;
}

export { h };

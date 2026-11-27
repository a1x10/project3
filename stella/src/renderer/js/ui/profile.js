import { $, $$, h, escapeHtml, toast, modal, plural } from './dom.js';
import { icon } from './icons.js';
import { block } from './page.js';

const COLORS = ['#a78bfa', '#f472b6', '#38bdf8', '#34d399', '#fbbf24', '#fb7185', '#71717a'];
const LEVELS = ['Незнакомцы', 'Знакомые', 'Приятели', 'Друзья', 'Лучшие друзья', 'Родственные души'];

export function bondLevel(stats) {
  const xp = (stats.messagesSent || 0) * 3 + (stats.actions || 0) * 2 + (stats.memories || 0) * 5;
  let lvl = 0, need = 30, acc = 0;
  while (xp >= acc + need && lvl < LEVELS.length - 1) { acc += need; lvl++; need = Math.round(need * 1.8); }
  return { level: lvl, name: LEVELS[lvl], progress: lvl === LEVELS.length - 1 ? 1 : (xp - acc) / need, xp };
}

/** HTML раздела «Аккаунт» и функция привязки событий. */
export async function profileSection(ctx) {
  const acc = ctx.account;
  if (!acc) return { html: '<p class="hint">Нет активного аккаунта</p>', bind() {} };
  const [stats, memories] = await Promise.all([window.stella.invoke('account:stats'), window.stella.invoke('memory:list')]);
  const days = Math.max(1, Math.ceil((Date.now() - acc.createdAt) / 86400000));
  const bond = bondLevel(stats);
  const p = ctx.persona();
  const html = `
    <div class="set"><div class="profile-hero">
      <div class="big-ava" style="background:${acc.avatarColor}">${escapeHtml(acc.displayName[0].toUpperCase())}</div>
      <div style="min-width:0"><h2>${escapeHtml(acc.displayName)}</h2><div class="u">@${escapeHtml(acc.username)}${acc.email ? ' · ' + escapeHtml(acc.email) : ''}</div><div class="u">${acc.bio ? escapeHtml(acc.bio) : 'Вместе ' + days + ' ' + plural(days, 'день', 'дня', 'дней')}</div></div>
    </div></div>
    ${block(`Близость ${p.id === 'mark' ? 'с Марком' : 'со Стеллой'}: ${bond.name}`, `Уровень ${bond.level + 1}. Растёт, когда вы общаетесь и работаете вместе.`, `<div class="bond-bar"><div style="width:${Math.round(bond.progress * 100)}%"></div></div>`, 'heart')}
    <div class="set"><div class="stats">
      <div class="stat"><b>${stats.messagesSent || 0}</b><span>сообщений</span></div>
      <div class="stat"><b>${stats.actions || 0}</b><span>действий на ПК</span></div>
      <div class="stat"><b>${days}</b><span>${plural(days, 'день', 'дня', 'дней')} вместе</span></div>
      <div class="stat"><b>${memories.length}</b><span>воспоминаний</span></div>
    </div></div>
    ${block(`Что ${p.name} помнит о тебе`, 'Факты, которые ассистент сохранил сам или ты добавил вручную.', `<div id="mem-list">${memories.length ? '' : '<p class="hint">Пока ничего. Расскажи о себе в чате.</p>'}</div><div class="row" style="margin-top:10px"><input class="input" id="mem-input" placeholder="Например: люблю синтвейв и кофе без сахара"><button class="btn" id="mem-add">${icon('plus', 16)}</button></div>`, 'brain')}
    ${block('Профиль', '', `<div class="field"><label>Имя</label><input class="input" id="p-name" value="${escapeHtml(acc.displayName)}"></div>
      <div class="field"><label>О себе</label><input class="input" id="p-bio" value="${escapeHtml(acc.bio || '')}" placeholder="Пара слов о тебе"></div>
      <div class="field"><label>Цвет аватарки</label><div class="swatches">${COLORS.map((c) => `<div class="swatch ${acc.avatarColor === c ? 'active' : ''}" data-color="${c}" style="background:${c}"></div>`).join('')}</div></div>
      <button class="btn primary" id="p-save">Сохранить профиль</button>`, 'edit')}
    ${block('Пароль', acc.hasPassword ? 'Сменить или убрать пароль на вход.' : 'Установить пароль на вход в аккаунт.', `${acc.hasPassword ? '<div class="field"><input class="input" type="password" id="p-old" placeholder="Текущий пароль"></div>' : ''}<div class="row"><input class="input" type="password" id="p-new" placeholder="${acc.hasPassword ? 'Новый пароль (пусто — убрать)' : 'Новый пароль'}"><button class="btn" id="p-pass">Обновить</button></div>`, 'lock')}
    <div class="set row" style="flex-wrap:wrap"><button class="btn" id="p-logout">${icon('logout', 16)} Выйти</button><button class="btn danger" id="p-delete">${icon('trash', 16)} Удалить аккаунт</button></div>`;
  const bind = (root, rerender) => {
    let color = acc.avatarColor;
    const ml = $('#mem-list', root);
    for (const m of memories) {
      const it = h(`<div class="memory-item">${icon('sparkles', 14)}<span>${escapeHtml(m.text)}</span><button class="icon-btn ghost" title="Забыть">${icon('trash', 14)}</button></div>`);
      it.querySelector('button').onclick = async () => { await window.stella.invoke('memory:remove', m.id); rerender(); };
      ml.appendChild(it);
    }
    $$('.swatch[data-color]', root).forEach((el) => el.onclick = () => { color = el.dataset.color; $$('.swatch[data-color]', root).forEach((x) => x.classList.toggle('active', x === el)); });
    $('#mem-add', root).onclick = async () => { const v = $('#mem-input', root).value.trim(); if (!v) return; await window.stella.invoke('memory:add', v); ctx.avatar.play('nod'); rerender(); };
    $('#mem-input', root).addEventListener('keydown', (e) => { if (e.key === 'Enter') $('#mem-add', root).click(); });
    $('#p-save', root).onclick = async () => { try { ctx.account = await window.stella.invoke('account:update', { displayName: $('#p-name', root).value, bio: $('#p-bio', root).value, avatarColor: color }); ctx.refreshChrome(); toast('Профиль обновлён', 'success'); rerender(); } catch (e) { toast(e.message, 'error'); } };
    $('#p-pass', root).onclick = async () => { try { ctx.account = await window.stella.invoke('account:update', { oldPassword: $('#p-old', root)?.value || '', newPassword: $('#p-new', root).value }); toast('Пароль обновлён', 'success'); rerender(); } catch (e) { toast(e.message, 'error'); } };
    $('#p-logout', root).onclick = async () => { await window.stella.invoke('account:logout'); location.reload(); };
    $('#p-delete', root).onclick = async () => {
      const ok = await modal({ title: `${icon('alert')} Удалить аккаунт?`, body: 'Будут удалены все чаты, команды и воспоминания этого аккаунта.', className: 'danger', buttons: [{ label: 'Отмена', value: false }, { label: 'Удалить', value: true, danger: true }] });
      if (ok) { await window.stella.invoke('account:delete'); location.reload(); }
    };
  };
  return { html, bind };
}

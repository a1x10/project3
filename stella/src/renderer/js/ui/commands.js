// Вкладка «Команды»: свои фразы-триггеры → действия.
import { $, $$, h, escapeHtml, toast, modal } from './dom.js';
import { icon } from './icons.js';
import { pageHead, renderSettingsPage, sw, select, bindKeys } from './page.js';
import { ACTION_TYPES, EXAMPLE_COMMANDS } from '../core/commands.js';

export class CommandsPage {
  constructor(ctx) { this.ctx = ctx; this.root = $('#page-commands'); this.tab = 'editor'; this.list = []; this.sel = null; this.draft = null; this.q = ''; }

  async render() {
    if (this.tab === 'settings') return this.renderSettings();
    this.list = await window.stella.invoke('commands:list');
    this.ctx.chat.commands = this.list;
    this.root.innerHTML = pageHead('Команды', { tabs: [['editor', 'Редактор команд'], ['settings', 'Настройки']], active: this.tab }) + `
      <div class="cmd-layout">
        <div class="cmd-list">
          <div class="cmd-list-head"><h2>Команды</h2>
            <button class="icon-btn ghost" id="c-export" title="Экспорт">${icon('download')}</button>
            <button class="icon-btn ghost" id="c-import" title="Импорт">${icon('upload')}</button>
            <button class="icon-btn" id="c-add" title="Новая команда">${icon('plus')}</button></div>
          <label class="search">${icon('search')}<input id="c-search" placeholder="Поиск..." value="${escapeHtml(this.q)}"></label>
          <div class="cmd-items" id="c-items"></div>
        </div>
        <div class="cmd-editor" id="c-editor"></div>
      </div>`;
    $$('[data-ptab]', this.root).forEach((b) => b.onclick = () => { this.tab = b.dataset.ptab; this.render(); });
    $('#c-add', this.root).onclick = () => this.edit({ name: '', triggers: [], actions: [{ type: 'say', value: '' }], enabled: true });
    $('#c-export', this.root).onclick = async () => { const p = await window.stella.invoke('commands:export'); if (p) toast('Сохранено: ' + p, 'success'); };
    $('#c-import', this.root).onclick = async () => { try { const n = await window.stella.invoke('commands:import'); if (n !== null) { toast(`Импортировано команд: ${n}`, 'success'); this.render(); } } catch (e) { toast(e.message, 'error'); } };
    $('#c-search', this.root).oninput = (e) => { this.q = e.target.value; this.renderItems(); };
    this.renderItems();
    if (this.draft) this.renderEditor(); else this.renderPlaceholder();
  }

  renderItems() {
    const el = $('#c-items', this.root);
    const q = this.q.toLowerCase();
    const items = this.list.filter((c) => !q || c.name.toLowerCase().includes(q) || c.triggers.some((t) => t.includes(q)));
    if (!items.length) {
      el.innerHTML = `<div class="cmd-empty">${this.list.length ? 'Ничего не найдено' : 'Команд пока нет'}${this.list.length ? '' : '<br><br><button class="btn sm" id="c-examples">Добавить примеры</button>'}</div>`;
      const ex = $('#c-examples', el);
      if (ex) ex.onclick = async () => { for (const c of EXAMPLE_COMMANDS) await window.stella.invoke('commands:save', c); toast('Добавлено 5 примеров', 'success'); this.render(); };
      return;
    }
    el.innerHTML = '';
    for (const c of items) {
      const it = h(`<div class="cmd-item ${c.id === this.sel ? 'active' : ''} ${c.enabled === false ? 'off' : ''}">${icon('bolt', 16)}<div class="t"><b>${escapeHtml(c.name)}</b><small>«${escapeHtml(c.triggers.join('», «'))}»</small></div></div>`);
      it.onclick = () => this.edit(c);
      el.appendChild(it);
    }
  }

  renderPlaceholder() {
    $('#c-editor', this.root).innerHTML = `<div class="panel cmd-placeholder"><div class="big-ico">${icon('terminal', 28)}</div>Выбери команду из списка или создай новую</div>`;
  }

  edit(cmd) {
    this.sel = cmd.id || null;
    this.draft = JSON.parse(JSON.stringify(cmd));
    this.renderItems();
    this.renderEditor();
  }

  renderEditor() {
    const d = this.draft;
    const ed = $('#c-editor', this.root);
    ed.innerHTML = `<div class="panel">
      <h2 class="panel-title">${icon('bolt', 22)} ${d.id ? 'Редактирование' : 'Новая команда'}</h2>
      <div class="set"><h3>Название</h3><input class="input" id="e-name" value="${escapeHtml(d.name)}" placeholder="Например: Открыть YouTube"></div>
      <div class="set"><h3>Фразы-триггеры</h3><p>По одной в строке. <code>{query}</code> захватывает остаток фразы: «найди {query}». Имя ассистента в начале фразы можно не учитывать — оно убирается само.</p>
        <textarea class="input" id="e-trig" rows="3" placeholder="открой ютуб&#10;включи ютуб">${escapeHtml(d.triggers.join('\n'))}</textarea></div>
      <div class="set"><h3>Действия</h3><p>Выполняются по порядку. Действия с компьютером проходят ту же проверку безопасности, что и у ИИ.</p>
        <div id="e-actions"></div><button class="btn sm" id="e-add-act">${icon('plus', 14)} Добавить действие</button></div>
      <div class="set"><div class="set-row"><div class="lbl"><b>Включена</b></div><label class="switch"><input type="checkbox" id="e-on" ${d.enabled !== false ? 'checked' : ''}><span></span></label></div></div>
      <div class="set row" style="flex-wrap:wrap"><button class="btn primary" id="e-save">${icon('check', 16)} Сохранить</button><button class="btn" id="e-test">${icon('play', 16)} Проверить</button>${d.id ? `<button class="btn danger" id="e-del">${icon('trash', 16)} Удалить</button>` : ''}<button class="btn" id="e-cancel">Отмена</button></div>
    </div>`;
    const acts = $('#e-actions', ed);
    const drawActs = () => {
      acts.innerHTML = '';
      d.actions.forEach((a, i) => {
        const meta = ACTION_TYPES.find((t) => t[0] === a.type) || ACTION_TYPES[0];
        const row = h(`<div class="action-row"><span class="num">${i + 1}.</span><select class="select">${ACTION_TYPES.map(([v, l]) => `<option value="${v}" ${v === a.type ? 'selected' : ''}>${l}</option>`).join('')}</select><input class="input" value="${escapeHtml(a.value)}" placeholder="${escapeHtml(meta[2])}"><button class="icon-btn ghost" title="Удалить">${icon('x', 16)}</button></div>`);
        row.querySelector('select').onchange = (e) => { a.type = e.target.value; drawActs(); };
        row.querySelector('input').oninput = (e) => { a.value = e.target.value; };
        row.querySelector('button').onclick = () => { d.actions.splice(i, 1); drawActs(); };
        acts.appendChild(row);
      });
    };
    drawActs();
    const collect = () => ({ ...d, name: $('#e-name', ed).value, triggers: $('#e-trig', ed).value.split('\n'), enabled: $('#e-on', ed).checked });
    $('#e-add-act', ed).onclick = () => { d.actions.push({ type: 'say', value: '' }); drawActs(); };
    $('#e-save', ed).onclick = async () => {
      try { const saved = await window.stella.invoke('commands:save', collect()); this.sel = saved.id; this.draft = saved; toast('Команда сохранена', 'success'); this.ctx.avatar.play('nod'); await this.render(); }
      catch (e) { toast(e.message, 'error'); }
    };
    $('#e-test', ed).onclick = async () => {
      const c = collect();
      const first = c.triggers.map((t) => t.trim()).find(Boolean);
      if (!first) { toast('Добавьте фразу-триггер', 'error'); return; }
      const prev = this.ctx.chat.commands;
      this.ctx.chat.commands = [{ ...c, id: 'test', triggers: c.triggers.map((t) => t.trim().toLowerCase()).filter(Boolean) }];
      this.ctx.switchTab('home');
      await this.ctx.chat.runCustomCommand(first.replace('{query}', 'котики'));
      this.ctx.chat.commands = prev;
    };
    $('#e-cancel', ed).onclick = () => { this.draft = null; this.sel = null; this.renderItems(); this.renderPlaceholder(); };
    const del = $('#e-del', ed);
    if (del) del.onclick = async () => {
      const ok = await modal({ title: 'Удалить команду?', body: `«${escapeHtml(d.name)}»`, buttons: [{ label: 'Отмена', value: false }, { label: 'Удалить', value: true, danger: true }] });
      if (ok) { await window.stella.invoke('commands:delete', d.id); this.draft = null; this.sel = null; this.render(); }
    };
  }

  renderSettings() {
    const s = this.ctx.settings;
    renderSettingsPage(this.root, {
      title: 'Команды', tabs: [['editor', 'Редактор команд'], ['settings', 'Настройки']], active: 'settings', onTab: (t) => { this.tab = t; this.render(); },
      sections: [{ id: 'cmd', icon: 'bolt', label: 'Распознавание команд', html: sw(s, 'commandsEnabled', 'Выполнять свои команды', 'Если фраза совпала с триггером — действия выполняются сразу, без ИИ и без ключа OpenRouter.') + select(s, 'commandMatch', 'Режим совпадения', '«Содержит» — триггер может быть частью фразы. «Точно» — фраза должна совпасть целиком.', [['contains', 'Содержит'], ['exact', 'Точно']]) }],
    });
    bindKeys(this.root, this.ctx);
  }
}

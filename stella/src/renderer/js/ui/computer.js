import { $, $$, h, escapeHtml, toast, timeAgo } from './dom.js';
import { icon } from './icons.js';
import { renderSettingsPage, block, sw, range, bindKeys } from './page.js';

const QUICK = [
  ['camera', 'Скриншот', 'take_screenshot', {}], ['info', 'О системе', 'system_info', {}], ['list', 'Процессы', 'list_processes', {}],
  ['globe', 'Браузер', 'open_url', { url: 'https://www.google.com' }], ['folder', 'Загрузки', 'open_path', { path: '~/Downloads' }],
  ['music', 'Пауза/плей', 'media_control', { action: 'play_pause' }], ['monitor', 'Окна', 'list_windows', {}], ['clock', 'Время', 'get_datetime', {}],
  ['volume', 'Тише', 'media_control', { action: 'volume_down' }], ['lock', 'Блокировка', 'lock_screen', {}],
];
const MODES = [
  ['confirm_all', 'Спрашивать всё', 'Подтверждение для каждого действия, кроме анимаций и памяти.'],
  ['confirm_risky', 'Только рискованное', 'Чтение и безопасное — сами; запись файлов, мышь, клавиатура, команды — с подтверждением.'],
  ['autonomous', 'Полная автономия', 'Всё выполняется само. Опасное (системные файлы, выключение) всё равно подтверждается.'],
];

export class ComputerView {
  constructor(ctx) { this.ctx = ctx; this.root = $('#page-computer'); }

  async render() {
    const s = this.ctx.settings;
    const [defs, log] = await Promise.all([window.stella.invoke('tool:defs'), window.stella.invoke('actions:list')]);
    const mode = MODES.find((m) => m[0] === s.permissionMode) || MODES[1];
    renderSettingsPage(this.root, {
      title: 'Компьютер', search: 'Поиск...',
      sections: [
        { id: 'perm', icon: 'shield', label: 'Права', desc: 'Что ассистент может делать сам.', html: sw(s, 'computerControl', 'Разрешить управление ПК', 'Команды, файлы, приложения, мышь, клавиатура, окна.')
          + block('Режим подтверждений', mode[2], `<div class="seg-tabs" style="display:inline-flex">${MODES.map(([v, l]) => `<button data-mode="${v}" class="${v === mode[0] ? 'active' : ''}">${l}</button>`).join('')}</div>`)
          + range(s, 'commandTimeout', 'Таймаут команд терминала', 'Секунды.', 10, 300, 5) },
        { id: 'quick', icon: 'bolt', label: 'Быстрые действия', html: `<div class="set"><div class="quick-grid">${QUICK.map(([ic, l], i) => `<button class="quick" data-q="${i}">${icon(ic, 20)}${l}</button>`).join('')}</div><div id="quick-out"></div></div>` },
        { id: 'term', icon: 'terminal', label: 'Терминал', html: block('Выполнить команду', navigator.userAgent.includes('Windows') ? 'PowerShell' : 'bash / zsh', `<div class="row"><input class="input" id="term" placeholder="${navigator.userAgent.includes('Windows') ? 'Get-Date' : 'ls -la ~'}"><button class="btn" id="term-run">${icon('play', 14)} Выполнить</button></div><div id="term-out"></div>`) },
        { id: 'log', icon: 'history', label: 'Журнал действий', html: `<div class="set"><div class="row" style="justify-content:flex-end;margin-bottom:10px"><button class="btn sm" id="log-clear">Очистить</button></div><div id="log">${log.length ? '' : '<p class="hint">Здесь появятся действия, которые ассистент выполнил на компьютере.</p>'}</div></div>` },
        { id: 'tools', icon: 'cpu', label: `Возможности (${defs.length})`, html: `<div class="set"><div class="tools-list">${defs.map((d) => `<div class="tool-pill" title="${escapeHtml(d.description)}"><span>${escapeHtml(d.label || d.name)}</span><span class="badge ${d.risk}">${{ safe: 'безопасно', risky: 'риск', danger: 'опасно' }[d.risk]}</span></div>`).join('')}</div></div>` },
      ],
    });
    bindKeys(this.root, this.ctx);
    const r = this.root;
    const logEl = $('#log', r);
    for (const e of log.slice(0, 60)) logEl.appendChild(h(`<div class="log-item"><div class="top"><span class="badge ${e.ok ? 'ok' : 'danger'}">${e.ok ? 'OK' : 'ошибка'}</span><b>${escapeHtml(e.label || e.name)}</b><span class="time">${timeAgo(e.ts)}</span></div><pre>${escapeHtml(JSON.stringify(e.args || {}))}\n${escapeHtml(e.output || '')}</pre></div>`));
    $$('[data-mode]', r).forEach((b) => b.onclick = async () => { await this.ctx.updateSettings({ permissionMode: b.dataset.mode }); this.render(); });
    $$('.quick', r).forEach((b) => b.onclick = () => { const [, , name, args] = QUICK[b.dataset.q]; this.run(name, args, '#quick-out'); });
    const term = $('#term', r);
    const runTerm = () => { const c = term.value.trim(); if (c) this.run('run_command', { command: c }, '#term-out'); };
    $('#term-run', r).onclick = runTerm;
    term.addEventListener('keydown', (e) => { if (e.key === 'Enter') runTerm(); });
    $('#log-clear', r).onclick = async () => { await window.stella.invoke('actions:clear'); this.render(); };
  }

  async run(name, args, target) {
    const out = $(target, this.root);
    out.innerHTML = '<p class="hint" style="margin-top:12px">Выполняю…</p>';
    try {
      const r = await window.stella.invoke('tool:run', { name, args });
      out.innerHTML = `<pre class="out-pre"><span class="badge ${r.ok ? 'ok' : 'danger'}">${r.ok ? 'Готово' : 'Ошибка'}</span>\n${escapeHtml(r.output || '')}</pre>`;
      if (r.image) out.appendChild(h(`<img src="${r.image}" style="width:100%;border-radius:14px;margin-top:8px">`));
      if (r.ok) this.ctx.avatar.play('nod');
    } catch (e) { out.innerHTML = ''; toast(e.message, 'error'); }
  }

  async renderLogOnly() {
    if (this.ctx.activeTab !== 'computer') return;
    const log = await window.stella.invoke('actions:list');
    const logEl = $('#log', this.root); if (!logEl) return;
    logEl.innerHTML = '';
    for (const e of log.slice(0, 60)) logEl.appendChild(h(`<div class="log-item"><div class="top"><span class="badge ${e.ok ? 'ok' : 'danger'}">${e.ok ? 'OK' : 'ошибка'}</span><b>${escapeHtml(e.label || e.name)}</b><span class="time">${timeAgo(e.ts)}</span></div><pre>${escapeHtml(JSON.stringify(e.args || {}))}\n${escapeHtml(e.output || '')}</pre></div>`));
  }
}

// «Мастерская»: режим игры и дополнительные агенты.
import { $, $$, h, escapeHtml, toast } from './dom.js';
import { icon } from './icons.js';
import { renderSettingsPage, block, sw, range, bindKeys } from './page.js';

export const ANTIGRAVITY_URL = 'https://antigravity.google/';

export class WorkshopPage {
  constructor(ctx) {
    this.ctx = ctx;
    this.root = $('#page-workshop');
    this.tab = 'games';
    this.state = { follow: false, agent: false };
    this.log = [];
    window.stella.on('game:state', (st) => { this.state = st; if (this.ctx.activeTab === 'workshop') this.render(); });
    window.stella.on('game:log', (e) => {
      const line = e.step ? `— шаг ${e.step}` : e.done ? `✓ Готово: ${e.text || ''}` : `${e.ok ? '✓' : '✗'} ${e.label}: ${JSON.stringify(e.args || {})}`;
      this.log.push(line);
      if (this.log.length > 200) this.log.shift();
      const el = $('#game-log', this.root);
      if (el) { el.appendChild(h(`<div>${escapeHtml(line)}</div>`)); el.scrollTop = el.scrollHeight; }
    });
  }

  async render() {
    try { this.state = await window.stella.invoke('game:state'); } catch { /* */ }
    const s = this.ctx.settings;
    const p = this.ctx.persona();
    const sections = this.tab === 'games' ? [
      { id: 'follow', icon: 'sparkle', label: 'Компаньон в игре', desc: `${escapeHtml(p.name)} появляется поверх любой игры внизу экрана, бегает за курсором и комментирует происходящее.`, html: `
        ${block(this.state.follow ? '🟢 Компаньон в игре' : 'Позвать в игру', 'Окно не мешает кликам — все нажатия проходят в игру. Остановить: кнопкой ниже или Ctrl+Shift+F10.', `<div class="row"><button class="btn primary" id="g-follow">${this.state.follow ? 'Остановить' : `${icon('play', 14)} Запустить`}</button></div>`)}
        ${sw(s, 'gameComments', 'Комментировать игру', 'Раз в N секунд смотрит на экран (скриншот) и говорит короткую реплику. Нужен ИИ с поддержкой зрения.')}
        ${range(s, 'gameCommentSec', 'Как часто комментировать (секунды)', '', 20, 300, 5)}` },
      { id: 'agent', icon: 'cpu', label: 'Играть за меня', desc: 'Ассистент сам управляет игрой: смотрит скриншоты и нажимает клавиши/мышь.', html: `
        ${block('Окно игры', 'Часть заголовка окна — ассистент переключится на него перед стартом.', '<input class="input" id="g-win" placeholder="Например: Minecraft">')}
        ${block('Цель', 'Что нужно сделать в игре.', '<textarea class="input" id="g-goal" rows="3" placeholder="Например: дойди до дома впереди и открой дверь"></textarea>')}
        ${block('Максимум шагов', 'Каждый шаг — скриншот и несколько действий.', '<input class="input" id="g-steps" type="number" value="40" min="5" max="200" style="max-width:160px">')}
        <div class="set"><div class="row"><button class="btn primary" id="g-start" ${this.state.agent ? 'disabled' : ''}>${icon('play', 14)} Играть</button><button class="btn danger" id="g-stop" ${this.state.agent ? '' : 'disabled'}>Стоп (Ctrl+Shift+F10)</button></div>
        <p class="hint" style="margin-top:10px">Честно: агент делает 1 шаг за несколько секунд (скриншот → ИИ → действие). Подходит для спокойных игр, стратегий, головоломок, квестов и простой навигации. В быстрых шутерах и гонках он не успеет реагировать.</p>
        <div class="game-log" id="game-log">${this.log.map((l) => `<div>${escapeHtml(l)}</div>`).join('')}</div></div>` },
    ] : [
      { id: 'antigravity', icon: 'bolt', label: 'Google Antigravity', desc: 'Агентная среда разработки от Google. Стелла открывает её и передаёт ей задачи по программированию.', html: `
        <div class="set agent-card"><div class="agent-logo">✦</div><div>
          <h3 style="margin:0 0 6px">Antigravity</h3>
          <p style="margin:0 0 12px;color:var(--muted)">Отдельный продукт Google: нужен свой аккаунт Google и установка программы. После подключения можно сказать: «${escapeHtml(p.name)}, попроси Antigravity сделать сайт-портфолио» — ассистент откроет Antigravity и отправит задачу в чат её агента.</p>
          <div class="row" style="flex-wrap:wrap"><button class="btn primary" id="ag-open">${icon('link', 16)} Скачать и войти</button><button class="btn" id="ag-check">${icon('play', 16)} Проверить установку</button><button class="btn" id="ag-try">Отправить тестовую задачу</button></div>
        </div></div>
        ${sw(s, 'agentsEnabled', 'Разрешить передавать задачи агентам', 'Ассистент сможет вызывать Antigravity сам, когда задача большая.')}` },
      { id: 'how', icon: 'info', label: 'Как это работает', html: block('Порядок подключения', '', `<ol style="margin:0;padding-left:20px;line-height:1.9"><li>Нажми «Скачать и войти» — откроется сайт Antigravity.</li><li>Установи программу и войди своим аккаунтом Google.</li><li>Нажми «Проверить установку» — ассистент запустит Antigravity.</li><li>Дальше просто проси в чате: «передай Antigravity задачу …».</li></ol>`) },
    ];
    renderSettingsPage(this.root, { title: 'Мастерская', tabs: [['games', 'Игры'], ['agents', 'Агенты']], active: this.tab, onTab: (t) => { this.tab = t; this.render(); }, sections });
    bindKeys(this.root, this.ctx);
    const r = this.root;
    if (this.tab === 'games') {
      $('#g-follow', r).onclick = async () => {
        this.state = await window.stella.invoke('game:follow', { on: !this.state.follow, comment: s.gameComments, commentSec: s.gameCommentSec });
        toast(this.state.follow ? `${p.name} уже в игре! Ctrl+Shift+F10 — остановить` : 'Компаньон остановлен', 'info');
        this.render();
      };
      $('#g-start', r).onclick = async () => {
        const goal = $('#g-goal', r).value.trim();
        if (!goal) { toast('Опиши цель в игре', 'error'); return; }
        this.log = [];
        $('#game-log', r).innerHTML = '';
        window.stella.invoke('game:agent', { goal, windowTitle: $('#g-win', r).value.trim(), maxSteps: Number($('#g-steps', r).value) })
          .catch((e) => toast(e.message, 'error', 6000));
      };
      $('#g-stop', r).onclick = () => window.stella.invoke('game:stop');
    } else {
      $('#ag-open', r).onclick = () => window.stella.invoke('tool:run', { name: 'open_url', args: { url: ANTIGRAVITY_URL } });
      $('#ag-check', r).onclick = async () => {
        const res = await window.stella.invoke('tool:run', { name: 'launch_app', args: { name: 'Antigravity' } });
        toast(res.ok ? 'Antigravity найдена и запущена' : 'Antigravity не найдена — сначала установи её', res.ok ? 'success' : 'error', 6000);
      };
      $('#ag-try', r).onclick = () => { this.ctx.switchTab('home'); this.ctx.chat.send('Передай агенту Antigravity задачу: создай простую HTML-страницу «Привет от Стеллы» с красивым градиентом.'); };
    }
  }
}

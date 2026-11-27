import { $, $$, h, escapeHtml, toast, timeAgo, modal } from './dom.js';
import { icon } from './icons.js';
import { renderMarkdown } from '../core/markdown.js';
import { SpeechChunker, parseTags, stripTags } from '../core/tags.js';
import { mentionsName } from '../core/wakeword.js';
import { matchCommand, resolveActions, actionToTool } from '../core/commands.js';

const SUBTITLES = ['Играть или работать?', 'Чем займёмся?', 'Я слушаю ✦', 'Что сегодня делаем?'];
const QUICK = [
  ['💃', 'Станцуй для меня'],
  ['🖥', 'Сделай скриншот и скажи, что у меня на экране'],
  ['🎵', 'Открой YouTube и найди лофи музыку'],
  ['💾', 'Сколько свободной памяти на компьютере?'],
  ['📝', 'Создай на рабочем столе файл с планом на день'],
  ['⏰', 'Поставь таймер на 5 минут'],
];
const SKILLS = `Вот что я умею:
- **Болтать** и помнить важное о тебе
- **Двигаться**: танцевать, махать, прыгать, показывать эмоции
- **Говорить голосом** (ElevenLabs) и **слушать** — позови меня по имени
- **Управлять компьютером**: терминал, файлы, приложения, браузер, мышь, клавиатура, окна, скриншоты, громкость, таймеры
- **Команды** — свои фразы-триггеры во вкладке «Команды», работают даже без ИИ`;

export class ChatView {
  constructor(ctx) {
    this.ctx = ctx;
    this.convId = null;
    this.busy = false;
    this.attachments = [];
    this.req = null;
    this.commands = [];
    this.els = { home: $('#home'), list: $('#messages'), input: $('#input'), send: $('#btn-send'), title: $('#chat-title'), sub: $('#chat-sub'), history: $('#history'), attach: $('#attach-preview'), composer: $('.composer'), pop: $('#quick-pop') };
    this._bind();
    this._bindStream();
  }

  _bind() {
    const { input, send } = this.els;
    input.addEventListener('input', () => { this._autosize(); this._syncComposer(); if (input.value === '/') this.showPop('commands'); });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); this.sendFromInput(); }
      if (e.key === 'Escape') this.els.pop.classList.remove('show');
    });
    send.addEventListener('click', () => (this.busy ? this.abort() : this.sendFromInput()));
    $('#btn-newchat').addEventListener('click', () => this.newChat());
    $('#btn-plus').addEventListener('click', () => this.newChat());
    $('#btn-history').addEventListener('click', (e) => { e.stopPropagation(); this.toggleHistory(); });
    $('#btn-rename').addEventListener('click', () => this.rename());
    $('#btn-slash').addEventListener('click', (e) => { e.stopPropagation(); this.showPop('commands'); });
    $('#btn-quick').addEventListener('click', (e) => { e.stopPropagation(); this.showPop('quick'); });
    document.addEventListener('click', (e) => {
      if (!this.els.history.contains(e.target)) this.els.history.classList.remove('show');
      if (!this.els.pop.contains(e.target)) this.els.pop.classList.remove('show');
    });
    $('#btn-attach-screen').addEventListener('click', () => this.attachScreenshot());
    $$('#hero-links button').forEach((b) => b.onclick = () => {
      if (b.dataset.link === 'last') this.openLast();
      if (b.dataset.link === 'mic') this.ctx.updateSettings({ wakeWordEnabled: true }).then(() => toast(`Микрофон включён — позови меня: «${this.ctx.persona().name}, …»`, 'success', 5000));
      if (b.dataset.link === 'skills') this.showSkills();
    });
    this.els.list.addEventListener('click', (e) => {
      const c = e.target.closest('[data-copy]');
      if (c) { navigator.clipboard.writeText(c.closest('pre').querySelector('code').textContent); c.textContent = 'Скопировано'; setTimeout(() => (c.textContent = 'Копировать'), 1400); }
    });
  }

  _autosize() { const i = this.els.input; i.style.height = 'auto'; i.style.height = Math.min(180, i.scrollHeight) + 'px'; }
  _syncComposer() { this.els.composer.classList.toggle('has-text', !!this.els.input.value.trim() || this.attachments.length > 0); }
  _chatting(on) { this.els.home.classList.toggle('chatting', on); }

  updatePlaceholder() {
    const p = this.ctx.persona();
    $('#hero-pre').textContent = p.id === 'mark' ? 'твой' : 'твоя';
    $('#hero-name').textContent = p.name;
    this.els.input.title = 'Enter — отправить, Shift+Enter — новая строка, / — команды';
    this.els.sub.textContent = this.ctx.settings.model || '';
  }

  async init() {
    this.updatePlaceholder();
    await this.loadCommands();
    this.renderEmpty();
  }

  async loadCommands() { try { this.commands = await window.stella.invoke('commands:list'); } catch { this.commands = []; } }

  renderEmpty() {
    this.convId = null;
    this.els.list.innerHTML = '';
    this.els.title.textContent = 'Новый чат';
    $('#hero-sub').textContent = SUBTITLES[Math.floor(Math.random() * SUBTITLES.length)];
    this._chatting(false);
  }

  async newChat() {
    if (this.busy) this.abort();
    this.renderEmpty();
    this.els.input.focus();
  }

  async openLast() {
    const list = await window.stella.invoke('chat:list');
    if (list.length) this.open(list[0].id); else toast('Пока нет ни одного чата', 'info');
  }

  showSkills() {
    this._chatting(true);
    const t = this._addAssistantTurn();
    this._appendText(t, SKILLS, true);
    this.ctx.avatar.play('wave');
    this.ctx.avatar.setEmotion('happy', 4);
    this.ctx.speaker.enqueue('Вот что я умею! Болтать, танцевать, говорить голосом и управлять твоим компьютером.');
  }

  showPop(kind) {
    const pop = this.els.pop;
    pop.innerHTML = '';
    if (kind === 'commands') {
      pop.appendChild(h('<div class="qh">Мои команды</div>'));
      const cmds = this.commands.filter((c) => c.enabled !== false);
      if (!cmds.length) pop.appendChild(h(`<button class="qi">${icon('plus', 16)} Создать команду<small>вкладка «Команды»</small></button>`)).onclick = () => { pop.classList.remove('show'); this.ctx.switchTab('commands'); };
      for (const c of cmds) {
        const b = h(`<button class="qi">${icon('bolt', 16)} ${escapeHtml(c.name)}<small>${escapeHtml(c.triggers[0])}</small></button>`);
        b.onclick = () => { pop.classList.remove('show'); this.els.input.value = c.triggers[0].replace('{query}', '').trim() + (c.triggers[0].includes('{query}') ? ' ' : ''); this._syncComposer(); this.els.input.focus(); if (!c.triggers[0].includes('{query}')) this.sendFromInput(); };
        pop.appendChild(b);
      }
    } else {
      pop.appendChild(h('<div class="qh">Попробуй</div>'));
      for (const [e, t] of QUICK) { const b = h(`<button class="qi"><span>${e}</span> ${escapeHtml(t)}</button>`); b.onclick = () => { pop.classList.remove('show'); this.send(t); }; pop.appendChild(b); }
    }
    pop.classList.add('show');
  }

  async rename() {
    if (!this.convId) { toast('Сначала начни чат', 'info'); return; }
    const inp = h(`<input class="input" value="${escapeHtml(this.els.title.textContent)}">`);
    const name = await modal({ title: 'Название чата', body: inp, buttons: [{ label: 'Отмена', value: null }, { label: 'Сохранить', value: () => inp.value, primary: true }], dismissValue: null });
    if (name) { await window.stella.invoke('chat:rename', this.convId, name); this.els.title.textContent = name; }
  }

  async open(id) {
    const conv = await window.stella.invoke('chat:get', id);
    if (!conv) return this.renderEmpty();
    this.convId = conv.id;
    this.els.title.textContent = conv.title;
    this.els.list.innerHTML = '';
    this._chatting(true);
    const toolResults = {};
    for (const m of conv.messages) if (m.role === 'tool') toolResults[m.tool_call_id] = m.content;
    let turn = null;
    for (const m of conv.messages) {
      if (m.role === 'user') { turn = null; this._addUser(typeof m.content === 'string' ? m.content : '', [], m.ts); continue; }
      if (m.role !== 'assistant') continue;
      if (!turn) turn = this._addAssistantTurn(m.ts);
      if (m.content) this._appendText(turn, stripTags(m.content), true);
      for (const tc of m.tool_calls || []) {
        let args = {}; try { args = JSON.parse(tc.function.arguments || '{}'); } catch { /* */ }
        const out = toolResults[tc.id];
        this._toolCard(turn, { id: tc.id, name: tc.function.name, label: tc.function.name, args }, out === undefined ? null : { ok: !/^Ошибка|отклонил/.test(out), output: out });
      }
    }
    this._scroll(true);
  }

  async toggleHistory() {
    const el = this.els.history;
    if (el.classList.contains('show')) { el.classList.remove('show'); return; }
    const list = await window.stella.invoke('chat:list');
    el.innerHTML = list.length ? '' : '<div style="padding:12px;color:var(--dim)">История пуста</div>';
    for (const c of list) {
      const it = h(`<div class="history-item ${c.id === this.convId ? 'active' : ''}"><div class="t"><b>${escapeHtml(c.title)}</b><small>${timeAgo(c.updatedAt)} · ${c.count} сообщ.</small></div><button class="icon-btn ghost del" title="Удалить">${icon('trash', 16)}</button></div>`);
      it.addEventListener('click', async (e) => {
        if (e.target.closest('.del')) { e.stopPropagation(); await window.stella.invoke('chat:delete', c.id); it.remove(); if (c.id === this.convId) this.newChat(); return; }
        el.classList.remove('show'); this.open(c.id);
      });
      el.appendChild(it);
    }
    el.classList.add('show');
  }

  async attachScreenshot() {
    try {
      const r = await window.stella.invoke('tool:run', { name: 'take_screenshot', args: {} });
      if (!r.ok || !r.image) throw new Error(r.output || 'Не удалось сделать скриншот');
      this.attachments = [r.image];
      this.els.attach.innerHTML = '';
      const a = h(`<div class="att"><img src="${r.image}" alt="скриншот"><button title="Убрать">${icon('x', 12)}</button></div>`);
      a.querySelector('button').onclick = () => { this.attachments = []; this.els.attach.innerHTML = ''; this._syncComposer(); };
      this.els.attach.appendChild(a);
      this._syncComposer();
      toast('Скриншот прикреплён к сообщению', 'success');
    } catch (e) { toast(e.message, 'error'); }
  }

  sendFromInput() {
    const text = this.els.input.value.trim();
    if (!text && !this.attachments.length) return;
    this.els.input.value = '';
    this._autosize();
    this._syncComposer();
    this.send(text || 'Посмотри на мой экран.');
  }

  /** Пользовательская команда без ИИ. Возвращает true, если сработала. */
  async runCustomCommand(text) {
    if (!this.ctx.settings.commandsEnabled || this.attachments.length) return false;
    const m = matchCommand(text, this.commands, this.ctx.settings.commandMatch, this.ctx.persona().wakeWords);
    if (!m) return false;
    this._chatting(true);
    this._addUser(text, []);
    const turn = this._addAssistantTurn();
    turn.querySelector('.meta').textContent += ` · команда «${m.command.name}»`;
    const a = this.ctx.avatar;
    let i = 0;
    for (const act of resolveActions(m.command, m.query)) {
      if (act.type === 'say') { this._appendText(turn, act.value, true); this.ctx.say(act.value); continue; }
      if (act.type === 'animation') { a.play(act.value.trim()); continue; }
      if (act.type === 'emotion') { a.setEmotion(act.value.trim()); continue; }
      if (act.type === 'wait') { await new Promise((r) => setTimeout(r, Math.min(30000, Number(act.value) || 500))); continue; }
      const tool = actionToTool(act);
      if (!tool) continue;
      const id = 'cmd' + Date.now() + i++;
      this._toolCard(turn, { id, name: tool.name, label: tool.name, args: tool.args }, null);
      try { const r = await window.stella.invoke('tool:run', tool); this._toolCard(turn, { id }, r); }
      catch (e) { this._toolCard(turn, { id }, { ok: false, output: e.message }); }
    }
    this._scroll(true);
    return true;
  }

  async send(text, { voice = false } = {}) {
    if (this.busy) { toast('Подожди, я ещё отвечаю на прошлое сообщение', 'info'); return; }
    this.ctx.speaker.stop();
    this.ctx.presence?.userInteracted();
    if (await this.runCustomCommand(text)) return;
    this._chatting(true);
    if (!this.ctx.settings.hasOpenrouterKey) {
      this._addUser(text, []);
      const t = this._addAssistantTurn();
      this._appendText(t, 'Чтобы я могла думать, добавь ключ **OpenRouter** во вкладке **ИИ**. Ключ можно получить на openrouter.ai/keys 🔑\n\nА свои **Команды** работают и без ключа!', true);
      this.ctx.avatar.setEmotion('shy'); this.ctx.avatar.play('shrug');
      return;
    }
    const atts = this.attachments; this.attachments = []; this.els.attach.innerHTML = ''; this._syncComposer();
    this._addUser(text, atts);
    if (mentionsName(text, this.ctx.persona().wakeWords)) { this.ctx.avatar.setEmotion('happy', 3); if (!this.ctx.avatar.currentAction) this.ctx.avatar.play('nod'); }
    else if (!this.ctx.avatar.currentAction) this.ctx.avatar.play('think');
    this._setBusy(true);
    this.req = { turn: this._addAssistantTurn(), raw: '', seg: null, chunker: new SpeechChunker(), voice, actions: 0 };
    this._typing(true);
    try {
      const r = await window.stella.invoke('chat:send', { conversationId: this.convId, text, attachments: atts });
      if (r.conversationId !== this.convId) { this.convId = r.conversationId; const list = await window.stella.invoke('chat:list'); const c = list.find((x) => x.id === this.convId); if (c) this.els.title.textContent = c.title; }
    } catch (e) {
      this._finishWithError(e.message);
    }
  }

  abort() { window.stella.invoke('chat:abort'); this.ctx.speaker.stop(); }

  _setBusy(b) {
    this.busy = b;
    this.els.composer.classList.toggle('busy', b);
    this.els.send.classList.toggle('stop', b);
    this.els.send.innerHTML = icon(b ? 'stop' : 'send', 18);
    this.els.send.title = b ? 'Остановить' : 'Отправить';
    this.ctx.setState(b ? 'thinking' : (this.ctx.speaker.busy ? 'speaking' : 'idle'));
  }

  _bindStream() {
    const on = window.stella.on;
    on('chat:token', ({ token }) => {
      const r = this.req; if (!r) return;
      this._typing(false);
      r.raw += token;
      const { sentences, tags } = r.chunker.push(token);
      for (const t of tags) this._applyTag(t);
      for (const s of sentences) this.ctx.speaker.enqueue(stripTags(s));
      this._renderLive();
    });
    on('chat:tool', (t) => {
      const r = this.req; if (!r) return;
      this._typing(false);
      if (t.phase === 'start') {
        r.seg = null; r.raw = '';
        this._toolCard(r.turn, t, null);
        this.ctx.setState('working');
        if (t.name !== 'play_animation' && !this.ctx.avatar.currentAction && r.actions++ % 3 === 0) this.ctx.avatar.play('point');
      } else {
        this._toolCard(r.turn, t, { ok: t.ok, output: t.output, image: t.image });
        this.ctx.setState('thinking');
        this._typing(true);
      }
      this._scroll();
    });
    on('chat:warning', ({ message }) => { const r = this.req; if (r) r.turn.querySelector('.bubble').appendChild(h(`<div class="warn-line">${escapeHtml(message)}</div>`)); });
    on('chat:done', () => {
      const r = this.req; if (!r) return;
      this._typing(false);
      for (const s of r.chunker.flush()) this.ctx.speaker.enqueue(s);
      this._renderLive(true);
      const bubble = r.turn.querySelector('.bubble');
      if (!bubble.textContent.trim() && !bubble.querySelector('.tool-card')) this._appendText(r.turn, '…', true);
      this.req = null;
      this._setBusy(false);
    });
    on('chat:error', ({ message, aborted }) => this._finishWithError(message, aborted));
  }

  _finishWithError(message, aborted = false) {
    const r = this.req;
    this._typing(false);
    if (r) {
      r.turn.querySelector('.bubble').appendChild(h(`<div class="warn-line">${aborted ? '⏹ Остановлено' : '⚠️ ' + escapeHtml(message)}</div>`));
      this.req = null;
    }
    if (!aborted) { this.ctx.avatar.setEmotion('sad', 4); this.ctx.avatar.play('shrug'); }
    this._setBusy(false);
  }

  _applyTag(t) { if (t.type === 'emotion') this.ctx.avatar.setEmotion(t.name); else this.ctx.avatar.play(t.name); }

  _renderLive(final = false) {
    const r = this.req; if (!r) return;
    if (this._raf && !final) return;
    const draw = () => {
      this._raf = 0;
      if (!r.seg) { r.seg = h('<div class="seg-text"></div>'); r.turn.querySelector('.bubble').appendChild(r.seg); }
      r.seg.innerHTML = renderMarkdown(parseTags(r.raw).clean);
      this._scroll();
    };
    if (final) { cancelAnimationFrame(this._raf); draw(); } else this._raf = requestAnimationFrame(draw);
  }

  _typing(on) {
    const r = this.req; if (!r) return;
    const b = r.turn.querySelector('.bubble');
    let t = b.querySelector('.typing');
    if (on && !t) { t = h('<span class="typing"><i></i><i></i><i></i></span>'); b.appendChild(t); this._scroll(); }
    if (!on && t) t.remove();
    if (on && t) b.appendChild(t);
  }

  _addUser(text, atts = [], ts = Date.now()) {
    const acc = this.ctx.account;
    const el = h(`<div class="msg user"><div class="ava" style="background:${acc?.avatarColor || '#52525b'}">${escapeHtml((acc?.displayName || 'Я')[0].toUpperCase())}</div><div><div class="bubble">${renderMarkdown(text)}${atts.map((a) => `<img class="att" src="${a}" alt="вложение">`).join('')}</div><div class="meta" style="text-align:right">${new Date(ts).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}</div></div></div>`);
    this.els.list.appendChild(el);
    this._scroll(true);
  }

  _addAssistantTurn(ts = Date.now()) {
    const p = this.ctx.persona();
    const el = h(`<div class="msg assistant"><div class="ava">✦</div><div style="min-width:0;flex:1"><div class="bubble"></div><div class="meta">${escapeHtml(p.name)} · ${new Date(ts).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}</div></div></div>`);
    this.els.list.appendChild(el);
    this._scroll(true);
    return el;
  }

  _appendText(turn, text, md) {
    const seg = h('<div class="seg-text"></div>');
    seg.innerHTML = md ? renderMarkdown(text) : escapeHtml(text);
    turn.querySelector('.bubble').appendChild(seg);
  }

  _toolCard(turn, t, result) {
    const bubble = turn.querySelector('.bubble');
    let card = bubble.querySelector(`.tool-card[data-id="${CSS.escape(t.id || '')}"]`);
    if (!card) {
      const argStr = Object.entries(t.args || {}).map(([k, v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`).join(', ');
      card = h(`<details class="tool-card run" data-id="${escapeHtml(t.id || '')}"><summary><span class="st"></span><span class="name">${escapeHtml(t.label || t.name)}</span><span class="arg">${escapeHtml(argStr)}</span></summary></details>`);
      bubble.appendChild(card);
    }
    if (result) {
      card.classList.remove('run');
      card.classList.add(result.ok ? 'ok' : 'fail');
      card.querySelector('.st').innerHTML = icon(result.ok ? 'check' : 'x', 12);
      if (!card.querySelector('pre')) card.appendChild(h(`<pre>${escapeHtml(result.output || '')}</pre>`));
      if (result.image && !card.querySelector('img')) card.appendChild(h(`<img src="${result.image}" alt="скриншот">`));
    }
  }

  _scroll(force = false) {
    const l = this.els.list;
    const near = l.scrollHeight - l.scrollTop - l.clientHeight < 160;
    if (force || near) l.scrollTop = l.scrollHeight;
  }
}

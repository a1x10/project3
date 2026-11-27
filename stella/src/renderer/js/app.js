import { Avatar } from './avatar/avatar.js';
import { Speaker } from './ui/speech.js';
import { Listener } from './ui/listen.js';
import { ChatView } from './ui/chat.js';
import { AIPage, VoicePage, ModelPage, SettingsPage } from './ui/settings.js';
import { CommandsPage } from './ui/commands.js';
import { ComputerView } from './ui/computer.js';
import { WorkshopPage, ANTIGRAVITY_URL } from './ui/workshop.js';
import { Perch } from './ui/perch.js';
import { Presence } from './ui/presence.js';
import { showAuth } from './ui/auth.js';
import { doodleTile } from './ui/doodles.js';
import { $, $$, h, escapeHtml, toast, modal } from './ui/dom.js';
import { icon, hydrateIcons } from './ui/icons.js';
import { parseTags } from './core/tags.js';

const isCompanion = new URLSearchParams(location.search).get('mode') === 'companion';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const ctx = {
  settings: {}, account: null, info: null, activeTab: 'home', avatar: null, speaker: null, listener: null, chat: null, presence: null, pages: {},
  persona() { return this.info.personas[this.settings.persona] || this.info.personas.stella; },
  async updateSettings(patch) { this.settings = await window.stella.invoke('settings:set', patch); applySettings(); return this.settings; },
  setState(state) { setState(state); },
  say(text, { emotion, action } = {}) {
    const { clean, emotions, actions } = parseTags(text);
    if (emotion || emotions[0]) this.avatar.setEmotion(emotion || emotions[0]);
    if (action || actions[0]) this.avatar.play(action || actions[0]);
    this.speaker.enqueue(clean);
  },
  previewPersona(p) { loadPersonaModel(p); },
  async switchPersona(p) {
    if (this.account) this.account = await window.stella.invoke('account:update', { persona: p });
    else await this.updateSettings({ persona: p });
  },
  switchTab(t) { switchTab(t); },
  refreshChrome() { refreshChrome(); },
};
window.__stella = ctx;

// ---------- состояние ----------
const STATE_TEXT = { idle: 'онлайн', thinking: 'думает…', working: 'работает за компьютером…', speaking: 'говорит', hearing: 'слышит тебя…', recognizing: 'распознаёт…' };
let chatState = 'idle', micState = 'off';
function setState(s) {
  chatState = s;
  const chip = $('#persona-chip');
  const shown = ['hearing', 'recognizing', 'ptt'].includes(micState) ? (micState === 'ptt' ? 'hearing' : micState) : s;
  chip.className = 'avatar-state ' + ({ thinking: 'thinking busy', working: 'thinking busy', speaking: 'speaking busy', hearing: 'listening busy', recognizing: 'listening busy' }[shown] || '');
  $('#persona-state').textContent = STATE_TEXT[shown] || 'онлайн';
  refreshPills();
}

function refreshPills() {
  const s = ctx.settings;
  const pill = (k) => $(`.pill[data-pill="${k}"]`);
  pill('ai').classList.toggle('on', !!s.hasOpenrouterKey);
  pill('ai').innerHTML = `${icon('sparkles', 14)}AI${s.cloudActive ? ' ☁' : ''}`;
  pill('ai').classList.toggle('warn', !s.hasOpenrouterKey);
  pill('stt').classList.toggle('on', !!s.wakeWordEnabled);
  pill('tts').classList.toggle('on', !!s.ttsEnabled);
}

function refreshChrome() {
  const p = ctx.persona();
  $('#persona-name').textContent = p.name;
  document.title = p.id === 'mark' ? 'Mark' : 'Stella';
  $('#sb-user').textContent = ctx.account?.displayName || 'Гость';
  ctx.chat?.updatePlaceholder();
}

let lastDark = null;
function applySettings() {
  const s = ctx.settings;
  document.documentElement.style.setProperty('--accent', s.accent || '#8b5cf6');
  document.body.dataset.theme = s.background || 'white';
  const dark = ['chalk', 'graphite', 'midnight'].includes(document.body.dataset.theme);
  if (dark !== lastDark) { lastDark = dark; $('#bg').style.backgroundImage = doodleTile(dark); }
  document.body.classList.toggle('avatar-left', s.avatarSide === 'left');
  document.body.classList.toggle('avatar-right', s.avatarSide !== 'left');
  if (ctx.avatar) ctx.avatar.intensity = s.animationIntensity ?? 1;
  $('#btn-companion').classList.toggle('on', !!s.companionMode);
  refreshChrome();
  refreshPills();
  ctx.listener?.updateSensitivity();
  if (ctx.listener && !isCompanion) {
    if (s.wakeWordEnabled && ctx.listener.mode === 'off') ctx.listener.setWake(true);
    if (!s.wakeWordEnabled && ctx.listener.mode === 'wake') ctx.listener.setWake(false);
  }
}

// ---------- модель ----------
let loadedPersona = null;
async function loadPersonaModel(persona, onProgress) {
  if (loadedPersona === persona && !onProgress) return;
  const url = await window.stella.invoke('model:path', persona);
  try {
    await ctx.avatar.load(url, onProgress);
    loadedPersona = persona;
    ctx.avatar.setEmotion('happy', 3);
    ctx.avatar.play('greet');
  } catch (e) { toast('Не удалось загрузить модель: ' + e.message, 'error', 8000); throw e; }
}

function splashProgress(p, text) {
  $('#splash-bar').style.width = Math.round(p * 100) + '%';
  if (text) $('#splash-status').textContent = text;
}

// ---------- вкладки ----------
function switchTab(name) {
  ctx.activeTab = name;
  $$('.tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === name));
  $$('.page').forEach((v) => v.classList.toggle('active', v.dataset.page === name));
  const page = ctx.pages[name];
  if (page) page.render();
  setTimeout(() => ctx.perch?.check(), 30);
  if (name === 'home') setTimeout(() => $('#input').focus(), 50);
}

// ---------- меню ----------
function bindMenu() {
  const menu = $('#menu');
  $('#btn-menu').onclick = (e) => {
    e.stopPropagation();
    menu.innerHTML = '';
    const items = [
      ['user2', 'Профиль', () => { switchTab('settings'); setTimeout(() => ctx.pages.settings.render('account'), 50); }],
      ['plus', 'Новый чат', () => { switchTab('home'); ctx.chat.newChat(); }],
      ['history', 'История чатов', () => { switchTab('home'); setTimeout(() => ctx.chat.toggleHistory(), 50); }],
      null,
      ['grid', ctx.settings.companionMode ? 'Скрыть компаньона' : 'Режим компаньона', () => ctx.updateSettings({ companionMode: !ctx.settings.companionMode })],
      ['download', 'Экспорт чатов', () => window.stella.invoke('data:export').then((p) => p && toast('Сохранено: ' + p, 'success'))],
      ['info', 'О программе', showAbout],
      null,
      ['logout', 'Выйти из аккаунта', async () => { await window.stella.invoke('account:logout'); location.reload(); }],
    ];
    for (const it of items) {
      if (!it) { menu.appendChild(h('<hr>')); continue; }
      const b = h(`<button>${icon(it[0], 16)}${escapeHtml(it[1])}</button>`);
      b.onclick = () => { menu.classList.remove('show'); it[2](); };
      menu.appendChild(b);
    }
    menu.classList.toggle('show');
  };
  document.addEventListener('click', (e) => { if (!menu.contains(e.target)) menu.classList.remove('show'); });
}

function showAbout() {
  modal({ title: `${icon('sparkle')} Stella Assistant`, body: `<p>Живой 3D-ассистент: VRM-аватар, голос, команды и управление компьютером.</p><p>Персонажи: <b>Стелла</b> и <b>Марк</b>. ИИ — OpenRouter, голос — ElevenLabs.</p><p class="hint">Горячие клавиши: Ctrl+1…7 — вкладки, / — команды в поле ввода, Esc — остановить ответ.</p>` });
}

// ---------- подтверждение действий ----------
function bindConfirm() {
  window.stella.on('tool:confirm', async (q) => {
    const danger = q.level === 'danger';
    const argsText = Object.entries(q.args || {}).map(([k, v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`).join('\n');
    ctx.avatar.play('think');
    const ok = await modal({
      title: `${icon(danger ? 'alert' : 'shield')} ${escapeHtml(ctx.persona().name)} хочет: ${escapeHtml(q.label)}`,
      body: `<p style="margin-top:0">${danger ? '<b style="color:var(--danger)">Внимание: потенциально опасное действие.</b> ' : ''}${escapeHtml(q.reason)}.</p>${argsText ? `<pre>${escapeHtml(argsText)}</pre>` : ''}<p class="hint">Режим подтверждений можно изменить во вкладке «Компьютер».</p>`,
      className: danger ? 'danger' : '',
      buttons: [{ label: 'Отклонить', value: false }, { label: danger ? 'Да, выполнить' : 'Разрешить', value: true, primary: !danger, danger }],
      dismissValue: false,
    });
    await window.stella.invoke('tool:respond', { id: q.id, approved: ok });
  });
}

// ---------- микрофон ----------
function bindMic() {
  const btn = $('#btn-mic');
  let holding = false, downAt = 0;
  btn.addEventListener('pointerdown', async () => {
    if (!ctx.settings.hasElevenlabsKey) { toast('Для голосового ввода нужен ключ ElevenLabs (вкладка «Голос»)', 'info', 5000); return; }
    if (ctx.listener.mode === 'ptt') { holding = false; btn.classList.remove('rec'); await ctx.listener.stopPtt(); return; }
    holding = true; downAt = Date.now();
    ctx.speaker.stop();
    btn.classList.add('rec');
    await ctx.listener.startPtt();
  });
  const release = async () => {
    if (!holding || Date.now() - downAt < 350) return;
    holding = false; btn.classList.remove('rec');
    await ctx.listener.stopPtt();
  };
  btn.addEventListener('pointerup', release);
  btn.addEventListener('pointerleave', release);
}

function bindChrome() {
  $('#wc-min').onclick = () => window.stella.window.minimize();
  $('#wc-max').onclick = () => window.stella.window.maximize();
  $('#wc-close').onclick = () => window.stella.window.close();
  $('#btn-companion').onclick = () => ctx.updateSettings({ companionMode: !ctx.settings.companionMode });
  $$('.tab').forEach((t) => t.addEventListener('click', () => switchTab(t.dataset.tab)));
  const tabs = $$('.tab').map((t) => t.dataset.tab);
  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && /^[1-7]$/.test(e.key)) { switchTab(tabs[+e.key - 1]); e.preventDefault(); }
    if (e.key === 'Escape' && ctx.chat.busy) ctx.chat.abort();
  });
  $('#sb-user').onclick = () => { switchTab('settings'); setTimeout(() => ctx.pages.settings.render('account'), 50); };
  $('#sb-help').onclick = showAbout;
  $$('.pill').forEach((p) => p.onclick = () => {
    const k = p.dataset.pill;
    if (k === 'ai') return switchTab('ai');
    if (k === 'tts') return ctx.updateSettings({ ttsEnabled: !ctx.settings.ttsEnabled }).then(() => toast(ctx.settings.ttsEnabled ? 'Озвучка включена' : 'Озвучка выключена', 'info'));
    if (k === 'stt') {
      if (!ctx.settings.hasElevenlabsKey) { toast('Для распознавания речи нужен ключ ElevenLabs', 'info'); return switchTab('voice'); }
      return ctx.updateSettings({ wakeWordEnabled: !ctx.settings.wakeWordEnabled }).then(() => toast(ctx.settings.wakeWordEnabled ? `Слушаю! Позови: «${ctx.persona().name}, …»` : 'Микрофон выключен', 'info'));
    }
  });
  $$('#dock button').forEach((b) => b.addEventListener('click', () => {
    const a = b.dataset.act;
    if (ctx.avatar.currentAction === a) { ctx.avatar.stop(); return; }
    ctx.avatar.play(a, a === 'dance' ? { duration: 12 } : {});
    ctx.avatar.setEmotion(a === 'think' ? 'thinking' : 'happy', 4);
  }));
  ctx.avatar.on('action', (n) => $$('#dock button').forEach((b) => b.classList.toggle('active', b.dataset.act === n)));
  ctx.avatar.on('actionEnd', () => $$('#dock button').forEach((b) => b.classList.remove('active')));
}

function bindGlobalEvents() {
  window.stella.on('settings:changed', (s) => { ctx.settings = s; applySettings(); });
  window.stella.on('persona:changed', async (p) => {
    ctx.settings = await window.stella.invoke('settings:get');
    ctx.account = await window.stella.invoke('account:current');
    applySettings();
    loadedPersona = null;
    await loadPersonaModel(p).catch(() => {});
  });
  window.stella.on('avatar:command', ({ animation, emotion }) => { if (emotion) ctx.avatar.setEmotion(emotion); if (animation) ctx.avatar.play(animation); });
  window.stella.on('assistant:timer', ({ message }) => { ctx.say(`⏰ ${message}`, { emotion: 'surprised', action: 'wave' }); toast('⏰ ' + message, 'info', 10000); });
  window.stella.on('actions:changed', () => ctx.pages.computer.renderLogOnly());
  window.stella.on('memory:changed', () => toast('Запомнила 💜', 'success'));
  window.stella.on('assistant:say', ({ text }) => ctx.say(text));
}

let subTimer;
function showSubtitle(text) {
  const el = $('#subtitle');
  clearTimeout(subTimer);
  if (text) { el.textContent = text; el.classList.add('show'); }
  else subTimer = setTimeout(() => el.classList.remove('show'), 1200);
}

// ---------- первый запуск: предложение подключить агентов ----------
async function offerAgents() {
  await ctx.updateSettings({ agentsPromptShown: true });
  const ok = await modal({
    title: `${icon('sparkle')} Можно подключить дополнительных агентов`,
    body: `<p style="margin-top:0">${escapeHtml(ctx.persona().name)} умеет передавать большие задачи другим ИИ-агентам. Например, <b>Google Antigravity</b> — агентная среда для программирования: ассистент откроет её и отправит задачу в чат агента.</p><p class="hint">Antigravity — отдельный продукт Google, для него нужен свой аккаунт Google. Подключить можно в любой момент: Мастерская → Агенты.</p>`,
    buttons: [{ label: 'Позже', value: false }, { label: 'Подключить дополнительных агентов', value: true, primary: true }],
  });
  if (!ok) return;
  ctx.pages.workshop.tab = 'agents';
  switchTab('workshop');
  window.stella.invoke('tool:run', { name: 'open_url', args: { url: ANTIGRAVITY_URL } });
  ctx.say('Открываю сайт Antigravity. Установи программу и войди через аккаунт Google — а я потом буду передавать ей задачи!', { emotion: 'happy', action: 'point' });
}

// ---------- компаньон ----------
async function startCompanion() {
  document.body.classList.add('companion');
  ctx.info = await window.stella.invoke('app:info');
  ctx.settings = await window.stella.invoke('settings:get');
  ctx.avatar = new Avatar($('#avatar-canvas'), { transparent: true, compact: true });
  ctx.speaker = new Speaker({ avatar: ctx.avatar, getSettings: () => ({ ...ctx.settings, ttsEnabled: false }), onSubtitle: showSubtitle });
  $('#avatar-layer').appendChild(h(`<div class="companion-ctrl"><button class="sq" id="cmp-open" title="Открыть окно">${icon('chat', 16)}</button><button class="sq" id="cmp-close" title="Скрыть">${icon('x', 16)}</button></div>`));
  $('#cmp-open').onclick = () => window.stella.invoke('companion:focusMain');
  $('#cmp-close').onclick = () => window.stella.invoke('companion:toggle', false);
  ctx.avatar.on('touch', () => { ctx.avatar.play('wave'); ctx.avatar.setEmotion('happy', 3); });
  await ctx.avatar.load(await window.stella.invoke('model:path', ctx.settings.persona));
  ctx.avatar.frame('full', true);
  let buf = '';
  window.stella.on('chat:start', () => { buf = ''; ctx.avatar.play('think'); });
  window.stella.on('chat:token', ({ token }) => { buf += token; });
  window.stella.on('chat:done', () => { const { clean, emotions, actions } = parseTags(buf); if (emotions[0]) ctx.avatar.setEmotion(emotions[0]); if (actions[0]) ctx.avatar.play(actions[0]); ctx.speaker.enqueue(clean.slice(0, 160)); });
  window.stella.on('avatar:command', ({ animation, emotion }) => { if (emotion) ctx.avatar.setEmotion(emotion); if (animation) ctx.avatar.play(animation); });
  window.stella.on('persona:changed', async (p) => { ctx.settings = await window.stella.invoke('settings:get'); await ctx.avatar.load(await window.stella.invoke('model:path', p)); });
  window.stella.on('assistant:say', ({ text }) => { const { clean, emotions, actions } = parseTags(text); if (emotions[0]) ctx.avatar.setEmotion(emotions[0]); if (actions[0]) ctx.avatar.play(actions[0]); ctx.speaker.enqueue(clean); });
  window.stella.on('companion:move', ({ kind, dir }) => ctx.avatar.move(kind, dir));
  window.stella.on('companion:game', ({ on }) => { document.body.classList.toggle('game', on); if (on) ctx.avatar.setPosture('stand'); });
  // опустили окно к панели задач — садимся на её край
  window.stella.on('companion:perch', async ({ sit, bottom, winY }) => {
    if (!sit) { ctx.avatar.setPosture('stand'); return; }
    ctx.avatar.setPosture('sit');
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    const hip = ctx.avatar.screenPointOf('hips');
    if (hip) await window.stella.invoke('companion:sitAt', { y: bottom - hip.y + 4 });
    ctx.avatar.setEmotion('happy', 3);
  });
  setInterval(async () => {
    try { const c = await window.stella.invoke('system:cursor'); ctx.avatar.lookAt((c.x - (window.screenX + innerWidth / 2)) / (screen.width * 0.5), (c.y - (window.screenY + innerHeight * 0.3)) / (screen.height * 0.5)); } catch { /* */ }
  }, 100);
}

// ---------- запуск ----------
async function main() {
  hydrateIcons();
  if (isCompanion) return startCompanion();
  ctx.info = await window.stella.invoke('app:info');
  ctx.settings = await window.stella.invoke('settings:get');
  ctx.account = await window.stella.invoke('account:current');
  const persona = ctx.persona();
  $('#splash-pre').textContent = persona.id === 'mark' ? 'твой' : 'твоя';
  $('#splash-title').textContent = persona.name;
  const showSplash = ctx.settings.showSplash !== false;
  if (!showSplash) $('#splash').classList.add('done');

  ctx.avatar = new Avatar($('#avatar-canvas'), { transparent: true });
  ctx.avatar.controls.enableZoom = false;
  ctx.speaker = new Speaker({
    avatar: ctx.avatar,
    getSettings: () => ctx.settings,
    onState: (speaking) => setState(speaking ? 'speaking' : (ctx.chat?.busy ? 'thinking' : 'idle')),
    onSubtitle: showSubtitle,
    onError: (m) => toast('Голос: ' + m, 'error', 6000),
  });
  ctx.listener = new Listener({
    getSettings: () => ctx.settings,
    getNames: () => ctx.persona().wakeWords,
    isBusy: () => ctx.speaker.busy || ctx.chat?.busy,
    onCommand: (text) => { ctx.presence.userInteracted(); switchTab('home'); ctx.chat.send(text, { voice: true }); },
    onWake: () => ctx.presence.onWake(),
    onState: (s) => { micState = s; $('#listening-badge').classList.toggle('show', ['hearing', 'recognizing', 'ptt'].includes(s)); $('#listening-text').textContent = s === 'recognizing' ? 'Распознаю…' : 'Слушаю…'; setState(chatState); },
    onError: (m) => toast(m, 'error', 6000),
  });
  ctx.chat = new ChatView(ctx);
  ctx.pages = { workshop: new WorkshopPage(ctx), commands: new CommandsPage(ctx), model: new ModelPage(ctx), voice: new VoicePage(ctx), ai: new AIPage(ctx), computer: new ComputerView(ctx), settings: new SettingsPage(ctx) };
  ctx.presence = new Presence(ctx);
  applySettings();

  splashProgress(0.08, 'Зажигаю звёзды…');
  await sleep(showSplash ? 900 : 0);
  splashProgress(0.15, `Загружаю ${persona.id === 'mark' ? 'Марка' : 'Стеллу'}…`);
  try { await loadPersonaModel(ctx.settings.persona, (p) => splashProgress(0.15 + p * 0.75, `Загружаю модель… ${Math.round(p * 100)}%`)); }
  catch { splashProgress(0.9, 'Ошибка загрузки модели'); }
  splashProgress(1, 'Готово!');
  await sleep(showSplash ? 500 : 0);
  $('#splash').classList.add('done');
  $('#app').classList.add('ready');

  bindChrome(); bindMenu(); bindMic(); bindConfirm(); bindGlobalEvents();
  ctx.perch = new Perch(ctx);
  ctx.presence.start();

  if (!ctx.account) {
    ctx.account = await showAuth(ctx, { mode: (await window.stella.invoke('account:list')).length ? 'login' : 'register' });
    ctx.settings = await window.stella.invoke('settings:get');
    applySettings();
  }
  await ctx.chat.init();
  refreshChrome();
  if (!ctx.settings.agentsPromptShown) setTimeout(offerAgents, 2500);
  const p = ctx.persona();
  const name = ctx.account?.displayName;
  ctx.say(`${name ? `Привет, ${name}! ` : ''}${p.id === 'mark' ? 'Марк на связи. Чем займёмся?' : 'Я Стелла ✨ Рада тебя видеть!'}`, { emotion: 'happy', action: 'wave' });
}

main().catch((e) => { console.error(e); toast('Ошибка запуска: ' + e.message, 'error', 10000); $('#splash').classList.add('done'); $('#app').classList.add('ready'); });

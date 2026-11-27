// Страницы «ИИ», «Голос», «Модель» и «Настройки».
import { $, $$, h, escapeHtml, toast, modal } from './dom.js';
import { icon } from './icons.js';
import { renderSettingsPage, block, sw, range, select, adv, bindKeys, keyField } from './page.js';
import { profileSection } from './profile.js';
import { cloudSection } from './cloud.js';

const EL_MODELS = [['eleven_multilingual_v2', 'Multilingual v2 — лучшее качество'], ['eleven_flash_v2_5', 'Flash v2.5 — самая быстрая'], ['eleven_turbo_v2_5', 'Turbo v2.5 — баланс'], ['eleven_v3', 'Eleven v3 — максимум эмоций']];
const THEMES = [['white', 'Белый', '#fbfbfa'], ['paper', 'Бумага', '#f4efe4'], ['chalk', 'Мел', '#1b1b1d'], ['graphite', 'Графит', '#121212'], ['midnight', 'Полночь', '#151a24']];
const ACCENTS = ['#8b5cf6', '#a78bfa', '#f472b6', '#38bdf8', '#34d399', '#fbbf24', '#fb7185', '#e4e4e7'];
const ANIMS = [['wave', '👋', 'Помахать'], ['dance', '💃', 'Танец'], ['heart', '💖', 'Сердечко'], ['clap', '👏', 'Хлопки'], ['jump', '🦘', 'Прыжок'], ['spin', '🌀', 'Кружение'], ['bow', '🙇', 'Поклон'], ['think', '🤔', 'Думать'], ['victory', '✌️', 'Победа'], ['laugh', '😆', 'Смех'], ['shrug', '🤷', 'Пожать плечами'], ['stretch', '🙆', 'Потянуться'], ['nod', '🙂', 'Кивнуть'], ['shake', '🙅', 'Нет-нет'], ['shy', '☺️', 'Смущение'], ['sleepy', '😴', 'Сонная']];

// ================= ИИ =================
export class AIPage {
  constructor(ctx) { this.ctx = ctx; this.root = $('#page-ai'); this.tab = 'main'; this.models = null; }
  render() {
    const s = this.ctx.settings;
    const sections = this.tab === 'main' ? [
      { id: 'general', icon: 'personality', label: 'Общие', html: `
        ${select(s, 'provider', 'Провайдер ИИ', '', [['openrouter', 'OpenRouter']], 'wide')}
        ${s.cloudActive ? block('☁ Stella Cloud', `Ты вошёл в Stella Cloud — ИИ работает через сервер, свой ключ не нужен. Управление: Настройки → Stella Cloud.`, '') : ''}
        ${block('API Key', 'Свой ключ OpenRouter — <a href="https://openrouter.ai/keys" target="_blank">openrouter.ai/keys</a>. Не нужен, если ты в Stella Cloud.', keyField('or-key', s, s.hasOwnOpenrouterKey, 'sk-or-v1-…'))}
        ${block('Модель', 'Название модели (например, openai/gpt-4o-mini, anthropic/claude-sonnet-4). Для управления ПК нужна модель с инструментами 🛠, для скриншотов — со зрением 👁.', `<div class="row"><input class="input" id="model-input" value="${escapeHtml(s.model)}" autocomplete="off"><button class="icon-btn" id="or-load" title="Список моделей">${icon('list')}</button></div><div class="model-list" id="model-list"></div>`)}
        ${adv(range(s, 'temperature', 'Креативность', 'Выше — живее и неожиданнее, ниже — точнее.', 0, 1.5, 0.05) + range(s, 'maxTokens', 'Максимальная длина ответа', 'В токенах.', 200, 4000, 100))}
        ${block('Проверить работоспособность', 'Отправить тестовый запрос с текущими настройками и проверить, работает ли провайдер.', `<button class="btn" id="or-test">${icon('check', 16)} Проверить работоспособность</button>`)}` },
      { id: 'computer', icon: 'cpu', label: 'Управление ПК', html: `${sw(s, 'computerControl', 'Разрешить ИИ управлять компьютером', 'Подробные права — во вкладке «Компьютер».')}` },
    ] : [
      { id: 'persona', icon: 'personality', label: 'Характер', html: `
        ${block('Кто твой ассистент', 'Выбери персонажа — меняется модель, голос и характер.', personaCards(this.ctx))}
        ${block('Дополнительные инструкции', 'Как ассистенту себя вести: стиль речи, обращение, правила.', `<textarea class="input" rows="5" data-key="customInstructions" placeholder="Например: называй меня «капитан», шути чаще, отвечай коротко">${escapeHtml(s.customInstructions)}</textarea>`)}` },
      { id: 'initiative', icon: 'bolt', label: 'Инициатива', html: `${sw(s, 'proactive', 'Проявлять инициативу', 'Заговаривает сама после тишины, засыпает, когда тебя нет, и встречает при возвращении.')}${range(s, 'proactiveMinutes', 'Через сколько минут тишины заговорить', '', 3, 60, 1)}` },
    ];
    renderSettingsPage(this.root, { title: 'Настройки ИИ', tabs: [['main', 'Основной ИИ'], ['personality', 'Личность']], active: this.tab, onTab: (t) => { this.tab = t; this.render(); }, sections });
    bindKeys(this.root, this.ctx);
    bindPersonaCards(this.root, this.ctx);
    const r = this.root;
    if (this.tab !== 'main') return;
    const saveKey = async () => { const v = $('#or-key', r).value.trim(); if (!v) return; await this.ctx.updateSettings({ openrouterKey: v }); toast('Ключ сохранён', 'success'); this.render(); };
    $('#or-key', r).addEventListener('change', saveKey);
    $('#or-key-save', r).onclick = saveKey;
    $('#or-key', r).addEventListener('keydown', (e) => { if (e.key === 'Enter') saveKey(); });
    const mi = $('#model-input', r);
    mi.addEventListener('input', () => this.models && this._renderModels(mi.value));
    mi.addEventListener('change', () => this.ctx.updateSettings({ model: mi.value.trim() }));
    mi.addEventListener('keydown', (e) => { if (e.key === 'Enter') { $('#model-list', r).classList.remove('show'); this.ctx.updateSettings({ model: mi.value.trim() }).then(() => toast('Модель сохранена', 'success')); } });
    $('#or-load', r).onclick = () => this.loadModels();
    $('#or-test', r).onclick = async (e) => {
      const b = e.currentTarget; b.disabled = true; b.textContent = 'Проверяю…';
      try { const ans = await window.stella.invoke('llm:test'); toast(`Модель ответила: «${ans.slice(0, 60)}»`, 'success'); this.ctx.avatar.play('victory'); }
      catch (err) { toast(err.message, 'error', 7000); }
      b.disabled = false; b.innerHTML = `${icon('check', 16)} Проверить работоспособность`;
    };
  }
  async loadModels() {
    const ml = $('#model-list', this.root);
    ml.innerHTML = '<div class="model-item">Загрузка…</div>'; ml.classList.add('show');
    try { this.models = await window.stella.invoke('llm:models'); this._renderModels(''); }
    catch (e) { ml.innerHTML = `<div class="model-item">${escapeHtml(e.message)}</div>`; }
  }
  _renderModels(q) {
    const ml = $('#model-list', this.root);
    const query = String(q || '').toLowerCase();
    const list = this.models.filter((m) => !query || m.id.toLowerCase().includes(query) || m.name.toLowerCase().includes(query)).sort((a, b) => (b.tools - a.tools) || a.id.localeCompare(b.id)).slice(0, 100);
    ml.innerHTML = '';
    for (const m of list) {
      const it = h(`<div class="model-item"><span class="mid">${escapeHtml(m.id)}</span>${m.tools ? '<span title="Инструменты">🛠</span>' : ''}${m.vision ? '<span title="Зрение">👁</span>' : ''}<span class="price">${m.free ? 'бесплатно' : `$${m.promptPrice.toFixed(2)} / $${m.completionPrice.toFixed(2)}`}</span></div>`);
      it.onclick = () => { $('#model-input', this.root).value = m.id; ml.classList.remove('show'); this.ctx.updateSettings({ model: m.id }).then(() => toast('Модель: ' + m.id, 'success')); };
      ml.appendChild(it);
    }
    if (!list.length) ml.innerHTML = '<div class="model-item">Ничего не найдено — введи id вручную и нажми Enter</div>';
    ml.classList.add('show');
  }
}

function personaCards(ctx) {
  const cur = ctx.settings.persona;
  return `<div class="cards2">${Object.values(ctx.info.personas).map((x) => `<button class="persona-card ${x.id === cur ? 'active' : ''}" data-persona="${x.id}"><span class="check">${icon('check', 14)}</span><span class="emoji">${x.id === 'mark' ? '🧑‍💻' : '👩‍🚀'}</span><b>${x.name}</b><small>${escapeHtml(x.tagline)}</small></button>`).join('')}</div>`;
}
function bindPersonaCards(root, ctx) {
  $$('.persona-card[data-persona]', root).forEach((el) => el.onclick = async () => { await ctx.switchPersona(el.dataset.persona); $$('.persona-card[data-persona]', root).forEach((x) => x.classList.toggle('active', x === el)); });
}

// ================= ГОЛОС =================
export class VoicePage {
  constructor(ctx) { this.ctx = ctx; this.root = $('#page-voice'); this.tab = 'tts'; this.voices = null; }
  render() {
    const s = this.ctx.settings;
    const voiceSel = (key) => `<select class="select wide" data-key="${key}" id="sel-${key}"><option value="${escapeHtml(s[key])}">${escapeHtml(s[key])}</option></select>`;
    const sections = this.tab === 'tts' ? [
      { id: 'tts', icon: 'volume', label: 'Синтез речи', html: `
        ${sw(s, 'ttsEnabled', 'Озвучивать ответы', 'Говорит вслух и шевелит губами в такт речи.')}
        ${block('API Key ElevenLabs', 'Ключ: <a href="https://elevenlabs.io/app/settings/api-keys" target="_blank">elevenlabs.io → API Keys</a>. Без ключа — системный голос.', keyField('el-key', s, s.hasOwnElevenlabsKey, 'sk_…'))}
        ${select(s, 'elevenModel', 'Модель синтеза', '', EL_MODELS)}
        ${block('Голос Стеллы', '', voiceSel('voiceStella'))}
        ${block('Голос Марка', `<button class="btn sm" id="voices-load">${icon('refresh', 14)} Загрузить голоса из аккаунта</button> <span class="hint" id="el-usage"></span>`, voiceSel('voiceMark'))}
        ${range(s, 'volume', 'Громкость', '', 0, 1, 0.05, true)}
        ${adv(range(s, 'voiceStability', 'Стабильность', 'Ниже — эмоциональнее, выше — ровнее.', 0, 1, 0.05) + range(s, 'voiceStyle', 'Выразительность', '', 0, 1, 0.05) + range(s, 'voiceSpeed', 'Скорость речи', '', 0.7, 1.2, 0.05) + sw(s, 'systemVoiceFallback', 'Системный голос как запасной', 'Если ElevenLabs недоступен.'))}
        ${block('Проверка', 'Если голос не работает — нажми «Проверить ключ»: покажу точную причину.', `<div class="row"><button class="btn" id="el-check">${icon('shield', 14)} Проверить ключ</button><button class="btn" id="voice-test">${icon('play', 14)} Прослушать голос</button></div>`)}` },
    ] : [
      { id: 'stt', icon: 'mic', label: 'Распознавание', html: `
        ${sw(s, 'wakeWordEnabled', 'Откликаться на имя', 'Микрофон слушает постоянно: скажи «Стелла, …» или «Марк, …». Распознавание — ElevenLabs Scribe (тратит символы тарифа).')}
        ${select(s, 'sttLanguage', 'Язык распознавания', '', [['rus', 'Русский'], ['eng', 'English'], ['ukr', 'Українська'], ['auto', 'Автоопределение']])}
        ${range(s, 'micSensitivity', 'Чувствительность микрофона', 'Выше — слышит тише, но чаще реагирует на шум.', 0, 1, 0.05, true)}` },
    ];
    renderSettingsPage(this.root, { title: 'Голос', tabs: [['tts', 'Синтез (TTS)'], ['stt', 'Распознавание (STT)']], active: this.tab, onTab: (t) => { this.tab = t; this.render(); }, sections });
    bindKeys(this.root, this.ctx);
    if (this.tab !== 'tts') return;
    const r = this.root;
    const saveKey = async () => { const v = $('#el-key', r).value.trim(); if (!v) return; await this.ctx.updateSettings({ elevenlabsKey: v }); toast('Ключ сохранён', 'success'); this.render(); };
    $('#el-key', r).addEventListener('change', saveKey);
    $('#el-key-save', r).onclick = saveKey;
    $('#el-check', r).onclick = () => this.checkKey();
    $('#el-key', r).addEventListener('keydown', (e) => { if (e.key === 'Enter') saveKey(); });
    $('#voices-load', r).onclick = () => this.loadVoices(false);
    $('#voice-test', r).onclick = () => { this.ctx.speaker.stop(); this.ctx.say(this.ctx.persona().id === 'mark' ? 'Привет! Я Марк. Так звучит мой голос.' : 'Привет! Я Стелла, и так звучит мой голос!', { emotion: 'happy', action: 'wave' }); };
    if (s.hasElevenlabsKey) this.loadVoices(true);
  }
  async checkKey() {
    const btn = $('#el-check', this.root);
    btn.disabled = true; btn.textContent = 'Проверяю…';
    try {
      const r = await window.stella.invoke('tts:check');
      await modal({
        title: `${icon(r.ok ? 'check' : 'alert')} ${r.ok ? 'ElevenLabs работает' : 'ElevenLabs: найдена проблема'}`,
        body: `<div>${r.steps.map((st) => `<div class="set-row" style="padding:8px 0;border-bottom:1px solid var(--border);align-items:flex-start"><b style="min-width:170px">${st.ok ? '✅' : '❌'} ${escapeHtml(st.name)}</b><span style="flex:1;color:var(--${st.ok ? 'muted' : 'danger'})">${escapeHtml(st.info)}</span></div>`).join('')}</div>${r.ok ? '' : '<p class="hint">Важны «Пробный синтез» и первая ошибка в списке. «Тариф» и «Голоса» могут не работать у ключей с ограниченными правами — это не мешает озвучке.</p>'}`,
      });
      if (r.ok) { this.ctx.speaker.elevenFailed = false; this.ctx.say('Ура, голос работает!', { emotion: 'happy', action: 'victory' }); }
    } catch (e) { toast(e.message, 'error', 8000); }
    btn.disabled = false; btn.innerHTML = `${icon('shield', 14)} Проверить ключ`;
  }

  async loadVoices(quiet) {
    try {
      this.voices ||= await window.stella.invoke('tts:voices');
      const s = this.ctx.settings;
      for (const key of ['voiceStella', 'voiceMark']) {
        const sel = $('#sel-' + key, this.root); if (!sel) continue;
        sel.innerHTML = this.voices.map((v) => `<option value="${v.id}" ${s[key] === v.id ? 'selected' : ''}>${escapeHtml(v.name)}${v.gender ? ' · ' + (v.gender === 'female' ? 'жен.' : v.gender === 'male' ? 'муж.' : v.gender) : ''}</option>`).join('');
        if (!this.voices.some((v) => v.id === s[key])) sel.insertAdjacentHTML('afterbegin', `<option value="${escapeHtml(s[key])}" selected>${escapeHtml(s[key])} (текущий)</option>`);
      }
      if (!quiet) toast(`Загружено голосов: ${this.voices.length}`, 'success');
      window.stella.invoke('tts:subscription').then((u) => { const el = $('#el-usage', this.root); if (el && u.limit) el.textContent = `${u.used.toLocaleString('ru-RU')} / ${u.limit.toLocaleString('ru-RU')} символов`; }).catch(() => {});
    } catch (e) { if (!quiet) toast(e.message, 'error'); }
  }
}

// ================= МОДЕЛЬ =================
export class ModelPage {
  constructor(ctx) { this.ctx = ctx; this.root = $('#page-model'); }
  render() {
    const s = this.ctx.settings;
    const file = (p) => (p ? escapeHtml(p.split(/[\\/]/).pop()) : 'встроенная');
    renderSettingsPage(this.root, {
      title: 'Модель', search: 'Поиск настроек...',
      sections: [
        { id: 'char', icon: 'personality', label: 'Персонаж', html: `${block('Ассистент', 'Какую модель вы хотите: Стелла или Марк.', personaCards(this.ctx))}
          ${select(this.ctx.settings, 'markModel', 'Модель Марка', 'Новая чиби-модель или классический процедурный Марк.', [['nick', 'Чиби (новая)'], ['classic', 'Классический']])}
          ${block('Своя VRM-модель', `Стелла: ${file(s.customModelStella)} · Марк: ${file(s.customModelMark)}`, `<div class="row" style="flex-wrap:wrap"><button class="btn" id="vrm-stella">${icon('upload', 16)} Для Стеллы</button><button class="btn" id="vrm-mark">${icon('upload', 16)} Для Марка</button><button class="btn" id="vrm-reset">Сбросить</button></div>`)}` },
        { id: 'anim', icon: 'sparkles', label: 'Анимации', html: block('Проиграть анимацию', 'Нажми, чтобы посмотреть движение.', `<div class="anim-grid">${ANIMS.map(([a, e, l]) => `<button data-anim="${a}"><span>${e}</span>${l}</button>`).join('')}</div>`) + range(s, 'animationIntensity', 'Амплитуда движений', '', 0.3, 1.5, 0.05, true) },
        { id: 'behavior', icon: 'bolt', label: 'Поведение', html: sw(s, 'lookAtCursor', 'Следить за курсором', 'Голова и глаза поворачиваются за мышью — даже вне окна.') + sw(s, 'idleAnimations', 'Живое поведение', 'Сама потягивается, оглядывается, иногда пританцовывает.') },
        { id: 'place', icon: 'panel', label: 'Расположение', html: select(s, 'avatarSide', 'Сторона экрана', 'Где стоит аватар в окне.', [['right', 'Справа'], ['left', 'Слева']]) + block('Камера', '', `<div class="row"><button class="btn" data-frame="full">Во весь рост</button><button class="btn" data-frame="upper">По пояс</button><button class="btn" data-frame="portrait">Портрет</button></div>`) + sw(s, 'companionMode', 'Режим компаньона', 'Маленький аватар поверх всех окон Windows.') },
      ],
    });
    bindKeys(this.root, this.ctx);
    bindPersonaCards(this.root, this.ctx);
    const r = this.root;
    $$('[data-anim]', r).forEach((b) => b.onclick = () => this.ctx.avatar.play(b.dataset.anim, b.dataset.anim === 'dance' ? { duration: 10 } : {}));
    $$('[data-frame]', r).forEach((b) => b.onclick = () => this.ctx.avatar.frame(b.dataset.frame));
    const pick = async (p) => { try { if (await window.stella.invoke('model:pick', p)) { toast('Модель загружена', 'success'); this.ctx.settings = await window.stella.invoke('settings:get'); this.render(); } } catch (e) { toast(e.message, 'error'); } };
    $('#vrm-stella', r).onclick = () => pick('stella');
    $('#vrm-mark', r).onclick = () => pick('mark');
    $('#vrm-reset', r).onclick = async () => { await this.ctx.updateSettings({ customModelStella: '', customModelMark: '' }); this.render(); };
  }
}

// ================= НАСТРОЙКИ =================
export class SettingsPage {
  constructor(ctx) { this.ctx = ctx; this.root = $('#page-settings'); }
  async render(focus) {
    const s = this.ctx.settings;
    const prof = await profileSection(this.ctx);
    const cloud = await cloudSection(this.ctx);
    const info = await window.stella.invoke('app:info');
    renderSettingsPage(this.root, {
      title: 'Настройки', search: 'Поиск настроек...',
      sections: [
        { id: 'general', icon: 'personality', label: 'Общие', desc: 'Язык и основные параметры.', html: select(s, 'lang', 'Язык', 'Язык интерфейса приложения.', [['ru', 'RU  Русский']]) + sw(s, 'showSplash', 'Заставка при запуске', 'Логотип и анимация загрузки модели.') },
        { id: 'look', icon: 'sun', label: 'Внешний вид', desc: 'Фон и цвета.', html: block('Фон', '', `<div class="theme-grid">${THEMES.map(([v, l, c]) => `<div class="theme-opt ${s.background === v ? 'active' : ''}" data-theme="${v}" style="background:${c}">${l}</div>`).join('')}</div>`) + block('Акцентный цвет', '', `<div class="swatches">${ACCENTS.map((c) => `<div class="swatch ${s.accent === c ? 'active' : ''}" data-accent="${c}" style="background:${c}"></div>`).join('')}</div>`) },
        { id: 'autostart', icon: 'bolt', label: 'Автозапуск', desc: 'Запуск вместе с системой.', html: sw(s, 'launchAtStartup', 'Запускать вместе с Windows', 'Ассистент будет готов сразу после входа в систему.') + sw(s, 'companionMode', 'Открывать режим компаньона', 'Аватар поверх всех окон.') },
        { id: 'account', icon: 'user2', label: 'Аккаунт', desc: 'Профиль, память и безопасность.', html: prof.html },
        { id: 'cloud', icon: 'globe', label: 'Stella Cloud', desc: 'Сервер с подписками: ИИ и голос без своих ключей.', html: cloud.html },
        { id: 'data', icon: 'database', label: 'Данные', desc: `Хранятся локально: ${escapeHtml(info.userData)}`, html: block('Экспорт', 'Сохранить чаты и воспоминания в файл JSON.', `<button class="btn" id="data-export">${icon('download', 16)} Экспорт чатов</button>`) + block('Сброс', 'Удалить аккаунты, чаты, команды, память и ключи.', `<button class="btn danger" id="data-reset">${icon('trash', 16)} Сбросить всё</button>`) },
      ],
    });
    bindKeys(this.root, this.ctx);
    const r = this.root;
    prof.bind(r, () => this.render('account'));
    cloud.bind(r, async () => { this.ctx.settings = await window.stella.invoke('settings:get'); this.render('cloud'); });
    $$('.theme-opt', r).forEach((el) => el.onclick = async () => { await this.ctx.updateSettings({ background: el.dataset.theme }); this.render(); });
    $$('.swatch[data-accent]', r).forEach((el) => el.onclick = async () => { await this.ctx.updateSettings({ accent: el.dataset.accent }); this.render(); });
    $('#data-export', r).onclick = async () => { try { const p = await window.stella.invoke('data:export'); if (p) toast('Сохранено: ' + p, 'success'); } catch (e) { toast(e.message, 'error'); } };
    $('#data-reset', r).onclick = async () => {
      const ok = await modal({ title: `${icon('alert')} Сбросить все данные?`, body: 'Будут удалены аккаунты, чаты, команды, память и ключи API. Это нельзя отменить.', className: 'danger', buttons: [{ label: 'Отмена', value: false }, { label: 'Удалить всё', value: true, danger: true }] });
      if (ok) { await window.stella.invoke('settings:reset'); location.reload(); }
    };
    if (focus) { const el = $('#sec-' + focus, r); const c = $('.content', r); if (el) c.scrollTop = el.offsetTop - c.offsetTop; }
  }
}

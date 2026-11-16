// «Мозг»: кто думает (провайдеры и модели по ролям), характер, понимание чата (что она делает сама),
// заметки для ИИ и проверка «что она поймёт и как ответит».
import { ago, busy, card, clock, del, emptyState, get, h, icon, modal, on, post, put, saveBar, segmented, toast, toggle } from '../lib.js';

const ROLES = [
  ['chat', 'Ответы на вопросы', 'spark', 'Объясняет задания, отвечает в группе и в личке'],
  ['understand', 'Понимание чата', 'brain', 'Читает сообщения: о чём, кому, что сделать. Нужна быстрая модель'],
  ['vision', 'Фото заданий', 'image', 'Понимает фото из учебника. Нужна модель с поддержкой фото'],
];
const PROVIDERS = [['auto', 'Авто'], ['openrouter', 'OpenRouter'], ['groq', 'Groq']];
const PNAME = { openrouter: 'OpenRouter', groq: 'Groq', backup: 'Запасной ИИ' };
const TONES = [
  ['friendly', '🤝', 'Подруга-отличница', 'Тепло, просто, поддерживает'],
  ['chill', '😎', 'Своя в чате', 'Коротко, по-свойски, лёгкий сленг'],
  ['tutor', '🎓', 'Репетитор', 'Спокойно, по шагам, наводящие вопросы'],
  ['strict', '📏', 'Строгая', 'Собранно и по делу, без шуток'],
  ['fun', '😄', 'С юмором', 'Весело, с шутками, но с пользой'],
];
const MODES = [
  ['all', 'Слушать всё', 'Читает каждое сообщение и сама решает, вмешаться ли. Больше всего запросов к ИИ'],
  ['smart', 'Умный', 'Читает сообщения про учёбу и ДЗ (и когда зовут). Экономит лимиты — рекомендуется'],
  ['mention', 'Только когда зовут', '@упоминание, ответ на её сообщение или «бот, …»'],
  ['off', 'Выключен', 'Без ИИ — только ДЗ по расписанию и команды'],
];
const ACTIONS = [
  ['sendHomework', 'Присылать ДЗ', '«что задали на завтра?» — фото из дневника'],
  ['sendSchedule', 'Присылать расписание', '«какие завтра уроки?»'],
  ['askTask', 'Просить полный пример', '«как решить №250?» — ответит с цитатой: «скинь сюда весь пример», а потом решит'],
  ['answer', 'Отвечать на вопросы по учёбе', 'Объяснить тему, литература, история, задача с условием'],
  ['react', 'Реакции на «спасибо»', 'Поставит ❤️ вместо лишнего сообщения'],
];
const DONE_CLASS = { 'ответила': 'ok', 'прислала ДЗ': 'ok', 'прислала расписание': 'ok', 'попросила пример': 'acc', 'реакция': 'acc' };
const ACTION_TEXT = { send_homework: 'пришлёт ДЗ', send_schedule: 'пришлёт расписание', ask_task: 'попросит прислать пример', answer: 'ответит', react: 'поставит реакцию ❤️', ignore: 'промолчит' };
const ACTION_INF = { send_homework: 'прислать ДЗ', send_schedule: 'прислать расписание', ask_task: 'попросить пример', answer: 'ответить', react: 'поставить реакцию', ignore: 'промолчать' };
// Проверенные варианты: «~…-latest» — псевдонимы OpenRouter, всегда ведут на свежую версию модели
const RECOMMENDED = {
  'openrouter/free': 'бесплатно: OpenRouter сам выберет доступную бесплатную модель',
  '~deepseek/deepseek-flash-latest': 'очень дёшево, умная, понимает фото — лучший выбор за деньги',
  '~z-ai/glm-flash-latest': 'самая дешёвая из толковых, понимает фото',
  '~openai/gpt-luna-latest': 'дёшево и аккуратно, понимает фото',
  '~anthropic/claude-haiku-latest': 'дёшево, очень живой русский язык, понимает фото',
  '~google/gemini-flash-latest': 'дороже, сильная в задачах и на фото',
};
const TABS = [['brain', 'Ум'], ['persona', 'Характер'], ['understand', 'Понимание'], ['notes', 'Заметки'], ['test', 'Проверка']];

export async function render(root, { params = [] } = {}) {
  let fields = {};
  let draft = {};
  let status = null;
  let tab = TABS.some(([id]) => id === params[0]) ? params[0] : 'brain';
  const offs = [];

  const bar = saveBar({
    onSave: async () => {
      const values = {};
      for (const [p, v] of Object.entries(draft)) if (JSON.stringify(v) !== JSON.stringify(fields[p])) values[p] = v;
      const r = await put('/api/settings', { values });
      apply(r.fields);
      status = await get('/api/ai/status');
      draw();
      toast('Сохранено — она уже думает по-новому');
    },
    onReset: () => {
      draft = structuredClone(fields);
      draw();
    },
  });
  const set = (p, v) => {
    draft[p] = v;
    if (Object.keys(draft).some((k) => JSON.stringify(draft[k]) !== JSON.stringify(fields[k]))) bar.show();
    else bar.hide();
  };
  const apply = (list) => {
    fields = Object.fromEntries(list.filter((f) => f.group === 'ai').map((f) => [f.path, f.value]));
    draft = structuredClone(fields);
    bar.hide();
  };
  const option = (title, sub, control) => h('div.opt', h('div.opt-text', h('b', title), h('span', sub)), control);

  const tabs = segmented(TABS, tab, (v) => {
    tab = v;
    history.replaceState(null, '', `#/ai/${v}`);
    draw();
  }, { cls: 'tabs' });
  const body = h('div.stack');
  root.append(h('div.stack', tabs, body));

  // --- Ум ---
  function brainTab() {
    const st = status.router;
    const providerCard = (id, hint) => {
      const ok = st.providers[id]?.hasKey;
      const s = st.stats[id];
      return h(`section.card.stat.${ok ? 'ok' : 'warn'}`,
        h('div.stat-top', h('span.stat-ico', icon(id === 'backup' ? 'shield' : 'key')), PNAME[id], h(`i.dot.${ok ? 'ok' : 'warn'}`)),
        h('div.stat-val', ok ? 'Подключён' : 'Нет ключа'),
        h('div.stat-sub', s ? `ответов ${s.ok} · сбоев ${s.fail}${s.lastError ? ` · ${s.lastError.slice(0, 60)}` : ''}` : ok ? 'ещё не использовался' : hint));
    };
    const roles = ROLES.map(([role, title, ico, sub]) => {
      const route = draft['ai.routing']?.[role] || { provider: 'auto', model: '' };
      const live = st.roles[role];
      const defaultFor = (prov) => status.defaults[(prov === 'auto' ? (st.providers.openrouter.hasKey ? 'openrouter' : 'groq') : prov)]?.[role] || '';
      const model = h('input.input.sm', { value: route.model, placeholder: `по умолчанию: ${defaultFor(route.provider)}`, spellcheck: false, style: { flex: 1, minWidth: '200px' } });
      model.onchange = () => set('ai.routing', { ...draft['ai.routing'], [role]: { ...route, model: model.value.trim() } });
      const provider = h('select.select.sm', { style: { width: '150px' } }, PROVIDERS.map(([v, t]) => h('option', { value: v, selected: route.provider === v }, t)));
      provider.onchange = () => {
        set('ai.routing', { ...draft['ai.routing'], [role]: { provider: provider.value, model: '' } });
        draw();
      };
      const pick = h('button.btn.btn-sm', { type: 'button' }, icon('search'), 'Выбрать');
      pick.onclick = () => pickModel(provider.value === 'groq' ? 'groq' : 'openrouter', role, (id) => {
        model.value = id;
        set('ai.routing', { ...draft['ai.routing'], [role]: { provider: provider.value === 'groq' ? 'groq' : 'openrouter', model: id } });
        draw();
      });
      const ping = h('button.btn.btn-sm.btn-ghost', { type: 'button', title: 'Проверить (сохранённые настройки)' }, icon('zap'));
      ping.onclick = () => busy(ping, async () => {
        const r = await post('/api/ai/ping', { role });
        toast(r.ok ? `${PNAME[r.provider]} · ${r.model}: «${r.text}» за ${(r.ms / 1000).toFixed(1)} с` : `Не отвечает: ${r.message}`, r.ok ? 'ok' : 'err');
        status = await get('/api/ai/status');
      });
      return h('div.role-row',
        h('div.role-head', h('span.stat-ico', icon(ico)), h('div', h('b', title), h('span', sub))),
        h('div.row', provider, model, pick, ping),
        h('div.hint', { style: { margin: 0 } }, live.provider
          ? `Сейчас: ${PNAME[live.provider]} · ${live.model}${live.last ? ` · последний ответ ${ago(live.last.at)} (${(live.last.ms / 1000).toFixed(1)} с)` : ''}${live.fallback.length ? ` · запас: ${live.fallback.join(', ')}` : ''}`
          : 'Нет ни одного ключа — добавьте OpenRouter или Groq в «Ключи и доступ»'));
    });
    const temp = h('input', { type: 'range', min: 0, max: 1.2, step: 0.1, value: draft['ai.temperature'] ?? 0.6, style: { width: '220px', accentColor: 'var(--green)' } });
    const tempLabel = h('b', String(draft['ai.temperature'] ?? 0.6));
    temp.oninput = () => {
      tempLabel.textContent = temp.value;
      set('ai.temperature', Number(temp.value));
    };
    return h('div.stack',
      h('div.grid.g3', providerCard('openrouter', 'ключ: openrouter.ai/keys'), providerCard('groq', 'нужен для голосовых'), providerCard('backup', 'необязательно')),
      card('Кто за что отвечает', { sub: 'для каждой роли — свой провайдер и модель', right: h('a.btn.btn-sm.btn-ghost', { href: '#/access' }, icon('key'), 'Ключи'), body: h('div.stack', roles),
        note: '«Авто» — OpenRouter, если есть его ключ, иначе Groq. Если выбранный ИИ не ответит (лимит, сбой), бот сам спросит другой. openrouter/free — бесплатный роутер OpenRouter: сам выбирает доступную бесплатную модель.' }),
      card('Ответы', { body: h('div', [
        option('Креативность', 'Меньше — точнее и суше, больше — живее и разнообразнее', h('div.row', h('span.hint', { style: { margin: 0 } }, 'точнее'), temp, h('span.hint', { style: { margin: 0 } }, 'живее'), tempLabel)),
        option('Голосовые вопросы', status.voice ? 'Расшифровка через Groq Whisper' : 'Нужен ключ Groq', segmented([['all', 'Все'], ['direct', 'Только ей'], ['off', 'Выкл']], draft['ai.voice'], (v) => set('ai.voice', v))),
        option('Понимать фото заданий', 'Сфотографировал номер — получил объяснение', toggle(draft['ai.images'], (v) => set('ai.images', v))),
      ]) }),
    );
  }

  async function pickModel(provider, role, onPick) {
    const list = h('div.model-list', h('div.skeleton', { style: { height: '200px' } }));
    const search = h('input.input', { type: 'search', placeholder: 'Поиск: gemini, deepseek, llama, free…' });
    const filters = { free: false, vision: role === 'vision' };
    let models = [];
    const item = (m, why) => h('button.model-item', { type: 'button', onclick: () => {
      onPick(m.id);
      document.getElementById('modal').close();
    } },
      h('span.mi-name', m.name, m.vision ? h('span.badge.acc', '📷 фото') : null, m.free ? h('span.badge.ok', 'бесплатно') : null),
      h('code', m.id),
      why ? h('span.mi-why', why) : null,
      h('span.mi-price', m.free ? 'бесплатно (с дневным лимитом)' : m.prompt == null ? 'цена — как у модели, которую выберет роутер' : `$${m.prompt} / $${m.completion} за 1 млн токенов`));
    const draw2 = () => {
      const q = search.value.trim().toLowerCase();
      const fits = (m) => (!filters.free || m.free) && (!filters.vision || m.vision);
      const top = q ? [] : models.filter((m) => RECOMMENDED[m.id] && fits(m)).sort((a, b) => Object.keys(RECOMMENDED).indexOf(a.id) - Object.keys(RECOMMENDED).indexOf(b.id));
      const rest = models.filter((m) => fits(m) && !top.includes(m) && (!q || `${m.id} ${m.name}`.toLowerCase().includes(q)))
        .sort((a, b) => (a.free === b.free ? (a.prompt ?? 99) - (b.prompt ?? 99) : a.free ? -1 : 1)).slice(0, 150);
      const out = [];
      if (top.length) out.push(h('div.mi-group', 'Рекомендуем'), ...top.map((m) => item(m, RECOMMENDED[m.id])), h('div.mi-group', 'Все модели'));
      out.push(...rest.map((m) => item(m)));
      list.replaceChildren(...(top.length || rest.length ? out : [emptyState('Ничего не нашлось', 'Снимите фильтры или измените поиск')]));
    };
    const chip = (key, text) => {
      const b = h('button', { type: 'button', 'aria-pressed': String(filters[key]) }, text);
      b.onclick = () => {
        filters[key] = !filters[key];
        b.setAttribute('aria-pressed', String(filters[key]));
        draw2();
      };
      return b;
    };
    search.oninput = draw2;
    modal({
      title: provider === 'groq' ? 'Модели Groq' : 'Модели OpenRouter',
      wide: true,
      body: h('div.stack', h('div.row', h('div', { style: { flex: 1, minWidth: '220px' } }, search), h('div.seg', chip('free', 'Бесплатные'), chip('vision', 'С фото'))), list,
        h('p.hint', { style: { margin: 0 } }, 'Цены — за 1 млн токенов (вопрос / ответ). Один ответ бота — примерно 2–4 тыс. токенов. Бесплатные модели работают с дневным лимитом запросов.')),
    });
    search.focus();
    try {
      models = (await get(`/api/ai/models?provider=${provider}`)).models;
      draw2();
    } catch (error) {
      list.replaceChildren(emptyState('Не удалось получить список', error.message));
    }
  }

  // --- Характер ---
  function personaTab() {
    const p = draft['ai.persona'];
    const setP = (change) => set('ai.persona', { ...draft['ai.persona'], ...change });
    const tones = h('div.grid.tones', TONES.map(([id, emoji, title, sub]) => h('button.card.choice', {
      type: 'button', 'aria-pressed': String(p.tone === id), onclick: () => {
        setP({ tone: id });
        draw();
      },
    }, h('span.choice-emoji', emoji), h('b', title), h('span', sub))));
    const name = h('input.input.sm', { value: draft['ai.botName'], maxlength: 40, style: { width: '200px' } });
    name.onchange = () => set('ai.botName', name.value);
    const wake = h('input.input.sm', { value: draft['ai.wakeWords'], style: { width: '260px' } });
    wake.onchange = () => set('ai.wakeWords', wake.value);
    const custom = h('textarea.textarea', { value: p.custom, maxlength: 1500, rows: 4, placeholder: 'Например: обращайся ко всем «друг», напоминай пить воду перед контрольной, в 7 «В» классный руководитель — Айгерим Сериковна' });
    const counter = h('span.hint', { style: { margin: 0 } }, `${p.custom.length}/1500`);
    custom.oninput = () => {
      counter.textContent = `${custom.value.length}/1500`;
      setP({ custom: custom.value });
    };

    // предпросмотр: как она ответит с этим характером (даже до сохранения)
    const question = h('input.input', { placeholder: 'Например: как решить уравнение 2x + 5 = 11?', value: 'не понимаю как решать 2x + 5 = 11 😭' });
    const out = h('div.wa-preview');
    const ask = h('button.btn.btn-primary', { type: 'button' }, icon('spark'), 'Как она ответит?');
    ask.onclick = () => busy(ask, async () => {
      out.replaceChildren(h('div.skeleton', { style: { height: '80px' } }));
      try {
        const r = await post('/api/ai/ask', { question: question.value, persona: draft['ai.persona'] });
        out.replaceChildren(h('div.wa-msg.me', question.value), h('div.wa-msg.bot', h('b', draft['ai.botName']), r.answer), h('p.hint', `${PNAME[r.provider] || ''} · ${r.model || ''} · ${(r.ms / 1000).toFixed(1)} с`));
      } catch (error) {
        out.replaceChildren();
        throw error;
      }
    });

    return h('div.grid.g-wide',
      h('div.stack',
        card('Кто она', { body: h('div', [
          option('Имя', 'Так она представляется и так к ней обращаются', name),
          option('О себе говорит', 'Влияет на «я поняла / я понял»', segmented([['female', 'Она'], ['male', 'Он']], p.gender, (v) => setP({ gender: v }))),
          option('Слова-обращения', 'Через запятую: «бот, как решить…»', wake),
        ]) }),
        card('Характер', { body: tones }),
        card('Как пишет', { body: h('div', [
          option('Эмодзи', '', segmented([[0, 'Без'], [1, 'Редко'], [2, 'Иногда'], [3, 'Часто']], p.emoji, (v) => setP({ emoji: Number(v) }))),
          option('Длина ответов', '', segmented([['short', 'Коротко'], ['normal', 'Обычно'], ['detailed', 'Подробно']], p.length, (v) => setP({ length: v }))),
          option('Помощь с заданиями', 'Объясняет и решает — или только подсказки, без готовых ответов', segmented([['tutor', 'Объясняет и решает'], ['hints', 'Только подсказки']], draft['ai.style'], (v) => set('ai.style', v))),
          option('Как живой человек', 'Читает, «печатает…», пишет короткими сообщениями. На вопрос «ты бот?» отвечает честно', toggle(draft['ai.humanLike'], (v) => set('ai.humanLike', v))),
        ]) }),
        card('Свои указания', { right: counter, body: custom, note: 'Указания добавляются к её инструкции. Правила безопасности (не выдумывать ДЗ, не писать сочинения целиком, честно говорить, что она бот) остаются.' })),
      card('Попробовать', { cls: 'sticky', sub: 'с характером, который сейчас на экране', body: h('div.stack', question, h('div.row', ask), out) }),
    );
  }

  // --- Понимание ---
  const journalBox = h('div.journal');
  let journalFilter = 'all';
  let journal = [];
  function drawJournal() {
    const items = journal.filter((j) => journalFilter === 'all' || (journalFilter === 'acted' ? j.done !== 'промолчала' && !String(j.done).startsWith('промолчала') : String(j.done).startsWith('промолчала')));
    journalBox.replaceChildren(...(items.length ? items.slice(0, 80).map((j) => h('div.j-item',
      h('div.j-top', h('time', clock(j.at)), h('b', j.name || (j.isGroup ? 'Группа' : 'Личка')), h(`span.badge.${DONE_CLASS[j.done] || ''}`, j.done || '—'), h('span.j-meta', `${j.decision.by === 'ai' ? `${PNAME[j.decision.provider] || ''} · ${j.decision.ms ? `${(j.decision.ms / 1000).toFixed(1)} с` : ''}` : j.decision.by || ''}`)),
      h('div.j-text', j.text),
      h('div.j-why', `решение: ${ACTION_INF[j.decision.action] || j.decision.action} · к ней: ${j.decision.toBot === 'yes' ? 'да' : j.decision.toBot === 'no' ? 'нет' : 'неясно'} · уверенность ${Math.round((j.decision.confidence || 0) * 100)}%${j.decision.reason ? ` — ${j.decision.reason}` : ''}`))) : [emptyState('Пока пусто', 'Здесь появится, что она поняла из сообщений чата и почему ответила или промолчала.')]));
  }

  function understandTab() {
    const modeCards = h('div.grid.g4', MODES.map(([value, title, sub]) => h('button.card.choice', {
      type: 'button', 'aria-pressed': String(draft['ai.mode'] === value), onclick: () => {
        set('ai.mode', value);
        draw();
      },
    }, h('b', title), h('span', sub))));
    const acts = draft['ai.actions'];
    const u = status.usage;
    const pct = (a, b) => `${Math.min(100, Math.round((a / Math.max(1, b)) * 100))}%`;
    const num = (path, min, max, width = '110px') => {
      const input = h('input.input.sm', { type: 'number', min, max, value: draft[path], style: { width } });
      input.onchange = () => set(path, Number(input.value));
      return input;
    };
    const filterSeg = segmented([['all', 'Все'], ['acted', 'Сделала'], ['silent', 'Промолчала']], journalFilter, (v) => {
      journalFilter = v;
      drawJournal();
    });
    return h('div.stack',
      card('Когда она читает чат', { body: modeCards, note: 'В личке она отвечает всегда. Сообщение, обращённое к другому человеку («Аня, ты сделала?»), она пропустит.' }),
      h('div.grid.g2',
        card('Что она делает сама', { body: h('div', ACTIONS.map(([key, title, sub]) => option(title, sub, toggle(acts[key] !== false, (v) => set('ai.actions', { ...draft['ai.actions'], [key]: v }))))) }),
        card('Лимиты', { body: h('div', [
          option('Сообщений на «понимание» в сутки', h('span', `сегодня: ${u.understand} из ${u.understandLimit}`, h('span.bar', { style: { display: 'block', marginTop: '6px' } }, h('i', { style: { width: pct(u.understand, u.understandLimit) } }))), num('ai.understandDailyLimit', 10, 100000)),
          option('Ответов в сутки', h('span', `сегодня: ${u.answers} из ${u.answersLimit}`, h('span.bar', { style: { display: 'block', marginTop: '6px' } }, h('i', { style: { width: pct(u.answers, u.answersLimit) } }))), num('ai.dailyLimit', 1, 100000)),
          option('Вопросов от одного ученика', 'за 10 минут — защита от спама', num('ai.userLimit', 1, 1000, '90px')),
        ]), note: 'Когда лимит «понимания» кончится, она до конца дня решает по простым правилам — без ИИ.' })),
      card('Что она поняла', { sub: 'вживую', right: filterSeg, body: journalBox }),
    );
  }

  // --- Заметки ---
  const notesBox = h('div');
  async function loadNotes() {
    try {
      drawNotes((await get('/api/notes')).notes);
    } catch (error) {
      notesBox.replaceChildren(emptyState('Не удалось загрузить', error.message));
    }
  }
  function drawNotes(notes) {
    notesBox.replaceChildren(notes.length ? h('ul.list', notes.map((n) => h('li',
      h('span.ic', icon('note')),
      h('span', { style: { flex: 1, minWidth: 0 } }, n.subject ? h('b', `${n.subject}: `) : null, n.text, n.until ? h('span.hint', { style: { display: 'block', margin: '2px 0 0' } }, `до ${n.until.split('-').reverse().slice(0, 2).join('.')}`) : null),
      h('button.btn.btn-sm.btn-ghost.btn-icon', { type: 'button', 'aria-label': 'Удалить', onclick: async () => drawNotes((await del(`/api/notes/${n.id}`)).notes) }, icon('trash'))))) : emptyState('Заметок пока нет', 'Расскажите ей то, чего нет в дневнике: учебники, даты СОР, правила класса.'));
  }
  function notesTab() {
    const subject = h('input.input.sm', { placeholder: 'Предмет (необязательно)', maxlength: 40, style: { width: '200px' } });
    const text = h('textarea.textarea', { placeholder: 'Например: учебник по алгебре — Абылкасымова, 7 класс, 2023 г.\nСОР по физике — 20.11, темы §10–14', rows: 3, maxlength: 1000 });
    const until = h('input.input.sm', { type: 'date', style: { width: '170px' }, title: 'До какого дня актуально (необязательно)' });
    const add = h('button.btn.btn-primary.btn-sm', { type: 'button' }, icon('plus'), 'Добавить');
    add.onclick = () => busy(add, async () => {
      drawNotes((await post('/api/notes', { subject: subject.value, text: text.value, until: until.value || null })).notes);
      text.value = '';
      subject.value = '';
      until.value = '';
      toast('Записала — теперь она это знает');
    });
    loadNotes();
    return h('div.grid.g-wide',
      card('Заметки для неё', { body: notesBox }),
      card('Новая заметка', { body: h('div.stack', subject, text, h('div.row', h('span.hint', { style: { margin: 0 } }, 'Актуально до'), until, h('span.spacer'), add)),
        note: h('span', 'Заметки видит только ИИ — она учитывает их в ответах. В WhatsApp (админ): ', h('code', '!заметка Алгебра: учебник Абылкасымова'), ' и ', h('code', '!заметки'), '.') }),
    );
  }

  // --- Проверка ---
  function testTab() {
    const text = h('input.input', { placeholder: 'Сообщение из чата, например: кто знает как решить номер 250?', value: 'кто знает как решить номер 250 по алгебре?' });
    let explicit = false;
    const out = h('div.stack');
    const run = h('button.btn.btn-primary', { type: 'button' }, icon('brain'), 'Что она сделает?');
    run.onclick = () => busy(run, async () => {
      out.replaceChildren(h('div.skeleton', { style: { height: '120px' } }));
      const { decision: d, reply } = await post('/api/ai/understand', { text: text.value, explicit });
      const blocks = [h('div.decision',
        h('div.d-main', h('span.d-action', ACTION_TEXT[d.action] || d.action), h('span.badge', `к ней: ${d.toBot === 'yes' ? 'да' : d.toBot === 'no' ? 'нет' : 'неясно'}`), h('span.badge', `уверенность ${Math.round(d.confidence * 100)}%`)),
        h('div.bar', h('i', { style: { width: `${Math.round(d.confidence * 100)}%` } })),
        h('dl.kv', h('dt', 'Почему'), h('dd', d.reason || '—'), h('dt', 'День · предмет'), h('dd', `${d.day || '—'} · ${d.subject || '—'}`), h('dt', 'Задание'), h('dd', `${d.task || '—'}${d.hasTaskText ? ' (условие есть в сообщении)' : ''}`), h('dt', 'Кто решал'), h('dd', d.by === 'ai' ? `${PNAME[d.provider] || ''} · ${d.model} · ${(d.ms / 1000).toFixed(1)} с` : `правила${d.error ? ` (ИИ: ${d.error})` : ''}`)))];
      if (d.action === 'answer') {
        const r = await post('/api/ai/ask', { question: text.value });
        blocks.push(h('div.wa-preview', h('div.wa-msg.me', text.value), h('div.wa-msg.bot', r.answer)));
      } else if (reply) {
        blocks.push(h('div.wa-preview', h('div.wa-msg.me', text.value), h('div.wa-msg.bot', h('b', '↩ ответ на сообщение'), reply),
          h('p.hint', 'Следующее сообщение этого ученика (пример текстом или фото) в течение 15 минут она решит и объяснит.')));
      }
      out.replaceChildren(...blocks);
    });
    return h('div.grid.g-wide',
      card('Проверить на сообщении', { sub: 'в группу ничего не отправляется', body: h('div.stack', text, h('div.row', run, h('span.spacer'), h('span.hint', { style: { margin: 0 } }, 'К ней обратились явно'), toggle(false, (v) => {
        explicit = v;
      })), out) }),
      card('Подсказки', { body: h('ul.list', [
        'кто знает как решить номер 250? → попросит пример',
        'что задали на завтра по алгебре → пришлёт ДЗ',
        'во сколько завтра физра → пришлёт расписание',
        'почему Печорин герой своего времени → ответит',
        'Аня, ты сделала? → промолчит',
        'спасибо бот 🙏 → реакция',
      ].map((s) => h('li', { style: { cursor: 'pointer' }, onclick: () => {
        text.value = s.split(' → ')[0];
      } }, h('span.ic', icon('chat')), s))) }),
    );
  }

  function draw() {
    tabs.set(tab);
    if (!status) return;
    body.replaceChildren(({ brain: brainTab, persona: personaTab, understand: understandTab, notes: notesTab, test: testTab }[tab] || brainTab)());
    if (tab === 'understand') drawJournal();
  }

  const [settings, st, j] = await Promise.all([get('/api/settings'), get('/api/ai/status'), get('/api/ai/journal?limit=150')]);
  apply(settings.fields);
  status = st;
  journal = j.items;
  draw();
  offs.push(on('sse:understand', (item) => {
    journal = [item, ...journal].slice(0, 300);
    if (tab === 'understand') drawJournal();
  }));
  return () => {
    offs.forEach((off) => off());
    bar.hide();
  };
}

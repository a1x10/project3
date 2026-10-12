// ИИ-помощник: когда отвечает, как пишет, лимиты и «песочница» для проверки.
import { busy, card, get, h, icon, post, put, saveBar, segmented, toast, toggle } from '../lib.js';

const MODES = [
  ['smart', 'Умный', 'Сам отвечает на вопросы по учёбе в группе (и когда зовут)'],
  ['mention', 'Только когда зовут', '@упоминание, ответ на сообщение бота или «бот, …»'],
  ['off', 'Выключен', 'Без ответов ИИ — только ДЗ и команды'],
];
const STYLES = [['tutor', 'Репетитор'], ['hints', 'Только подсказки']];
const VOICE = [['all', 'Все'], ['direct', 'Только боту'], ['off', 'Выкл']];

export async function render(root) {
  let fields = {};
  let draft = {};
  const bar = saveBar({
    onSave: async () => {
      const values = {};
      for (const [p, v] of Object.entries(draft)) if (JSON.stringify(v) !== JSON.stringify(fields[p])) values[p] = v;
      const r = await put('/api/settings', { values });
      apply(r.fields);
      toast('Сохранено — ИИ уже отвечает по-новому');
    },
    onReset: () => {
      draft = structuredClone(fields);
      draw();
    },
  });
  const set = (p, v) => {
    draft[p] = v;
    const dirty = Object.keys(draft).some((k) => JSON.stringify(draft[k]) !== JSON.stringify(fields[k]));
    if (dirty) bar.show();
    else bar.hide();
  };
  const apply = (list) => {
    fields = Object.fromEntries(list.filter((f) => f.group === 'ai').map((f) => [f.path, f.value]));
    draft = structuredClone(fields);
    bar.hide();
    draw();
  };
  const option = (title, sub, control) => h('div.opt', h('div.opt-text', h('b', title), h('span', sub)), control);

  const content = h('div.stack');
  root.append(content);

  // песочница
  const question = h('textarea.textarea', { placeholder: 'Например: как решить уравнение 2x + 5 = 11? или: что задали на завтра?', rows: 3 });
  const answer = h('div');
  const ask = h('button.btn.btn-primary', { type: 'button' }, icon('spark'), 'Спросить');
  ask.onclick = () => busy(ask, async () => {
    if (!question.value.trim()) throw new Error('Напишите вопрос');
    answer.replaceChildren(h('div.skeleton', { style: { height: '90px' } }));
    try {
      const r = await post('/api/ai/ask', { question: question.value });
      answer.replaceChildren(h('div.answer', r.answer), h('p.hint', `Ответ занял ${(r.ms / 1000).toFixed(1)} с${r.provider === 'backup' ? ' · через запасной ИИ' : ''}. В WhatsApp он придёт ${draft['ai.humanLike'] ? 'с «печатает…» и, если длинный, несколькими сообщениями' : 'одним сообщением'}.`));
    } catch (error) {
      answer.replaceChildren();
      throw error;
    }
  });
  question.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) ask.click();
  });

  function draw() {
    if (!draft['ai.mode']) return;
    const modeCards = h('div.grid.g3', MODES.map(([value, title, sub]) => h('button', {
      type: 'button',
      class: 'card',
      style: { textAlign: 'left', padding: '16px 18px', cursor: 'pointer', borderColor: draft['ai.mode'] === value ? 'rgba(37,211,102,.55)' : '', background: draft['ai.mode'] === value ? 'var(--grad-soft)' : '' },
      'aria-pressed': String(draft['ai.mode'] === value),
      onclick: () => {
        set('ai.mode', value);
        draw();
      },
    }, h('b', { style: { display: 'block', fontSize: '15px', marginBottom: '4px' } }, title), h('span', { style: { color: 'var(--muted)', fontSize: '13px' } }, sub))));

    content.replaceChildren(
      card('Когда ИИ отвечает в группе', { body: modeCards, note: 'В личке ИИ отвечает всегда (если не выключен совсем). Просьбы «скинь дз на завтра» бот выполняет сам — фото из дневника.' }),
      h('div.grid.g2',
        card('Как пишет', { body: h('div', [
          option('Отвечать как человек', 'Прочитал → «печатает…» → короткие сообщения. На вопрос «ты бот?» честно говорит, что бот.', toggle(draft['ai.humanLike'], (v) => set('ai.humanLike', v))),
          option('Стиль помощи', 'Репетитор — объясняет и даёт ответ; подсказки — без готовых решений', segmented(STYLES, draft['ai.style'], (v) => set('ai.style', v))),
          option('Имя бота', 'Так бот представляется', h('input.input.sm', { value: draft['ai.botName'], maxlength: 40, style: { width: '180px' }, onchange: (e) => set('ai.botName', e.target.value) })),
          option('Слова-обращения', '«бот, как решить…» — через запятую', h('input.input.sm', { value: draft['ai.wakeWords'], style: { width: '220px' }, onchange: (e) => set('ai.wakeWords', e.target.value) })),
        ]) }),
        card('Голос, фото и лимиты', { body: h('div', [
          option('Голосовые вопросы', 'Бот расшифровывает и отвечает текстом', segmented(VOICE, draft['ai.voice'], (v) => set('ai.voice', v))),
          option('Понимать фото заданий', 'Сфотографировал номер — получил объяснение', toggle(draft['ai.images'], (v) => set('ai.images', v))),
          option('Вопросов от одного ученика', 'за 10 минут — защита от спама', h('input.input.sm', { type: 'number', min: 1, max: 1000, value: draft['ai.userLimit'], style: { width: '96px' }, onchange: (e) => set('ai.userLimit', Number(e.target.value)) })),
          option('Ответов ИИ в сутки', 'на весь класс', h('input.input.sm', { type: 'number', min: 1, max: 100000, value: draft['ai.dailyLimit'], style: { width: '110px' }, onchange: (e) => set('ai.dailyLimit', Number(e.target.value)) })),
        ]) })),
      card('Проверить ИИ', { sub: 'вопрос уходит только сюда, в группу ничего не отправляется', body: h('div.stack', question, h('div.row', ask, h('span.hint', { style: { margin: 0 } }, 'Ctrl + Enter')), answer) }),
    );
  }

  apply((await get('/api/settings')).fields);
  return () => bar.hide();
}

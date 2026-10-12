// Уведомления: журнал технических событий и кому/как их присылать.
import { ago, busy, card, confirmDialog, emptyState, get, h, icon, on, post, put, saveBar, segmented, toast, toggle } from '../lib.js';

const LEVEL = { error: ['err', 'Проблема'], warn: ['warn', 'Внимание'], ok: ['ok', 'Восстановлено'] };
const PRIVATE = [['members', 'Ученики класса'], ['all', 'Все'], ['admins', 'Только админы'], ['off', 'Никто']];

export async function render(root) {
  let items = (await get('/api/alerts')).items;
  let fields = {};
  let draft = {};
  const listBox = h('div');
  const settingsBox = h('div');
  const bar = saveBar({
    onSave: async () => {
      const values = {};
      for (const [p, v] of Object.entries(draft)) if (JSON.stringify(v) !== JSON.stringify(fields[p])) values[p] = v;
      apply((await put('/api/settings', { values })).fields);
      toast('Сохранено');
    },
    onReset: () => {
      draft = structuredClone(fields);
      drawSettings();
    },
  });
  const set = (p, v) => {
    draft[p] = v;
    if (Object.keys(draft).some((k) => JSON.stringify(draft[k]) !== JSON.stringify(fields[k]))) bar.show();
    else bar.hide();
  };
  const apply = (list) => {
    fields = Object.fromEntries(list.filter((f) => ['notify', 'access'].includes(f.group)).map((f) => [f.path, f.value]));
    draft = structuredClone(fields);
    bar.hide();
    drawSettings();
  };
  const option = (title, sub, control) => h('div.opt', h('div.opt-text', h('b', title), h('span', sub)), control);

  function drawList() {
    if (!items.length) {
      listBox.replaceChildren(emptyState('Уведомлений нет 👌', 'Если что-то сломается — бот сам починится и запишет сюда, что было.'));
      return;
    }
    listBox.replaceChildren(h('ul.list', items.map((a) => {
      const [cls, label] = LEVEL[a.level] || LEVEL.warn;
      return h('li', h(`span.ic.${cls}`, icon(a.level === 'ok' ? 'check' : a.level === 'error' ? 'x' : 'bell')), h('span', h('b', { style: { display: 'block', fontSize: '12.5px', color: 'var(--muted)' } }, label), a.text), h('span.when', { title: new Date(a.at).toLocaleString('ru-RU') }, ago(a.at)));
    })));
  }

  function drawSettings() {
    if (!('notify.whatsapp' in draft)) return;
    settingsBox.replaceChildren(
      option('Присылать админам в WhatsApp', 'Только технические проблемы и «починилось» — в личку админам, не в группу', toggle(draft['notify.whatsapp'], (v) => set('notify.whatsapp', v))),
      option('Вечерний отчёт', 'В 21:00 — сколько было ответов, ушла ли рассылка, были ли проблемы', toggle(draft['notify.dailyReport'], (v) => set('notify.dailyReport', v))),
      option('Номера админов', 'Через запятую, с кодом страны: 77001234567', h('input.input.sm', { value: draft['whatsapp.admins'], style: { width: '260px' }, onchange: (e) => set('whatsapp.admins', e.target.value) })),
      option('Админы группы — тоже админы бота', 'Могут писать !рассылка, !график и т. п.', toggle(draft['whatsapp.groupAdminsAreBotAdmins'], (v) => set('whatsapp.groupAdminsAreBotAdmins', v))),
      option('Кто может писать боту в личку', 'Посторонним бот вежливо откажет', segmented(PRIVATE, draft['whatsapp.privateChat'], (v) => set('whatsapp.privateChat', v))),
    );
  }

  const clear = h('button.btn.btn-sm.btn-ghost', { type: 'button' }, icon('trash'), 'Очистить');
  clear.onclick = async () => {
    if (!(await confirmDialog({ title: 'Очистить журнал уведомлений?', text: 'Записи пропадут из панели. На работу бота это не влияет.', ok: 'Очистить', danger: true }))) return;
    await busy(clear, async () => {
      await post('/api/alerts/clear');
      items = [];
      drawList();
    });
  };

  root.append(h('div.grid.g-wide',
    card('Журнал', { sub: 'последние 30 дней', right: clear, body: listBox }),
    card('Настройки уведомлений', { body: settingsBox, note: 'В группу класса бот технические сообщения не пишет никогда.' })));
  drawList();
  apply((await get('/api/settings')).fields);

  const off = on('sse:alert', (a) => {
    items = [a, ...items];
    drawList();
  });
  return () => {
    off();
    bar.hide();
  };
}

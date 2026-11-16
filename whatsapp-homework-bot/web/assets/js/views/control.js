// Пульт: всё, что админ делает руками прямо сейчас — ДЗ и расписание в группу, сообщение от имени бота
// (можно попросить ИИ написать), опрос, отложенные сообщения, быстрые переключатели.
import { busy, card, confirmDialog, del, dm, emptyState, get, h, icon, isoWeekday, modal, post, segmented, toast, todayLocal, toggle, WD, WEEKDAYS } from '../lib.js';

const WEEKDAY_FULL = WEEKDAYS;

export async function render(root, { app } = {}) {
  const tz = app?.overview?.bot?.timezone;
  let groups = [];
  try {
    groups = (await get('/api/groups')).groups.filter((g) => g.bound);
  } catch {
    groups = [];
  }
  const groupSelect = () => h('select.select.sm', { 'aria-label': 'Куда', style: { width: 'auto', minWidth: '180px' } },
    h('option', { value: '' }, groups.length > 1 ? 'Во все группы' : groups[0]?.name || 'В группу класса'),
    groups.length > 1 ? groups.map((g) => h('option', { value: g.jid }, g.name)) : null);

  const dayBox = h('div.grid.g2');
  const content = h('div.stack', dayBox);
  root.append(content);
  if (!groups.length) {
    content.prepend(h('div.banner', icon('users'), h('div', h('b', 'Бот ещё не подключён к группе'), h('span', 'Добавьте номер бота в группу класса и напишите там !привязать — тогда кнопки ниже будут отправлять туда.'))));
  }

  // --- сегодня и ближайший учебный день ---
  async function loadDays() {
    dayBox.replaceChildren(h('div.skeleton', { style: { height: '220px' } }), h('div.skeleton', { style: { height: '220px' } }));
    try {
      const r = await get('/api/today');
      dayBox.replaceChildren(dayCard(r.today, 'Сегодня'), dayCard(r.next, 'Ближайший учебный день'));
    } catch (error) {
      dayBox.replaceChildren(emptyState('Дневник недоступен', error.message));
    }
  }

  function dayCard(day, label) {
    const byLesson = new Map();
    for (const e of day.entries) byLesson.set(e.subject, [...(byLesson.get(e.subject) || []), e]);
    const shown = new Set();
    const rows = day.lessons.map((l) => {
      const first = !shown.has(l.subject);
      shown.add(l.subject);
      const hw = first ? (byLesson.get(l.subject) || []).map((e) => e.text || 'см. дневник').join('; ') : '';
      return h('li', h('span.t', l.start || ''), h('span', h('span.s', l.subject), h(`span.hw${hw ? '' : '.none'}`, hw || (first ? 'ДЗ нет' : ''))));
    });
    const jidSel = groupSelect();
    const sendHw = h('button.btn.btn-sm.btn-primary', { type: 'button', disabled: !groups.length }, icon('image'), 'ДЗ в группу');
    sendHw.onclick = () => busy(sendHw, async () => {
      const r = await post('/api/group/homework', { date: day.date, jid: jidSel.value || undefined });
      toast(`ДЗ на ${dm(r.date)} отправлено (групп: ${r.groups})`);
    });
    const sendSch = h('button.btn.btn-sm', { type: 'button', disabled: !groups.length }, icon('calendar'), 'Расписание');
    sendSch.onclick = () => busy(sendSch, async () => {
      const r = await post('/api/group/schedule', { date: day.date, jid: jidSel.value || undefined });
      toast(`Расписание на ${dm(r.date)} отправлено (групп: ${r.groups})`);
    });
    const preview = h('button.btn.btn-sm.btn-ghost', { type: 'button', title: 'Как увидит класс' }, icon('eye'));
    preview.onclick = () => busy(preview, async () => {
      const r = await get(`/api/preview?date=${day.date.split('-').reverse().join('.')}`);
      modal({
        title: `${WEEKDAY_FULL[isoWeekday(day.date) - 1]}, ${dm(day.date)}`,
        wide: r.kind === 'image',
        body: r.kind === 'image'
          ? h('figure', { style: { margin: 0 } }, h('img.preview-img', { src: `data:image/jpeg;base64,${r.data}`, alt: 'Предпросмотр' }), h('figcaption.preview-cap', r.caption))
          : h('div.preview-text', r.text),
      });
    });
    return card(`${label} · ${WD[isoWeekday(day.date) - 1]} ${dm(day.date)}`, {
      right: preview,
      body: h('div.stack', rows.length ? h('ul.lessons', rows) : h('p.no-lessons', 'Уроков нет'), h('div.row', sendHw, sendSch, groups.length > 1 ? jidSel : null)),
    });
  }

  // --- написать в группу (можно попросить ИИ) ---
  function messageCard() {
    const text = h('textarea.textarea', { placeholder: 'Сообщение в группу от имени бота…', rows: 4, maxlength: 4000 });
    const about = h('input.input.sm', { placeholder: 'О чём? Например: завтра СОР по физике, повторить §10–12', maxlength: 300 });
    const draft = h('button.btn.btn-sm', { type: 'button' }, icon('spark'), 'Написать с ИИ');
    draft.onclick = () => busy(draft, async () => {
      if (!about.value.trim()) throw new Error('Напишите, о чём сообщение');
      text.value = (await post('/api/ai/draft', { about: about.value })).text;
      toast('Черновик готов — поправьте и отправьте');
    });
    const jidSel = groupSelect();
    const send = h('button.btn.btn-primary', { type: 'button', disabled: !groups.length }, icon('send'), 'Отправить');
    send.onclick = () => busy(send, async () => {
      if (!text.value.trim()) throw new Error('Пустое сообщение');
      if (!(await confirmDialog({ title: 'Отправить в группу?', text: text.value.slice(0, 300), ok: 'Отправить' }))) return;
      const r = await post('/api/group/message', { text: text.value, jid: jidSel.value || undefined });
      text.value = '';
      toast(`Отправлено (групп: ${r.groups})`);
    });
    return card('Написать в группу', {
      sub: 'от имени бота',
      body: h('div.stack', h('div.row', h('div', { style: { flex: 1, minWidth: '200px' } }, about), draft), text, h('div.row', groups.length > 1 ? jidSel : null, h('span.spacer'), send)),
      note: 'Совет: ИИ напишет черновик в характере бота (раздел «Мозг» → «Характер»). Перед отправкой его можно поправить.',
    });
  }

  // --- быстро ---
  function quickCard() {
    const date = h('input.input.sm', { type: 'date', value: todayLocal(tz), style: { width: '170px' } });
    const hw = h('button.btn.btn-sm', { type: 'button', disabled: !groups.length }, icon('image'), 'ДЗ');
    hw.onclick = () => busy(hw, async () => {
      const r = await post('/api/group/homework', { date: date.value });
      toast(`ДЗ на ${dm(r.date)} отправлено`);
    });
    const sch = h('button.btn.btn-sm', { type: 'button', disabled: !groups.length }, icon('calendar'), 'Расписание');
    sch.onclick = () => busy(sch, async () => {
      const r = await post('/api/group/schedule', { date: date.value });
      toast(`Расписание на ${dm(r.date)} отправлено`);
    });
    const aiOn = groups.every((g) => g.ai !== false);
    return card('Быстро', {
      body: h('div', [
        h('div.opt', { style: { flexWrap: 'wrap' } }, h('div.opt-text', { style: { flexBasis: '100%' } }, h('b', 'Другой день в группу'), h('span', 'ДЗ фото или расписание на выбранную дату')), h('div.row', date, hw, sch)),
        h('div.opt', h('div.opt-text', h('b', 'ИИ отвечает в группе'), h('span', 'Выключите на время контрольной — бот будет только присылать ДЗ')), toggle(aiOn, async (on) => {
          try {
            await post('/api/group/ai', { on });
            toast(on ? 'ИИ снова отвечает в группе' : 'ИИ в группе выключен');
          } catch (error) {
            toast(error.message, 'err');
          }
        })),
        h('div.opt', h('div.opt-text', h('b', 'Пауза рассылок'), h('span', 'Каникулы, праздник — в разделе «График»')), h('a.btn.btn-sm', { href: '#/schedule' }, icon('pause'), 'График')),
        h('div.opt', h('div.opt-text', h('b', 'Проверить дневник сейчас'), h('span', 'Новое ДЗ сразу уйдёт в группу')), h('button.btn.btn-sm', { type: 'button', onclick: (e) => busy(e.currentTarget, async () => {
          const r = await post('/api/actions/poll');
          toast(r.added + r.changed ? `Найдено изменений: ${r.added + r.changed}` : 'Новых ДЗ нет');
        }) }, icon('refresh'), 'Проверить')),
      ]),
    });
  }

  // --- опрос ---
  function pollCard() {
    const question = h('input.input', { placeholder: 'Вопрос, например: Кто идёт на субботник?', maxlength: 250 });
    const list = h('div.stack', { style: { gap: '8px' } });
    const addOption = (value = '') => {
      if (list.children.length >= 12) return;
      const input = h('input.input.sm', { placeholder: `Вариант ${list.children.length + 1}`, maxlength: 100, value });
      const row = h('div.row', h('div', { style: { flex: 1 } }, input), h('button.btn.btn-sm.btn-ghost.btn-icon', { type: 'button', 'aria-label': 'Убрать', onclick: () => list.children.length > 2 && row.remove() }, icon('x')));
      list.append(row);
    };
    addOption('Да');
    addOption('Нет');
    let multiple = false;
    const jidSel = groupSelect();
    const send = h('button.btn.btn-primary', { type: 'button', disabled: !groups.length }, icon('poll'), 'Отправить опрос');
    send.onclick = () => busy(send, async () => {
      const options = [...list.querySelectorAll('input')].map((i) => i.value.trim()).filter(Boolean);
      const r = await post('/api/group/poll', { question: question.value, options, multiple, jid: jidSel.value || undefined });
      question.value = '';
      toast(`Опрос отправлен (групп: ${r.groups})`);
    });
    return card('Опрос в группу', {
      body: h('div.stack', question, list,
        h('div.row', h('button.btn.btn-sm', { type: 'button', onclick: () => addOption() }, icon('plus'), 'Вариант'), h('span.spacer'), h('span.hint', { style: { margin: 0 } }, 'Несколько ответов'), toggle(false, (v) => {
          multiple = v;
        })),
        h('div.row', groups.length > 1 ? jidSel : null, h('span.spacer'), send)),
    });
  }

  // --- отложенные сообщения ---
  const schedBox = h('div');
  async function loadScheduled() {
    try {
      drawScheduled((await get('/api/scheduled')).items);
    } catch (error) {
      schedBox.replaceChildren(emptyState('Не удалось загрузить', error.message));
    }
  }
  function when(m) {
    if (m.kind === 'weekly') return `каждый ${m.days.map((d) => WD[d - 1]).join(', ')} в ${m.time}`;
    const [d, t] = m.at.split('T');
    return `${dm(d)} в ${t}`;
  }
  function drawScheduled(items) {
    const rows = items.length ? h('ul.list', items.map((m) => h('li',
      h(`span.ic.${m.enabled ? 'ok' : ''}`, icon(m.kind === 'weekly' ? 'refresh' : 'clock')),
      h('span', { style: { flex: 1, minWidth: 0 } }, h('b', { style: { display: 'block', fontSize: '13px', color: 'var(--muted)' } }, `${when(m)}${m.lastRun ? ` · ${m.lastRun === 'пропущено' ? 'пропущено' : `отправлено ${m.kind === 'once' ? m.lastRun : dm(m.lastRun)}`}` : ''}`), m.text.length > 160 ? `${m.text.slice(0, 160)}…` : m.text),
      h('span.row', { style: { gap: '6px', flexWrap: 'nowrap' } },
        m.kind === 'weekly' || !m.lastRun ? toggle(m.enabled, async () => drawScheduled((await post(`/api/scheduled/${m.id}/toggle`)).items), 'Включено') : null,
        h('button.btn.btn-sm.btn-ghost.btn-icon', { type: 'button', 'aria-label': 'Удалить', onclick: async () => drawScheduled((await del(`/api/scheduled/${m.id}`)).items) }, icon('trash')))))) : emptyState('Нет отложенных сообщений', 'Например: «Не забудьте сменку» каждый понедельник в 07:30.');
    schedBox.replaceChildren(rows);
  }
  function scheduledCard() {
    let kind = 'once';
    const text = h('textarea.textarea', { placeholder: 'Текст сообщения…', rows: 3, maxlength: 4000 });
    const tomorrow = new Date(`${todayLocal(tz)}T08:00`);
    tomorrow.setDate(tomorrow.getDate() + 1);
    const pad = (n) => String(n).padStart(2, '0');
    const at = h('input.input.sm', { type: 'datetime-local', value: `${tomorrow.getFullYear()}-${pad(tomorrow.getMonth() + 1)}-${pad(tomorrow.getDate())}T07:30`, style: { width: '220px' } });
    const time = h('input.input.sm', { type: 'time', value: '07:30', style: { width: '130px' } });
    const days = new Set([1]);
    const chips = h('div.seg', WD.map((d, i) => {
      const b = h('button', { type: 'button', 'aria-pressed': String(days.has(i + 1)) }, d);
      b.onclick = () => {
        if (days.has(i + 1)) days.delete(i + 1);
        else days.add(i + 1);
        b.setAttribute('aria-pressed', String(days.has(i + 1)));
      };
      return b;
    }));
    const onceRow = h('div.row', h('span.hint', { style: { margin: 0 } }, 'Когда'), at);
    const weeklyRow = h('div.row', chips, time);
    weeklyRow.hidden = true;
    const kindSeg = segmented([['once', 'Один раз'], ['weekly', 'Каждую неделю']], kind, (v) => {
      kind = v;
      onceRow.hidden = v !== 'once';
      weeklyRow.hidden = v !== 'weekly';
    });
    const save = h('button.btn.btn-primary.btn-sm', { type: 'button', disabled: !groups.length }, icon('plus'), 'Запланировать');
    save.onclick = () => busy(save, async () => {
      const body = kind === 'once' ? { kind, text: text.value, at: at.value } : { kind, text: text.value, days: [...days], time: time.value };
      drawScheduled((await post('/api/scheduled', body)).items);
      text.value = '';
      toast('Запланировано');
    });
    return card('Отложенные сообщения', {
      sub: 'бот отправит сам',
      body: h('div.stack', schedBox, h('div.stack', { style: { borderTop: '1px solid var(--border)', paddingTop: '14px' } }, kindSeg, onceRow, weeklyRow, text, h('div.row.end', save))),
      note: `Время — по часам школы${tz ? ` (${tz})` : ''}. Если бот был выключен, разовое сообщение отправится позже, но не позднее чем через 3 часа.`,
    });
  }

  content.append(h('div.grid.g-wide', messageCard(), quickCard()), h('div.grid.g2', pollCard(), scheduledCard()));
  loadDays();
  loadScheduled();
  return null;
}

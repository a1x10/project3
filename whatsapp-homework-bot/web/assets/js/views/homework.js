// Домашка: неделя из дневника, предпросмотр фото для класса, ДЗ вручную.
import { addDaysIso, busy, del, todayLocal, dm, emptyState, get, h, humanDate, icon, isoWeekday, modal, post, toast, WEEKDAYS } from '../lib.js';

export async function render(root) {
  let monday = null;
  const title = h('h2');
  const weekBox = h('div.week');
  const nav = h('div.week-nav',
    h('button.btn.btn-icon.btn-sm', { type: 'button', 'aria-label': 'Прошлая неделя', onclick: () => load(addDaysIso(monday, -7)) }, icon('left')),
    title,
    h('button.btn.btn-icon.btn-sm', { type: 'button', 'aria-label': 'Следующая неделя', onclick: () => load(addDaysIso(monday, 7)) }, icon('right')),
    h('button.btn.btn-sm.btn-ghost', { type: 'button', onclick: () => load(null) }, 'Эта неделя'),
    h('span.spacer'),
    h('button.btn.btn-sm', { type: 'button', onclick: () => addManual() }, icon('plus'), 'Добавить ДЗ вручную'),
  );
  root.append(nav, weekBox);

  async function load(target) {
    weekBox.replaceChildren(...Array.from({ length: 5 }, () => h('div.skeleton', { style: { height: '220px' } })));
    let data;
    try {
      data = await get(`/api/homework${target ? `?monday=${target}` : ''}`);
    } catch (error) {
      weekBox.replaceChildren(emptyState('Дневник недоступен', error.message));
      return;
    }
    monday = data.monday;
    title.textContent = `${humanDate(data.monday)} — ${humanDate(addDaysIso(data.monday, 6))}`;
    const days = data.days.filter((d) => d.lessons.length || d.entries.length || isoWeekday(d.date) <= 5);
    weekBox.replaceChildren(...days.map((d) => dayCard(d, data.today)));
  }

  function dayCard(day, today) {
    const isToday = day.date === today;
    const byLesson = new Map();
    for (const e of day.entries) {
      if (!byLesson.has(e.subject)) byLesson.set(e.subject, []);
      byLesson.get(e.subject).push(e);
    }
    const shown = new Set();
    const rows = day.lessons.map((l) => {
      const entries = byLesson.get(l.subject) || [];
      const first = !shown.has(l.subject);
      shown.add(l.subject);
      const hw = first && entries.length
        ? entries.map((e) => h('span.hw', e.manual ? h('span.manual', '✍️ ', e.text, h('button.del', { type: 'button', title: 'Удалить', onclick: () => removeManual(e.id) }, icon('trash'))) : [e.text || (e.books.length ? `Учебник: ${e.books.join('; ')}` : 'см. в дневнике'), e.hasFiles ? ' 📎' : '']))
        : h('span.hw.none', first ? 'ДЗ нет' : '');
      return h('li', h('span.t', l.start || ''), h('span', h('span.s', l.subject), hw));
    });
    // ДЗ без урока в этот день (добавленные вручную или по другому предмету)
    for (const [subject, entries] of byLesson) {
      if (shown.has(subject)) continue;
      rows.push(h('li', h('span.t', ''), h('span', h('span.s', subject), entries.map((e) => h('span.hw', e.manual ? h('span.manual', '✍️ ', e.text, h('button.del', { type: 'button', title: 'Удалить', onclick: () => removeManual(e.id) }, icon('trash'))) : e.text)))));
    }
    const preview = day.entries.length
      ? h('button.btn.btn-sm.btn-ghost', { type: 'button', title: 'Как это увидит класс', onclick: (ev) => showPreview(ev.currentTarget, day.date) }, icon('eye'), 'Фото')
      : null;
    return h(`section.card.day-card${isToday ? '.today' : ''}`,
      h('header', h('b', WEEKDAYS[isoWeekday(day.date) - 1]), h('span', dm(day.date)), isToday ? h('span.badge.ok', 'сегодня') : null, day.isHoliday ? h('span.badge.warn', 'выходной') : null, preview),
      rows.length ? h('ul.lessons', rows) : h('p.no-lessons', day.missing ? 'Нет данных' : 'Уроков нет'));
  }

  function showPreview(button, date) {
    return busy(button, async () => {
      const r = await get(`/api/preview?date=${date.split('-').reverse().join('.')}`);
      modal({
        title: `${WEEKDAYS[isoWeekday(date) - 1]}, ${humanDate(date)}`,
        wide: r.kind === 'image',
        body: r.kind === 'image'
          ? h('figure', { style: { margin: 0 } }, h('img.preview-img', { src: `data:image/jpeg;base64,${r.data}`, alt: 'Предпросмотр' }), h('figcaption.preview-cap', r.caption))
          : h('div.preview-text', r.text),
      });
    });
  }

  async function removeManual(id) {
    try {
      await del(`/api/homework/manual/${id}`);
      toast('Удалено');
      load(monday);
    } catch (error) {
      toast(error.message, 'err');
    }
  }

  function addManual() {
    const date = h('input.input', { type: 'date', value: addDaysIso(todayLocal(), 1) });
    const subject = h('input.input', { placeholder: 'Например: Алгебра', maxlength: 80 });
    const text = h('textarea.textarea', { placeholder: 'Например: № 250–255, повторить формулы', maxlength: 2000 });
    const save = h('button.btn.btn-primary', { type: 'button' }, icon('plus'), 'Добавить');
    save.onclick = () => busy(save, async () => {
      if (!date.value || !subject.value.trim() || !text.value.trim()) throw new Error('Заполните день, предмет и задание');
      await post('/api/homework/manual', { date: date.value.split('-').reverse().join('.'), subject: subject.value, text: text.value });
      toast('ДЗ добавлено — оно попадёт в рассылку и ответы бота');
      document.getElementById('modal').close();
      load(monday);
    });
    modal({
      title: 'Добавить ДЗ вручную',
      body: h('div.fields',
        h('p.hint', { style: { margin: 0 } }, 'Если учитель сказал задание устно или в дневнике его нет — добавьте сюда. Бот покажет его вместе с ДЗ из дневника.'),
        h('div.field', h('label.label', 'К какому дню'), date),
        h('div.field', h('label.label', 'Предмет'), subject),
        h('div.field', h('label.label', 'Задание'), text)),
      actions: [h('button.btn', { type: 'button', onclick: () => document.getElementById('modal').close() }, 'Отмена'), save],
    });
    subject.focus();
  }

  await load(null);
  return null;
}


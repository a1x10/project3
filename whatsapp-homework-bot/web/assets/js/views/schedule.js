// График: когда присылать ДЗ по дням недели, пауза, пропуски, параметры рассылки, группы.
import { addDaysIso, busy, card, dm, emptyState, get, h, icon, isoWeekday, put, saveBar, segmented, toast, todayLocal, toggle, WEEKDAYS } from '../lib.js';

const MODES = [['lessons', 'После уроков'], ['time', 'В своё время'], ['off', 'Не присылать', 'on-red']];
const SCOPES = [['new', 'Завтра + новое на другие дни'], ['tomorrow', 'Только на завтра']];
const PHOTO = [['screenshot', 'Скриншот дневника'], ['card', 'Карточка'], ['text', 'Текст']];

export async function render(root) {
  let fields = {};
  let draft = {};
  const bar = saveBar({
    onSave: async () => {
      const values = {};
      for (const [path, value] of Object.entries(draft)) if (JSON.stringify(value) !== JSON.stringify(fields[path])) values[path] = value;
      const r = await put('/api/settings', { values });
      apply(r.fields);
      toast(r.changed.length ? 'Сохранено — бот уже работает по новому графику' : 'Изменений нет');
    },
    onReset: () => {
      draft = structuredClone(fields);
      draw();
    },
  });
  const set = (path, value) => {
    draft[path] = value;
    const dirty = Object.keys(draft).some((p) => JSON.stringify(draft[p]) !== JSON.stringify(fields[p]));
    if (dirty) bar.show();
    else bar.hide();
  };

  function apply(list) {
    fields = Object.fromEntries(list.map((f) => [f.path, f.value]));
    draft = structuredClone(fields);
    bar.hide();
    draw();
  }

  // Немедленные изменения (пауза, пропуски) — без кнопки «Сохранить»
  async function saveNow(values, message) {
    try {
      const r = await put('/api/settings', { values });
      fields = Object.fromEntries(r.fields.map((f) => [f.path, f.value]));
      for (const p of Object.keys(values)) draft[p] = fields[p];
      draw();
      toast(message);
    } catch (error) {
      toast(error.message, 'err');
    }
  }

  const todayIso = todayLocal();
  const today = isoWeekday(todayIso);

  function dayRow(d) {
    const day = draft['schedule.days'][d];
    const update = (change) => {
      const days = structuredClone(draft['schedule.days']);
      days[d] = { ...days[d], ...change };
      if (change.mode === 'time' && !days[d].time) days[d].time = '18:00';
      set('schedule.days', days);
      draw();
    };
    const time = h('input.input.sm', { type: 'time', value: day.time || '', disabled: day.mode === 'off', 'aria-label': 'Время', title: day.mode === 'lessons' ? 'Если в этот день нет уроков' : 'Время рассылки', onchange: (e) => update({ time: e.target.value }) });
    const scope = h('select.select.sm', { 'aria-label': 'Что присылать', disabled: day.mode === 'off', onchange: (e) => update({ scope: e.target.value }) },
      SCOPES.map(([v, t]) => h('option', { value: v, selected: day.scope === v }, t)));
    const desc = day.mode === 'off' ? 'Бот в этот день сам ничего не присылает'
      : day.mode === 'lessons' ? `Через ${draft['schedule.digestDelayMinutes']} мин после последнего урока${day.time ? `; без уроков — в ${day.time}` : '; без уроков — не присылать'}`
        : `Каждую неделю в ${day.time}`;
    return h(`div.day-row${d === today ? '.today' : ''}${day.mode === 'off' ? '.off' : ''}`,
      h('div.day-name', h('span', WEEKDAYS[d - 1], d === today ? h('span.badge.ok', { style: { marginLeft: '8px', height: '20px' } }, 'сегодня') : null), h('small', desc)),
      segmented(MODES, day.mode, (mode) => update({ mode })),
      time,
      scope);
  }

  const content = h('div.stack');
  root.append(content);

  function draw() {
    if (!draft['schedule.days']) return;
    const paused = fields['schedule.pausedUntil'];
    const skip = fields['schedule.skipDates'] || [];
    const days = [1, 2, 3, 4, 5, 6, 7];

    const quick = h('div.row',
      h('button.btn.btn-sm', { type: 'button', onclick: () => {
        const next = structuredClone(draft['schedule.days']);
        for (const d of [1, 2, 3, 4, 5]) next[d] = { ...next[d], mode: 'lessons' };
        set('schedule.days', next);
        draw();
      } }, 'Будни — после уроков'),
      h('button.btn.btn-sm', { type: 'button', onclick: () => {
        const next = structuredClone(draft['schedule.days']);
        next[6] = { ...next[6], mode: 'off' };
        next[7] = { ...next[7], mode: 'time', time: next[7].time || '18:00', scope: 'tomorrow' };
        set('schedule.days', next);
        draw();
      } }, 'Сб — выкл, Вс — только на завтра'),
      h('button.btn.btn-sm', { type: 'button', onclick: () => {
        const next = structuredClone(draft['schedule.days']);
        for (const d of days) next[d] = { ...next[d], scope: 'tomorrow' };
        set('schedule.days', next);
        draw();
      } }, 'Всегда только на завтра'));

    const pauseBanner = paused ? h('div.banner', icon('pause'),
      h('div', h('b', paused === 'forever' ? 'Рассылки на паузе' : `Рассылки на паузе по ${dm(paused)} включительно`), h('span', 'Бот не присылает ДЗ в группу сам. Новые задания запоминает и пришлёт после паузы. Ответы на вопросы и команды работают.')),
      h('button.btn.btn-primary.btn-sm', { type: 'button', onclick: () => saveNow({ 'schedule.pausedUntil': null }, '▶️ Рассылки снова включены') }, icon('play'), 'Продолжить')) : null;

    const pauseDate = h('input.input.sm', { type: 'date', min: todayIso, value: addDaysIso(todayIso, 6), 'aria-label': 'Пауза до', style: { width: '170px' } });
    const skipDate = h('input.input.sm', { type: 'date', min: todayIso, value: addDaysIso(todayIso, 1), 'aria-label': 'Пропустить день', style: { width: '170px' } });

    const groupsBox = h('div', h('div.skeleton', { style: { height: '60px' } }));
    loadGroups(groupsBox);

    content.replaceChildren(
      pauseBanner || h('span'),
      card('Рассылка по дням недели', {
        sub: 'когда бот сам присылает ДЗ в группу',
        body: h('div.stack', h('div.days', days.map(dayRow)), quick),
        note: '«Завтра + новое» — «Домашнее задание на завтра» и фото дней, где появилось новое ДЗ. «Только на завтра» — без заданий на дальние дни (они придут в свой день). Время у «после уроков» — на случай дня без уроков.',
      }),
      h('div.grid.g2',
          card('Пауза', {
            body: h('div.stack',
              h('p.hint', { style: { margin: 0 } }, 'Каникулы, карантин или просто не нужно — бот замолчит в группе, но будет отвечать на вопросы.'),
              h('div.row',
                h('button.btn.btn-sm', { type: 'button', onclick: () => saveNow({ 'schedule.pausedUntil': todayIso }, '⏸ Сегодня без рассылок') }, 'Сегодня'),
                h('button.btn.btn-sm', { type: 'button', onclick: () => saveNow({ 'schedule.pausedUntil': addDaysIso(todayIso, 6) }, '⏸ Пауза на неделю') }, 'Неделя'),
                h('button.btn.btn-sm', { type: 'button', onclick: () => saveNow({ 'schedule.pausedUntil': 'forever' }, '⏸ Рассылки на паузе до отмены') }, 'До отмены')),
              h('div.row', pauseDate, h('button.btn.btn-sm', { type: 'button', onclick: () => pauseDate.value && saveNow({ 'schedule.pausedUntil': pauseDate.value }, `⏸ Пауза по ${dm(pauseDate.value)}`) }, icon('pause'), 'Пауза по дату'))),
          }),
          card('Пропустить отдельные дни', {
            body: h('div.stack',
              skip.length ? h('div.chips', skip.map((d) => h('span.chip-x', `${WEEKDAYS[isoWeekday(d) - 1].slice(0, 2)}, ${dm(d)}`, h('button', { type: 'button', 'aria-label': 'Вернуть рассылку', onclick: () => saveNow({ 'schedule.skipDates': skip.filter((x) => x !== d) }, `Рассылка ${dm(d)} вернётся`) }, icon('x'))))) : h('p.hint', { style: { margin: 0 } }, 'Нет пропусков. Например, праздник или день без уроков.'),
              h('div.row', skipDate, h('button.btn.btn-sm', { type: 'button', onclick: () => skipDate.value && saveNow({ 'schedule.skipDates': [...skip, skipDate.value] }, `⏭ ${dm(skipDate.value)} без рассылки`) }, icon('plus'), 'Пропустить'))),
          })),
      h('div.grid.g2',
        card('Параметры рассылки', { body: h('div', [
          option('Через сколько минут после уроков', 'Учителя успевают заполнить дневник', h('input.input.sm', { type: 'number', min: 0, max: 360, value: draft['schedule.digestDelayMinutes'], style: { width: '96px' }, onchange: (e) => { set('schedule.digestDelayMinutes', Number(e.target.value)); draw(); } })),
          option('Как присылать ДЗ', 'Скриншот — настоящее фото из дневника', segmented(PHOTO, draft['features.homeworkPhoto'], (v) => set('features.homeworkPhoto', v))),
          option('Каждый день «ДЗ на завтра»', 'Даже если нового нет', toggle(draft['schedule.remindTomorrow'], (v) => set('schedule.remindTomorrow', v))),
          option('Молчать, если нового нет', 'Без сообщения «новых ДЗ нет»', toggle(draft['schedule.skipEmptyDigest'], (v) => set('schedule.skipEmptyDigest', v))),
          option('Пересылать файлы к ДЗ', 'PDF, фото и документы из дневника', toggle(draft['features.sendFiles'], (v) => set('features.sendFiles', v))),
        ]) }),
        card('Проверки в течение дня', { body: h('div', [
          option('Сообщать о новых ДЗ днём', 'Срочное (на сегодня) — сразу, остальное — в рассылке', toggle(draft['schedule.notifyChanges'], (v) => set('schedule.notifyChanges', v))),
          option('Проверять дневник каждые', 'минут', h('input.input.sm', { type: 'number', min: 10, max: 1440, value: draft['schedule.pollIntervalMinutes'], style: { width: '96px' }, onchange: (e) => set('schedule.pollIntervalMinutes', Number(e.target.value)) })),
          option('Когда можно писать в группу', 'Ночью бот не беспокоит', rangeInput()),
          option('Утреннее напоминание', 'Расписание и что сдаём сегодня (пусто — выкл)', h('input.input.sm', { type: 'time', value: draft['schedule.morningTime'] || '', onchange: (e) => set('schedule.morningTime', e.target.value) })),
        ]) })),
      card('Группы', { sub: 'куда бот присылает ДЗ', body: groupsBox, note: 'Чтобы добавить группу: добавьте бота в группу класса и напишите там !привязать.' }),
    );
  }

  function option(title, sub, control) {
    return h('div.opt', h('div.opt-text', h('b', title), h('span', sub)), control);
  }

  function rangeInput() {
    const [from, to] = String(draft['schedule.activeHours'] || '07:00-22:00').split('-');
    const a = h('input.input.sm', { type: 'time', value: from, 'aria-label': 'С' });
    const b = h('input.input.sm', { type: 'time', value: to, 'aria-label': 'До' });
    const change = () => set('schedule.activeHours', `${a.value}-${b.value}`);
    a.onchange = change;
    b.onchange = change;
    return h('div.row', a, '—', b);
  }

  async function loadGroups(box) {
    try {
      const { groups } = await get('/api/groups');
      if (!groups.length) {
        box.replaceChildren(emptyState('Бот пока не в группах', 'Добавьте номер бота в группу класса.'));
        return;
      }
      box.replaceChildren(h('div', groups.map((g) => h('div.opt',
        h('div.opt-text', h('b', g.name), h('span', g.bound ? `ДЗ приходит сюда${g.members ? ` · ${g.members} участников` : ''}` : 'бот в группе, но ДЗ сюда не присылает')),
        g.bound ? h('div.row', h('span.hint', { style: { margin: 0 } }, 'ДЗ'), toggle(g.digest !== false, (v) => updateGroup(g.jid, { digest: v })), h('span.hint', { style: { margin: 0 } }, 'ИИ'), toggle(g.ai !== false, (v) => updateGroup(g.jid, { ai: v }))) : null,
        g.fromEnv ? h('span.badge', '.env') : h('button.btn.btn-sm', { type: 'button', onclick: (e) => busy(e.currentTarget, async () => {
          await updateGroup(g.jid, { bound: !g.bound, name: g.name });
          loadGroups(box);
        }) }, g.bound ? 'Отключить' : 'Подключить')))));
    } catch (error) {
      box.replaceChildren(emptyState('Не удалось получить группы', error.message));
    }
  }

  async function updateGroup(jid, body) {
    try {
      await put(`/api/groups/${encodeURIComponent(jid)}`, body);
      toast('Готово');
    } catch (error) {
      toast(error.message, 'err');
    }
  }

  apply((await get('/api/settings')).fields);
  return () => bar.hide();
}

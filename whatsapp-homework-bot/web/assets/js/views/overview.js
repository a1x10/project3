// Обзор: состояние бота, активность, график недели, события и живой журнал.
import { ago, busy, card, clock, emptyState, h, icon, modal, on, post, toast, WD } from '../lib.js';

const SVGNS = 'http://www.w3.org/2000/svg';
const s = (tag, attrs = {}, ...children) => {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  el.append(...children);
  return el;
};

function greeting() {
  const hour = new Date().getHours();
  if (hour < 5) return 'Доброй ночи';
  if (hour < 12) return 'Доброе утро';
  if (hour < 18) return 'Добрый день';
  return 'Добрый вечер';
}

function digestSummary(o) {
  const d = o.digest;
  if (d.pausedUntil) return d.pausedUntil === 'forever' ? 'Рассылки на паузе.' : `Рассылки на паузе до ${d.pausedUntil.split('-').reverse().slice(0, 2).join('.')}.`;
  if (d.sentToday) return 'Сегодняшняя рассылка уже в группе ✅';
  if (d.today?.quiet) return `Сегодня рассылки нет: ${d.today.quiet}.`;
  if (d.today?.at) return d.today.source === 'lessons' ? `Сегодня ДЗ уйдёт в ${d.today.at} — уроки закончатся в ${d.today.lessonsEnd}.` : `Сегодня ДЗ уйдёт в ${d.today.at}.`;
  return 'План рассылки на сегодня рассчитывается…';
}

// Столбики: ответы ИИ + сообщения в личке за 14 дней
function chart(stats) {
  const W = 640;
  const H = 200;
  const pad = { l: 28, r: 8, t: 12, b: 26 };
  const max = Math.max(5, ...stats.map((d) => d.ai + d.dm));
  const step = (W - pad.l - pad.r) / stats.length;
  const bw = Math.min(26, step * 0.62);
  const y = (v) => pad.t + (H - pad.t - pad.b) * (1 - v / max);
  const svg = s('svg', { class: 'chart', viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'none', role: 'img', 'aria-label': 'Активность за 14 дней' },
    s('defs', {}, s('linearGradient', { id: 'chart-grad', x1: '0', y1: '0', x2: '0', y2: '1' }, s('stop', { offset: '0', 'stop-color': '#25d366' }), s('stop', { offset: '1', 'stop-color': '#22d3ee' }))));
  for (const v of [0, Math.round(max / 2), max]) {
    svg.append(s('line', { class: 'grid-line', x1: pad.l, x2: W - pad.r, y1: y(v), y2: y(v) }), s('text', { x: 0, y: y(v) + 4 }, String(v)));
  }
  stats.forEach((d, i) => {
    const x = pad.l + i * step + (step - bw) / 2;
    const aiH = y(0) - y(d.ai);
    const dmH = y(0) - y(d.dm);
    const g = s('g', {}, s('title', {}, `${d.date.slice(8, 10)}.${d.date.slice(5, 7)}: ИИ — ${d.ai}, личка — ${d.dm}${d.digest ? ', рассылка ✓' : ''}`));
    g.append(s('rect', { class: 'bar-ai', x, y: y(d.ai), width: bw, height: Math.max(0, aiH), rx: 4 }));
    if (d.dm) g.append(s('rect', { class: 'bar-dm', x, y: y(d.ai) - dmH - 2, width: bw, height: Math.max(0, dmH), rx: 4 }));
    const wd = ((new Date(`${d.date}T00:00:00Z`).getUTCDay() + 6) % 7);
    if (i % 2 === stats.length % 2 || stats.length < 10) g.append(s('text', { x: x + bw / 2, y: H - 6, 'text-anchor': 'middle' }, WD[wd]));
    svg.append(g);
  });
  return svg;
}

function statCard({ ico, title, value, sub, level = 'ok', extra = null }) {
  return h(`section.card.stat.${level}`, h('div.stat-top', h('span.stat-ico', icon(ico)), title, h(`i.dot.${level}`)), h('div.stat-val', value), h('div.stat-sub', sub), extra);
}

export async function render(root, { refreshOverview }) {
  let o = await refreshOverview();
  if (!o) {
    root.append(emptyState('Нет связи с ботом', 'Проверьте, что бот запущен, и обновите страницу.'));
    return null;
  }
  const logBox = h('div.mini-log');

  const actions = h('div.row');
  const sendBtn = h('button.btn.btn-primary', { type: 'button' }, icon('send'), 'Разослать сейчас');
  const pollBtn = h('button.btn', { type: 'button' }, icon('refresh'), 'Проверить дневник');
  const previewBtn = h('button.btn', { type: 'button' }, icon('eye'), 'Предпросмотр');
  actions.append(previewBtn, pollBtn, sendBtn);

  previewBtn.onclick = () => busy(previewBtn, async () => {
    const r = await post('/api/actions/digest/preview');
    const items = (r.messages || []).map((m) => (m.kind === 'image'
      ? h('figure', { style: { margin: '0 0 16px' } }, h('img.preview-img', { src: `data:image/jpeg;base64,${m.data}`, alt: m.caption }), h('figcaption.preview-cap', m.caption))
      : h('div.preview-text', m.text)));
    modal({
      title: 'Так выглядела бы рассылка сейчас',
      wide: true,
      body: h('div', h('p.hint', { style: { marginTop: 0 } }, r.firstTime ? 'Первая рассылка: только «на завтра», всё остальное бот запомнит.' : `Новых заданий: ${r.fresh}. Ничего не отправлено.`), items.length ? items : emptyState('Пусто', 'Рассылка сейчас ничего бы не отправила.')),
      actions: [h('button.btn.btn-primary', { type: 'button', onclick: (e) => busy(e.currentTarget, async () => {
        const res = await post('/api/actions/digest');
        toast(`Рассылка отправлена в очередь (групп: ${res.groups})`);
        document.getElementById('modal').close();
      }) }, icon('send'), 'Отправить в группу')],
    });
  });
  pollBtn.onclick = () => busy(pollBtn, async () => {
    const r = await post('/api/actions/poll');
    toast(r.added + r.changed ? `Найдено изменений: ${r.added + r.changed} — отправлено в группу` : 'Дневник проверен — новых ДЗ нет');
    refreshOverview();
  });
  sendBtn.onclick = () => busy(sendBtn, async () => {
    const r = await post('/api/actions/digest');
    toast(`Рассылка отправлена в очередь (групп: ${r.groups})`);
  });

  const hello = h('div.hello', h('div', h('h2', `${greeting()} 👋`), h('p.summary')), actions);
  const stats = h('div.grid.g4');
  const middle = h('div.grid.g-wide.mt');
  const bottom = h('div.grid.g2.mt');
  root.append(hello, stats, middle, bottom);

  const draw = () => {
    hello.querySelector('.summary').textContent = digestSummary(o);
    const wa = o.whatsapp;
    const waOk = wa.status === 'open';
    const aiPct = Math.min(100, Math.round((o.ai.today / Math.max(1, o.ai.dailyLimit)) * 100));
    stats.replaceChildren(
      statCard({ ico: 'phone', title: 'WhatsApp', level: waOk ? 'ok' : wa.status === 'qr' ? 'warn' : 'err', value: waOk ? 'На связи' : wa.status === 'qr' ? 'Ждёт привязки' : 'Нет связи', sub: waOk ? `+${(wa.me?.id || '').split('@')[0]} · с ${ago(wa.connectedSince)}` : 'бот переподключается сам' }),
      statCard({ ico: 'book', title: 'Дневник BilimClass', level: o.bilim.ok ? (o.bilim.mode === 'site' ? 'warn' : 'ok') : 'err', value: o.bilim.ok ? (o.bilim.mode === 'site' ? 'Через сайт' : 'Работает') : 'Ошибка', sub: o.bilim.ok ? `обновлён ${ago(o.bilim.lastSyncAt)}` : o.bilim.error || '' }),
      statCard({ ico: 'spark', title: 'ИИ-помощник', level: o.ai.enabled ? 'ok' : 'warn', value: o.ai.enabled ? `${o.ai.today} ответов` : 'Выключен', sub: o.ai.enabled ? `сегодня из ${o.ai.dailyLimit} · ключ «${o.ai.key || '—'}»${o.ai.provider === 'backup' ? ' · запасной ИИ' : ''}` : 'добавьте ключ в «Ключи и доступ»', extra: o.ai.enabled ? h('div.bar', h('i', { style: { width: `${aiPct}%` } })) : null }),
      statCard({ ico: 'calendar', title: 'Рассылка', level: o.digest.pausedUntil ? 'warn' : 'ok', value: o.digest.sentToday ? 'Отправлена' : o.digest.today?.at ? `в ${o.digest.today.at}` : o.digest.pausedUntil ? 'Пауза' : 'Сегодня нет', sub: o.digest.last ? `последняя: ${o.digest.last.split('-').reverse().slice(0, 2).join('.')}` : 'ещё не было' }),
    );

    const today = ((new Date().getDay() + 6) % 7);
    middle.replaceChildren(
      card('Активность за 2 недели', {
        right: h('div.legend', h('span', h('i', { style: { background: 'linear-gradient(#25d366,#22d3ee)' } }), 'ответы ИИ'), h('span', h('i', { style: { background: 'rgba(139,92,246,.7)' } }), 'личка')),
        body: chart(o.stats),
      }),
      card('График на неделю', {
        right: h('a.btn.btn-sm.btn-ghost', { href: '#/schedule' }, 'Изменить', icon('right')),
        body: h('ul.plan-list', o.digest.week.map((line, i) => {
          const [d, ...rest] = line.split(': ');
          const text = rest.join(': ');
          return h(`li${i === today ? '.today' : ''}${/не присылать/.test(text) ? '.off' : ''}`, h('span.d', d), h('span.w', text));
        })),
        note: o.groups.length ? `Группы: ${o.groups.map((g) => g.name).join(', ')}` : 'Бот пока не привязан к группе — напишите в группе класса !привязать',
      }),
    );

    const alerts = o.alerts || [];
    bottom.replaceChildren(
      card('Последние события', {
        right: h('a.btn.btn-sm.btn-ghost', { href: '#/alerts' }, 'Все', icon('right')),
        body: alerts.length
          ? h('ul.list', alerts.slice(0, 6).map((a) => h('li', h(`span.ic.${a.level === 'error' ? 'err' : a.level}`, icon(a.level === 'ok' ? 'check' : 'bell')), h('span', a.text), h('span.when', ago(a.at)))))
          : emptyState('Всё спокойно', 'Проблем не было — бот работает штатно.'),
      }),
      card('Журнал', { right: h('a.btn.btn-sm.btn-ghost', { href: '#/terminal' }, 'Терминал', icon('right')), body: logBox }),
    );
  };
  draw();

  // живой мини-журнал
  const addLog = (item) => {
    if (!['info', 'warn', 'error', 'fatal'].includes(item.level)) return;
    logBox.prepend(h('div', h('time', clock(item.time)), h(`span.lv-${item.level}`, `${item.module ? `[${item.module}] ` : ''}${item.msg}`)));
    while (logBox.children.length > 40) logBox.lastChild.remove();
  };
  try {
    const { items } = await (await fetch('/api/logs?limit=30&level=info', { headers: { 'X-HWB': '1' } })).json();
    for (const item of items) addLog(item);
  } catch {
    /* журнал недоступен */
  }
  const offs = [
    on('sse:log', addLog),
    on('overview', (fresh) => {
      o = fresh;
      draw();
    }),
  ];
  return () => offs.forEach((off) => off());
}

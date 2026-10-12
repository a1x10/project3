// Терминал в панели: безопасный набор команд бота (не shell сервера — выполнить произвольную команду нельзя).
// Каждая команда возвращает строки { t: текст, c: класс } — ok | warn | err | dim | acc | head.
import { formatDay, formatSchedule, formatWeek } from '../homework/format.js';
import { addDays, formatClock, mondayOf, nowParts, parseDayArg, toDM } from '../utils/dates.js';
import { normalizePhone } from '../config.js';
import { mask } from '../secrets.js';

const line = (t, c) => ({ t: String(t), ...(c ? { c } : {}) });
const ago = (ts) => {
  if (!ts) return '—';
  const s = Math.round((Date.now() - ts) / 1000);
  if (s < 60) return `${s} с назад`;
  if (s < 3600) return `${Math.round(s / 60)} мин назад`;
  if (s < 86400) return `${Math.round(s / 3600)} ч назад`;
  return `${Math.round(s / 86400)} д назад`;
};
const uptime = (ms) => {
  const m = Math.floor(ms / 60000);
  return `${Math.floor(m / 1440)} д ${Math.floor((m % 1440) / 60)} ч ${m % 60} мин`;
};

// "a b 'c d'" → ['a', 'b', 'c d']
export function tokenize(input) {
  const out = [];
  const re = /"([^"]*)"|'([^']*)'|(\S+)/g;
  let m;
  while ((m = re.exec(input))) out.push(m[1] ?? m[2] ?? m[3]);
  return out;
}

const HELP = [
  ['status', 'состояние бота: WhatsApp, дневник, ИИ, рассылка'],
  ['logs [N] [warn|error]', 'последние записи журнала'],
  ['logs -f', 'живой журнал (Ctrl+C — остановить)'],
  ['dz [завтра|пт|20.10]', 'ДЗ на день — свежие данные из дневника'],
  ['week [след]', 'ДЗ на неделю'],
  ['lessons [день]', 'расписание уроков'],
  ['check', 'проверить дневник на новые ДЗ и прислать их'],
  ['digest preview', 'что уйдёт в рассылку (без отправки)'],
  ['digest send', 'отправить рассылку в группы сейчас'],
  ['plan', 'график рассылок по дням'],
  ['pause [N|до 20.10] · resume · skip [день]', 'пауза / продолжить / пропустить день'],
  ['groups', 'группы бота'],
  ['queue', 'очередь исходящих сообщений'],
  ['wa status|reconnect|relink', 'WhatsApp: состояние, переподключение, новая привязка'],
  ['bilim status|relogin', 'BilimClass: вход, способ получения дневника'],
  ['ai ask <вопрос>', 'спросить ИИ (проверка)'],
  ['ai keys', 'ключи ИИ'],
  ['send <номер|id> <текст>', 'написать от имени бота'],
  ['get <настройка> · set <настройка> <значение> · settings', 'настройки'],
  ['alerts', 'журнал уведомлений'],
  ['uptime · whoami · date · clear', 'разное'],
  ['restart --yes', 'перезапустить бота'],
];

export class Terminal {
  constructor(app) {
    this.app = app; // { config, settings, scheduler, homework, wa, core, inbox, keys, backup, assistant, diary, bilim, logBuffer, restart }
  }

  async run(input, { session } = {}) {
    const args = tokenize(String(input || '').trim());
    const [cmd = '', ...rest] = args;
    const name = cmd.toLowerCase();
    if (!name) return [];
    const handler = this.commands()[name];
    if (!handler) return [line(`${cmd}: команда не найдена. Список команд — help`, 'err')];
    try {
      const result = await handler(rest, { session, raw: input });
      return Array.isArray(result) ? result : [result];
    } catch (error) {
      return [line(`Ошибка: ${error.message}`, 'err')];
    }
  }

  commands() {
    const a = this.app;
    return {
      help: () => [line('Команды бота (это не shell сервера):', 'head'), ...HELP.map(([c, d]) => line(`  ${c.padEnd(46)} ${d}`)), line('Tab — дополнение, ↑/↓ — история.', 'dim')],
      '?': () => this.commands().help(),
      clear: () => ({ clear: true }),
      cls: () => ({ clear: true }),
      date: () => {
        const now = nowParts(a.config.timezone);
        return line(`${now.iso} ${formatClock(now.minutes)} (${a.config.timezone})`);
      },
      uptime: () => line(`Работает ${uptime(Date.now() - a.core.startedAt)} · память ${Math.round(process.memoryUsage().rss / 1048576)} МБ · Node ${process.version}`),
      whoami: (_, { session }) => line(`Админ панели · вход: ${session?.method || '—'} · IP ${session?.ip || '—'} · с ${session ? new Date(session.createdAt).toLocaleString('ru-RU') : '—'}`),
      status: () => this.status(),
      logs: (r) => this.logs(r),
      tail: () => ({ follow: true }),
      dz: (r) => this.day(r.join(' ')),
      'дз': (r) => this.day(r.join(' ')),
      week: (r) => this.week(r[0]),
      lessons: (r) => this.lessons(r.join(' ')),
      check: async () => {
        const result = await a.scheduler.runPoll({ manual: true });
        return line(result.added + result.changed ? `Найдено изменений: ${result.added + result.changed} — отправлено в группы` : 'Дневник проверен — новых ДЗ нет', 'ok');
      },
      digest: (r) => this.digest(r[0]),
      plan: () => [line('График рассылок:', 'head'), ...a.scheduler.weekPlanLines().map((l) => line(`  ${l}`)), line(this.todayPlan(), 'dim')],
      pause: (r) => this.pause(r),
      resume: () => {
        a.settings.resume();
        return line('▶ Рассылки снова включены', 'ok');
      },
      skip: (r) => {
        const today = a.homework.today();
        const date = r.length ? parseDayArg(r.join(' '), today) : today;
        if (!date) return line('Не понял день: skip, skip завтра, skip 20.10', 'err');
        const skipped = a.config.schedule.skipDates.includes(date);
        a.settings.skipDate(date, !skipped);
        return line(skipped ? `Пропуск ${toDM(date)} отменён` : `${toDM(date)} рассылки не будет`, 'ok');
      },
      groups: () => this.groups(),
      queue: () => {
        const q = a.wa.queue || [];
        if (!q.length) return line('Очередь пуста — всё отправлено', 'ok');
        return [line(`В очереди: ${q.length}`, 'head'), ...q.slice(0, 20).map((i) => line(`  → ${i.jid} · ${i.content?.text ? i.content.text.slice(0, 60) : i.content?.caption || '[фото]'} · ${ago(i.createdAt)}`))];
      },
      wa: (r) => this.wa(r[0]),
      bilim: (r) => this.bilim(r[0]),
      ai: (r) => this.ai(r),
      send: (r) => this.send(r),
      get: (r) => {
        const row = a.settings.describe().find((f) => f.path === r[0]);
        if (!row) return line('Нет такой настройки. Список: settings', 'err');
        return line(`${row.path} = ${JSON.stringify(row.value)}${row.overridden ? ' (изменено в панели)' : ''}`);
      },
      set: (r) => {
        const [path, ...value] = r;
        if (!path || !value.length) return line('Формат: set <настройка> <значение>', 'err');
        let parsed = value.join(' ');
        if (/^[[{]/.test(parsed)) parsed = JSON.parse(parsed);
        const changed = a.settings.update({ [path]: parsed }, { by: 'terminal' });
        return line(changed.length ? `✓ ${path} изменено` : 'Значение и так такое', 'ok');
      },
      settings: () => a.settings.describe().map((f) => line(`${f.path.padEnd(36)} ${typeof f.value === 'object' ? JSON.stringify(f.value).slice(0, 80) : f.value}${f.overridden ? '  *' : ''}`, f.overridden ? 'acc' : undefined)),
      alerts: () => {
        const log = a.core.store.data.alertLog || [];
        if (!log.length) return line('Уведомлений не было 👌', 'ok');
        return log.slice(0, 25).map((e) => line(`${new Date(e.at).toLocaleString('ru-RU')}  ${e.text}`, e.level === 'error' ? 'err' : e.level === 'ok' ? 'ok' : 'warn'));
      },
      restart: (r) => {
        if (!a.restart) return line('Перезапуск недоступен: бот запущен без Docker/PM2/systemd — перезапустите его на сервере', 'err');
        if (r[0] !== '--yes') return line('Бот перезапустится (Docker/PM2 поднимут его снова). Подтвердите: restart --yes', 'warn');
        a.restart();
        return line('Перезапуск… Страница переподключится сама через несколько секунд.', 'warn');
      },
      exit: () => line('Это терминал бота, а не SSH 🙂 Закройте вкладку или выберите другой раздел.', 'dim'),
      sudo: () => line('Здесь нет sudo — только команды бота. help — список.', 'dim'),
      ls: () => line('Здесь нет файловой системы — только команды бота. help — список.', 'dim'),
    };
  }

  todayPlan() {
    const plan = this.app.scheduler.plan;
    const today = this.app.homework.today();
    if (this.app.core.store.data.jobs.digest === today) return 'Сегодня рассылка уже отправлена';
    if (!plan || plan.date !== today) return 'План на сегодня ещё не рассчитан';
    if (plan.quiet) return `Сегодня рассылки нет: ${plan.quiet}`;
    if (plan.at == null) return 'Сегодня рассылки нет';
    return `Сегодня рассылка в ${formatClock(plan.at)}${plan.lessonsEnd != null ? ` (уроки до ${formatClock(plan.lessonsEnd)})` : ''}`;
  }

  status() {
    const a = this.app;
    const s = a.homework.status();
    const mode = a.diary?.status?.() || {};
    const usage = a.core.store.data.usage[a.homework.today()] || {};
    const keyInUse = a.keys?.list().find((k) => k.inUse);
    return [
      line('Состояние бота', 'head'),
      line(`  WhatsApp      ${a.wa.isOpen ? `на связи (${a.wa.me?.id?.split('@')[0] || ''})` : a.wa.status}`, a.wa.isOpen ? 'ok' : 'err'),
      line(`  Дневник       ${s.lastError ? `ошибка: ${s.lastError}` : `ок, обновлён ${ago(s.lastSuccessAt)}`}${mode.mode === 'site' ? ' · через сайт (API сбоит)' : ''}`, s.lastError ? 'err' : 'ok'),
      line(`  Класс         ${s.session?.className || '—'}${s.session?.schoolName ? `, ${s.session.schoolName}` : ''}`),
      line(`  ИИ            ${a.assistant.enabled ? `${a.config.ai.mode}, ключ ${keyInUse?.label || '—'}, ответов сегодня ${usage.ai || 0}/${a.config.ai.dailyLimit}` : 'выключен'}`, a.assistant.enabled ? 'ok' : 'warn'),
      line(`  Рассылка      ${this.todayPlan()}`),
      line(`  Группы        ${a.core.targets().length}`),
      line(`  Очередь       ${a.wa.queue?.length || 0}`),
      line(`  Работает      ${uptime(Date.now() - a.core.startedAt)}`),
    ];
  }

  logs(args) {
    if (args[0] === '-f' || args[0] === 'follow') return { follow: true };
    const n = Math.min(Number(args.find((x) => /^\d+$/.test(x))) || 40, 500);
    const level = args.find((x) => /^(debug|info|warn|error)$/.test(x)) || 'info';
    const items = this.app.logBuffer.recent(n, level);
    if (!items.length) return line('Журнал пуст', 'dim');
    return items.map((i) => ({ log: i }));
  }

  async day(arg) {
    const a = this.app;
    const today = a.homework.today();
    const date = arg ? parseDayArg(arg.replace(/^на\s+/i, ''), today) : (await a.homework.nextSchoolDay(today)) || addDays(today, 1);
    if (!date) return line('Не понял день: dz завтра, dz пт, dz 20.10', 'err');
    const view = await a.homework.dayView(date, { fresh: true });
    return formatDay(view, today, { footer: false }).split('\n').map((t) => line(t.replace(/\*/g, '')));
  }

  async week(arg) {
    const a = this.app;
    const today = a.homework.today();
    const monday = /^след/.test(arg || '') ? addDays(mondayOf(today), 7) : mondayOf(today);
    return formatWeek(await a.homework.weekView(monday), today).split('\n').map((t) => line(t.replace(/\*/g, '')));
  }

  async lessons(arg) {
    const a = this.app;
    const today = a.homework.today();
    const date = arg ? parseDayArg(arg, today) : today;
    if (!date) return line('Не понял день', 'err');
    return formatSchedule(await a.homework.dayView(date), today).split('\n').map((t) => line(t.replace(/\*/g, '')));
  }

  async digest(sub) {
    const a = this.app;
    if (sub === 'send') {
      const targets = a.scheduler.digestTargets();
      if (!targets.length) return line('Нет групп для рассылки', 'err');
      await a.scheduler.sendDigest({ targets, force: true, scope: a.scheduler.todayScope() });
      return line(`✓ Рассылка отправлена в очередь (групп: ${targets.length})`, 'ok');
    }
    const digest = await a.scheduler.buildDigest({ force: true, scope: a.scheduler.todayScope() });
    const out = [line(`Предпросмотр рассылки${digest.firstTime ? ' (первая — только на завтра)' : ''}:`, 'head')];
    for (const m of digest.messages || []) {
      if (m.image) out.push(line(`  🖼 фото · ${m.caption.replace(/\n/g, ' · ')}`, 'acc'));
      else out.push(...m.text.split('\n').map((t) => line(`  ${t.replace(/\*/g, '')}`)));
    }
    out.push(line(`Новых заданий: ${digest.fresh.length}. Отправить: digest send`, 'dim'));
    return out;
  }

  pause(args) {
    const a = this.app;
    const today = a.homework.today();
    const raw = args.join(' ').trim();
    let until = 'forever';
    if (/^\d{1,3}$/.test(raw)) until = addDays(today, Number(raw) - 1);
    else if (raw) {
      until = parseDayArg(raw.replace(/^(до|по)\s+/i, ''), today);
      if (!until) return line('Не понял срок: pause, pause 3, pause до 20.10', 'err');
    }
    a.settings.pause(until);
    return line(`⏸ Рассылки на паузе ${until === 'forever' ? 'до команды resume' : `по ${toDM(until)}`}`, 'warn');
  }

  async groups() {
    const a = this.app;
    const groups = a.wa.isOpen ? await a.wa.allGroups() : [];
    const targets = a.core.targets();
    if (!groups.length && !targets.length) return line('Групп нет', 'dim');
    const known = new Map(groups.map((g) => [g.id, g.subject]));
    for (const jid of targets) if (!known.has(jid)) known.set(jid, a.core.store.data.groups[jid]?.name || jid);
    return [...known].map(([jid, name]) => {
      const st = a.core.groupSettings(jid);
      const on = targets.includes(jid);
      return line(`${on ? '●' : '○'} ${name}  ${jid}${on ? `  ДЗ:${st.digest !== false ? 'да' : 'нет'} ИИ:${st.ai !== false ? 'да' : 'нет'}` : ''}`, on ? 'ok' : 'dim');
    });
  }

  async wa(sub = 'status') {
    const a = this.app;
    if (sub === 'reconnect') {
      a.wa.reconnect();
      return line('Переподключаюсь к WhatsApp…', 'warn');
    }
    if (sub === 'relink') return line('Новая привязка отвяжет текущую сессию. Сделайте это в разделе «Ключи и доступ» — там будет QR-код.', 'warn');
    const info = a.wa.info();
    return [
      line(`WhatsApp: ${info.status}${info.me ? ` · ${info.me.id}` : ''}`, a.wa.isOpen ? 'ok' : 'err'),
      line(`  на связи с ${info.connectedSince ? new Date(info.connectedSince).toLocaleString('ru-RU') : '—'} · очередь ${info.queue}`),
      info.lastDisconnect ? line(`  последний обрыв: код ${info.lastDisconnect.code ?? '—'}, ${ago(info.lastDisconnect.at)}`, 'dim') : line('  обрывов не было', 'dim'),
      info.pairingCode ? line(`  код привязки: ${info.pairingCode}`, 'acc') : null,
    ].filter(Boolean);
  }

  async bilim(sub = 'status') {
    const a = this.app;
    if (sub === 'relogin') {
      a.bilim.setCredentials({}); // сбросить токены и войти заново
      await a.bilim.login();
      return line(`✓ Вошёл в BilimClass: ${a.bilim.session?.fullName || ''} ${a.bilim.session?.className || ''}`, 'ok');
    }
    const st = a.diary.status();
    const s = a.homework.status();
    return [
      line(`BilimClass: ${s.lastError ? `ошибка — ${s.lastError}` : 'работает'}`, s.lastError ? 'err' : 'ok'),
      line(`  логин ${mask(a.config.bilim.login)} · вошёл: ${a.bilim.loggedIn ? 'да' : 'нет'}`),
      line(`  способ: ${st.mode === 'site' ? 'через сайт (запасной путь)' : 'API'}${st.siteAvailable ? ' · запасной путь через сайт готов' : ' · без браузера'}`),
      st.apiError ? line(`  последняя ошибка API: ${st.apiError}`, 'warn') : null,
      line(`  последнее обновление: ${ago(s.lastSuccessAt)}`, 'dim'),
    ].filter(Boolean);
  }

  async ai(args) {
    const a = this.app;
    const [sub, ...rest] = args;
    if (sub === 'keys') {
      const list = a.keys.list();
      const out = list.map((k) => line(`${k.inUse ? '●' : '○'} ${k.label.padEnd(20)} ${k.masked}  ${k.status}${k.lastError ? ` (${k.lastError})` : ''}`, k.status === 'invalid' ? 'err' : k.inUse ? 'ok' : undefined));
      const backup = a.backup.describe();
      out.push(line(`Запасной ИИ: ${backup.enabled ? `${backup.model} · ${backup.baseUrl}` : 'не настроен'}`, 'dim'));
      return out.length ? out : line('Ключей нет', 'warn');
    }
    if (sub === 'ask') {
      const question = rest.join(' ');
      if (!question) return line('Формат: ai ask <вопрос>', 'err');
      if (!a.assistant.enabled) return line('ИИ выключен или нет ключа', 'err');
      const answer = await a.assistant.answer({ question, senderName: 'Админ', isPrivate: true });
      return answer.split('\n').map((t) => line(t, 'acc'));
    }
    return line('ai ask <вопрос> · ai keys', 'dim');
  }

  async send(args) {
    const a = this.app;
    const [to, ...words] = args;
    const text = words.join(' ');
    if (!to || !text) return line('Формат: send <номер или id группы> <текст>', 'err');
    const jid = to.includes('@') ? to : `${normalizePhone(to)}@s.whatsapp.net`;
    if (!/^[\d-]+@(s\.whatsapp\.net|g\.us|lid)$/.test(jid)) return line('Неверный получатель', 'err');
    await a.wa.sendText(jid, text, { meta: { by: 'admin' } });
    if (!jid.endsWith('@g.us')) a.inbox?.takeover(jid);
    return line(`✓ Отправлено → ${jid}`, 'ok');
  }
}


import type { Auth } from './auth.js';
import type { Config } from './config.js';
import type { Store, User } from './db.js';
import { gatewaySettings, limitStatus } from './gateway.js';
import { esc, type TelegramClient, type TgCallback, type TgMessage, type TgUpdate } from './telegram.js';

const CLIENT_LABEL: Record<string, string> = { web: 'сайт', studio: 'Vibing AI Studio', stella: 'STELLA CODER', other: 'приложение' };
const fmt = (n: number | null) => (n === null ? '∞' : n.toLocaleString('ru-RU'));

/** All registration, sign-in approval, keys and administration happen in Telegram. */
export class Bot {
  constructor(
    private readonly tg: TelegramClient,
    private readonly store: Store,
    private readonly auth: Auth,
    private readonly cfg: Config,
  ) {}

  private isAdminTg(tgId: number) {
    return this.cfg.adminTgIds.includes(tgId);
  }

  /** Register on first contact; ADMIN_TELEGRAM_IDS (or the very first user when none set) become admins. */
  private ensureUser(from: NonNullable<TgMessage['from']>): { user: User; created: boolean } {
    const noAdmins = !this.cfg.adminTgIds.length && !(this.store.db.prepare("SELECT 1 FROM users WHERE role = 'admin'").get() as any);
    return this.store.upsertTgUser(from, this.isAdminTg(from.id) || noAdmins);
  }

  async handle(u: TgUpdate) {
    if (u.callback_query) return this.onCallback(u.callback_query);
    const m = u.message;
    if (!m?.text || !m.from || m.from.is_bot) return;
    if (m.chat.type !== 'private') return; // keys and codes only in private chats
    const { user, created } = this.ensureUser(m.from);
    const [cmdRaw, ...rest] = m.text.trim().split(/\s+/);
    const rawArg = m.text.trim().slice((cmdRaw ?? '').length).trim();
    const cmd = (cmdRaw ?? '').toLowerCase().replace(/@.*$/, '');
    const arg = rest.join(' ');
    const chat = m.chat.id;

    if (user.status !== 'active') return this.tg.send(chat, '⛔ Ваш аккаунт заблокирован администратором.');

    switch (cmd) {
      case '/start': {
        if (arg.startsWith('login_')) return this.offerLogin(chat, user, arg.slice(6));
        const lines = [
          created ? `✨ <b>Добро пожаловать, ${esc(user.name)}!</b>\nАккаунт создан${user.role === 'admin' ? ' — вы <b>администратор</b>' : ''}.` : `👋 С возвращением, ${esc(user.name)}!`,
          '',
          '<b>Как пользоваться</b>',
          `• Сайт и кабинет: ${esc(this.cfg.publicUrl)} — «Войти через Telegram»`,
          '• Vibing AI Studio (Windows) — кнопка «Войти через Telegram» в приложении',
          '• STELLA CODER — команда <code>stella-coder login</code> в терминале',
          '• Любой OpenAI-клиент — /key, адрес API: <code>' + esc(this.cfg.publicUrl) + '/v1</code>',
          '',
          '/me — аккаунт и лимиты · /keys — ключи · /help — все команды',
        ];
        return this.tg.send(chat, lines.join('\n'));
      }
      case '/help':
        return this.tg.send(chat, this.helpText(user));
      case '/me':
        return this.tg.send(chat, this.meText(user));
      case '/web':
        return this.tg.send(chat, `🌐 ${esc(this.cfg.publicUrl)}`);
      case '/key': {
        const { key } = this.auth.createApiKey(user.id, arg || 'Telegram', 'other');
        return this.tg.send(chat, `🔑 Новый API-ключ${arg ? ` «${esc(arg)}»` : ''}:\n<code>${key}</code>\n\nАдрес API: <code>${esc(this.cfg.publicUrl)}/v1</code>\nКлюч показывается один раз — сохраните его. Отозвать: /keys`);
      }
      case '/keys': {
        const keys = this.auth.listKeys(user.id);
        if (!keys.length) return this.tg.send(chat, 'Ключей нет. Создать: /key название');
        return this.tg.send(
          chat,
          '🔑 <b>Ваши ключи</b>\n' + keys.map((k) => `• ${esc(k.name)} — <code>${esc(k.prefix)}…</code>${k.last_used_at ? ` · ${new Date(k.last_used_at).toLocaleDateString('ru-RU')}` : ''}`).join('\n'),
          keys.slice(0, 10).map((k) => [{ text: `Отозвать «${k.name.slice(0, 30)}»`, callback_data: `revoke:${k.id}` }]),
        );
      }
      case '/login': {
        const req = this.auth.loginByCode(arg);
        if (!req) return this.tg.send(chat, 'Код не найден или устарел. Нажмите «Войти через Telegram» ещё раз и введите новый код: /login ABCD-1234');
        return this.offerLogin(chat, user, req.id);
      }
      case '/delete':
        return this.tg.send(chat, '⚠️ Удалить аккаунт вместе с ключами и историей? Это необратимо.', [[{ text: 'Да, удалить мой аккаунт', callback_data: 'delself' }], [{ text: 'Отмена', callback_data: 'cancel' }]]);
    }
    if (user.role === 'admin') return this.adminCommand(chat, user, cmd, rest, rawArg);
    return this.tg.send(chat, 'Не понял команду. /help — список команд.');
  }

  private helpText(user: User) {
    const base = [
      '<b>Команды</b>',
      '/me — аккаунт, тариф, лимиты',
      '/key [название] — новый API-ключ',
      '/keys — ключи и отзыв',
      '/login КОД — подтвердить вход по коду',
      '/web — ссылка на сайт',
      '/delete — удалить аккаунт',
    ];
    if (user.role === 'admin')
      base.push(
        '',
        '<b>Администрирование</b>',
        '/stats — статистика',
        '/users [поиск] — пользователи',
        '/user ID|@ник — карточка пользователя',
        '/plan ID тариф — сменить тариф (' + Object.keys(this.store.plans()).join(', ') + ')',
        '/ban ID · /unban ID — блокировка',
        '/admin ID · /unadmin ID — права администратора',
        '/deluser ID — удалить аккаунт',
        '/prompt — показать системный промпт · /setprompt ТЕКСТ — изменить',
        '/model ID — модель по умолчанию',
      );
    return base.join('\n');
  }

  private meText(user: User) {
    const lim = limitStatus(this.store, user);
    return [
      `👤 <b>${esc(user.name)}</b>${user.tg_username ? ` (@${esc(user.tg_username)})` : ''} · ID ${user.id}`,
      `Тариф: <b>${esc(lim.plan.name)}</b>${user.role === 'admin' ? ' · администратор' : ''}`,
      `Сегодня: ${fmt(lim.usage.requests)} / ${fmt(user.role === 'admin' ? null : lim.plan.dailyRequests)} запросов, ${fmt(lim.usage.tokens)} / ${fmt(user.role === 'admin' ? null : lim.plan.dailyTokens)} токенов`,
      `Ключей: ${this.auth.listKeys(user.id).length}`,
    ].join('\n');
  }

  private async offerLogin(chat: number, user: User, loginId: string) {
    const req = this.auth.getLogin(loginId);
    if (!req || req.status !== 'pending' || req.expires_at < Date.now()) return this.tg.send(chat, 'Запрос на вход устарел. Нажмите «Войти через Telegram» ещё раз.');
    return this.tg.send(
      chat,
      `🔐 <b>Вход: ${esc(CLIENT_LABEL[req.client] ?? req.client)}</b>${req.device ? `\nУстройство: ${esc(req.device)}` : ''}\nКод: <b>${esc(req.code)}</b>\n\nУбедитесь, что код совпадает с показанным на экране.`,
      [[{ text: '✅ Подтвердить вход', callback_data: `approve:${req.id}` }], [{ text: '❌ Это не я', callback_data: `deny:${req.id}` }]],
    );
  }

  private async onCallback(q: TgCallback) {
    const { user } = this.ensureUser(q.from);
    const chat = q.message?.chat.id ?? q.from.id;
    const mid = q.message?.message_id ?? 0;
    const [action, id] = (q.data ?? '').split(':');
    if (user.status !== 'active') return this.tg.answer(q.id, 'Аккаунт заблокирован');
    switch (action) {
      case 'approve':
      case 'deny': {
        const r = this.auth.decide(id!, user.id, action === 'approve');
        await this.tg.answer(q.id, r ? (action === 'approve' ? 'Вход подтверждён' : 'Вход отклонён') : 'Запрос устарел');
        return this.tg.edit(chat, mid, r ? (action === 'approve' ? `✅ Вход подтверждён: ${esc(CLIENT_LABEL[r.client] ?? r.client)}. Можно вернуться в приложение.` : '❌ Вход отклонён.') : 'Запрос на вход устарел.');
      }
      case 'revoke': {
        const ok = this.auth.revokeKey(user.id, Number(id));
        await this.tg.answer(q.id, ok ? 'Ключ отозван' : 'Ключ не найден');
        return this.tg.send(chat, ok ? '🗑 Ключ отозван.' : 'Ключ не найден.');
      }
      case 'delself': {
        this.store.deleteUser(user.id);
        await this.tg.answer(q.id, 'Аккаунт удалён');
        return this.tg.edit(chat, mid, 'Аккаунт удалён. Чтобы зарегистрироваться снова — /start');
      }
      case 'deluser': {
        if (user.role !== 'admin') return this.tg.answer(q.id, 'Нет прав');
        const target = this.store.userById(Number(id));
        if (!target) return this.tg.answer(q.id, 'Не найден');
        if (target.id === user.id) return this.tg.answer(q.id, 'Нельзя удалить себя');
        this.store.deleteUser(target.id);
        await this.tg.answer(q.id, 'Удалён');
        return this.tg.edit(chat, mid, `🗑 Пользователь ${esc(target.name)} (ID ${target.id}) удалён.`);
      }
      case 'ban':
      case 'unban': {
        if (user.role !== 'admin') return this.tg.answer(q.id, 'Нет прав');
        const target = this.store.userById(Number(id));
        if (!target) return this.tg.answer(q.id, 'Не найден');
        if (target.id === user.id) return this.tg.answer(q.id, 'Нельзя заблокировать себя');
        const t2 = this.store.updateUser(target.id, { status: action === 'ban' ? 'banned' : 'active' })!;
        if (action === 'ban') this.auth.revokeAllKeys(target.id);
        await this.tg.answer(q.id, action === 'ban' ? 'Заблокирован' : 'Разблокирован');
        return this.tg.edit(chat, mid, this.card(t2), this.cardButtons(t2));
      }
      case 'askdel': {
        if (user.role !== 'admin') return this.tg.answer(q.id, 'Нет прав');
        const target = this.store.userById(Number(id));
        if (!target) return this.tg.answer(q.id, 'Не найден');
        await this.tg.answer(q.id);
        return this.tg.send(chat, `Удалить ${esc(target.name)} (ID ${target.id}) со всеми ключами и историей?`, [[{ text: '🗑 Да, удалить', callback_data: `deluser:${target.id}` }], [{ text: 'Отмена', callback_data: 'cancel' }]]);
      }
      case 'cancel':
        await this.tg.answer(q.id);
        return this.tg.edit(chat, mid, 'Отменено.');
    }
    return this.tg.answer(q.id);
  }

  private card(u: User) {
    const lim = limitStatus(this.store, u);
    return `👤 <b>${esc(u.name)}</b>${u.tg_username ? ` @${esc(u.tg_username)}` : ''}\nID ${u.id} · tg ${u.tg_id} · ${u.role}${u.status === 'banned' ? ' · ⛔ заблокирован' : ''}\nТариф: ${esc(lim.plan.name)} (${esc(u.plan)}) · сегодня ${lim.usage.requests} запросов, ${lim.usage.tokens} токенов\nКлючей: ${this.auth.listKeys(u.id).length} · с ${new Date(u.created_at).toLocaleDateString('ru-RU')}`;
  }

  private cardButtons(t: User) {
    return [
      [
        { text: t.status === 'banned' ? '✅ Разблокировать' : '⛔ Заблокировать', callback_data: `${t.status === 'banned' ? 'unban' : 'ban'}:${t.id}` },
        { text: '🗑 Удалить', callback_data: `askdel:${t.id}` },
      ],
    ];
  }

  private async adminCommand(chat: number, admin: User, cmd: string, args: string[], rawArg = '') {
    const target = () => {
      const t = args[0] ? this.store.findUser(args[0]) : undefined;
      if (!t) void this.tg.send(chat, 'Пользователь не найден. Укажите ID или @ник.');
      return t;
    };
    switch (cmd) {
      case '/stats': {
        const s = this.store.stats();
        return this.tg.send(chat, `📊 Пользователей: <b>${s.users}</b> (новых сегодня ${s.newToday}, заблокировано ${s.banned})\nАктивных сегодня: ${s.activeToday}\nЗапросов сегодня: ${s.requestsToday} · токенов: ${s.tokensToday.toLocaleString('ru-RU')}`);
      }
      case '/users': {
        const { users, total } = this.store.listUsers({ q: args.join(' '), limit: 20 });
        if (!users.length) return this.tg.send(chat, 'Никого не найдено.');
        return this.tg.send(chat, `👥 ${total} пользователей${args.length ? ' (поиск)' : ''}:\n` + users.map((u) => `${u.status === 'banned' ? '⛔' : '•'} <b>${u.id}</b> ${esc(u.name)}${u.tg_username ? ` @${esc(u.tg_username)}` : ''} · ${esc(u.plan)}${u.role === 'admin' ? ' · admin' : ''} · ${u.requests_today} запр.`).join('\n'));
      }
      case '/user': {
        const t = target();
        if (!t) return;
        return this.tg.send(chat, this.card(t), this.cardButtons(t));
      }
      case '/plan': {
        const t = target();
        if (!t) return;
        const plan = args[1];
        if (!plan || !this.store.plans()[plan]) return this.tg.send(chat, `Тарифы: ${Object.keys(this.store.plans()).join(', ')}`);
        this.store.updateUser(t.id, { plan });
        return this.tg.send(chat, `✅ ${esc(t.name)}: тариф ${esc(plan)}`);
      }
      case '/ban':
      case '/unban': {
        const t = target();
        if (!t) return;
        if (t.id === admin.id) return this.tg.send(chat, 'Нельзя заблокировать себя.');
        this.store.updateUser(t.id, { status: cmd === '/ban' ? 'banned' : 'active' });
        if (cmd === '/ban') this.auth.revokeAllKeys(t.id);
        return this.tg.send(chat, `${cmd === '/ban' ? '⛔ Заблокирован (ключи отозваны)' : '✅ Разблокирован'}: ${esc(t.name)}`);
      }
      case '/admin':
      case '/unadmin': {
        const t = target();
        if (!t) return;
        if (t.id === admin.id && cmd === '/unadmin') return this.tg.send(chat, 'Нельзя снять права с себя.');
        this.store.updateUser(t.id, { role: cmd === '/admin' ? 'admin' : 'user' });
        return this.tg.send(chat, `✅ ${esc(t.name)}: ${cmd === '/admin' ? 'администратор' : 'обычный пользователь'}`);
      }
      case '/deluser': {
        const t = target();
        if (!t) return;
        if (t.id === admin.id) return this.tg.send(chat, 'Нельзя удалить себя.');
        return this.tg.send(chat, `Удалить ${esc(t.name)} (ID ${t.id}) со всеми ключами и историей?`, [[{ text: '🗑 Да, удалить', callback_data: `deluser:${t.id}` }], [{ text: 'Отмена', callback_data: 'cancel' }]]);
      }
      case '/prompt': {
        const s = gatewaySettings(this.store, this.cfg);
        return this.tg.send(chat, `🧠 Системный промпт (${s.promptMode === 'off' ? 'выключен' : 'добавляется к каждому запросу'}):\n<pre>${esc(s.systemPrompt || '(пусто)')}</pre>\nМодель по умолчанию: <code>${esc(s.defaultModel)}</code>`);
      }
      case '/setprompt': {
        const text = rawArg;
        this.store.setSetting('system_prompt', text);
        return this.tg.send(chat, text ? '✅ Системный промпт обновлён.' : '✅ Системный промпт очищен.');
      }
      case '/model': {
        if (!args[0]) return this.tg.send(chat, `Модель по умолчанию: <code>${esc(gatewaySettings(this.store, this.cfg).defaultModel)}</code>`);
        this.store.setSetting('default_model', args[0]);
        return this.tg.send(chat, `✅ Модель по умолчанию: <code>${esc(args[0])}</code>`);
      }
    }
    return this.tg.send(chat, 'Не понял команду. /help — список команд.');
  }

  start() {
    void this.tg.poll((u) => this.handle(u));
  }
}

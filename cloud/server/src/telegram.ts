/** Minimal Telegram Bot API client (long polling) — no third-party dependencies. */
export interface TgUser {
  id: number;
  is_bot?: boolean;
  first_name?: string;
  last_name?: string;
  username?: string;
}
export interface TgMessage {
  message_id: number;
  from?: TgUser;
  chat: { id: number; type: string };
  text?: string;
}
export interface TgCallback {
  id: string;
  from: TgUser;
  message?: TgMessage;
  data?: string;
}
export interface TgUpdate {
  update_id: number;
  message?: TgMessage;
  callback_query?: TgCallback;
}

export type InlineKeyboard = Array<Array<{ text: string; callback_data?: string; url?: string }>>;

export class TelegramClient {
  private offset = 0;
  private stopped = false;
  private controller: AbortController | null = null;
  username = '';

  constructor(
    private readonly token: string,
    private readonly apiBase = 'https://api.telegram.org',
  ) {}

  get enabled() {
    return !!this.token;
  }

  async call<T = any>(method: string, params: Record<string, unknown> = {}, signal?: AbortSignal): Promise<T> {
    const res = await fetch(`${this.apiBase}/bot${this.token}/${method}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(params),
      signal,
    });
    const j: any = await res.json().catch(() => ({ ok: false, description: `HTTP ${res.status}` }));
    if (!j.ok) throw new Error(`Telegram ${method}: ${j.description ?? res.status}`);
    return j.result as T;
  }

  async init(): Promise<void> {
    const me = await this.call<TgUser>('getMe');
    this.username = me.username ?? '';
    await this.call('setMyCommands', {
      commands: [
        { command: 'start', description: 'Регистрация и вход' },
        { command: 'me', description: 'Мой аккаунт и лимиты' },
        { command: 'key', description: 'Создать API-ключ' },
        { command: 'keys', description: 'Мои ключи' },
        { command: 'login', description: 'Войти по коду с сайта или приложения' },
        { command: 'help', description: 'Помощь' },
      ],
    }).catch(() => undefined);
  }

  send(chatId: number, text: string, keyboard?: InlineKeyboard) {
    return this.call('sendMessage', {
      chat_id: chatId,
      text,
      parse_mode: 'HTML',
      disable_web_page_preview: true,
      ...(keyboard ? { reply_markup: { inline_keyboard: keyboard } } : {}),
    });
  }

  edit(chatId: number, messageId: number, text: string, keyboard?: InlineKeyboard) {
    return this.call('editMessageText', { chat_id: chatId, message_id: messageId, text, parse_mode: 'HTML', disable_web_page_preview: true, reply_markup: { inline_keyboard: keyboard ?? [] } }).catch(() => undefined);
  }

  answer(callbackId: string, text?: string) {
    return this.call('answerCallbackQuery', { callback_query_id: callbackId, text }).catch(() => undefined);
  }

  /** Long-poll forever; errors back off and never stop the loop. */
  async poll(onUpdate: (u: TgUpdate) => Promise<void>) {
    let backoff = 1000;
    while (!this.stopped) {
      this.controller = new AbortController();
      try {
        const updates = await this.call<TgUpdate[]>('getUpdates', { offset: this.offset, timeout: 25, allowed_updates: ['message', 'callback_query'] }, this.controller.signal);
        backoff = 1000;
        for (const u of updates) {
          this.offset = u.update_id + 1;
          await onUpdate(u).catch((e) => console.error('[bot] handler error:', (e as Error).message));
        }
      } catch (e) {
        if (this.stopped) break;
        console.error('[bot] polling error:', (e as Error).message);
        await new Promise((r) => setTimeout(r, backoff));
        backoff = Math.min(backoff * 2, 30_000);
      }
    }
  }

  stop() {
    this.stopped = true;
    this.controller?.abort();
  }
}

export const esc = (s: unknown) => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

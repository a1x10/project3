// Общие функции бота: какие группы обслуживаем, кто админ, уведомления админам, статистика.
import { EventEmitter } from 'node:events';
import { normalize } from './utils/text.js';
import { nowParts } from './utils/dates.js';
import { findParticipant, senderIds, senderPhone } from './whatsapp/identity.js';

export class BotCore extends EventEmitter {
  constructor({ config, store, wa, logger }) {
    super();
    this.config = config;
    this.store = store;
    this.wa = wa;
    this.logger = logger;
    this.startedAt = Date.now();
  }

  // Группы, куда отправляется ДЗ: из .env (WA_GROUP_IDS) + привязанные командой !привязать
  targets() {
    return [...new Set([...this.config.whatsapp.groupIds, ...Object.keys(this.store.data.groups)])];
  }

  isTarget(jid) {
    return this.targets().includes(jid);
  }

  groupSettings(jid) {
    return { ai: true, digest: true, ...(this.store.data.groups[jid] || {}) };
  }

  bindGroup(jid, name) {
    this.store.update((s) => {
      s.groups[jid] = { ...(s.groups[jid] || { ai: true, digest: true }), name, boundAt: Date.now() };
    });
  }

  unbindGroup(jid) {
    this.store.update((s) => {
      delete s.groups[jid];
    });
  }

  setGroupOption(jid, key, value) {
    this.store.update((s) => {
      s.groups[jid] = { ...(s.groups[jid] || { ai: true, digest: true }), [key]: value };
    });
  }

  // Автопривязка группы по названию из WA_GROUP_NAME
  async autoBindByName() {
    if (!this.wa.isOpen) return;
    try {
      const groups = await this.wa.allGroups();
      if (!this.groupsLogged) {
        this.groupsLogged = true;
        this.logger.info(
          { groups: groups.map((g) => `${g.subject} → ${g.id}${this.isTarget(g.id) ? ' (ДЗ отправляется сюда)' : ''}`) },
          `Бот состоит в группах: ${groups.length}`,
        );
      }
      const wanted = normalize(this.config.whatsapp.groupName);
      if (wanted) {
        for (const g of groups) {
          if (normalize(g.subject) === wanted && !this.isTarget(g.id)) {
            this.bindGroup(g.id, g.subject);
            this.logger.info({ group: g.subject }, 'Группа привязана по названию WA_GROUP_NAME');
          }
        }
      }
      if (!this.targets().length) {
        this.logger.warn('Нет группы для отправки ДЗ. Добавьте бота в группу класса и напишите там: !привязать (нужны права админа)');
      }
    } catch (error) {
      this.logger.warn({ err: error.message }, 'Не удалось получить список групп');
    }
  }

  async isAdmin(ctx) {
    if (ctx.isOwner) return true;
    const phone = await senderPhone(ctx, this.wa.sock);
    if (phone && this.config.whatsapp.admins.includes(phone)) return true;
    if (!this.config.whatsapp.groupAdminsAreBotAdmins) return false;
    // админы привязанных групп тоже считаются админами бота
    const groups = ctx.isGroup ? [ctx.chat] : this.targets();
    for (const jid of groups) {
      try {
        const participant = findParticipant(await this.wa.groupMetadata(jid), senderIds(ctx));
        if (participant?.admin) return true;
      } catch {
        /* группа недоступна */
      }
    }
    return false;
  }

  async isMember(ctx) {
    for (const jid of this.targets()) {
      try {
        if (findParticipant(await this.wa.groupMetadata(jid), senderIds(ctx))) return true;
      } catch {
        /* группа недоступна */
      }
    }
    return false;
  }

  // Можно ли этому человеку общаться с ботом в личке
  async canUsePrivate(ctx) {
    const mode = this.config.whatsapp.privateChat;
    if (mode === 'all') return true;
    if (await this.isAdmin(ctx)) return true;
    if (mode === 'members') return this.isMember(ctx);
    return false;
  }

  aiReady() {
    return Boolean(this.assistant?.enabled);
  }

  // Техническое уведомление: в журнал панели и админам в личку WhatsApp (только им — не в группу).
  // Одинаковые уведомления — не чаще throttleMs. level: error | warn | ok
  async notifyAdmins(key, text, throttleMs = 6 * 3600 * 1000) {
    const last = this.store.data.alerts[key] || 0;
    if (Date.now() - last < throttleMs) return;
    const level = /recovered|^ok-/.test(key) || text.startsWith('✅') ? 'ok' : /auth|down|failed|invalid/.test(key) ? 'error' : 'warn';
    const entry = { id: `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`, key, text, level, at: Date.now() };
    this.store.update((s) => {
      s.alerts[key] = Date.now();
      s.alertLog = [entry, ...(s.alertLog || [])].slice(0, 200);
    });
    this.logger.warn({ key }, `Уведомление админам: ${text}`);
    this.emit('alert', entry);
    if (this.config.notify?.whatsapp === false) return;
    const icon = level === 'ok' ? '' : '⚠️ ';
    for (const phone of this.config.whatsapp.admins) {
      this.wa.sendText(`${phone}@s.whatsapp.net`, `${icon}*Бот ДЗ*\n${text}`, { persist: true, maxAgeMs: 24 * 3600 * 1000 }).catch(() => {});
    }
  }

  clearAlert(key) {
    if (this.store.data.alerts[key]) {
      this.store.update((s) => {
        delete s.alerts[key];
      });
    }
  }

  // Личное сообщение всем админам (без журнала тревог): коды входа, отчёты
  messageAdmins(text, { maxAgeMs = 10 * 60 * 1000 } = {}) {
    const admins = this.config.whatsapp.admins;
    for (const phone of admins) this.wa.sendText(`${phone}@s.whatsapp.net`, text, { maxAgeMs }).catch(() => {});
    return admins.length;
  }

  // Вечерний отчёт админу: что бот сделал за день
  async dailyReport(now) {
    const usage = this.store.data.usage[now.iso] || {};
    const problems = (this.store.data.alertLog || []).filter((a) => a.at > Date.now() - 24 * 3600 * 1000 && a.level === 'error');
    const lines = [
      `📊 *Отчёт за ${now.iso.slice(8, 10)}.${now.iso.slice(5, 7)}*`,
      `• Рассылка ДЗ: ${this.store.data.jobs.digest === now.iso ? 'отправлена ✅' : 'не было'}`,
      `• Ответов ИИ: ${usage.ai || 0}${usage.voice ? `, голосовых: ${usage.voice}` : ''}${usage.vision ? `, фото: ${usage.vision}` : ''}`,
      `• Сообщений в личке: ${usage.dm || 0}`,
      `• WhatsApp: ${this.wa.isOpen ? 'на связи' : this.wa.status}, в очереди: ${this.wa.queue?.length || 0}`,
      problems.length ? `• Проблемы: ${problems.map((p) => p.text).slice(0, 3).join(' / ')}` : '• Проблем не было 👌',
    ];
    this.messageAdmins(lines.join('\n'), { maxAgeMs: 3 * 3600 * 1000 });
  }

  today() {
    return nowParts(this.config.timezone).iso;
  }

  usage(kind) {
    return this.store.data.usage[this.today()]?.[kind] || 0;
  }

  countUsage(kind) {
    const day = this.today();
    this.store.update((s) => {
      s.usage[day] = s.usage[day] || {};
      s.usage[day][kind] = (s.usage[day][kind] || 0) + 1;
    });
  }
}

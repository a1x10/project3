// Переписка: список чатов, сообщения, ответ от имени бота, управление ИИ в чате.
import { avatarColor, busy, clock, confirmDialog, dayLabel, del, emptyState, get, h, icon, initials, on, post, segmented, shortWhen, toast } from '../lib.js';

const AI_TEXT = { on: 'ИИ отвечает', paused: 'ИИ ждёт (вы отвечаете)', off: 'ИИ выключен' };

export async function render(root, { params, refreshOverview }) {
  let chats = [];
  let current = params[0] || null;
  let filter = '';

  const items = h('div.chat-items');
  const search = h('input.input', { type: 'search', placeholder: 'Поиск по имени или тексту', 'aria-label': 'Поиск', oninput: (e) => {
    filter = e.target.value.trim().toLowerCase();
    drawList();
  } });
  const list = h('aside.chat-list', h('div.chat-search', icon('search'), search), items);
  const view = h('section.chat-view');
  const wrap = h('div.chats', list, view);
  root.append(wrap);

  function drawList() {
    const shown = chats.filter((c) => !filter || c.name.toLowerCase().includes(filter) || (c.last?.text || '').toLowerCase().includes(filter) || c.phone.includes(filter));
    if (!shown.length) {
      items.replaceChildren(emptyState(chats.length ? 'Ничего не нашлось' : 'Переписки пока нет', chats.length ? '' : 'Когда ученики напишут боту в личку, чаты появятся здесь.'));
      return;
    }
    items.replaceChildren(...shown.map((c) => {
      const preview = c.last ? `${c.last.dir === 'out' ? (c.last.by === 'admin' ? 'Вы: ' : 'Бот: ') : ''}${c.last.text || (c.last.media === 'image' ? '📷 Фото' : c.last.media === 'voice' ? '🎤 Голосовое' : '📎 Файл')}` : '';
      return h(`button.chat-item${c.jid === current ? '.active' : ''}`, { type: 'button', onclick: () => open(c.jid) },
        h('span.avatar', { style: { '--av': avatarColor(c.jid) } }, c.isGroup ? icon('users') : initials(c.name)),
        h('span.chat-meta',
          h('span.l1', h('b', c.name), h('time', c.lastAt ? shortWhen(c.lastAt) : '')),
          h('span.l2', h('span', preview), c.ai !== 'on' && !c.isGroup ? h('span', { title: AI_TEXT[c.ai] }, icon(c.ai === 'off' ? 'x' : 'pause', `ai-ico ${c.ai}`)) : null, c.unread ? h('em.count', String(c.unread)) : null)));
    }));
  }

  async function loadList() {
    const r = await get('/api/chats');
    chats = r.chats;
    drawList();
  }

  function bubble(m, chat) {
    const who = m.dir === 'out' ? (m.by === 'admin' ? 'Вы (от имени бота)' : 'Бот') : chat.isGroup ? m.name : null;
    const media = m.media ? h('span.media', icon(m.media === 'image' ? 'image' : m.media === 'voice' ? 'mic' : 'file'), m.media === 'image' ? 'Фото' : m.media === 'voice' ? 'Голосовое' : 'Файл') : null;
    return h(`div.bubble.${m.dir}${m.by === 'admin' ? '.admin' : ''}`, who ? h('span.who', who) : null, media, media && m.text ? h('br') : null, m.text || '', h('time', clock(m.at)));
  }

  async function open(jid) {
    current = jid;
    wrap.classList.add('open');
    if (location.hash !== `#/chats/${encodeURIComponent(jid)}`) history.replaceState(null, '', `#/chats/${encodeURIComponent(jid)}`);
    drawList();
    let chat;
    try {
      chat = await get(`/api/chats/${encodeURIComponent(jid)}`);
    } catch (error) {
      view.replaceChildren(emptyState('Чат не найден', error.message));
      return;
    }
    const target = chats.find((c) => c.jid === jid);
    if (target) target.unread = 0;
    drawList();
    refreshOverview();

    const messages = h('div.messages', { role: 'log', 'aria-live': 'polite' });
    let lastDay = '';
    const addMessage = (m, animate = false) => {
      const day = new Date(m.at).toDateString();
      if (day !== lastDay) {
        messages.append(h('div.day-sep', dayLabel(m.at)));
        lastDay = day;
      }
      const el = bubble(m, chat);
      if (!animate) el.style.animation = 'none';
      messages.append(el);
    };
    for (const m of chat.messages) addMessage(m);

    const aiControl = chat.isGroup ? null : segmented([['on', 'ИИ отвечает', 'on-green'], ['paused', 'Пауза 30 мин'], ['off', 'Выкл', 'on-red']], chat.ai, async (state) => {
      try {
        await post(`/api/chats/${encodeURIComponent(jid)}/ai`, { state });
        toast(state === 'on' ? 'ИИ снова отвечает в этом чате' : state === 'off' ? 'ИИ в этом чате выключен — отвечаете вы' : 'ИИ подождёт 30 минут');
        loadList();
      } catch (error) {
        toast(error.message, 'err');
      }
    });

    const hwBtn = h('button.btn.btn-sm', { type: 'button', title: 'Отправить в этот чат ДЗ на ближайший учебный день', onclick: (e) => busy(e.currentTarget, async () => {
      const r = await post(`/api/chats/${encodeURIComponent(jid)}/homework`, {});
      toast(`ДЗ на ${r.date.split('-').reverse().slice(0, 2).join('.')} отправлено`);
    }) }, icon('book'), 'Отправить ДЗ');
    const removeBtn = h('button.btn.btn-sm.btn-ghost.btn-icon', { type: 'button', title: 'Удалить переписку из панели', onclick: async () => {
      if (!(await confirmDialog({ title: 'Удалить переписку?', text: 'Сообщения пропадут только из панели — у ученика в WhatsApp всё останется.', ok: 'Удалить', danger: true }))) return;
      await del(`/api/chats/${encodeURIComponent(jid)}`).catch((error) => toast(error.message, 'err'));
      current = null;
      wrap.classList.remove('open');
      view.replaceChildren(placeholder());
      loadList();
    } }, icon('trash'));

    const input = h('textarea.textarea', { rows: 1, placeholder: 'Ответить от имени бота…', 'aria-label': 'Сообщение', maxlength: 4000 });
    const send = h('button.btn.btn-primary', { type: 'button', title: 'Отправить (Enter)' }, icon('send'));
    const doSend = () => busy(send, async () => {
      const text = input.value.trim();
      if (!text) return;
      await post(`/api/chats/${encodeURIComponent(jid)}/send`, { text });
      input.value = '';
      input.style.height = '';
      if (!chat.isGroup) aiControl?.set('paused');
    });
    send.onclick = doSend;
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        doSend();
      }
    });
    input.addEventListener('input', () => {
      input.style.height = 'auto';
      input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
    });

    view.replaceChildren(
      h('header.chat-head',
        h('button.btn.btn-icon.btn-ghost.btn-sm.chat-back', { type: 'button', 'aria-label': 'Назад', onclick: () => {
          wrap.classList.remove('open');
          current = null;
          history.replaceState(null, '', '#/chats');
          drawList();
        } }, icon('back')),
        h('span.avatar', { style: { '--av': avatarColor(jid) } }, chat.isGroup ? icon('users') : initials(chat.name)),
        h('div.who', h('b', chat.name), h('span', chat.isGroup ? 'группа · видны сообщения бота и обращения к нему' : chat.phone ? `+${chat.phone}` : 'личный чат')),
        h('div.right', aiControl, chat.isGroup ? null : hwBtn, removeBtn)),
      messages,
      h('div.composer', input, send),
      h('p.composer-note', chat.isGroup ? 'Сообщение увидит вся группа — от имени бота.' : 'Ученик увидит ответ от имени бота. После вашего ответа ИИ замолкает в этом чате на 30 минут.'),
    );
    messages.scrollTop = messages.scrollHeight;
    if (matchMedia('(min-width: 981px)').matches) input.focus();

    view.addMessage = (m) => {
      const atBottom = messages.scrollHeight - messages.scrollTop - messages.clientHeight < 120;
      addMessage(m, true);
      if (atBottom || m.dir === 'out') messages.scrollTop = messages.scrollHeight;
    };
  }

  function placeholder() {
    return h('div.chat-empty', h('div', icon('chat'), h('b', 'Выберите чат'), h('p', 'Здесь видно, о чём ученики спрашивают бота, и можно ответить самому.')));
  }

  view.append(placeholder());
  await loadList();
  if (current) open(current);
  else if (chats.length && matchMedia('(min-width: 981px)').matches) open(chats[0].jid);

  const offs = [
    on('sse:chat', (e) => {
      const i = chats.findIndex((c) => c.jid === e.jid);
      const summary = { ...e.chat };
      if (e.jid === current) {
        summary.unread = 0;
        view.addMessage?.(e.message);
        // чат открыт — сообщение прочитано
        if (e.message.dir === 'in') get(`/api/chats/${encodeURIComponent(e.jid)}`).then(() => refreshOverview()).catch(() => {});
      }
      if (i >= 0) chats.splice(i, 1);
      chats.unshift(summary);
      drawList();
    }),
    on('sse:chatState', (c) => {
      const i = chats.findIndex((x) => x.jid === c.jid);
      if (i >= 0) chats[i] = { ...chats[i], ai: c.ai };
      drawList();
    }),
  ];
  return () => offs.forEach((off) => off());
}


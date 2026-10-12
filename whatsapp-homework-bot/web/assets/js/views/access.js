// Ключи и доступ: ключи Groq, запасной ИИ, вход в BilimClass, WhatsApp (переподключить / привязать заново),
// безопасность панели (пароль, сессии), перезапуск бота.
import { ago, busy, card, confirmDialog, del, get, h, icon, modal, post, put, toast, toggle } from '../lib.js';

const STATUS = { ok: ['ok', 'работает'], invalid: ['err', 'не принят'], unknown: ['', 'не проверен'] };

export async function render(root, { refreshOverview }) {
  let data = await get('/api/access');
  const content = h('div.stack');
  root.append(content);
  let qrTimer = null;

  async function reload() {
    data = await get('/api/access');
    draw();
  }

  // --- ключи Groq ---
  function keysCard() {
    const rows = data.groq.length ? data.groq.map((k) => {
      const [cls, text] = STATUS[k.status] || STATUS.unknown;
      return h(`div.key-row${k.inUse ? '.in-use' : ''}`,
        h('div',
          h('div.k1', h('b', k.label), h('code', k.masked), h(`span.badge${cls ? `.${cls}` : ''}`, text), k.inUse ? h('span.badge.acc', 'используется') : null, k.source === 'env' ? h('span.badge', 'из .env') : null),
          h('div.k2', k.lastError ? `Ошибка: ${k.lastError}` : k.lastOkAt ? `Последний успешный запрос ${ago(k.lastOkAt)}` : k.addedAt ? `Добавлен ${ago(k.addedAt)}` : '')),
        h('div.acts',
          h('button.btn.btn-sm', { type: 'button', onclick: (e) => busy(e.currentTarget, async () => {
            const r = await post(`/api/access/groq/${k.id}/test`);
            data.groq = r.keys;
            toast(r.test.ok ? `Ключ работает · моделей: ${r.test.models}` : `Ключ не работает: ${r.test.message}`, r.test.ok ? 'ok' : 'err');
            draw();
          }) }, icon('zap'), 'Проверить'),
          k.inUse ? null : h('button.btn.btn-sm', { type: 'button', onclick: (e) => busy(e.currentTarget, async () => {
            data.groq = (await post(`/api/access/groq/${k.id}/activate`)).keys;
            toast(`Теперь используется «${k.label}»`);
            draw();
          }) }, 'Сделать основным'),
          h('button.btn.btn-sm.btn-ghost.btn-icon', { type: 'button', title: 'Удалить ключ', onclick: async () => {
            if (!(await confirmDialog({ title: `Удалить ключ «${k.label}»?`, text: k.source === 'env' ? 'Ключ останется в .env, но бот перестанет им пользоваться.' : 'Ключ будет удалён из бота. В аккаунте Groq он останется — удалите его там, если он утёк.', ok: 'Удалить', danger: true }))) return;
            try {
              data.groq = (await del(`/api/access/groq/${k.id}`)).keys;
              toast('Ключ удалён');
              draw();
              refreshOverview();
            } catch (error) {
              toast(error.message, 'err');
            }
          } }, icon('trash'))));
    }) : [h('div.empty', h('b', 'Ключей нет'), 'Без ключа ИИ не отвечает. Ключ бесплатный: console.groq.com/keys')];

    const label = h('input.input.sm', { placeholder: 'Название, например «Основной»', maxlength: 40, style: { maxWidth: '220px' } });
    const key = h('input.input.sm', { type: 'password', placeholder: 'gsk_…', autocomplete: 'off', spellcheck: false });
    const add = h('button.btn.btn-primary.btn-sm', { type: 'button' }, icon('plus'), 'Добавить и проверить');
    add.onclick = () => busy(add, async () => {
      const r = await post('/api/access/groq', { key: key.value, label: label.value });
      data.groq = r.keys;
      key.value = '';
      label.value = '';
      toast(r.test.ok ? 'Ключ добавлен и работает ✅' : `Ключ добавлен, но не прошёл проверку: ${r.test.message}`, r.test.ok ? 'ok' : 'warn');
      draw();
      refreshOverview();
    });

    return card('Ключи Groq', {
      sub: 'ИИ-помощник',
      body: h('div.stack', h('div.keys', rows), h('div.row', label, h('div', { style: { flex: '1', minWidth: '220px' } }, key), add)),
      note: h('div.policy', 'Можно хранить несколько ключей одного вашего аккаунта Groq: если ключ отзовут или он утечёт, бот сам перейдёт на следующий и напишет админу. Лимиты Groq общие на аккаунт, поэтому ключи с разных аккаунтов ради обхода лимитов добавлять нельзя — это запрещено правилами Groq. Если Groq перегружен, поможет запасной ИИ ниже.'),
    });
  }

  // --- запасной ИИ ---
  function backupCard() {
    const b = data.backup;
    let enabled = b.enabled;
    const baseUrl = h('input.input.sm', { value: b.baseUrl, placeholder: 'https://openrouter.ai/api/v1' });
    const model = h('input.input.sm', { value: b.model, placeholder: 'например: meta-llama/llama-3.3-70b-instruct' });
    const key = h('input.input.sm', { type: 'password', placeholder: b.hasKey ? `сохранён (${b.key}) — оставьте пустым` : 'ключ API', autocomplete: 'off' });
    const save = h('button.btn.btn-sm.btn-primary', { type: 'button' }, 'Сохранить');
    save.onclick = () => busy(save, async () => {
      data.backup = (await put('/api/access/backup', { enabled, baseUrl: baseUrl.value, model: model.value, apiKey: key.value })).backup;
      key.value = '';
      toast(data.backup.enabled ? 'Запасной ИИ включён' : 'Сохранено');
      draw();
    });
    const test = h('button.btn.btn-sm', { type: 'button' }, icon('zap'), 'Проверить');
    test.onclick = () => busy(test, async () => {
      const r = await post('/api/access/backup/test');
      toast(r.ok ? `Запасной ИИ отвечает: «${r.text}»` : `Не работает: ${r.message}`, r.ok ? 'ok' : 'err');
    });
    return card('Запасной ИИ', {
      sub: 'если Groq недоступен',
      right: toggle(enabled, (v) => {
        enabled = v;
      }, 'Включить запасной ИИ'),
      body: h('div.fields',
        h('div.field', h('label.label', 'Адрес API (OpenAI-совместимый)'), baseUrl),
        h('div.grid.g2', h('div.field', h('label.label', 'Модель'), model), h('div.field', h('label.label', 'Ключ'), key)),
        h('div.row', save, b.enabled ? test : null)),
      note: 'Любой сервис с OpenAI-совместимым API: OpenRouter, Together, свой сервер. Подключается, только когда Groq не отвечает или перегружен. Фото запасному ИИ не отправляются.',
    });
  }

  // --- BilimClass ---
  function bilimCard() {
    const b = data.bilim;
    const login = h('input.input.sm', { placeholder: 'Логин BilimClass', autocomplete: 'off', spellcheck: false });
    const password = h('input.input.sm', { type: 'password', placeholder: 'Пароль', autocomplete: 'new-password' });
    const save = h('button.btn.btn-sm.btn-primary', { type: 'button' }, icon('check'), 'Проверить и сохранить');
    save.onclick = () => busy(save, async () => {
      const r = await put('/api/access/bilim', { login: login.value, password: password.value });
      password.value = '';
      toast(`Вход выполнен: ${[r.fullName, r.className].filter(Boolean).join(', ')} ✅`);
      reload();
      refreshOverview();
    });
    const relogin = h('button.btn.btn-sm', { type: 'button' }, icon('refresh'), 'Войти заново');
    relogin.onclick = () => busy(relogin, async () => {
      const r = await post('/api/access/bilim/relogin');
      toast(`Вход обновлён: ${r.className || 'ок'}`);
      reload();
      refreshOverview();
    });
    return card('Дневник BilimClass', {
      right: h(`span.badge.${b.error ? 'err' : b.mode === 'site' ? 'warn' : 'ok'}`, b.error ? 'ошибка' : b.mode === 'site' ? 'через сайт' : 'работает'),
      body: h('div.stack',
        h('dl.kv', h('dt', 'Ученик'), h('dd', [b.fullName, b.className].filter(Boolean).join(', ') || '—'), h('dt', 'Логин'), h('dd', b.loginHint || '—', b.fromPanel ? ' · задан в панели' : ' · из .env'), h('dt', 'Способ'), h('dd', b.mode === 'site' ? 'через сайт (API сбоит — бот переключился сам)' : 'API BilimClass'), b.error ? h('dt', 'Ошибка') : null, b.error ? h('dd', { style: { color: 'var(--red)' } }, b.error) : null),
        h('div.row', relogin),
        h('div.field', h('label.label', 'Сменить логин и пароль'), h('div.grid.g2', login, password), h('div.row', { style: { marginTop: '8px' } }, save))),
      note: 'Пароль проверяется входом в BilimClass и хранится только на вашем сервере (data/secrets.json, доступ только у владельца). В панель он не возвращается.',
    });
  }

  // --- WhatsApp ---
  function waCard() {
    const w = data.whatsapp;
    const ok = w.status === 'open';
    const reconnect = h('button.btn.btn-sm', { type: 'button' }, icon('refresh'), 'Переподключить');
    reconnect.onclick = () => busy(reconnect, async () => {
      await post('/api/access/whatsapp/reconnect');
      toast('Переподключаюсь к WhatsApp…');
      setTimeout(reload, 4000);
    });
    const relink = h('button.btn.btn-sm.btn-danger', { type: 'button' }, icon('qr'), 'Привязать заново');
    relink.onclick = async () => {
      const number = await confirmDialog({
        title: 'Привязать WhatsApp заново?',
        text: 'Текущая сессия будет отвязана, бот покажет новый QR-код (или код для входа по номеру). Делайте это, если сменили номер или WhatsApp «вылетел».',
        ok: 'Отвязать и показать QR',
        danger: true,
        input: { label: 'Номер для привязки по коду (необязательно)', placeholder: '77001234567 — или пусто для QR', hint: 'Код удобен, если телефон с ботом далеко от экрана.' },
      });
      if (number === false) return;
      try {
        await post('/api/access/whatsapp/relink', { confirm: 'ОТВЯЗАТЬ', pairingNumber: number || '' });
        showQr();
      } catch (error) {
        toast(error.message, 'err');
      }
    };
    return card('WhatsApp', {
      right: h(`span.badge.${ok ? 'ok' : w.status === 'qr' ? 'warn' : 'err'}`, ok ? 'на связи' : w.status === 'qr' ? 'ждёт привязки' : w.status),
      body: h('div.stack',
        h('dl.kv',
          h('dt', 'Номер бота'), h('dd', w.me?.id ? `+${w.me.id.split('@')[0]}` : '—'),
          h('dt', 'На связи'), h('dd', w.connectedSince ? `с ${new Date(w.connectedSince).toLocaleString('ru-RU')}` : '—'),
          h('dt', 'Последний обрыв'), h('dd', w.lastDisconnect ? `${ago(w.lastDisconnect.at)} (код ${w.lastDisconnect.code ?? '—'})` : 'не было'),
          h('dt', 'Админы'), h('dd', w.admins.length ? w.admins.join(', ') : 'не заданы — уведомления некому слать'),
          h('dt', 'Очередь'), h('dd', `${w.queue} сообщ.`)),
        h('div.row', reconnect, relink, w.status === 'qr' ? h('button.btn.btn-sm.btn-primary', { type: 'button', onclick: showQr }, icon('qr'), 'Показать QR') : null)),
      note: 'Бот сам переподключается при обрывах. «Переподключить» — если что-то зависло; «Привязать заново» — новая сессия через QR.',
    });
  }

  function showQr() {
    const box = h('div.stack', h('div.skeleton', { style: { height: '260px' } }));
    const tick = async () => {
      try {
        const r = await get('/api/access/whatsapp/qr');
        if (r.status === 'open') {
          box.replaceChildren(h('div.empty', h('b', '✅ WhatsApp подключён'), r.me?.id ? `+${r.me.id.split('@')[0]}` : ''));
          clearInterval(qrTimer);
          reload();
          refreshOverview();
          return;
        }
        if (r.pairingCode) {
          box.replaceChildren(h('div.pair-code', r.pairingCode), h('p.hint', 'Телефон бота → WhatsApp → Связанные устройства → Привязка устройства → «Привязать по номеру телефона» → введите код.'));
        } else if (r.qr) {
          box.replaceChildren(h('div.qr-box', h('img', { src: r.qr, alt: 'QR-код WhatsApp' })), h('p.hint', { style: { textAlign: 'center' } }, 'Телефон бота → WhatsApp → Настройки → Связанные устройства → Привязка устройства. QR обновляется сам.'));
        } else {
          box.replaceChildren(h('div.empty', h('b', 'Подключаюсь…'), `Статус: ${r.status}`));
        }
      } catch (error) {
        box.replaceChildren(h('div.empty', h('b', 'Нет ответа от бота'), error.message));
      }
    };
    clearInterval(qrTimer);
    qrTimer = setInterval(tick, 3000);
    tick();
    modal({ title: 'Привязка WhatsApp', body: box, onClose: () => clearInterval(qrTimer) });
  }

  // --- безопасность панели ---
  function panelCard() {
    const p = data.panel;
    const current = h('input.input.sm', { type: 'password', placeholder: 'Текущий пароль', autocomplete: 'current-password' });
    const next = h('input.input.sm', { type: 'password', placeholder: 'Новый пароль (от 10 символов)', autocomplete: 'new-password' });
    const save = h('button.btn.btn-sm.btn-primary', { type: 'button' }, icon('lock'), p.hasPassword ? 'Сменить пароль' : 'Задать пароль');
    save.onclick = () => busy(save, async () => {
      await put('/api/access/password', { current: current.value, next: next.value });
      current.value = '';
      next.value = '';
      toast('Пароль изменён. Остальные устройства вышли из панели.');
      reload();
    });
    const revoke = h('button.btn.btn-sm', { type: 'button' }, icon('logout'), 'Выйти на других устройствах');
    revoke.onclick = () => busy(revoke, async () => {
      data.panel.sessions = (await post('/api/access/sessions/revoke')).sessions;
      toast('Готово — остальные сессии закрыты');
      draw();
    });
    const method = { password: 'пароль', whatsapp: 'код WhatsApp', link: 'ссылка из WhatsApp' };
    return card('Безопасность панели', {
      body: h('div.stack',
        h('div.field', h('label.label', p.hasPassword ? 'Сменить пароль' : 'Пароль не задан — вход только по коду из WhatsApp'), h('div.grid.g2', p.hasPassword ? current : h('span'), next), h('div.row', { style: { marginTop: '8px' } }, save)),
        h('div.field', h('label.label', 'Где открыта панель'), h('ul.list', p.sessions.map((s) => h('li', h('span.ic', icon(s.current ? 'check' : 'user')), h('span', `${s.current ? 'Это устройство' : s.ua.replace(/\(.*?\)/g, '').slice(0, 60) || 'Устройство'} · ${method[s.method] || s.method}${s.ip ? ` · ${s.ip}` : ''}`), h('span.when', ago(s.lastSeen))))), h('div.row', { style: { marginTop: '8px' } }, revoke))),
      note: 'Восстановить доступ без пароля: напишите боту в личку !панель — придёт одноразовая ссылка (только админам). Или войдите по коду из WhatsApp.',
    });
  }

  function systemCard() {
    const restart = h('button.btn.btn-sm.btn-danger', { type: 'button' }, icon('power'), 'Перезапустить бота');
    restart.onclick = async () => {
      if (!(await confirmDialog({ title: 'Перезапустить бота?', text: 'Бот выключится и через несколько секунд запустится снова (Docker/PM2/systemd). Неотправленные сообщения сохранятся.', ok: 'Перезапустить', danger: true }))) return;
      await busy(restart, async () => {
        await post('/api/system/restart');
        toast('Перезапуск… Панель переподключится сама.', 'warn');
      });
    };
    const sys = data.system;
    return card('Система', {
      body: h('div.stack',
        h('dl.kv', h('dt', 'Версия бота'), h('dd', sys.version), h('dt', 'Node.js'), h('dd', sys.node)),
        h('div.row', sys.canRestart ? restart : null, h('a.btn.btn-sm', { href: '#/terminal' }, icon('terminal'), 'Открыть терминал'))),
      note: sys.canRestart ? 'После перезапуска бот сам подключится к WhatsApp и продолжит работу.' : 'Бот запущен без Docker/PM2/systemd, поэтому перезапуск из панели выключен.',
    });
  }

  function draw() {
    content.replaceChildren(
      h('div.grid.g2', keysCard(), h('div.stack', backupCard())),
      h('div.grid.g2', bilimCard(), waCard()),
      h('div.grid.g2', panelCard(), systemCard()),
    );
  }
  draw();
  return () => clearInterval(qrTimer);
}

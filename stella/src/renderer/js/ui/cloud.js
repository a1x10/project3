// Раздел «Stella Cloud» в настройках: вход на сервер, тариф, лимиты, коды подписки.
import { $, h, escapeHtml, toast } from './dom.js';
import { icon } from './icons.js';
import { block } from './page.js';

const num = (n) => Number(n || 0).toLocaleString('ru-RU');

export async function cloudSection(ctx) {
  const info = await window.stella.invoke('cloud:info');
  let me = null, err = '';
  if (info.connected) { try { me = await window.stella.invoke('cloud:me'); } catch (e) { err = e.message; } }
  const usage = (label, used, limit) => `<div class="usage-row"><span>${label}</span><div class="bond-bar" style="margin:0"><div style="width:${Math.min(100, limit ? (used / limit) * 100 : 0)}%"></div></div><span class="hint">${num(used)} / ${num(limit)}</span></div>`;
  const html = me ? `
    <div class="set"><div class="cloud-plan"><span class="tag" style="background:${escapeHtml(me.planColor || '#8b5cf6')}">${escapeHtml(me.planName)}</span>
      <div style="flex:1"><b>@${escapeHtml(me.username)}</b><div class="hint">${escapeHtml(info.url)} · ${me.planExpiresAt ? 'до ' + new Date(me.planExpiresAt).toLocaleDateString('ru-RU') : 'бессрочно'}</div></div>
      <button class="btn sm" id="cl-logout">${icon('logout', 14)} Выйти</button></div>
      ${usage('Сообщений сегодня', me.usage.messagesToday, me.limits.messagesPerDay)}
      ${usage('Озвучка за месяц (символы)', me.usage.ttsCharsMonth, me.limits.ttsCharsPerMonth)}
      ${usage('Распознаваний сегодня', me.usage.sttToday, me.limits.sttPerDay)}</div>
    <div class="set"><div class="set-row"><div class="lbl"><b>Использовать Stella Cloud</b><small>ИИ, голос и распознавание идут через сервер — свои ключи не нужны.</small></div><label class="switch"><input type="checkbox" data-key="cloudEnabled" ${ctx.settings.cloudEnabled ? 'checked' : ''}><span></span></label></div></div>
    ${block('Активировать код подписки', 'Код выдаёт администратор сервера, например PLUS-1A2B3C-4D5E6F.', `<div class="row"><input class="input" id="cl-code" placeholder="PLUS-XXXXXX-XXXXXX"><button class="btn" id="cl-redeem">Активировать</button></div>`)}`
    : `
    ${err ? `<div class="set"><p style="color:var(--danger);margin:0">${escapeHtml(err)}</p></div>` : ''}
    ${block('Адрес сервера', 'IP или домен сервера Stella Cloud, например http://203.0.113.10:8787', `<div class="row"><input class="input" id="cl-url" value="${escapeHtml(info.url)}" placeholder="http://IP:8787"><button class="btn" id="cl-check">Проверить</button></div><div class="note" id="cl-status"></div>`)}
    ${block('Аккаунт', 'Войди или зарегистрируйся — тариф и лимиты привязаны к аккаунту на сервере.', `
      <div class="field"><input class="input" id="cl-user" placeholder="Логин" autocomplete="username"></div>
      <div class="field"><input class="input" id="cl-pass" type="password" placeholder="Пароль (от 6 символов)" autocomplete="current-password"></div>
      <div class="row"><button class="btn primary" id="cl-login">Войти</button><button class="btn" id="cl-register">Зарегистрироваться</button></div>`)}`;
  const bind = (root, rerender) => {
    if (me) {
      $('#cl-logout', root).onclick = async () => { await window.stella.invoke('cloud:logout'); toast('Вы вышли из Stella Cloud', 'info'); rerender(); };
      $('#cl-redeem', root).onclick = async () => {
        try { const u = await window.stella.invoke('cloud:redeem', $('#cl-code', root).value); toast(`Тариф ${u.planName} активирован!`, 'success'); ctx.avatar.play('victory'); rerender(); }
        catch (e) { toast(e.message, 'error'); }
      };
      return;
    }
    const url = () => $('#cl-url', root).value.trim();
    $('#cl-check', root).onclick = async () => {
      const st = $('#cl-status', root);
      try { const r = await window.stella.invoke('cloud:health', url()); st.className = 'note ok'; st.innerHTML = `${icon('check', 14)} ${escapeHtml(r.name)} ${escapeHtml(r.version)} · ИИ ${r.ai ? '✓' : '✗'} · голос ${r.voice ? '✓' : '✗'}${r.openRegistration ? '' : ' · регистрация закрыта'}`; }
      catch (e) { st.className = 'note'; st.textContent = e.message; }
    };
    const auth = async (mode) => {
      try {
        const u = await window.stella.invoke('cloud:auth', { url: url(), username: $('#cl-user', root).value.trim(), password: $('#cl-pass', root).value, mode });
        toast(`Stella Cloud: вы вошли как ${u.username} (${u.planName})`, 'success');
        ctx.avatar.play('wave');
        rerender();
      } catch (e) { toast(e.message, 'error', 6000); }
    };
    $('#cl-login', root).onclick = () => auth('login');
    $('#cl-register', root).onclick = () => auth('register');
  };
  return { html, bind };
}

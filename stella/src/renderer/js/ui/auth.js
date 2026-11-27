import { $, $$, h, escapeHtml } from './dom.js';
import { icon } from './icons.js';

/** Экран регистрации/входа. Возвращает Promise<account>. */
export function showAuth(ctx, { mode = 'register' } = {}) {
  return new Promise((resolve) => {
    const root = $('#auth');
    root.classList.remove('hidden');
    let persona = 'stella';
    const render = async () => {
      const accounts = await window.stella.invoke('account:list');
      if (mode === 'login' && !accounts.length) mode = 'register';
      const P = ctx.info.personas;
      root.innerHTML = mode === 'register' ? `
        <div class="auth-card">
          <h2>Создание аккаунта</h2>
          <p class="lead">Познакомимся! Выбери, кто будет твоим ассистентом.</p>
          <div class="field"><label>Какую модель вы хотите?</label>
            <div class="persona-cards">${Object.values(P).map((x) => `<button class="persona-card ${x.id === persona ? 'active' : ''}" data-persona="${x.id}" style="--pc:${x.color}"><span class="check">${icon('check', 14)}</span><span class="emoji">${x.id === 'mark' ? '🧑‍💻' : '👩‍🚀'}</span><b>${x.name}</b><small>${escapeHtml(x.tagline)}</small></button>`).join('')}</div>
          </div>
          <div class="field"><label>Как тебя зовут?</label><input class="input" id="a-name" placeholder="Например, Алекс" maxlength="40"></div>
          <div class="field"><label>Логин</label><input class="input" id="a-user" placeholder="alex" maxlength="32" autocomplete="username"></div>
          <div class="field"><label>Email <span class="hint">необязательно</span></label><input class="input" id="a-email" placeholder="you@example.com" autocomplete="email"></div>
          <div class="field"><label>Пароль <span class="hint">необязательно</span></label><input class="input" type="password" id="a-pass" placeholder="Можно оставить пустым" autocomplete="new-password"></div>
          <div class="err" id="a-err"></div>
          <button class="btn primary" id="a-go" style="width:100%;padding:12px">${icon('sparkles', 16)} Начать</button>
          ${accounts.length ? '<div class="auth-switch">Уже есть аккаунт? <a id="a-switch">Войти</a></div>' : ''}
        </div>` : `
        <div class="auth-card">
          <h2>С возвращением!</h2>
          <p class="lead">Выбери аккаунт и войди.</p>
          <div class="field"><label>Логин</label><select class="select" id="a-user">${accounts.map((a) => `<option value="${escapeHtml(a.username)}">${escapeHtml(a.displayName)} (@${escapeHtml(a.username)})</option>`).join('')}</select></div>
          <div class="field"><label>Пароль</label><input class="input" type="password" id="a-pass" placeholder="Если задан" autocomplete="current-password"></div>
          <div class="err" id="a-err"></div>
          <button class="btn primary" id="a-go" style="width:100%;padding:12px">Войти</button>
          <div class="auth-switch">Нет аккаунта? <a id="a-switch">Создать</a></div>
        </div>`;
      const sw = $('#a-switch', root);
      if (sw) sw.onclick = () => { mode = mode === 'register' ? 'login' : 'register'; render(); };
      $$('.persona-card', root).forEach((el) => el.onclick = () => {
        persona = el.dataset.persona;
        $$('.persona-card', root).forEach((x) => x.classList.toggle('active', x === el));
        ctx.previewPersona(persona);
      });
      const name = $('#a-name', root), user = $('#a-user', root);
      if (name) name.addEventListener('input', () => { if (!user.dataset.touched) user.value = translit(name.value).toLowerCase().replace(/[^a-z0-9_.-]/g, '').slice(0, 32); });
      if (user && user.tagName === 'INPUT') user.addEventListener('input', () => { user.dataset.touched = '1'; });
      const go = async () => {
        const err = $('#a-err', root); err.textContent = '';
        try {
          const acc = mode === 'register'
            ? await window.stella.invoke('account:register', { displayName: name.value.trim(), username: user.value.trim() || translit(name.value).toLowerCase(), email: $('#a-email', root).value.trim(), password: $('#a-pass', root).value, persona })
            : await window.stella.invoke('account:login', { username: user.value, password: $('#a-pass', root).value });
          root.classList.add('hidden'); root.innerHTML = '';
          resolve(acc);
        } catch (e) { err.textContent = e.message; ctx.avatar.play('shake'); }
      };
      $('#a-go', root).onclick = go;
      root.querySelectorAll('input').forEach((i) => i.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); }));
      setTimeout(() => (name || $('#a-pass', root))?.focus(), 100);
    };
    render();
  });
}

const MAP = { а: 'a', б: 'b', в: 'v', г: 'g', д: 'd', е: 'e', ё: 'e', ж: 'zh', з: 'z', и: 'i', й: 'y', к: 'k', л: 'l', м: 'm', н: 'n', о: 'o', п: 'p', р: 'r', с: 's', т: 't', у: 'u', ф: 'f', х: 'h', ц: 'ts', ч: 'ch', ш: 'sh', щ: 'sch', ъ: '', ы: 'y', ь: '', э: 'e', ю: 'yu', я: 'ya', ' ': '_' };
export function translit(s) { return String(s || '').toLowerCase().split('').map((c) => MAP[c] ?? c).join(''); }

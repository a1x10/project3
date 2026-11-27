// Перетащи файл, папку или ярлык на персонажа — он его «съест» (уберёт в желудок, откуда можно выплюнуть).
import { escapeHtml } from './dom.js';
import { pick } from './presence.js';

const LINES = {
  stella: {
    eat: ['Ням! Вкусно 😋', 'Хрум-хрум! Спасибо!', 'Мм, свеженький файлик!', 'Ам! И нет его.'],
    many: ['Целый обед! Ням-ням!', 'Ого, сколько всего! Хрум!'],
    big: ['Ух, какой большой… Ик!', 'Тяжеловато… но я справилась!'],
    shortcut: 'Съела ярлык. Сама программа осталась на компьютере.',
    refuse: ['Фу, это я есть не буду!', 'Не-не-не, это нельзя!'],
    hungry: ['Дай-дай!', 'Это мне?', 'Ам?'],
    spit: 'Тьфу! Вернула на место.',
  },
  mark: {
    eat: ['Ням. Принято.', 'Хрум. Готово.', 'Минус один файл.', 'Утилизировано!'],
    many: ['Плотный обед. Спасибо.', 'Всё в желудок!'],
    big: ['Ох, тяжёлый… но съел.', 'Многовато, но справился.'],
    shortcut: 'Съел ярлык. Программа осталась на компьютере.',
    refuse: ['Это я есть не буду.', 'Нет, это важное.'],
    hungry: ['Давай сюда.', 'Это мне?'],
    spit: 'Ладно, вернул обратно.',
  },
};
export const eaterLines = (persona) => LINES[persona] || LINES.stella;

const fmt = (n) => (n > 1024 ** 3 ? (n / 1024 ** 3).toFixed(1) + ' ГБ' : n > 1024 ** 2 ? (n / 1024 ** 2).toFixed(1) + ' МБ' : Math.max(1, Math.round(n / 1024)) + ' КБ');

/**
 * @param {object} ctx — нужен ctx.avatar, ctx.say(text), ctx.settings, ctx.notify(html, actions)
 * @param {HTMLElement} target — куда можно бросать файлы
 * @param {HTMLElement} anchor — элемент, в котором нарисован аватар (для координат рта)
 */
export function attachEater(ctx, target, anchor) {
  let hungry = false;
  let leaveTimer = null;
  const lines = () => eaterLines(ctx.settings.persona);
  const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes('Files');

  // запрещаем браузеру «открывать» брошенный файл вместо обработки
  for (const ev of ['dragover', 'drop']) window.addEventListener(ev, (e) => { if (hasFiles(e)) e.preventDefault(); });

  const startHungry = () => {
    clearTimeout(leaveTimer);
    if (hungry) return;
    hungry = true;
    ctx.avatar.setPosture('stand');
    ctx.avatar.play('hungry', { loop: true });
    ctx.avatar.setEmotion('surprised', 3);
    ctx.avatar.setMouth({ aa: 0.9 });
    target.classList.add('eater-hover');
    ctx.bubble?.(pick(lines().hungry));
  };
  const stopHungry = () => {
    hungry = false;
    ctx.avatar.stop();
    ctx.avatar.setMouth(null);
    target.classList.remove('eater-hover');
  };

  target.addEventListener('dragenter', (e) => { if (hasFiles(e)) { e.preventDefault(); startHungry(); } });
  target.addEventListener('dragover', (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    startHungry();
    const r = anchor.getBoundingClientRect();
    ctx.avatar.lookAt((e.clientX - (r.left + r.width / 2)) / (r.width * 0.8), (e.clientY - (r.top + r.height * 0.25)) / (r.height * 0.6));
  });
  target.addEventListener('dragleave', (e) => {
    if (!hasFiles(e)) return;
    leaveTimer = setTimeout(stopHungry, 120); // dragleave приходит и при переходе между дочерними элементами
  });
  target.addEventListener('drop', async (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    clearTimeout(leaveTimer);
    const paths = [...e.dataTransfer.files].map((f) => window.stella.pathForFile(f)).filter(Boolean);
    stopHungry();
    if (!paths.length) return;
    await eatPaths(ctx, paths, { x: e.clientX, y: e.clientY }, anchor);
  });
}

/** Проглотить файлы: проверка, анимация иконки в рот, перемещение в желудок. */
export async function eatPaths(ctx, paths, from, anchor) {
  const L = eaterLines(ctx.settings.persona);
  const checks = await window.stella.invoke('food:check', paths);
  const ok = checks.filter((c) => !c.reason).map((c) => c.path);
  const bad = checks.filter((c) => c.reason);
  if (!ok.length) {
    ctx.avatar.setEmotion('angry', 3);
    ctx.avatar.play('shake');
    ctx.say(`${pick(L.refuse)} ${bad[0].reason}.`);
    return [];
  }
  // иконки летят в рот
  const mouth = ctx.avatar.screenPointOf('head');
  const r = anchor.getBoundingClientRect();
  const to = mouth ? { x: r.left + mouth.x, y: r.top + mouth.y + 18 } : { x: r.left + r.width / 2, y: r.top + r.height * 0.25 };
  const icons = await Promise.all(ok.slice(0, 5).map((p) => window.stella.invoke('food:icon', p).catch(() => null)));
  icons.forEach((src, i) => flyIcon(src, from, to, i * 120));
  ctx.avatar.play('eat');
  ctx.avatar.setEmotion('happy', 4);
  // жуём
  const t0 = performance.now();
  const chew = () => { const t = (performance.now() - t0) / 1000; if (t > 0.5 && t < 2.2) { ctx.avatar.setMouth({ aa: Math.abs(Math.sin(t * 14)) * 0.8 }); requestAnimationFrame(chew); } else if (t <= 0.5) requestAnimationFrame(chew); else ctx.avatar.setMouth(null); };
  chew();
  const res = await window.stella.invoke('food:eat', ok);
  const eaten = res.filter((x) => x.ok);
  const failed = res.filter((x) => !x.ok).concat(bad.map((b) => ({ name: b.path.split(/[\\/]/).pop(), error: b.reason })));
  await new Promise((r2) => setTimeout(r2, 900));
  if (eaten.length) {
    const total = eaten.reduce((s, x) => s + (x.size || 0), 0);
    let line = eaten.length > 2 ? pick(L.many) : total > 200 * 1024 ** 2 ? pick(L.big) : pick(L.eat);
    if (eaten.some((x) => x.isShortcut)) line += ' ' + L.shortcut;
    ctx.say(line);
    const names = eaten.slice(0, 3).map((x) => `«${escapeHtml(x.name)}»`).join(', ') + (eaten.length > 3 ? ` и ещё ${eaten.length - 3}` : '');
    ctx.notify?.(`Съедено: ${names} (${fmt(total)}). Через 7 дней переварится в Корзину.`, [{ label: '↩ Выплюнуть', onClick: async () => {
      for (const x of eaten) await window.stella.invoke('food:spit', x.id).catch(() => {});
      ctx.avatar.play('shrug'); ctx.say(L.spit);
    } }]);
  }
  if (failed.length) setTimeout(() => { ctx.avatar.play('shake'); ctx.say(`«${failed[0].name}» не съелось: ${failed[0].error}`); }, eaten.length ? 2500 : 0);
  return res;
}

function flyIcon(src, from, to, delay) {
  const el = document.createElement('div');
  el.className = 'food-fly';
  el.innerHTML = src ? `<img src="${src}" alt="">` : '📄';
  el.style.left = from.x + 'px';
  el.style.top = from.y + 'px';
  document.body.appendChild(el);
  el.animate([
    { transform: 'translate(-50%,-50%) scale(1) rotate(0)', opacity: 1 },
    { transform: `translate(calc(-50% + ${(to.x - from.x) * 0.5}px), calc(-50% + ${(to.y - from.y) * 0.5 - 60}px)) scale(0.9) rotate(-20deg)`, opacity: 1, offset: 0.55 },
    { transform: `translate(calc(-50% + ${to.x - from.x}px), calc(-50% + ${to.y - from.y}px)) scale(0.1) rotate(40deg)`, opacity: 0.2 },
  ], { duration: 750, delay, easing: 'cubic-bezier(.5,0,.6,1)', fill: 'forwards' }).onfinish = () => el.remove();
}

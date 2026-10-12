// Сайт-презентация: заставка, появление блоков, прогресс истории для 3D-сцены, статус бота.
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const body = document.body;
const loaderBar = $('.loader-bar i');
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
const setLoad = (k) => {
  if (loaderBar) loaderBar.style.width = `${Math.round(k * 100)}%`;
};

// --- шапка ---
const nav = $('#nav');
const onScrollNav = () => nav.classList.toggle('scrolled', window.scrollY > 24);
onScrollNav();

// --- появление блоков при прокрутке ---
const io = new IntersectionObserver((entries) => {
  for (const e of entries) {
    if (e.isIntersecting) {
      e.target.classList.add('in');
      io.unobserve(e.target);
    }
  }
}, { threshold: 0.18, rootMargin: '0px 0px -8% 0px' });
$$('.reveal').forEach((el) => io.observe(el));

// --- подсветка карточек за курсором ---
for (const card of $$('.feature')) {
  card.addEventListener('pointermove', (e) => {
    const r = card.getBoundingClientRect();
    card.style.setProperty('--mx', `${e.clientX - r.left}px`);
    card.style.setProperty('--my', `${e.clientY - r.top}px`);
  });
}

// --- бот онлайн? ---
async function liveStatus() {
  try {
    const res = await fetch('/api/public/status', { cache: 'no-store' });
    if (!res.ok) return;
    const data = await res.json();
    const live = $('#live');
    live.hidden = false;
    live.classList.toggle('off', !data.online);
    live.querySelector('span').textContent = data.online ? 'бот онлайн' : 'бот переподключается';
  } catch {
    /* сайт открыт без бота */
  }
}
liveStatus();
setInterval(liveStatus, 60000);

// --- прогресс истории: номер главы (дробный) по положению прокрутки ---
const chapters = $$('[data-chapter]');
function storyProgress() {
  const mid = window.innerHeight / 2;
  const centers = chapters.map((el) => {
    const r = el.getBoundingClientRect();
    return r.top + r.height / 2 - mid;
  });
  if (centers[0] >= 0) return 0;
  for (let i = 0; i < centers.length - 1; i += 1) {
    if (centers[i] <= 0 && centers[i + 1] > 0) return i + -centers[i] / (centers[i + 1] - centers[i]);
  }
  return chapters.length - 1;
}

let scene = null;
let ticking = false;
function onScroll() {
  onScrollNav();
  if (ticking) return;
  ticking = true;
  requestAnimationFrame(() => {
    ticking = false;
    scene?.setProgress(storyProgress());
  });
}
window.addEventListener('scroll', onScroll, { passive: true });

function webglOk() {
  try {
    const c = document.createElement('canvas');
    return Boolean(c.getContext('webgl2') || c.getContext('webgl'));
  } catch {
    return false;
  }
}

function finishLoading() {
  setLoad(1);
  setTimeout(() => body.classList.add('loaded'), 250);
}

async function boot() {
  setLoad(0.1);
  if (!webglOk()) {
    body.classList.add('no-webgl');
    finishLoading();
    return;
  }
  try {
    // шрифты нужны для надписей на 3D-моделях (экран телефона, дневник)
    await Promise.race([
      Promise.all([document.fonts.load('400 24px "Noto Sans"'), document.fonts.load('700 24px "Noto Sans"')]),
      new Promise((r) => setTimeout(r, 1500)),
    ]);
    setLoad(0.25);
    const { StoryScene } = await import('./scene.js');
    const lowPower = matchMedia('(max-width: 760px)').matches || (navigator.hardwareConcurrency || 8) <= 4 || (navigator.deviceMemory || 8) <= 4;
    scene = new StoryScene($('#scene'), { lowPower, reducedMotion });
    scene.init((k) => setLoad(0.25 + k * 0.7));
    scene.setProgress(storyProgress());
    scene.progress = scene.target;
    scene.start();
    body.classList.add('scene-ready');
    window.addEventListener('resize', () => scene.resize());
    window.addEventListener('pointermove', (e) => scene.setPointer((e.clientX / window.innerWidth) * 2 - 1, -((e.clientY / window.innerHeight) * 2 - 1)), { passive: true });
    document.addEventListener('visibilitychange', () => (document.hidden ? scene.stop() : scene.start()));
  } catch (error) {
    console.warn('3D-сцена недоступна:', error);
    body.classList.add('no-webgl');
  }
  finishLoading();
}

// если что-то пошло совсем не так — не держим заставку дольше 6 секунд
setTimeout(() => body.classList.add('loaded'), 6000);
boot();

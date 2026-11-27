// Перетаскивание аватара мышью и посадка на панели интерфейса.
import { $, $$ } from './dom.js';
import { pick } from './presence.js';

const SITTABLE = '.panel, .composer-box, .nav, .cmd-list, .subnav, .hero-title, .pills, .seg-tabs, .top-right, .page-head h1, .msg .bubble, .quick, .stat, .persona-card';
const LINES = {
  stella: ['Удобненько!', 'Посижу тут, ладно?', 'Отсюда всё видно ✨', 'Хорошее местечко!'],
  mark: ['Тут и посижу.', 'Удобно, однако.', 'Отличный обзор отсюда.'],
};
const raf2 = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));

export class Perch {
  constructor(ctx) {
    this.ctx = ctx;
    this.layer = $('#avatar-layer');
    this.canvas = $('#avatar-canvas');
    this.state = 'dock'; // dock | free | sit
    this.target = null;
    this._bind();
  }

  _bind() {
    const av = this.ctx.avatar;
    // левая кнопка — перетаскивание аватара, правая — вращение камеры
    av.controls.mouseButtons = { LEFT: null, MIDDLE: 1, RIGHT: 0 };
    let start = null;
    let dragging = false;
    let grab = { x: 0, y: 0 };
    this.canvas.addEventListener('contextmenu', (e) => e.preventDefault());
    this.canvas.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || !av.hitTest(e.clientX, e.clientY)) return;
      start = { x: e.clientX, y: e.clientY };
      const r = this.layer.getBoundingClientRect();
      grab = { x: e.clientX - r.left, y: e.clientY - r.top };
    });
    window.addEventListener('pointermove', (e) => {
      if (!start) return;
      if (!dragging && Math.hypot(e.clientX - start.x, e.clientY - start.y) < 8) return;
      if (!dragging) { dragging = true; this._beginDrag(); }
      this._place(e.clientX - grab.x, e.clientY - grab.y);
      this._highlight(this._findTarget());
    });
    window.addEventListener('pointerup', async () => {
      if (!start) return;
      start = null;
      if (!dragging) return;
      dragging = false;
      this.canvas.classList.remove('dragging');
      const t = this._findTarget();
      this._highlight(null);
      if (t) await this.sitOn(t.el, t.x);
      else await this.drop();
    });
    this.canvas.addEventListener('dblclick', () => this.dock());
    window.addEventListener('resize', () => { if (this.state !== 'dock') this.dock(); });
  }

  _beginDrag() {
    const r = this.layer.getBoundingClientRect();
    this.state = 'free';
    this.layer.classList.add('free');
    this.layer.style.height = r.height + 'px';
    this._place(r.left, r.top);
    this.canvas.classList.add('dragging');
    this.ctx.avatar.setPosture('stand');
    this.ctx.avatar.setEmotion('surprised', 2);
    if (!this.ctx.avatar.currentAction) this.ctx.avatar.play('surprised');
  }

  _place(x, y) {
    this.layer.style.left = Math.round(x) + 'px';
    this.layer.style.top = Math.round(y) + 'px';
  }

  /** Точка бёдер аватара в координатах окна. */
  _hip() {
    const p = this.ctx.avatar.screenPointOf('hips');
    const r = this.layer.getBoundingClientRect();
    return p ? { x: r.left + p.x, y: r.top + p.y } : null;
  }

  _findTarget() {
    const hip = this._hip();
    if (!hip) return null;
    let best = null;
    for (const el of $$(SITTABLE)) {
      if (!el.offsetParent || el.closest('.page:not(.active)') || el.closest('#avatar-layer')) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 60 || hip.x < r.left + 10 || hip.x > r.right - 10) continue;
      const d = Math.abs(hip.y - r.top);
      if (d < 70 && (!best || d < best.d)) best = { el, d, x: hip.x };
    }
    return best;
  }

  _highlight(t) {
    if (this._hl && this._hl !== t?.el) this._hl.classList.remove('perch-target');
    this._hl = t?.el || null;
    if (this._hl) this._hl.classList.add('perch-target');
  }

  /** Посадить аватара на верхний край элемента. */
  async sitOn(el, hipX) {
    const av = this.ctx.avatar;
    if (this.state === 'dock') {
      const r0 = this.layer.getBoundingClientRect();
      this.layer.classList.add('free');
      this.layer.style.height = r0.height + 'px';
      this._place(r0.left, r0.top);
    }
    av.stop();
    av.setPosture('sit');
    await raf2();
    const r = el.getBoundingClientRect();
    const hip = this._hip();
    const lr = this.layer.getBoundingClientRect();
    const x = Math.max(r.left + 10, Math.min(r.right - 10, hipX ?? hip.x));
    this._place(lr.left + (x - hip.x), lr.top + (r.top + 6 - hip.y));
    this.state = 'sit';
    this.target = el;
    av.setEmotion('happy', 4);
    const lines = LINES[this.ctx.settings.persona] || LINES.stella;
    if (!this.ctx.speaker.busy && !this.ctx.chat?.busy) this.ctx.say(pick(lines));
  }

  /** Отпустили не над панелью — аватар «приземляется» на пол (нижнюю строку окна). */
  async drop() {
    this.ctx.avatar.setPosture('stand');
    await raf2();
    const foot = this.ctx.avatar.screenPointOf('leftFoot');
    const lr = this.layer.getBoundingClientRect();
    const floor = $('.statusbar').getBoundingClientRect().top + 4;
    if (foot) this._place(lr.left, lr.top + (floor - (lr.top + foot.y)));
    this.state = 'free';
  }

  /** Вернуть аватара на своё место сбоку окна. */
  dock() {
    this.layer.classList.remove('free');
    this.layer.style.left = '';
    this.layer.style.top = '';
    this.layer.style.height = '';
    this.state = 'dock';
    this.target = null;
    this.ctx.avatar.setPosture('stand');
  }

  /** Если панель, на которой сидим, скрылась (смена вкладки) — возвращаемся на место. */
  check() {
    if (this.state === 'sit' && (!this.target?.isConnected || !this.target.offsetParent || this.target.closest('.page:not(.active)'))) this.dock();
  }
}

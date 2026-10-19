/* Стелла — фильм-заставка (владелец: film.js / film.css). ~53 с кинетической типографики, финал — статичный #hero.
   Движок по времени: каждый кадр — чистая функция времени t (в сценах нет CSS-переходов и случайностей),
   поэтому seek(t) мгновенный и повторяемый, в том числе назад.
   Контракт для проверок: window.__film = {duration, time, playing, scenes:[{name,start,end}], seek(t), play(), pause()};
   адрес #t=12.5 — открыть фильм на паузе на 12.5 с (из адреса берётся только число).
   DOM строится через Stella.h / Stella.svg (Trusted Types: никакого innerHTML). */
(function () {
  "use strict";

  const S = window.Stella;
  const film = document.getElementById("film");
  const stage = document.getElementById("film-stage");
  const hero = document.getElementById("hero");
  const ui = document.getElementById("film-ui");
  if (!S || !film || !stage || !hero || !ui) return;
  const { h, svg } = S;
  const noop = () => {};

  // Без движения — без фильма: сразу статичный первый экран.
  if (S.reducedMotion()) {
    film.classList.add("film--static");
    window.__film = Object.freeze({ duration: 0, time: 0, playing: false, reduced: true, scenes: [], seek: noop, play: noop, pause: noop });
    return;
  }
  film.classList.add("film--js");
  stage.setAttribute("data-allow-overflow", "");

  /* ───────────── математика ───────────── */
  const clamp = (v, a = 0, b = 1) => (v < a ? a : v > b ? b : v);
  const lerp = (a, b, k) => a + (b - a) * k;
  const seg = (t, a, b) => clamp((t - a) / (b - a));
  const f = (v, d = 3) => {
    const m = 10 ** d;
    return Math.round(v * m) / m;
  };
  const E = {
    out2: (k) => 1 - (1 - k) * (1 - k),
    out3: (k) => 1 - (1 - k) ** 3,
    out4: (k) => 1 - (1 - k) ** 4,
    out5: (k) => 1 - (1 - k) ** 5,
    in2: (k) => k * k,
    in3: (k) => k * k * k,
    in4: (k) => k ** 4,
    io2: (k) => (k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2),
    io3: (k) => (k < 0.5 ? 4 * k * k * k : 1 - (-2 * k + 2) ** 3 / 2),
    back: (k) => {
      const c1 = 1.70158;
      const c3 = c1 + 1;
      return 1 + c3 * (k - 1) ** 3 + c1 * (k - 1) ** 2;
    },
  };

  // детерминированный ГПСЧ (mulberry32)
  function rng(seed) {
    let a = seed >>> 0;
    return () => {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // затухающая тряска после удара: [dx, dy]
  function shake(lt, t0, len, amp) {
    const d = lt - t0;
    if (d < 0 || d > len) return [0, 0];
    const a = amp * (1 - d / len) ** 2;
    return [
      a * (Math.sin(d * 93.1) * 0.7 + Math.sin(d * 211.7 + 1.3) * 0.3),
      a * (Math.sin(d * 77.3 + 2.1) * 0.7 + Math.sin(d * 179.9) * 0.3),
    ];
  }

  /* ───────────── DOM-помощники ───────────── */
  // запись стилей только при изменении значения
  function css(el, o) {
    const c = el.__c || (el.__c = {});
    for (const k in o) {
      const v = o[k];
      if (c[k] === v) continue;
      c[k] = v;
      if (k.charCodeAt(0) === 45) el.style.setProperty(k, v);
      else el.style[k] = v;
    }
  }
  function unstyle(el, props) {
    for (const p of props) el.style.removeProperty(p);
    el.__c = undefined;
  }

  // "ЭТО *НЕ* БОТ." → текст и <span class="r">НЕ</span>
  function rich(str) {
    return str
      .split(/(\*[^*]+\*)/)
      .filter(Boolean)
      .map((part) => (part[0] === "*" ? h("span", { class: "r", text: part.slice(1, -1) }) : part));
  }
  const L = (str, cls) => h("span", { class: "ln" + (cls ? " " + cls : "") }, rich(str));
  const TB = (lines, cls) => h("div", { class: "tb" + (cls ? " " + cls : "") }, lines.map((l) => (typeof l === "string" ? L(l) : l)));
  // строка из отдельных букв
  function LL(str, cls, chCls) {
    const chars = [];
    const el = h("span", { class: "ln" + (cls ? " " + cls : "") });
    let red = false;
    for (const ch of str) {
      if (ch === "*") {
        red = !red;
        continue;
      }
      const sp = h("span", { class: (chCls || "ch") + (red ? " r" : ""), text: ch === " " ? " " : ch });
      chars.push(sp);
      el.append(sp);
    }
    return { el, chars };
  }
  // печать: показать первые n букв
  function typer(chars) {
    let last = -1;
    return (n) => {
      n = clamp(Math.floor(n), 0, chars.length);
      if (n === last) return;
      const a = Math.min(n, last < 0 ? 0 : last);
      const b = last < 0 ? chars.length : Math.max(n, last);
      for (let i = a; i < b; i++) chars[i].classList.toggle("on", i < n);
      last = n;
    };
  }

  // подгонка: весь блок по ширине/высоте (одна величина шрифта)
  function fitBlock(el, maxW, maxH, maxFs) {
    el.style.fontSize = "100px";
    const w = el.offsetWidth || 1;
    const hh = el.offsetHeight || 1;
    let fs = (100 * maxW) / w;
    if (maxH) fs = Math.min(fs, (100 * maxH) / hh);
    if (maxFs) fs = Math.min(fs, maxFs);
    el.style.fontSize = f(fs, 2) + "px";
    return fs;
  }
  // подгонка «в разгон»: каждая строка по ширине, общий потолок по высоте
  function fitJustify(el, maxW, maxH, ratio = 3) {
    const lines = [...el.children].filter((x) => x.classList.contains("ln"));
    el.style.fontSize = "100px";
    lines.forEach((l) => (l.style.fontSize = "100px"));
    let sizes = lines.map((l) => (100 * maxW) / Math.max(1, l.offsetWidth));
    const mn = Math.min(...sizes);
    sizes = sizes.map((s) => Math.min(s, mn * ratio));
    lines.forEach((l, i) => (l.style.fontSize = f(sizes[i], 2) + "px"));
    const hh = el.offsetHeight;
    if (maxH && hh > maxH) {
      const k = maxH / hh;
      sizes = sizes.map((s) => s * k);
      lines.forEach((l, i) => (l.style.fontSize = f(sizes[i], 2) + "px"));
    }
    const base = Math.min(...sizes);
    el.style.fontSize = f(base, 2) + "px";
    el.__sizes = sizes;
    return base;
  }
  // геометрия элемента относительно сцены
  function rel(el) {
    const r = el.getBoundingClientRect();
    const s = stage.getBoundingClientRect();
    return { x: r.left - s.left, y: r.top - s.top, w: r.width, h: r.height, cx: r.left - s.left + r.width / 2, cy: r.top - s.top + r.height / 2 };
  }

  /* ───────────── иконки (SVG кодом) ───────────── */
  const STAR_D = "M12 0C12.9 7.6 16.4 11.1 24 12 16.4 12.9 12.9 16.4 12 24 11.1 16.4 7.6 12.9 0 12 7.6 11.1 11.1 7.6 12 0Z";
  const ICONS = {
    star: STAR_D,
    play: "M5 2.6 21.6 12 5 21.4Z",
    plane: "M21.5 3.5 2.8 10.7c-1 .4-1 1.8.1 2.1l4.6 1.4 1.8 5.6c.3.9 1.4 1.1 2 .4l2.6-2.7 4.6 3.4c.8.6 1.9.1 2.1-.8L23 4.9c.2-1-.6-1.8-1.5-1.4Z",
    chat: "M12 2.5a9.5 9.5 0 0 0-8.2 14.3L2.5 21.5l4.8-1.3A9.5 9.5 0 1 0 12 2.5Z",
  };
  const icon = (k, cls) =>
    svg("svg", { viewBox: "0 0 24 24", class: cls || "ico", "aria-hidden": "true", focusable: "false" }, svg("path", { d: ICONS[k], fill: "currentColor" }));

  /* ───────────── сцена: слои ───────────── */
  const defs = svg("defs");
  const defsSvg = svg("svg", { class: "film-defs", width: "0", height: "0", "aria-hidden": "true", focusable: "false" }, defs);
  const canvas = h("canvas", { class: "film-canvas" });
  const flash = h("div", { class: "film-flash" });
  const vig = h("div", { class: "film-vig" });
  stage.replaceChildren(defsSvg, canvas, vig, flash);
  const g = canvas.getContext("2d");

  let UID = 0;
  const uid = (p) => p + "-" + ++UID;

  // горизонтальное (или вертикальное) размытие движения — SVG-фильтр feGaussianBlur с разными радиусами по осям
  function mblur(el) {
    const id = uid("fmb");
    const fe = svg("feGaussianBlur", { in: "SourceGraphic", stdDeviation: "0 0" });
    defs.append(svg("filter", { id, x: "-60%", y: "-40%", width: "220%", height: "180%", "color-interpolation-filters": "sRGB" }, fe));
    let last = "";
    return (px, py = 0) => {
      px = Math.round(px * 2) / 2;
      py = Math.round(py * 2) / 2;
      const key = px < 0.5 && py < 0.5 ? "0" : px + " " + py;
      if (key === last) return;
      last = key;
      if (key === "0") {
        el.style.filter = "";
        return;
      }
      fe.setAttribute("stdDeviation", key);
      el.style.filter = "url(#" + id + ")";
    };
  }

  /* ───────────── частицы на канвасе (всё — функция времени) ───────────── */
  function sprite(stops) {
    const c = document.createElement("canvas");
    c.width = c.height = 128;
    const x = c.getContext("2d");
    const gr = x.createRadialGradient(64, 64, 0, 64, 64, 64);
    for (const [o, col] of stops) gr.addColorStop(o, col);
    x.fillStyle = gr;
    x.fillRect(0, 0, 128, 128);
    return c;
  }
  const SPR = {
    red: sprite([[0, "rgba(255,96,84,0.95)"], [0.4, "rgba(255,61,58,0.5)"], [1, "rgba(255,61,58,0)"]]),
    hot: sprite([[0, "rgba(255,255,255,1)"], [0.16, "rgba(255,226,214,0.9)"], [0.42, "rgba(255,70,60,0.35)"], [1, "rgba(255,61,58,0)"]]),
    bokeh: sprite([[0, "rgba(255,80,68,0.85)"], [0.62, "rgba(255,61,58,0.62)"], [0.8, "rgba(255,61,58,0.25)"], [1, "rgba(255,61,58,0)"]]),
    soft: sprite([[0, "rgba(255,240,236,0.55)"], [0.6, "rgba(255,200,190,0.25)"], [1, "rgba(255,200,190,0)"]]),
  };

  const emberCache = new Map();
  function emberSet(seed, n) {
    const key = seed + ":" + n;
    let a = emberCache.get(key);
    if (!a) {
      const r = rng(seed);
      a = [];
      for (let i = 0; i < n; i++) a.push({ x: r(), y: r(), z: r(), ph: r() * 6.283, fq: 0.4 + r() * 1.2, vy: 0.01 + r() * 0.05, kind: r() });
      emberCache.set(key, a);
    }
    return a;
  }
  // боке и искорки: мягкие красные пятна, медленно плывут вверх
  function embers(gc, e, t, seed, n, alpha = 1) {
    if (alpha <= 0.01) return;
    const arr = emberSet(seed, n);
    const m = Math.min(e.W, e.H);
    gc.globalCompositeOperation = "lighter";
    for (const p of arr) {
      const big = p.z * p.z;
      const r = m * (0.006 + big * 0.05);
      const x = (p.x + Math.sin(t * p.fq * 0.5 + p.ph) * 0.02) * e.W;
      const y = ((((p.y - t * p.vy) % 1) + 1) % 1) * e.H;
      gc.globalAlpha = alpha * (0.22 + 0.5 * (1 - p.z)) * (0.65 + 0.35 * Math.sin(t * p.fq * 2 + p.ph));
      gc.drawImage(p.kind > 0.85 ? SPR.soft : big > 0.3 ? SPR.bokeh : SPR.red, x - r, y - r, 2 * r, 2 * r);
    }
    gc.globalAlpha = 1;
    gc.globalCompositeOperation = "source-over";
  }

  // лазер: светящаяся точка летит от (x0,y0) к (x1,y1), k — прогресс, за ней — след
  function laser(gc, x0, y0, x1, y1, k, o = {}) {
    const hx = lerp(x0, x1, k);
    const hy = lerp(y0, y1, k);
    const tk = Math.max(0, k - (o.tail === undefined ? 0.5 : o.tail));
    const tx = lerp(x0, x1, tk);
    const ty = lerp(y0, y1, tk);
    const a = o.alpha === undefined ? 1 : o.alpha;
    const w = o.w || 3;
    if (a <= 0.01) return [hx, hy];
    gc.globalCompositeOperation = "lighter";
    gc.lineCap = "round";
    if (Math.abs(hx - tx) + Math.abs(hy - ty) > 1) {
      const gr = gc.createLinearGradient(tx, ty, hx, hy);
      gr.addColorStop(0, "rgba(255,61,58,0)");
      gr.addColorStop(1, "rgba(255,61,58,1)");
      gc.strokeStyle = gr;
      gc.globalAlpha = 0.22 * a;
      gc.lineWidth = w * 5;
      gc.beginPath();
      gc.moveTo(tx, ty);
      gc.lineTo(hx, hy);
      gc.stroke();
      gc.globalAlpha = a;
      gc.lineWidth = w;
      gc.stroke();
      const gw = gc.createLinearGradient(tx, ty, hx, hy);
      gw.addColorStop(0, "rgba(255,230,220,0)");
      gw.addColorStop(1, "rgba(255,240,232,0.95)");
      gc.strokeStyle = gw;
      gc.lineWidth = Math.max(1, w * 0.35);
      gc.stroke();
    }
    const r = o.head || 30;
    gc.globalAlpha = a;
    gc.drawImage(SPR.red, hx - r * 2.4, hy - r * 2.4, r * 4.8, r * 4.8);
    gc.drawImage(SPR.hot, hx - r, hy - r, 2 * r, 2 * r);
    gc.globalAlpha = 1;
    gc.globalCompositeOperation = "source-over";
    return [hx, hy];
  }

  // искры: вспышка из точки в момент t0
  function sparks(gc, t, t0, x, y, seed, n, o = {}) {
    const d = t - t0;
    if (d < 0 || d > 1.4) return;
    const r = rng(seed);
    const sc = o.scale || 1;
    const sp = (o.speed || 520) * sc;
    const G = (o.g === undefined ? 900 : o.g) * sc;
    const dir = o.dir === undefined ? -Math.PI / 2 : o.dir;
    const spread = o.spread === undefined ? Math.PI * 2 : o.spread;
    gc.globalCompositeOperation = "lighter";
    gc.lineCap = "round";
    for (let i = 0; i < n; i++) {
      const a = dir + (r() - 0.5) * spread;
      const v = sp * (0.25 + r() * 0.75);
      const life = 0.25 + r() * 0.65;
      const w = 0.8 + r() * 1.8;
      if (d > life) continue;
      const q = d / life;
      const t1 = d;
      const t2 = Math.max(0, d - 0.04);
      const hx = x + Math.cos(a) * v * t1;
      const hy = y + Math.sin(a) * v * t1 + 0.5 * G * t1 * t1;
      const bx = x + Math.cos(a) * v * t2;
      const by = y + Math.sin(a) * v * t2 + 0.5 * G * t2 * t2;
      gc.globalAlpha = (1 - q) ** 1.4;
      gc.strokeStyle = q < 0.35 ? "#fff1e6" : "#ff5a48";
      gc.lineWidth = w;
      gc.beginPath();
      gc.moveTo(bx, by);
      gc.lineTo(hx, hy);
      gc.stroke();
    }
    gc.globalAlpha = 1;
    gc.globalCompositeOperation = "source-over";
  }

  /* ───────────── реестр сцен ───────────── */
  const SCENES = [];
  function scene(name, dur, opts, build) {
    SCENES.push(Object.assign({ name, dur, build }, opts));
  }
  const env = { W: 390, H: 844, P: true, g: 16, dpr: 1, key: "" };
  const tw = (e) => (e.P ? e.W - 2 * e.g : Math.min(e.W - 2 * e.g, e.W * 0.84));

  /* 1. Темнота, пульсирует красная точка — и раскрывается в красный кадр */
  scene("dot", 1.2, { bg: "ink" }, (c) => {
    const ring = h("i", { class: "sdot-ring" });
    const ring2 = h("i", { class: "sdot-ring" });
    const dot = h("i", { class: "sdot" });
    c.append(ring, ring2, dot);
    return {
      update(lt) {
        const pulse = 1 + 0.22 * Math.sin(lt * 11);
        const grow = E.in4(seg(lt, 0.8, 1.2));
        css(dot, { transform: `scale(${f(pulse * (1 + grow * 190))})`, opacity: f(seg(lt, 0, 0.2)) });
        [ring, ring2].forEach((r, i) => {
          const rk = (((lt + i * 0.3) % 0.6) + 0.6) % 0.6 / 0.6;
          css(r, { transform: `scale(${f(1 + rk * 6)})`, opacity: f((1 - rk) * 0.75 * (1 - grow) * seg(lt, 0.1, 0.3)) });
        });
      },
      draw(gc, lt, p, e) {
        embers(gc, e, lt + 3, 7, 10, 0.5 * seg(lt, 0, 0.6) * (1 - seg(lt, 0.8, 1.0)));
      },
    };
  });

  /* 2. Красный кадр: «ДА ЛАДНО» влетает с размытием движения, тряска */
  scene("da-ladno", 1.4, { bg: "red", out: "smear" }, (c, e0) => {
    const els = (e0.P ? ["ДА", "ЛАДНО"] : ["ДА ЛАДНО"]).map((t) => L(t));
    const tb = TB(els, "tc k");
    const wrap = h("div", { class: "mbw" }, tb);
    const mb = mblur(wrap);
    const r = rng(5);
    const lines = [0, 1, 2, 3].map(() => {
      const el = h("i", { class: "speed" });
      el.style.top = f(12 + r() * 76, 1) + "%";
      el.style.height = f(1 + r() * 3, 1) + "px";
      return el;
    });
    c.append(...lines, wrap);
    let fs = 100;
    return {
      layout(e) {
        fs = fitBlock(tb, tw(e), e.H * (e.P ? 0.62 : 0.66));
      },
      update(lt, p, e) {
        let blur = 0;
        els.forEach((el, i) => {
          const q = seg(lt, i * 0.07, 0.3 + i * 0.07);
          const k = E.out5(q);
          const d = i % 2 ? -1 : 1;
          css(el, { transform: `translateX(${f((1 - k) * d * e.W * 1.1, 1)}px) scaleX(${f(1 + (1 - k) * 0.9)})` });
          if (q > 0) blur = Math.max(blur, 70 * (1 - q) ** 3);
        });
        mb(blur);
        const [sx, sy] = shake(lt, 0.3, 0.55, fs * 0.07);
        css(tb, { transform: `translate(${f(sx, 1)}px,${f(sy, 1)}px) scale(${f(1 + 0.07 * E.out3(seg(lt, 0.3, 1.4)))})` });
        lines.forEach((el, i) => {
          const q = seg(lt, 0.02 + i * 0.05, 0.3 + i * 0.05);
          css(el, { transform: `translateX(${f(lerp(e.W * 1.1, -e.W * 1.4, q), 1)}px)`, opacity: q > 0 && q < 1 ? "1" : "0" });
        });
      },
    };
  });

  /* 3. Бумага: «НЕ МОЖЕТ / БЫТЬ.», поперёк — красный мазок */
  scene("ne-mozhet", 1.6, { bg: "paper", out: "zoom" }, (c, e0) => {
    const els = (e0.P ? ["НЕ", "МОЖЕТ", "БЫТЬ*.*"] : ["НЕ МОЖЕТ", "БЫТЬ*.*"]).map((t) => L(t));
    const tb = TB(els, "tw k");
    const sm = h("div", { class: "smear" }, h("i"), h("i"), h("i"), h("i"));
    tb.append(sm);
    c.append(tb);
    let fs = 100;
    return {
      layout(e) {
        fs = e.P ? fitJustify(tb, tw(e), e.H * 0.58, 2.2) : fitBlock(tb, tw(e) * 0.92, e.H * 0.62);
      },
      update(lt, p) {
        els.forEach((el, i) => {
          const q = seg(lt, 0.02 + i * 0.1, 0.34 + i * 0.1);
          const k = E.out5(q);
          css(el, {
            transform: `translateY(${f((1 - k) * -0.7)}em) scale(${f(1 + (1 - k) * 0.4)})`,
            opacity: f(clamp(q * 4)),
            filter: q < 1 ? `blur(${f((1 - k) * 0.14, 3)}em)` : "none",
          });
        });
        const sk = E.out3(seg(lt, 0.44, 0.72));
        css(sm, { transform: `translateY(-50%) rotate(-9deg) scaleX(${f(sk)})`, opacity: f(clamp(sk * 4)) });
        const [sx, sy] = shake(lt, 0.66, 0.4, fs * 0.05);
        css(tb, { transform: `translate(${f(sx, 1)}px,${f(sy, 1)}px) scale(${f(1 + 0.05 * p)})` });
      },
    };
  });

  /* 4. Чёрный, частицы, свечение: «ОКЕЙ.» + красная точка; сбоку выскакивает «ХА» */
  scene("okay", 1.7, { bg: "glow", flash: "white" }, (c) => {
    const dot = h("span", { class: "okdot" });
    const word = h("span", { class: "ln" }, "ОКЕЙ", dot);
    const ha = h("span", { class: "ha", text: "ХА" });
    const tb = TB([word], "tw w");
    tb.append(ha);
    c.append(tb);
    let fs = 100;
    return {
      layout(e) {
        fs = fitBlock(tb, tw(e) * 0.9, e.H * 0.42);
      },
      update(lt, p) {
        const q = seg(lt, 0, 0.38);
        const k = E.out5(q);
        const [sx, sy] = shake(lt, 0.36, 0.3, fs * 0.03);
        css(tb, {
          transform: `translate(${f(sx, 1)}px,${f(sy, 1)}px) scale(${f((2.1 - 1.1 * k) * (1 + 0.05 * p))})`,
          opacity: f(clamp(q * 4)),
          filter: q < 1 ? `blur(${f((1 - k) * 26, 1)}px)` : "none",
        });
        const dk = E.back(seg(lt, 0.3, 0.55));
        css(dot, { transform: `scale(${f(Math.max(0, dk) * (1 + 0.08 * Math.sin(lt * 9)))})` });
        const hk = E.back(seg(lt, 0.85, 1.08));
        const [hx, hy] = shake(lt, 1.08, 0.3, fs * 0.04);
        css(ha, { transform: `translate(${f(hx, 1)}px,${f(hy, 1)}px) rotate(-12deg) scale(${f(Math.max(0, hk))})`, opacity: hk > 0 ? "1" : "0" });
      },
      draw(gc, lt, p, e) {
        embers(gc, e, lt, 4, 22, 0.95);
      },
    };
  });

  /* 5. «ТЫ ПРАВДА / ДУМАЕШЬ,» — огромное белое из размытия и масштаба */
  scene("pravda", 1.5, { bg: "ink", out: "smear" }, (c, e0) => {
    const els = (e0.P ? ["ТЫ", "ПРАВДА", "ДУМАЕШЬ,"] : ["ТЫ ПРАВДА", "ДУМАЕШЬ,"]).map((t) => L(t));
    const tb = TB(els, "tw w");
    c.append(tb);
    return {
      layout(e) {
        if (e.P) fitJustify(tb, tw(e), e.H * 0.6, 1.9);
        else fitBlock(tb, tw(e) * 0.95, e.H * 0.64);
      },
      update(lt, p) {
        els.forEach((el, i) => {
          const q = seg(lt, i * 0.11, 0.36 + i * 0.11);
          const k = E.out4(q);
          css(el, {
            transform: `scale(${f(1.8 - 0.8 * k)})`,
            opacity: f(clamp(q * 3)),
            filter: q < 1 ? `blur(${f((1 - k) * 0.2, 3)}em)` : "none",
          });
        });
        css(tb, { transform: `scale(${f(1 + 0.07 * E.io2(p))})` });
      },
    };
  });

  /* 6. «ЧТО ЭТО / ПРОСТО БОТ?» — шлейф-экструзия из копий */
  scene("chto-eto", 1.5, { bg: "ink", out: "smear" }, (c, e0) => {
    const txt = e0.P ? ["ЧТО ЭТО", "ПРОСТО", "БОТ?"] : ["ЧТО ЭТО", "ПРОСТО БОТ?"];
    const N = 12;
    const mk = (cls) => TB(txt.map((t) => L(t)), "tw " + cls);
    const main = mk("w");
    const ghosts = [];
    for (let i = 1; i <= N; i++) {
      const gh = mk("ghost");
      const v = Math.round(lerp(150, 26, ((i - 1) / (N - 1)) ** 0.8));
      gh.style.color = `rgb(${v},${v},${Math.round(v * 1.04)})`;
      ghosts.push(gh);
    }
    const stack = h("div", { class: "stack" }, ghosts.slice().reverse(), main);
    const mb = mblur(stack);
    c.append(stack);
    return {
      layout(e) {
        if (e.P) fitJustify(main, tw(e) * 0.86, e.H * 0.48, 1.6);
        else fitBlock(main, tw(e) * 0.86, e.H * 0.52);
        const lines = [...main.children];
        for (const gh of ghosts) {
          gh.style.fontSize = main.style.fontSize;
          [...gh.children].forEach((l, i) => (l.style.fontSize = lines[i].style.fontSize));
        }
      },
      update(lt, p, e) {
        const q = seg(lt, 0, 0.34);
        const k = E.out5(q);
        mb(q > 0 && q < 1 ? 64 * (1 - q) ** 3 : 0);
        const d = lerp(0.15, 0.04, E.out3(seg(lt, 0.15, 1.15))) * (1 - E.in3(seg(lt, 1.18, 1.5)));
        const a = lerp(-2.4, -0.7, E.io2(p));
        const dx = Math.cos(a) * d;
        const dy = Math.sin(a) * d;
        ghosts.forEach((gh, i) => {
          css(gh, { transform: `translate(${f(dx * (i + 1), 4)}em,${f(dy * (i + 1), 4)}em)`, opacity: f(1 - i * 0.04) });
        });
        css(stack, { transform: `translateX(${f((1 - k) * e.W * 0.7, 1)}px) scale(${f(1 + 0.08 * E.in2(seg(lt, 1.1, 1.5)))})` });
      },
    };
  });

  /* 6b. Бумажный кадр: огромный красный «?» */
  scene("vopros", 1.0, { bg: "paper", flash: "white" }, (c) => {
    const q1 = h("div", { class: "qq tw r", text: "?" });
    const q2 = h("div", { class: "qq tw k", text: "?" });
    const mb = mblur(q1);
    c.append(q2, q1);
    let fs1 = 100;
    return {
      layout(e) {
        fs1 = e.P ? Math.min(e.W * 1.15, e.H * 0.6) : e.H * 0.92;
        q1.style.fontSize = f(fs1, 1) + "px";
        q2.style.fontSize = f(fs1 * 0.42, 1) + "px";
        q1.style.left = e.P ? "60%" : "62%";
        q1.style.top = e.P ? "46%" : "50%";
        q2.style.left = e.P ? "24%" : "34%";
        q2.style.top = e.P ? "66%" : "62%";
      },
      update(lt) {
        const q = seg(lt, 0, 0.26);
        const k = E.out5(q);
        mb(q > 0 && q < 1 ? 50 * (1 - q) ** 3 : 0);
        const [sx, sy] = shake(lt, 0.26, 0.35, fs1 * 0.03);
        css(q1, {
          transform: `translate(-50%,-50%) translate(${f(sx + (1 - k) * fs1 * 1.2, 1)}px,${f(sy, 1)}px) rotate(${f(lerp(38, 9, k) + lt * 5, 2)}deg) scale(${f(1.9 - 0.9 * k)})`,
        });
        const k2 = E.back(seg(lt, 0.24, 0.48));
        css(q2, { transform: `translate(-50%,-50%) rotate(-14deg) scale(${f(Math.max(0, k2))})` });
      },
    };
  });

  /* 7. «ЭТО НЕ БОТ.» + лазер + мини-схема Telegram — Стелла — WhatsApp */
  scene("ne-bot", 2.4, { bg: "ink dots", out: "smear" }, (c, e0) => {
    const P = e0.P;
    const tLines = (P ? ["ЭТО *НЕ*", "БОТ."] : ["ЭТО *НЕ* БОТ."]).map((t) => L(t));
    const title = TB(tLines, "tw w nb-title");
    const tmb = tLines.map((l) => mblur(l));
    const pos = P ? { tg: [0.3, 0.12], st: [0.66, 0.5], wa: [0.32, 0.88] } : { tg: [0.14, 0.72], st: [0.5, 0.26], wa: [0.86, 0.72] };
    const mkCard = (cls, tag, name, ico) =>
      h("div", { class: "nb-card" + (cls ? " " + cls : "") }, h("span", { class: "nb-ico" }, ico), h("span", { class: "nb-txt" }, h("span", { class: "nb-tag", text: tag }), h("span", { class: "nb-name", text: name })));
    const cards = [mkCard("", "личка и группы", "Telegram", icon("plane")), mkCard("nb-main", "ИИ-собеседница", "Стелла", icon("star")), mkCard("", "чаты", "WhatsApp", icon("chat"))];
    const keys = ["tg", "st", "wa"];
    const links = [svg("path", { class: "nb-link" }), svg("path", { class: "nb-link" })];
    const pulses = [svg("circle", { r: "4.5", class: "nb-pulse" }), svg("circle", { r: "4.5", class: "nb-pulse" })];
    const sv = svg("svg", { class: "nb-svg", "aria-hidden": "true" }, links, pulses);
    const box = h("div", { class: "nb-box" }, sv, cards);
    const col = h("div", { class: "col nb" }, title, box);
    c.append(col);
    let lens = [1, 1];
    let laserY = 0;
    return {
      layout(e) {
        fitBlock(title, e.P ? e.W - 2 * e.g : Math.min(e.W * 0.78, 1100), e.H * (e.P ? 0.2 : 0.17));
        const bw = e.P ? e.W - 2 * e.g : Math.min(e.W * 0.84, 1100);
        const bh = e.P ? e.H * 0.5 : Math.min(e.H * 0.5, bw * 0.42);
        css(box, { width: f(bw, 1) + "px", height: f(bh, 1) + "px", fontSize: f(e.P ? clamp(e.W * 0.036, 12, 22) : clamp(bw * 0.02, 12, 22), 1) + "px" });
        col.style.gap = f(e.P ? e.H * 0.05 : e.H * 0.07, 1) + "px";
        sv.setAttribute("viewBox", `0 0 ${f(bw, 1)} ${f(bh, 1)}`);
        const pt = (k) => [pos[k][0] * bw, pos[k][1] * bh];
        cards.forEach((cd, i) => {
          const [x, y] = pt(keys[i]);
          cd.style.left = f(x, 1) + "px";
          cd.style.top = f(y, 1) + "px";
        });
        const d = ([x1, y1], [x2, y2]) =>
          e.P
            ? `M${f(x1, 1)} ${f(y1, 1)}C${f(x1, 1)} ${f((y1 + y2) / 2, 1)} ${f(x2, 1)} ${f((y1 + y2) / 2, 1)} ${f(x2, 1)} ${f(y2, 1)}`
            : `M${f(x1, 1)} ${f(y1, 1)}C${f((x1 + x2) / 2, 1)} ${f(y1, 1)} ${f((x1 + x2) / 2, 1)} ${f(y2, 1)} ${f(x2, 1)} ${f(y2, 1)}`;
        links[0].setAttribute("d", d(pt("tg"), pt("st")));
        links[1].setAttribute("d", d(pt("st"), pt("wa")));
        lens = links.map((l) => l.getTotalLength() || 1);
        links.forEach((l, i) => (l.style.strokeDasharray = `${f(lens[i], 1)} ${f(lens[i], 1)}`));
        const tr = rel(title);
        laserY = tr.y + tr.h + (e.P ? e.H * 0.025 : e.H * 0.035);
      },
      update(lt) {
        tLines.forEach((l, i) => {
          const q = seg(lt, i * 0.08, 0.3 + i * 0.08);
          const k = E.out5(q);
          css(l, { transform: `translateX(${f((1 - k) * -env.W, 1)}px)` });
          tmb[i](q > 0 && q < 1 ? 50 * (1 - q) ** 3 : 0);
        });
        cards.forEach((cd, i) => {
          const k = E.back(seg(lt, 0.62 + i * 0.16, 0.95 + i * 0.16));
          css(cd, { transform: `translate(-50%,-50%) scale(${f(Math.max(0, k))})`, opacity: f(clamp(k * 2)) });
        });
        links.forEach((l, i) => {
          const k = E.io2(seg(lt, 0.85 + i * 0.25, 1.3 + i * 0.25));
          css(l, { strokeDashoffset: f(lens[i] * (1 - k), 1) + "px" });
        });
        pulses.forEach((pc, i) => {
          const on = lt > 1.5 + i * 0.12;
          const k = on ? ((lt - 1.5 - i * 0.12) * 1.3) % 1 : 0;
          const pt = links[i].getPointAtLength(lens[i] * k);
          pc.setAttribute("cx", f(pt.x, 1));
          pc.setAttribute("cy", f(pt.y, 1));
          css(pc, { opacity: on ? f(Math.sin(k * Math.PI)) : "0" });
        });
      },
      draw(gc, lt, p, e) {
        embers(gc, e, lt, 21, 14, 0.7);
        const x0 = -0.05 * e.W;
        const x1 = 1.05 * e.W;
        if (lt > 0.12 && lt < 1.0) {
          const k = E.io2(seg(lt, 0.12, 0.62));
          laser(gc, x0, laserY, x1, laserY, k, { tail: 0.55, alpha: 1 - seg(lt, 0.62, 1.0), w: 3, head: 26 });
        }
        [0.28, 0.4, 0.5].forEach((t0, i) => {
          const kk = E.io2(seg(t0, 0.12, 0.62));
          sparks(gc, lt, t0, lerp(x0, x1, kk), laserY, 300 + i, 16, { scale: Math.min(e.W, e.H) / 800 });
        });
      },
    };
  });

  /* 8. Красный кадр: огромное «ЭТО —» */
  scene("eto", 1.1, { bg: "red", flash: "white", out: "zoom" }, (c, e0) => {
    const tb = TB(e0.P ? ["ЭТО", "—"] : ["ЭТО —"], "tw k");
    c.append(tb);
    let fs = 100;
    return {
      layout(e) {
        fs = fitBlock(tb, tw(e) * 0.95, e.H * 0.7);
      },
      update(lt, p) {
        const q = seg(lt, 0, 0.24);
        const k = E.out4(q);
        const [sx, sy] = shake(lt, 0.24, 0.45, fs * 0.05);
        css(tb, {
          transform: `translate(${f(sx, 1)}px,${f(sy, 1)}px) scale(${f((3.2 - 2.2 * k) * (1 + 0.08 * p))})`,
          filter: q < 1 ? `blur(${f((1 - k) * 0.12, 3)}em)` : "none",
          opacity: f(clamp(q * 4)),
        });
      },
    };
  });

  /* 9. Логотип: «Стелла» широким курсивом, лазер насквозь, искры, звезда */
  scene("logo", 2.6, { bg: "glow dots", flash: "red" }, (c) => {
    const star = h("span", { class: "lg-star" }, icon("star"));
    const word = h("span", { class: "lg-word", text: "Стелла" });
    const skew = h("span", { class: "lg-skew" }, word);
    const row = h("div", { class: "lg-row" }, star, skew);
    const cap = h("p", { class: "lg-cap" }, h("span", { class: "r", text: "✦" }), " ИИ в Telegram и WhatsApp");
    const col = h("div", { class: "col lg" }, row, cap);
    c.append(col);
    let geo = { x: 0, w: 1, cy: 0, sx: 0, sy: 0 };
    let fs = 100;
    return {
      layout(e) {
        fs = fitBlock(row, e.P ? (e.W - 2 * e.g) * 0.9 : Math.min(e.W * 0.64, 980), e.H * 0.3);
        cap.style.fontSize = f(clamp(fs * 0.14, 13, 24), 1) + "px";
        const r = rel(word);
        const rs = rel(star);
        geo = { x: r.x, w: r.w, cy: r.y + r.h * 0.56, sx: rs.cx, sy: rs.cy };
      },
      update(lt, p, e) {
        const kx = E.io2(seg(lt, 0.15, 0.85));
        const hx = lerp(-0.05 * e.W, 1.05 * e.W, kx);
        const rv = clamp((hx - geo.x) / geo.w);
        css(word, { clipPath: rv >= 1 ? "none" : `inset(-40% ${f((1 - rv) * 100, 2)}% -40% -10%)` });
        const sk = E.back(seg(lt, 0.8, 1.12));
        css(star, { transform: `rotate(${f((1 - sk) * -200, 1)}deg) scale(${f(Math.max(0, sk))})` });
        const ck = E.out4(seg(lt, 1.0, 1.4));
        css(cap, { opacity: f(ck), transform: `translateY(${f((1 - ck) * 16, 1)}px)` });
        css(col, { transform: `scale(${f(1 + 0.05 * E.io2(p))})` });
      },
      draw(gc, lt, p, e) {
        embers(gc, e, lt, 9, 18, 0.9);
        const x0 = -0.05 * e.W;
        const x1 = 1.05 * e.W;
        const kx = E.io2(seg(lt, 0.15, 0.85));
        if (lt > 0.15) {
          // луч остаётся тонкой линией после пролёта
          const a = 1 - 0.55 * seg(lt, 0.85, 1.6);
          laser(gc, x0, geo.cy, x1, geo.cy, kx, { tail: 1, alpha: a, w: 2.4, head: kx < 1 ? 30 : 0.01 });
        }
        [0.34, 0.47, 0.6, 0.72].forEach((t0, i) => {
          const kk = E.io2(seg(t0, 0.15, 0.85));
          sparks(gc, lt, t0, lerp(x0, x1, kk), geo.cy, 40 + i, 18, { scale: Math.min(e.W, e.H) / 700 });
        });
        sparks(gc, lt, 0.86, geo.sx, geo.sy, 77, 22, { scale: Math.min(e.W, e.H) / 900, g: 300 });
      },
    };
  });

  /* 10. «ВСЁ, ЧТО / НУЖНО —» — по слову из размытия */
  scene("vsyo", 1.4, { bg: "ink dots", out: "smear" }, (c) => {
    const w = (t, cls) => h("span", { class: "wd" + (cls ? " " + cls : ""), text: t });
    const ws = [w("ВСЁ,"), w("ЧТО"), w("НУЖНО"), w("—", "r")];
    const l1 = h("span", { class: "ln" }, ws[0], " ", ws[1]);
    const l2 = h("span", { class: "ln" }, ws[2], " ", ws[3]);
    const tb = TB([l1, l2], "tw w");
    c.append(tb);
    return {
      layout(e) {
        fitBlock(tb, tw(e) * 0.92, e.H * 0.5);
      },
      update(lt, p) {
        ws.forEach((el, i) => {
          const q = seg(lt, 0.04 + i * 0.13, 0.36 + i * 0.13);
          const k = E.out4(q);
          css(el, { opacity: f(clamp(q * 3)), transform: `scale(${f(1.55 - 0.55 * k)})`, filter: q < 1 ? `blur(${f((1 - k) * 0.16, 3)}em)` : "none" });
        });
        css(tb, { transform: `scale(${f(1 + 0.06 * p)})` });
      },
      draw(gc, lt, p, e) {
        embers(gc, e, lt + 5, 12, 12, 0.7);
      },
    };
  });

  /* 11. Поле ввода (синее стекло): печатается запрос, слова-чипы подсвечены, ↵ «нажимается» */
  scene("prompt", 3.4, { bg: "ink dots" }, (c) => {
    const parts = [
      ["Стелла, сделай ", 0],
      ["мультик", 1],
      [", как ", 0],
      ["кот танцует", 1],
    ];
    const chars = [];
    const chips = [];
    const txt = h("div", { class: "pr-text" });
    for (const [s, isChip] of parts) {
      const holder = isChip ? h("span", { class: "chip" }) : txt;
      if (isChip) {
        chips.push({ el: holder, at: chars.length, len: [...s].length });
        txt.append(holder);
      }
      for (const ch of s) {
        const sp = h("span", { class: "pc", text: ch });
        chars.push(sp);
        holder.append(sp);
      }
    }
    const caret = h("span", { class: "pr-caret" });
    txt.prepend(caret);
    const ring = h("i", { class: "pr-ring" });
    const enter = h(
      "span",
      { class: "pr-enter" },
      ring,
      svg(
        "svg",
        { viewBox: "0 0 24 24", "aria-hidden": "true", focusable: "false" },
        svg("path", { d: "M19 5v7a3 3 0 0 1-3 3H6m0 0 4-4m-4 4 4 4", fill: "none", stroke: "currentColor", "stroke-width": "2.2", "stroke-linecap": "round", "stroke-linejoin": "round" })
      )
    );
    const head = h("div", { class: "pr-head" }, h("span", { class: "pr-av" }, icon("star")), h("span", { class: "pr-name", text: "Стелла" }), h("span", { class: "pr-on", text: "в сети" }));
    const box = h("div", { class: "pr-box" }, head, txt, enter);
    const glow = h("i", { class: "pr-glow" });
    c.append(glow, box);
    const type = typer(chars);
    const T0 = 0.42;
    const T1 = 2.2;
    const tAt = (i) => T0 + (i / chars.length) * (T1 - T0);
    let caretAt = -1;
    let ec = { x: 0, y: 0 };
    return {
      layout(e) {
        const bw = e.P ? e.W - 2 * e.g : Math.min(e.W * 0.68, 960);
        const fz = e.P ? clamp(bw * 0.064, 16, 26) : clamp(bw * 0.04, 20, 38);
        css(box, { width: f(bw, 1) + "px", fontSize: f(fz, 1) + "px" });
        const r = rel(enter);
        ec = { x: r.cx, y: r.cy };
      },
      update(lt, p, e) {
        const n = Math.floor(seg(lt, T0, T1) * chars.length + 1e-6);
        type(n);
        if (n !== caretAt) {
          if (n > 0) chars[n - 1].after(caret);
          else txt.prepend(caret);
          caretAt = n;
        }
        const typing = lt < T1 + 0.05;
        css(caret, { opacity: typing || Math.floor(lt * 3.4) % 2 === 0 ? "1" : "0.1" });
        chips.forEach((ch) => {
          const k = E.out2(seg(lt, tAt(ch.at) - 0.03, tAt(ch.at + ch.len)));
          css(ch.el, { "--k": String(f(k)) });
        });
        // вход, «камера», выход
        const qi = seg(lt, 0, 0.36);
        const ki = E.out4(qi);
        const ko = E.in3(seg(lt, 2.86, 3.4));
        const sc = (0.92 + 0.08 * ki) * (1 + 0.035 * E.io2(seg(lt, 0.3, 2.8))) * (1 + ko * 0.4);
        const bl = (1 - ki) * 10 + ko * 12;
        css(box, {
          transform: `translateY(${f((1 - ki) * 30 - ko * 40, 1)}px) scale(${f(sc)})`,
          opacity: f(clamp(qi * 3) * (1 - ko)),
          filter: bl > 0.2 ? `blur(${f(bl, 1)}px)` : "none",
        });
        // ↵: пульс, нажатие, волна
        const pulse = lt > T1 && lt < 2.6 ? 1 + 0.09 * Math.sin((lt - T1) * 18) : 1;
        const press = lt < 2.6 ? 1 : lt < 2.7 ? lerp(1, 0.82, seg(lt, 2.6, 2.7)) : lerp(0.82, 1.06, E.out3(seg(lt, 2.7, 2.9)));
        css(enter, { transform: `scale(${f(pulse * press)})` });
        enter.classList.toggle("hit", lt > 2.64);
        const rk = seg(lt, 2.66, 3.15);
        css(ring, { transform: `scale(${f(1 + rk * 2.6)})`, opacity: rk > 0 && rk < 1 ? f((1 - rk) * 0.9) : "0" });
        css(glow, { opacity: f(0.55 + 0.45 * seg(lt, 2.62, 2.8) - 0.6 * ko) });
      },
      draw(gc, lt, p, e) {
        embers(gc, e, lt + 2, 31, 12, 0.6);
        sparks(gc, lt, 2.66, ec.x, ec.y, 909, 26, { scale: Math.min(e.W, e.H) / 900, g: 400 });
      },
    };
  });

  /* 12a. «ПИШЕТ / КАК ЧЕЛОВЕК» — буквы собираются из размытия; «Стелла печатает…» */
  scene("pishet", 1.5, { bg: "red", flash: "white", out: "smear" }, (c, e0) => {
    const src = e0.P ? ["ПИШЕТ", "КАК", "ЧЕЛОВЕК"] : ["ПИШЕТ", "КАК ЧЕЛОВЕК"];
    const lls = src.map((t) => LL(t));
    const chars = lls.flatMap((x) => x.chars);
    const tb = TB(lls.map((x) => x.el), "tw k");
    const dots = [h("i"), h("i"), h("i")];
    const typing = h("div", { class: "ps-typing" }, h("span", { text: "Стелла печатает" }), dots);
    const col = h("div", { class: "col" }, tb, typing);
    c.append(col);
    const r = rng(42);
    const prm = chars.map(() => ({ x: (r() - 0.5) * 1.6, y: (r() - 0.5) * 1.2, rot: (r() - 0.5) * 90, s: 0.3 + r() * 1.9, d: r() * 0.22 }));
    return {
      layout(e) {
        if (e.P) fitJustify(tb, tw(e), e.H * 0.55, 1.9);
        else fitBlock(tb, tw(e) * 0.92, e.H * 0.58);
        typing.style.fontSize = f(e.P ? clamp(e.W * 0.04, 13, 18) : clamp(e.H * 0.026, 14, 22), 1) + "px";
        col.style.gap = f(e.H * 0.04, 1) + "px";
      },
      update(lt, p) {
        chars.forEach((ch, i) => {
          const m = prm[i];
          const t0 = 0.02 + m.d + i * 0.012;
          const q = seg(lt, t0, t0 + 0.46);
          const k = E.out4(q);
          css(ch, {
            transform: `translate(${f((1 - k) * m.x, 3)}em,${f((1 - k) * m.y, 3)}em) rotate(${f((1 - k) * m.rot, 1)}deg) scale(${f(lerp(m.s, 1, k))})`,
            opacity: f(clamp(q * 2.5)),
            filter: k < 0.985 ? `blur(${f((1 - k) * 0.13, 3)}em)` : "none",
          });
        });
        css(tb, { transform: `scale(${f(1 + 0.05 * p)})` });
        css(typing, { opacity: f(seg(lt, 0.55, 0.8)) });
        const ph = Math.floor(lt * 7) % 3;
        dots.forEach((d, i) => css(d, { opacity: i === ph ? "1" : "0.3" }));
      },
    };
  });

  /* 12b. «ПОМНИТ / ВСЕХ» — красная фигура меняет форму под словами */
  scene("pomnit", 1.4, { bg: "ink", out: "smear" }, (c) => {
    const l1 = L("ПОМНИТ");
    const l2 = L("ВСЕХ");
    const tb = TB([l1, l2], "tw w");
    const shape = h("i", { class: "pm-shape" });
    tb.prepend(shape);
    const cap = h("div", { class: "cap-mono", text: "имена · ники · кто есть кто" });
    const col = h("div", { class: "col" }, tb, cap);
    c.append(col);
    const m1 = mblur(l1);
    const m2 = mblur(l2);
    // [t, w, h, radius, rot, x, y] — размеры в em
    const K = [
      [0.0, 0.1, 0.1, 0.05, 0, 0, 0],
      [0.22, 2.3, 1.7, 0.04, -8, 0.7, -0.1],
      [0.5, 1.6, 1.6, 0.8, 0, -0.9, 0.1],
      [0.8, 3.8, 0.72, 0.36, 5, 0, 0.5],
      [1.1, 1.8, 1.8, 0.18, 45, 1.3, -0.2],
      [1.4, 1.9, 1.9, 0.5, 90, 1.2, -0.1],
    ];
    return {
      layout(e) {
        fitBlock(tb, tw(e) * (e.P ? 0.96 : 0.66), e.H * 0.5);
        cap.style.fontSize = f(e.P ? clamp(e.W * 0.038, 12, 17) : clamp(e.H * 0.026, 13, 20), 1) + "px";
        col.style.gap = f(e.H * 0.045, 1) + "px";
      },
      update(lt) {
        let i = 0;
        while (i < K.length - 2 && lt > K[i + 1][0]) i++;
        const a = K[i];
        const b = K[i + 1];
        const k = E.io3(seg(lt, a[0], b[0]));
        const v = (j) => lerp(a[j], b[j], k);
        css(shape, {
          width: f(v(1), 3) + "em",
          height: f(v(2), 3) + "em",
          borderRadius: f(v(3), 3) + "em",
          transform: `translate(-50%,-50%) translate(${f(v(5), 3)}em,${f(v(6), 3)}em) rotate(${f(v(4), 1)}deg)`,
        });
        const q1 = seg(lt, 0.02, 0.32);
        const q2 = seg(lt, 0.1, 0.4);
        css(l1, { transform: `translateX(${f((1 - E.out5(q1)) * -env.W, 1)}px)` });
        css(l2, { transform: `translateX(${f((1 - E.out5(q2)) * env.W, 1)}px)` });
        m1(q1 > 0 && q1 < 1 ? 50 * (1 - q1) ** 3 : 0);
        m2(q2 > 0 && q2 < 1 ? 50 * (1 - q2) ** 3 : 0);
        css(cap, { opacity: f(seg(lt, 0.45, 0.7)) });
      },
    };
  });

  /* 12c. Бумага: «3D» + крутится красный куб, «МУЛЬТИКИ» */
  scene("cube", 1.6, { bg: "paper", out: "smear" }, (c) => {
    const faces = ["fr", "bk", "rt", "lf", "tp", "dn"].map((k) => h("i", { class: "cb-face cb-" + k }));
    const cube = h("div", { class: "cb" }, faces);
    const cw = h("div", { class: "cb-wrap" }, cube);
    const d3 = h("span", { class: "cb-3d", text: "3D" });
    const row = h("div", { class: "cb-row" }, d3, cw);
    const mlt = LL("МУЛЬТИКИ", "cb-word");
    const tb = h("div", { class: "tb tw k cb-tb" }, row, mlt.el);
    const cap = h("div", { class: "cap-mono k", text: "кот, лиса и зайка — танцуют и машут" });
    const col = h("div", { class: "col" }, tb, cap);
    c.append(col);
    const mb = mblur(cw);
    return {
      layout(e) {
        fitBlock(tb, tw(e) * (e.P ? 0.92 : 0.6), e.H * (e.P ? 0.42 : 0.56));
        cap.style.fontSize = f(e.P ? clamp(e.W * 0.036, 12, 16) : clamp(e.H * 0.024, 13, 20), 1) + "px";
        col.style.gap = f(e.H * 0.04, 1) + "px";
      },
      update(lt, p) {
        const q = seg(lt, 0, 0.3);
        const k = E.out5(q);
        css(d3, { transform: `translateX(${f((1 - k) * -1.2, 3)}em) scale(${f(1.3 - 0.3 * k)})`, opacity: f(clamp(q * 4)) });
        const qc = seg(lt, 0.08, 0.42);
        const kc = E.out5(qc);
        css(cw, { transform: `translateX(${f((1 - kc) * 3, 3)}em)` });
        mb(qc > 0 && qc < 1 ? 46 * (1 - qc) ** 3 : 0);
        css(cube, { transform: `rotateX(${f(-24 + 10 * Math.sin(lt * 2.2), 2)}deg) rotateY(${f(30 + lt * 150, 2)}deg)` });
        mlt.chars.forEach((ch, i) => {
          const qq = seg(lt, 0.35 + i * 0.05, 0.6 + i * 0.05);
          const kk = E.out4(qq);
          css(ch, { opacity: f(clamp(qq * 3)), transform: `translateY(${f((1 - kk) * 0.6, 3)}em)`, filter: kk < 0.98 ? `blur(${f((1 - kk) * 0.08, 3)}em)` : "none" });
        });
        css(cap, { opacity: f(seg(lt, 0.8, 1.05)) });
        css(tb, { transform: `scale(${f(1 + 0.04 * p)})` });
      },
    };
  });

  /* 12d. «ГОЛОСОВЫЕ» — слова плывут по кривой, осциллограмма */
  scene("golos", 1.6, { bg: "glow dots", out: "smear" }, (c) => {
    const id1 = uid("glp");
    const id2 = uid("glq");
    const XL = "http://www.w3.org/1999/xlink";
    const d1 = svg("path", { id: id1, fill: "none" });
    const d2 = svg("path", { id: id2, fill: "none" });
    const s1 = svg("path", { class: "gl-line", pathLength: "1" });
    const s2 = svg("path", { class: "gl-line gl-line2", pathLength: "1" });
    const tp1 = svg("textPath", { href: "#" + id1, startOffset: "50%" }, "ГОЛОСОВЫЕ");
    const tp2 = svg("textPath", { href: "#" + id2, startOffset: "50%" }, "слышит · понимает · отвечает голосом");
    tp1.setAttributeNS(XL, "xlink:href", "#" + id1);
    tp2.setAttributeNS(XL, "xlink:href", "#" + id2);
    const t1 = svg("text", { class: "gl-t1", "text-anchor": "middle" }, tp1);
    const t2 = svg("text", { class: "gl-t2", "text-anchor": "middle" }, tp2);
    const sv = svg("svg", { class: "gl-svg", "aria-hidden": "true" }, svg("defs", {}, d1, d2), s1, s2, t1, t2);
    c.append(sv);
    let G = { W: 1, H: 1, y1: 0, y2: 0, a1: 0, a2: 0, fs: 40 };
    const path = (y0, amp, ph, W) =>
      `M${f(-0.08 * W, 1)} ${f(y0 + amp * 0.5 * Math.sin(ph), 1)}C${f(0.3 * W, 1)} ${f(y0 - amp, 1)} ${f(0.68 * W, 1)} ${f(y0 + amp, 1)} ${f(1.08 * W, 1)} ${f(y0 + amp * 0.5 * Math.sin(ph + 1.7), 1)}`;
    return {
      layout(e) {
        sv.setAttribute("viewBox", `0 0 ${e.W} ${e.H}`);
        const fs = e.P ? e.W * 0.098 : Math.min(e.H * 0.15, e.W * 0.085);
        G = { W: e.W, H: e.H, y1: e.H * (e.P ? 0.42 : 0.42), y2: e.H * (e.P ? 0.57 : 0.64), a1: e.H * (e.P ? 0.06 : 0.11), a2: e.H * (e.P ? 0.04 : 0.07), fs };
        t1.setAttribute("font-size", f(fs, 1));
        t2.setAttribute("font-size", f(clamp(fs * 0.3, 13, 26), 1));
      },
      update(lt) {
        const amp = 1 - 0.45 * E.out3(seg(lt, 0, 1.3));
        const a = path(G.y1, G.a1 * amp, lt * 2.4, G.W);
        const b = path(G.y2, -G.a2 * amp, lt * 2 + 1, G.W);
        d1.setAttribute("d", a);
        s1.setAttribute("d", a);
        d2.setAttribute("d", b);
        s2.setAttribute("d", b);
        const k = E.out4(seg(lt, 0.02, 0.6));
        tp1.setAttribute("startOffset", f(lerp(78, 50, k) - lt * 1.6, 2) + "%");
        tp2.setAttribute("startOffset", f(lerp(26, 50, E.out4(seg(lt, 0.2, 0.8))) + lt * 1.2, 2) + "%");
        css(t1, { opacity: f(clamp(seg(lt, 0.02, 0.2) * 1)) });
        css(t2, { opacity: f(seg(lt, 0.25, 0.5)) });
        css(s1, { strokeDashoffset: String(f(1 - E.out3(seg(lt, 0, 0.55)))) });
        css(s2, { strokeDashoffset: String(f(1 - E.out3(seg(lt, 0.15, 0.7)))) });
      },
      draw(gc, lt, p, e) {
        embers(gc, e, lt, 55, 12, 0.6);
        // осциллограмма
        const n = e.P ? 30 : 46;
        const ww = Math.min(e.W * (e.P ? 0.86 : 0.6), 760);
        const x0 = (e.W - ww) / 2;
        const y = e.H * (e.P ? 0.74 : 0.82);
        const mh = e.H * (e.P ? 0.07 : 0.09);
        const bw = (ww / n) * 0.42;
        const on = seg(lt, 0.15, 0.45);
        gc.lineCap = "round";
        gc.lineWidth = bw;
        for (let i = 0; i < n; i++) {
          const u = i / (n - 1);
          const env1 = Math.sin(u * Math.PI) ** 0.7;
          const v = 0.12 + 0.88 * Math.abs(Math.sin(i * 0.71 + lt * 9) * Math.sin(i * 0.23 - lt * 3.7));
          const hh = Math.max(bw * 0.6, mh * v * env1 * on);
          const x = x0 + u * ww;
          gc.strokeStyle = i % 5 === 2 ? "#ffffff" : "#ff3d3a";
          gc.globalAlpha = 0.9 * on;
          gc.beginPath();
          gc.moveTo(x, y - hh / 2);
          gc.lineTo(x, y + hh / 2);
          gc.stroke();
        }
        gc.globalAlpha = 1;
      },
    };
  });

  /* 12e. «СТИКЕРЫ · КАРТИНКИ · САЙТЫ» — растяжение на красном */
  scene("stretch", 1.5, { bg: "red", flash: "white", out: "smear" }, (c) => {
    const els = ["СТИКЕРЫ", "КАРТИНКИ", "САЙТЫ"].map((t) => L(t));
    const tb = TB(els, "tw k");
    const mbs = els.map((el) => mblur(el));
    const cap = h("div", { class: "cap-mono k", text: "+ игры · открытки · презентации" });
    const col = h("div", { class: "col" }, tb, cap);
    c.append(col);
    return {
      layout(e) {
        fitJustify(tb, e.P ? tw(e) : Math.min(e.W * 0.58, 860), e.H * (e.P ? 0.56 : 0.64), 1.5);
        cap.style.fontSize = f(e.P ? clamp(e.W * 0.038, 12, 17) : clamp(e.H * 0.026, 13, 20), 1) + "px";
        col.style.gap = f(e.H * 0.035, 1) + "px";
      },
      update(lt) {
        els.forEach((el, i) => {
          const q = seg(lt, 0.02 + i * 0.15, 0.4 + i * 0.15);
          const k = E.out5(q);
          const sx = 1 + (1 - k) * 4 + 0.035 * Math.sin(lt * 5 + i * 2) * k;
          css(el, { transform: `scaleX(${f(sx)})`, transformOrigin: i % 2 ? "100% 50%" : "0% 50%", opacity: f(clamp(q * 5)) });
          mbs[i](q > 0 && q < 1 ? 40 * (1 - q) ** 3 : 0);
        });
        css(cap, { opacity: f(seg(lt, 0.7, 0.95)) });
      },
    };
  });

  /* 12f. «ВИДЕО / ИЗ TIKTOK» — уголки видоискателя, REC */
  scene("video", 1.5, { bg: "ink", out: "smear" }, (c) => {
    const corners = ["tl", "tr", "bl", "br"].map((k) => h("i", { class: "vf vf-" + k }));
    const recDot = h("i", { class: "vf-dot" });
    const tc = h("span", { class: "vf-tc", text: "00:00:00:00" });
    const hud = h("div", { class: "vf-hud" }, h("span", { class: "vf-rec" }, recDot, "REC"), tc);
    const tb = TB(["ВИДЕО", "ИЗ *TIKTOK*"], "tw w");
    const cap = h("div", { class: "cap-mono", text: "и с YouTube — прямо в чат" });
    const col = h("div", { class: "col" }, tb, cap);
    const frame = h("div", { class: "vf-frame" }, corners, hud);
    c.append(frame, col);
    return {
      layout(e) {
        if (e.P) fitJustify(tb, tw(e) * 0.9, e.H * 0.42, 1.6);
        else fitBlock(tb, tw(e) * 0.66, e.H * 0.5);
        cap.style.fontSize = f(e.P ? clamp(e.W * 0.038, 12, 17) : clamp(e.H * 0.026, 13, 20), 1) + "px";
        col.style.gap = f(e.H * 0.04, 1) + "px";
        css(frame, { "--vfz": f(e.P ? clamp(e.W * 0.08, 22, 40) : clamp(e.H * 0.07, 28, 64), 1) + "px", fontSize: f(clamp(Math.min(e.W, e.H) * 0.032, 11, 16), 1) + "px" });
      },
      update(lt, p, e) {
        const k = E.out3(seg(lt, 0, 0.45));
        css(frame, { "--vfi": f(lerp(-0.02, 0.06, k) * Math.min(e.W, e.H) + e.g * 0.6, 1) + "px", opacity: f(seg(lt, 0, 0.15)) });
        css(recDot, { opacity: Math.floor(lt * 3) % 2 ? "0.15" : "1" });
        const fr = Math.floor(lt * 24);
        const ss = 7 + Math.floor(fr / 24);
        tc.textContent = `00:00:${String(ss).padStart(2, "0")}:${String(fr % 24).padStart(2, "0")}`;
        const qf = seg(lt, 0.05, 0.5);
        const kf = E.out3(qf);
        css(tb, { transform: `scale(${f(1.12 - 0.12 * kf + 0.04 * p)})`, filter: qf < 1 ? `blur(${f((1 - kf) * 0.1, 3)}em)` : "none", opacity: f(clamp(qf * 4)) });
        css(cap, { opacity: f(seg(lt, 0.55, 0.8)) });
      },
    };
  });

  /* 12g. Красный круг-циферблат и печатающийся текст «и всё это — / в одном чате» */
  scene("dial", 2.0, { bg: "glow", out: "zoom" }, (c) => {
    const gid = uid("dg");
    const grad = svg(
      "radialGradient",
      { id: gid },
      svg("stop", { offset: "0", "stop-color": "#ff7a6e" }),
      svg("stop", { offset: "0.55", "stop-color": "#ff3d3a" }),
      svg("stop", { offset: "1", "stop-color": "#b10f22" })
    );
    const ticks = svg("g", { class: "dl-ticks" });
    for (let i = 0; i < 72; i++) {
      const a = (i / 72) * Math.PI * 2;
      const r1 = 40;
      const r2 = i % 6 === 0 ? 46 : 43.5;
      ticks.append(svg("line", { x1: f(Math.cos(a) * r1, 2), y1: f(Math.sin(a) * r1, 2), x2: f(Math.cos(a) * r2, 2), y2: f(Math.sin(a) * r2, 2) }));
    }
    const CIRC = 2 * Math.PI * 49;
    const arc = svg("circle", { r: "49", class: "dl-arc", "stroke-dasharray": `${f(CIRC, 2)} ${f(CIRC, 2)}`, transform: "rotate(-90)" });
    const core = svg("circle", { r: "25", fill: `url(#${gid})`, class: "dl-core" });
    const ring = svg("circle", { r: "33", class: "dl-ring" });
    const dot = svg("circle", { r: "3.4", class: "dl-dot" });
    const dial = svg("svg", { viewBox: "-52 -52 104 104", class: "dl-svg", "aria-hidden": "true" }, svg("defs", {}, grad), ticks, ring, arc, core, dot);
    const a1 = LL("и всё это *—*", "", "ty");
    const a2 = LL("в одном чате", "", "ty");
    const caret = h("span", { class: "dl-caret" });
    const txt = h("div", { class: "dl-text" }, a1.el, a2.el);
    const box = h("div", { class: "dl-box" }, dial);
    const wrap = h("div", { class: "dl" }, box, txt);
    c.append(wrap);
    const chars = a1.chars.concat(a2.chars);
    const type = typer(chars);
    let caretAt = -1;
    return {
      layout(e) {
        wrap.classList.toggle("dl-p", e.P);
        const ds = e.P ? Math.min(e.W * 0.62, e.H * 0.36) : Math.min(e.H * 0.5, e.W * 0.34);
        css(box, { width: f(ds, 1) + "px", height: f(ds, 1) + "px" });
        txt.style.fontSize = f(e.P ? clamp(e.W * 0.085, 24, 44) : clamp(ds * 0.15, 26, 64), 1) + "px";
      },
      update(lt) {
        const k = E.back(seg(lt, 0, 0.42));
        css(box, { transform: `scale(${f(0.4 + 0.6 * Math.max(0, k))})`, opacity: f(seg(lt, 0, 0.12)) });
        ticks.setAttribute("transform", `rotate(${f(lt * 40, 2)})`);
        arc.setAttribute("stroke-dashoffset", f(CIRC * (1 - E.io2(seg(lt, 0.15, 1.9))), 2));
        core.setAttribute("r", f(25 + 1.6 * Math.sin(lt * 8), 2));
        const n = seg(lt, 0.35, 1.45) * chars.length;
        type(n);
        const ni = clamp(Math.floor(n), 0, chars.length);
        if (ni !== caretAt) {
          if (ni > 0) chars[ni - 1].after(caret);
          else a1.el.prepend(caret);
          caretAt = ni;
        }
        css(caret, { opacity: lt < 1.5 || Math.floor(lt * 3.4) % 2 === 0 ? "1" : "0" });
      },
      draw(gc, lt, p, e) {
        embers(gc, e, lt, 66, 12, 0.6);
      },
    };
  });

  /* 13. Бумага, красная звезда-взрыв: «ВЫ / СЕРЬЁЗНО?!» */
  scene("seryozno", 1.6, { bg: "paper", flash: "red", out: "smear" }, (c, e0) => {
    const r = rng(1313);
    const n = 15;
    const pts = [];
    const pts2 = [];
    for (let i = 0; i < n * 2; i++) {
      const a = (i / (n * 2)) * Math.PI * 2;
      const rr = i % 2 === 0 ? 96 - r() * 18 : 48 + r() * 14;
      pts.push(f(Math.cos(a) * rr, 2) + "," + f(Math.sin(a) * rr, 2));
      pts2.push(f(Math.cos(a) * rr * 1.1, 2) + "," + f(Math.sin(a) * rr * 1.1, 2));
    }
    const fill = svg("polygon", { points: pts.join(" "), class: "sz-fill" });
    const line = svg("polygon", { points: pts2.join(" "), class: "sz-line" });
    const burst = svg("svg", { viewBox: "-110 -110 220 220", class: "sz-burst", "aria-hidden": "true" }, line, fill);
    const els = ["ВЫ", "СЕРЬЁЗНО?!"].map((t) => L(t));
    const tb = TB(els, (e0.P ? "tc" : "tw") + " k al sz-tb");
    const mbs = els.map((el) => mblur(el));
    c.append(burst, tb);
    let fs = 100;
    let bs = 100;
    return {
      layout(e) {
        fs = e.P ? fitJustify(tb, tw(e), e.H * 0.5, 2) : fitJustify(tb, Math.min(e.W * 0.56, 820), e.H * 0.7, 2);
        bs = e.P ? e.W * 1.15 : e.H * 1.05;
        css(burst, { width: f(bs, 1) + "px", height: f(bs, 1) + "px", left: e.P ? "64%" : "70%", top: e.P ? "64%" : "50%" });
        css(tb, { left: f(e.P ? e.g : e.W * 0.07, 1) + "px", top: e.P ? "34%" : "50%" });
      },
      update(lt, p) {
        const k = E.back(seg(lt, 0.04, 0.34));
        css(burst, { transform: `translate(-50%,-50%) rotate(${f(lerp(-50, 0, clamp(k)) + lt * 9, 2)}deg) scale(${f(Math.max(0, k))})` });
        css(line, { transform: `rotate(${f(8 - lt * 14, 2)}deg)` });
        els.forEach((el, i) => {
          const q = seg(lt, 0.12 + i * 0.1, 0.4 + i * 0.1);
          const kk = E.out5(q);
          css(el, { transform: `translateX(${f((1 - kk) * -env.W * 0.9, 1)}px) scaleX(${f(1 + (1 - kk) * 0.6)})`, opacity: q > 0 ? "1" : "0" });
          mbs[i](q > 0 && q < 1 ? 50 * (1 - q) ** 3 : 0);
        });
        const [sx, sy] = shake(lt, 0.5, 0.45, fs * 0.06);
        css(tb, { transform: `translateY(-50%) translate(${f(sx, 1)}px,${f(sy, 1)}px) scale(${f(1 + 0.04 * p)})` });
      },
    };
  });

  /* 14. Тёмная сетка: «ПРЕДСТАВЬ, / КАК ДЕЛАТЬ ЭТО» + курсив с засечками «по-старому» */
  scene("predstav", 2.0, { bg: "ink grid", out: "smear" }, (c, e0) => {
    const in1 = h("span", { class: "pd-in", text: "ПРЕДСТАВЬ," });
    const l1 = h("span", { class: "ln pd-mask " + (e0.P ? "tc" : "tw") }, in1);
    const handles = ["a", "b", "c", "d"].map((k) => h("i", { class: "sel-h sel-" + k }));
    const cursor = svg(
      "svg",
      { viewBox: "0 0 24 24", class: "pd-cur", "aria-hidden": "true" },
      svg("path", { d: "M3 2v19l5.2-5 3.6 7.6 3.2-1.5-3.5-7.4H19Z", fill: "#fff", stroke: "#0a0a0b", "stroke-width": "1.4", "stroke-linejoin": "round" })
    );
    const selBox = h("i", { class: "sel-box" });
    const sel = h("span", { class: "sel" }, "ЭТО", selBox, handles, cursor);
    const in2 = h("span", { class: "pd-in" }, "КАК ДЕЛАТЬ ", sel);
    const l2 = h("span", { class: "ln pd-mask pd-l2" }, in2);
    const ty = LL("по-старому", "pd-l3", "ty");
    const tb = TB([l1, l2, ty.el], "w al pd-tb");
    c.append(tb);
    const type = typer(ty.chars);
    return {
      layout(e) {
        fitBlock(tb, tw(e) * (e.P ? 1 : 0.86), e.H * 0.62);
      },
      update(lt, p) {
        const k1 = E.out5(seg(lt, 0.04, 0.42));
        css(in1, { transform: `translateY(${f((1 - k1) * 110, 2)}%)` });
        const k2 = E.out5(seg(lt, 0.3, 0.66));
        css(in2, { transform: `translateY(${f((1 - k2) * 110, 2)}%)` });
        const ks = E.back(seg(lt, 0.86, 1.06));
        css(selBox, { opacity: f(clamp(ks * 2)), transform: `scale(${f(1.25 - 0.25 * clamp(ks))})` });
        handles.forEach((hd) => css(hd, { opacity: f(clamp(ks * 2)) }));
        const kc = E.io3(seg(lt, 0.5, 0.88));
        css(cursor, { transform: `translate(${f(lerp(3.2, 0.2, kc), 3)}em,${f(lerp(2.4, -0.2, kc), 3)}em) scale(${lt > 0.86 && lt < 0.96 ? 0.85 : 1})`, opacity: f(seg(lt, 0.45, 0.6)) });
        type(seg(lt, 1.05, 1.6) * ty.chars.length);
        css(tb, { transform: `scale(${f(1 + 0.04 * p)})` });
      },
    };
  });

  /* 15. Каскад слов: ГУГЛИТЬ. КОПИРОВАТЬ. ВСТАВЛЯТЬ. ПЕРЕДЕЛЫВАТЬ. — стопкой */
  scene("kaskad", 2.2, { bg: "ink dots", out: "zoom" }, (c) => {
    const W0 = ["ГУГЛИТЬ.", "КОПИРОВАТЬ.", "ВСТАВЛЯТЬ.", "ПЕРЕДЕЛЫВАТЬ."];
    const list = W0.concat(W0);
    const words = list.map((t) => h("div", { class: "kk-w tc", text: t }));
    const stackEl = h("div", { class: "kk" }, words);
    c.append(stackEl);
    let fsz = [];
    let hz = [];
    const T0 = 0.04;
    const STEP = 0.2;
    return {
      layout(e) {
        const target = e.P ? e.W - 2 * e.g : Math.min(e.W * 0.56, 820);
        fsz = words.map((w) => {
          w.style.fontSize = "100px";
          const s = Math.min((100 * target) / (w.offsetWidth || 1), e.H * 0.2);
          w.style.fontSize = f(s, 2) + "px";
          return s;
        });
        hz = words.map((w) => w.offsetHeight);
      },
      update(lt, p, e) {
        const kin = words.map((_, i) => E.out4(seg(lt, T0 + i * STEP, T0 + i * STEP + 0.22)));
        let cursor = 0;
        const base = e.H * (e.P ? 0.68 : 0.76);
        for (let i = words.length - 1; i >= 0; i--) {
          const w = words[i];
          if (kin[i] <= 0) {
            css(w, { opacity: "0" });
            continue;
          }
          let depth = 0;
          for (let j = i + 1; j < words.length; j++) depth += kin[j];
          const s = Math.pow(0.8, depth);
          const hh = hz[i] * 0.86 * s;
          const rise = (1 - kin[i]) * e.H * 0.28;
          const top = base - cursor - hh + rise;
          cursor += hh * kin[i];
          const op = clamp(1 - depth * 0.17) * clamp(kin[i] * 2);
          const fresh = 1 - seg(lt, T0 + i * STEP, T0 + i * STEP + 0.16);
          css(w, {
            transform: `translate(-50%,${f(top, 1)}px) scale(${f(s)})`,
            opacity: f(op),
            color: depth < 0.5 ? "#fff" : depth < 1.5 ? "#d8d8dc" : "#8d8d96",
            filter: fresh > 0.02 ? `blur(${f(fresh * 10, 1)}px)` : "none",
          });
        }
      },
    };
  });

  /* 16. Бумага: «А ПОТОМ …» */
  scene("potom", 1.1, { bg: "paper" }, (c, e0) => {
    const dots = [0, 1, 2].map(() => h("span", { class: "pt-dot", text: "." }));
    const lines = e0.P ? [L("А"), h("span", { class: "ln" }, "ПОТОМ", dots)] : [h("span", { class: "ln" }, "А ПОТОМ", dots)];
    const tb = TB(lines, "tw k al");
    const wrap = h("div", { class: "mbw" }, tb);
    const mb = mblur(wrap);
    c.append(wrap);
    return {
      layout(e) {
        fitBlock(tb, tw(e) * 0.9, e.H * 0.5);
      },
      update(lt, p, e) {
        const q = seg(lt, 0, 0.28);
        const k = E.out5(q);
        mb(0, q > 0 && q < 1 ? 40 * (1 - q) ** 3 : 0);
        css(tb, { transform: `translateY(${f((1 - k) * e.H * 0.7, 1)}px) scale(${f(1 + 0.05 * p)})` });
        dots.forEach((d, i) => {
          const kk = E.back(seg(lt, 0.36 + i * 0.13, 0.5 + i * 0.13));
          css(d, { opacity: kk > 0 ? "1" : "0", transform: `scale(${f(Math.max(0, kk))})` });
        });
      },
    };
  });

  /* 17. «ЖДАТЬ.» — прогресс-бар «загрузка…» и таймер, цифры бегут */
  scene("zhdat", 2.2, { bg: "ink dots", out: "smear" }, (c) => {
    const title = h("div", { class: "zh-title tw", text: "ЖДАТЬ." });
    const pct = h("span", { class: "zh-pct", text: "1%" });
    const ldots = h("span", { class: "zh-ld", text: "..." });
    const fillEl = h("i", { class: "zh-fill" });
    const barEl = h("div", { class: "zh-bar" }, fillEl);
    const glass = svg(
      "svg",
      { viewBox: "0 0 24 32", class: "zh-glass", "aria-hidden": "true" },
      svg("path", { d: "M3 2h18M3 30h18M5 2c0 8 7 10 7 14S5 22 5 30M19 2c0 8-7 10-7 14s7 6 7 14", fill: "none", stroke: "#fff", "stroke-width": "2", "stroke-linecap": "round" }),
      svg("path", { d: "M8 27c1-3 3-4 4-5 1 1 3 2 4 5Z", fill: "#ff3d3a" })
    );
    const timer = h("span", { class: "zh-timer", text: "04:06:18" });
    const eta = h("div", { class: "zh-eta" }, glass, h("div", { class: "zh-etac" }, h("span", { class: "zh-etal", text: "ОСТАЛОСЬ" }), timer));
    const row = h("div", { class: "zh-row" }, h("span", {}, "ЗАГРУЗКА", ldots), pct);
    const box = h("div", { class: "zh" }, title, row, barEl, eta);
    c.append(box);
    const base = 4 * 3600 + 6 * 60 + 18;
    const two = (v) => String(v).padStart(2, "0");
    return {
      layout(e) {
        const fs = fitBlock(title, tw(e) * (e.P ? 1 : 0.72), e.H * 0.3);
        box.style.fontSize = f(fs, 2) + "px";
        title.style.fontSize = "1em";
      },
      update(lt, p) {
        const q = seg(lt, 0, 0.36);
        const k = E.out4(q);
        css(title, { transform: `scale(${f(1.25 - 0.25 * k)})`, filter: q < 1 ? `blur(${f((1 - k) * 0.1, 3)}em)` : "none", opacity: f(clamp(q * 3)) });
        const k2 = E.out3(seg(lt, 0.3, 0.6));
        css(row, { opacity: f(k2) });
        css(barEl, { opacity: f(k2) });
        const k3 = E.out3(seg(lt, 0.5, 0.85));
        css(eta, { opacity: f(k3), transform: `translateY(${f((1 - k3) * 0.2, 3)}em)` });
        const pr = 0.01 + 0.025 * seg(lt, 0.4, 2.2);
        css(fillEl, { transform: `scaleX(${f(pr, 4)})` });
        pct.textContent = Math.floor(pr * 100) + "%";
        ldots.textContent = ".".repeat(1 + (Math.floor(lt * 4) % 3));
        const secs = base + Math.floor(seg(lt, 0.6, 2.2) * 2.2 * 61);
        timer.textContent = `${two(Math.floor(secs / 3600))}:${two(Math.floor(secs / 60) % 60)}:${two(secs % 60)}`;
        css(glass, { transform: `rotate(${f(180 * E.io3(seg(lt, 1.2, 1.55)), 1)}deg)` });
      },
    };
  });

  /* 18. «А МОЖНО / ТАК?» под наклоном, с лазером → глитч-полосы */
  scene("a-mozhno", 1.6, { bg: "glow", flash: "white" }, (c, e0) => {
    const txt = e0.P ? ["А МОЖНО", "ТАК?"] : ["А МОЖНО", "ТАК?"];
    const mk = (cls) => TB(txt.map((t) => L(t)), "tw w " + cls);
    const main = mk("am-main");
    const BANDS = 6;
    const slices = [];
    for (let i = 0; i < BANDS; i++) {
      const s = mk("am-slice" + (i === 2 ? " am-red" : ""));
      s.style.clipPath = `inset(${f((i / BANDS) * 100, 2)}% -20% ${f(100 - ((i + 1) / BANDS) * 100, 2)}% -20%)`;
      slices.push(s);
    }
    const tilt = h("div", { class: "am-tilt" }, main, slices);
    const mb = mblur(tilt);
    c.append(tilt);
    let geo = { cx: 0, cy: 0 };
    let fs = 100;
    const ANG = -8;
    return {
      layout(e) {
        fs = e.P ? fitJustify(main, tw(e) * 0.84, e.H * 0.4, 1.5) : fitBlock(main, tw(e) * 0.72, e.H * 0.58);
        const lines = [...main.children];
        for (const s of slices) {
          s.style.fontSize = main.style.fontSize;
          [...s.children].forEach((l, i) => (l.style.fontSize = lines[i].style.fontSize));
        }
        const r = rel(tilt);
        geo = { cx: r.cx, cy: r.cy };
      },
      update(lt, p, e) {
        const q = seg(lt, 0, 0.3);
        const k = E.out5(q);
        mb(q > 0 && q < 1 ? 56 * (1 - q) ** 3 : 0);
        const glitch = lt > 1.12;
        const [sx, sy] = shake(lt, 0.3, 0.35, fs * 0.04);
        css(tilt, { transform: `translate(${f((1 - k) * -e.W + sx, 1)}px,${f(sy, 1)}px) rotate(${ANG}deg) skewX(-6deg) scale(${f(1 + 0.06 * p)})` });
        css(main, { opacity: glitch ? "0" : "1" });
        const r = rng(Math.floor(lt * 24) * 31 + 7);
        slices.forEach((s) => {
          const dx = (r() - 0.5) * 0.5;
          css(s, { visibility: glitch ? "visible" : "hidden", transform: glitch ? `translateX(${f(dx, 3)}em)` : "none" });
        });
      },
      draw(gc, lt, p, e) {
        embers(gc, e, lt, 88, 14, 0.7);
        const t = Math.tan((ANG * Math.PI) / 180);
        const x0 = -0.1 * e.W;
        const x1 = 1.1 * e.W;
        const y0 = geo.cy + (x0 - geo.cx) * t;
        const y1 = geo.cy + (x1 - geo.cx) * t;
        if (lt > 0.32 && lt < 1.12) {
          const k = E.io2(seg(lt, 0.32, 0.78));
          laser(gc, x0, y0, x1, y1, k, { tail: 0.6, alpha: 1 - seg(lt, 0.78, 1.12), w: 3, head: 28 });
        }
        sparks(gc, lt, 0.55, lerp(x0, x1, E.io2(seg(0.55, 0.32, 0.78))), lerp(y0, y1, E.io2(seg(0.55, 0.32, 0.78))), 515, 18, { scale: Math.min(e.W, e.H) / 800 });
        if (lt > 1.12) {
          const r = rng(Math.floor(lt * 24) * 17 + 3);
          gc.globalCompositeOperation = "lighter";
          for (let i = 0; i < 16; i++) {
            const x = r() * e.W;
            const w = 1 + r() * 5;
            gc.globalAlpha = 0.15 + r() * 0.45;
            gc.fillStyle = r() < 0.6 ? "#ff3d3a" : "#ffffff";
            gc.fillRect(x, 0, w, e.H);
          }
          gc.globalAlpha = 1;
          gc.globalCompositeOperation = "source-over";
        }
      },
    };
  });

  /* 19. Столбиком: «›_ ПИШЕШЬ» / «✦ СТЕЛЛА ДЕЛАЕТ» / «▶ ГОТОВО» */
  scene("stolbik", 2.2, { bg: "glowl", flash: "red", out: "smear" }, (c, e0) => {
    const mkRow = (ico, lines, cls) => {
      const t = h("div", { class: "sb-t " + cls }, lines.map((l) => h("span", { class: "sb-l", text: l })));
      const ic = h("span", { class: "sb-ic" }, ico);
      return { ic, t, m: mblur(t) };
    };
    const rows = [
      mkRow(h("span", { class: "sb-prompt", text: "›_" }), ["ПИШЕШЬ"], "sb-outline"),
      mkRow(icon("star", "sb-star"), e0.P ? ["СТЕЛЛА", "ДЕЛАЕТ"] : ["СТЕЛЛА ДЕЛАЕТ"], "sb-red"),
      mkRow(icon("play", "sb-play"), ["ГОТОВО"], "sb-white"),
    ];
    const vline = h("i", { class: "sb-vline" });
    const node = h("i", { class: "sb-node" });
    const grid = h("div", { class: "sb tw" }, vline, node, rows.map((r) => [r.ic, r.t]));
    c.append(grid);
    return {
      layout(e) {
        fitBlock(grid, tw(e) * (e.P ? 0.9 : 0.78), e.H * (e.P ? 0.56 : 0.68));
      },
      update(lt, p) {
        css(vline, { transform: `scaleY(${f(E.out3(seg(lt, 0, 0.5)))})` });
        css(node, { transform: `translateY(${f(lerp(-1.4, 1.1, E.io2(seg(lt, 0.1, 1.5))), 3)}em)` });
        rows.forEach((r, i) => {
          const t0 = 0.1 + i * 0.42;
          const ki = E.back(seg(lt, t0, t0 + 0.25));
          css(r.ic, { transform: `scale(${f(Math.max(0, ki))})` });
          const q = seg(lt, t0 + 0.06, t0 + 0.4);
          const k = E.out4(q);
          css(r.t, { clipPath: q >= 1 ? "none" : `inset(-20% ${f((1 - k) * 100, 2)}% -20% -5%)`, transform: `translateX(${f((1 - k) * -0.4, 3)}em)` });
          r.m(q > 0 && q < 1 ? 26 * (1 - q) ** 2 : 0);
        });
        css(grid, { transform: `translateY(${f(lerp(0.12, -0.06, E.io2(p)), 3)}em)` });
      },
      draw(gc, lt, p, e) {
        embers(gc, e, lt, 99, 12, 0.6);
      },
    };
  });

  /* 20. Рамка плеера: «И ВОТ / РЕЗУЛЬТАТ» с ▶ и бегущим прогрессом */
  scene("player", 2.0, { bg: "ink", flash: "white", out: "zoom" }, (c, e0) => {
    const tri = icon("play", "pl-tri");
    const word = h("span", { class: "pl-word " + (e0.P ? "tc" : "tw"), text: "РЕЗУЛЬТАТ" });
    const mask = h("span", { class: "pl-mask" }, word);
    const mid = h("div", { class: "pl-mid" }, tri, mask);
    const kick = LL("И ВОТ", "pl-kick", "ty");
    const fillEl = h("i", { class: "pl-fill" });
    const knob = h("i", { class: "pl-knob" });
    const time = h("span", { class: "pl-time", text: "0:04 / 0:20" });
    const bottom = h("div", { class: "pl-bottom" }, h("div", { class: "pl-bar" }, fillEl, knob), time);
    const frame = h("div", { class: "pl-frame" }, h("div", { class: "pl-top" }, kick.el), mid, bottom);
    const persp = h("div", { class: "pl-persp" }, frame);
    c.append(persp);
    const mb = mblur(word);
    const type = typer(kick.chars);
    return {
      layout(e) {
        const fw = e.P ? e.W - 2 * e.g : Math.min(e.W * 0.68, 1080);
        const fh = e.P ? Math.min(fw * 1.2, e.H * 0.6) : Math.min(fw * 0.5625, e.H * 0.72);
        css(frame, { width: f(fw, 1) + "px", height: f(fh, 1) + "px", fontSize: f(clamp(fw / 24, 13, 34), 1) + "px" });
        fitBlock(mid, fw * 0.86, fh * 0.44);
        frame.style.fontSize = f(clamp(fw / 24, 13, 34), 1) + "px";
      },
      update(lt, p) {
        const kf = E.out5(seg(lt, 0.25, 0.65));
        css(frame, { transform: `rotateY(${f((1 - E.out3(seg(lt, 0.25, 1.4))) * 22, 2)}deg) scale(${f(0.35 + 0.65 * kf)})`, opacity: f(clamp(seg(lt, 0.25, 0.4))) });
        const tk = E.back(seg(lt, 0, 0.3));
        const pulse = lt < 0.5 ? 1 + 0.12 * Math.sin(lt * 20) : 1;
        css(tri, { transform: `scale(${f(Math.max(0, tk) * pulse)})` });
        const q = seg(lt, 0.55, 0.9);
        const k = E.out5(q);
        css(word, { transform: `translateX(${f((1 - k) * -105, 2)}%)` });
        mb(q > 0 && q < 1 ? 40 * (1 - q) ** 3 : 0);
        type(seg(lt, 0.7, 1.0) * kick.chars.length);
        const pr = lerp(0.18, 0.64, seg(lt, 0.4, 2.0));
        css(fillEl, { transform: `scaleX(${f(pr, 4)})` });
        css(knob, { left: f(pr * 100, 2) + "%" });
        const s = Math.floor(pr * 20);
        time.textContent = `0:${String(s).padStart(2, "0")} / 0:20`;
      },
      draw(gc, lt, p, e) {
        embers(gc, e, lt, 120, 10, 0.5 * seg(lt, 0.3, 0.8));
      },
    };
  });

  /* 21. «ОТ ПЕРВОЙ ИДЕИ / ДО ГОТОВОГО ФАЙЛА» с лампочкой */
  scene("idea", 2.2, { bg: "ink", out: "smear" }, (c, e0) => {
    const gid = uid("bulb");
    const bulb = svg(
      "svg",
      { viewBox: "0 0 64 84", class: "id-bulb", "aria-hidden": "true" },
      svg(
        "defs",
        {},
        svg("radialGradient", { id: gid }, svg("stop", { offset: "0", "stop-color": "#ff8c80" }), svg("stop", { offset: "0.5", "stop-color": "#ff3d3a" }), svg("stop", { offset: "1", "stop-color": "#ff3d3a", "stop-opacity": "0" }))
      ),
      svg("circle", { cx: "32", cy: "30", r: "34", fill: `url(#${gid})`, class: "id-halo" }),
      svg("path", { d: "M32 5C18 5 8 15 8 29c0 9 5 15 9 20 3 4 4 7 4 11h22c0-4 1-7 4-11 4-5 9-11 9-20C56 15 46 5 32 5Z", class: "id-glass" }),
      svg("path", { d: "M24 42l4-9 4 9 4-9 4 9", class: "id-fil" }),
      svg("path", { d: "M22 66h20M23 72h18M27 78h10", class: "id-base" })
    );
    const aTxt = h("div", { class: "id-txt" }, h("span", { class: "id-s", text: "ОТ ПЕРВОЙ" }), h("span", { class: "id-b tw", text: "ИДЕИ" }));
    const A = h("div", { class: "id-a" }, h("span", { class: "id-bw" }, bulb), aTxt);
    const fileIc = h("i", { class: "id-file-ic" });
    const file = h("div", { class: "id-file" }, fileIc, h("span", { text: "открытка.html" }));
    const bTxt = h("div", { class: "id-txt id-r" }, h("span", { class: "id-s", text: "ДО ГОТОВОГО" }), h("span", { class: "id-b tw", text: "ФАЙЛА" }));
    const B = h("div", { class: "id-bb" }, bTxt, file);
    const box = h("div", { class: "id" + (e0.P ? " id-p" : "") }, A, B);
    c.append(box);
    const mbB = mblur(bTxt);
    const halo = bulb.querySelector(".id-halo");
    let pa = { x: 0, y: 0 };
    let pb = { x: 0, y: 0 };
    return {
      layout(e) {
        fitBlock(box, tw(e) * (e.P ? 1 : 0.78), e.H * (e.P ? 0.66 : 0.74));
        const ra = rel(bulb);
        const rb = rel(file);
        pa = { x: ra.cx, y: ra.cy - ra.h * 0.12 };
        pb = { x: rb.x + rb.w * 0.1, y: rb.cy };
      },
      update(lt, p) {
        const fl = lt < 0.4 ? [0, 1, 0.15, 1, 0.4, 1, 1, 1][Math.floor(lt * 20) % 8] : 1;
        css(halo, { opacity: f(fl * (0.75 + 0.25 * Math.sin(lt * 7))) });
        const qa = seg(lt, 0.12, 0.46);
        const ka = E.out4(qa);
        css(aTxt, { transform: `scale(${f(1.4 - 0.4 * ka)})`, opacity: f(clamp(qa * 3)), filter: qa < 1 ? `blur(${f((1 - ka) * 0.1, 3)}em)` : "none" });
        const qb = seg(lt, 1.05, 1.4);
        const kb = E.out5(qb);
        css(bTxt, { transform: `translateX(${f((1 - kb) * 2.5, 3)}em)`, opacity: qb > 0 ? "1" : "0" });
        mbB(qb > 0 && qb < 1 ? 50 * (1 - qb) ** 3 : 0);
        const kf = E.back(seg(lt, 1.22, 1.5));
        css(file, { transform: `rotate(${f((1 - clamp(kf)) * -12, 2)}deg) scale(${f(Math.max(0, kf))})` });
        css(box, { transform: `scale(${f(1 + 0.05 * E.io2(p))})` });
      },
      draw(gc, lt, p, e) {
        embers(gc, e, lt, 133, 16, 0.75);
        if (lt > 0.62) {
          const k = E.io2(seg(lt, 0.62, 1.2));
          laser(gc, pa.x, pa.y, pb.x, pb.y, k, { tail: 1, alpha: 1 - 0.6 * seg(lt, 1.3, 2.2), w: 2.4, head: k < 1 ? 24 : 12 });
        }
        sparks(gc, lt, 1.2, pb.x, pb.y, 1201, 20, { scale: Math.min(e.W, e.H) / 900, g: 500 });
      },
    };
  });

  /* 22. Красный кадр: маленькое «СДЕЛАНО» + огромное «ОДНИМ / СООБЩЕНИЕМ.» */
  scene("odnim", 2.0, { bg: "red", flash: "white", out: "zoom" }, (c, e0) => {
    const rule = h("i", { class: "od-rule" });
    const kword = h("span", { text: "СДЕЛАНО" });
    const kr = h("div", { class: "od-k" }, kword, rule);
    const l1 = L("ОДНИМ");
    const l2 = L("СООБЩЕНИЕМ.");
    const tb = TB([l1, l2], (e0.P ? "tc" : "tw") + " k al");
    tb.prepend(kr);
    const m1 = mblur(l1);
    const m2 = mblur(l2);
    c.append(tb);
    let fs = 100;
    return {
      layout(e) {
        fs = fitJustify(tb, tw(e) * (e.P ? 1 : 0.86), e.H * 0.62, 2.2);
        kr.style.fontSize = f(clamp(fs * 0.2, 12, 30), 1) + "px";
      },
      update(lt, p) {
        const kk = E.out3(seg(lt, 0.02, 0.4));
        css(rule, { transform: `scaleX(${f(kk)})` });
        css(kword, { opacity: f(seg(lt, 0, 0.2)) });
        [l1, l2].forEach((l, i) => {
          const q = seg(lt, 0.1 + i * 0.12, 0.44 + i * 0.12);
          const k = E.out5(q);
          css(l, { transform: `translateX(${f((1 - k) * 60, 2)}%) scaleX(${f(1 + (1 - k) * 1.6)})`, opacity: q > 0 ? "1" : "0", transformOrigin: "0 50%" });
          (i ? m2 : m1)(q > 0 && q < 1 ? 60 * (1 - q) ** 3 : 0);
        });
        const [sx, sy] = shake(lt, 0.56, 0.45, fs * 0.05);
        css(tb, { transform: `translate(${f(sx, 1)}px,${f(sy, 1)}px) scale(${f(1 + 0.05 * E.io2(p))})` });
      },
    };
  });

  /* 23. Финал = #hero: логотип собирается лазером, искры, подпись и кнопки */
  scene("final", 2.4, { bg: "clear", flash: "red", hero: true }, () => {
    const logo = hero.querySelector(".hero-logo");
    const kick = hero.querySelector(".hero-kicker");
    const tag = hero.querySelector(".hero-tag");
    const btns = [...hero.querySelectorAll(".hero-cta > *")];
    const all = [logo, kick, tag, ...btns].filter(Boolean);
    let geo = { x: 0, w: 1, cy: 0 };
    let clean = true;
    const reset = () => {
      if (clean) return;
      for (const el of all) unstyle(el, ["opacity", "transform", "clip-path"]);
      unstyle(hero, ["--laser"]);
      clean = true;
    };
    return {
      layout() {
        if (!logo) return;
        const was = clean;
        reset();
        const r = rel(logo);
        geo = { x: r.x, w: r.w, cy: r.y + r.h * 0.56 };
        clean = was;
      },
      update(lt, p) {
        if (p >= 1) {
          reset();
          return;
        }
        clean = false;
        const kx = E.io2(seg(lt, 0.12, 0.9));
        const hx = lerp(-0.08 * env.W, 1.08 * env.W, kx);
        const rv = clamp((hx - geo.x) / geo.w);
        if (logo) css(logo, { clipPath: `inset(-40% ${f((1 - rv) * 100, 2)}% -40% -12%)` });
        css(hero, { "--laser": String(f(kx)) });
        if (kick) {
          const k = E.out4(seg(lt, 0.8, 1.2));
          css(kick, { opacity: f(k), transform: `translateY(${f((1 - k) * -14, 1)}px)` });
        }
        if (tag) {
          const k = E.out4(seg(lt, 1.0, 1.4));
          css(tag, { opacity: f(k), transform: `translateY(${f((1 - k) * 14, 1)}px)` });
        }
        btns.forEach((b, i) => {
          const k = E.back(seg(lt, 1.15 + i * 0.12, 1.55 + i * 0.12));
          css(b, { opacity: f(clamp(k * 1.5)), transform: `translateY(${f((1 - k) * 22, 1)}px)` });
        });
      },
      leave: reset,
      draw(gc, lt, p, e) {
        embers(gc, e, lt, 2024, 16, lerp(0.15, 0.55, seg(lt, 0, 1.2)));
        if (lt < 1.2) {
          const x0 = -0.08 * e.W;
          const x1 = 1.08 * e.W;
          const kx = E.io2(seg(lt, 0.12, 0.9));
          if (lt > 0.12) laser(gc, x0, geo.cy, x1, geo.cy, kx, { tail: 0.25, alpha: 1 - seg(lt, 0.9, 1.2), w: 2.4, head: 30 });
          [0.32, 0.45, 0.58, 0.7].forEach((t0, i) => {
            const kk = E.io2(seg(t0, 0.12, 0.9));
            sparks(gc, lt, t0, lerp(x0, x1, kk), geo.cy, 610 + i, 18, { scale: Math.min(e.W, e.H) / 700 });
          });
        }
      },
    };
  });

  /* ───────────── движок ───────────── */
  {
    let acc = 0;
    for (const s of SCENES) {
      s.start = acc;
      s.end = acc + s.dur;
      acc = s.end;
    }
  }
  const DURATION = f(SCENES[SCENES.length - 1].end, 3);
  const FLASH = { white: "#ffffff", red: "#ff3d3a", ink: "#0a0a0b" };

  let active = null;
  let fontGen = 0;

  function ensure(s) {
    if (!s._b) {
      const c = h("div", { class: "fs-c" });
      const cls = (s.bg || "ink")
        .split(" ")
        .map((x) => "bg-" + x)
        .join(" ");
      const root = h("div", { class: "fs " + cls, dataset: { scene: s.name } }, c);
      stage.insertBefore(root, canvas);
      const inst = s.build(c, env, root) || {};
      s._b = { root, c, inst, key: "" };
    }
    return s._b;
  }

  function invalidate() {
    for (const s of SCENES) {
      if (!s._b) continue;
      if (s._b.inst.leave) s._b.inst.leave();
      s._b.root.remove();
      s._b = null;
    }
    active = null;
    defs.replaceChildren();
  }

  function measureEnv() {
    const W = film.clientWidth || window.innerWidth || 390;
    const H = film.clientHeight || window.innerHeight || 844;
    env.W = W;
    env.H = H;
    env.P = H > W * 1.05;
    env.g = clamp(W * 0.055, 16, 72);
    env.dpr = Math.min(2, window.devicePixelRatio || 1);
    env.key = W + "x" + H + ":" + fontGen;
  }
  function sizeCanvas() {
    const cw = Math.round(env.W * env.dpr);
    const ch = Math.round(env.H * env.dpr);
    if (canvas.width !== cw) canvas.width = cw;
    if (canvas.height !== ch) canvas.height = ch;
  }

  function applyOut(s, b, lt) {
    const LEN = 0.2;
    const k = s.out ? seg(lt, s.dur - LEN, s.dur) : 0;
    if (k <= 0) {
      css(b.c, { transform: "none", opacity: "1", filter: "none" });
      return;
    }
    const q = E.in3(k);
    if (s.out === "smear") {
      css(b.c, { transform: `translateX(${f(-q * env.W * 0.4, 1)}px) scaleX(${f(1 + q * 0.9)})`, opacity: f(1 - q * 0.6), filter: `blur(${f(q * 10, 1)}px)` });
    } else if (s.out === "zoom") {
      css(b.c, { transform: `scale(${f(1 + q * 1.6)})`, opacity: f(1 - q), filter: `blur(${f(q * 8, 1)}px)` });
    }
  }

  let canvasDirty = true;
  function render(t) {
    const tt = clamp(t, 0, DURATION);
    let s = SCENES[SCENES.length - 1];
    for (const x of SCENES) {
      if (tt < x.end) {
        s = x;
        break;
      }
    }
    const b = ensure(s);
    if (active !== s) {
      if (active && active._b) {
        active._b.root.classList.remove("on");
        if (active._b.inst.leave) active._b.inst.leave();
      }
      b.root.classList.add("on");
      active = s;
      film.classList.toggle("film--hero", !!s.hero);
    }
    if (b.key !== env.key) {
      b.key = env.key;
      css(b.c, { transform: "none", opacity: "1", filter: "none" });
      if (b.inst.layout) b.inst.layout(env);
    }
    const lt = clamp(tt - s.start, 0, s.dur);
    const p = lt / s.dur;
    if (b.inst.update) b.inst.update(lt, p, env);
    applyOut(s, b, lt);

    const fk = s.flash ? 1 - seg(lt, 0, 0.17) : 0;
    css(flash, { opacity: String(f(fk * fk * fk * 0.95)), backgroundColor: FLASH[s.flash] || "#fff" });

    if (canvasDirty || b.inst.draw) {
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.clearRect(0, 0, canvas.width, canvas.height);
      canvasDirty = false;
      if (b.inst.draw) {
        g.setTransform(env.dpr, 0, 0, env.dpr, 0, 0);
        b.inst.draw(g, lt, p, env);
        g.globalAlpha = 1;
        g.globalCompositeOperation = "source-over";
        canvasDirty = true;
      }
    }

    const done = tt >= DURATION - 1e-4;
    css(barFill, { transform: `scaleX(${f(tt / DURATION, 4)})` });
    film.classList.toggle("film--done", done);
    if (replayBtn.hidden === done) replayBtn.hidden = !done;
    if (skipBtn.hidden !== done) skipBtn.hidden = done;
    if (pauseBtn.hidden !== done) pauseBtn.hidden = done;
  }

  /* ───────────── управление ───────────── */
  const barFill = h("i");
  const ICO_PAUSE = "M7 4h3.5v16H7zM13.5 4H17v16h-3.5z";
  const pausePath = svg("path", { d: ICO_PAUSE, fill: "currentColor" });
  const pauseBtn = h(
    "button",
    { type: "button", class: "film-btn film-btn-ico", "aria-label": "Пауза", onclick: () => (running() || want ? pause() : play()) },
    svg("svg", { viewBox: "0 0 24 24", "aria-hidden": "true", focusable: "false" }, pausePath)
  );
  const skipBtn = h("button", { type: "button", class: "film-btn", onclick: skip }, "Пропустить", h("span", { class: "film-btn-arr", "aria-hidden": "true", text: "→" }));
  const replayBtn = h("button", { type: "button", class: "film-btn", hidden: true, onclick: replay }, h("span", { "aria-hidden": "true", text: "↻" }), "Смотреть ещё раз");
  ui.replaceChildren(h("div", { class: "film-ctrl" }, pauseBtn, skipBtn, replayBtn), h("div", { class: "film-bar", "aria-hidden": "true" }, barFill));

  let time = 0;
  let want = false;
  let touched = false;
  let ready = false;
  let hidden = document.hidden;
  let offscreen = false;
  let raf = 0;
  let last = 0;
  const running = () => want && ready && !hidden && !offscreen;

  function syncUI() {
    const on = want;
    pauseBtn.setAttribute("aria-label", on ? "Пауза" : "Смотреть");
    pausePath.setAttribute("d", on ? ICO_PAUSE : ICONS.play);
  }
  function tick(now) {
    raf = 0;
    if (!running()) return;
    const dt = last ? Math.min(0.1, (now - last) / 1000) : 0;
    last = now;
    time = Math.min(DURATION, time + dt);
    render(time);
    if (time >= DURATION) {
      want = false;
      syncUI();
      return;
    }
    raf = requestAnimationFrame(tick);
  }
  function kick() {
    if (running()) {
      if (!raf) {
        last = 0;
        raf = requestAnimationFrame(tick);
      }
    } else if (raf) {
      cancelAnimationFrame(raf);
      raf = 0;
    }
    syncUI();
  }
  function seek(t) {
    touched = true;
    want = false;
    const v = Number(t);
    time = clamp(Number.isFinite(v) ? v : 0, 0, DURATION);
    render(time);
    kick();
  }
  function play() {
    touched = true;
    if (time >= DURATION) time = 0;
    want = true;
    render(time);
    kick();
  }
  function pause() {
    touched = true;
    want = false;
    kick();
  }
  function skip() {
    const hadFocus = document.activeElement === skipBtn;
    seek(DURATION);
    if (hadFocus) replayBtn.focus({ preventScroll: true });
  }
  function replay() {
    seek(0);
    play();
    if (document.activeElement === replayBtn || document.activeElement === document.body) skipBtn.focus({ preventScroll: true });
  }

  /* ───────────── размеры, шрифты, видимость ───────────── */
  let rz = 0;
  function onResize() {
    if (rz) return;
    rz = requestAnimationFrame(() => {
      rz = 0;
      const wasP = env.P;
      const oldKey = env.key;
      measureEnv();
      if (env.key === oldKey) return;
      sizeCanvas();
      if (wasP !== env.P) invalidate();
      canvasDirty = true;
      render(time);
    });
  }
  if ("ResizeObserver" in window) new ResizeObserver(onResize).observe(film);
  else window.addEventListener("resize", onResize);

  document.addEventListener("visibilitychange", () => {
    hidden = document.hidden;
    kick();
  });
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(
      (entries) => {
        for (const en of entries) offscreen = !en.isIntersecting || en.intersectionRatio < 0.3;
        kick();
      },
      { threshold: [0, 0.3, 0.6, 1] }
    ).observe(film);
  }
  const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
  const onMq = (ev) => {
    if (ev.matches) seek(DURATION);
  };
  if (mq.addEventListener) mq.addEventListener("change", onMq);

  const hashT = () => {
    const m = /^#t=(\d{1,3}(?:\.\d{1,4})?)$/.exec(location.hash);
    return m ? parseFloat(m[1]) : null;
  };
  window.addEventListener("hashchange", () => {
    const t = hashT();
    if (t !== null) seek(t);
  });

  measureEnv();
  sizeCanvas();
  const ht = hashT();
  if (ht !== null) seek(ht);
  else render(0);

  window.__film = Object.freeze({
    get duration() {
      return DURATION;
    },
    get time() {
      return time;
    },
    get playing() {
      return running();
    },
    scenes: Object.freeze(SCENES.map((s) => Object.freeze({ name: s.name, start: f(s.start, 3), end: f(s.end, 3) }))),
    seek,
    play,
    pause,
  });

  // Шрифты: запросить все сразу (лениво они грузятся только при показе), потом — старт.
  const SAMPLE = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя ABCDEFGHIJKLMNOPQRSTUVWXYZ abcxyz 0123456789 .,?!:%";
  const FONTS = [
    "900 64px Unbounded",
    "800 64px Unbounded",
    "700 64px Unbounded",
    "700 64px Oswald",
    "500 64px 'JetBrains Mono'",
    "700 64px 'JetBrains Mono'",
    "600 64px Inter",
    "italic 600 64px 'Cormorant Garamond'",
  ];
  const fontsDone = () => {
    fontGen++;
    measureEnv();
    canvasDirty = true;
    render(time);
  };
  const loads = document.fonts && document.fonts.load ? FONTS.map((fo) => document.fonts.load(fo, SAMPLE).catch(noop)) : [];
  if (document.fonts && document.fonts.addEventListener) document.fonts.addEventListener("loadingdone", fontsDone);
  Promise.race([Promise.all(loads), new Promise((r) => setTimeout(r, 2500))]).then(() => {
    fontsDone();
    ready = true;
    if (!touched) want = true;
    kick();
  });
})();

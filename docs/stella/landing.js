/* Стелла — лендинг под фильмом (владелец: landing.js / landing.css).
   Весь текст уже в HTML; этот файл только добавляет движение: появления при прокрутке (удар с размытием,
   сборка букв, растяжение, подъём по строкам, лазер-подчёркивание), липкую шапку, живой чат-пример,
   перекос бегущих строк от скорости прокрутки. Без innerHTML (Trusted Types), без внешних запросов. */
(function () {
  "use strict";

  const root = document.documentElement;
  const landing = document.getElementById("landing");
  if (!landing) return;

  const mq = (q) => (window.matchMedia ? window.matchMedia(q) : { matches: false });
  const reduced = mq("(prefers-reduced-motion: reduce)").matches;
  const hasIO = "IntersectionObserver" in window;
  const motion = !reduced && hasIO;

  root.classList.add("lp-js");
  if (motion) root.classList.add("lp-motion");

  const $ = (sel, ctx) => (ctx || document).querySelector(sel);
  const $$ = (sel, ctx) => Array.from((ctx || document).querySelectorAll(sel));
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  };
  const wait = (ms) => new Promise((res) => setTimeout(res, ms));

  // повторяемый «случай» для разлёта букв
  let seed = 20251019;
  const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;

  /* ───────── заголовки: номера строк, разбивка на буквы ───────── */

  const headings = $$(".lp-h2, .lp-mega", landing);

  function splitLetters(node, start) {
    let ci = start;
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
    const texts = [];
    while (walker.nextNode()) texts.push(walker.currentNode);
    for (const t of texts) {
      if (t.parentElement && t.parentElement.closest(".lp-laser")) continue;
      const frag = document.createDocumentFragment();
      for (const part of t.data.split(/(\s+)/)) {
        if (!part) continue;
        if (/^\s+$/.test(part)) {
          frag.append(" ");
          continue;
        }
        const w = el("span", "lp-w");
        for (const ch of part) {
          const c = el("span", "lp-ch", ch);
          c.style.setProperty("--ci", String(ci++));
          c.style.setProperty("--rx", (rnd() * 2 - 1).toFixed(2));
          c.style.setProperty("--ry", (rnd() * 2 - 1).toFixed(2));
          w.append(c);
        }
        frag.append(w);
      }
      t.replaceWith(frag);
    }
    return ci;
  }

  for (const hd of headings) {
    const lines = $$(":scope > .lp-line", hd);
    lines.forEach((ln, i) => ln.style.setProperty("--li", String(i)));
    if (motion && hd.dataset.fx === "letters") {
      // экранным чтилкам — цельный текст, глазам — буквы
      const clone = hd.cloneNode(true);
      for (const n of $$('[aria-hidden="true"]', clone)) n.remove();
      const label = clone.textContent.replace(/\s+/g, " ").trim();
      let ci = 0;
      for (const ln of lines) {
        ci = splitLetters(ln, ci);
        ln.setAttribute("aria-hidden", "true");
      }
      hd.append(el("span", "sr-only", label));
    }
  }

  /* ───────── подгонка строк под ширину (страховка поверх CSS cqi) ───────── */

  function fit() {
    for (const hd of headings) {
      const box = hd.clientWidth;
      if (!box) continue;
      const lines = $$(":scope > .lp-line", hd);
      const uniform = hd.classList.contains("lp-stack") || hd.classList.contains("lp-ask");
      for (const ln of lines) ln.style.fontSize = "";
      const ratios = lines.map((ln) => {
        const w = ln.offsetWidth;
        return w > box ? (box / w) * 0.995 : 1;
      });
      const minR = Math.min(1, ...ratios);
      lines.forEach((ln, i) => {
        const r = uniform ? minR : ratios[i];
        if (r < 1) ln.style.fontSize = (parseFloat(getComputedStyle(ln).fontSize) * r).toFixed(2) + "px";
      });
    }
  }

  fit();
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(fit);
  let fitTimer = 0;
  window.addEventListener("resize", () => {
    clearTimeout(fitTimer);
    fitTimer = setTimeout(fit, 120);
  });

  /* ───────── появления при прокрутке ───────── */

  if (motion) {
    const io = new IntersectionObserver(
      (entries) => {
        const hits = entries
          .filter((e) => e.isIntersecting)
          .map((e) => ({ t: e.target, r: e.boundingClientRect }))
          .sort((a, b) => a.r.top - b.r.top || a.r.left - b.r.left);
        hits.forEach(({ t }, i) => {
          io.unobserve(t);
          if (t.hasAttribute("data-reveal")) t.style.setProperty("--d", Math.min(i, 7) * 85 + "ms");
          t.classList.add("is-in");
        });
      },
      { rootMargin: "0px 0px -6% 0px", threshold: 0.12 }
    );
    for (const n of $$("[data-fx], [data-reveal]", landing)) io.observe(n);

    landing.addEventListener("animationend", (e) => {
      const t = e.target;
      if (e.animationName === "lp-card-in" && t.hasAttribute && t.hasAttribute("data-reveal")) t.classList.add("is-done");
    });
  }

  // «живые» разделы: петли крутятся только на экране
  if (hasIO) {
    const live = new IntersectionObserver(
      (entries) => {
        for (const e of entries) e.target.classList.toggle("is-live", e.isIntersecting);
      },
      { rootMargin: "80px 0px" }
    );
    for (const s of $$(".lp-sec, .lp-marq", landing)) live.observe(s);
  } else {
    for (const s of $$(".lp-sec, .lp-marq", landing)) s.classList.add("is-live");
  }

  /* ───────── шапка, прогресс, дрейф, перекос строк ───────── */

  const bar = $("#lp-bar");
  const laser = bar && $(".lp-bar__laser", bar);
  const film = document.getElementById("film");
  const drifts = motion ? $$("[data-drift]", landing) : [];
  const skews = motion ? $$(".lp-tape__skew", landing) : [];
  const marq = $(".lp-marq", landing);

  let ticking = false;
  let lastY = window.scrollY;
  let lastT = performance.now();
  let skew = 0;
  let skewTarget = 0;
  let skewRaf = 0;

  function stepSkew() {
    skew += (skewTarget - skew) * 0.2;
    skewTarget *= 0.85;
    if (Math.abs(skew) < 0.05 && Math.abs(skewTarget) < 0.05) {
      skew = 0;
      for (const s of skews) s.style.transform = "";
      skewRaf = 0;
      return;
    }
    for (const s of skews) s.style.transform = "skewX(" + (-skew).toFixed(2) + "deg)";
    skewRaf = requestAnimationFrame(stepSkew);
  }

  function frame(now) {
    ticking = false;
    const y = window.scrollY;
    const vh = window.innerHeight;
    if (bar) {
      const filmEnd = film ? film.offsetTop + film.offsetHeight : vh;
      bar.classList.toggle("is-on", y > filmEnd - 80);
      if (laser) {
        const max = root.scrollHeight - vh;
        laser.style.transform = "scaleX(" + (max > 0 ? Math.min(1, Math.max(0, y / max)) : 0).toFixed(4) + ")";
      }
    }
    for (const d of drifts) {
      const r = d.parentElement.getBoundingClientRect();
      if (r.bottom < -100 || r.top > vh + 100) continue;
      const k = parseFloat(d.dataset.drift) || 0;
      d.style.transform = "translate3d(" + ((r.top + r.height / 2 - vh / 2) * k).toFixed(1) + "px,0,0)";
    }
    const dt = Math.max(8, now - lastT);
    const v = (y - lastY) / dt;
    lastY = y;
    lastT = now;
    if (skews.length && marq && marq.classList.contains("is-live")) {
      skewTarget = Math.max(-14, Math.min(14, v * 7));
      if (!skewRaf) skewRaf = requestAnimationFrame(stepSkew);
    }
  }

  function onScroll() {
    if (!ticking) {
      ticking = true;
      requestAnimationFrame(frame);
    }
  }

  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll, { passive: true });
  requestAnimationFrame(frame);

  /* ───────── свечение карточек за пальцем/курсором ───────── */

  if (mq("(hover: hover)").matches) {
    landing.addEventListener(
      "pointermove",
      (e) => {
        const card = e.target instanceof Element ? e.target.closest(".lp-card") : null;
        if (!card) return;
        const r = card.getBoundingClientRect();
        card.style.setProperty("--mx", (e.clientX - r.left).toFixed(0) + "px");
        card.style.setProperty("--my", (e.clientY - r.top).toFixed(0) + "px");
      },
      { passive: true }
    );
  }

  /* ───────── FAQ: мягкое раскрытие ───────── */

  if (motion && Element.prototype.animate) {
    for (const d of $$(".lp-q", landing)) {
      d.addEventListener("toggle", () => {
        if (!d.open) return;
        const a = $(".lp-q__a", d);
        if (a)
          a.animate(
            [
              { opacity: 0, transform: "translateY(-10px)", filter: "blur(4px)" },
              { opacity: 1, transform: "none", filter: "none" },
            ],
            { duration: 460, easing: "cubic-bezier(0.16, 1, 0.3, 1)" }
          );
      });
    }
  }

  /* ───────── живой чат ───────── */

  const tg = $("#tg");
  if (tg && motion) initChat(tg);

  function initChat(box) {
    const feed = $(".tg-feed", box);
    const status = $(".tg-status", box);
    const field = $(".tg-field", box);
    const typed = $(".tg-typed", box);
    const send = $(".tg-send", box);
    const figure = box.closest(".lp-vf");
    const tc = figure && $(".lp-vf__tc", figure);
    const steps = $$(":scope > [data-step]", feed);
    if (!feed || !steps.length) return;
    const idle = (status && status.dataset.idle) || (status && status.textContent) || "";

    const replay = el("button", "tg-replay", "↻ Ещё раз");
    replay.type = "button";
    replay.hidden = true;
    replay.setAttribute("aria-label", "Показать переписку ещё раз");
    if (figure) figure.append(replay);

    let run = 0;
    let clock = 0;

    function setStatus(text, typing) {
      if (!status) return;
      status.textContent = text;
      status.classList.toggle("is-typing", !!typing);
    }

    function startClock() {
      const t0 = performance.now();
      clearInterval(clock);
      if (!tc) return;
      const pad = (n) => String(n).padStart(2, "0");
      clock = setInterval(() => {
        const ms = performance.now() - t0;
        const s = Math.floor(ms / 1000);
        tc.textContent = pad(Math.floor(s / 60)) + ":" + pad(s % 60) + ":" + pad(Math.floor((ms % 1000) / 40));
      }, 80);
    }

    // FLIP: лента прижата к низу; когда она растёт, плавно «подъезжает» вверх
    function flip(mutate) {
      const before = feed.getBoundingClientRect().top;
      mutate();
      const dy = before - feed.getBoundingClientRect().top;
      if (dy && feed.animate) {
        feed.animate([{ transform: "translateY(" + dy + "px)" }, { transform: "none" }], {
          duration: 420,
          easing: "cubic-bezier(0.16, 1, 0.3, 1)",
        });
      }
    }

    function typingBubble() {
      const li = el("li", "tg-msg tg-in tg-last tg-typing");
      li.setAttribute("aria-hidden", "true");
      const av = el("span", "tg-ava tg-ava--st", "✦");
      const b = el("p", "tg-b");
      b.append(el("i"), el("i"), el("i"));
      li.append(av, b);
      return li;
    }

    async function typeInto(text, id) {
      if (!field || !typed) return id === run;
      field.classList.add("is-typing");
      const chars = Array.from(text);
      const step = Math.max(16, Math.min(42, 1100 / chars.length));
      for (let i = 1; i <= chars.length; i++) {
        typed.textContent = chars.slice(0, i).join("");
        await wait(step);
        if (id !== run) return false;
      }
      await wait(240);
      if (send) send.classList.add("is-press");
      await wait(170);
      if (send) send.classList.remove("is-press");
      typed.textContent = "";
      field.classList.remove("is-typing");
      return id === run;
    }

    function reset() {
      for (const li of steps) li.classList.remove("is-shown");
      for (const n of $$(".tg-typing", feed)) n.remove();
      if (typed) typed.textContent = "";
      if (field) field.classList.remove("is-typing");
      setStatus(idle, false);
      replay.hidden = true;
    }

    async function play() {
      const id = ++run;
      reset();
      startClock();
      await wait(500);
      for (const li of steps) {
        if (id !== run) return;
        const kind = li.dataset.step;
        if (kind === "me") {
          const t = $(".tg-t", li);
          if (!(await typeInto(t ? t.textContent : "", id))) return;
          flip(() => li.classList.add("is-shown"));
          await wait(520);
        } else if (kind === "st") {
          const ms = Number(li.dataset.typing) || 0;
          if (ms > 0) {
            const bubble = typingBubble();
            flip(() => li.before(bubble));
            setStatus("Стелла печатает…", true);
            await wait(ms);
            if (id !== run) return;
            flip(() => {
              bubble.remove();
              li.classList.add("is-shown");
            });
            setStatus(idle, false);
          } else {
            flip(() => li.classList.add("is-shown"));
          }
          await wait(420);
        } else {
          flip(() => li.classList.add("is-shown"));
          await wait(kind === "sys" ? 900 : 600);
        }
      }
      clearInterval(clock);
      if (id === run) replay.hidden = false;
    }

    replay.addEventListener("click", () => {
      play();
    });

    const once = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          once.disconnect();
          play();
        }
      },
      { threshold: 0.3 }
    );
    once.observe(box);
  }
})();

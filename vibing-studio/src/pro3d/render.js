// Builds a complete, self-contained HTML site from a template spec:
// { template, palette, font, brand, hero, stats, features, showcase, steps, testimonials, pricing, faq, cta, contact, footer, sections }.
// The AI only fills the spec (texts + colours); layout, animation and 3D come from here.
import { normalizePalette } from "./palette.js";
import { SCENES, THREE_ADDONS_URL, THREE_URL } from "./scenes.js";
import { TEMPLATES_3D, templateById } from "./templates3d.js";

export const LUCIDE_URL = "https://unpkg.com/lucide@0.460.0/dist/umd/lucide.min.js";

export const ICONS = [
  "sparkles", "zap", "shield-check", "rocket", "cpu", "globe", "heart", "star", "coffee", "camera", "music", "code", "layers",
  "chart-column", "users", "clock", "check", "lock", "cloud", "smartphone", "palette", "leaf", "gem", "truck", "map-pin", "phone",
  "mail", "award", "target", "trending-up", "brain", "wand-sparkles", "dumbbell", "stethoscope", "graduation-cap", "building-2",
  "house", "shopping-bag", "utensils", "scissors", "plane", "sun", "moon", "flame", "wifi", "headphones", "book-open", "briefcase",
  "gift", "infinity", "activity", "bot", "database", "fingerprint", "heart-pulse", "pill", "microscope", "car", "wrench", "hammer",
  "paintbrush", "shirt", "baby", "paw-print", "calendar", "message-circle", "handshake", "wallet", "credit-card", "bitcoin",
  "chart-line", "package", "store", "hotel", "mountain", "waves", "film", "gamepad-2", "mic", "lightbulb", "settings", "gauge", "timer",
];

/** Display/body font pairs with Cyrillic support (Google Fonts). */
export const FONTS = {
  unbounded: { name: "Unbounded + Manrope", head: "Unbounded", body: "Manrope", q: "family=Unbounded:wght@400;600;800&family=Manrope:wght@400;500;700" },
  manrope: { name: "Manrope", head: "Manrope", body: "Manrope", q: "family=Manrope:wght@400;500;700;800" },
  playfair: { name: "Playfair Display + Inter", head: "Playfair Display", body: "Inter", q: "family=Playfair+Display:ital,wght@0,500;0,700;1,500&family=Inter:wght@400;500;700" },
  cormorant: { name: "Cormorant + Manrope", head: "Cormorant Garamond", body: "Manrope", q: "family=Cormorant+Garamond:ital,wght@0,500;0,700;1,500&family=Manrope:wght@400;500;700" },
  onest: { name: "Onest", head: "Onest", body: "Onest", q: "family=Onest:wght@400;500;700;800" },
  rubik: { name: "Rubik", head: "Rubik", body: "Rubik", q: "family=Rubik:wght@400;500;700;800" },
  exo: { name: "Exo 2 + Inter", head: "Exo 2", body: "Inter", q: "family=Exo+2:wght@500;700;800&family=Inter:wght@400;500;700" },
  oswald: { name: "Oswald + Inter", head: "Oswald", body: "Inter", q: "family=Oswald:wght@500;600;700&family=Inter:wght@400;500;700" },
  comfortaa: { name: "Comfortaa + Nunito", head: "Comfortaa", body: "Nunito", q: "family=Comfortaa:wght@500;700&family=Nunito:wght@400;600;700" },
  mono: { name: "JetBrains Mono + Inter", head: "JetBrains Mono", body: "Inter", q: "family=JetBrains+Mono:wght@500;700;800&family=Inter:wght@400;500;700" },
  prata: { name: "Prata + Manrope", head: "Prata", body: "Manrope", q: "family=Prata&family=Manrope:wght@400;500;700" },
  montserrat: { name: "Montserrat + Inter", head: "Montserrat", body: "Inter", q: "family=Montserrat:wght@500;700;800&family=Inter:wght@400;500;700" },
};

export const SECTION_IDS = ["stats", "features", "showcase", "steps", "testimonials", "pricing", "faq", "cta", "contact"];
const NAV_LABEL = { features: "Возможности", showcase: "Работы", steps: "Как это работает", testimonials: "Отзывы", pricing: "Цены", faq: "Вопросы", contact: "Контакты" };

const esc = (v) => String(v ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const str = (v, max = 400) => (typeof v === "string" ? v.trim().slice(0, max) : typeof v === "number" ? String(v) : "");
const arr = (v, max = 12) => (Array.isArray(v) ? v.slice(0, max) : []);
const icon = (name) => (ICONS.includes(String(name)) ? String(name) : "sparkles");

/** Make a model- or user-provided spec safe and complete. Unknown templates fall back to the first one. */
export function normalizeSpec(input, { demo = true } = {}) {
  const s = input && typeof input === "object" ? input : {};
  const tpl = templateById(s.template) || TEMPLATES_3D[0];
  const d = tpl.demo;
  const pick = (key) => (s[key] !== undefined ? s[key] : demo ? d[key] : undefined);
  const hero = { ...(demo ? d.hero : {}), ...(s.hero && typeof s.hero === "object" ? s.hero : {}) };
  const secSrc = Array.isArray(s.sections) ? s.sections : demo && Array.isArray(d.sections) ? d.sections : null;
  const sectionsIn = secSrc ? secSrc.filter((x) => SECTION_IDS.includes(x)) : null;
  const spec = {
    template: tpl.id,
    font: FONTS[s.font] ? s.font : tpl.font,
    palette: normalizePalette(s.palette, tpl.palette),
    lang: str(s.lang, 5) || "ru",
    brand: str(pick("brand"), 40) || "Brand",
    hero: {
      eyebrow: str(hero.eyebrow, 80),
      title: str(hero.title, 140) || str(pick("brand"), 40),
      highlight: str(hero.highlight, 60),
      subtitle: str(hero.subtitle, 320),
      cta: str(hero.cta, 40) || "Начать",
      cta2: str(hero.cta2, 40),
    },
    stats: arr(pick("stats"), 4).map((x) => ({ value: str(x?.value, 16), label: str(x?.label, 60) })).filter((x) => x.value),
    features: section(pick("features"), (x) => ({ icon: icon(x?.icon), title: str(x?.title, 70), text: str(x?.text, 240) }), 6),
    showcase: section(pick("showcase"), (x) => ({ title: str(x?.title, 70), text: str(x?.text, 200), tag: str(x?.tag, 30) }), 6),
    steps: section(pick("steps"), (x) => ({ title: str(x?.title, 70), text: str(x?.text, 220) }), 5),
    testimonials: section(pick("testimonials"), (x) => ({ quote: str(x?.quote, 320), name: str(x?.name, 50), role: str(x?.role, 60) }), 3),
    pricing: (() => {
      const p = pick("pricing");
      if (!p || typeof p !== "object") return null;
      const plans = arr(p.plans, 3).map((x) => ({ name: str(x?.name, 30), price: str(x?.price, 20), period: str(x?.period, 20), features: arr(x?.features, 7).map((f) => str(f, 80)).filter(Boolean), cta: str(x?.cta, 30) || "Выбрать", featured: !!x?.featured }));
      return plans.length ? { title: str(p.title, 80), subtitle: str(p.subtitle, 200), plans } : null;
    })(),
    faq: section(pick("faq"), (x) => ({ q: str(x?.q, 160), a: str(x?.a, 500) }), 6),
    cta: (() => {
      const c = pick("cta");
      return c && typeof c === "object" ? { title: str(c.title, 120), text: str(c.text, 240), button: str(c.button, 40) || "Связаться" } : null;
    })(),
    contact: (() => {
      const c = pick("contact");
      return c && typeof c === "object" ? { title: str(c.title, 80) || "Контакты", email: str(c.email, 80), phone: str(c.phone, 40), address: str(c.address, 160), hours: str(c.hours, 80) } : null;
    })(),
    footer: { text: str((pick("footer") || {}).text, 160) },
  };
  spec.sections = (sectionsIn && sectionsIn.length ? sectionsIn : tpl.sections).filter((id) => hasContent(spec, id));
  return spec;
}

function section(v, mapItem, max) {
  if (!v || typeof v !== "object") return null;
  const items = arr(v.items, max).map(mapItem).filter((x) => Object.values(x).some((y) => y));
  return items.length ? { title: str(v.title, 90), subtitle: str(v.subtitle, 240), text: str(v.text, 300), items } : null;
}

function hasContent(spec, id) {
  if (id === "stats") return spec.stats.length > 0;
  return !!spec[id];
}

function titleHtml(title, highlight) {
  const t = esc(title);
  const h = esc(highlight);
  if (h && t.includes(h)) return t.replace(h, `<span class="hl">${h}</span>`);
  return t;
}

const head = (s, id) => (s.title || s.subtitle ? `<div class="sec-head reveal">${s.title ? `<h2>${esc(s.title)}</h2>` : ""}${s.subtitle ? `<p>${esc(s.subtitle)}</p>` : ""}</div>` : "") + (id ? "" : "");

function renderSection(spec, id, tpl) {
  const card = `card card-${tpl.cards}`;
  switch (id) {
    case "stats":
      return `<section class="stats" id="stats"><div class="wrap stats-row">${spec.stats
        .map((x, i) => `<div class="stat reveal" style="--d:${i * 80}ms"><b data-count="${esc(x.value)}">${esc(x.value)}</b><span>${esc(x.label)}</span></div>`)
        .join("")}</div></section>`;
    case "features": {
      const f = spec.features;
      return `<section id="features"><div class="wrap">${head(f)}<div class="grid ${tpl.features === "bento" ? "bento" : "grid-3"}">${f.items
        .map((x, i) => `<article class="${card} tilt reveal" style="--d:${i * 70}ms"><div class="ico"><i data-lucide="${x.icon}"></i></div><h3>${esc(x.title)}</h3><p>${esc(x.text)}</p></article>`)
        .join("")}</div></div></section>`;
    }
    case "showcase": {
      const s = spec.showcase;
      return `<section id="showcase"><div class="wrap">${head(s)}${s.text ? `<p class="lead reveal">${esc(s.text)}</p>` : ""}<div class="grid grid-3">${s.items
        .map((x, i) => `<article class="show tilt reveal" style="--d:${i * 90}ms;--h:${(i * 47) % 360}deg"><div class="show-art"><span></span><span></span><span></span></div><div class="show-body">${x.tag ? `<em>${esc(x.tag)}</em>` : ""}<h3>${esc(x.title)}</h3><p>${esc(x.text)}</p></div></article>`)
        .join("")}</div></div></section>`;
    }
    case "steps": {
      const s = spec.steps;
      return `<section id="steps"><div class="wrap">${head(s)}<ol class="steps">${s.items
        .map((x, i) => `<li class="${card} reveal" style="--d:${i * 90}ms"><span class="num">${String(i + 1).padStart(2, "0")}</span><h3>${esc(x.title)}</h3><p>${esc(x.text)}</p></li>`)
        .join("")}</ol></div></section>`;
    }
    case "testimonials": {
      const s = spec.testimonials;
      return `<section id="testimonials"><div class="wrap">${head(s)}<div class="grid grid-3">${s.items
        .map((x, i) => `<figure class="${card} quote reveal" style="--d:${i * 90}ms"><i data-lucide="quote" class="q"></i><blockquote>${esc(x.quote)}</blockquote><figcaption><span class="ava">${esc((x.name || "?").slice(0, 1))}</span><span><b>${esc(x.name)}</b><small>${esc(x.role)}</small></span></figcaption></figure>`)
        .join("")}</div></div></section>`;
    }
    case "pricing": {
      const p = spec.pricing;
      return `<section id="pricing"><div class="wrap">${head(p)}<div class="grid grid-${Math.min(3, p.plans.length)} prices">${p.plans
        .map((x, i) => `<div class="${card} price ${x.featured ? "featured" : ""} tilt reveal" style="--d:${i * 90}ms">${x.featured ? '<span class="badge">Популярный</span>' : ""}<h3>${esc(x.name)}</h3><div class="amount"><b>${esc(x.price)}</b>${x.period ? `<span>${esc(x.period)}</span>` : ""}</div><ul>${x.features.map((f) => `<li><i data-lucide="check"></i>${esc(f)}</li>`).join("")}</ul><a href="#contact" class="btn ${x.featured ? "btn-primary" : "btn-ghost"} magnetic">${esc(x.cta)}</a></div>`)
        .join("")}</div></div></section>`;
    }
    case "faq": {
      const f = spec.faq;
      return `<section id="faq"><div class="wrap narrow">${head(f)}<div class="faq">${f.items
        .map((x, i) => `<details class="${card} reveal" style="--d:${i * 60}ms"><summary>${esc(x.q)}<i data-lucide="plus"></i></summary><p>${esc(x.a)}</p></details>`)
        .join("")}</div></div></section>`;
    }
    case "cta": {
      const c = spec.cta;
      return `<section class="cta-sec"><div class="wrap"><div class="cta-box reveal"><div class="cta-glow"></div><h2>${esc(c.title)}</h2>${c.text ? `<p>${esc(c.text)}</p>` : ""}<a href="#contact" class="btn btn-primary btn-lg magnetic">${esc(c.button)}<i data-lucide="arrow-right"></i></a></div></div></section>`;
    }
    case "contact": {
      const c = spec.contact;
      const rows = [
        c.phone && `<a href="tel:${esc(c.phone.replace(/[^\d+]/g, ""))}"><i data-lucide="phone"></i>${esc(c.phone)}</a>`,
        c.email && `<a href="mailto:${esc(c.email)}"><i data-lucide="mail"></i>${esc(c.email)}</a>`,
        c.address && `<span><i data-lucide="map-pin"></i>${esc(c.address)}</span>`,
        c.hours && `<span><i data-lucide="clock"></i>${esc(c.hours)}</span>`,
      ].filter(Boolean);
      return `<section id="contact"><div class="wrap contact"><div class="reveal"><h2>${esc(c.title)}</h2><div class="contact-rows">${rows.join("")}</div></div><form class="${card} form reveal" onsubmit="event.preventDefault();this.classList.add('sent')"><label>Имя<input required placeholder="Как к вам обращаться"></label><label>Телефон или e-mail<input required placeholder="+7 … или mail@…"></label><label>Сообщение<textarea rows="3" placeholder="Коротко о задаче"></textarea></label><button class="btn btn-primary magnetic" type="submit">Отправить</button><div class="sent-msg"><i data-lucide="check"></i>Спасибо! Мы свяжемся с вами.</div></form></div></section>`;
    }
    default:
      return "";
  }
}

function css(tpl, p, f) {
  const r = tpl.radius;
  return `
:root{--bg:${p.bg};--surface:${p.surface};--text:${p.text};--muted:${p.muted};--accent:${p.accent};--accent2:${p.accent2};--on-accent:${p.onAccent};
--line:color-mix(in srgb,var(--text) 12%,transparent);--glass:color-mix(in srgb,var(--surface) 72%,transparent);--r:${r}px;
--fh:'${f.head}',system-ui,sans-serif;--fb:'${f.body}',system-ui,sans-serif;color-scheme:${p.light ? "light" : "dark"}}
*{box-sizing:border-box;margin:0;padding:0}html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--text);font:16px/1.65 var(--fb);overflow-x:hidden;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}img{max-width:100%}
h1,h2,h3{font-family:var(--fh);line-height:1.08;letter-spacing:${tpl.tracking}}
.wrap{width:min(1180px,100% - 40px);margin:0 auto}.narrow{width:min(820px,100% - 40px)}
section{padding:110px 0;position:relative}
.noise{position:fixed;inset:0;pointer-events:none;z-index:100;opacity:${p.light ? 0.035 : 0.05};background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence baseFrequency='.85' numOctaves='3'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")}
.cursor-glow{position:fixed;width:520px;height:520px;border-radius:50%;pointer-events:none;z-index:0;transform:translate(-50%,-50%);background:radial-gradient(circle,color-mix(in srgb,var(--accent) 16%,transparent),transparent 65%);transition:opacity .3s;opacity:0}
body:hover .cursor-glow{opacity:1}
/* nav */
.nav{position:fixed;top:14px;left:50%;transform:translateX(-50%);z-index:50;width:min(1180px,100% - 28px);display:flex;align-items:center;gap:22px;padding:12px 14px 12px 20px;border-radius:999px;border:1px solid var(--line);background:color-mix(in srgb,var(--bg) 55%,transparent);backdrop-filter:blur(18px) saturate(160%);-webkit-backdrop-filter:blur(18px) saturate(160%);transition:background .3s,box-shadow .3s}
.nav.scrolled{background:color-mix(in srgb,var(--bg) 82%,transparent);box-shadow:0 12px 40px -18px rgba(0,0,0,.45)}
.logo{font:800 19px/1 var(--fh);display:flex;align-items:center;gap:10px;white-space:nowrap}
.logo i{width:30px;height:30px;border-radius:10px;display:grid;place-items:center;background:linear-gradient(135deg,var(--accent),var(--accent2));box-shadow:0 0 24px -4px var(--accent)}
.logo i:after{content:"";width:10px;height:10px;border-radius:3px;background:var(--on-accent);transform:rotate(45deg)}
.links{display:flex;gap:4px;margin-left:auto}.links a{padding:8px 14px;border-radius:999px;color:var(--muted);font-size:14.5px;transition:.2s}.links a:hover{color:var(--text);background:var(--line)}
.burger{display:none;margin-left:auto;background:none;border:0;color:var(--text);cursor:pointer}
/* buttons */
.btn{display:inline-flex;align-items:center;justify-content:center;gap:9px;padding:13px 24px;border-radius:999px;font:600 15px/1 var(--fb);cursor:pointer;border:1px solid transparent;transition:transform .25s cubic-bezier(.2,.8,.2,1),box-shadow .3s,background .3s;will-change:transform}
.btn svg{width:18px;height:18px}
.btn-primary{background:linear-gradient(135deg,var(--accent),color-mix(in srgb,var(--accent) 55%,var(--accent2)));color:var(--on-accent);box-shadow:0 10px 34px -10px var(--accent)}
.btn-primary:hover{box-shadow:0 16px 48px -10px var(--accent)}
.btn-ghost{background:var(--glass);border-color:var(--line);color:var(--text);backdrop-filter:blur(10px)}.btn-ghost:hover{border-color:color-mix(in srgb,var(--accent) 60%,transparent)}
.btn-lg{padding:17px 32px;font-size:16.5px}.nav .btn{padding:10px 18px;font-size:14px}
/* hero */
.hero{min-height:100svh;display:flex;align-items:${tpl.hero === "bottom" ? "flex-end" : "center"};padding:140px 0 90px;overflow:hidden;isolation:isolate}
.hero canvas{position:absolute;inset:0;width:100%;height:100%;z-index:-2}
.hero:before{content:"";position:absolute;inset:0;z-index:-3;background:radial-gradient(60% 60% at 70% 40%,color-mix(in srgb,var(--accent) 35%,transparent),transparent 70%),radial-gradient(50% 50% at 20% 80%,color-mix(in srgb,var(--accent2) 25%,transparent),transparent 70%)}
.hero:after{content:"";position:absolute;inset:0;z-index:-1;pointer-events:none;background:${tpl.hero === "split" ? "linear-gradient(90deg,var(--bg) 18%,color-mix(in srgb,var(--bg) 40%,transparent) 55%,transparent)" : tpl.hero === "bottom" ? "linear-gradient(0deg,var(--bg) 5%,transparent 60%)" : "radial-gradient(70% 60% at 50% 50%,color-mix(in srgb,var(--bg) 55%,transparent),transparent 80%)"},linear-gradient(0deg,var(--bg),transparent 22%)}
.hero-inner{${tpl.hero === "center" ? "text-align:center;margin:0 auto;max-width:900px" : "max-width:640px"}}
.eyebrow{display:inline-flex;align-items:center;gap:8px;padding:7px 14px;border-radius:999px;border:1px solid var(--line);background:var(--glass);backdrop-filter:blur(10px);font-size:13px;color:var(--muted);margin-bottom:26px}
.eyebrow:before{content:"";width:7px;height:7px;border-radius:50%;background:var(--accent2);box-shadow:0 0 12px var(--accent2);animation:pulse 2s infinite}
@keyframes pulse{50%{opacity:.35}}
.hero h1{font-size:clamp(40px,${tpl.heroSize}vw,${tpl.heroMax}px);font-weight:${tpl.weight};margin-bottom:24px;${tpl.upper ? "text-transform:uppercase;" : ""}}
.hl{background:linear-gradient(100deg,var(--accent),var(--accent2) 60%,var(--accent));background-size:200% auto;-webkit-background-clip:text;background-clip:text;color:transparent;animation:shine 6s linear infinite;${tpl.italic ? "font-style:italic;" : ""}}
@keyframes shine{to{background-position:200% center}}
.hero p.sub{font-size:clamp(17px,1.5vw,20px);color:var(--muted);max-width:620px;${tpl.hero === "center" ? "margin:0 auto 36px" : "margin-bottom:36px"}}
.hero-ctas{display:flex;gap:12px;flex-wrap:wrap;${tpl.hero === "center" ? "justify-content:center" : ""}}
.scroll-hint{position:absolute;left:50%;bottom:26px;width:24px;height:38px;border:2px solid var(--line);border-radius:14px;transform:translateX(-50%)}
.scroll-hint:after{content:"";position:absolute;left:50%;top:7px;width:4px;height:8px;border-radius:2px;background:var(--text);transform:translateX(-50%);animation:wheel 1.6s infinite}
@keyframes wheel{to{transform:translate(-50%,12px);opacity:0}}
/* sections */
.sec-head{max-width:720px;margin:0 auto 56px;text-align:center}.sec-head h2,.contact h2{font-size:clamp(32px,4vw,54px);font-weight:${tpl.weight};margin-bottom:16px}.sec-head p,.lead{color:var(--muted);font-size:18px}
.lead{text-align:center;max-width:680px;margin:-30px auto 48px}
.grid{display:grid;gap:20px}.grid-3{grid-template-columns:repeat(auto-fit,minmax(270px,1fr))}.grid-2{grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}.grid-1{grid-template-columns:minmax(0,440px);justify-content:center}
.bento{grid-template-columns:repeat(6,1fr)}.bento>*:nth-child(1){grid-column:span 4}.bento>*:nth-child(2){grid-column:span 2}.bento>*:nth-child(3),.bento>*:nth-child(4),.bento>*:nth-child(5){grid-column:span 2}.bento>*:nth-child(6){grid-column:span 6}
.card{position:relative;padding:30px;border-radius:var(--r);transition:transform .35s cubic-bezier(.2,.8,.2,1),border-color .3s,box-shadow .3s;transform-style:preserve-3d}
.card-glass{background:var(--glass);border:1px solid var(--line);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px)}
.card-solid{background:var(--surface);border:1px solid var(--line);box-shadow:0 20px 50px -30px rgba(0,0,0,.5)}
.card-outline{background:transparent;border:1px solid color-mix(in srgb,var(--text) 22%,transparent)}
.card:hover{border-color:color-mix(in srgb,var(--accent) 55%,transparent);box-shadow:0 30px 70px -35px color-mix(in srgb,var(--accent) 80%,transparent)}
.card:before{content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;background:radial-gradient(400px circle at var(--mx,50%) var(--my,0%),color-mix(in srgb,var(--accent) 14%,transparent),transparent 45%);opacity:0;transition:opacity .3s}.card:hover:before{opacity:1}
.ico{width:50px;height:50px;border-radius:14px;display:grid;place-items:center;margin-bottom:22px;background:linear-gradient(135deg,color-mix(in srgb,var(--accent) 22%,transparent),color-mix(in srgb,var(--accent2) 14%,transparent));border:1px solid color-mix(in srgb,var(--accent) 35%,transparent);color:var(--accent2);transform:translateZ(30px)}
.ico svg{width:24px;height:24px}
.card h3{font-size:21px;margin-bottom:10px;transform:translateZ(20px)}.card p{color:var(--muted)}
.stats{padding:30px 0 60px}.stats-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:20px;padding:34px;border-radius:var(--r);border:1px solid var(--line);background:var(--glass);backdrop-filter:blur(14px)}
.stat{text-align:center}.stat b{display:block;font:800 clamp(34px,4vw,50px)/1.1 var(--fh);background:linear-gradient(135deg,var(--text),var(--accent2));-webkit-background-clip:text;background-clip:text;color:transparent}.stat span{color:var(--muted);font-size:14.5px}
.show{border-radius:var(--r);overflow:hidden;border:1px solid var(--line);background:var(--surface);transition:transform .35s cubic-bezier(.2,.8,.2,1),box-shadow .3s}
.show:hover{box-shadow:0 30px 70px -35px var(--accent)}
.show-art{height:230px;position:relative;overflow:hidden;background:linear-gradient(135deg,color-mix(in srgb,var(--accent) 70%,var(--bg)),color-mix(in srgb,var(--accent2) 60%,var(--bg)));filter:hue-rotate(var(--h))}
.show-art span{position:absolute;border-radius:50%;filter:blur(2px);background:color-mix(in srgb,var(--text) 18%,transparent);animation:float 9s ease-in-out infinite}
.show-art span:nth-child(1){width:180px;height:180px;left:-30px;top:-40px}.show-art span:nth-child(2){width:120px;height:120px;right:20px;bottom:-30px;animation-delay:-3s;border-radius:28px;transform:rotate(25deg)}.show-art span:nth-child(3){width:60px;height:60px;left:45%;top:40%;animation-delay:-6s;background:color-mix(in srgb,var(--bg) 45%,transparent)}
@keyframes float{50%{translate:0 -16px;rotate:12deg}}
.show-body{padding:24px}.show-body em{font-style:normal;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--accent2)}.show-body h3{font-size:21px;margin:6px 0 8px}.show-body p{color:var(--muted)}
.steps{list-style:none;display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:20px;counter-reset:s}
.num{display:inline-block;font:800 15px/1 var(--fh);color:var(--accent2);padding:8px 12px;border-radius:999px;border:1px solid color-mix(in srgb,var(--accent2) 40%,transparent);margin-bottom:18px}
.quote blockquote{font-size:17px;margin:12px 0 22px;color:var(--text)}.quote .q{color:var(--accent);width:28px;height:28px}
.quote figcaption{display:flex;align-items:center;gap:12px}.quote small{display:block;color:var(--muted)}
.ava{width:42px;height:42px;border-radius:50%;display:grid;place-items:center;font-weight:700;color:var(--on-accent);background:linear-gradient(135deg,var(--accent),var(--accent2))}
.price{display:flex;flex-direction:column}.price .amount{margin:12px 0 22px}.price .amount b{font:800 44px/1 var(--fh)}.price .amount span{color:var(--muted);margin-left:6px}
.price ul{list-style:none;display:grid;gap:11px;margin-bottom:28px;flex:1}.price li{display:flex;gap:10px;color:var(--muted)}.price li svg{width:18px;height:18px;color:var(--accent2);flex:none;margin-top:3px}
.price.featured{border-color:color-mix(in srgb,var(--accent) 70%,transparent);box-shadow:0 30px 80px -40px var(--accent);background:linear-gradient(180deg,color-mix(in srgb,var(--accent) 12%,var(--surface)),var(--surface))}
.badge{position:absolute;top:18px;right:18px;font-size:12px;font-weight:700;padding:5px 11px;border-radius:999px;background:var(--accent);color:var(--on-accent)}
.faq{display:grid;gap:12px}.faq details{padding:0}.faq summary{list-style:none;cursor:pointer;padding:22px 26px;display:flex;justify-content:space-between;gap:16px;font-weight:600;font-size:17px}
.faq summary::-webkit-details-marker{display:none}.faq summary svg{flex:none;transition:transform .3s;color:var(--accent2)}.faq details[open] summary svg{transform:rotate(45deg)}.faq details p{padding:0 26px 24px;color:var(--muted)}
.cta-box{position:relative;overflow:hidden;text-align:center;padding:80px 30px;border-radius:calc(var(--r) * 1.5);border:1px solid var(--line);background:var(--surface)}
.cta-box h2{font-size:clamp(32px,4.2vw,58px);max-width:820px;margin:0 auto 18px;position:relative}.cta-box p{color:var(--muted);font-size:18px;max-width:600px;margin:0 auto 34px;position:relative}
.cta-glow{position:absolute;inset:-40%;background:conic-gradient(from 0deg,transparent,color-mix(in srgb,var(--accent) 45%,transparent),transparent 30%,color-mix(in srgb,var(--accent2) 40%,transparent),transparent 60%);animation:spin 14s linear infinite;filter:blur(50px);opacity:.7}
@keyframes spin{to{transform:rotate(1turn)}}
.contact{display:grid;grid-template-columns:1fr 1fr;gap:50px;align-items:start}.contact-rows{display:grid;gap:14px;margin-top:26px}.contact-rows>*{display:flex;gap:12px;align-items:center;color:var(--muted);font-size:17px}.contact-rows svg{color:var(--accent2)}.contact-rows a:hover{color:var(--text)}
.form{display:grid;gap:16px}.form label{display:grid;gap:7px;font-size:14px;color:var(--muted)}
.form input,.form textarea{font:inherit;color:var(--text);background:color-mix(in srgb,var(--bg) 60%,transparent);border:1px solid var(--line);border-radius:12px;padding:13px 15px;outline:none;transition:border-color .2s}
.form input:focus,.form textarea:focus{border-color:var(--accent)}.sent-msg{display:none;align-items:center;gap:8px;color:var(--accent2)}.form.sent .sent-msg{display:flex}.form.sent button{display:none}
footer{padding:46px 0 60px;border-top:1px solid var(--line)}.foot{display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap;color:var(--muted);font-size:14px}
.reveal{opacity:0;transform:translateY(34px);transition:opacity .9s cubic-bezier(.2,.8,.2,1) var(--d,0ms),transform .9s cubic-bezier(.2,.8,.2,1) var(--d,0ms)}.reveal.in{opacity:1;transform:none}
.hero .reveal{transition-duration:1.1s}
@media (max-width:860px){.links,.nav .btn{display:none}.burger{display:block}.nav.open{border-radius:24px;flex-wrap:wrap}.nav.open .links{display:flex;flex-direction:column;width:100%;order:3}.nav.open .btn{display:inline-flex;order:4}
section{padding:80px 0}.contact{grid-template-columns:1fr}.bento{grid-template-columns:1fr}.bento>*{grid-column:auto!important}.hero:after{background:linear-gradient(0deg,var(--bg) 8%,color-mix(in srgb,var(--bg) 55%,transparent))}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}.reveal{opacity:1;transform:none}}
`;
}

const RUNTIME = `
(function(){
var nav=document.querySelector('.nav');addEventListener('scroll',function(){nav&&nav.classList.toggle('scrolled',scrollY>30)},{passive:true});
var b=document.querySelector('.burger');b&&b.addEventListener('click',function(){nav.classList.toggle('open')});
document.querySelectorAll('.links a').forEach(function(a){a.addEventListener('click',function(){nav.classList.remove('open')})});
var io=new IntersectionObserver(function(es){es.forEach(function(e){if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target);var c=e.target.querySelector('[data-count]');c&&count(c)}})},{threshold:.15});
document.querySelectorAll('.reveal').forEach(function(el){io.observe(el)});
requestAnimationFrame(function(){document.querySelectorAll('.hero .reveal').forEach(function(el){el.classList.add('in')})});
setTimeout(function(){document.querySelectorAll('.reveal:not(.in)').forEach(function(el){if(el.getBoundingClientRect().top<innerHeight){el.classList.add('in');var c=el.querySelector('[data-count]');c&&count(c)}})},1200);
function count(el){var m=String(el.dataset.count).match(/^([^\\d]*)([\\d.,\\s]+)(.*)$/);if(!m)return;var raw=m[2].replace(/\\s/g,''),dec=(raw.split(/[.,]/)[1]||'').length,n=parseFloat(raw.replace(',','.'));if(isNaN(n))return;var t0=performance.now();(function step(t){var k=Math.min(1,(t-t0)/1400),v=n*(1-Math.pow(1-k,3));el.textContent=m[1]+(dec?v.toFixed(dec):Math.round(v).toLocaleString('ru-RU'))+m[3];if(k<1)requestAnimationFrame(step);else el.textContent=el.dataset.count})(t0)}
var fine=matchMedia('(pointer:fine)').matches;
if(fine){document.querySelectorAll('.tilt').forEach(function(el){el.addEventListener('pointermove',function(e){var r=el.getBoundingClientRect(),x=(e.clientX-r.left)/r.width,y=(e.clientY-r.top)/r.height;el.style.transform='perspective(900px) rotateX('+((.5-y)*9)+'deg) rotateY('+((x-.5)*11)+'deg) translateY(-4px)';el.style.setProperty('--mx',x*100+'%');el.style.setProperty('--my',y*100+'%')});el.addEventListener('pointerleave',function(){el.style.transform=''})});
document.querySelectorAll('.magnetic').forEach(function(el){el.addEventListener('pointermove',function(e){var r=el.getBoundingClientRect();el.style.transform='translate('+((e.clientX-r.left-r.width/2)*.22)+'px,'+((e.clientY-r.top-r.height/2)*.3)+'px)'});el.addEventListener('pointerleave',function(){el.style.transform=''})});
var g=document.querySelector('.cursor-glow');g&&addEventListener('pointermove',function(e){g.style.left=e.clientX+'px';g.style.top=e.clientY+'px'},{passive:true})}
function icons(){if(window.lucide)lucide.createIcons();else setTimeout(icons,150)}icons();
})();`;

function sceneModule(tpl, p) {
  const scene = SCENES[tpl.scene];
  if (!scene) return "";
  const colors = JSON.stringify({ bg: p.bg, surface: p.surface, text: p.text, accent: p.accent, accent2: p.accent2, light: p.light, split: tpl.hero === "split" });
  return `<script type="importmap">{"imports":{"three":"${THREE_URL}","three/addons/":"${THREE_ADDONS_URL}"}}</script>
<script type="module">
import * as THREE from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
const S=${colors};const canvas=document.getElementById('hero3d');
if(canvas){let renderer;try{renderer=new THREE.WebGLRenderer({canvas,antialias:true,alpha:true,powerPreference:'high-performance'})}catch(e){renderer=null}
if(renderer){renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.outputColorSpace=THREE.SRGBColorSpace;
const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(50,1,0.1,200);
const C={bg:new THREE.Color(S.bg),surface:new THREE.Color(S.surface),text:new THREE.Color(S.text),accent:new THREE.Color(S.accent),accent2:new THREE.Color(S.accent2)};
const ctx={THREE,scene,camera,renderer,C,light:S.light,mouse:{x:0,y:0},parallax:true,target:new THREE.Vector3(),
env:(k)=>{const pm=new THREE.PMREMGenerator(renderer);scene.environment=pm.fromScene(new RoomEnvironment(),0.04).texture;scene.environmentIntensity=k??1;pm.dispose()}};
const update=(function(ctx){${scene.code}
})(ctx);
const base=camera.position.clone();
const size=()=>{const r=canvas.getBoundingClientRect();renderer.setSize(r.width,r.height,false);camera.aspect=r.width/Math.max(1,r.height);
if(S.split&&r.width>860)camera.setViewOffset(r.width,r.height,-r.width*0.24,0,r.width,r.height);else camera.clearViewOffset();camera.updateProjectionMatrix()};size();addEventListener('resize',size);
const m={x:0,y:0};addEventListener('pointermove',(e)=>{m.x=e.clientX/innerWidth*2-1;m.y=-(e.clientY/innerHeight*2-1)},{passive:true});
let visible=true;new IntersectionObserver(([e])=>{visible=e.isIntersecting}).observe(canvas);
const reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;let t=0,last=performance.now();
renderer.setAnimationLoop(()=>{const now=performance.now(),dt=Math.min((now-last)/1000,0.05);last=now;if(!visible||document.hidden)return;t+=reduce?dt*0.1:dt;
ctx.mouse.x+=(m.x-ctx.mouse.x)*0.05;ctx.mouse.y+=(m.y-ctx.mouse.y)*0.05;update(t,dt);
if(ctx.parallax){camera.position.x=base.x+ctx.mouse.x*0.45;camera.position.y=base.y+ctx.mouse.y*0.3;camera.lookAt(ctx.target)}
renderer.render(scene,camera)});document.documentElement.classList.add('webgl')}}
</script>`;
}

/** Full HTML document for a spec (normalized here, so raw model output is fine). */
export function renderSite(input, opts) {
  const spec = normalizeSpec(input, opts);
  const tpl = templateById(spec.template);
  const p = spec.palette;
  const f = FONTS[spec.font] || FONTS.manrope;
  const h = spec.hero;
  const navItems = spec.sections.filter((id) => NAV_LABEL[id]).slice(0, 5);
  const body = spec.sections.map((id) => renderSection(spec, id, tpl)).join("\n");
  return `<!DOCTYPE html>
<html lang="${esc(spec.lang)}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>${esc(spec.brand)}${h.title && h.title !== spec.brand ? ` — ${esc(h.title)}` : ""}</title>
<meta name="description" content="${esc(h.subtitle)}">
<meta name="theme-color" content="${p.bg}">
<meta name="generator" content="Vibing AI Studio · 3D Pro · ${tpl.id}">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?${f.q}&display=swap" rel="stylesheet">
<script src="${LUCIDE_URL}" defer></script>
<style>${css(tpl, p, f)}</style>
</head>
<body>
<div class="noise"></div><div class="cursor-glow"></div>
<nav class="nav"><a href="#top" class="logo"><i></i>${esc(spec.brand)}</a><div class="links">${navItems.map((id) => `<a href="#${id}">${NAV_LABEL[id]}</a>`).join("")}</div><a href="#contact" class="btn btn-primary magnetic">${esc(h.cta)}</a><button class="burger" aria-label="Меню"><i data-lucide="menu"></i></button></nav>
<header class="hero" id="top"><canvas id="hero3d" aria-hidden="true"></canvas><div class="wrap"><div class="hero-inner">
${h.eyebrow ? `<div class="eyebrow reveal">${esc(h.eyebrow)}</div>` : ""}
<h1 class="reveal" style="--d:80ms">${titleHtml(h.title, h.highlight)}</h1>
${h.subtitle ? `<p class="sub reveal" style="--d:160ms">${esc(h.subtitle)}</p>` : ""}
<div class="hero-ctas reveal" style="--d:240ms"><a href="#contact" class="btn btn-primary btn-lg magnetic">${esc(h.cta)}<i data-lucide="arrow-right"></i></a>${h.cta2 ? `<a href="#${spec.sections.find((id) => id !== "stats") || "contact"}" class="btn btn-ghost btn-lg magnetic">${esc(h.cta2)}</a>` : ""}</div>
</div></div><div class="scroll-hint"></div></header>
<main>
${body}
</main>
<footer><div class="wrap foot"><span class="logo"><i></i>${esc(spec.brand)}</span><span>${esc(spec.footer.text || `© ${new Date().getFullYear()} ${spec.brand}. Все права защищены.`)}</span></div></footer>
<script>${RUNTIME}</script>
${sceneModule(tpl, p)}
</body>
</html>`;
}

export { esc };

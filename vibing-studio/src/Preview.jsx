import React, { useEffect, useMemo, useRef, useState } from "react";
import Icon from "./Icons.jsx";
import { Pet, VibeWord } from "./Pet.jsx";

/* ---------------- document helpers ---------------- */

const SKIP = new Set(["SCRIPT", "STYLE", "LINK", "NOSCRIPT", "TEMPLATE"]);
const kidsOf = (doc) => [...doc.body.children].filter((el) => !SKIP.has(el.tagName));

const parseDoc = (src) => new DOMParser().parseFromString(src, "text/html");
const serializeDoc = (doc) => "<!DOCTYPE html>\n" + doc.documentElement.outerHTML;

function blockLabel(el) {
  const id = el.getAttribute("id");
  if (id) return `#${id}`;
  const cls = (el.getAttribute("class") || "").split(/\s+/).filter(Boolean)[0];
  if (cls) return `.${cls}`;
  const txt = (el.textContent || "").trim().replace(/\s+/g, " ").slice(0, 28);
  return `<${el.tagName.toLowerCase()}>${txt ? " " + txt : ""}`;
}

function getBlocks(src) {
  try {
    return kidsOf(parseDoc(src)).map((el, i) => ({
      index: i,
      label: blockLabel(el),
      tag: el.tagName.toLowerCase(),
      hidden: el.hasAttribute("data-vhide"),
      moved: el.hasAttribute("data-vx") || el.hasAttribute("data-vscale"),
      scale: parseInt(el.getAttribute("data-vscale") || "100", 10),
    }));
  } catch {
    return [];
  }
}

function mutateDoc(src, index, fn) {
  const doc = parseDoc(src);
  const kids = kidsOf(doc);
  const el = kids[index];
  if (!el) return src;
  fn(doc, kids, el);
  return serializeDoc(doc);
}

function setPos(el, x, y) {
  if (x || y) {
    el.setAttribute("data-vx", String(x));
    el.setAttribute("data-vy", String(y));
    el.style.setProperty("translate", `${x}px ${y}px`);
  } else {
    el.removeAttribute("data-vx");
    el.removeAttribute("data-vy");
    el.style.removeProperty("translate");
  }
}

function setScale(el, s) {
  if (s >= 100) {
    el.removeAttribute("data-vscale");
    ["width", "max-width", "margin-inline", "box-sizing"].forEach((p) => el.style.removeProperty(p));
  } else {
    el.setAttribute("data-vscale", String(s));
    el.style.setProperty("width", `${s}%`);
    el.style.setProperty("max-width", "none");
    el.style.setProperty("margin-inline", "auto");
    el.style.setProperty("box-sizing", "border-box");
  }
}

const moveBlock = (src, i, dir) =>
  mutateDoc(src, i, (doc, kids, el) => {
    const j = i + dir;
    if (j < 0 || j >= kids.length) return;
    if (dir < 0) doc.body.insertBefore(el, kids[j]);
    else doc.body.insertBefore(el, kids[j].nextSibling);
  });

const toggleBlock = (src, i) =>
  mutateDoc(src, i, (doc, kids, el) => {
    if (el.hasAttribute("data-vhide")) {
      el.removeAttribute("data-vhide");
      el.style.removeProperty("display");
    } else {
      el.setAttribute("data-vhide", "1");
      el.style.setProperty("display", "none");
    }
  });

const scaleBlock = (src, i, s) => mutateDoc(src, i, (d, k, el) => setScale(el, s));
const resetBlock = (src, i) => mutateDoc(src, i, (d, k, el) => { setPos(el, 0, 0); setScale(el, 100); });
const commitBlock = (src, m) =>
  mutateDoc(src, m.i, (d, k, el) => { setPos(el, m.x, m.y); setScale(el, m.scale); });

/* ---------------- in-frame editor (runs inside the iframe) ---------------- */

function editor() {
  var cfg = window.__vc || {};
  var SKIP = { SCRIPT: 1, STYLE: 1, LINK: 1, NOSCRIPT: 1, TEMPLATE: 1 };
  var root = document.documentElement;
  var sel = -1;
  var drag = null;
  var scrollTimer = 0;

  var css = document.createElement("style");
  css.textContent =
    "html,body{-webkit-user-select:none!important;user-select:none!important}" +
    "body>*:not(script):not(style){cursor:grab}" +
    "#__vc,#__vch,#__vcp{position:fixed;z-index:2147483647;pointer-events:none;display:none;box-sizing:border-box;border-radius:3px}" +
    "#__vc{border:2px solid #7c5cff}" +
    "#__vch{border:1.5px dashed rgba(124,92,255,.85)}" +
    "#__vcp{border:2px solid #f472b6;background:rgba(244,114,182,.12)}" +
    "#__vc b{position:absolute;left:-2px;top:-25px;font:600 11px/19px ui-monospace,Consolas,monospace;background:#7c5cff;color:#ffffff;padding:0 8px;border-radius:5px;white-space:nowrap}" +
    "#__vc.in b{top:3px;left:3px}" +
    "#__vc i{position:absolute;top:50%;width:11px;height:40px;margin-top:-20px;background:#7c5cff;border:2px solid #ffffff;border-radius:6px;pointer-events:auto;cursor:ew-resize;box-sizing:border-box}" +
    "#__vc i[data-h=w]{left:-7px}#__vc i[data-h=e]{right:-7px}";
  root.appendChild(css);

  var ov = document.createElement("div");
  ov.id = "__vc";
  ov.innerHTML = '<b></b><i data-h="w"></i><i data-h="e"></i>';
  root.appendChild(ov);
  var label = ov.firstChild;
  var hv = document.createElement("div");
  hv.id = "__vch";
  root.appendChild(hv);
  var pk = document.createElement("div");
  pk.id = "__vcp";
  root.appendChild(pk);
  var picked = null;

  function send(o) { o.vc = 1; parent.postMessage(o, "*"); }
  function kids() {
    return Array.prototype.filter.call(document.body.children, function (e) { return !SKIP[e.tagName]; });
  }
  function topOf(t) {
    var k = kids();
    while (t && t !== document.body && t !== root) {
      var i = k.indexOf(t);
      if (i > -1) return i;
      t = t.parentElement;
    }
    return -1;
  }
  function pos(el) {
    return { x: parseFloat(el.getAttribute("data-vx")) || 0, y: parseFloat(el.getAttribute("data-vy")) || 0 };
  }
  function setPos(el, x, y) {
    if (x || y) {
      el.setAttribute("data-vx", x);
      el.setAttribute("data-vy", y);
      el.style.setProperty("translate", x + "px " + y + "px");
    } else {
      el.removeAttribute("data-vx");
      el.removeAttribute("data-vy");
      el.style.removeProperty("translate");
    }
  }
  function cw() {
    var cs = getComputedStyle(document.body);
    return document.body.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
  }
  function scaleOf(el) { return parseInt(el.getAttribute("data-vscale") || "100", 10); }
  function setScale(el, p) {
    p = Math.max(10, Math.min(100, Math.round(p)));
    if (p >= 100) {
      el.removeAttribute("data-vscale");
      ["width", "max-width", "margin-inline", "box-sizing"].forEach(function (k) { el.style.removeProperty(k); });
    } else {
      el.setAttribute("data-vscale", p);
      el.style.setProperty("width", p + "%");
      el.style.setProperty("max-width", "none");
      el.style.setProperty("margin-inline", "auto");
      el.style.setProperty("box-sizing", "border-box");
    }
    return p;
  }
  function box(node, el) {
    var r = el.getBoundingClientRect();
    node.style.display = "block";
    node.style.left = r.left + "px";
    node.style.top = r.top + "px";
    node.style.width = r.width + "px";
    node.style.height = r.height + "px";
    return r;
  }
  function placePick() {
    if (picked && document.body.contains(picked)) box(pk, picked);
    else { picked = null; pk.style.display = "none"; }
  }
  function place() {
    placePick();
    var el = sel > -1 ? kids()[sel] : null;
    if (!el || el.hasAttribute("data-vhide")) { ov.style.display = "none"; return; }
    var r = box(ov, el);
    var pct = Math.round((r.width / cw()) * 100);
    label.textContent = el.tagName.toLowerCase() + "  " + pct + "%";
    ov.className = r.top < 28 ? "in" : "";
    send({ t: "select", i: sel, html: el.outerHTML });
  }
  function hover(i) {
    var el = i > -1 && i !== sel ? kids()[i] : null;
    if (el && !el.hasAttribute("data-vhide")) box(hv, el);
    else hv.style.display = "none";
  }

  document.addEventListener("pointerdown", function (e) {
    if (e.button !== 0) return;
    var h = e.target.getAttribute && e.target.getAttribute("data-h");
    var el;
    if (e.shiftKey && !h) {
      var ti = topOf(e.target);
      if (ti > -1) {
        picked = e.target;
        sel = ti;
        place();
        send({ t: "select", i: ti, html: "" });
        send({ t: "pick", i: ti, html: picked.outerHTML.slice(0, 4000) });
      }
      e.preventDefault();
      return;
    }
    picked = null;
    if (h && sel > -1) {
      el = kids()[sel];
      drag = { mode: "rs", side: h, el: el, sx: e.clientX, w0: el.getBoundingClientRect().width, moved: false };
    } else {
      var i = topOf(e.target);
      if (i < 0) { if (sel > -1) { sel = -1; place(); send({ t: "select", i: -1 }); } return; }
      if (i !== sel) { sel = i; place(); send({ t: "select", i: i }); }
      el = kids()[i];
      var p = pos(el);
      drag = { mode: "mv", el: el, sx: e.clientX, sy: e.clientY, x0: p.x, y0: p.y, moved: false };
    }
    hv.style.display = "none";
    try { root.setPointerCapture(e.pointerId); } catch (err) {}
    e.preventDefault();
  }, true);

  document.addEventListener("pointermove", function (e) {
    if (!drag) { hover(topOf(e.target)); return; }
    var dx = e.clientX - drag.sx;
    if (drag.mode === "mv") {
      var dy = e.clientY - drag.sy;
      if (!drag.moved && Math.abs(dx) + Math.abs(dy) < 4) return;
      drag.moved = true;
      var x = drag.x0 + dx, y = drag.y0 + dy;
      if (!e.altKey) { if (Math.abs(x) < 8) x = 0; if (Math.abs(y) < 8) y = 0; }
      setPos(drag.el, Math.round(x), Math.round(y));
    } else {
      if (!drag.moved && Math.abs(dx) < 2) return;
      drag.moved = true;
      var w = drag.w0 + (drag.side === "e" ? dx : -dx) * 2;
      setScale(drag.el, (w / cw()) * 100);
    }
    place();
  }, true);

  function finish(e) {
    if (!drag) return;
    var d = drag;
    drag = null;
    try { root.releasePointerCapture(e.pointerId); } catch (err) {}
    if (d.moved) {
      var p = pos(d.el);
      send({ t: "commit", i: sel, x: p.x, y: p.y, scale: scaleOf(d.el), sy: window.scrollY });
    }
  }
  document.addEventListener("pointerup", finish, true);
  document.addEventListener("pointercancel", finish, true);

  document.addEventListener("click", function (e) { e.preventDefault(); e.stopPropagation(); }, true);
  document.addEventListener("submit", function (e) { e.preventDefault(); }, true);
  document.addEventListener("pointerleave", function () { hv.style.display = "none"; });

  window.addEventListener("scroll", function () {
    place();
    clearTimeout(scrollTimer);
    scrollTimer = setTimeout(function () { send({ t: "scroll", sy: window.scrollY }); }, 120);
  }, true);
  window.addEventListener("resize", place);

  window.addEventListener("message", function (e) {
    var d = e.data;
    if (!d || !d.vc || d.t !== "select") return;
    sel = d.i;
    place();
    var el = sel > -1 ? kids()[sel] : null;
    if (el && !drag) {
      var r = el.getBoundingClientRect();
      if (r.bottom < 0 || r.top > window.innerHeight) el.scrollIntoView({ block: "center" });
    }
  });

  function restore() {
    root.style.scrollBehavior = "auto";
    window.scrollTo(0, cfg.sy || 0);
    place();
  }
  restore();
  window.addEventListener("load", restore);
  send({ t: "ready" });
}

const EDITOR_JS = "(" + editor.toString() + ")();";

function inject(src, init) {
  const tag = "<script>window.__vc=" + JSON.stringify(init) + ";" + EDITOR_JS + "</scr" + "ipt>";
  const i = src.lastIndexOf("</body>");
  return i === -1 ? src + tag : src.slice(0, i) + tag + src.slice(i);
}

/* ---------------- generation phase text ---------------- */

function phaseOf(h) {
  if (!h) return "Продумываю структуру";
  if (/<style/i.test(h) && !/<\/style>/i.test(h)) return "Пишу стили";
  if (!/<body/i.test(h)) return "Готовлю каркас";
  if (/<\/html>/i.test(h)) return "Довожу детали";
  const n = (h.match(/<(section|header|footer|nav|main)\b/gi) || []).length;
  return n ? `Верстаю блоки: ${n}` : "Собираю разметку";
}

/* ---------------- style-writing card ---------------- */

// Streaming head phase: <style> exists, but no real body element has started yet.
function styleInfo(h) {
  if (!h) return { active: false, css: "", open: false };
  const bodyStarted = /<body[^>]*>\s*(?:<style[\s\S]*?<\/style>\s*)*<(?!\/?style\b)[a-z!]/i.test(h);
  let css = "";
  let open = false;
  let any = false;
  const re = /<style[^>]*>([\s\S]*?)(<\/style>|$)/gi;
  let m;
  while ((m = re.exec(h)) !== null) {
    any = true;
    css += m[1] + "\n";
    if (!m[2]) open = true;
  }
  return { active: any && !bodyStarted, css: css.trim(), open };
}

const TOK =
  /\/\*[\s\S]*?(?:\*\/|$)|"(?:[^"\\\n]|\\.)*"?|'(?:[^'\\\n]|\\.)*'?|[{};]|#[0-9a-fA-F]{3,8}\b|@[\w-]+|-?\d*\.?\d+(?:px|rem|em|%|vh|vw|svh|dvh|ms|s|deg|fr)?\b|-{0,2}[A-Za-z_][\w-]*/g;

function highlightCss(text, depth0) {
  const out = [];
  const push = (t, cls, k) => out.push(cls ? <span key={k} className={"t-" + cls}>{t}</span> : t);
  let last = 0;
  let depth = depth0;
  let sig = ";";
  let k = 0;
  let m;
  TOK.lastIndex = 0;
  while ((m = TOK.exec(text)) !== null) {
    const t = m[0];
    if (m.index > last) out.push(text.slice(last, m.index));
    last = m.index + t.length;
    let cls = "";
    if (t.startsWith("/*")) cls = "c";
    else if (t[0] === '"' || t[0] === "'") { cls = "s"; sig = "x"; }
    else if (t === "{") { depth++; sig = "{"; cls = "p"; }
    else if (t === "}") { depth = Math.max(0, depth - 1); sig = "}"; cls = "p"; }
    else if (t === ";") { sig = ";"; cls = "p"; }
    else if (t[0] === "#") { cls = "h"; sig = "x"; }
    else if (t[0] === "@") { cls = "k"; sig = "x"; }
    else if (/^-?\d|^-?\./.test(t)) { cls = "n"; sig = "x"; }
    else {
      const isProp = depth > 0 && (sig === "{" || sig === ";" || sig === "}") && /^\s*:/.test(text.slice(last, last + 8));
      if (isProp) cls = "pr";
      else if (depth === 0) cls = "sel";
      else if (t.startsWith("--")) cls = "v";
      sig = "x";
    }
    push(t, cls, k++);
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

const COLOR_RE =
  /#[0-9a-fA-F]{6}(?=[;\s,)}"'])|#[0-9a-fA-F]{3}(?=[;\s,)}"'])|(?:rgba?|hsla?)\([^)]*\)/g;

function cssMeta(css) {
  const colors = [];
  for (const m of css.matchAll(COLOR_RE)) {
    const c = m[0].toLowerCase();
    if (!colors.includes(c)) colors.push(c);
    if (colors.length >= 10) break;
  }
  const fonts = [];
  for (const m of css.matchAll(/font-family\s*:\s*([^;}]+)[;}]/g)) {
    const stack = m[1].trim();
    const name = stack.split(",")[0].replace(/["']/g, "").trim();
    if (!name || /^(inherit|initial|unset)$/i.test(name) || fonts.some((f) => f.name === name)) continue;
    fonts.push({ name, stack });
    if (fonts.length >= 2) break;
  }
  return {
    colors,
    fonts,
    rules: (css.match(/\{/g) || []).length,
    lines: css ? css.split("\n").length : 0,
  };
}

function StyleCard({ info }) {
  const { css, open } = info;
  const code = useMemo(() => {
    const MAX = 22;
    const lines = css.split("\n");
    const head = lines.slice(0, -MAX).join("\n");
    const depth0 = Math.max(0, (head.match(/\{/g) || []).length - (head.match(/\}/g) || []).length);
    return highlightCss(lines.slice(-MAX).join("\n"), depth0);
  }, [css]);
  const meta = useMemo(() => cssMeta(css), [css]);

  return (
    <div className={"sc" + (open ? "" : " done")}>
      <div className="sc-head">
        <Pet size={62} mood={open ? "focus" : "happy"} />
        <div className="sc-title">
          <VibeWord />
          <span className="sc-sub">{open ? "Пишу стили" : "Стили готовы · собираю разметку"}</span>
        </div>
      </div>

      <div className="sc-window">
        <div className="sc-bar">
          <i className="d1" /><i className="d2" /><i className="d3" />
          <span>style.css</span>
          <em>{open ? "пишется" : "готово"}</em>
        </div>
        <pre className="sc-code">
          <code>
            {code}
            {open && <span className="sc-caret" />}
          </code>
        </pre>
      </div>

      <div className="sc-meta">
        {meta.colors.length > 0 && (
          <div className="sc-palette">
            {meta.colors.map((c) => (
              <span key={c} className="sc-chip" style={{ background: c }} title={c} />
            ))}
          </div>
        )}
        {meta.fonts.map((f) => (
          <div key={f.name} className="sc-font" title={f.stack}>
            <b style={{ fontFamily: f.stack }}>Aa</b>
            <span>{f.name}</span>
          </div>
        ))}
        <span className="sc-stat">правил: {meta.rules} · строк: {meta.lines}</span>
      </div>
    </div>
  );
}

/* Top-level blocks beyond `seen` fade in one after another. */
function reveal(src, seen) {
  try {
    const doc = parseDoc(src);
    const kids = kidsOf(doc);
    if (kids.length <= seen) return src;
    kids.forEach((el, i) => {
      if (i < seen) return;
      el.setAttribute("data-vnew", "");
      el.style.setProperty("animation-delay", `${Math.min(i - seen, 6) * 0.09}s`);
    });
    const st = doc.createElement("style");
    st.textContent =
      "@keyframes vc-in{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:none}}" +
      "[data-vnew]{animation:vc-in .55s cubic-bezier(.2,.7,.2,1) both}";
    (doc.head || doc.documentElement).appendChild(st);
    return serializeDoc(doc);
  } catch {
    return src;
  }
}

/* While the AI edits, keep the page where the user was looking. */
function keepScroll(src, sy) {
  const tag =
    "<script>try{var s=" + (Number(sy) || 0) + ";document.documentElement.style.scrollBehavior='auto';" +
    "scrollTo(0,s);addEventListener('load',function(){scrollTo(0,s)})}catch(e){}</scr" + "ipt>";
  const i = src.lastIndexOf("</body>");
  return i === -1 ? src + tag : src.slice(0, i) + tag + src.slice(i);
}

/* ---------------- component ---------------- */

const VIEW_WIDTH = { desktop: "100%", tablet: "768px", mobile: "390px" };
const VIEW_LABEL = { desktop: "Компьютер", tablet: "Планшет", mobile: "Телефон" };

export default function Preview({ html, streaming, genId, kind = "new", onEdited, onSelect }) {
  const [edited, setEdited] = useState(null);
  const [debounced, setDebounced] = useState("");
  const [view, setView] = useState("desktop");
  const [tabMode, setTabMode] = useState("preview"); // 'preview' | 'code' | 'split'
  const [refreshKey, setRefreshKey] = useState(0);
  const [selected, setSelected] = useState(-1);
  const [copied, setCopied] = useState(false);
  const [editMode, setEditMode] = useState(true);
  const [picked, setPicked] = useState("");

  const frameRef = useRef(null);
  const scrollRef = useRef(0);
  const selRef = useRef(-1);
  const docRef = useRef("");
  const seenRef = useRef(0);
  selRef.current = selected;

  // New generation -> drop user edits, follow the stream.
  // For an AI edit the html already contains the user's manual tweaks, so they are dropped,
  // but the page stays on screen and keeps its scroll position.
  useEffect(() => {
    setEdited(null);
    setSelected(-1);
    seenRef.current = 0;
    if (kind === "edit") setDebounced(html);
    else scrollRef.current = 0;
  }, [genId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Let the app know about manual edits so the AI edits the same version the user sees.
  useEffect(() => {
    if (onEdited) onEdited(edited);
  }, [edited]); // eslint-disable-line react-hooks/exhaustive-deps

  // Debounce live reloads while tokens arrive.
  useEffect(() => {
    if (!streaming) {
      setDebounced(html);
      return;
    }
    const t = setTimeout(() => setDebounced(html), 300);
    return () => clearTimeout(t);
  }, [html, streaming]);

  const doc = edited ?? debounced;
  docRef.current = doc;
  const blocks = useMemo(() => (doc ? getBlocks(doc) : []), [doc]);
  const live = editMode && !streaming && !!doc;
  const frameDoc = useMemo(() => {
    if (live) return inject(doc, { sy: scrollRef.current });
    if (streaming && doc) return kind === "edit" ? keepScroll(doc, scrollRef.current) : reveal(doc, seenRef.current);
    return doc;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc, live, refreshKey, streaming, kind]);

  // Remember how many blocks are already on screen so only new ones animate.
  useEffect(() => {
    seenRef.current = streaming ? blocks.length : 0;
  }, [frameDoc]); // eslint-disable-line react-hooks/exhaustive-deps

  const sInfo = useMemo(() => styleInfo(html), [html]);
  const showCard = streaming && kind !== "edit" && sInfo.active;

  const postSelect = (i) =>
    frameRef.current?.contentWindow?.postMessage({ vc: 1, t: "select", i }, "*");

  useEffect(() => {
    if (live) postSelect(selected);
  }, [selected, live]);

  // Messages from the in-frame editor.
  useEffect(() => {
    const onMsg = (e) => {
      if (!frameRef.current || e.source !== frameRef.current.contentWindow) return;
      const d = e.data;
      if (!d || !d.vc) return;
      if (d.t === "ready") postSelect(selRef.current);
      else if (d.t === "select") { setSelected(d.i); setPicked(""); }
      else if (d.t === "pick") { setSelected(d.i); setPicked(d.html || ""); }
      else if (d.t === "scroll") scrollRef.current = d.sy || 0;
      else if (d.t === "commit") {
        scrollRef.current = d.sy || 0;
        setSelected(d.i);
        setEdited(commitBlock(docRef.current, d));
      }
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, []);

  // Inspector: tell the chat which block/element is selected (Shift+click = exact element).
  useEffect(() => {
    if (!onSelect) return;
    if (streaming || selected < 0 || !doc) { onSelect(""); return; }
    if (picked) { onSelect(picked); return; }
    try {
      const el = kidsOf(parseDoc(doc))[selected];
      onSelect(el ? el.outerHTML.slice(0, 4000) : "");
    } catch {
      onSelect("");
    }
  }, [selected, picked, doc, streaming]); // eslint-disable-line react-hooks/exhaustive-deps

  const download = () => {
    const blob = new Blob([doc], { type: "text/html;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "vibecode-site.html";
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  };

  const openTab = () => {
    const blob = new Blob([doc], { type: "text/html;charset=utf-8" });
    window.open(URL.createObjectURL(blob), "_blank");
  };

  const copy = () => {
    navigator.clipboard.writeText(doc).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  const phase = streaming && kind === "edit" ? "Вношу правки в код" : phaseOf(html);

  return (
    <div className="preview">
      <div className="pv-toolbar">
        <span className="pv-title">Превью</span>
        {streaming && doc && <span className="pv-live"><i />Обновляется</span>}

        <div className="pv-tab-modes">
          <button className={tabMode === "preview" ? "on" : ""} onClick={() => setTabMode("preview")} title="Только превью">
            <Icon name="eye" size={14} />
            <span>Превью</span>
          </button>
          <button className={tabMode === "split" ? "on" : ""} onClick={() => setTabMode("split")} title="Сплит режим (Превью + Код)">
            <Icon name="layout" size={14} />
            <span>Сплит</span>
          </button>
          <button className={tabMode === "code" ? "on" : ""} onClick={() => setTabMode("code")} title="Только HTML код">
            <Icon name="edit" size={14} />
            <span>Код</span>
          </button>
        </div>

        {tabMode !== "code" && (
          <div className="pv-views">
            {["desktop", "tablet", "mobile"].map((v) => (
              <button key={v} className={view === v ? "on" : ""} onClick={() => setView(v)} title={VIEW_LABEL[v]}>
                <Icon name={v} size={16} />
              </button>
            ))}
          </div>
        )}
        <button
          className={"pv-edit" + (live ? " on" : "")}
          onClick={() => setEditMode((v) => !v)}
          disabled={streaming}
          title="Редактор: двигайте блоки и меняйте их ширину прямо в превью"
        >
          <Icon name="move" size={15} />
          Редактор
        </button>
        <div className="pv-actions">
          <button onClick={() => { scrollRef.current = 0; setRefreshKey((k) => k + 1); }} title="Обновить"><Icon name="refresh" size={16} /></button>
          <button onClick={copy} title="Скопировать HTML"><Icon name={copied ? "check" : "copy"} size={16} /></button>
          <button onClick={openTab} title="Открыть в новой вкладке"><Icon name="external" size={16} /></button>
          <button onClick={download} title="Скачать .html"><Icon name="download" size={16} /></button>
        </div>
      </div>

      <div className={`pv-body tab-${tabMode}`}>
        {tabMode !== "code" && (
          <div className="pv-stagewrap">
            {streaming && <div className="pv-scan" />}
            <div className="pv-stage">
              {showCard ? (
                <StyleCard info={sInfo} />
              ) : !doc ? (
                <div className="pv-empty">
                  {streaming ? (
                    <div className="pv-gen">
                      <Pet size={136} />
                      <div className="pv-gen-word"><VibeWord /></div>
                      <div className="pv-gen-phase">{phase}</div>
                    </div>
                  ) : (
                    <>
                      <div className="pv-empty-icon"><Icon name="layout" size={30} /></div>
                      <p>Здесь появится сайт.<br />Опиши его в чате слева или выбери шаблон.</p>
                    </>
                  )}
                </div>
              ) : (
                <iframe
                  key={refreshKey}
                  ref={frameRef}
                  title="preview"
                  className="pv-frame"
                  style={{ maxWidth: VIEW_WIDTH[view] }}
                  sandbox="allow-scripts"
                  srcDoc={frameDoc}
                />
              )}
            </div>
            {streaming && doc && !showCard && (
              <div className="pv-status">
                <Pet size={58} />
                <div className="pv-status-text">
                  <VibeWord />
                  <span className="pv-gen-phase">{phase}</span>
                </div>
              </div>
            )}
          </div>
        )}

        {(tabMode === "code" || tabMode === "split") && (
          <div className="pv-codepanel">
            <div className="pv-codepanel-header">
              <span className="pv-code-title">index.html</span>
              <span className="pv-code-stats">{doc ? `${doc.length} символов · ${doc.split("\n").length} строк` : "Пусто"}</span>
              <button className="pv-code-copy" onClick={copy} title="Скопировать весь код">
                <Icon name={copied ? "check" : "copy"} size={13} />
                <span>{copied ? "Скопировано" : "Копировать"}</span>
              </button>
            </div>
            <pre className="pv-code-editor">
              <code>{doc || "<!-- HTML код появится здесь -->"}</code>
            </pre>
          </div>
        )}


        {blocks.length > 0 && (
          <div className="pv-blocks">
            <div className="pv-blocks-title">Блоки ({blocks.length})</div>
            {live && (
              <p className="pv-hint">
                Перетаскивайте блок в превью. Боковые ручки меняют ширину. Alt отключает привязку к краю.
                Shift+клик выбирает конкретный элемент (кнопку, заголовок) и отправляет его в чат.
              </p>
            )}
            {blocks.map((b) => (
              <div key={b.index} className={`pv-block${selected === b.index ? " sel" : ""}${b.hidden ? " hid" : ""}`}>
                <button className="pv-block-name" onClick={() => setSelected(b.index)} title={b.label}>
                  <span className="pv-tag">{b.tag}</span>
                  <span className="pv-label">{b.label}</span>
                  {b.moved && <span className="pv-dot" title="Блок изменён" />}
                </button>
                {selected === b.index && (
                  <div className="pv-block-ctl">
                    <div className="pv-row">
                      <button onClick={() => setEdited(moveBlock(doc, b.index, -1))} title="Выше по порядку"><Icon name="up" size={15} /></button>
                      <button onClick={() => setEdited(moveBlock(doc, b.index, +1))} title="Ниже по порядку"><Icon name="down" size={15} /></button>
                      <button onClick={() => setEdited(toggleBlock(doc, b.index))} title="Скрыть или показать">
                        <Icon name={b.hidden ? "eyeoff" : "eye"} size={15} />
                      </button>
                      <button onClick={() => setEdited(resetBlock(doc, b.index))} title="Вернуть позицию и ширину" disabled={!b.moved}>
                        <Icon name="undo" size={15} />
                      </button>
                    </div>
                    <div className="pv-row scale">
                      <span>Ширина {b.scale}%</span>
                      <input
                        type="range"
                        min="10"
                        max="100"
                        step="5"
                        value={b.scale}
                        onChange={(e) => setEdited(scaleBlock(doc, b.index, Number(e.target.value)))}
                      />
                    </div>
                  </div>
                )}
              </div>
            ))}
            {edited && (
              <button className="pv-reset" onClick={() => { setEdited(null); setSelected(-1); }}>
                Сбросить все правки
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
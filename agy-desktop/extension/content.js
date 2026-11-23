(() => {
  if (window.__AURA_AGENT_LOADED__) return;
  window.__AURA_AGENT_LOADED__ = true;

  // =========================================================
  // SHADOW DOM OVERLAY — CURSORS, DYNAMIC ISLAND & HOVER GLASS
  // =========================================================
  let host = null;
  let shadow = null;
  let edgeGlowEl = null;
  let islandEl = null;
  let islandTextEl = null;
  let fxLayerEl = null;
  let cursorsLayerEl = null;
  let hoverCardEl = null;

  const cursors = new Map();
  const activeAgents = new Set();
  let elementMap = new Map();

  // Always-on hover settings & cache
  let hoverEnabled = true;
  const localAnswerCache = new Map();
  let hoverTimer = null;
  let currentHoverEl = null;
  let isMouseOverCard = false;
  let activeHoverRequestId = 0;

  // Load hover toggle from storage (works even when extension panel is never opened!)
  chrome.storage.local.get("auraSettings", (res) => {
    if (res?.auraSettings && typeof res.auraSettings.hoverAnswer === "boolean") {
      hoverEnabled = res.auraSettings.hoverAnswer;
    }
  });
  chrome.storage.onChanged.addListener((changes) => {
    if (changes?.auraSettings?.newValue) {
      const s = changes.auraSettings.newValue;
      if (typeof s.hoverAnswer === "boolean") hoverEnabled = s.hoverAnswer;
    }
  });

  const OVERLAY_CSS = `
    :host {
      all: initial;
    }

    * {
      box-sizing: border-box;
      font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Segoe UI", Roboto, sans-serif;
    }

    /* Apple Intelligence Screen Edge Glow */
    .aura-edge-glow {
      position: fixed;
      inset: 0;
      pointer-events: none;
      z-index: 2147483644;
      opacity: 0;
      transition: opacity 0.65s cubic-bezier(0.22, 1, 0.36, 1);
    }

    .aura-edge-glow.visible {
      opacity: 1;
    }

    .aura-edge-glow::before {
      content: "";
      position: absolute;
      inset: -4px;
      border-radius: 10px;
      padding: 6px;
      background: conic-gradient(
        from var(--aura-angle, 0deg),
        #32ade6,
        #007aff,
        #5856d6,
        #af52de,
        #ff2d55,
        #ff9500,
        #32ade6
      );
      -webkit-mask:
        linear-gradient(#fff 0 0) content-box,
        linear-gradient(#fff 0 0);
      -webkit-mask-composite: xor;
      mask-composite: exclude;
      filter: blur(8px);
      animation: auraSpin 4.5s linear infinite;
    }

    .aura-edge-glow::after {
      content: "";
      position: absolute;
      inset: 0;
      box-shadow:
        inset 0 0 38px rgba(175, 82, 222, 0.25),
        inset 0 0 16px rgba(0, 122, 255, 0.28),
        inset 0 0 6px rgba(255, 45, 85, 0.2);
      animation: auraPulse 2.8s ease-in-out infinite;
    }

    @property --aura-angle {
      syntax: "<angle>";
      initial-value: 0deg;
      inherits: false;
    }

    @keyframes auraSpin {
      to { --aura-angle: 360deg; }
    }

    @keyframes auraPulse {
      0%, 100% { opacity: 0.72; }
      50% { opacity: 1; }
    }

    /* Light Frosted Apple Dynamic Island HUD */
    .aura-island {
      position: fixed;
      top: 16px;
      left: 50%;
      transform: translateX(-50%) translateY(-80px) scale(0.86);
      z-index: 2147483646;
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 8px 12px 8px 10px;
      min-width: 210px;
      max-width: 460px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.88);
      backdrop-filter: blur(26px) saturate(190%);
      -webkit-backdrop-filter: blur(26px) saturate(190%);
      border: 1px solid rgba(15, 23, 42, 0.1);
      box-shadow:
        0 18px 42px rgba(15, 23, 42, 0.16),
        0 0 24px rgba(0, 122, 255, 0.14),
        inset 0 1px 0 rgba(255, 255, 255, 0.95);
      color: #1d1d1f;
      opacity: 0;
      pointer-events: none;
      transition:
        transform 0.5s cubic-bezier(0.34, 1.56, 0.64, 1),
        opacity 0.32s ease;
    }

    .aura-island.visible {
      transform: translateX(-50%) translateY(0) scale(1);
      opacity: 1;
      pointer-events: auto;
    }

    .aura-mini-orb {
      width: 20px;
      height: 20px;
      border-radius: 50%;
      position: relative;
      overflow: hidden;
      flex-shrink: 0;
      background: #ffffff;
      box-shadow: 0 3px 10px rgba(88, 86, 214, 0.36), inset 0 0 0 1px rgba(255, 255, 255, 0.9);
    }

    .aura-mini-orb::before {
      content: "";
      position: absolute;
      inset: -40%;
      background: conic-gradient(from 0deg, #32ade6, #007aff, #5856d6, #af52de, #ff2d55, #32ade6);
      filter: blur(3px);
      animation: spinSimple 2s linear infinite;
    }

    .aura-mini-orb::after {
      content: "";
      position: absolute;
      top: 3px;
      left: 4px;
      width: 7px;
      height: 4px;
      border-radius: 50%;
      background: rgba(255, 255, 255, 0.92);
      transform: rotate(-20deg);
    }

    @keyframes spinSimple {
      to { transform: rotate(360deg); }
    }

    .aura-island-text {
      font-size: 13px;
      font-weight: 500;
      letter-spacing: -0.01em;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      flex: 1;
      color: #1d1d1f;
    }

    .aura-island-stop {
      width: 24px;
      height: 24px;
      border-radius: 50%;
      border: none;
      background: rgba(255, 45, 85, 0.12);
      color: #ff2d55;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      flex-shrink: 0;
      transition: transform 0.2s ease, background 0.2s ease, color 0.2s ease;
    }

    .aura-island-stop:hover {
      background: #ff2d55;
      color: #fff;
      transform: scale(1.1);
    }

    /* =========================================================
       ALWAYS-ON TRANSPARENT GLASS HOVER ANSWER POPOVER
       ========================================================= */
    .aura-hover-card {
      position: fixed;
      z-index: 2147483647;
      width: max-content;
      max-width: 340px;
      min-width: 190px;
      padding: 11px 13px;
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.62);
      backdrop-filter: blur(28px) saturate(210%);
      -webkit-backdrop-filter: blur(28px) saturate(210%);
      border: 1px solid rgba(255, 255, 255, 0.78);
      box-shadow:
        0 18px 44px rgba(15, 23, 42, 0.16),
        0 2px 10px rgba(15, 23, 42, 0.06),
        inset 0 1px 0 rgba(255, 255, 255, 0.95);
      color: #1d1d1f;
      opacity: 0;
      transform: translateY(8px) scale(0.95);
      pointer-events: none;
      transition:
        opacity 0.26s cubic-bezier(0.22, 1, 0.36, 1),
        transform 0.32s cubic-bezier(0.34, 1.56, 0.64, 1);
    }

    .aura-hover-card.visible {
      opacity: 1;
      transform: translateY(0) scale(1);
      pointer-events: auto;
    }

    .aura-hover-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 6px;
    }

    .aura-hover-brand {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 11px;
      font-weight: 600;
      color: #6e6e73;
    }

    .aura-hover-badge {
      font-size: 10px;
      font-weight: 600;
      padding: 1px 7px;
      border-radius: 999px;
      background: rgba(52, 199, 89, 0.14);
      color: #1e8e3e;
    }

    .aura-hover-badge.ai {
      background: rgba(0, 122, 255, 0.12);
      color: #0066d6;
    }

    .aura-hover-close {
      width: 20px;
      height: 20px;
      border-radius: 50%;
      border: none;
      background: rgba(15, 23, 42, 0.06);
      color: #6e6e73;
      font-size: 13px;
      line-height: 1;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      transition: background 0.2s ease, color 0.2s ease;
    }

    .aura-hover-close:hover {
      background: rgba(15, 23, 42, 0.14);
      color: #1d1d1f;
    }

    .aura-hover-body {
      font-size: 13.5px;
      font-weight: 500;
      line-height: 1.42;
      color: #1d1d1f;
      word-wrap: break-word;
    }

    .aura-hover-loading {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: #6e6e73;
      font-size: 12.5px;
    }

    .aura-hover-actions {
      display: flex;
      align-items: center;
      gap: 6px;
      margin-top: 9px;
    }

    .aura-hover-btn {
      padding: 5px 11px;
      border-radius: 999px;
      border: none;
      background: linear-gradient(135deg, #007aff, #5856d6);
      color: #fff;
      font-size: 11.5px;
      font-weight: 600;
      cursor: pointer;
      box-shadow: 0 4px 12px rgba(0, 122, 255, 0.25);
      transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1), filter 0.2s ease;
    }

    .aura-hover-btn:hover {
      transform: scale(1.04);
      filter: brightness(1.06);
    }

    .aura-hover-btn.secondary {
      background: rgba(15, 23, 42, 0.07);
      color: #1d1d1f;
      box-shadow: none;
    }

    /* FX Layer */
    .aura-fx-layer {
      position: fixed;
      inset: 0;
      pointer-events: none;
      z-index: 2147483645;
      overflow: hidden;
    }

    .aura-cursors-layer {
      position: fixed;
      inset: 0;
      pointer-events: none;
      z-index: 2147483647;
    }

    .aura-trail-dot {
      position: fixed;
      width: 9px;
      height: 9px;
      border-radius: 50%;
      transform: translate(-50%, -50%) scale(1);
      pointer-events: none;
      animation: trailFade 0.55s cubic-bezier(0.22, 1, 0.36, 1) forwards;
    }

    @keyframes trailFade {
      0% { opacity: 0.8; transform: translate(-50%, -50%) scale(1); }
      100% { opacity: 0; transform: translate(-50%, -50%) scale(0.2); }
    }

    .aura-ripple {
      position: fixed;
      width: 18px;
      height: 18px;
      border-radius: 50%;
      border: 2px solid #007aff;
      transform: translate(-50%, -50%) scale(0.3);
      pointer-events: none;
      animation: rippleExpand 0.72s cubic-bezier(0.22, 1, 0.36, 1) forwards;
    }

    .aura-ripple-secondary {
      animation-delay: 0.08s;
      animation-duration: 0.85s;
      opacity: 0.7;
    }

    @keyframes rippleExpand {
      0% { opacity: 0.95; transform: translate(-50%, -50%) scale(0.35); }
      100% { opacity: 0; transform: translate(-50%, -50%) scale(3.4); }
    }

    .aura-target-box {
      position: fixed;
      border-radius: 12px;
      border: 2px solid #007aff;
      pointer-events: none;
      animation: targetHighlight 0.9s cubic-bezier(0.22, 1, 0.36, 1) forwards;
    }

    @keyframes targetHighlight {
      0% { opacity: 0; transform: scale(1.08); }
      25% { opacity: 1; transform: scale(1); }
      75% { opacity: 1; transform: scale(1); }
      100% { opacity: 0; transform: scale(0.98); }
    }

    /* Named Virtual AI Cursor */
    .aura-cursor-wrap {
      position: fixed;
      top: 0;
      left: 0;
      pointer-events: none;
      opacity: 0;
      will-change: transform, opacity;
      transition: opacity 0.32s ease;
    }

    .aura-cursor-wrap.visible {
      opacity: 1;
    }

    .aura-cursor-halo {
      position: absolute;
      top: -12px;
      left: -12px;
      width: 34px;
      height: 34px;
      border-radius: 50%;
      filter: blur(6px);
      opacity: 0.55;
      pointer-events: none;
    }

    .aura-cursor-svg {
      position: relative;
      width: 28px;
      height: 28px;
      filter: drop-shadow(0 4px 10px rgba(15, 23, 42, 0.28));
      transform-origin: 3px 3px;
      transition: transform 0.16s cubic-bezier(0.34, 1.56, 0.64, 1);
    }

    .aura-cursor-svg.clicking {
      transform: scale(0.8);
    }

    .aura-cursor-tag {
      position: absolute;
      top: 22px;
      left: 17px;
      padding: 3px 10px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.94);
      backdrop-filter: blur(14px);
      border: 1.5px solid #007aff;
      box-shadow: 0 6px 18px rgba(15, 23, 42, 0.16);
      color: #1d1d1f;
      font-size: 11px;
      font-weight: 600;
      white-space: nowrap;
      letter-spacing: -0.01em;
      display: inline-flex;
      align-items: center;
      gap: 5px;
    }

    .aura-cursor-tag-dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      flex-shrink: 0;
    }
  `;

  function ensureOverlay() {
    if (host && document.documentElement.contains(host)) return;

    host = document.createElement("div");
    host.id = "aura-agent-shadow-host";
    host.style.cssText = "position:fixed;inset:0;pointer-events:none;z-index:2147483647;";
    shadow = host.attachShadow({ mode: "open" });

    const styleEl = document.createElement("style");
    styleEl.textContent = OVERLAY_CSS;
    shadow.appendChild(styleEl);

    edgeGlowEl = document.createElement("div");
    edgeGlowEl.className = "aura-edge-glow";
    shadow.appendChild(edgeGlowEl);

    fxLayerEl = document.createElement("div");
    fxLayerEl.className = "aura-fx-layer";
    shadow.appendChild(fxLayerEl);

    cursorsLayerEl = document.createElement("div");
    cursorsLayerEl.className = "aura-cursors-layer";
    shadow.appendChild(cursorsLayerEl);

    islandEl = document.createElement("div");
    islandEl.className = "aura-island";
    islandEl.innerHTML = `
      <div class="aura-mini-orb"></div>
      <div class="aura-island-text">Стелла активна</div>
      <button class="aura-island-stop" title="Остановить агентов">
        <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor">
          <rect x="5" y="5" width="14" height="14" rx="3"/>
        </svg>
      </button>
    `;
    islandTextEl = islandEl.querySelector(".aura-island-text");
    islandEl.querySelector(".aura-island-stop").addEventListener("click", () => {
      chrome.runtime.sendMessage({ type: "STOP_ALL_AGENTS" });
      hideOverlay();
    });
    shadow.appendChild(islandEl);

    hoverCardEl = document.createElement("div");
    hoverCardEl.className = "aura-hover-card";
    hoverCardEl.addEventListener("mouseenter", () => {
      isMouseOverCard = true;
    });
    hoverCardEl.addEventListener("mouseleave", () => {
      isMouseOverCard = false;
      setTimeout(() => {
        if (!isMouseOverCard) hideHoverCard();
      }, 280);
    });
    shadow.appendChild(hoverCardEl);

    document.documentElement.appendChild(host);
  }

  // =========================================================
  // ZERO-CREDIT LOCAL MATH & QUESTION SOLVER ENGINE
  // =========================================================
  function safeEvalArithmetic(expr) {
    // Allow strictly numbers, operators, parens, spaces, decimals
    const cleaned = expr
      .replace(/,/g, ".")
      .replace(/[×х]/gi, "*")
      .replace(/[÷:]/g, "/")
      .replace(/[−–—]/g, "-")
      .replace(/\^/g, "**")
      .replace(/[^0-9+\-*/().\s]/g, "")
      .trim();

    if (!cleaned || !/\d/.test(cleaned) || !/[+\-*/]/.test(cleaned)) return null;
    // Prevent unsafe or degenerate strings
    if (cleaned.length > 60 || /[^\d+\-*/().\s]/.test(cleaned)) return null;

    try {
      const fn = new Function(`"use strict"; return (${cleaned});`);
      const val = fn();
      if (typeof val === "number" && Number.isFinite(val)) {
        return Number.isInteger(val) ? String(val) : String(Number(val.toFixed(4)));
      }
    } catch (_) {}
    return null;
  }

  function trySolveLocally(questionText) {
    const q = String(questionText || "").trim();
    if (!q) return null;

    // 1. Percentage: "20% от 150" / "15% of 200"
    const pctMatch = q.match(/(\d+(?:[.,]\d+)?)\s*%\s*(?:от|of)\s*(\d+(?:[.,]\d+)?)/i);
    if (pctMatch) {
      const p = parseFloat(pctMatch[1].replace(",", "."));
      const base = parseFloat(pctMatch[2].replace(",", "."));
      const res = (p / 100) * base;
      if (Number.isFinite(res)) {
        const formatted = Number.isInteger(res) ? String(res) : String(Number(res.toFixed(4)));
        return { answer: formatted, source: "Локально (0 кредитов)" };
      }
    }

    // 2. Square root: "корень из 144" / "√144"
    const sqrtMatch = q.match(/(?:√|корень\s+из\s*)(\d+(?:[.,]\d+)?)/i);
    if (sqrtMatch) {
      const n = parseFloat(sqrtMatch[1].replace(",", "."));
      if (n >= 0) {
        const r = Math.sqrt(n);
        const formatted = Number.isInteger(r) ? String(r) : String(Number(r.toFixed(4)));
        return { answer: formatted, source: "Локально (0 кредитов)" };
      }
    }

    // 3. Linear equation: ax + b = c  (e.g., "2x + 5 = 15" or "x - 3 = 7")
    const linMatch = q.match(/(-?\d*)\s*[xх]\s*([+-])\s*(\d+)\s*=\s*(-?\d+)/i);
    if (linMatch) {
      const aStr = linMatch[1];
      const a = aStr === "" ? 1 : aStr === "-" ? -1 : parseFloat(aStr);
      const sign = linMatch[2] === "-" ? -1 : 1;
      const b = sign * parseFloat(linMatch[3]);
      const c = parseFloat(linMatch[4]);
      if (a !== 0) {
        const x = (c - b) / a;
        const formatted = Number.isInteger(x) ? String(x) : String(Number(x.toFixed(4)));
        return { answer: `x = ${formatted}`, rawMatch: formatted, source: "Локально (0 кредитов)" };
      }
    }

    // 4. Direct arithmetic expression inside text (e.g., "Сколько будет 24 * 5 + 8?")
    const exprMatch = q.match(/(\(?\s*-?\d+(?:[.,]\d+)?(?:\s*[+\-*/^×÷−–—:]\s*\(?\s*-?\d+(?:[.,]\d+)?\s*\)?)+)/);
    if (exprMatch) {
      const val = safeEvalArithmetic(exprMatch[1]);
      if (val !== null) {
        return { answer: val, rawMatch: val, source: "Локально (0 кредитов)" };
      }
    }

    return null;
  }

  // =========================================================
  // ALWAYS-ON HOVER QUESTION DETECTOR & GLASS POPOVER
  // =========================================================
  const QUESTION_REGEX =
    /(\?\s*$|^(сколько|какой|какая|какое|какие|что\s+такое|что\s+означает|где|когда|почему|зачем|как\s+|кто\s+|чему\s+равн|вычислите|решите|найдите|выберите|укажите|определите|what|which|who|where|when|why|how|calculate|solve|find|choose|select)\b)/i;

  function findQuestionElement(el) {
    let curr = el;
    for (let depth = 0; depth < 4 && curr && curr !== document.body; depth++) {
      if (host && host.contains(curr)) return null;
      const tag = curr.tagName?.toLowerCase() || "";
      if (["input", "textarea", "select", "nav", "footer", "button"].includes(tag)) return null;

      const text = (curr.innerText || "").replace(/\s+/g, " ").trim();
      if (text.length >= 6 && text.length <= 420) {
        const cls = String(curr.className || "").toLowerCase();
        const isQuizHint =
          cls.includes("question") ||
          cls.includes("qtext") ||
          cls.includes("prompt") ||
          tag === "legend" ||
          curr.getAttribute("role") === "heading";

        if (QUESTION_REGEX.test(text) || (isQuizHint && text.length >= 10)) {
          return { el: curr, text };
        }
      }
      curr = curr.parentElement;
    }
    return null;
  }

  function findNearbyOptions(questionEl) {
    let container = questionEl.parentElement;
    for (let i = 0; i < 4 && container && container !== document.body; i++) {
      const candidates = container.querySelectorAll(
        "label, [role='radio'], [role='checkbox'], [role='option'], button"
      );
      if (candidates.length >= 2 && candidates.length <= 10) {
        const opts = [];
        candidates.forEach((node) => {
          if (node.contains(questionEl) || questionEl.contains(node)) return;
          const t = (node.innerText || node.textContent || "").replace(/\s+/g, " ").trim();
          if (t && t.length <= 160) {
            opts.push({ el: node, text: t });
          }
        });
        if (opts.length >= 2) return opts;
      }
      container = container.parentElement;
    }
    return [];
  }

  function matchOptionByAnswer(options, answerText) {
    if (!options?.length || !answerText) return null;
    const normAns = String(answerText).toLowerCase().trim();
    // Exact or substring match
    for (const opt of options) {
      const t = opt.text.toLowerCase().trim();
      if (t === normAns || t.includes(normAns) || normAns.includes(t)) {
        return opt;
      }
    }
    return null;
  }

  function positionHoverCard(rect) {
    const pad = 12;
    const cardW = 320;
    let left = Math.min(window.innerWidth - cardW - pad, Math.max(pad, rect.left));
    let top = rect.bottom + 10;
    if (top + 130 > window.innerHeight) {
      top = Math.max(pad, rect.top - 120);
    }
    hoverCardEl.style.left = `${Math.round(left)}px`;
    hoverCardEl.style.top = `${Math.round(top)}px`;
  }

  function hideHoverCard() {
    if (!hoverCardEl) return;
    hoverCardEl.classList.remove("visible");
    currentHoverEl = null;
  }

  function renderHoverCard({ rect, badge, isAi = false, bodyHtml, matchedOption = null, askAiCallback = null }) {
    ensureOverlay();
    positionHoverCard(rect);

    hoverCardEl.innerHTML = `
      <div class="aura-hover-head">
        <div class="aura-hover-brand">
          <div class="aura-mini-orb" style="width:15px;height:15px;"></div>
          <span>Стелла</span>
          <span class="aura-hover-badge ${isAi ? "ai" : ""}">${badge}</span>
        </div>
        <button class="aura-hover-close" title="Закрыть">×</button>
      </div>
      <div class="aura-hover-body">${bodyHtml}</div>
      <div class="aura-hover-actions" id="auraHoverActions"></div>
    `;

    hoverCardEl.querySelector(".aura-hover-close").addEventListener("click", hideHoverCard);

    const actionsEl = hoverCardEl.querySelector("#auraHoverActions");
    if (matchedOption) {
      const clickBtn = document.createElement("button");
      clickBtn.className = "aura-hover-btn";
      clickBtn.textContent = "Нажать ответ";
      clickBtn.addEventListener("click", async () => {
        const r = matchedOption.el.getBoundingClientRect();
        const tx = Math.round(r.left + r.width / 2);
        const ty = Math.round(r.top + r.height / 2);
        const meta = { agentId: "hover-aura", agentName: "Стелла", agentColor: "#007aff" };
        showOverlay({ ...meta, edgeGlow: false, showCursor: true, status: "Выбираю ответ..." });
        await performClick(meta, null, tx, ty, "Выбираю ответ");
        setTimeout(() => hideOverlay("hover-aura"), 700);
        hideHoverCard();
      });
      actionsEl.appendChild(clickBtn);
    }

    if (askAiCallback) {
      const aiBtn = document.createElement("button");
      aiBtn.className = "aura-hover-btn secondary";
      aiBtn.textContent = "Спросить AI";
      aiBtn.addEventListener("click", askAiCallback);
      actionsEl.appendChild(aiBtn);
    }

    if (!actionsEl.children.length) {
      actionsEl.remove();
    }

    hoverCardEl.classList.add("visible");
  }

  function escapeHtmlLocal(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  async function handleQuestionHover(qEl, qText, rect) {
    const reqId = ++activeHoverRequestId;
    const options = findNearbyOptions(qEl);
    const cacheKey = `${qText}::${options.map((o) => o.text).join("|")}`;

    // 1. Check local zero-credit solver first
    const localSolved = trySolveLocally(qText);
    if (localSolved) {
      const matched = matchOptionByAnswer(options, localSolved.rawMatch || localSolved.answer);
      renderHoverCard({
        rect,
        badge: localSolved.source,
        isAi: false,
        bodyHtml: escapeHtmlLocal(localSolved.answer),
        matchedOption: matched,
      });
      return;
    }

    // 2. Check local in-memory cache (0 credits)
    if (localAnswerCache.has(cacheKey)) {
      const cached = localAnswerCache.get(cacheKey);
      const matched = matchOptionByAnswer(options, cached);
      renderHoverCard({
        rect,
        badge: "Кэш (0 кредитов)",
        isAi: false,
        bodyHtml: escapeHtmlLocal(cached),
        matchedOption: matched,
      });
      return;
    }

    // 3. Lightweight text-only OpenRouter quick answer (no screenshot!)
    renderHoverCard({
      rect,
      badge: "Анализ...",
      isAi: true,
      bodyHtml: `<span class="aura-hover-loading">Ищу ответ...</span>`,
    });

    chrome.runtime.sendMessage(
      {
        type: "QUICK_ANSWER",
        question: qText,
        options: options.map((o) => o.text),
      },
      (res) => {
        if (reqId !== activeHoverRequestId) return;
        if (res?.ok && res.answer) {
          localAnswerCache.set(cacheKey, res.answer);
          const matched = matchOptionByAnswer(options, res.answer);
          renderHoverCard({
            rect,
            badge: res.cached ? "Кэш (0 кредитов)" : "AI ответ",
            isAi: !res.cached,
            bodyHtml: escapeHtmlLocal(res.answer),
            matchedOption: matched,
          });
        } else {
          renderHoverCard({
            rect,
            badge: "Подсказка",
            isAi: false,
            bodyHtml: escapeHtmlLocal(
              res?.error || "Добавьте OpenRouter ключ в настройках Стеллы для авто-ответов."
            ),
          });
        }
      }
    );
  }

  document.addEventListener(
    "mousemove",
    (e) => {
      if (!hoverEnabled || activeAgents.size > 0 || isMouseOverCard) return;
      if (host && host.contains(e.target)) return;

      const found = findQuestionElement(e.target);
      if (!found) {
        clearTimeout(hoverTimer);
        if (currentHoverEl && !currentHoverEl.contains(e.target)) {
          setTimeout(() => {
            if (!isMouseOverCard) hideHoverCard();
          }, 260);
        }
        return;
      }

      if (found.el === currentHoverEl) return;
      clearTimeout(hoverTimer);
      hoverTimer = setTimeout(() => {
        currentHoverEl = found.el;
        const rect = found.el.getBoundingClientRect();
        handleQuestionHover(found.el, found.text, rect);
      }, 650);
    },
    { passive: true }
  );

  // Also support selecting any question text on any page!
  document.addEventListener("mouseup", () => {
    if (!hoverEnabled || activeAgents.size > 0) return;
    const sel = window.getSelection();
    const text = (sel?.toString() || "").replace(/\s+/g, " ").trim();
    if (text.length < 4 || text.length > 360) return;
    if (!QUESTION_REGEX.test(text) && !/\d\s*[+\-*/^=]\s*\d/.test(text)) return;

    try {
      const range = sel.getRangeAt(0);
      const rect = range.getBoundingClientRect();
      if (rect.width > 0 || rect.height > 0) {
        handleQuestionHover(range.commonAncestorContainer.parentElement || document.body, text, rect);
      }
    } catch (_) {}
  });

  // =========================================================
  // CURSORS & OVERLAY CONTROLS
  // =========================================================
  function getOrCreateCursor(agentId = "default", agentName = "Стелла", color = "#007aff") {
    ensureOverlay();
    let entry = cursors.get(agentId);
    if (entry) {
      entry.name = agentName || entry.name;
      entry.color = color || entry.color;
      return entry;
    }

    const offset = cursors.size * 38;
    const startX = Math.round(window.innerWidth * 0.45 + offset);
    const startY = Math.round(window.innerHeight * 0.45 + (offset % 90));

    const wrap = document.createElement("div");
    wrap.className = "aura-cursor-wrap";
    wrap.innerHTML = `
      <div class="aura-cursor-halo" style="background: radial-gradient(circle, ${color}, transparent 72%);"></div>
      <svg class="aura-cursor-svg" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M4.5 2.8L22.6 13.4C23.5 13.9 23.3 15.3 22.3 15.6L14.9 17.5L11.6 24.4C11.1 25.4 9.7 25.2 9.4 24.2L3.1 4.2C2.8 3.2 3.7 2.3 4.5 2.8Z" fill="#FFFFFF" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>
      </svg>
      <div class="aura-cursor-tag" style="border-color: ${color};">
        <span class="aura-cursor-tag-dot" style="background: ${color};"></span>
        <span class="aura-cursor-tag-label">${agentName}</span>
      </div>
    `;

    cursorsLayerEl.appendChild(wrap);
    entry = {
      wrap,
      svg: wrap.querySelector(".aura-cursor-svg"),
      tagLabel: wrap.querySelector(".aura-cursor-tag-label"),
      x: startX,
      y: startY,
      name: agentName,
      color,
    };
    cursors.set(agentId, entry);
    setCursorPosition(entry, startX, startY, 0);
    return entry;
  }

  function setCursorPosition(entry, x, y, tiltDeg = 0) {
    entry.x = x;
    entry.y = y;
    entry.wrap.style.transform = `translate3d(${x}px, ${y}px, 0) rotate(${tiltDeg.toFixed(1)}deg)`;
  }

  function showOverlay({
    agentId = "default",
    agentName = "Стелла",
    agentColor = "#007aff",
    edgeGlow = true,
    showCursor = true,
    status = "Думаю...",
  } = {}) {
    ensureOverlay();
    hideHoverCard();
    activeAgents.add(agentId);

    if (edgeGlow) edgeGlowEl.classList.add("visible");
    else if (activeAgents.size <= 1) edgeGlowEl.classList.remove("visible");

    islandTextEl.textContent = `${agentName} • ${status}`;
    islandEl.classList.add("visible");

    const cur = getOrCreateCursor(agentId, agentName, agentColor);
    cur.tagLabel.textContent = agentName;
    if (showCursor) cur.wrap.classList.add("visible");
    else cur.wrap.classList.remove("visible");
  }

  function updateIsland(text, tagText, agentId = "default", agentName = "Стелла", agentColor = "#007aff") {
    ensureOverlay();
    if (text) islandTextEl.textContent = `${agentName} • ${text}`;
    const cur = getOrCreateCursor(agentId, agentName, agentColor);
    cur.tagLabel.textContent = tagText ? `${agentName} · ${tagText}` : agentName;
  }

  function hideOverlay(agentId = null) {
    if (!host) return;
    if (agentId) {
      activeAgents.delete(agentId);
      const cur = cursors.get(agentId);
      if (cur) {
        cur.wrap.classList.remove("visible");
        setTimeout(() => {
          if (!activeAgents.has(agentId)) {
            cur.wrap.remove();
            cursors.delete(agentId);
          }
        }, 350);
      }
      if (activeAgents.size > 0) return;
    } else {
      activeAgents.clear();
      for (const cur of cursors.values()) {
        cur.wrap.classList.remove("visible");
        cur.wrap.remove();
      }
      cursors.clear();
    }

    edgeGlowEl.classList.remove("visible");
    islandEl.classList.remove("visible");
  }

  function spawnTrailDot(x, y, color = "#007aff") {
    if (!fxLayerEl) return;
    const dot = document.createElement("div");
    dot.className = "aura-trail-dot";
    dot.style.left = `${x}px`;
    dot.style.top = `${y}px`;
    dot.style.background = `radial-gradient(circle, ${color}, transparent 72%)`;
    fxLayerEl.appendChild(dot);
    setTimeout(() => dot.remove(), 580);
  }

  function spawnClickRipple(x, y, color = "#007aff") {
    if (!fxLayerEl) return;
    const r1 = document.createElement("div");
    r1.className = "aura-ripple";
    r1.style.left = `${x}px`;
    r1.style.top = `${y}px`;
    r1.style.borderColor = color;
    r1.style.boxShadow = `0 0 16px ${color}`;
    fxLayerEl.appendChild(r1);

    const r2 = document.createElement("div");
    r2.className = "aura-ripple aura-ripple-secondary";
    r2.style.left = `${x}px`;
    r2.style.top = `${y}px`;
    r2.style.borderColor = color;
    fxLayerEl.appendChild(r2);

    setTimeout(() => {
      r1.remove();
      r2.remove();
    }, 950);
  }

  function highlightRect(rect, color = "#007aff") {
    if (!fxLayerEl || !rect) return;
    const box = document.createElement("div");
    box.className = "aura-target-box";
    box.style.left = `${Math.max(0, rect.left - 4)}px`;
    box.style.top = `${Math.max(0, rect.top - 4)}px`;
    box.style.width = `${rect.width + 8}px`;
    box.style.height = `${rect.height + 8}px`;
    box.style.borderColor = color;
    box.style.boxShadow = `0 0 18px ${color}55`;
    fxLayerEl.appendChild(box);
    setTimeout(() => box.remove(), 950);
  }

  function easeInOutCubic(t) {
    return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  }

  function moveCursorTo(entry, targetX, targetY, durationMs = 500) {
    entry.wrap.classList.add("visible");

    const startX = entry.x;
    const startY = entry.y;
    const dx = targetX - startX;
    const dy = targetY - startY;
    const dist = Math.hypot(dx, dy);

    if (dist < 4) {
      setCursorPosition(entry, targetX, targetY, 0);
      return Promise.resolve();
    }

    const actualDuration = Math.min(780, Math.max(250, durationMs * (dist / 420)));
    const midX = (startX + targetX) / 2 - dy * 0.12;
    const midY = (startY + targetY) / 2 + dx * 0.12;

    return new Promise((resolve) => {
      const startTime = performance.now();
      let lastTrailTime = 0;

      function frame(now) {
        const elapsed = now - startTime;
        const rawT = Math.min(1, elapsed / actualDuration);
        const t = easeInOutCubic(rawT);
        const inv = 1 - t;

        const x = inv * inv * startX + 2 * inv * t * midX + t * t * targetX;
        const y = inv * inv * startY + 2 * inv * t * midY + t * t * targetY;

        const tilt = Math.max(-14, Math.min(14, (x - entry.x) * 0.65)) * (1 - rawT);
        setCursorPosition(entry, x, y, tilt);

        if (now - lastTrailTime > 38 && rawT < 0.94) {
          spawnTrailDot(x + 4, y + 4, entry.color);
          lastTrailTime = now;
        }

        if (rawT < 1) requestAnimationFrame(frame);
        else {
          setCursorPosition(entry, targetX, targetY, 0);
          resolve();
        }
      }

      requestAnimationFrame(frame);
    });
  }

  function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  // =========================================================
  // REAL DOM INTERACTIONS
  // =========================================================
  function resolveTarget(elementId, x, y) {
    let el = null;
    if (elementId != null && elementMap.has(Number(elementId))) {
      el = elementMap.get(Number(elementId));
      if (el && !document.contains(el)) el = null;
    }

    if (el) {
      const rect = el.getBoundingClientRect();
      if (rect.top < 0 || rect.bottom > window.innerHeight) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
      }
      const r2 = el.getBoundingClientRect();
      return {
        el,
        x: Math.round(r2.left + r2.width / 2),
        y: Math.round(r2.top + r2.height / 2),
        rect: r2,
      };
    }

    if (typeof x === "number" && typeof y === "number") {
      const hit = document.elementFromPoint(x, y);
      return {
        el: hit,
        x: Math.round(x),
        y: Math.round(y),
        rect: hit ? hit.getBoundingClientRect() : null,
      };
    }

    return null;
  }

  async function performClick(meta, elementId, x, y, label = "Клик") {
    const cur = getOrCreateCursor(meta.agentId, meta.agentName, meta.agentColor);
    const target = resolveTarget(elementId, x, y);
    if (!target) return { ok: false, error: "Элемент не найден на странице" };

    await sleep(120);
    const updatedRect = target.el ? target.el.getBoundingClientRect() : target.rect;
    const tx = updatedRect ? Math.round(updatedRect.left + updatedRect.width / 2) : target.x;
    const ty = updatedRect ? Math.round(updatedRect.top + updatedRect.height / 2) : target.y;

    updateIsland(label, "Клик", meta.agentId, meta.agentName, meta.agentColor);
    await moveCursorTo(cur, tx, ty, 480);

    if (updatedRect) highlightRect(updatedRect, cur.color);
    cur.svg.classList.add("clicking");
    spawnClickRipple(tx, ty, cur.color);

    const el = target.el || document.elementFromPoint(tx, ty);
    if (el) {
      const mouseOpts = { bubbles: true, cancelable: true, clientX: tx, clientY: ty, view: window };
      el.dispatchEvent(new PointerEvent("pointerover", mouseOpts));
      el.dispatchEvent(new MouseEvent("mouseover", mouseOpts));
      el.dispatchEvent(new PointerEvent("pointerdown", mouseOpts));
      el.dispatchEvent(new MouseEvent("mousedown", mouseOpts));
      if (typeof el.focus === "function") el.focus({ preventScroll: true });
      await sleep(85);
      el.dispatchEvent(new PointerEvent("pointerup", mouseOpts));
      el.dispatchEvent(new MouseEvent("mouseup", mouseOpts));
      el.click();
    }

    await sleep(100);
    cur.svg.classList.remove("clicking");
    return { ok: true, x: tx, y: ty };
  }

  function setNativeValue(el, value) {
    const proto =
      el instanceof HTMLTextAreaElement
        ? HTMLTextAreaElement.prototype
        : el instanceof HTMLInputElement
        ? HTMLInputElement.prototype
        : null;
    const setter = proto && Object.getOwnPropertyDescriptor(proto, "value")?.set;
    if (setter) setter.call(el, value);
    else el.value = value;
  }

  async function performType(meta, elementId, text, clearFirst = true, pressEnter = false) {
    const clickRes = await performClick(meta, elementId, null, null, "Ввожу текст...");
    if (!clickRes.ok) return clickRes;

    const el = elementMap.get(Number(elementId)) || document.activeElement;
    if (!el) return { ok: false, error: "Поле ввода не найдено" };

    updateIsland(`Печатаю...`, "Ввод", meta.agentId, meta.agentName, meta.agentColor);
    el.focus();

    const isContentEditable = el.isContentEditable;
    if (clearFirst) {
      if (isContentEditable) el.textContent = "";
      else if ("value" in el) setNativeValue(el, "");
      el.dispatchEvent(new Event("input", { bubbles: true }));
    }

    const str = String(text ?? "");
    let current = isContentEditable ? el.textContent : el.value || "";

    for (let i = 0; i < str.length; i++) {
      const ch = str[i];
      current += ch;
      el.dispatchEvent(new KeyboardEvent("keydown", { key: ch, bubbles: true }));
      if (isContentEditable) el.textContent = current;
      else if ("value" in el) setNativeValue(el, current);
      el.dispatchEvent(new InputEvent("input", { data: ch, inputType: "insertText", bubbles: true }));
      el.dispatchEvent(new KeyboardEvent("keyup", { key: ch, bubbles: true }));
      await sleep(str.length > 35 ? 12 : 24);
    }

    el.dispatchEvent(new Event("change", { bubbles: true }));

    if (pressEnter) {
      await sleep(100);
      el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", keyCode: 13, bubbles: true }));
      el.dispatchEvent(new KeyboardEvent("keypress", { key: "Enter", code: "Enter", keyCode: 13, bubbles: true }));
      el.dispatchEvent(new KeyboardEvent("keyup", { key: "Enter", code: "Enter", keyCode: 13, bubbles: true }));
      if (el.form) el.form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    }

    return { ok: true };
  }

  async function performHover(meta, elementId) {
    const cur = getOrCreateCursor(meta.agentId, meta.agentName, meta.agentColor);
    const target = resolveTarget(elementId, null, null);
    if (!target) return { ok: false, error: "Элемент не найден" };
    updateIsland("Навожу курсор...", "Наведение", meta.agentId, meta.agentName, meta.agentColor);
    await moveCursorTo(cur, target.x, target.y, 440);
    if (target.rect) highlightRect(target.rect, cur.color);
    if (target.el) {
      const opts = { bubbles: true, clientX: target.x, clientY: target.y, view: window };
      target.el.dispatchEvent(new PointerEvent("pointerover", opts));
      target.el.dispatchEvent(new MouseEvent("mouseover", opts));
      target.el.dispatchEvent(new MouseEvent("mouseenter", opts));
    }
    return { ok: true };
  }

  async function performScroll(meta, direction = "down", amount = 520) {
    const delta = direction === "up" ? -Math.abs(amount) : Math.abs(amount);
    updateIsland(direction === "up" ? "Листаю вверх..." : "Листаю вниз...", "Скролл", meta.agentId, meta.agentName, meta.agentColor);
    window.scrollBy({ top: delta, behavior: "smooth" });
    await sleep(460);
    return { ok: true, scrollY: window.scrollY };
  }

  async function performKey(meta, key = "Enter") {
    updateIsland(`Нажимаю ${key}`, key, meta.agentId, meta.agentName, meta.agentColor);
    const el = document.activeElement || document.body;
    el.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
    el.dispatchEvent(new KeyboardEvent("keyup", { key, bubbles: true }));
    await sleep(130);
    return { ok: true };
  }

  // Local Zero-Credit Auto-Click by text (for fast local commands!)
  async function performLocalClickByText(meta, queryText) {
    const q = String(queryText || "").toLowerCase().trim();
    if (!q) return { ok: false, error: "Пустой запрос" };
    const obs = observePage();
    const match = obs.elements.find(
      (e) =>
        (e.text && e.text.toLowerCase().includes(q)) ||
        (e.aria && e.aria.toLowerCase().includes(q)) ||
        (e.placeholder && e.placeholder.toLowerCase().includes(q))
    );
    if (!match) return { ok: false, error: `Элемент "${queryText}" не найден` };
    return performClick(meta, match.id, match.x, match.y, `Нажимаю "${match.text || queryText}"`);
  }

  // =========================================================
  // COMPACT DOM PERCEPTION (SAVES ~70% AI TOKENS)
  // =========================================================
  function isElementVisible(el) {
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || parseFloat(style.opacity) === 0) {
      return false;
    }
    const rect = el.getBoundingClientRect();
    if (rect.width < 4 || rect.height < 4) return false;
    if (rect.bottom < -100 || rect.top > window.innerHeight + 140) return false;
    if (rect.right < 0 || rect.left > window.innerWidth) return false;
    return true;
  }

  function observePage() {
    elementMap = new Map();
    const selector = [
      "a[href]",
      "button",
      "input:not([type='hidden'])",
      "textarea",
      "select",
      "[role='button']",
      "[role='link']",
      "[role='radio']",
      "[role='checkbox']",
      "[role='option']",
      "[role='tab']",
      "[contenteditable='true']",
      "label",
    ].join(",");

    const nodes = Array.from(document.querySelectorAll(selector));
    const items = [];
    let idCounter = 1;

    for (const el of nodes) {
      if (idCounter > 65) break;
      if (host && host.contains(el)) continue;
      if (!isElementVisible(el)) continue;

      const rect = el.getBoundingClientRect();
      const tag = el.tagName.toLowerCase();
      const type = el.getAttribute("type") || "";
      const ariaLabel = el.getAttribute("aria-label") || "";
      const placeholder = el.getAttribute("placeholder") || "";
      const text = (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 75);
      const value = "value" in el && type !== "password" ? String(el.value || "").slice(0, 45) : "";

      if (!text && !ariaLabel && !placeholder && !["input", "textarea", "select"].includes(tag)) {
        continue;
      }

      const id = idCounter++;
      elementMap.set(id, el);

      const entry = { id, tag };
      if (type) entry.t = type;
      if (text) entry.text = text;
      if (ariaLabel && ariaLabel !== text) entry.aria = ariaLabel.slice(0, 55);
      if (placeholder) entry.ph = placeholder.slice(0, 45);
      if (value) entry.val = value;
      if (el.checked) entry.chk = 1;
      items.push(entry);
    }

    const bodyText = (document.body?.innerText || "").replace(/\s+/g, " ").trim().slice(0, 2800);

    return {
      url: location.href,
      title: document.title,
      scrollY: Math.round(window.scrollY),
      elements: items,
      pageText: bodyText,
    };
  }

  // =========================================================
  // MULTI-AGENT DEMO CHOREOGRAPHY
  // =========================================================
  async function runDemoMotion() {
    const w = window.innerWidth;
    const h = window.innerHeight;

    showOverlay({
      agentId: "demo-1",
      agentName: "Стелла",
      agentColor: "#007aff",
      edgeGlow: true,
      showCursor: true,
      status: "Мульти-агентное демо...",
    });
    showOverlay({
      agentId: "demo-2",
      agentName: "Nova",
      agentColor: "#af52de",
      edgeGlow: true,
      showCursor: true,
      status: "Два агента работают вместе!",
    });

    const c1 = getOrCreateCursor("demo-1", "Стелла", "#007aff");
    const c2 = getOrCreateCursor("demo-2", "Nova", "#af52de");

    await Promise.all([
      moveCursorTo(c1, w * 0.26, h * 0.34, 650),
      moveCursorTo(c2, w * 0.72, h * 0.38, 720),
    ]);
    spawnClickRipple(w * 0.26, h * 0.34, "#007aff");
    spawnClickRipple(w * 0.72, h * 0.38, "#af52de");
    await sleep(360);

    await Promise.all([
      moveCursorTo(c1, w * 0.62, h * 0.62, 680),
      moveCursorTo(c2, w * 0.35, h * 0.66, 650),
    ]);
    spawnClickRipple(w * 0.62, h * 0.62, "#007aff");
    spawnClickRipple(w * 0.35, h * 0.66, "#af52de");
    await sleep(900);

    hideOverlay("demo-1");
    hideOverlay("demo-2");
    return { ok: true };
  }

  // =========================================================
  // SET-OF-MARK (SoM) VISUAL BADGES FOR PRECISION VISION
  // =========================================================
  let somLayerEl = null;

  function showSomLabels() {
    ensureOverlay();
    hideSomLabels();
    somLayerEl = document.createElement("div");
    somLayerEl.style.cssText = "position:fixed;inset:0;pointer-events:none;z-index:2147483645;";

    for (const [id, el] of elementMap.entries()) {
      if (!document.contains(el)) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 4 || r.height < 4 || r.bottom < 0 || r.top > window.innerHeight) continue;
      const badge = document.createElement("div");
      badge.textContent = String(id);
      badge.style.cssText = `
        position:fixed;
        left:${Math.max(0, Math.round(r.left - 4))}px;
        top:${Math.max(0, Math.round(r.top - 4))}px;
        padding:1px 5px;
        border-radius:6px;
        background:rgba(29,29,31,0.88);
        color:#ffffff;
        font-size:10px;
        font-weight:700;
        border:1px solid rgba(255,255,255,0.75);
        box-shadow:0 2px 6px rgba(0,0,0,0.3);
        line-height:1.3;
      `;
      somLayerEl.appendChild(badge);
    }
    shadow.appendChild(somLayerEl);
  }

  function hideSomLabels() {
    if (somLayerEl) {
      somLayerEl.remove();
      somLayerEl = null;
    }
  }

  // =========================================================
  // FULL MOUSE CONTROL: DOUBLE CLICK, RIGHT CLICK, DRAG & DROP
  // =========================================================
  async function performDoubleClick(meta, elementId, x, y) {
    const cur = getOrCreateCursor(meta.agentId, meta.agentName, meta.agentColor);
    const target = resolveTarget(elementId, x, y);
    if (!target) return { ok: false, error: "Элемент не найден" };

    updateIsland("Двойной клик...", "2× Клик", meta.agentId, meta.agentName, meta.agentColor);
    await moveCursorTo(cur, target.x, target.y, 460);
    if (target.rect) highlightRect(target.rect, cur.color);

    const el = target.el || document.elementFromPoint(target.x, target.y);
    const opts = { bubbles: true, cancelable: true, clientX: target.x, clientY: target.y, detail: 2, view: window };
    spawnClickRipple(target.x, target.y, cur.color);
    cur.svg.classList.add("clicking");
    if (el) {
      el.dispatchEvent(new MouseEvent("mousedown", opts));
      el.dispatchEvent(new MouseEvent("mouseup", opts));
      el.click();
      await sleep(75);
      spawnClickRipple(target.x, target.y, cur.color);
      el.dispatchEvent(new MouseEvent("mousedown", opts));
      el.dispatchEvent(new MouseEvent("mouseup", opts));
      el.click();
      el.dispatchEvent(new MouseEvent("dblclick", opts));
    }
    await sleep(100);
    cur.svg.classList.remove("clicking");
    return { ok: true, x: target.x, y: target.y };
  }

  async function performRightClick(meta, elementId, x, y) {
    const cur = getOrCreateCursor(meta.agentId, meta.agentName, meta.agentColor);
    const target = resolveTarget(elementId, x, y);
    if (!target) return { ok: false, error: "Элемент не найден" };

    updateIsland("Правый клик...", "Меню", meta.agentId, meta.agentName, meta.agentColor);
    await moveCursorTo(cur, target.x, target.y, 460);
    if (target.rect) highlightRect(target.rect, cur.color);
    spawnClickRipple(target.x, target.y, cur.color);

    const el = target.el || document.elementFromPoint(target.x, target.y);
    const opts = { bubbles: true, cancelable: true, clientX: target.x, clientY: target.y, button: 2, buttons: 2, view: window };
    if (el) {
      el.dispatchEvent(new MouseEvent("mousedown", opts));
      el.dispatchEvent(new MouseEvent("mouseup", opts));
      el.dispatchEvent(new MouseEvent("contextmenu", opts));
    }
    return { ok: true, x: target.x, y: target.y };
  }

  async function performDragDrop(meta, fromId, toId) {
    const cur = getOrCreateCursor(meta.agentId, meta.agentName, meta.agentColor);
    const from = resolveTarget(fromId, null, null);
    const to = resolveTarget(toId, null, null);
    if (!from || !to) return { ok: false, error: "Элементы для перетаскивания не найдены" };

    updateIsland("Перетаскиваю элемент...", "Drag", meta.agentId, meta.agentName, meta.agentColor);
    await moveCursorTo(cur, from.x, from.y, 450);
    cur.svg.classList.add("clicking");
    spawnClickRipple(from.x, from.y, cur.color);

    const dt = new DataTransfer();
    const startOpts = { bubbles: true, cancelable: true, clientX: from.x, clientY: from.y, view: window };
    const endOpts = { bubbles: true, cancelable: true, clientX: to.x, clientY: to.y, view: window };

    if (from.el) {
      from.el.dispatchEvent(new PointerEvent("pointerdown", startOpts));
      from.el.dispatchEvent(new MouseEvent("mousedown", startOpts));
      from.el.dispatchEvent(new DragEvent("dragstart", { ...startOpts, dataTransfer: dt }));
    }

    await moveCursorTo(cur, to.x, to.y, 620);

    if (to.el) {
      to.el.dispatchEvent(new DragEvent("dragenter", { ...endOpts, dataTransfer: dt }));
      to.el.dispatchEvent(new DragEvent("dragover", { ...endOpts, dataTransfer: dt }));
      to.el.dispatchEvent(new DragEvent("drop", { ...endOpts, dataTransfer: dt }));
      to.el.dispatchEvent(new MouseEvent("mouseup", endOpts));
      to.el.dispatchEvent(new PointerEvent("pointerup", endOpts));
    }
    if (from.el) {
      from.el.dispatchEvent(new DragEvent("dragend", { ...endOpts, dataTransfer: dt }));
    }

    cur.svg.classList.remove("clicking");
    spawnClickRipple(to.x, to.y, cur.color);
    return { ok: true };
  }

  // =========================================================
  // WORKFLOW RECORDER (TEACH MODE — 0-CREDIT MACRO REPLAY)
  // =========================================================
  let isRecording = false;
  let recordedSteps = [];

  function buildSimpleSelector(el) {
    if (!el || el === document.body) return "body";
    if (el.id) return `#${CSS.escape(el.id)}`;
    const aria = el.getAttribute("aria-label");
    if (aria) return `${el.tagName.toLowerCase()}[aria-label="${aria.replace(/"/g, '\\"')}"]`;
    const name = el.getAttribute("name");
    if (name) return `${el.tagName.toLowerCase()}[name="${name.replace(/"/g, '\\"')}"]`;
    const ph = el.getAttribute("placeholder");
    if (ph) return `${el.tagName.toLowerCase()}[placeholder="${ph.replace(/"/g, '\\"')}"]`;
    return el.tagName.toLowerCase();
  }

  function onRecordClick(e) {
    if (!isRecording || (host && host.contains(e.target))) return;
    const el = e.target;
    const text = (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 60);
    recordedSteps.push({
      type: "click",
      selector: buildSimpleSelector(el),
      text,
      x: Math.round(e.clientX),
      y: Math.round(e.clientY),
    });
    updateIsland(`Записано шагов: ${recordedSteps.length}`, "Запись", "rec", "Стелла", "#ff2d55");
  }

  function onRecordChange(e) {
    if (!isRecording || (host && host.contains(e.target))) return;
    const el = e.target;
    if (!("value" in el)) return;
    recordedSteps.push({
      type: "type",
      selector: buildSimpleSelector(el),
      value: String(el.value || ""),
    });
    updateIsland(`Записано шагов: ${recordedSteps.length}`, "Запись", "rec", "Стелла", "#ff2d55");
  }

  function startRecording() {
    isRecording = true;
    recordedSteps = [];
    document.addEventListener("click", onRecordClick, true);
    document.addEventListener("change", onRecordChange, true);
    showOverlay({
      agentId: "rec",
      agentName: "Стелла",
      agentColor: "#ff2d55",
      edgeGlow: true,
      showCursor: false,
      status: "Запись сценария... Выполните действия",
    });
    return { ok: true };
  }

  function stopRecording() {
    isRecording = false;
    document.removeEventListener("click", onRecordClick, true);
    document.removeEventListener("change", onRecordChange, true);
    hideOverlay("rec");
    return { ok: true, steps: recordedSteps, url: location.href, title: document.title };
  }

  async function replayMacro(steps = []) {
    const meta = { agentId: "macro", agentName: "Стелла", agentColor: "#34c759" };
    showOverlay({ ...meta, edgeGlow: true, showCursor: true, status: "Воспроизвожу сценарий (0 кредитов)..." });

    for (let i = 0; i < steps.length; i++) {
      const st = steps[i];
      let el = null;
      if (st.selector) {
        const matches = Array.from(document.querySelectorAll(st.selector));
        el = st.text
          ? matches.find((n) => (n.innerText || n.textContent || "").includes(st.text)) || matches[0]
          : matches[0];
      }
      if (st.type === "click") {
        const r = el ? el.getBoundingClientRect() : null;
        const tx = r ? Math.round(r.left + r.width / 2) : st.x;
        const ty = r ? Math.round(r.top + r.height / 2) : st.y;
        await performClick(meta, null, tx, ty, `Шаг ${i + 1}/${steps.length}`);
      } else if (st.type === "type" && el) {
        const r = el.getBoundingClientRect();
        const cur = getOrCreateCursor(meta.agentId, meta.agentName, meta.agentColor);
        await moveCursorTo(cur, Math.round(r.left + r.width / 2), Math.round(r.top + r.height / 2), 420);
        el.focus();
        setNativeValue(el, st.value || "");
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
      }
      await sleep(360);
    }

    hideOverlay("macro");
    return { ok: true, count: steps.length };
  }

  // =========================================================
  // MESSAGE HANDLER
  // =========================================================
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    (async () => {
      try {
        switch (msg.type) {
          case "PING":
            sendResponse({ ok: true });
            return;

          case "SHOW_OVERLAY":
            showOverlay(msg.options || {});
            sendResponse({ ok: true });
            return;

          case "UPDATE_ISLAND":
            updateIsland(msg.text, msg.tag, msg.agentId, msg.agentName, msg.agentColor);
            sendResponse({ ok: true });
            return;

          case "HIDE_OVERLAY":
            hideOverlay(msg.agentId || null);
            sendResponse({ ok: true });
            return;

          case "SHOW_SOM_LABELS":
            showSomLabels();
            sendResponse({ ok: true });
            return;

          case "HIDE_SOM_LABELS":
            hideSomLabels();
            sendResponse({ ok: true });
            return;

          case "START_RECORDING":
            sendResponse(startRecording());
            return;

          case "STOP_RECORDING":
            sendResponse(stopRecording());
            return;

          case "REPLAY_MACRO":
            sendResponse(await replayMacro(msg.steps || []));
            return;

          case "OBSERVE_PAGE":
            sendResponse({ ok: true, data: observePage() });
            return;

          case "LOCAL_CLICK_TEXT": {
            const meta = {
              agentId: msg.agentId || "default",
              agentName: msg.agentName || "Стелла",
              agentColor: msg.agentColor || "#007aff",
            };
            sendResponse(await performLocalClickByText(meta, msg.query));
            return;
          }

          case "EXECUTE_ACTION": {
            const a = msg.action || {};
            const meta = {
              agentId: msg.agentId || "default",
              agentName: msg.agentName || "Стелла",
              agentColor: msg.agentColor || "#007aff",
            };
            if (a.type === "click") {
              sendResponse(await performClick(meta, a.elementId, a.x, a.y, a.label || "Нажимаю..."));
            } else if (a.type === "double_click") {
              sendResponse(await performDoubleClick(meta, a.elementId, a.x, a.y));
            } else if (a.type === "right_click") {
              sendResponse(await performRightClick(meta, a.elementId, a.x, a.y));
            } else if (a.type === "drag_drop") {
              sendResponse(await performDragDrop(meta, a.fromElementId, a.toElementId));
            } else if (a.type === "type") {
              sendResponse(await performType(meta, a.elementId, a.text, a.clearFirst !== false, !!a.pressEnter));
            } else if (a.type === "hover") {
              sendResponse(await performHover(meta, a.elementId));
            } else if (a.type === "scroll") {
              sendResponse(await performScroll(meta, a.direction, a.amount));
            } else if (a.type === "press_key") {
              sendResponse(await performKey(meta, a.key));
            } else if (a.type === "modify_dom") {
              if (a.css) {
                const st = document.createElement("style");
                st.setAttribute("data-stella-custom", "1");
                st.textContent = String(a.css);
                document.head.appendChild(st);
              }
              if (a.hideSelector) {
                document.querySelectorAll(a.hideSelector).forEach((el) => {
                  el.style.display = "none";
                });
              }
              if (a.insertHtml && a.targetSelector) {
                const target = document.querySelector(a.targetSelector);
                if (target) target.insertAdjacentHTML("beforeend", String(a.insertHtml));
              }
              sendResponse({ ok: true });
            } else {
              sendResponse({ ok: false, error: `Неизвестное действие: ${a.type}` });
            }
            return;
          }

          case "DEMO_MOTION":
            sendResponse(await runDemoMotion());
            return;

          default:
            sendResponse({ ok: false, error: "Unknown message type" });
        }
      } catch (err) {
        sendResponse({ ok: false, error: String(err?.message || err) });
      }
    })();

    return true;
  });
})();

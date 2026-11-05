import React, { useEffect, useRef, useState } from "react";
import { marked } from "marked";
import Icon from "./Icons.jsx";
import { parseEdits, applyEdits, compactHtml, protectUserCode, buildEditSystem, buildContext, IMAGE_RULES } from "./siteEdit.js";
import ImagePicker from "./ImagePicker.jsx";
import Prism from "prismjs";
import "prismjs/themes/prism-tomorrow.css";
import "prismjs/components/prism-python";
import "prismjs/components/prism-javascript";
import "prismjs/components/prism-jsx";
import "prismjs/components/prism-bash";
import "prismjs/components/prism-json";
import "prismjs/components/prism-rust";
import "prismjs/components/prism-go";
import "prismjs/components/prism-css";
import "prismjs/components/prism-markup";
import { streamChat } from "./llmClient.js";
import { cloudTarget, listModels, saveModel, savedModel } from "./cloud.js";
import { buildProCreatePrompt, buildProEditPrompt, commentAfterJson, specFromAnswer } from "./pro3d/prompt.js";
import { templateById } from "./pro3d/templates3d.js";
import ProBar from "./ProBar.jsx";


const EDIT_MAX_TOKENS = 3072;

const SMART_PROMPTS = [
  "✨ Добавь стеклянный эффект (Glassmorphism) и блюр",
  "📱 Сделай адаптивное бургер-меню для мобилок",
  "🌙 Добавь переключатель темы (Dark / Light) со скриптом",
  "🎨 Сделай сочные неоновые градиенты и подсветку кнопок",
  "⚡ Добавь интерактивные табы (вкладки) с переключением",
  "💬 Добавь всплывающее модальное окно обратной связи",
  "⭐️ Сделай блок отзывов с 5-звездочным рейтингом",
  "📊 Добавь карточки тарифов с переключателем Месяц/Год",
  "🚀 Добавь FAQ аккордеон с анимацией открытия",
  "🛒 Добавь блок корзины с подсчетом суммы заказа",
  "🎞️ Сделай плавную анимацию появления блоков при скролле",
  "🔥 Добавь бегущую строку (Marquee) с логотипами партнеров",
  "💎 Сделай 3D-эффект карточек при наведении курсора",
  "✉️ Добавь поле подписки на рассылку с валидацией",
  "⏱️ Добавь таймер обратного отсчета до конца акции",
  "🗺️ Добавь блок контактов с картой и формой заявки",
  "🎉 Добавь праздничные конфетти при нажатии на кнопку",
  "🔍 Сделай живой поиск по элементам каталога",
  "📈 Добавь счетчик статистики с цифрами 10k+, 99.9%",
  "🛡️ Добавь плашку с уведомлением о Cookies и согласии",
  "🎯 Сделай стильный Hero-блок с двумя кнопками CTA"
];

function formatTimeAgo(timestamp) {
  if (!timestamp) return "";
  const sec = Math.floor((Date.now() - new Date(timestamp).getTime()) / 1000);
  if (sec < 60) return "только что";
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} мин. назад`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} ч. назад`;
  const days = Math.floor(hr / 24);
  return `${days} дн. назад`;
}


const SYSTEM_SITE =
  "Ты — профессиональный веб-дизайнер и разработчик. Когда пользователь просит сайт, страницу или интерфейс: " +
  "выдай ПОЛНЫЙ самодостаточный HTML-документ. " +
  "ИСПОЛЬЗУЙ СОВРЕМЕННЫЕ БИБЛИОТЕКИ для лучшего результата: " +
  "1. Tailwind CSS через CDN: <script src=\"https://cdn.tailwindcss.com\"></script> в <head>. " +
  "2. Иконки Lucide: <script src=\"https://unpkg.com/lucide@latest\"></script> в <head>, " +
  "затем вызывай lucide.createIcons() в конце скрипта. " +
  "Используй современные шрифты (Inter, Montserrat) и сочные градиенты. " +
  "Структурируй страницу крупными блоками: header, hero, features, gallery, footer. " +
  "ПИШИ КОМПАКТНО: не более 6 секций и примерно 150-200 строк HTML, короткие тексты, без дублирования блоков — ответ должен генерироваться быстро. " +
  "CSS пиши в классах Tailwind, а специфичные стили — в <style> в <head>. " +
  "JS пиши одним <script> перед </body>. " +
  IMAGE_RULES + " " +
  "После блока кода добавь 1-2 предложения описания обычным текстом.";

function splitThink(text) {
  const m = text.match(/<think>([\s\S]*?)(?:<\/think>|$)/);
  if (!m) return { think: "", answer: text };
  return { think: m[1].trim(), answer: text.replace(m[0], "").trimStart() };
}

/** Last ```html fence (closed or still streaming) from model output. */
function extractHtml(text) {
  const re = /```html\s*\n?([\s\S]*?)(?:```|$)/g;
  let last = "";
  let m;
  while ((m = re.exec(text)) !== null) last = m[1];
  return last.trim();
}

function renderMarkdown(text) {
  return marked.parse(text, { breaks: true });
}

function CodeHtml({ html }) {
  const ref = useRef(null);
  useEffect(() => {
    if (ref.current) {
      ref.current.querySelectorAll("pre code").forEach((el) => {
        try {
          Prism.highlightElement(el);
        } catch {
          /* ignore */
        }
      });
    }
  }, [html]);

  const onClick = (e) => {
    const btn = e.target.closest("[data-copy]");
    if (!btn) return;
    const code = btn.parentElement?.querySelector("pre code");
    navigator.clipboard.writeText(code ? code.innerText : "").then(() => {
      btn.textContent = "Скопировано";
      setTimeout(() => (btn.textContent = "Копировать"), 1500);
    });
  };

  const withBtn = html.replace(
    /<pre>/g,
    '<div class="codewrap"><button data-copy>Копировать</button><pre>'
  );
  return (
    <div
      ref={ref}
      className="md"
      onClick={onClick}
      dangerouslySetInnerHTML={{ __html: withBtn.replace(/<\/pre>/g, "</pre></div>") }}
    />
  );
}

function ThinkBlock({ think, streaming, hasAnswer }) {
  if (!think && (hasAnswer || !streaming)) return null;
  return (
    <details className="think" open={streaming}>
      <summary>
        <Icon name="think" size={15} />
        {streaming && !hasAnswer ? "Думаю..." : "Ход мыслей"}
      </summary>
      <div className="think-body">{think || "···"}</div>
    </details>
  );
}

function Vibing({ floating, label = "Vibing...", note = "" }) {
  return (
    <div className={floating ? "vibing floating" : "vibing"}>
      <span className="vdot" />
      <span className="vdot" />
      <span className="vdot" />
      <span className="vlabel">{label}</span>
      {note && <span className="vnote">{note}</span>}
    </div>
  );
}

const OP_LABEL = { SEARCH: "Замена", INSERT_AFTER: "Вставка после", INSERT_BEFORE: "Вставка перед" };

function clip(text, n = 10) {
  const l = text.split("\n");
  return l.length > n ? [...l.slice(0, n), `… ещё ${l.length - n} строк`].join("\n") : text;
}

/** One search/replace or insert block, shown as a small diff card. */
function EditCard({ n, block, result }) {
  const pending = !block.complete;
  const ok = result && result.ok;
  const label = block.op === "SEARCH" && !block.replace.trim() ? "Удаление" : OP_LABEL[block.op];
  let chip = "…";
  if (pending) chip = "оборвано";
  else if (result) {
    chip = ok
      ? "применено" + (result.how === "fuzzy" ? " · без учёта пробелов" : "") + (result.many ? " · первое из нескольких" : "")
      : "фрагмент не найден";
  }
  return (
    <div className={"edit" + (result && !ok ? " bad" : "") + (pending ? " bad" : "")}>
      <div className="edit-head">
        <Icon name="edit" size={14} />
        <b>Правка {n}</b>
        <span>{label}</span>
        <em>{chip}</em>
      </div>
      <div className="edit-diff">
        {block.search && <div className={block.op === "SEARCH" ? "rm" : "ctx"}>{clip(block.search)}</div>}
        {block.replace && <div className="add">{clip(block.replace)}</div>}
      </div>
    </div>
  );
}

/**
 * While streaming the chat shows ONLY "Vibing..." (+think).
 * Tokens go to the live preview on the right; the full answer
 * appears in chat only when generation is done.
 * In edit mode the answer is split into text + diff cards.
 */
function AssistantMessage({ text, streaming, mode, results }) {
  const { think, answer } = splitThink(text);
  if (streaming) {
    const n = mode === "edit" ? parseEdits(answer).blocks.length : 0;
    return (
      <div className="assistant">
        <ThinkBlock think={think} streaming={streaming} hasAnswer={!!answer} />
        <Vibing label={mode === "edit" ? "Правлю сайт..." : "Vibing..."} note={n ? `правок: ${n}` : ""} />
      </div>
    );
  }
  const parsed = mode === "edit" ? parseEdits(answer) : null;
  if (!parsed || !parsed.segs.some((s) => s.type === "edit")) {
    return (
      <div className="assistant">
        {think && <ThinkBlock think={think} streaming={false} hasAnswer={true} />}
        <CodeHtml html={renderMarkdown(answer)} />
      </div>
    );
  }
  let n = 0;
  let ci = 0;
  const okN = results ? results.filter((r) => r.ok).length : 0;
  return (
    <div className="assistant">
      {think && <ThinkBlock think={think} streaming={false} hasAnswer={true} />}
      {parsed.segs.map((s, i) => {
        if (s.type === "text") return <CodeHtml key={i} html={renderMarkdown(s.text)} />;
        const num = ++n;
        return <EditCard key={i} n={num} block={s} result={s.complete && results ? results[ci++] : undefined} />;
      })}
      {results && (
        <div className={"edit-sum" + (okN < results.length || parsed.open ? " warn" : "")}>
          Применено правок: {okN} из {results.length}.
          {okN < results.length && " Не найденные фрагменты сайт не изменили — можно попросить повторить."}
          {parsed.open && " Ответ оборвался на последней правке, она не применена."}
        </div>
      )}
    </div>
  );
}

export default function Chat({
  siteMode,
  onPreview,
  getSite,
  onNewSite,
  selectedHtml = "",
  currentUser,
  apiKey = "",
  onAfterRequest,
  onAuthLost,
  onApplySpec,
  chatData,
  onSaveMessages,
  onOpenAuth,
  onOpenPlans,
}) {
  const [messages, setMessages] = useState(chatData?.messages || []);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const feedRef = useRef(null);
  const stickRef = useRef(true);
  const abortRef = useRef(null);
  const accRef = useRef("");
  // Context the routed cloud models offer (decides how big a site fits into edit mode).
  const ctxRef = useRef(16384);
  const hasSite = siteMode && !!(getSite && getSite());
  const [images, setImages] = useState([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [dismissed, setDismissed] = useState("");
  // 3D Pro: the AI always picks a professional template itself and fills texts + palette.
  const currentSite = siteMode && getSite ? getSite() || "" : "";
  const activeSpec = siteMode && chatData?.siteSpec && currentSite && currentSite === chatData.siteSpecHtml ? chatData.siteSpec : null;
  const selection = hasSite && selectedHtml && selectedHtml !== dismissed ? selectedHtml : "";
  const selTag = selection ? (selection.match(/^<\s*([a-z0-9-]+)/i) || [])[1] || "блок" : "";

  // Update messages when switching active chat
  useEffect(() => {
    setMessages(chatData?.messages || []);
  }, [chatData?.id]);


  // Models offered by the Stella Cloud server (the owner can restrict the list).
  const [models, setModels] = useState([]);
  const [model, setModel] = useState(() => savedModel());
  useEffect(() => {
    if (!apiKey) return undefined;
    let off = false;
    listModels(apiKey)
      .then((ids) => {
        if (off) return;
        setModels(ids);
        setModel((m) => (m && ids.includes(m) ? m : ids[0] || "auto"));
      })
      .catch(() => {});
    return () => {
      off = true;
    };
  }, [apiKey]);
  const activeModel = model || "auto";
  const providerLabel = "Stella Cloud";

  const onScroll = () => {
    const el = feedRef.current;
    if (!el) return;
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  };

  useEffect(() => {
    const el = feedRef.current;
    if (el && stickRef.current) el.scrollTop = el.scrollHeight;
  }, [messages, busy]);

  async function send() {
    const content = input.trim();
    if (!content || busy) return;
    setError("");

    if (!currentUser || !apiKey) {
      setError("Войдите через Telegram, чтобы отправлять запросы.");
      if (onOpenAuth) onOpenAuth();
      return;
    }


    const base = siteMode && getSite ? getSite() || "" : "";
    const editMode = siteMode && !!base.trim();
    const history = [...messages, { role: "user", content, timestamp: new Date().toISOString() }];
    const aiIndex = history.length;
    if (siteMode && onApplySpec && (activeSpec || !editMode)) return sendPro({ content, history, aiIndex, base, spec: activeSpec });
    const mode = editMode ? "edit" : "new";

    let apiMessages;
    let codes = [];
    if (editMode) {
      const prot = protectUserCode(content);
      codes = prot.codes;
      const requests = messages
        .filter((m) => m.role === "user")
        .slice(-4)
        .map((m) => m.content.replace(/```[\s\S]*?```/g, "[код]").slice(0, 160));
      // ~2.7 chars per token for html; keep room for rules, history, request and the answer
      const extra = buildContext({ selected: selection, images });
      const budget = Math.floor((ctxRef.current - EDIT_MAX_TOKENS - 450) * 2.7) - 1700 - prot.text.length - extra.length;
      const site = base.length > budget ? compactHtml(base) : base;
      if (site.length > budget) {
        setError(
          `Сайт слишком большой для режима правок: ${site.length} символов, лимит ≈ ${Math.max(budget, 0)}. ` +
            `Увеличь контекст сервера (переменная VIBE_CTX) или нажми «Новый сайт».`
        );
        return;
      }
      apiMessages = [
        { role: "system", content: buildEditSystem(site, requests) },
        { role: "user", content: extra + prot.text },
      ];
    } else {
      const plain = history.map(({ role, content: c }) => ({ role, content: c }));
      const extra = buildContext({ images });
      if (extra) plain[plain.length - 1].content = extra + plain[plain.length - 1].content;
      apiMessages = siteMode ? [{ role: "system", content: SYSTEM_SITE }, ...plain] : plain;
    }

    setMessages([...history, { role: "assistant", content: "", streaming: true, mode }]);
    setInput("");
    setImages([]);
    setPickerOpen(false);
    setBusy(true);
    stickRef.current = true;
    onPreview(editMode ? base : "", true, aiIndex, mode);

    const ctl = new AbortController();
    abortRef.current = ctl;
    accRef.current = "";
    const target = cloudTarget(apiKey, activeModel);
    let appliedN = 0;
    try {
      const r = await streamChat({
        target,
        messages: apiMessages,
        maxTokens: editMode ? EDIT_MAX_TOKENS : siteMode ? 8192 : 2048,
        temperature: editMode ? 0.3 : 0.7,
        signal: ctl.signal,
        onToken: (snapshot) => {
          accRef.current = snapshot;
          setMessages((prev) => {
            const next = [...prev];
            next[next.length - 1] = { role: "assistant", content: snapshot, streaming: true, mode };
            return next;
          });
          if (editMode) {
            // finished edit blocks are applied to the live preview as they arrive
            const answer = splitThink(snapshot).answer;
            const { blocks } = parseEdits(answer);
            if (blocks.length > appliedN) {
              appliedN = blocks.length;
              onPreview(applyEdits(base, blocks, codes).doc, true, aiIndex, "edit");
            } else if (!blocks.length && /```html/i.test(answer)) {
              onPreview(extractHtml(answer), true, aiIndex, "new");
            }
          } else {
            onPreview(extractHtml(snapshot), true, aiIndex, "new");
          }
        },
      });
      const acc = r.text;
      const final = {
        role: "assistant",
        content: acc,
        streaming: false,
        mode,
        timestamp: new Date().toISOString(),
        model: r.routedVia ? `${target.model} → ${r.routedVia}` : target.model,
        provider: "Stella Cloud",
      };
      if (editMode) {
        const answer = splitThink(acc).answer;
        const parsed = parseEdits(answer);
        if (parsed.blocks.length) {
          const { doc, results } = applyEdits(base, parsed.blocks, codes);
          final.results = results;
          onPreview(results.some((x) => x.ok) ? doc : base, false, aiIndex, "edit");
        } else if (/```html/i.test(answer) && extractHtml(answer)) {
          onPreview(extractHtml(answer), false, aiIndex, "new");
        } else {
          onPreview(base, false, aiIndex, "edit");
        }
      } else {
        onPreview(extractHtml(acc), false, aiIndex, "new");
      }
      setMessages((prev) => {
        const next = [...prev];
        next[next.length - 1] = final;
        if (onSaveMessages) onSaveMessages(next);
        return next;
      });
      if (onAfterRequest) onAfterRequest();
    } catch (e) {
      if (e.name === "AbortError") {
        // user pressed stop: keep what has been generated so far
        const part = accRef.current;
        setMessages((prev) => {
          const next = [...prev];
          next[next.length - 1] = { role: "assistant", content: part, streaming: false, mode };
          if (onSaveMessages) onSaveMessages(next);
          return next;
        });
        if (editMode) {
          const parsed = parseEdits(splitThink(part).answer);
          const res = parsed.blocks.length ? applyEdits(base, parsed.blocks, codes) : null;
          onPreview(res && res.results.some((x) => x.ok) ? res.doc : base, false, aiIndex, "edit");
        } else onPreview(extractHtml(part), false, aiIndex, "new");
        return;
      }
      setMessages((prev) => prev.slice(0, -1));
      setInput(content);
      if (e.status === 401 || e.status === 403) {
        setError(`${e.detail || e.message} Войдите через Telegram ещё раз.`);
        if (onAuthLost) onAuthLost();
      } else if (e.status === 429) {
        setError(`${e.detail || e.message} Лимит обновится завтра; тариф меняет администратор.`);
        if (onOpenPlans) onOpenPlans();
        if (onAfterRequest) onAfterRequest();
      } else {
        setError(`Stella Cloud: ${e.detail || e.message}`);
      }
      onPreview(editMode ? base : "", false, aiIndex, mode);
    } finally {
      setBusy(false);
    }
  }

  /** 3D Pro: one JSON answer → rendered professional site. */
  async function sendPro({ content, history, aiIndex, base, spec }) {
    const mode = spec ? "pro-edit" : "pro";
    const extra = buildContext({ images });
    const recent = messages
      .filter((m) => m.role === "user")
      .slice(-3)
      .map((m) => m.content.slice(0, 300));
    const apiMessages = [
      { role: "system", content: spec ? buildProEditPrompt(spec) : buildProCreatePrompt() },
      ...(spec || !recent.length ? [] : [{ role: "user", content: `Ранее я просил: ${recent.join(" / ")}` }]),
      { role: "user", content: extra + content },
    ];
    setMessages([...history, { role: "assistant", content: "", streaming: true, mode }]);
    setInput("");
    setImages([]);
    setPickerOpen(false);
    setBusy(true);
    stickRef.current = true;
    onPreview(base, true, aiIndex, spec ? "edit" : "new");
    const ctl = new AbortController();
    abortRef.current = ctl;
    accRef.current = "";
    const target = cloudTarget(apiKey, activeModel);
    const finish = (msg) =>
      setMessages((prev) => {
        const next = [...prev];
        next[next.length - 1] = msg;
        if (onSaveMessages) onSaveMessages(next);
        return next;
      });
    try {
      const r = await streamChat({
        target,
        messages: apiMessages,
        maxTokens: 4096,
        temperature: spec ? 0.4 : 0.8,
        signal: ctl.signal,
        onToken: (snapshot) => {
          accRef.current = snapshot;
        },
      });
      const next = specFromAnswer(r.text);
      if (!next) {
        finish({ role: "assistant", content: "Модель ответила не в том формате, сайт не изменён. Попробуйте ещё раз, выберите другую модель или выключите «3D Pro».", streaming: false, mode, timestamp: new Date().toISOString() });
        onPreview(base, false, aiIndex, "edit");
        return;
      }
      onApplySpec(next, aiIndex);
      const tpl = templateById(next.template);
      const comment = commentAfterJson(r.text);
      finish({
        role: "assistant",
        content: `${comment || (spec ? "Готово, изменения применены." : "Готово! Сайт собран.")}\n\n**Шаблон:** ${tpl?.name || next.template} · 3D: ${tpl?.desc?.split(" — ")[0] || ""}`,
        streaming: false,
        mode,
        timestamp: new Date().toISOString(),
        model: r.routedVia ? `${target.model} → ${r.routedVia}` : target.model,
        provider: "Stella Cloud",
      });
      if (onAfterRequest) onAfterRequest();
    } catch (e) {
      if (e.name === "AbortError") {
        finish({ role: "assistant", content: "Остановлено.", streaming: false, mode });
        onPreview(base, false, aiIndex, "edit");
        return;
      }
      setMessages((prev) => prev.slice(0, -1));
      setInput(content);
      if (e.status === 401 || e.status === 403) {
        setError(`${e.detail || e.message} Войдите через Telegram ещё раз.`);
        if (onAuthLost) onAuthLost();
      } else if (e.status === 429) {
        setError(`${e.detail || e.message} Лимит обновится завтра; тариф меняет администратор.`);
        if (onOpenPlans) onOpenPlans();
        if (onAfterRequest) onAfterRequest();
      } else setError(`Stella Cloud: ${e.detail || e.message}`);
      onPreview(base, false, aiIndex, "edit");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="chat">
      <div className="apirow" title="Модели работают на сервере Stella Cloud">
        <span className="pulse-dot" />
        <span className="apirow-name">{providerLabel}</span>
        {models.length > 1 ? (
          <select
            className="apirow-select"
            value={activeModel}
            onChange={(e) => {
              setModel(e.target.value);
              saveModel(e.target.value);
            }}
            aria-label="Модель"
          >
            {models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        ) : (
          <span className="apirow-model">{activeModel}</span>
        )}
      </div>

      <div className="feed" ref={feedRef} onScroll={onScroll}>
        <div className="column">
          {messages.length === 0 && (
            <div className="hero">
              <div className="hero-logo"><Icon name="logo" size={34} /></div>
              <h1>Vibecode v1</h1>
              <p>{siteMode ? "Опиши сайт — соберу его справа вживую." : `${providerLabel} · ${activeModel}. Спроси что-нибудь.`}</p>
            </div>
          )}
          {messages.map((m, i) =>
            m.role === "user" ? (
              <div key={i} className="row user">
                <div className="bubble">
                  {m.content}
                  {m.timestamp && <span className="bubble-time">{formatTimeAgo(m.timestamp)}</span>}
                </div>
              </div>
            ) : (
              <div key={i} className="row assistant-row">
                <div className="avatar"><Icon name="logo" size={16} /></div>
                <div className="assistant-wrap">
                  {m.content ? (
                    <>
                      <AssistantMessage text={m.content} streaming={!!m.streaming} mode={m.mode} results={m.results} />
                      {m.timestamp && (
                        <div className="assistant-time-tag">
                          <span>Ответил: {formatTimeAgo(m.timestamp)}</span>
                          {m.model && <span className="assistant-model-tag" title={m.provider}>· {m.model}</span>}
                        </div>
                      )}
                    </>
                  ) : m.streaming ? (
                    <Vibing label={m.mode === "pro" ? "Подбираю 3D-шаблон и пишу тексты..." : m.mode === "pro-edit" ? "Обновляю 3D-сайт..." : m.mode === "edit" ? "Правлю сайт..." : "Vibing..."} />
                  ) : (
                    <div className="vlabel">Пустой ответ. Попробуй ещё раз.</div>
                  )}
                </div>
              </div>
            )
          )}
          {error && <div className="err">{error}</div>}
        </div>
      </div>

      <div className="dock">
        <div className="column">
          {activeSpec && <ProBar spec={activeSpec} disabled={busy} onChange={(next) => onApplySpec(next)} onNewSite={onNewSite} />}
          {hasSite && !activeSpec && (
            <div className="editbar">
              <span className="editbar-dot" />
              <span>Правлю текущий сайт, а не создаю заново</span>
              <button onClick={onNewSite} disabled={busy}>Новый сайт</button>
            </div>
          )}
          {selection && (
            <div className="selchip" title={selection.slice(0, 400)}>
              <Icon name="move" size={13} />
              <span>Выбрано: <b>&lt;{selTag}&gt;</b> — правка коснётся его</span>
              <button onClick={() => setDismissed(selection)} aria-label="Снять выбор">×</button>
            </div>
          )}
          {images.length > 0 && (
            <div className="imgchips">
              {images.map((im) => (
                <span key={im.id} className="imgchip">
                  <img src={im.url} alt="" />
                  <button onClick={() => setImages((l) => l.filter((x) => x.id !== im.id))} aria-label="Убрать фото">×</button>
                </span>
              ))}
            </div>
          )}
          {siteMode && (
            <div className="dock-tools">
              <button data-photo-btn onClick={() => setPickerOpen((v) => !v)} disabled={busy}>
                <Icon name="image" size={14} />
                Добавить фото{images.length ? ` (${images.length})` : ""}
              </button>
              {pickerOpen && <ImagePicker images={images} onChange={setImages} onClose={() => setPickerOpen(false)} />}
            </div>
          )}
          {/* Quick Smart Prompt Chips */}
          <div className="prompt-chips-carousel">
            {SMART_PROMPTS.map((p, idx) => (
              <button
                key={idx}
                type="button"
                className="prompt-chip-btn"
                onClick={() => setInput(p.replace(/^[^\s]+\s/, ""))}
                disabled={busy}
              >
                {p}
              </button>
            ))}
          </div>

          <div className="composer">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder={siteMode ? (hasSite ? "Что поменять? Например: добавь в шапку кнопку «Заказать»..." : "Опиши сайт или выбери быстрый чип выше...") : "Спросить что-нибудь..."}
              disabled={busy}
              rows={1}
            />
            <button onClick={busy ? () => abortRef.current && abortRef.current.abort() : send} disabled={!busy && !input.trim()} aria-label={busy ? "Остановить" : "Отправить"}>
              {busy ? <Icon name="stop" size={14} /> : <Icon name="up" size={18} />}
            </button>
          </div>
          <div className="hint">Enter — отправить · Shift+Enter — новая строка</div>
        </div>
      </div>
    </div>
  );
}
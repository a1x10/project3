import React, { useEffect, useRef, useState } from "react";
import { marked } from "marked";
import Icon from "./Icons.jsx";
import { cloudUrl } from "./cloud.js";

// «Разработка»: STELLA CODER (coding agent) running on this computer inside a project folder.
// It writes code from scratch, edits and refactors, runs commands and tests, fixes bugs, works with git,
// writes docs and automates routine — like a senior engineer, with your approval for risky actions.

const FOLDER_KEY = "vibing-dev-folder";
const RECENT_KEY = "vibing-dev-recent";
const MODE_KEY = "vibing-dev-mode";

const MODES = [
  { id: "default", label: "Спрашивать разрешение", hint: "Агент спрашивает перед изменением файлов и командами" },
  { id: "acceptEdits", label: "Править файлы сам", hint: "Файлы меняет без вопросов, команды — с разрешения" },
  { id: "auto", label: "Автономно", hint: "Безопасные действия сам, рискованные — с разрешения" },
  { id: "plan", label: "Сначала план", hint: "Изучает проект и предлагает план, ничего не меняя" },
];

const QUICK = [
  "🤖 Сделай Telegram-бота на Python (aiogram 3): меню, команды /start и /help, обработка кнопок, README как запустить",
  "💬 Сделай WhatsApp-бота на Node.js (whatsapp-web.js) с автоответами и вход по QR-коду",
  "🌐 Создай MVP веб-приложения: фронтенд на React, API на Node.js, база SQLite, инструкция запуска",
  "🧪 Изучи проект, напиши тесты для непокрытого кода и запусти их, пока не пройдут",
  "🐞 Найди и исправь ошибки: запусти сборку, линтер и тесты, разберись с падениями",
  "♻️ Проведи рефакторинг: наведи порядок в структуре, убери дублирование, ничего не сломав",
  "📝 Объясни, как устроен этот проект, и напиши README и CLAUDE.md с описанием",
  "🔀 Посмотри изменения и сделай осмысленный git-коммит",
  "⚙️ Настрой GitHub Actions: сборка и тесты на каждый push",
  "🗂 Разбери файлы в этой папке и разложи их по понятным папкам",
];

const read = (k, d) => {
  try {
    return localStorage.getItem(k) ?? d;
  } catch {
    return d;
  }
};
const write = (k, v) => {
  try {
    localStorage.setItem(k, v);
  } catch {
    /* ignore */
  }
};
const baseName = (p) => String(p || "").split(/[\\/]/).filter(Boolean).pop() || p;
const md = (t) => ({ __html: marked.parse(String(t || ""), { breaks: true }) });

export default function DevMode({ apiKey, onOpenAuth, onAuthLost }) {
  const bridge = typeof window !== "undefined" ? window.stellaDesktop?.agent : undefined;
  const [folder, setFolder] = useState(() => read(FOLDER_KEY, ""));
  const [recent, setRecent] = useState(() => {
    try {
      return JSON.parse(read(RECENT_KEY, "[]"));
    } catch {
      return [];
    }
  });
  const [mode, setMode] = useState(() => read(MODE_KEY, "default"));
  const [status, setStatus] = useState("idle"); // idle | starting | ready | running
  const [statusText, setStatusText] = useState("");
  const [items, setItems] = useState([]);
  const [todos, setTodos] = useState([]);
  const [changed, setChanged] = useState([]);
  const [input, setInput] = useState("");
  const pendingPrompt = useRef(null);
  const feedRef = useRef(null);
  const liveText = useRef(-1);

  const push = (item) => setItems((l) => [...l, item]);
  const update = (pred, patch) => setItems((l) => l.map((x) => (pred(x) ? { ...x, ...patch } : x)));

  useEffect(() => {
    const el = feedRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [items, statusText]);

  useEffect(() => {
    if (!bridge) return undefined;
    return bridge.onMessage((m) => {
      if (m.type === "ready") {
        setStatus(pendingPrompt.current ? "running" : "ready");
        (m.warnings || []).forEach((w) => push({ kind: "note", level: "warn", text: w }));
        if (pendingPrompt.current) {
          bridge.send({ type: "prompt", text: pendingPrompt.current });
          pendingPrompt.current = null;
        }
      } else if (m.type === "event") onEvent(m.event);
      else if (m.type === "permission_request") push({ kind: "perm", id: m.id, summary: m.summary, reason: m.reason, tool: m.tool });
      else if (m.type === "plan_request") push({ kind: "plan", id: m.id, plan: m.plan });
      else if (m.type === "question") push({ kind: "question", id: m.id, question: m.question, options: m.options || [] });
      else if (m.type === "done") {
        liveText.current = -1;
        setStatus("ready");
        setStatusText("");
      } else if (m.type === "error") {
        push({ kind: "note", level: "error", text: m.message });
        if (/401|403|Не выполнен вход/.test(m.message || "") && onAuthLost) onAuthLost();
        if (m.fatal) setStatus("idle");
        else setStatus((s) => (s === "running" ? "ready" : s));
        setStatusText("");
      } else if (m.type === "exit") {
        setStatus("idle");
        setStatusText("");
        liveText.current = -1;
        if (m.code) push({ kind: "note", level: "error", text: `Агент завершился с ошибкой (код ${m.code}). ${m.stderr || ""}` });
      }
    });
  }, [bridge]);

  function onEvent(ev) {
    if (!ev) return;
    const sub = ev.agentId && ev.agentId !== "main";
    switch (ev.type) {
      case "text_delta":
        if (sub) return;
        setItems((l) => {
          const i = liveText.current;
          if (i >= 0 && l[i]?.kind === "text") {
            const next = [...l];
            next[i] = { ...next[i], text: next[i].text + ev.text };
            return next;
          }
          liveText.current = l.length;
          return [...l, { kind: "text", text: ev.text }];
        });
        break;
      case "text_reset":
        if (sub) return;
        setItems((l) => (liveText.current >= 0 && l[liveText.current]?.kind === "text" ? l.filter((_, i) => i !== liveText.current) : l));
        liveText.current = -1;
        break;
      case "tool_call":
        liveText.current = -1;
        push({ kind: "tool", id: ev.id, name: ev.name, summary: ev.summary, state: "run", sub });
        break;
      case "tool_progress":
        update((x) => x.kind === "tool" && x.id === ev.id, { progress: String(ev.text).slice(-300) });
        break;
      case "tool_result":
        update((x) => x.kind === "tool" && x.id === ev.id, { state: ev.isError ? "err" : "ok", output: String(ev.content || "").slice(0, 1500), ms: ev.durationMs });
        if (ev.filesChanged?.length) setChanged((c) => [...new Set([...ev.filesChanged, ...c])].slice(0, 200));
        break;
      case "status":
        setStatusText(ev.text);
        break;
      case "todos":
        if (!sub) setTodos(ev.todos || []);
        break;
      case "subagent":
        push({ kind: "note", level: "info", text: `Помощник «${ev.name}»: ${ev.description} — ${ev.status}` });
        break;
      case "notification":
        if (ev.level !== "info") push({ kind: "note", level: ev.level, text: ev.text });
        break;
      default:
    }
  }

  const answer = (item, value, label) => {
    bridge.send({ type: "answer", id: item.id, value });
    update((x) => x.id === item.id && x.kind === item.kind, { answered: label });
  };

  async function chooseFolder() {
    const p = await bridge.pickFolder();
    if (!p) return;
    if (status !== "idle") await bridge.stop();
    setStatus("idle");
    setFolder(p);
    write(FOLDER_KEY, p);
    const r = [p, ...recent.filter((x) => x !== p)].slice(0, 6);
    setRecent(r);
    write(RECENT_KEY, JSON.stringify(r));
    setItems([]);
    setChanged([]);
    setTodos([]);
  }

  async function start(resume = false) {
    if (!apiKey) {
      onOpenAuth?.();
      return false;
    }
    setStatus("starting");
    setStatusText("Запускаю агента…");
    const r = await bridge.start({ cwd: folder, mode, resume, cloudUrl: cloudUrl(), apiKey });
    if (!r.ok) {
      push({ kind: "note", level: "error", text: r.error });
      setStatus("idle");
      setStatusText("");
      return false;
    }
    return true;
  }

  async function send(textArg) {
    const text = (textArg ?? input).trim();
    if (!text || !folder || status === "running" || status === "starting") return;
    setInput("");
    push({ kind: "user", text });
    if (status === "idle") {
      pendingPrompt.current = text;
      await start(false);
      return;
    }
    setStatus("running");
    bridge.send({ type: "prompt", text });
  }

  const stop = () => {
    bridge.send({ type: "interrupt" });
    setStatusText("Останавливаю…");
  };

  const changeMode = (m) => {
    setMode(m);
    write(MODE_KEY, m);
    if (status !== "idle") bridge.send({ type: "mode", mode: m });
  };

  if (!bridge) {
    return (
      <div className="dev-empty">
        <Icon name="code" size={34} />
        <h2>Разработка доступна в приложении для Windows</h2>
        <p>Агент работает с файлами и командами на вашем компьютере, поэтому этот режим есть только в установленном Vibing AI Studio.</p>
      </div>
    );
  }

  const busy = status === "running" || status === "starting";
  return (
    <div className="dev">
      <section className="dev-main">
        <div className="dev-feed" ref={feedRef}>
          {!items.length && (
            <div className="dev-hero">
              <div className="dev-hero-ico">
                <Icon name="code" size={30} />
              </div>
              <h1>Разработка с ИИ-агентом</h1>
              <p>
                Опишите задачу — агент сам напишет код с нуля, поправит существующий, запустит команды и тесты, исправит ошибки, сделает git-коммит и документацию.
                {folder ? (
                  <>
                    {" "}
                    Работаю в папке <b>{baseName(folder)}</b>.
                  </>
                ) : (
                  " Сначала выберите папку проекта (можно пустую для нового проекта)."
                )}
              </p>
              {!folder && (
                <button className="dev-btn primary" onClick={chooseFolder}>
                  <Icon name="folder" size={15} /> Выбрать папку проекта
                </button>
              )}
              {folder && (
                <div className="dev-quick">
                  {QUICK.map((q) => (
                    <button key={q} onClick={() => send(q)} disabled={busy}>
                      {q}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          {items.map((it, i) => {
            if (it.kind === "user")
              return (
                <div key={i} className="dev-user">
                  {it.text}
                </div>
              );
            if (it.kind === "text") return <div key={i} className="dev-text md" dangerouslySetInnerHTML={md(it.text)} />;
            if (it.kind === "tool")
              return (
                <details key={i} className={`dev-tool ${it.state}`}>
                  <summary>
                    <span className="dot" />
                    <b>{it.name}</b> <span className="sum">{it.summary}</span>
                    {it.sub && <em>помощник</em>}
                    {it.ms ? <small>{(it.ms / 1000).toFixed(1)} с</small> : null}
                  </summary>
                  {(it.output || it.progress) && <pre>{it.output || it.progress}</pre>}
                </details>
              );
            if (it.kind === "perm")
              return (
                <div key={i} className="dev-card perm">
                  <div className="dev-card-title">
                    <Icon name="shield" size={15} /> Разрешить действие?
                  </div>
                  <code>{it.summary}</code>
                  <small>{it.reason}</small>
                  {it.answered ? (
                    <div className="dev-answered">{it.answered}</div>
                  ) : (
                    <div className="dev-actions">
                      <button className="dev-btn primary" onClick={() => answer(it, { decision: "allow_once" }, "Разрешено один раз")}>
                        Разрешить
                      </button>
                      <button className="dev-btn" onClick={() => answer(it, { decision: "allow_session" }, "Разрешено до конца сессии")}>
                        Разрешать в этой сессии
                      </button>
                      <button className="dev-btn danger" onClick={() => answer(it, { decision: "deny" }, "Запрещено")}>
                        Запретить
                      </button>
                    </div>
                  )}
                </div>
              );
            if (it.kind === "plan")
              return (
                <div key={i} className="dev-card plan">
                  <div className="dev-card-title">
                    <Icon name="think" size={15} /> План работы
                  </div>
                  <div className="md" dangerouslySetInnerHTML={md(it.plan)} />
                  {it.answered ? (
                    <div className="dev-answered">{it.answered}</div>
                  ) : (
                    <div className="dev-actions">
                      <button className="dev-btn primary" onClick={() => answer(it, { decision: "approve", mode: "acceptEdits" }, "План одобрен")}>
                        Выполнить план
                      </button>
                      <button className="dev-btn danger" onClick={() => answer(it, { decision: "reject", feedback: "Пользователь отклонил план" }, "План отклонён")}>
                        Отклонить
                      </button>
                    </div>
                  )}
                </div>
              );
            if (it.kind === "question")
              return (
                <div key={i} className="dev-card">
                  <div className="dev-card-title">
                    <Icon name="sparkles" size={15} /> {it.question}
                  </div>
                  {it.answered ? (
                    <div className="dev-answered">{it.answered}</div>
                  ) : (
                    <div className="dev-actions">
                      {it.options.map((o) => (
                        <button key={o} className="dev-btn" onClick={() => answer(it, o, o)}>
                          {o}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              );
            return (
              <div key={i} className={`dev-note ${it.level}`}>
                {it.text}
              </div>
            );
          })}
          {busy && <div className="dev-status">{statusText || "Работаю…"}</div>}
        </div>
        <div className="dev-composer">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder={folder ? "Что сделать? Например: сделай телеграм-бота для записи клиентов" : "Сначала выберите папку проекта справа"}
            disabled={!folder}
            rows={3}
          />
          {busy ? (
            <button className="dev-send stop" onClick={stop} title="Остановить">
              ■
            </button>
          ) : (
            <button className="dev-send" onClick={() => send()} disabled={!folder || !input.trim()} title="Отправить">
              <Icon name="send" size={16} />
            </button>
          )}
        </div>
      </section>

      <aside className="dev-side">
        <div className="dev-block">
          <h4>Проект</h4>
          {folder ? (
            <div className="dev-folder" title={folder}>
              <Icon name="folder" size={15} /> <span>{baseName(folder)}</span>
            </div>
          ) : (
            <p className="dev-muted">Папка не выбрана</p>
          )}
          <div className="dev-actions">
            <button className="dev-btn" onClick={chooseFolder} disabled={busy}>
              {folder ? "Другая папка" : "Выбрать папку"}
            </button>
            {folder && (
              <button className="dev-btn" onClick={() => bridge.openPath(folder)}>
                Открыть
              </button>
            )}
          </div>
          {recent.length > 1 && (
            <div className="dev-recent">
              {recent
                .filter((r) => r !== folder)
                .map((r) => (
                  <button
                    key={r}
                    onClick={async () => {
                      if (status !== "idle") await bridge.stop();
                      setStatus("idle");
                      setFolder(r);
                      write(FOLDER_KEY, r);
                      setItems([]);
                      setChanged([]);
                      setTodos([]);
                    }}
                    disabled={busy}
                    title={r}
                  >
                    {baseName(r)}
                  </button>
                ))}
            </div>
          )}
          {folder && status === "idle" && (
            <button className="dev-link" onClick={async () => (await start(true)) && push({ kind: "note", level: "info", text: "Продолжаю прошлую сессию в этой папке." })}>
              Продолжить прошлую сессию
            </button>
          )}
        </div>

        <div className="dev-block">
          <h4>Режим</h4>
          {MODES.map((m) => (
            <label key={m.id} className={`dev-mode ${mode === m.id ? "on" : ""}`}>
              <input type="radio" name="dev-mode" checked={mode === m.id} onChange={() => changeMode(m.id)} />
              <span>
                <b>{m.label}</b>
                <small>{m.hint}</small>
              </span>
            </label>
          ))}
        </div>

        {todos.length > 0 && (
          <div className="dev-block">
            <h4>План задач</h4>
            <ul className="dev-todos">
              {todos.map((t, i) => (
                <li key={i} className={t.status}>
                  {t.status === "completed" ? "✓" : t.status === "in_progress" ? "▸" : "○"} {t.status === "in_progress" ? t.activeForm || t.content : t.content}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="dev-block">
          <h4>Изменённые файлы {changed.length ? `(${changed.length})` : ""}</h4>
          {changed.length ? (
            <ul className="dev-files">
              {changed.map((f) => (
                <li key={f} title={f} onClick={() => bridge.openPath(f)}>
                  {f.startsWith(folder) ? f.slice(folder.length).replace(/^[\\/]/, "") : f}
                </li>
              ))}
            </ul>
          ) : (
            <p className="dev-muted">Пока ничего</p>
          )}
        </div>
        <p className="dev-muted small">Модель: auto:smart (Stella Cloud). Агент работает только в выбранной папке; опасные действия — с вашего разрешения.</p>
      </aside>
    </div>
  );
}

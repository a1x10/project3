import React, { useEffect, useRef, useState } from "react";
import Icon from "./Icons.jsx";
import { cloudUrl, openExternal, pollLogin, saveCredentials, setCloudUrl, startLogin } from "./cloud.js";

const fmt = (n) => (n === null || n === undefined ? "∞" : Number(n).toLocaleString("ru-RU"));

/** Sign in through the Telegram bot: show a code, open the bot, wait for approval. */
export function CloudLoginModal({ isOpen, onClose, onLoggedIn }) {
  const [req, setReq] = useState(null);
  const [state, setState] = useState("idle"); // idle | waiting | denied | expired | error
  const [error, setError] = useState("");
  const [server, setServer] = useState(cloudUrl());
  const [editServer, setEditServer] = useState(!cloudUrl());
  const timer = useRef(null);

  const begin = async () => {
    clearTimeout(timer.current);
    setError("");
    const base = server.trim().replace(/\/$/, "");
    if (!/^https?:\/\//.test(base)) {
      setEditServer(true);
      setState("error");
      setError("Укажите адрес сервера Stella Cloud, например https://ai.example.com");
      return;
    }
    setState("starting");
    try {
      const r = await startLogin(base);
      setCloudUrl(base);
      setReq({ ...r, base });
      setState("waiting");
      if (r.link) openExternal(r.link);
    } catch (e) {
      setState("error");
      setError(e.message);
    }
  };

  useEffect(() => {
    if (!isOpen) {
      clearTimeout(timer.current);
      setState("idle");
      setReq(null);
      return undefined;
    }
    if (cloudUrl()) begin();
    return () => clearTimeout(timer.current);
  }, [isOpen]);

  useEffect(() => {
    if (state !== "waiting" || !req) return undefined;
    let alive = true;
    const tick = async () => {
      try {
        const r = await pollLogin(req.id, req.base);
        if (!alive) return;
        if (r.status === "approved" && r.apiKey) {
          const creds = { apiKey: r.apiKey, user: r.user, server: req.base };
          await saveCredentials(creds);
          onLoggedIn(creds);
          onClose();
          return;
        }
        if (r.status === "denied") return setState("denied");
        if (r.status === "expired" || r.status === "unknown") return setState("expired");
      } catch {
        /* keep polling through network hiccups */
      }
      if (alive) timer.current = setTimeout(tick, (req.interval || 2) * 1000);
    };
    timer.current = setTimeout(tick, 1200);
    return () => {
      alive = false;
      clearTimeout(timer.current);
    };
  }, [state, req]);

  if (!isOpen) return null;
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card auth-modal cloud-login" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title">
            <span className="modal-icon-badge">
              <Icon name="logo" size={20} />
            </span>
            <h3>Вход через Telegram</h3>
          </div>
          <button className="modal-close" onClick={onClose} aria-label="Закрыть">
            <Icon name="close" size={14} />
          </button>
        </div>
        <div className="modal-form">
          {editServer ? (
            <div className="form-group">
              <label>Сервер Stella Cloud</label>
              <input className="modal-input" value={server} onChange={(e) => setServer(e.target.value)} placeholder="https://ai.example.com" spellCheck={false} />
            </div>
          ) : (
            <div className="cloud-server-line">
              Сервер: <b>{server}</b>{" "}
              <button type="button" className="linklike" onClick={() => setEditServer(true)}>
                изменить
              </button>
            </div>
          )}
          {error && <div className="form-alert error">{error}</div>}
          {state === "starting" && <p className="cloud-muted">Получаем код…</p>}
          {state === "waiting" && req && (
            <>
              <p className="cloud-muted">
                Откройте бота{req.botUsername ? <b> @{req.botUsername}</b> : ""} и нажмите «Подтвердить вход». Новый аккаунт создаётся автоматически. Код:
              </p>
              <div className="cloud-code" data-testid="login-code">
                {req.code}
              </div>
              {req.link ? (
                <button className="submit-btn" onClick={() => openExternal(req.link)}>
                  Открыть Telegram
                </button>
              ) : (
                <div className="form-alert error">На сервере не настроен Telegram-бот.</div>
              )}
              <p className="cloud-muted small">
                Или отправьте боту: <code>/login {req.code}</code>
              </p>
              <p className="cloud-muted small cloud-pulse">Ждём подтверждения…</p>
            </>
          )}
          {(state === "denied" || state === "expired") && <div className={`form-alert ${state === "denied" ? "error" : ""}`}>{state === "denied" ? "Вход отклонён в Telegram." : "Код устарел."}</div>}
          {state !== "waiting" && state !== "starting" && (
            <button className="submit-btn" onClick={begin}>
              {state === "idle" || state === "error" ? "Получить код" : "Получить новый код"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function Meter({ label, used, limit }) {
  const pct = limit === null || limit === undefined ? 100 : Math.min(100, (used / Math.max(1, limit)) * 100);
  return (
    <div className="cloud-meter">
      <div className="cloud-meter-head">
        <span>{label}</span>
        <span>
          <b>{fmt(used)}</b> / {fmt(limit)}
        </span>
      </div>
      <div className="cloud-bar">
        <div className={`cloud-fill ${limit !== null && pct > 90 ? "hot" : ""}`} style={{ width: `${pct}%`, opacity: limit === null ? 0.3 : 1 }} />
      </div>
    </div>
  );
}

/** Account, plan and limits (managed on the server; changes happen in the bot / admin panel). */
export function AccountModal({ isOpen, onClose, user, onLogout, onRefresh }) {
  useEffect(() => {
    if (isOpen) onRefresh?.();
  }, [isOpen]);
  if (!isOpen || !user) return null;
  const p = user.planInfo || {};
  const base = cloudUrl();
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card auth-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title">
            <span className="modal-icon-badge">
              <Icon name="crown" size={20} />
            </span>
            <h3>{user.name}</h3>
          </div>
          <button className="modal-close" onClick={onClose} aria-label="Закрыть">
            <Icon name="close" size={14} />
          </button>
        </div>
        <div className="modal-form">
          <div className="cloud-muted">
            {user.username ? `@${user.username} · ` : ""}
            {user.role === "admin" ? "администратор" : "пользователь"} · тариф <b>{p.name || user.plan}</b>
          </div>
          <Meter label="Запросы сегодня" used={user.usageToday?.requests ?? 0} limit={p.dailyRequests ?? null} />
          <Meter label="Токены сегодня" used={user.usageToday?.tokens ?? 0} limit={p.dailyTokens ?? null} />
          <p className="cloud-muted small">Тариф меняет администратор. Ключи, история и удаление аккаунта — в личном кабинете или в Telegram-боте.</p>
          <div className="cloud-actions">
            <button className="submit-btn" onClick={() => openExternal(`${base}/#/cabinet`)}>
              Личный кабинет
            </button>
            {user.role === "admin" && (
              <button className="submit-btn secondary" onClick={() => openExternal(`${base}/#/admin`)}>
                Админ-панель
              </button>
            )}
          </div>
          <button className="user-logout-btn wide" onClick={onLogout}>
            Выйти из аккаунта
          </button>
        </div>
      </div>
    </div>
  );
}

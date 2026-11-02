import React, { useEffect, useRef, useState } from 'react';
import { api } from './api.js';

/** Telegram device-flow: get a code, approve it in the bot, poll for the session. */
export default function LoginModal({ config, onClose, onDone }) {
  const [req, setReq] = useState(null);
  const [state, setState] = useState('starting'); // starting | waiting | denied | expired | error
  const [error, setError] = useState('');
  const timer = useRef(null);

  const start = async () => {
    clearTimeout(timer.current);
    setState('starting');
    setError('');
    try {
      const r = await api('/api/auth/start', { body: { client: 'web', kind: 'session', device: navigator.userAgent.includes('Windows') ? 'Браузер · Windows' : 'Браузер' }, token: '' });
      setReq(r);
      setState('waiting');
    } catch (e) {
      setError(e.message);
      setState('error');
    }
  };

  useEffect(() => {
    start();
    return () => clearTimeout(timer.current);
  }, []);

  useEffect(() => {
    if (state !== 'waiting' || !req) return;
    let alive = true;
    const tick = async () => {
      try {
        const r = await api(`/api/auth/poll?id=${encodeURIComponent(req.id)}`, { token: '' });
        if (!alive) return;
        if (r.status === 'approved' && r.token) return onDone(r.token);
        if (r.status === 'denied') return setState('denied');
        if (r.status === 'expired' || r.status === 'unknown') return setState('expired');
      } catch {
        /* network hiccup — keep polling */
      }
      if (alive) timer.current = setTimeout(tick, (req.interval || 2) * 1000);
    };
    timer.current = setTimeout(tick, 1500);
    return () => {
      alive = false;
      clearTimeout(timer.current);
    };
  }, [state, req, onDone]);

  const bot = req?.botUsername || config?.botUsername;
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-label="Вход через Telegram">
        <button className="close" onClick={onClose} aria-label="Закрыть">
          ×
        </button>
        <h2>Вход через Telegram</h2>
        {state === 'starting' && <p className="muted">Готовим код…</p>}
        {state === 'error' && (
          <>
            <p className="err">{error}</p>
            <button className="btn" onClick={start}>
              Повторить
            </button>
          </>
        )}
        {state === 'waiting' && req && (
          <>
            <ol className="steps">
              <li>
                Откройте бота{bot ? <> <b>@{bot}</b></> : ''} — новый аккаунт создастся автоматически.
              </li>
              <li>Подтвердите вход кнопкой в чате. Код должен совпадать:</li>
            </ol>
            <div className="code" data-testid="login-code">
              {req.code}
            </div>
            {req.link ? (
              <a className="btn primary wide" href={req.link} target="_blank" rel="noreferrer">
                Открыть Telegram
              </a>
            ) : (
              <p className="warn">Бот ещё не настроен на сервере (TELEGRAM_BOT_TOKEN).</p>
            )}
            <p className="muted small">
              Или отправьте боту: <code>/login {req.code}</code>
            </p>
            <p className="muted small pulse">Ждём подтверждения…</p>
          </>
        )}
        {(state === 'denied' || state === 'expired') && (
          <>
            <p className={state === 'denied' ? 'err' : 'muted'}>{state === 'denied' ? 'Вход отклонён в Telegram.' : 'Код устарел.'}</p>
            <button className="btn primary" onClick={start}>
              Получить новый код
            </button>
          </>
        )}
      </div>
    </div>
  );
}

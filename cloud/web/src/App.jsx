import React, { useCallback, useEffect, useState } from 'react';
import { api, getToken, setToken } from './api.js';
import Landing from './Landing.jsx';
import LoginModal from './LoginModal.jsx';
import Cabinet from './Cabinet.jsx';
import Admin from './Admin.jsx';

function useHash() {
  const [hash, setHash] = useState(() => window.location.hash.replace(/^#\/?/, ''));
  useEffect(() => {
    const on = () => setHash(window.location.hash.replace(/^#\/?/, ''));
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  return hash;
}
export const go = (p) => {
  window.location.hash = p ? `#/${p}` : '';
};

export default function App() {
  const route = useHash();
  const [config, setConfig] = useState(null);
  const [me, setMe] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loginOpen, setLoginOpen] = useState(false);

  const refreshMe = useCallback(async () => {
    if (!getToken()) {
      setMe(null);
      return null;
    }
    try {
      const r = await api('/api/me');
      setMe(r.user);
      return r.user;
    } catch (e) {
      if (e.status === 401 || e.status === 403) setToken('');
      setMe(null);
      return null;
    }
  }, []);

  useEffect(() => {
    Promise.all([api('/api/config', { token: '' }).then(setConfig).catch(() => setConfig({})), refreshMe()]).finally(() => setLoading(false));
  }, [refreshMe]);

  const logout = async () => {
    await api('/api/auth/logout', { method: 'POST' }).catch(() => undefined);
    setToken('');
    setMe(null);
    go('');
  };
  const onLoggedIn = async (token) => {
    setToken(token);
    setLoginOpen(false);
    await refreshMe();
    go('cabinet');
  };

  const needsAuth = route === 'cabinet' || route === 'admin';
  let page;
  if (loading) page = <div className="center muted">Загрузка…</div>;
  else if (needsAuth && !me)
    page = (
      <div className="center">
        <div className="card narrow">
          <h2>Нужен вход</h2>
          <p className="muted">Регистрация и вход — через нашего Telegram-бота. Пароль не нужен.</p>
          <button className="btn primary" onClick={() => setLoginOpen(true)}>
            Войти через Telegram
          </button>
        </div>
      </div>
    );
  else if (route === 'admin' && me.role !== 'admin') page = <div className="center muted">Раздел только для администраторов.</div>;
  else if (route === 'admin') page = <Admin me={me} config={config} />;
  else if (route === 'cabinet') page = <Cabinet me={me} config={config} onChange={refreshMe} onDeleted={logout} />;
  else page = <Landing config={config} me={me} onLogin={() => setLoginOpen(true)} />;

  return (
    <div className="app">
      <header className="topbar">
        <a className="brand" href="#/">
          <img src="/favicon.svg" alt="" width="28" height="28" />
          <span>
            Stella <b>Cloud</b>
          </span>
        </a>
        <nav>
          <a href="#/" className={!route ? 'active' : ''}>
            Главная
          </a>
          {me && (
            <a href="#/cabinet" className={route === 'cabinet' ? 'active' : ''}>
              Кабинет
            </a>
          )}
          {me?.role === 'admin' && (
            <a href="#/admin" className={route === 'admin' ? 'active' : ''}>
              Админка
            </a>
          )}
        </nav>
        <div className="spacer" />
        {me ? (
          <div className="userchip">
            <span className="avatar">{(me.name || '?').slice(0, 1).toUpperCase()}</span>
            <span className="hide-sm">{me.name}</span>
            <button className="btn ghost sm" onClick={logout}>
              Выйти
            </button>
          </div>
        ) : (
          <button className="btn primary sm" onClick={() => setLoginOpen(true)} disabled={loading}>
            Войти через Telegram
          </button>
        )}
      </header>
      <main>{page}</main>
      <footer className="footer muted">
        Stella Cloud · {config?.botUsername ? <a href={config.botLink} target="_blank" rel="noreferrer">@{config.botUsername}</a> : 'бот не настроен'} · API: <code>{config?.apiBase || '/v1'}</code>
      </footer>
      {loginOpen && <LoginModal config={config} onClose={() => setLoginOpen(false)} onDone={onLoggedIn} />}
    </div>
  );
}

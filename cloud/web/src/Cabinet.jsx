import React, { useEffect, useState } from 'react';
import { api, date, fmt } from './api.js';

export function Meter({ label, used, limit }) {
  const pct = limit === null || limit === undefined ? 0 : Math.min(100, (used / Math.max(1, limit)) * 100);
  return (
    <div className="meter">
      <div className="meter-head">
        <span>{label}</span>
        <span>
          <b>{fmt(used)}</b> / {fmt(limit)}
        </span>
      </div>
      <div className="bar">
        <div className={`fill ${pct > 90 ? 'hot' : ''}`} style={{ width: limit === null ? '100%' : `${pct}%`, opacity: limit === null ? 0.25 : 1 }} />
      </div>
    </div>
  );
}

export function UsageChart({ days }) {
  const list = [...(days || [])].reverse();
  if (!list.length) return <p className="muted">Запросов пока не было.</p>;
  const max = Math.max(1, ...list.map((d) => d.requests));
  return (
    <div className="chart" role="img" aria-label="Запросы по дням">
      {list.map((d) => (
        <div className="col" key={d.day} title={`${d.day}: ${d.requests} запросов, ${fmt(d.tokens)} токенов`}>
          <div className="colbar" style={{ height: `${(d.requests / max) * 100}%` }} />
          <span className="small muted">{d.day.slice(8)}</span>
        </div>
      ))}
    </div>
  );
}

export default function Cabinet({ me, config, onChange, onDeleted }) {
  const [keys, setKeys] = useState([]);
  const [usage, setUsage] = useState([]);
  const [newKey, setNewKey] = useState(null);
  const [name, setName] = useState('');
  const [err, setErr] = useState('');
  const [confirmDel, setConfirmDel] = useState(false);

  const load = async () => {
    try {
      const [k, u] = await Promise.all([api('/api/me/keys'), api('/api/me/usage')]);
      setKeys(k.keys);
      setUsage(u.days);
    } catch (e) {
      setErr(e.message);
    }
  };
  useEffect(() => {
    load();
  }, []);

  const create = async () => {
    setErr('');
    try {
      const r = await api('/api/me/keys', { body: { name: name.trim() || 'Ключ с сайта' } });
      setNewKey(r.key);
      setName('');
      load();
      onChange();
    } catch (e) {
      setErr(e.message);
    }
  };
  const revoke = async (id) => {
    await api(`/api/me/keys/${id}`, { method: 'DELETE' }).catch((e) => setErr(e.message));
    load();
  };
  const del = async () => {
    await api('/api/me', { method: 'DELETE' });
    onDeleted();
  };
  const p = me.planInfo;
  const apiBase = config?.apiBase || `${location.origin}/v1`;

  return (
    <div className="page">
      <h1>Личный кабинет</h1>
      {err && <p className="err">{err}</p>}
      <div className="grid2">
        <div className="card">
          <div className="row between">
            <h2>{me.name}</h2>
            <span className={`badge ${me.role === 'admin' ? 'gold' : ''}`}>{me.role === 'admin' ? 'администратор' : 'пользователь'}</span>
          </div>
          <p className="muted">
            {me.username ? `@${me.username} · ` : ''}ID {me.id} · с {date(me.createdAt)}
          </p>
          <h3>
            Тариф: <span className="grad">{p.name}</span>
          </h3>
          <Meter label="Запросы сегодня" used={me.usageToday.requests} limit={p.dailyRequests} />
          <Meter label="Токены сегодня" used={me.usageToday.tokens} limit={p.dailyTokens} />
        </div>
        <div className="card">
          <h2>Использование за 30 дней</h2>
          <UsageChart days={usage} />
        </div>
      </div>

      <div className="card">
        <h2>API-ключи</h2>
        <p className="muted small">STELLA CODER и Vibing AI Studio создают ключи сами при входе через Telegram. Здесь — ключи для других клиентов.</p>
        {newKey && (
          <div className="notice">
            <b>Новый ключ — скопируйте, он показывается один раз:</b>
            <div className="row">
              <code className="keyval">{newKey}</code>
              <button className="btn sm" onClick={() => navigator.clipboard?.writeText(newKey)}>
                Копировать
              </button>
            </div>
          </div>
        )}
        <div className="row">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Название ключа (например, Cursor)" maxLength={60} onKeyDown={(e) => e.key === 'Enter' && create()} />
          <button className="btn primary" onClick={create}>
            Создать ключ
          </button>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>Название</th>
              <th>Ключ</th>
              <th>Создан</th>
              <th>Использован</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {keys.map((k) => (
              <tr key={k.id}>
                <td>{k.name}</td>
                <td>
                  <code>{k.prefix}…</code>
                </td>
                <td>{date(k.created_at)}</td>
                <td>{date(k.last_used_at)}</td>
                <td>
                  <button className="btn ghost sm danger" onClick={() => revoke(k.id)}>
                    Отозвать
                  </button>
                </td>
              </tr>
            ))}
            {!keys.length && (
              <tr>
                <td colSpan={5} className="muted">
                  Ключей нет
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h2>Подключение</h2>
        <div className="grid2">
          <div>
            <h3>STELLA CODER</h3>
            <pre className="code-block">{`stella-coder login ${config?.publicUrl || location.origin}`}</pre>
            <h3>Vibing AI Studio</h3>
            <p className="muted">Запустите приложение и нажмите «Войти через Telegram».</p>
          </div>
          <div>
            <h3>curl</h3>
            <pre className="code-block">{`curl ${apiBase}/chat/completions \\
  -H "Authorization: Bearer sk-stella-…" \\
  -H "Content-Type: application/json" \\
  -d '{"model":"auto","messages":[{"role":"user","content":"Привет"}]}'`}</pre>
          </div>
        </div>
      </div>

      <div className="card danger-zone">
        <h2>Удаление аккаунта</h2>
        <p className="muted">Удалит аккаунт, все ключи и историю. Это необратимо. Позже можно зарегистрироваться заново через бота.</p>
        {confirmDel ? (
          <div className="row">
            <button className="btn danger" onClick={del}>
              Да, удалить навсегда
            </button>
            <button className="btn ghost" onClick={() => setConfirmDel(false)}>
              Отмена
            </button>
          </div>
        ) : (
          <button className="btn ghost danger" onClick={() => setConfirmDel(true)}>
            Удалить аккаунт
          </button>
        )}
      </div>
    </div>
  );
}

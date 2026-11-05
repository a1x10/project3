import React, { useEffect, useState } from 'react';
import { api, date, fmt } from './api.js';
import { UsageChart } from './Cabinet.jsx';

function Stats() {
  const [s, setS] = useState(null);
  const [up, setUp] = useState(null);
  useEffect(() => {
    api('/api/admin/stats').then((r) => setS(r.stats)).catch(() => undefined);
    api('/api/admin/upstream').then(setUp).catch((e) => setUp({ ok: false, error: e.message }));
  }, []);
  const tiles = s
    ? [
        ['Пользователей', s.users],
        ['Новых сегодня', s.newToday],
        ['Активных сегодня', s.activeToday],
        ['Запросов сегодня', s.requestsToday],
        ['Токенов сегодня', s.tokensToday],
        ['Заблокировано', s.banned],
      ]
    : [];
  return (
    <>
      <div className="tiles">
        {tiles.map(([k, v]) => (
          <div className="card tile" key={k}>
            <div className="muted small">{k}</div>
            <div className="big">{fmt(v)}</div>
          </div>
        ))}
      </div>
      <div className={`card upstream ${up?.ok ? 'ok' : 'bad'}`}>
        <b>Сервер моделей (FreeLLMAPI):</b>{' '}
        {!up ? 'проверяем…' : up.ok ? `работает · ${up.models} моделей · ключ: ${up.keySource}` : `недоступен — ${up.error}`}
        {up?.baseUrl && <span className="muted small"> · {up.baseUrl}</span>}
      </div>
    </>
  );
}

function UserRow({ u, plans, meId, onChanged, onOpen }) {
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const patch = async (body) => {
    setBusy(true);
    try {
      await api(`/api/admin/users/${u.id}`, { method: 'PATCH', body });
      onChanged();
    } catch (e) {
      alert(e.message);
    } finally {
      setBusy(false);
    }
  };
  const del = async () => {
    setBusy(true);
    try {
      await api(`/api/admin/users/${u.id}`, { method: 'DELETE' });
      onChanged();
    } catch (e) {
      alert(e.message);
      setBusy(false);
    }
  };
  const self = u.id === meId;
  return (
    <tr className={u.status === 'banned' ? 'banned' : ''}>
      <td>{u.id}</td>
      <td>
        <button className="link" onClick={() => onOpen(u.id)}>
          {u.name}
        </button>
        <div className="muted small">{u.username ? `@${u.username}` : `tg ${u.tgId}`}</div>
      </td>
      <td>
        <select value={u.plan} disabled={busy} onChange={(e) => patch({ plan: e.target.value })}>
          {Object.entries(plans).map(([id, p]) => (
            <option key={id} value={id}>
              {p.name}
            </option>
          ))}
          {!plans[u.plan] && <option value={u.plan}>{u.plan} (удалён)</option>}
        </select>
      </td>
      <td>
        <select value={u.role} disabled={busy || self} onChange={(e) => patch({ role: e.target.value })}>
          <option value="user">пользователь</option>
          <option value="admin">админ</option>
        </select>
      </td>
      <td>
        {u.requestsToday} / {fmt(u.tokensToday)}
      </td>
      <td>{u.keys}</td>
      <td className="small">{date(u.lastSeenAt)}</td>
      <td className="actions">
        {!self && (
          <button className="btn ghost sm" disabled={busy} onClick={() => patch({ status: u.status === 'banned' ? 'active' : 'banned' })}>
            {u.status === 'banned' ? 'Разблокировать' : 'Заблокировать'}
          </button>
        )}
        {!self &&
          (confirm ? (
            <>
              <button className="btn danger sm" disabled={busy} onClick={del}>
                Удалить?
              </button>
              <button className="btn ghost sm" onClick={() => setConfirm(false)}>
                Нет
              </button>
            </>
          ) : (
            <button className="btn ghost sm danger" onClick={() => setConfirm(true)}>
              Удалить
            </button>
          ))}
      </td>
    </tr>
  );
}

function UserDrawer({ id, onClose, onChanged }) {
  const [d, setD] = useState(null);
  const load = () => api(`/api/admin/users/${id}`).then(setD).catch((e) => setD({ error: e.message }));
  useEffect(() => {
    load();
  }, [id]);
  const revoke = async (keyId) => {
    await api(`/api/admin/keys/${keyId}`, { method: 'DELETE' });
    load();
    onChanged();
  };
  const revokeAll = async () => {
    await api(`/api/admin/users/${id}/revoke-keys`, { method: 'POST', body: {} });
    load();
    onChanged();
  };
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal wide-modal">
        <button className="close" onClick={onClose}>
          ×
        </button>
        {!d ? (
          <p className="muted">Загрузка…</p>
        ) : d.error ? (
          <p className="err">{d.error}</p>
        ) : (
          <>
            <h2>{d.user.name}</h2>
            <p className="muted">
              ID {d.user.id} · tg {d.user.tgId} {d.user.username ? `· @${d.user.username}` : ''} · {d.user.planInfo.name} · с {date(d.user.createdAt)}
            </p>
            <h3>Использование</h3>
            <UsageChart days={d.usage} />
            <div className="row between">
              <h3>Ключи ({d.keys.length})</h3>
              {!!d.keys.length && (
                <button className="btn ghost sm danger" onClick={revokeAll}>
                  Отозвать все
                </button>
              )}
            </div>
            <table className="table">
              <tbody>
                {d.keys.map((k) => (
                  <tr key={k.id}>
                    <td>{k.name}</td>
                    <td>
                      <code>{k.prefix}…</code>
                    </td>
                    <td className="small">{date(k.last_used_at)}</td>
                    <td>
                      <button className="btn ghost sm danger" onClick={() => revoke(k.id)}>
                        Отозвать
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>
    </div>
  );
}

function Users({ me, plans }) {
  const [q, setQ] = useState('');
  const [data, setData] = useState({ users: [], total: 0 });
  const [page, setPage] = useState(0);
  const [open, setOpen] = useState(null);
  const limit = 50;
  const load = () =>
    api(`/api/admin/users?q=${encodeURIComponent(q)}&limit=${limit}&offset=${page * limit}`)
      .then(setData)
      .catch(() => undefined);
  useEffect(() => {
    const t = setTimeout(load, 250);
    return () => clearTimeout(t);
  }, [q, page]);
  return (
    <div className="card">
      <div className="row between">
        <h2>Пользователи ({data.total})</h2>
        <input className="search" placeholder="Поиск: имя, @ник, ID" value={q} onChange={(e) => (setPage(0), setQ(e.target.value))} />
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Пользователь</th>
              <th>Тариф</th>
              <th>Роль</th>
              <th>Сегодня (запр./ток.)</th>
              <th>Ключи</th>
              <th>Был</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.users.map((u) => (
              <UserRow key={u.id} u={u} plans={plans} meId={me.id} onChanged={load} onOpen={setOpen} />
            ))}
          </tbody>
        </table>
      </div>
      {data.total > limit && (
        <div className="row">
          <button className="btn ghost sm" disabled={!page} onClick={() => setPage(page - 1)}>
            ←
          </button>
          <span className="muted small">
            {page + 1} / {Math.ceil(data.total / limit)}
          </span>
          <button className="btn ghost sm" disabled={(page + 1) * limit >= data.total} onClick={() => setPage(page + 1)}>
            →
          </button>
        </div>
      )}
      {open && <UserDrawer id={open} onClose={() => setOpen(null)} onChanged={load} />}
    </div>
  );
}

function Settings({ settings, onSaved }) {
  const [s, setS] = useState(settings);
  const [plansText, setPlansText] = useState(JSON.stringify(settings.plans, null, 2));
  const [models, setModels] = useState(settings.allowedModels.join('\n'));
  const [msg, setMsg] = useState('');
  const [upModels, setUpModels] = useState([]);
  useEffect(() => {
    api('/api/admin/upstream').then((r) => setUpModels(r.modelIds || [])).catch(() => undefined);
  }, []);
  const save = async () => {
    setMsg('');
    let plans;
    try {
      plans = JSON.parse(plansText);
    } catch {
      return setMsg('Ошибка: тарифы — неверный JSON');
    }
    try {
      const r = await api('/api/admin/settings', {
        method: 'PUT',
        body: { systemPrompt: s.systemPrompt, promptMode: s.promptMode, defaultModel: s.defaultModel, allowedModels: models.split(/\s+/).filter(Boolean), plans, defaultPlan: s.defaultPlan },
      });
      onSaved(r);
      setMsg('Сохранено ✓');
    } catch (e) {
      setMsg(`Ошибка: ${e.message}`);
    }
  };
  return (
    <div className="card">
      <h2>Настройки шлюза</h2>
      <label className="field">
        <span>Системный промпт (добавляется к каждому запросу всех пользователей)</span>
        <textarea rows={10} value={s.systemPrompt} onChange={(e) => setS({ ...s, systemPrompt: e.target.value })} placeholder="Ты — Stella, ассистент компании…" />
      </label>
      <div className="grid3">
        <label className="field">
          <span>Режим промпта</span>
          <select value={s.promptMode} onChange={(e) => setS({ ...s, promptMode: e.target.value })}>
            <option value="prepend">Добавлять перед сообщениями</option>
            <option value="off">Выключен</option>
          </select>
        </label>
        <label className="field">
          <span>Модель по умолчанию</span>
          <input list="up-models" value={s.defaultModel} onChange={(e) => setS({ ...s, defaultModel: e.target.value })} />
          <datalist id="up-models">
            {upModels.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        </label>
        <label className="field">
          <span>Тариф для новых пользователей</span>
          <select value={s.defaultPlan} onChange={(e) => setS({ ...s, defaultPlan: e.target.value })}>
            {Object.keys(settings.plans).map((id) => (
              <option key={id}>{id}</option>
            ))}
          </select>
        </label>
      </div>
      <div className="grid2">
        <label className="field">
          <span>Разрешённые модели (по одной в строке). Одна модель — все запросы принудительно идут в неё; пусто — любые модели роутера</span>
          <textarea rows={6} value={models} onChange={(e) => setModels(e.target.value)} placeholder={'auto\nauto:smart\nauto:fast'} />
        </label>
        <label className="field">
          <span>Тарифы (JSON; null — без лимита)</span>
          <textarea rows={6} className="mono" value={plansText} onChange={(e) => setPlansText(e.target.value)} />
        </label>
      </div>
      <div className="row">
        <button className="btn primary" onClick={save}>
          Сохранить
        </button>
        {msg && <span className={msg.startsWith('Ошибка') ? 'err' : 'ok-text'}>{msg}</span>}
      </div>
    </div>
  );
}

export default function Admin({ me }) {
  const [tab, setTab] = useState('users');
  const [settings, setSettings] = useState(null);
  useEffect(() => {
    api('/api/admin/settings').then(setSettings).catch(() => undefined);
  }, []);
  return (
    <div className="page">
      <h1>Администрирование</h1>
      <Stats />
      <div className="tabs">
        <button className={tab === 'users' ? 'active' : ''} onClick={() => setTab('users')}>
          Пользователи
        </button>
        <button className={tab === 'settings' ? 'active' : ''} onClick={() => setTab('settings')}>
          Промпт и тарифы
        </button>
      </div>
      {tab === 'users' && settings && <Users me={me} plans={settings.plans} />}
      {tab === 'settings' && settings && <Settings settings={settings} onSaved={setSettings} />}
    </div>
  );
}

import React, { useState } from "react";
import Icon from "./Icons.jsx";
import {
  loginUser,
  registerUser,
  PLANS,
  getActivationKeys,
  createActivationKey,
  redeemActivationKey,
} from "./authStore.js";


export function AuthModal({ isOpen, onClose, onAuthSuccess }) {
  const [isRegister, setIsRegister] = useState(false);
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      if (isRegister) {
        if (!username || !email || !password) throw new Error("Заполните все поля");
        const user = registerUser(username, email, password);
        onAuthSuccess(user);
        onClose();
      } else {
        if (!username || !password) throw new Error("Введите логин/email и пароль");
        const user = loginUser(username, password);
        onAuthSuccess(user);
        onClose();
      }
    } catch (err) {
      setError(err.message || "Ошибка авторизации");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card auth-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title">
            <span className="modal-icon-badge">
              <Icon name="logo" size={20} />
            </span>
            <h3>{isRegister ? "Регистрация в Vibing" : "Вход в аккаунт"}</h3>
          </div>
          <button className="modal-close" onClick={onClose}>
            <Icon name="close" size={14} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="modal-form">
          {error && <div className="form-alert error">{error}</div>}

          <div className="form-group">
            <label>{isRegister ? "Логин (никнейм)" : "Логин или Email"}</label>
            <input
              type="text"
              className="modal-input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder={isRegister ? "alex_vibes" : "admin или ваш email"}
              autoFocus
              required
            />
          </div>

          {isRegister && (
            <div className="form-group">
              <label>Email</label>
              <input
                type="email"
                className="modal-input"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="user@example.com"
                required
              />
            </div>
          )}

          <div className="form-group">
            <label>Пароль</label>
            <input
              type="password"
              className="modal-input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              required
            />
          </div>

          <button type="submit" className="submit-btn" disabled={loading}>
            {loading ? "Загрузка..." : isRegister ? "Создать аккаунт" : "Войти"}
          </button>

          <div className="auth-switch">
            {isRegister ? (
              <span>
                Уже есть аккаунт?{" "}
                <button type="button" onClick={() => { setIsRegister(false); setError(""); }}>
                  Войти
                </button>
              </span>
            ) : (
              <span>
                Нет аккаунта?{" "}
                <button type="button" onClick={() => { setIsRegister(true); setError(""); }}>
                  Зарегистрироваться
                </button>
              </span>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}

export function SubscriptionModal({ isOpen, onClose, currentUser, onPlanChange }) {
  if (!isOpen) return null;

  const currentPlan = currentUser?.plan || "free";

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card plan-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title">
            <span className="modal-icon-badge">
              <Icon name="sparkles" size={20} />
            </span>
            <h3>Тарифы и Лимиты генерации</h3>
          </div>
          <button className="modal-close" onClick={onClose}>
            <Icon name="close" size={14} />
          </button>
        </div>

        <div className="plans-grid">
          {Object.values(PLANS).map((p) => {
            const isCurrent = currentPlan === p.id;
            return (
              <div key={p.id} className={`plan-card ${isCurrent ? "current" : ""} ${p.id === "unlimited" ? "vip" : ""}`}>
                {isCurrent && <span className="current-badge">Ваш тариф</span>}
                <h4>{p.name}</h4>
                <div className="plan-price">{p.price}</div>
                <ul className="plan-perks">
                  <li>
                    <b>{p.dailyRequests === Infinity ? "∞" : p.dailyRequests}</b> запросов в сутки
                  </li>
                  <li>
                    <b>{p.tokenLimit === Infinity ? "∞" : p.tokenLimit.toLocaleString()}</b> токенов
                  </li>
                  <li>{p.id === "free" ? "Базовая скорость" : "Приоритетная очередь"}</li>
                  <li>Поддержка всех моделей</li>
                </ul>
                <button
                  className={`plan-select-btn ${isCurrent ? "active" : ""}`}
                  disabled={isCurrent}
                  onClick={() => {
                    onPlanChange(p.id);
                    onClose();
                  }}
                >
                  {isCurrent ? "Активен" : "Выбрать план"}
                </button>
              </div>
            );
          })}
        </div>

        {/* Promo / Activation Key Section */}
        <div className="redeem-key-box">
          <div className="redeem-key-title">
            <Icon name="crown" size={16} />
            <span>Есть ключ активации тарифа?</span>
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const input = e.target.elements.promoKey;
              const val = input.value.trim();
              if (!val) return;
              try {
                const res = redeemActivationKey(currentUser.id, val);
                onPlanChange(res.plan);
                alert(`Успешно! Активирован тариф: ${PLANS[res.plan]?.name || res.plan}`);
                onClose();
              } catch (err) {
                alert(err.message);
              }
            }}
            className="redeem-form"
          >
            <input
              name="promoKey"
              type="text"
              className="modal-input"
              placeholder="Введите ключ, например: VIBE-PRO-2026"
            />
            <button type="submit" className="redeem-btn">
              Активировать
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

export function AdminModal({ isOpen, onClose, users, onUpdateUsers }) {
  const [keys, setKeys] = useState(() => getActivationKeys());
  const [newKeyCode, setNewKeyCode] = useState("");
  const [newKeyPlan, setNewKeyPlan] = useState("pro");
  const [newKeyMaxUses, setNewKeyMaxUses] = useState(10);
  const [newKeyExpires, setNewKeyExpires] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() + 30);
    return d.toISOString().slice(0, 10);
  });
  const [adminTab, setAdminTab] = useState("users"); // 'users' | 'keys'

  if (!isOpen) return null;

  const handleCreateKey = (e) => {
    e.preventDefault();
    try {
      createActivationKey({
        code: newKeyCode,
        plan: newKeyPlan,
        maxUses: newKeyMaxUses,
        expiresAt: newKeyExpires,
      });
      setKeys(getActivationKeys());
      setNewKeyCode("");
      alert("Ключ успешно создан!");
    } catch (err) {
      alert(err.message);
    }
  };

  const handleSetPlan = (userId, newPlan) => {
    const updated = users.map((u) => (u.id === userId ? { ...u, plan: newPlan } : u));
    onUpdateUsers(updated);
  };

  const handleResetLimits = (userId) => {
    const updated = users.map((u) =>
      u.id === userId ? { ...u, requestsToday: 0, tokensUsed: 0 } : u
    );
    onUpdateUsers(updated);
  };

  const handleDeleteUser = (userId) => {
    if (confirm("Точно удалить пользователя?")) {
      const updated = users.filter((u) => u.id !== userId);
      onUpdateUsers(updated);
    }
  };


  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card admin-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title">
            <span className="modal-icon-badge">
              <Icon name="shield" size={20} />
            </span>
            <h3>Панель администратора</h3>
          </div>
          <button className="modal-close" onClick={onClose}>
            <Icon name="close" size={14} />
          </button>
        </div>

        <div className="admin-stats-bar">
          <div className="stat-box">
            <span className="stat-num">{users.length}</span>
            <span className="stat-desc">Пользователей</span>
          </div>
          <div className="stat-box">
            <span className="stat-num">
              {users.filter((u) => u.plan === "unlimited" || u.role === "admin").length}
            </span>
            <span className="stat-desc">Безлимитных</span>
          </div>
          <div className="stat-box">
            <span className="stat-num">
              {users.reduce((acc, u) => acc + (u.requestsToday || 0), 0)}
            </span>
            <span className="stat-desc">Запросов за день</span>
          </div>
        </div>

        <div className="admin-tabs">
          <button
            className={`admin-tab-btn ${adminTab === "users" ? "active" : ""}`}
            onClick={() => setAdminTab("users")}
          >
            Пользователи ({users.length})
          </button>
          <button
            className={`admin-tab-btn ${adminTab === "keys" ? "active" : ""}`}
            onClick={() => setAdminTab("keys")}
          >
            Ключи активации ({keys.length})
          </button>
        </div>

        {adminTab === "users" ? (
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Логин / Email</th>
                  <th>Роль</th>
                  <th>Тариф</th>
                  <th>Запросов сегодня</th>
                  <th>Токенов</th>
                  <th>Действия</th>
                </tr>
              </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td>
                    <b>{u.username}</b>
                    <br />
                    <small>{u.email}</small>
                  </td>
                  <td>
                    <span className={`role-pill ${u.role}`}>{u.role}</span>
                  </td>
                  <td>
                    <select
                      className="admin-select"
                      value={u.plan}
                      onChange={(e) => handleSetPlan(u.id, e.target.value)}
                    >
                      <option value="free">Free</option>
                      <option value="pro">Pro</option>
                      <option value="unlimited">Unlimited (∞)</option>
                    </select>
                  </td>
                  <td>{u.requestsToday || 0}</td>
                  <td>{u.tokensUsed || 0}</td>
                  <td>
                    <div className="admin-actions-cell">
                      <button
                        className="admin-mini-btn"
                        onClick={() => handleResetLimits(u.id)}
                        title="Сбросить счетчик лимитов"
                      >
                        Сбросить
                      </button>
                      {u.role !== "admin" && u.username !== "taranka" && (
                        <button
                          className="admin-mini-btn danger"
                          onClick={() => handleDeleteUser(u.id)}
                          title="Удалить аккаунт"
                        >
                          ✕
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        ) : (
          <div className="admin-keys-section">
            <form onSubmit={handleCreateKey} className="create-key-form">
              <h4>Создать новый ключ активации</h4>
              <div className="create-key-grid">
                <div>
                  <label>Код ключа (или оставьте пустым для генерации)</label>
                  <input
                    type="text"
                    className="modal-input"
                    placeholder="Например: VIBE-VIP-2026"
                    value={newKeyCode}
                    onChange={(e) => setNewKeyCode(e.target.value)}
                  />
                </div>
                <div>
                  <label>Тариф</label>
                  <select
                    className="modal-input"
                    value={newKeyPlan}
                    onChange={(e) => setNewKeyPlan(e.target.value)}
                  >
                    <option value="pro">Pro Разработчик</option>
                    <option value="unlimited">VIP Безлимит (∞)</option>
                  </select>
                </div>
                <div>
                  <label>Кол-во активаций</label>
                  <input
                    type="number"
                    min="1"
                    max="1000"
                    className="modal-input"
                    value={newKeyMaxUses}
                    onChange={(e) => setNewKeyMaxUses(e.target.value)}
                  />
                </div>
                <div>
                  <label>Действует до</label>
                  <input
                    type="date"
                    className="modal-input"
                    value={newKeyExpires}
                    onChange={(e) => setNewKeyExpires(e.target.value)}
                  />
                </div>
              </div>
              <button type="submit" className="submit-btn create-key-submit">
                + Создать ключ
              </button>
            </form>

            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Код ключа</th>
                    <th>Тариф</th>
                    <th>Использовано</th>
                    <th>Действует до</th>
                    <th>Дата создания</th>
                  </tr>
                </thead>
                <tbody>
                  {keys.length === 0 ? (
                    <tr>
                      <td colSpan="5" style={{ textAlign: "center", opacity: 0.6 }}>
                        Нет созданных ключей. Создайте первый выше!
                      </td>
                    </tr>
                  ) : (
                    keys.map((k) => (
                      <tr key={k.id}>
                        <td>
                          <code className="key-code-badge">{k.code}</code>
                        </td>
                        <td>
                          <span className={`role-pill ${k.plan === "unlimited" ? "admin" : "user"}`}>
                            {PLANS[k.plan]?.name || k.plan}
                          </span>
                        </td>
                        <td>
                          <b>{k.usedCount || 0}</b> из {k.maxUses}
                        </td>
                        <td>{k.expiresAt || "Бессрочно"}</td>
                        <td>{new Date(k.createdAt).toLocaleDateString()}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

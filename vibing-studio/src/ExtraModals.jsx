import React, { useState } from "react";
import Icon from "./Icons.jsx";
import { TEMPLATES } from "./templates.js";

export function TemplatesModal({ isOpen, onClose, onSelectTemplate }) {
  const [activeCategory, setActiveCategory] = useState("Все");
  const [search, setSearch] = useState("");

  if (!isOpen) return null;

  const categories = ["Все", ...new Set(TEMPLATES.map((t) => t.category))];

  const filtered = TEMPLATES.filter((t) => {
    const matchesCat = activeCategory === "Все" || t.category === activeCategory;
    const matchesSearch =
      !search ||
      t.name.toLowerCase().includes(search.toLowerCase()) ||
      t.desc.toLowerCase().includes(search.toLowerCase()) ||
      t.tags.some((tag) => tag.toLowerCase().includes(search.toLowerCase()));
    return matchesCat && matchesSearch;
  });

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card templates-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title">
            <span className="modal-icon-badge">
              <Icon name="layout" size={20} />
            </span>
            <div>
              <h3>Галерея шаблонов (40+ готовых сайтов)</h3>
              <p className="modal-subtitle">Выберите готовую основу для мгновенного старта или кастомизации</p>
            </div>
          </div>
          <button className="modal-close" onClick={onClose}>
            <Icon name="close" size={14} />
          </button>
        </div>

        <div className="templates-toolbar">
          <div className="templates-search">
            <Icon name="layout" size={15} />
            <input
              type="text"
              placeholder="Поиск по названию или теме (SaaS, крипта, кафе, магазин)..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              autoFocus
            />
          </div>

          <div className="templates-categories">
            {categories.slice(0, 8).map((cat) => (
              <button
                key={cat}
                className={`template-cat-chip ${activeCategory === cat ? "active" : ""}`}
                onClick={() => setActiveCategory(cat)}
              >
                {cat}
              </button>
            ))}
          </div>
        </div>

        <div className="templates-grid">
          {filtered.map((t) => (
            <div key={t.id} className="template-card">
              <div className="template-mini-frame-wrap">
                <iframe
                  title={t.name}
                  srcDoc={t.html}
                  className="template-mini-frame"
                  sandbox="allow-scripts"
                  tabIndex="-1"
                />
                <div className="template-mini-overlay">
                  <span className="template-badge-pill">{t.category}</span>
                </div>
              </div>
              <div className="template-content">
                <div className="template-tags">
                  {t.tags.map((tag) => (
                    <span key={tag} className="template-tag">
                      #{tag}
                    </span>
                  ))}
                </div>
                <h4>{t.name}</h4>
                <p>{t.desc}</p>
                <button
                  className="template-apply-btn"
                  onClick={() => {
                    onSelectTemplate(t);
                    onClose();
                  }}
                >
                  <Icon name="plus" size={13} />
                  <span>Использовать шаблон</span>
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function HistoryModal({ isOpen, onClose, historyStack, activeIdx, onSelectHistory }) {
  if (!isOpen) return null;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card history-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title">
            <span className="modal-icon-badge">
              <Icon name="undo" size={20} />
            </span>
            <div>
              <h3>История версий сайта (Visual Time Machine)</h3>
              <p className="modal-subtitle">Мгновенный откат к любому состоянию текущей сессии</p>
            </div>
          </div>
          <button className="modal-close" onClick={onClose}>
            <Icon name="close" size={14} />
          </button>
        </div>

        <div className="history-timeline-wrap">
          {historyStack.length === 0 ? (
            <div className="history-empty">История версий пока пуста. Сделайте первую генерацию!</div>
          ) : (
            <div className="history-timeline">
              {historyStack.map((rawDoc, idx) => {
                const doc = typeof rawDoc === "string" ? rawDoc : "";
                const isCurrent = idx === activeIdx;
                const lines = doc ? doc.split("\n").length : 0;
                const chars = doc ? doc.length : 0;
                return (
                  <div key={idx} className={`history-step-card ${isCurrent ? "current" : ""}`}>
                    <div className="history-step-badge">
                      <span>Версия #{idx + 1}</span>
                      {isCurrent && <span className="history-live-tag">Текущая</span>}
                    </div>
                    <div className="history-step-meta">
                      <span>Размер: {chars.toLocaleString()} симв.</span>
                      <span>Строк: {lines}</span>
                    </div>
                    <button
                      className="history-revert-btn"
                      disabled={isCurrent}
                      onClick={() => {
                        onSelectHistory(idx);
                        onClose();
                      }}
                    >
                      {isCurrent ? "Активно" : "Откатиться к этой версии"}
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

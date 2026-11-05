import React, { useState } from "react";
import Icon from "./Icons.jsx";
import { TEMPLATES } from "./templates.js";
import { TEMPLATES_3D } from "./pro3d/templates3d.js";
import { renderSite } from "./pro3d/render.js";

/** Live preview of one 3D Pro template (only one WebGL scene at a time). */
function ProPreview({ tpl, onClose, onUse }) {
  const html = React.useMemo(() => renderSite({ template: tpl.id }), [tpl.id]);
  return (
    <div className="modal-backdrop" onClick={onClose} style={{ zIndex: 1100 }}>
      <div className="modal-card pro-preview-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title">
            <span className="probar-badge">3D Pro</span>
            <div>
              <h3>{tpl.name}</h3>
              <p className="modal-subtitle">{tpl.desc}</p>
            </div>
          </div>
          <div className="pro-preview-actions">
            <button className="template-apply-btn" onClick={onUse}>
              <Icon name="plus" size={13} />
              <span>Использовать</span>
            </button>
            <button className="modal-close" onClick={onClose}>
              <Icon name="close" size={14} />
            </button>
          </div>
        </div>
        <iframe title={tpl.name} srcDoc={html} className="pro-preview-frame" sandbox="allow-scripts" />
      </div>
    </div>
  );
}

export function TemplatesModal({ isOpen, onClose, onSelectTemplate, onSelectPro }) {
  const [activeCategory, setActiveCategory] = useState("Все");
  const [search, setSearch] = useState("");
  const [previewPro, setPreviewPro] = useState(null);

  if (!isOpen) return null;
  const q = search.toLowerCase();
  const pro = TEMPLATES_3D.filter((t) => !q || `${t.name} ${t.desc} ${t.bestFor} ${t.category}`.toLowerCase().includes(q));

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

        <div className="templates-scroll">
        {onSelectPro && activeCategory === "Все" && pro.length > 0 && (
          <>
            <div className="templates-section-title">
              <span className="probar-badge">3D Pro</span> Профессиональные шаблоны с 3D-анимацией — ИИ подставит ваши тексты и цвета
            </div>
            <div className="templates-grid pro-grid">
              {pro.map((t) => (
                <div key={t.id} className="template-card">
                  <div className="template-mini-frame-wrap" style={{ background: t.palette.bg }} onClick={() => setPreviewPro(t)} role="button" tabIndex={0}>
                    <div className="pro-card-art" style={{ background: `radial-gradient(60% 70% at 70% 40%, ${t.palette.accent}55, transparent 70%), radial-gradient(50% 60% at 20% 90%, ${t.palette.accent2}40, transparent 70%), ${t.palette.bg}` }}>
                      <div className="pro-card-orb" style={{ background: `linear-gradient(135deg, ${t.palette.accent}, ${t.palette.accent2})`, boxShadow: `0 0 60px ${t.palette.accent}` }} />
                      <span className="pro-card-name" style={{ color: t.palette.text }}>{t.name}</span>
                    </div>
                    <div className="template-mini-overlay">
                      <span className="template-badge-pill">{t.category}</span>
                    </div>
                  </div>
                  <div className="template-content">
                    <h4>{t.name}</h4>
                    <p>{t.desc}</p>
                    <div className="pro-card-actions">
                      <button className="template-apply-btn secondary" onClick={() => setPreviewPro(t)}>
                        <span>Предпросмотр 3D</span>
                      </button>
                      <button
                        className="template-apply-btn"
                        onClick={() => {
                          onSelectPro(t.id);
                          onClose();
                        }}
                      >
                        <Icon name="plus" size={13} />
                        <span>Использовать</span>
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
            <div className="templates-section-title">Классические шаблоны</div>
          </>
        )}

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
      {previewPro && (
        <ProPreview
          tpl={previewPro}
          onClose={() => setPreviewPro(null)}
          onUse={() => {
            onSelectPro(previewPro.id);
            setPreviewPro(null);
            onClose();
          }}
        />
      )}
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

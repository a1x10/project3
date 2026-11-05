import React from "react";
import Icon from "./Icons.jsx";

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

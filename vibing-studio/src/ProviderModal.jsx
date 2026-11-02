import React, { useState } from "react";
import Icon from "./Icons.jsx";
import { PRESET_PROVIDERS, getProviderConfig, saveProviderConfig } from "./providerStore.js";
import { listModels, resolveTarget, testConnection } from "./llmClient.js";

export function ProviderSettingsModal({ isOpen, onClose, onConfigChange }) {
  const [config, setConfig] = useState(() => getProviderConfig());
  const [selectedProviderId, setSelectedProviderId] = useState(() => config.activeProviderId || "freellmapi");
  const [remoteModels, setRemoteModels] = useState({});
  const [status, setStatus] = useState({ kind: "", text: "" });
  const [working, setWorking] = useState("");

  if (!isOpen) return null;

  const currentPreset = PRESET_PROVIDERS.find((p) => p.id === selectedProviderId) || PRESET_PROVIDERS[0];
  const providerData = config.providers?.[selectedProviderId] || { apiKey: "", model: currentPreset.defaultModel, customUrl: "" };

  const handleUpdateCurrent = (field, val) => {
    const updated = {
      ...config,
      providers: {
        ...config.providers,
        [selectedProviderId]: {
          ...providerData,
          [field]: val,
        },
      },
    };
    setConfig(updated);
    saveProviderConfig(updated);
    if (onConfigChange) onConfigChange(updated);
  };

  const target = resolveTarget(currentPreset, providerData);
  const modelOptions = [...new Set([...(currentPreset.models || []), ...(remoteModels[selectedProviderId] || [])])];

  const handleLoadModels = async () => {
    setWorking("models");
    setStatus({ kind: "", text: "" });
    try {
      const ids = await listModels(currentPreset, target);
      setRemoteModels((m) => ({ ...m, [selectedProviderId]: ids }));
      setStatus({ kind: "ok", text: `Загружено моделей: ${ids.length}. Выберите в списке или впишите id.` });
    } catch (e) {
      setStatus({ kind: "err", text: `Не удалось получить список моделей: ${e.message}` });
    } finally {
      setWorking("");
    }
  };

  const handleTest = async () => {
    setWorking("test");
    setStatus({ kind: "", text: "" });
    try {
      const r = await testConnection(currentPreset, target);
      setStatus({ kind: r.ok ? "ok" : "err", text: r.ok ? `Работает: ответ «${r.text.slice(0, 40)}» за ${r.ms} мс${r.routedVia ? ` · модель ${r.routedVia}` : ""}` : "Сервер ответил пустым сообщением" });
    } catch (e) {
      setStatus({ kind: "err", text: `Ошибка: ${e.message}` });
    } finally {
      setWorking("");
    }
  };

  const handleActivateProvider = (pId) => {
    const updated = {
      ...config,
      activeProviderId: pId,
    };
    setConfig(updated);
    saveProviderConfig(updated);
    if (onConfigChange) onConfigChange(updated);
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card provider-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title">
            <span className="modal-icon-badge">
              <Icon name="sparkles" size={20} />
            </span>
            <div>
              <h3>Провайдеры нейросетей &amp; API</h3>
              <p className="modal-subtitle">FreeLLMAPI (бесплатно), ChatGPT, Claude, Gemini, Qwen, Kimi или локальная модель</p>
            </div>
          </div>
          <button className="modal-close" onClick={onClose}>
            <Icon name="close" size={14} />
          </button>
        </div>

        <div className="provider-layout">
          {/* Sidebar with Providers */}
          <div className="provider-sidebar-list">
            {PRESET_PROVIDERS.map((p) => {
              const isActive = config.activeProviderId === p.id;
              const isSelected = selectedProviderId === p.id;
              const hasKey = config.providers?.[p.id]?.apiKey || !p.requiresKey;
              return (
                <div
                  key={p.id}
                  className={`provider-tab-item ${isSelected ? "selected" : ""} ${isActive ? "active" : ""}`}
                  onClick={() => {
                    setSelectedProviderId(p.id);
                    setStatus({ kind: "", text: "" });
                  }}
                >
                  <div className="provider-tab-info">
                    <span className="provider-tab-name">{p.name}</span>
                    <span className="provider-tab-status">
                      {isActive ? "● Используется сейчас" : hasKey ? "Настроен" : "Не подключен"}
                    </span>
                  </div>
                  {isActive && <span className="provider-active-badge">Активен</span>}
                </div>
              );
            })}
          </div>

          {/* Configuration Form */}
          <div className="provider-config-panel">
            <div className="provider-header-row">
              <div>
                <h4>{currentPreset.name}</h4>
                <p className="provider-desc-text">
                  {currentPreset.requiresKey ? "Требуется API-ключ провайдера" : "Локальный запуск без ключа"}
                </p>
              </div>
              <button
                className={`provider-switch-btn ${config.activeProviderId === currentPreset.id ? "current" : ""}`}
                onClick={() => handleActivateProvider(currentPreset.id)}
              >
                {config.activeProviderId === currentPreset.id ? "✓ Выбран как основной" : "Сделать активным"}
              </button>
            </div>

            <div className="provider-form-fields">
              {currentPreset.requiresKey && (
                <div className="form-group">
                  <label>API-ключ</label>
                  <input
                    type="password"
                    className="modal-input"
                    placeholder={currentPreset.placeholder}
                    value={providerData.apiKey || ""}
                    onChange={(e) => handleUpdateCurrent("apiKey", e.target.value)}
                  />
                </div>
              )}

              <div className="form-group">
                <label>Эндпоинт API (URL обращения)</label>
                <input
                  type="text"
                  className="modal-input"
                  placeholder={currentPreset.url}
                  value={providerData.customUrl || currentPreset.url}
                  onChange={(e) => handleUpdateCurrent("customUrl", e.target.value)}
                />
              </div>

              <div className="form-group">
                <label>Модель</label>
                <div className="provider-model-selector" style={{ display: "flex", gap: "8px" }}>
                  <select
                    className="modal-input"
                    value={modelOptions.includes(providerData.model) ? providerData.model : "custom"}
                    onChange={(e) => {
                      if (e.target.value !== "custom") {
                        handleUpdateCurrent("model", e.target.value);
                      }
                    }}
                    style={{ flex: 1 }}
                  >
                    {modelOptions.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                    <option value="custom">Другая модель (ввести вручную)...</option>
                  </select>
                  <input
                    type="text"
                    className="modal-input"
                    placeholder="Название модели..."
                    value={providerData.model || currentPreset.defaultModel}
                    onChange={(e) => handleUpdateCurrent("model", e.target.value)}
                    style={{ flex: 1 }}
                  />
                </div>
                <span style={{ fontSize: "11px", color: "var(--text-muted, #94a3b8)", marginTop: "4px", display: "block" }}>
                  Выберите из списка или введите точный идентификатор модели (например: {currentPreset.models.slice(0, 3).join(", ")})
                </span>
              </div>

              <div className="provider-test-row">
                {currentPreset.canListModels && (
                  <button type="button" className="provider-switch-btn" onClick={handleLoadModels} disabled={!!working}>
                    {working === "models" ? "Загружаю…" : "Загрузить модели"}
                  </button>
                )}
                <button type="button" className="provider-switch-btn" onClick={handleTest} disabled={!!working}>
                  {working === "test" ? "Проверяю…" : "Проверить подключение"}
                </button>
              </div>
              {status.text && <div className={`form-alert ${status.kind === "ok" ? "success" : "error"}`}>{status.text}</div>}

              <div className="provider-instructions-box">
                <div className="provider-instructions-title">
                  <Icon name="think" size={15} />
                  <span>Инструкция по получению ключа:</span>
                </div>
                <pre className="instructions-pre">{currentPreset.instructions}</pre>
                {currentPreset.docUrl && (
                  <a
                    href={currentPreset.docUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="provider-doc-link"
                  >
                    Перейти в личный кабинет {currentPreset.name} ↗
                  </a>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

import React, { useCallback, useEffect, useRef, useState } from "react";
import Chat from "./Chat.jsx";
import Preview from "./Preview.jsx";
import Icon from "./Icons.jsx";
import { ProjectSidebar } from "./ProjectSidebar.jsx";
import { AuthModal, SubscriptionModal, AdminModal } from "./Modals.jsx";
import { TemplatesModal, HistoryModal } from "./ExtraModals.jsx";
import { ProviderSettingsModal } from "./ProviderModal.jsx";
import { getProviderConfig, PRESET_PROVIDERS } from "./providerStore.js";
import {
  getCurrentUser,
  getUsers,
  saveUsers,
  logoutUser,
  changePassword,
  checkUserLimit,
  recordUsage,
  getProjects,
  saveProjects,
  PLANS,
} from "./authStore.js";

const THEME_KEY = "vc-theme";
const THEME_COLOR = { dark: "#13121a", light: "#f7f6fc" };

function initialTheme() {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    /* storage unavailable */
  }
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

const HISTORY_MAX = 50;

export default function App() {
  const [siteMode, setSiteMode] = useState(true);
  const [preview, setPreview] = useState({ html: "", streaming: false, genId: 0, kind: "new" });
  const [selectedHtml, setSelectedHtml] = useState("");
  const [, setTick] = useState(0);

  // User and Auth State
  const [currentUser, setCurrentUser] = useState(() => getCurrentUser());
  const [allUsers, setAllUsers] = useState(() => getUsers());
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [plansModalOpen, setPlansModalOpen] = useState(false);
  const [adminModalOpen, setAdminModalOpen] = useState(false);
  const [templatesModalOpen, setTemplatesModalOpen] = useState(false);
  const [historyModalOpen, setHistoryModalOpen] = useState(false);
  const [providerModalOpen, setProviderModalOpen] = useState(false);
  const [providerConfig, setProviderConfig] = useState(() => getProviderConfig());



  // Projects and Chats State
  const [projects, setProjects] = useState(() => {
    const list = getProjects(currentUser?.id || "guest");
    return list && list.length ? list : [];
  });
  const [activeProjectId, setActiveProjectId] = useState(() => {
    const list = getProjects(currentUser?.id || "guest");
    return list && list.length ? list[0].id : "";
  });
  const [activeChatId, setActiveChatId] = useState(() => {
    const list = getProjects(currentUser?.id || "guest");
    return list && list.length && list[0].chats && list[0].chats.length ? list[0].chats[0].id : "";
  });
  const [sidebarOpen, setSidebarOpen] = useState(true);

  // The site the AI can edit
  const siteRef = useRef({ html: "", edited: null });
  const histRef = useRef({ stack: [], idx: -1, lastManualAt: 0 });

  // Sync projects with storage
  useEffect(() => {
    saveProjects(currentUser?.id || "guest", projects);
  }, [projects, currentUser?.id]);

  // When user changes, reload their projects
  useEffect(() => {
    const userProjs = getProjects(currentUser?.id || "guest");
    setProjects(userProjs);
    if (userProjs.length > 0) {
      setActiveProjectId(userProjs[0].id);
      setActiveChatId(userProjs[0].chats[0]?.id || "");
      const initialHtml = userProjs[0].chats[0]?.siteHtml || "";
      siteRef.current = { html: initialHtml, edited: null };
      setPreview({ html: initialHtml, streaming: false, genId: Date.now(), kind: "new" });
    }
  }, [currentUser?.id]);

  const commit = useCallback((doc, manual = false) => {
    const h = histRef.current;
    if (!doc || h.stack[h.idx] === doc) return;
    const now = Date.now();
    const coalesce = manual && h.idx === h.stack.length - 1 && h.idx > 0 && now - h.lastManualAt < 700;
    h.lastManualAt = manual ? now : 0;
    h.stack = h.stack.slice(0, h.idx + 1);
    if (coalesce) h.stack[h.idx] = doc;
    else {
      h.stack.push(doc);
      if (h.stack.length > HISTORY_MAX) h.stack.shift();
      h.idx = h.stack.length - 1;
    }
    setTick((t) => t + 1);
  }, []);

  const jump = useCallback((to) => {
    const h = histRef.current;
    if (to < 0 || to >= h.stack.length) return;
    h.idx = to;
    h.lastManualAt = 0;
    const doc = h.stack[to];
    siteRef.current = { html: doc, edited: null };
    setPreview({ html: doc, streaming: false, genId: -Date.now(), kind: "edit" });
    setTick((t) => t + 1);
  }, []);

  const undo = useCallback(() => jump(histRef.current.idx - 1), [jump]);
  const redo = useCallback(() => jump(histRef.current.idx + 1), [jump]);

  const onPreview = useCallback(
    (html, streaming, genId, kind = "new") => {
      siteRef.current = { html, edited: null };
      setPreview({ html, streaming, genId, kind });
      if (!streaming && html) {
        commit(html);
        // Save current siteHtml into active chat
        setProjects((prev) =>
          prev.map((p) =>
            p.id === activeProjectId
              ? {
                  ...p,
                  chats: (p.chats || []).map((c) =>
                    c.id === activeChatId ? { ...c, siteHtml: html } : c
                  ),
                }
              : p
          )
        );
      }
    },
    [commit, activeProjectId, activeChatId]
  );

  const getSite = useCallback(() => siteRef.current.edited ?? siteRef.current.html, []);

  const onEdited = useCallback(
    (doc) => {
      if (doc === siteRef.current.edited) return;
      siteRef.current.edited = doc;
      if (doc) commit(doc, true);
    },
    [commit]
  );

  const onNewSite = useCallback(() => {
    siteRef.current = { html: "", edited: null };
    histRef.current = { stack: [], idx: -1, lastManualAt: 0 };
    setSelectedHtml("");
    setPreview({ html: "", streaming: false, genId: -Date.now(), kind: "new" });
  }, []);

  // Keyboard undo/redo
  useEffect(() => {
    const onKey = (e) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      const t = e.target;
      if (t && (t.tagName === "TEXTAREA" || t.tagName === "INPUT" || t.isContentEditable)) return;
      const k = e.key.toLowerCase();
      if (k === "z" && !e.shiftKey) {
        e.preventDefault();
        undo();
      } else if (k === "y" || (k === "z" && e.shiftKey)) {
        e.preventDefault();
        redo();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo, redo]);

  const hist = histRef.current;
  const canUndo = hist.idx > 0 && !preview.streaming;
  const canRedo = hist.idx < hist.stack.length - 1 && !preview.streaming;

  // Theme
  const [theme, setTheme] = useState(initialTheme);
  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", THEME_COLOR[theme]);
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* ignore */
    }
  }, [theme]);

  const toggleTheme = () => {
    const root = document.documentElement;
    root.classList.add("theming");
    setTheme((t) => (t === "dark" ? "light" : "dark"));
    setTimeout(() => root.classList.remove("theming"), 400);
  };

  const download = () => {
    const doc = getSite();
    if (!doc) return;
    const blob = new Blob([doc], { type: "text/html;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "vibecode-site.html";
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  };

  // Chat and Project Handlers
  const handleSelectChat = (projId, chatId) => {
    setActiveProjectId(projId);
    setActiveChatId(chatId);
    const proj = projects.find((p) => p.id === projId);
    const chat = proj?.chats?.find((c) => c.id === chatId);
    const doc = chat?.siteHtml || "";
    siteRef.current = { html: doc, edited: null };
    histRef.current = { stack: doc ? [doc] : [], idx: doc ? 0 : -1, lastManualAt: 0 };
    setPreview({ html: doc, streaming: false, genId: Date.now(), kind: "new" });
    setSelectedHtml("");
  };

  const handleCreateProject = (name) => {
    const newProj = {
      id: "proj-" + Date.now(),
      name,
      createdAt: new Date().toISOString(),
      chats: [
        {
          id: "chat-" + Date.now(),
          title: "Главная страница",
          createdAt: new Date().toISOString(),
          messages: [],
          siteHtml: "",
        },
      ],
    };
    setProjects((prev) => [newProj, ...prev]);
    handleSelectChat(newProj.id, newProj.chats[0].id);
  };

  const handleCreateChat = (projId, title) => {
    const newChat = {
      id: "chat-" + Date.now(),
      title,
      createdAt: new Date().toISOString(),
      messages: [],
      siteHtml: "",
    };
    setProjects((prev) =>
      prev.map((p) => (p.id === projId ? { ...p, chats: [...(p.chats || []), newChat] } : p))
    );
    handleSelectChat(projId, newChat.id);
  };

  const handleDeleteChat = (projId, chatId) => {
    setProjects((prev) =>
      prev.map((p) => {
        if (p.id !== projId) return p;
        const newChats = p.chats.filter((c) => c.id !== chatId);
        return { ...p, chats: newChats };
      })
    );
    if (activeChatId === chatId) {
      const proj = projects.find((p) => p.id === projId);
      const remaining = proj?.chats.filter((c) => c.id !== chatId);
      if (remaining && remaining.length > 0) {
        handleSelectChat(projId, remaining[0].id);
      }
    }
  };

  const handleDeleteProject = (projId) => {
    if (confirm("Удалить проект со всеми чатами?")) {
      const filtered = projects.filter((p) => p.id !== projId);
      setProjects(filtered);
      if (activeProjectId === projId && filtered.length > 0) {
        handleSelectChat(filtered[0].id, filtered[0].chats[0]?.id || "");
      }
    }
  };

  const handleSaveMessages = (msgs) => {
    setProjects((prev) =>
      prev.map((p) =>
        p.id === activeProjectId
          ? {
              ...p,
              chats: (p.chats || []).map((c) =>
                c.id === activeChatId ? { ...c, messages: msgs } : c
              ),
            }
          : p
      )
    );
  };

  const handleRecordUsage = (tokens) => {
    if (!currentUser) return { ok: false, reason: "Необходимо войти в аккаунт" };
    const check = checkUserLimit(currentUser);
    if (!check.ok) return check;
    if (tokens > 0) {
      recordUsage(currentUser.id, tokens);
      const updated = getCurrentUser();
      setCurrentUser(updated);
      setAllUsers(getUsers());
    }
    return { ok: true };
  };

  const handlePlanChange = (newPlan) => {
    if (!currentUser) return;
    const users = getUsers().map((u) => (u.id === currentUser.id ? { ...u, plan: newPlan } : u));
    saveUsers(users);
    setAllUsers(users);
    const updated = users.find((u) => u.id === currentUser.id);
    setCurrentUser(updated);
  };

  const handleUpdateUsers = (updated) => {
    saveUsers(updated);
    setAllUsers(updated);
    if (currentUser) {
      const currentFresh = updated.find((u) => u.id === currentUser.id);
      if (currentFresh) setCurrentUser(currentFresh);
      else {
        logoutUser();
        setCurrentUser(null);
      }
    }
  };

  const handleChangePassword = () => {
    if (!currentUser) return;
    const oldPass = window.prompt("Текущий пароль:");
    if (oldPass === null) return;
    const newPass = window.prompt("Новый пароль (не короче 8 символов):");
    if (newPass === null) return;
    try {
      const updated = changePassword(currentUser.id, oldPass, newPass);
      setCurrentUser(updated);
      setAllUsers(getUsers());
      alert("Пароль изменён");
    } catch (e) {
      alert(e.message);
    }
  };

  const currentProject = projects.find((p) => p.id === activeProjectId) || projects[0];
  const currentChat = currentProject?.chats?.find((c) => c.id === activeChatId) || currentProject?.chats?.[0];
  const userPlanInfo = PLANS[currentUser?.plan || "free"];

  return (
    <div className="app builder">
      <header className="topbar">
        <div className="topbar-left">
          <button
            className="topbar-sidebar-toggle"
            onClick={() => setSidebarOpen((v) => !v)}
            title="Боковая панель проектов"
          >
            <Icon name="menu" size={16} />
          </button>
          <div className="logo">
            <span className="logo-mark">
              <Icon name="logo" size={18} />
            </span>
            <span className="logo-name">Vibing AI Studio</span>
            <span className="logo-sep" />
            <span className="logo-sub">{currentProject ? `${currentProject.name} / ${currentChat?.title || "Чат"}` : "Конструктор"}</span>
          </div>
        </div>

        <div className="topbar-actions">
          <button
            className="topbtn"
            onClick={undo}
            disabled={!canUndo}
            title={`Отменить (Ctrl+Z) · шагов: ${Math.max(hist.idx, 0)}`}
          >
            <Icon name="undo" size={16} />
          </button>
          <button className="topbtn" onClick={redo} disabled={!canRedo} title="Вернуть (Ctrl+Y)">
            <Icon name="redo" size={16} />
          </button>
          <button
            className="topbtn"
            onClick={() => setHistoryModalOpen(true)}
            title="История версий сайта (Visual Time Machine)"
          >
            <Icon name="think" size={15} />
            <span>История ({hist.stack.length})</span>
          </button>
          <div className="topbar-sep" />
          <button
            className="topbtn highlight-btn"
            onClick={() => setTemplatesModalOpen(true)}
            title="Открыть галерею 40+ готовых шаблонов сайтов"
          >
            <Icon name="sparkles" size={15} />
            <span>Шаблоны (40+)</span>
          </button>
          <button
            className="topbtn"
            onClick={() => setProviderModalOpen(true)}
            title="Выбор AI-провайдера (FreeLLMAPI, ChatGPT, Claude, Gemini, Kimi, Qwen, Local)"
          >
            <Icon name="sparkles" size={15} />
            <span>AI: {(() => { const p = PRESET_PROVIDERS.find((x) => x.id === providerConfig.activeProviderId); return p ? p.shortName || p.name.split(" ")[0] : "FreeLLMAPI"; })()}</span>
          </button>
          <div className="topbar-sep" />
          <button
            className="topbtn"
            onClick={download}
            disabled={!getSite() || preview.streaming}
            title="Скачать готовый index.html"
          >
            <Icon name="download" size={16} />
            <span>Экспорт</span>
          </button>
        </div>

        <div className="topbar-right">
          <label className="modetoggle" title="Автоматическое обновление превью">
            <span>Режим сайта</span>
            <input type="checkbox" checked={siteMode} onChange={(e) => setSiteMode(e.target.checked)} />
            <span className="track">
              <span className="thumb" />
            </span>
          </label>

          {/* User Account / Auth & Plans */}
          {currentUser ? (
            <div className="user-profile-menu">
              <button className="user-plan-pill" onClick={() => setPlansModalOpen(true)} title="Нажмите для управления тарифом">
                <span className="plan-badge-icon">
                  <Icon name="crown" size={14} />
                </span>
                <span>{userPlanInfo.badge}</span>
                {currentUser.plan !== "unlimited" && currentUser.role !== "admin" && (
                  <small className="plan-limit-counter">
                    ({userPlanInfo.dailyRequests - (currentUser.requestsToday || 0)} ост.)
                  </small>
                )}
              </button>

              {currentUser.role === "admin" && (
                <button
                  className="admin-badge-btn"
                  onClick={() => setAdminModalOpen(true)}
                  title="Панель администратора"
                >
                  <Icon name="shield" size={14} />
                  <span>Админка</span>
                </button>
              )}

              <div className="user-info-card">
                <span className="user-name-label">{currentUser.username}</span>
                <button className="user-logout-btn" onClick={handleChangePassword} title="Сменить пароль">
                  Пароль
                </button>
                <button
                  className="user-logout-btn"
                  onClick={() => {
                    logoutUser();
                    setCurrentUser(null);
                  }}
                  title="Выйти из аккаунта"
                >
                  Выйти
                </button>
              </div>
            </div>
          ) : (
            <div className="auth-actions-group">
              <button className="auth-btn-login" onClick={() => setAuthModalOpen(true)}>
                Вход / Регистрация
              </button>
            </div>
          )}

          <button
            className="themebtn"
            onClick={toggleTheme}
            title={theme === "dark" ? "Светлая тема" : "Тёмная тема"}
            aria-label="Смена темы"
          >
            <Icon key={theme} name={theme === "dark" ? "sun" : "moon"} size={16} />
          </button>
        </div>
      </header>

      {currentUser?.mustChangePassword && (
        <div className="security-banner">
          Пароль этой учётной записи был опубликован в исходном коде старой версии. Смените его прямо сейчас.
          <button onClick={handleChangePassword}>Сменить пароль</button>
        </div>
      )}

      <div className="builder-main">
        <ProjectSidebar
          projects={projects}
          activeProjectId={activeProjectId}
          activeChatId={activeChatId}
          onSelectChat={handleSelectChat}
          onCreateProject={handleCreateProject}
          onCreateChat={handleCreateChat}
          onDeleteChat={handleDeleteChat}
          onDeleteProject={handleDeleteProject}
          isOpen={sidebarOpen}
          onToggleOpen={() => setSidebarOpen((v) => !v)}
        />

        <aside className="pane-chat">
          <Chat
            siteMode={siteMode}
            onPreview={onPreview}
            getSite={getSite}
            onNewSite={onNewSite}
            selectedHtml={selectedHtml}
            currentUser={currentUser}
            onRecordUsage={handleRecordUsage}
            chatData={currentChat}
            onSaveMessages={handleSaveMessages}
            onOpenAuth={() => setAuthModalOpen(true)}
            onOpenPlans={() => setPlansModalOpen(true)}
            providerConfig={providerConfig}
          />
        </aside>

        <section className="pane-preview">
          <Preview
            html={preview.html}
            streaming={preview.streaming}
            genId={preview.genId}
            kind={preview.kind}
            onEdited={onEdited}
            onSelect={setSelectedHtml}
          />
        </section>
      </div>

      {/* Modals */}
      <AuthModal
        isOpen={authModalOpen}
        onClose={() => setAuthModalOpen(false)}
        onAuthSuccess={(user) => {
          setCurrentUser(user);
          setAllUsers(getUsers());
        }}
      />

      <SubscriptionModal
        isOpen={plansModalOpen}
        onClose={() => setPlansModalOpen(false)}
        currentUser={currentUser}
        onPlanChange={handlePlanChange}
      />

      <AdminModal
        isOpen={adminModalOpen}
        onClose={() => setAdminModalOpen(false)}
        users={allUsers}
        onUpdateUsers={handleUpdateUsers}
      />

      <TemplatesModal
        isOpen={templatesModalOpen}
        onClose={() => setTemplatesModalOpen(false)}
        onSelectTemplate={(template) => {
          siteRef.current = { html: template.html, edited: null };
          commit(template.html);
          setPreview({
            html: template.html,
            streaming: false,
            genId: Date.now(),
            kind: "new",
          });
        }}
      />

      <HistoryModal
        isOpen={historyModalOpen}
        onClose={() => setHistoryModalOpen(false)}
        historyStack={hist.stack}
        activeIdx={hist.idx}
        onSelectHistory={(to) => jump(to)}
      />

      <ProviderSettingsModal
        isOpen={providerModalOpen}
        onClose={() => setProviderModalOpen(false)}
        onConfigChange={(updated) => setProviderConfig(updated)}
      />
    </div>
  );
}
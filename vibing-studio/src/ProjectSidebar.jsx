import React, { useState } from "react";
import Icon from "./Icons.jsx";

export function ProjectSidebar({
  projects,
  activeProjectId,
  activeChatId,
  onSelectChat,
  onCreateProject,
  onCreateChat,
  onDeleteChat,
  onDeleteProject,
  isOpen,
  onToggleOpen,
}) {
  const [newProjName, setNewProjName] = useState("");
  const [addingProj, setAddingProj] = useState(false);
  const [newChatName, setNewChatName] = useState("");
  const [addingChatFor, setAddingChatFor] = useState(null);

  const handleCreateProj = (e) => {
    e.preventDefault();
    if (!newProjName.trim()) return;
    onCreateProject(newProjName.trim());
    setNewProjName("");
    setAddingProj(false);
  };

  const handleCreateChat = (e, projId) => {
    e.preventDefault();
    if (!newChatName.trim()) return;
    onCreateChat(projId, newChatName.trim());
    setNewChatName("");
    setAddingChatFor(null);
  };

  return (
    <aside className={`project-sidebar ${isOpen ? "open" : "collapsed"}`}>
      <div className="sidebar-header">
        <div className="sidebar-title">
          <span className="sidebar-folder-icon">
            <Icon name="folder" size={17} />
          </span>
          <span>Проекты &amp; Чаты</span>
        </div>
        <button
          className="sidebar-collapse-btn"
          onClick={onToggleOpen}
          title={isOpen ? "Свернуть панель" : "Развернуть панель"}
        >
          <Icon name={isOpen ? "undo" : "redo"} size={13} />
        </button>
      </div>

      {isOpen && (
        <>
          <div className="sidebar-actions">
            <button
              className="sidebar-new-btn"
              onClick={() => setAddingProj(true)}
              title="Создать новый проект"
            >
              <Icon name="plus" size={14} />
              <span>Новый проект</span>
            </button>
          </div>

          {addingProj && (
            <form onSubmit={handleCreateProj} className="sidebar-input-form">
              <input
                type="text"
                className="sidebar-input"
                placeholder="Имя проекта..."
                value={newProjName}
                onChange={(e) => setNewProjName(e.target.value)}
                autoFocus
              />
              <div className="sidebar-form-btns">
                <button type="submit" className="mini-confirm">
                  <Icon name="check" size={13} />
                </button>
                <button type="button" className="mini-cancel" onClick={() => setAddingProj(false)}>
                  <Icon name="close" size={13} />
                </button>
              </div>
            </form>
          )}

          <div className="projects-list">
            {projects.map((proj) => {
              const isProjActive = proj.id === activeProjectId;
              return (
                <div key={proj.id} className={`project-group ${isProjActive ? "active" : ""}`}>
                  <div className="project-group-header">
                    <span className="project-icon">
                      <Icon name="folder" size={15} />
                    </span>
                    <span className="project-name" title={proj.name}>{proj.name}</span>
                    <div className="project-header-actions">
                      <button
                        className="project-add-chat-btn"
                        onClick={() => setAddingChatFor(proj.id)}
                        title="Добавить чат в проект"
                      >
                        <Icon name="plus" size={12} />
                      </button>
                      {projects.length > 1 && (
                        <button
                          className="project-delete-btn"
                          onClick={() => onDeleteProject(proj.id)}
                          title="Удалить проект"
                        >
                          <Icon name="trash" size={12} />
                        </button>
                      )}
                    </div>
                  </div>

                  {addingChatFor === proj.id && (
                    <form onSubmit={(e) => handleCreateChat(e, proj.id)} className="sidebar-input-form inset">
                      <input
                        type="text"
                        className="sidebar-input"
                        placeholder="Название чата..."
                        value={newChatName}
                        onChange={(e) => setNewChatName(e.target.value)}
                        autoFocus
                      />
                      <div className="sidebar-form-btns">
                        <button type="submit" className="mini-confirm">
                          <Icon name="check" size={13} />
                        </button>
                        <button type="button" className="mini-cancel" onClick={() => setAddingChatFor(null)}>
                          <Icon name="close" size={13} />
                        </button>
                      </div>
                    </form>
                  )}

                  <div className="chats-list">
                    {(proj.chats || []).map((chat) => {
                      const isChatActive = isProjActive && chat.id === activeChatId;
                      return (
                        <div
                          key={chat.id}
                          className={`chat-item ${isChatActive ? "active" : ""}`}
                          onClick={() => onSelectChat(proj.id, chat.id)}
                        >
                          <span className="chat-bubble-icon">
                            <Icon name="chat" size={13} />
                          </span>
                          <span className="chat-title" title={chat.title}>{chat.title}</span>
                          {(proj.chats || []).length > 1 && (
                            <button
                              className="chat-delete-btn"
                              onClick={(e) => {
                                e.stopPropagation();
                                onDeleteChat(proj.id, chat.id);
                              }}
                              title="Удалить чат"
                            >
                              <Icon name="close" size={11} />
                            </button>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </aside>
  );
}

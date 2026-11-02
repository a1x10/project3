// Projects & chats are stored locally, per signed-in account.
const PROJECTS_KEY = "vibing_projects";

export function getProjects(userId = "guest") {
  try {
    const raw = localStorage.getItem(PROJECTS_KEY + "_" + userId);
    if (!raw) {
      // Create initial project
      const initialProject = {
        id: "proj-1",
        name: "Мой первый сайт",
        createdAt: new Date().toISOString(),
        chats: [
          {
            id: "chat-1",
            title: "Создание лендинга",
            createdAt: new Date().toISOString(),
            messages: [],
            siteHtml: "",
          },
        ],
      };
      localStorage.setItem(PROJECTS_KEY + "_" + userId, JSON.stringify([initialProject]));
      return [initialProject];
    }
    return JSON.parse(raw);
  } catch {
    return [];
  }
}

export function saveProjects(userId = "guest", projects) {
  try {
    localStorage.setItem(PROJECTS_KEY + "_" + userId, JSON.stringify(projects));
  } catch (e) {
    console.error("Save projects error:", e);
  }
}



// Storage & Auth Manager for Vibing AI Studio
const USERS_KEY = "vibing_users";
const SESSION_KEY = "vibing_session";
const PROJECTS_KEY = "vibing_projects";

// Default admin and demo plans
export const PLANS = {
  free: {
    id: "free",
    name: "Бесплатный",
    tokenLimit: 5000,
    dailyRequests: 10,
    badge: "Free",
    price: "0 ₽",
  },
  pro: {
    id: "pro",
    name: "Pro Разработчик",
    tokenLimit: 50000,
    dailyRequests: 100,
    badge: "PRO",
    price: "990 ₽ / мес",
  },
  unlimited: {
    id: "unlimited",
    name: "Безлимит (Админ / VIP)",
    tokenLimit: Infinity,
    dailyRequests: Infinity,
    badge: "VIP ∞",
    price: "Безлимит",
  },
};

export const INITIAL_ADMIN = {
  id: "admin-root",
  username: "taranka",
  email: "taranka@vibing.local",
  password: "Vibe#Admin987!Secure99",
  role: "admin", // 'admin' | 'user'
  plan: "unlimited",
  tokensUsed: 0,
  requestsToday: 0,
  lastRequestDate: new Date().toISOString().slice(0, 10),
  createdAt: new Date().toISOString(),
};

export function getUsers() {
  try {
    const raw = localStorage.getItem(USERS_KEY);
    if (!raw) {
      const initial = [INITIAL_ADMIN];
      localStorage.setItem(USERS_KEY, JSON.stringify(initial));
      return initial;
    }
    let users = JSON.parse(raw);
    const adminIdx = users.findIndex((u) => u.username === "taranka" || u.username === "admin");
    if (adminIdx === -1) {
      users.push(INITIAL_ADMIN);
    } else {
      // Ensure admin has username taranka, strong password and unlimited plan
      users[adminIdx].username = "taranka";
      users[adminIdx].email = "taranka@vibing.local";
      users[adminIdx].password = INITIAL_ADMIN.password;
      users[adminIdx].role = "admin";
      users[adminIdx].plan = "unlimited";
    }
    localStorage.setItem(USERS_KEY, JSON.stringify(users));
    return users;
  } catch {
    return [INITIAL_ADMIN];
  }
}

export function saveUsers(users) {
  try {
    localStorage.setItem(USERS_KEY, JSON.stringify(users));
  } catch (e) {
    console.error("Save users error:", e);
  }
}

export function getCurrentUser() {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const session = JSON.parse(raw);
    const users = getUsers();
    const found = users.find((u) => u.id === session.id);
    return found || null;
  } catch {
    return null;
  }
}

export function setCurrentUser(user) {
  try {
    if (!user) {
      localStorage.removeItem(SESSION_KEY);
    } else {
      localStorage.setItem(SESSION_KEY, JSON.stringify({ id: user.id, username: user.username }));
    }
  } catch (e) {
    console.error("Set current user error:", e);
  }
}

export function registerUser(username, email, password) {
  const users = getUsers();
  if (users.some((u) => u.username.toLowerCase() === username.toLowerCase())) {
    throw new Error("Пользователь с таким логином уже существует");
  }
  if (users.some((u) => u.email.toLowerCase() === email.toLowerCase())) {
    throw new Error("Пользователь с таким email уже существует");
  }
  const newUser = {
    id: "user-" + Date.now() + "-" + Math.random().toString(36).slice(2, 6),
    username: username.trim(),
    email: email.trim(),
    password,
    role: "user",
    plan: "free",
    tokensUsed: 0,
    requestsToday: 0,
    lastRequestDate: new Date().toISOString().slice(0, 10),
    createdAt: new Date().toISOString(),
  };
  users.push(newUser);
  saveUsers(users);
  setCurrentUser(newUser);
  return newUser;
}

export function loginUser(loginOrEmail, password) {
  const users = getUsers();
  const found = users.find(
    (u) =>
      (u.username.toLowerCase() === loginOrEmail.toLowerCase() ||
        u.email.toLowerCase() === loginOrEmail.toLowerCase()) &&
      u.password === password
  );
  if (!found) {
    throw new Error("Неверный логин или пароль");
  }
  setCurrentUser(found);
  return found;
}

export function logoutUser() {
  setCurrentUser(null);
}

export function checkUserLimit(user) {
  if (!user) return { ok: false, reason: "Войдите в систему для продолжения" };
  if (user.role === "admin" || user.plan === "unlimited") {
    return { ok: true, unlimited: true };
  }
  const today = new Date().toISOString().slice(0, 10);
  const requests = user.lastRequestDate === today ? (user.requestsToday || 0) : 0;
  const planInfo = PLANS[user.plan] || PLANS.free;

  if (requests >= planInfo.dailyRequests) {
    return {
      ok: false,
      reason: `Достигнут дневной лимит (${planInfo.dailyRequests} запросов в день на тарифе ${planInfo.name}). Обновите тариф или обратитесь к администратору!`,
    };
  }
  if ((user.tokensUsed || 0) >= planInfo.tokenLimit) {
    return {
      ok: false,
      reason: `Исчерпан лимит токенов (${planInfo.tokenLimit} токенов на тарифе ${planInfo.name}).`,
    };
  }
  return { ok: true, unlimited: false, remainingToday: planInfo.dailyRequests - requests };
}

export function recordUsage(userId, tokensSpent = 1) {
  const users = getUsers();
  const idx = users.findIndex((u) => u.id === userId);
  if (idx === -1) return;
  const user = users[idx];
  const today = new Date().toISOString().slice(0, 10);
  if (user.lastRequestDate !== today) {
    user.lastRequestDate = today;
    user.requestsToday = 0;
  }
  user.requestsToday = (user.requestsToday || 0) + 1;
  user.tokensUsed = (user.tokensUsed || 0) + tokensSpent;
  users[idx] = user;
  saveUsers(users);
}

// Projects & Chats Storage
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


// Activation Keys Storage & Verification
const KEYS_STORAGE_KEY = "vibing_activation_keys";

export function getActivationKeys() {
  try {
    const raw = localStorage.getItem(KEYS_STORAGE_KEY);
    if (!raw) return [];
    return JSON.parse(raw);
  } catch {
    return [];
  }
}

export function saveActivationKeys(keys) {
  try {
    localStorage.setItem(KEYS_STORAGE_KEY, JSON.stringify(keys));
  } catch (e) {
    console.error("Save activation keys error:", e);
  }
}

export function createActivationKey({ code, plan = "pro", maxUses = 10, expiresAt }) {
  const keys = getActivationKeys();
  const cleanCode = (code || "KEY-" + Math.random().toString(36).slice(2, 8).toUpperCase()).trim();
  if (keys.some((k) => k.code.toUpperCase() === cleanCode.toUpperCase())) {
    throw new Error("Такой ключ уже существует");
  }
  const newKey = {
    id: "key-" + Date.now(),
    code: cleanCode,
    plan,
    maxUses: Number(maxUses) || 1,
    usedCount: 0,
    expiresAt: expiresAt || new Date(Date.now() + 30 * 24 * 3600 * 1000).toISOString().slice(0, 10),
    createdAt: new Date().toISOString(),
  };
  keys.unshift(newKey);
  saveActivationKeys(keys);
  return newKey;
}

export function redeemActivationKey(userId, rawCode) {
  const code = (rawCode || "").trim().toUpperCase();
  if (!code) throw new Error("Введите код активации");
  const keys = getActivationKeys();
  const idx = keys.findIndex((k) => k.code.toUpperCase() === code);
  if (idx === -1) throw new Error("Неверный ключ активации");

  const key = keys[idx];
  const today = new Date().toISOString().slice(0, 10);
  if (key.expiresAt && key.expiresAt < today) {
    throw new Error(`Срок действия ключа истёк (${key.expiresAt})`);
  }
  if (key.usedCount >= key.maxUses) {
    throw new Error("Лимит активаций этого ключа исчерпан");
  }

  // Update key usage
  key.usedCount = (key.usedCount || 0) + 1;
  keys[idx] = key;
  saveActivationKeys(keys);

  // Upgrade user
  const users = getUsers();
  const userIdx = users.findIndex((u) => u.id === userId);
  if (userIdx !== -1) {
    users[userIdx].plan = key.plan;
    saveUsers(users);
  }
  return { ok: true, plan: key.plan };
}

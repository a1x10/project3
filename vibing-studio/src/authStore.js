// Storage & Auth Manager for Vibing AI Studio
import { sha256 } from "./sha256.js";
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

// Hash of the admin password that shipped in plain text in earlier builds. Accounts still using
// it are flagged so the owner changes it (the plain value is no longer in the code).
const LEAKED_PASSWORD_HASHES = new Set(["990ac8c419c469bee1ea098ac1bb0e88d927835a210778a57ddbfcdc6ed65e21"]);
const HASH_ROUNDS = 5000;

function randomSalt() {
  const a = new Uint8Array(16);
  (globalThis.crypto || window.crypto).getRandomValues(a);
  return Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Salted, iterated SHA-256. (Client-side only: see README about the need for a server.) */
export function hashPassword(password, salt) {
  let h = sha256(salt + ":" + password);
  for (let i = 1; i < HASH_ROUNDS; i++) h = sha256(salt + h);
  return h;
}

function withPassword(user, password) {
  const salt = randomSalt();
  const { password: _plain, ...rest } = user;
  return { ...rest, salt, passwordHash: hashPassword(password, salt), mustChangePassword: LEAKED_PASSWORD_HASHES.has(sha256(password)) || undefined };
}

function verifyPassword(user, password) {
  if (user.passwordHash && user.salt) return hashPassword(password, user.salt) === user.passwordHash;
  return typeof user.password === "string" && user.password === password;
}

function publicUser(u) {
  if (!u) return u;
  const { password: _p, passwordHash: _h, salt: _s, ...rest } = u;
  return rest;
}

/** Load users, migrating plain-text passwords from older builds to salted hashes. */
export function getUsers() {
  try {
    const raw = localStorage.getItem(USERS_KEY);
    const users = raw ? JSON.parse(raw) : [];
    let changed = false;
    const migrated = users.map((u) => {
      if (typeof u.password === "string") {
        changed = true;
        return withPassword(u, u.password);
      }
      return u;
    });
    if (changed) localStorage.setItem(USERS_KEY, JSON.stringify(migrated));
    return migrated;
  } catch {
    return [];
  }
}

export function saveUsers(users) {
  try {
    localStorage.setItem(USERS_KEY, JSON.stringify(users));
  } catch (e) {
    console.error("Save users error:", e);
  }
}

export function hasAdmin(users = getUsers()) {
  return users.some((u) => u.role === "admin");
}

export function getCurrentUser() {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const session = JSON.parse(raw);
    const found = getUsers().find((u) => u.id === session.id);
    return found ? publicUser(found) : null;
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

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function registerUser(username, email, password) {
  const name = (username || "").trim();
  const mail = (email || "").trim();
  if (!/^[\p{L}\p{N}_.-]{3,32}$/u.test(name)) throw new Error("Логин: 3–32 символа (буквы, цифры, _ . -)");
  if (!EMAIL_RE.test(mail)) throw new Error("Введите корректный email");
  if ((password || "").length < 8) throw new Error("Пароль должен быть не короче 8 символов");
  const users = getUsers();
  if (users.some((u) => u.username.toLowerCase() === name.toLowerCase())) {
    throw new Error("Пользователь с таким логином уже существует");
  }
  if (users.some((u) => (u.email || "").toLowerCase() === mail.toLowerCase())) {
    throw new Error("Пользователь с таким email уже существует");
  }
  // The first account on a fresh installation becomes the owner/administrator.
  const owner = !hasAdmin(users);
  const newUser = withPassword(
    {
      id: "user-" + Date.now() + "-" + Math.random().toString(36).slice(2, 6),
      username: name,
      email: mail,
      role: owner ? "admin" : "user",
      plan: owner ? "unlimited" : "free",
      tokensUsed: 0,
      requestsToday: 0,
      lastRequestDate: new Date().toISOString().slice(0, 10),
      createdAt: new Date().toISOString(),
    },
    password
  );
  users.push(newUser);
  saveUsers(users);
  setCurrentUser(newUser);
  return publicUser(newUser);
}

export function loginUser(loginOrEmail, password) {
  const key = (loginOrEmail || "").trim().toLowerCase();
  const users = getUsers();
  const found = users.find((u) => u.username.toLowerCase() === key || (u.email || "").toLowerCase() === key);
  if (!found || !verifyPassword(found, password)) {
    throw new Error("Неверный логин или пароль");
  }
  setCurrentUser(found);
  return publicUser(found);
}

export function changePassword(userId, oldPassword, newPassword) {
  if ((newPassword || "").length < 8) throw new Error("Новый пароль должен быть не короче 8 символов");
  const users = getUsers();
  const idx = users.findIndex((u) => u.id === userId);
  if (idx === -1) throw new Error("Пользователь не найден");
  if (!verifyPassword(users[idx], oldPassword)) throw new Error("Текущий пароль указан неверно");
  if (LEAKED_PASSWORD_HASHES.has(sha256(newPassword))) throw new Error("Этот пароль был опубликован в коде старой версии — выберите другой");
  const updated = withPassword(users[idx], newPassword);
  delete updated.mustChangePassword;
  users[idx] = updated;
  saveUsers(users);
  return publicUser(updated);
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

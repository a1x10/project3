import { beforeEach, describe, expect, it } from "vitest";
import "./setup-storage.js";
import { getProviderConfig, defaultProviderConfig } from "../src/providerStore.js";
import { registerUser, loginUser, getUsers, getCurrentUser, changePassword, checkUserLimit, recordUsage, createActivationKey, redeemActivationKey, logoutUser } from "../src/authStore.js";

beforeEach(() => localStorage.clear());

describe("provider config", () => {
  it("defaults to FreeLLMAPI", () => {
    expect(getProviderConfig().activeProviderId).toBe("freellmapi");
    expect(defaultProviderConfig().providers.freellmapi.model).toBe("auto:smart");
  });
  it("migrates v1 configs: adds FreeLLMAPI, switches untouched local default, updates retired models", () => {
    localStorage.setItem("vibing_ai_providers", JSON.stringify({ activeProviderId: "local", providers: { local: { apiKey: "", model: "gpt-oss-20b", customUrl: "" }, anthropic: { apiKey: "k", model: "claude-3-7-sonnet-20250219" } } }));
    const c = getProviderConfig();
    expect(c.activeProviderId).toBe("freellmapi");
    expect(c.providers.freellmapi).toBeTruthy();
    expect(c.providers.anthropic).toEqual({ apiKey: "k", model: "claude-sonnet-5-5" });
    expect(JSON.parse(localStorage.getItem("vibing_ai_providers")).version).toBe(2);
  });
  it("keeps a deliberate provider choice", () => {
    localStorage.setItem("vibing_ai_providers", JSON.stringify({ activeProviderId: "gemini", providers: {} }));
    expect(getProviderConfig().activeProviderId).toBe("gemini");
  });
});

describe("auth", () => {
  it("first account becomes owner/admin, later ones are regular users; passwords are hashed", () => {
    const owner = registerUser("owner", "owner@example.com", "correct horse");
    expect(owner).toMatchObject({ role: "admin", plan: "unlimited" });
    expect(owner.passwordHash).toBeUndefined();
    const u = registerUser("alice", "alice@example.com", "password123");
    expect(u).toMatchObject({ role: "user", plan: "free" });
    const raw = localStorage.getItem("vibing_users");
    expect(raw).not.toContain("password123");
    expect(raw).not.toContain("correct horse");
    expect(getUsers()[1].passwordHash).toMatch(/^[0-9a-f]{64}$/);
    logoutUser();
    expect(getCurrentUser()).toBeNull();
    expect(loginUser("ALICE@example.com", "password123").username).toBe("alice");
    expect(() => loginUser("alice", "wrong-password")).toThrow(/Неверный/);
  });
  it("validates input", () => {
    expect(() => registerUser("ab", "a@b.co", "12345678")).toThrow(/Логин/);
    expect(() => registerUser("abc", "not-an-email", "12345678")).toThrow(/email/);
    expect(() => registerUser("abc", "a@b.co", "short")).toThrow(/8/);
    registerUser("abc", "a@b.co", "12345678");
    expect(() => registerUser("ABC", "x@b.co", "12345678")).toThrow(/логином/);
  });
  it("migrates plain-text passwords from old builds and flags the leaked admin password", () => {
    localStorage.setItem("vibing_users", JSON.stringify([{ id: "admin-root", username: "taranka", email: "t@v.local", password: "Vibe#Admin987!Secure99", role: "admin", plan: "unlimited" }, { id: "u1", username: "bob", email: "b@b.co", password: "bobpassword", role: "user", plan: "free" }]));
    const users = getUsers();
    expect(localStorage.getItem("vibing_users")).not.toContain("Vibe#Admin987");
    expect(users[0].mustChangePassword).toBe(true);
    expect(users[1].mustChangePassword).toBeUndefined();
    const admin = loginUser("taranka", "Vibe#Admin987!Secure99");
    expect(admin.mustChangePassword).toBe(true);
    expect(() => changePassword(admin.id, "Vibe#Admin987!Secure99", "Vibe#Admin987!Secure99")).toThrow(/опубликован/);
    const after = changePassword(admin.id, "Vibe#Admin987!Secure99", "a brand new secret");
    expect(after.mustChangePassword).toBeUndefined();
    expect(loginUser("taranka", "a brand new secret").role).toBe("admin");
  });
  it("enforces daily limits and activation keys", () => {
    registerUser("owner", "o@o.co", "ownerpass");
    const u = registerUser("carl", "c@c.co", "carlpass1");
    for (let i = 0; i < 10; i++) recordUsage(u.id, 10);
    const fresh = getUsers().find((x) => x.id === u.id);
    expect(checkUserLimit(fresh).ok).toBe(false);
    const key = createActivationKey({ code: "VIBE-PRO-TEST", plan: "pro", maxUses: 1 });
    expect(redeemActivationKey(u.id, "vibe-pro-test")).toEqual({ ok: true, plan: "pro" });
    expect(getUsers().find((x) => x.id === u.id).plan).toBe("pro");
    expect(() => redeemActivationKey(u.id, key.code)).toThrow(/исчерпан/);
  });
});

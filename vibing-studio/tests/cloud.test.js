import { beforeEach, describe, expect, it } from "vitest";
import { cloudTarget, cloudUrl, loadCredentials, saveCredentials, setCloudUrl } from "../src/cloud.js";

beforeEach(() => {
  localStorage.clear();
  delete globalThis.window;
});

describe("cloud client", () => {
  it("server URL: saved value, desktop config", () => {
    expect(cloudUrl()).toBe("");
    globalThis.window = { stellaDesktop: { cloudUrl: "https://desk.example.com/" } };
    expect(cloudUrl()).toBe("https://desk.example.com");
    setCloudUrl("https://mine.example.com/");
    expect(cloudUrl()).toBe("https://mine.example.com");
    expect(cloudTarget("sk", "auto:fast")).toEqual({ url: "https://mine.example.com/v1/chat/completions", model: "auto:fast", apiKey: "sk" });
  });
  it("credentials go to the desktop secure store when available", async () => {
    const vault = new Map();
    globalThis.window = { stellaDesktop: { secureGet: async (k) => vault.get(k) || "", secureSet: async (k, v) => vault.set(k, v) } };
    await saveCredentials({ apiKey: "sk-stella-1", user: { id: 1 } });
    expect(localStorage.getItem("stella-cloud-credentials")).toBeNull();
    expect((await loadCredentials()).apiKey).toBe("sk-stella-1");
    await saveCredentials(null);
    expect(await loadCredentials()).toBeNull();
  });
  it("falls back to localStorage in a browser build", async () => {
    await saveCredentials({ apiKey: "sk-stella-2" });
    expect((await loadCredentials()).apiKey).toBe("sk-stella-2");
  });
});

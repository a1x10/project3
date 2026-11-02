// Vibing AI Studio — Windows desktop app (Electron).
// The UI is the Vite build in ../dist loaded from disk; all AI traffic goes to the Stella Cloud server.
const { app, BrowserWindow, ipcMain, safeStorage, shell, Menu } = require("electron");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const isDev = !!process.env.STUDIO_DEV_URL;
const userData = process.env.STUDIO_USER_DATA;
if (userData) app.setPath("userData", userData);

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return {};
  }
}

/** Server address: STELLA_CLOUD_URL env, then config.json next to the .exe / in userData, then the build default. */
function cloudUrl() {
  if (process.env.STELLA_CLOUD_URL) return process.env.STELLA_CLOUD_URL;
  const candidates = [path.join(path.dirname(process.execPath), "stella-cloud.json"), path.join(app.getPath("userData"), "stella-cloud.json")];
  for (const f of candidates) {
    const j = readJson(f);
    if (typeof j.url === "string" && j.url) return j.url;
  }
  // shared with STELLA CODER (`stella-coder login`) and the installer
  const stellaHome = process.env.STELLA_HOME || path.join(os.homedir(), ".stella");
  const shared = readJson(path.join(stellaHome, "credentials.json"))["cloud.url"];
  if (typeof shared === "string" && shared) return shared;
  return process.env.VITE_CLOUD_URL || "";
}

// ------- encrypted credential storage (Windows DPAPI via safeStorage)
const vaultFile = () => path.join(app.getPath("userData"), "credentials.bin");
function vaultRead() {
  try {
    const buf = fs.readFileSync(vaultFile());
    const text = safeStorage.isEncryptionAvailable() ? safeStorage.decryptString(buf) : buf.toString("utf8");
    return JSON.parse(text);
  } catch {
    return {};
  }
}
function vaultWrite(obj) {
  const text = JSON.stringify(obj);
  const data = safeStorage.isEncryptionAvailable() ? safeStorage.encryptString(text) : Buffer.from(text, "utf8");
  fs.mkdirSync(path.dirname(vaultFile()), { recursive: true });
  fs.writeFileSync(vaultFile(), data, { mode: 0o600 });
}

ipcMain.handle("secure:get", (_e, key) => {
  const v = vaultRead()[String(key)];
  return typeof v === "string" ? v : "";
});
ipcMain.handle("secure:set", (_e, key, value) => {
  const all = vaultRead();
  if (value) all[String(key)] = String(value);
  else delete all[String(key)];
  vaultWrite(all);
  return true;
});
ipcMain.handle("open-external", (_e, url) => {
  if (process.env.STUDIO_E2E) return (globalThis.__opened = [...(globalThis.__opened || []), String(url)]), true;
  if (/^https?:\/\//i.test(String(url)) || /^tg:\/\//i.test(String(url))) shell.openExternal(String(url));
  return true;
});
ipcMain.on("config:sync", (e) => {
  e.returnValue = { cloudUrl: cloudUrl(), deviceName: `${os.hostname()} · ${process.platform === "win32" ? "Windows" : process.platform}`, version: app.getVersion() };
});

function createWindow() {
  const win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 960,
    minHeight: 600,
    backgroundColor: "#13121a",
    title: "Vibing AI Studio",
    icon: path.join(__dirname, "icon.png"),
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  // Links open in the system browser / Telegram, never inside the app window.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^(https?|tg):/i.test(url)) shell.openExternal(url);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (e, url) => {
    if (!url.startsWith("file:") && !(isDev && url.startsWith(process.env.STUDIO_DEV_URL))) {
      e.preventDefault();
      if (/^(https?|tg):/i.test(url)) shell.openExternal(url);
    }
  });
  if (isDev) win.loadURL(process.env.STUDIO_DEV_URL);
  else win.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  return win;
}

if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on("second-instance", () => {
    const [w] = BrowserWindow.getAllWindows();
    if (w) {
      if (w.isMinimized()) w.restore();
      w.focus();
    }
  });
  app.whenReady().then(() => {
    Menu.setApplicationMenu(null);
    createWindow();
    app.on("activate", () => BrowserWindow.getAllWindows().length === 0 && createWindow());
  });
  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });
}

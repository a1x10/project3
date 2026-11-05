// Vibing AI Studio — Windows desktop app (Electron).
// The UI is the Vite build in ../dist loaded from disk; all AI traffic goes to the Stella Cloud server.
const { app, BrowserWindow, ipcMain, safeStorage, shell, Menu, dialog } = require("electron");
const { spawn } = require("node:child_process");
const readline = require("node:readline");
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

// ------- development agent (STELLA CODER in `serve` mode, one per window)
function agentEntry() {
  if (process.env.STUDIO_AGENT_ENTRY) return process.env.STUDIO_AGENT_ENTRY;
  const packaged = path.join(process.resourcesPath || "", "agent", "dist", "cli", "main.js");
  if (fs.existsSync(packaged)) return packaged;
  return path.join(__dirname, "..", "..", "stella-coder", "dist", "cli", "main.js");
}
const agents = new Map(); // webContents.id -> child process

function stopAgent(id) {
  const child = agents.get(id);
  if (!child) return;
  agents.delete(id);
  try {
    child.stdin.end();
  } catch {
    /* already closed */
  }
  setTimeout(() => {
    if (child.exitCode === null) child.kill();
  }, 3000).unref();
}

ipcMain.handle("agent:start", (e, opts) => {
  const wc = e.sender;
  stopAgent(wc.id);
  const entry = agentEntry();
  if (!fs.existsSync(entry)) return { ok: false, error: "Агент не найден в установке приложения (" + entry + ")" };
  const cwd = String(opts.cwd || "");
  if (!cwd || !fs.existsSync(cwd)) return { ok: false, error: "Папка проекта не найдена" };
  const args = [entry, "serve", "--cwd", cwd, "-m", "cloud:auto:smart", "--permission-mode", String(opts.mode || "default")];
  if (opts.resume) args.push("-c");
  const child = spawn(process.execPath, args, {
    cwd,
    env: {
      ...process.env,
      ELECTRON_RUN_AS_NODE: "1",
      STELLA_HOME: path.join(app.getPath("userData"), "stella"),
      STELLA_CLOUD_URL: String(opts.cloudUrl || ""),
      STELLA_CLOUD_API_KEY: String(opts.apiKey || ""),
      STELLA_MODEL: "cloud:auto:smart",
      STELLA_NO_ROUTER_AUTOSTART: "1",
      STELLA_NO_BROWSER: "1",
      FORCE_COLOR: "0",
    },
    windowsHide: true,
  });
  agents.set(wc.id, child);
  const emit = (msg) => {
    if (!wc.isDestroyed()) wc.send("agent:message", msg);
  };
  readline.createInterface({ input: child.stdout }).on("line", (line) => {
    try {
      emit(JSON.parse(line));
    } catch {
      /* not protocol */
    }
  });
  let stderr = "";
  child.stderr.on("data", (d) => {
    stderr = (stderr + d).slice(-4000);
  });
  child.on("error", (err) => emit({ type: "error", fatal: true, message: err.message }));
  child.on("exit", (code) => {
    if (agents.get(wc.id) === child) agents.delete(wc.id);
    emit({ type: "exit", code, stderr: code ? stderr.slice(-1500) : "" });
  });
  return { ok: true };
});
ipcMain.handle("agent:send", (e, msg) => {
  const child = agents.get(e.sender.id);
  if (!child) return false;
  child.stdin.write(JSON.stringify(msg) + "\n");
  return true;
});
ipcMain.handle("agent:stop", (e) => {
  stopAgent(e.sender.id);
  return true;
});
ipcMain.handle("agent:pick-folder", async (e) => {
  if (process.env.STUDIO_E2E_FOLDER) return process.env.STUDIO_E2E_FOLDER;
  const win = BrowserWindow.fromWebContents(e.sender);
  const r = await dialog.showOpenDialog(win, { title: "Папка проекта", properties: ["openDirectory", "createDirectory"] });
  return r.canceled ? "" : r.filePaths[0] || "";
});
ipcMain.handle("agent:open-path", (_e, p) => {
  if (process.env.STUDIO_E2E) return true;
  if (typeof p === "string" && fs.existsSync(p)) shell.openPath(p);
  return true;
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
  win.webContents.on("destroyed", () => stopAgent(win.webContents.id));
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

// Bridge between the sandboxed UI and the main process (no Node access in the page).
const { contextBridge, ipcRenderer } = require("electron");

const cfg = ipcRenderer.sendSync("config:sync");
contextBridge.exposeInMainWorld("stellaDesktop", {
  cloudUrl: cfg.cloudUrl,
  deviceName: cfg.deviceName,
  version: cfg.version,
  secureGet: (key) => ipcRenderer.invoke("secure:get", key),
  secureSet: (key, value) => ipcRenderer.invoke("secure:set", key, value),
  openExternal: (url) => ipcRenderer.invoke("open-external", url),
  agent: {
    start: (opts) => ipcRenderer.invoke("agent:start", opts),
    send: (msg) => ipcRenderer.invoke("agent:send", msg),
    stop: () => ipcRenderer.invoke("agent:stop"),
    pickFolder: () => ipcRenderer.invoke("agent:pick-folder"),
    openPath: (p) => ipcRenderer.invoke("agent:open-path", p),
    onMessage: (cb) => {
      const h = (_e, m) => cb(m);
      ipcRenderer.on("agent:message", h);
      return () => ipcRenderer.removeListener("agent:message", h);
    },
  },
});

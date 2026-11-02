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
});

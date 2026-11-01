'use strict';
const { contextBridge, ipcRenderer } = require('electron');

const on = (ch) => (cb) => {
  const h = (_e, d) => cb(d);
  ipcRenderer.on(ch, h);
  return () => ipcRenderer.removeListener(ch, h);
};

contextBridge.exposeInMainWorld('stells', {
  info: () => ipcRenderer.invoke('app:info'),
  config: {
    get: () => ipcRenderer.invoke('config:get'),
    set: (p) => ipcRenderer.invoke('config:set', p),
    reset: () => ipcRenderer.invoke('config:reset'),
  },
  validateKey: (k) => ipcRenderer.invoke('key:validate', k),
  win: { min: () => ipcRenderer.send('win:min'), max: () => ipcRenderer.send('win:max'), close: () => ipcRenderer.send('win:close') },
  openExternal: (u) => ipcRenderer.invoke('open:external', u),
  openPath: (p) => ipcRenderer.invoke('open:path', p),
  showItem: (p) => ipcRenderer.invoke('show:item', p),
  models: {
    manifest: () => ipcRenderer.invoke('models:manifest'),
    installed: () => ipcRenderer.invoke('models:installed'),
    download: (a) => ipcRenderer.invoke('models:download', a),
    import: () => ipcRenderer.invoke('models:import'),
    remove: (f) => ipcRenderer.invoke('models:remove', f),
  },
  firmware: { download: () => ipcRenderer.invoke('firmware:download'), saveAs: (p) => ipcRenderer.invoke('firmware:saveAs', p) },
  vision: {
    install: () => ipcRenderer.invoke('vision:install'),
    start: (s) => ipcRenderer.invoke('vision:start', s),
    stop: () => ipcRenderer.invoke('vision:stop'),
    status: () => ipcRenderer.invoke('vision:status'),
    onLog: on('vision:log'), onProgress: on('vision:progress'), onStopped: on('vision:stopped'),
  },
  net: {
    discover: () => ipcRenderer.invoke('net:discover'),
    wol: (a) => ipcRenderer.invoke('net:wol', a),
    interfaces: () => ipcRenderer.invoke('net:interfaces'),
  },
  term: {
    start: (cwd) => ipcRenderer.invoke('term:start', cwd),
    write: (id, data) => ipcRenderer.send('term:write', { id, data }),
    kill: (id) => ipcRenderer.send('term:kill', id),
    onData: on('term:data'), onExit: on('term:exit'),
  },
  connector: {
    start: (lang, code) => ipcRenderer.invoke('connector:start', { lang, code }),
    send: (o) => ipcRenderer.send('connector:send', o),
    stop: () => ipcRenderer.invoke('connector:stop'),
    template: (l) => ipcRenderer.invoke('connector:template', l),
    onData: on('connector:data'), onTelemetry: on('connector:telemetry'), onClosed: on('connector:closed'),
  },
  file: { save: (a) => ipcRenderer.invoke('file:save', a), open: () => ipcRenderer.invoke('file:open') },
  onDownload: on('dl:progress'),
});

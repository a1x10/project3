const { contextBridge, ipcRenderer } = require('electron');

const on = (ch) => (cb) => {
  const h = (_e, d) => cb(d);
  ipcRenderer.on(ch, h);
  return () => ipcRenderer.removeListener(ch, h);
};

contextBridge.exposeInMainWorld('agy', {
  info: () => ipcRenderer.invoke('app:info'),
  check: () => ipcRenderer.invoke('agy:check'),
  install: () => ipcRenderer.invoke('agy:install'),
  models: () => ipcRenderer.invoke('agy:models'),
  verifyLogin: () => ipcRenderer.invoke('agy:verify-login'),
  onInstallLog: on('install:log'),

  termStart: () => ipcRenderer.invoke('term:start'),
  termRestart: () => ipcRenderer.invoke('term:restart'),
  termWrite: (d) => ipcRenderer.send('term:write', d),
  termResize: (cols, rows) => ipcRenderer.send('term:resize', { cols, rows }),
  termBuffer: () => ipcRenderer.invoke('term:buffer'),
  onTermData: on('term:data'),
  onTermExit: on('term:exit'),
  onMaybeLoggedIn: on('term:maybe-logged-in'),
  onAuthUrl: on('term:auth-url'),

  voiceStart: () => ipcRenderer.invoke('voice:start'),
  voiceStop: () => ipcRenderer.invoke('voice:stop'),

  send: (req) => ipcRenderer.send('chat:send', req),
  stop: (reqId) => ipcRenderer.send('chat:stop', reqId),
  onEvent: on('chat:event'),
  onDone: on('chat:done'),
  onBridgeAction: on('bridge:action'),
  cloudLogin: (url, user, pass) => ipcRenderer.invoke('cloud:login', { url, user, pass }),
  cloudLogout: () => ipcRenderer.invoke('cloud:logout'),
  cloudStatus: () => ipcRenderer.invoke('cloud:status'),
  cloudSync: (chats) => ipcRenderer.send('cloud:sync', chats),
  cloudChat: (chat, extra) => ipcRenderer.invoke('cloud:chat', { chat, extra }),
  cloudEv: (ev) => ipcRenderer.send('cloud:ev', ev),
  onCloudStatus: on('cloud:status'),
  onCloudCommand: on('cloud:command'),
  onCloudWaReply: on('cloud:wa-reply'),
  onControlStopped: on('control:stopped'),
  controlBrowser: (on) => ipcRenderer.invoke('control:browser', on),
  controlScreen: (on) => ipcRenderer.invoke('control:screen', on),
  controlStop: () => ipcRenderer.send('control:stop'),

  getSettings: () => ipcRenderer.invoke('settings:get'),
  setSettings: (p) => ipcRenderer.invoke('settings:set', p),
  loadChats: () => ipcRenderer.invoke('chats:load'),
  saveChats: (c) => ipcRenderer.invoke('chats:save', c),
  pickFolder: () => ipcRenderer.invoke('dialog:folder'),
  pickFiles: () => ipcRenderer.invoke('dialog:files'),
  openExternal: (u) => ipcRenderer.invoke('shell:open', u)
});

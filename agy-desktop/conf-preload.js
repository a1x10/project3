const { contextBridge, ipcRenderer } = require('electron');
const on = ch => cb => { const h = (_e, d) => cb(d); ipcRenderer.on(ch, h); return () => ipcRenderer.removeListener(ch, h); };
contextBridge.exposeInMainWorld('conf', {
  status: () => ipcRenderer.invoke('conf:status'),
  transcribe: (audio, who, hint) => ipcRenderer.invoke('conf:transcribe', { audio, who, hint }),
  assist: req => ipcRenderer.invoke('conf:assist', req),
  cancel: id => ipcRenderer.send('conf:cancel', id),
  save: (md, title) => ipcRenderer.invoke('conf:save', { md, title }),
  opacity: v => ipcRenderer.send('conf:opacity', v),
  pin: v => ipcRenderer.send('conf:pin', v),
  minimize: () => ipcRenderer.send('conf:minimize'),
  close: () => ipcRenderer.send('conf:closeWin'),
  onDelta: on('conf:delta'),
  onStop: on('conf:stop')
});

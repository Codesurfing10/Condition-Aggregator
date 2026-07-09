const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  showSaveDialog: (opts) => ipcRenderer.invoke('show-save-dialog', opts),
});

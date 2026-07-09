const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const path = require('path');

function createWindow() {
  const win = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js')
    }
  });

  // Load the app's index.html from project root
  win.loadFile(path.join(__dirname, '..', 'index.html'));

  // Open DevTools when in development environments
  if (process.env.NODE_ENV === 'development') {
    win.webContents.openDevTools();
  }
}

app.whenReady().then(() => {
  createWindow();

  app.on('activate', function () {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', function () {
  if (process.platform !== 'darwin') app.quit();
});

// Simple IPC example for saving a file (GPX/KML exports)
ipcMain.handle('show-save-dialog', async (event, options) => {
  const win = BrowserWindow.getFocusedWindow();
  return await dialog.showSaveDialog(win, options);
});

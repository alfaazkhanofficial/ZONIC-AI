import { contextBridge, ipcRenderer } from "electron";

// The ONLY surface exposed to the renderer. No generic ipcRenderer, no Node APIs, no arbitrary channels.
contextBridge.exposeInMainWorld("zonic", {
  getConnection: () => ipcRenderer.invoke("zonic:get-connection"),
  getBackendState: () => ipcRenderer.invoke("zonic:get-backend-state"),
  onBackendState: (cb: (s: unknown) => void) => {
    const h = (_e: unknown, s: unknown) => cb(s);
    ipcRenderer.on("zonic:backend-state", h);
    return () => ipcRenderer.removeListener("zonic:backend-state", h);
  },
  retryBackend: () => ipcRenderer.invoke("zonic:retry-backend"),
  openLogs: () => ipcRenderer.invoke("zonic:open-logs"),
  pickFolder: () => ipcRenderer.invoke("zonic:pick-folder"),
  pickExecutable: () => ipcRenderer.invoke("zonic:pick-executable"),
  getStartupLaunch: () => ipcRenderer.invoke("zonic:get-startup-launch"),
  setStartupLaunch: (v: boolean) => ipcRenderer.invoke("zonic:set-startup-launch", !!v),
});

import { app, BrowserWindow, dialog, ipcMain, session, shell, type IpcMainInvokeEvent } from "electron";
import crypto from "crypto";
import fs from "fs";
import net from "net";
import path from "path";
import { pathToFileURL } from "url";
import { BackendManager } from "./backend-manager";
import { resolveBackendLaunch } from "./launch";
import { isAllowedPermission, isTrustedUrl, webPreferences, type TrustContext } from "./security";
import { spawn } from "child_process";

app.setName("ZONIC M4");
const isDev = !app.isPackaged && process.env.NODE_ENV === "development";
const DEV_URL = "http://127.0.0.1:5173";
const distDir = path.join(app.getAppPath(), "dist");
const trust: TrustContext = { devUrl: isDev ? DEV_URL : null, distFileUrlPrefix: pathToFileURL(distDir).href + "/" };
const repoRoot = path.resolve(app.getAppPath(), "..", "..");
const dataDir = app.getPath("userData");

let win: BrowserWindow | null = null;
let appLoaded = false;
let quitting = false;

const backend = new BackendManager(
  {
    spawn: (command, args, opts) => spawn(command, args, { cwd: opts.cwd, env: opts.env, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] }),
    health: async (baseUrl, timeoutMs) => {
      try { return (await fetch(`${baseUrl}/health`, { signal: AbortSignal.timeout(timeoutMs) })).ok; } catch { return false; }
    },
    requestShutdown: async (baseUrl, token) => {
      await fetch(`${baseUrl}/api/shutdown`, { method: "POST", headers: { "X-Zonic-Token": token }, signal: AbortSignal.timeout(2000) });
    },
    pickPort: () => new Promise((resolve, reject) => {
      const s = net.createServer();
      s.once("error", reject);
      s.listen(0, "127.0.0.1", () => { const p = (s.address() as net.AddressInfo).port; s.close(() => resolve(p)); });
    }),
    newToken: () => crypto.randomBytes(24).toString("hex"),
    sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
  },
  {
    launch: () => resolveBackendLaunch({ packaged: app.isPackaged, resourcesPath: process.resourcesPath, repoRoot, platform: process.platform, env: process.env, exists: (p) => fs.existsSync(p) }),
    baseEnv: { ...(process.env as Record<string, string>), ZONIC_DATA_DIR: dataDir, ZONIC_PARENT_PID: String(process.pid) },
  },
);

const startupUrl = () => (isDev ? `${DEV_URL}/startup.html` : pathToFileURL(path.join(distDir, "startup.html")).href);
const appUrl = () => (isDev ? DEV_URL : pathToFileURL(path.join(distDir, "index.html")).href);

/** App icon (the Z mark). Resolved at runtime so dev, unpacked and packaged runs all find it; a missing file just means the default icon. */
function appIcon(): string | undefined {
  return [path.join(app.getAppPath(), "build", "icon.ico"), path.join(app.getAppPath(), "build", "icon.png")].find((p) => fs.existsSync(p));
}

function createWindow(): BrowserWindow {
  const w = new BrowserWindow({
    width: 1360, height: 860, minWidth: 960, minHeight: 640, show: false, title: "ZONIC M4", backgroundColor: "#080A0D", icon: appIcon(),
    autoHideMenuBar: true, webPreferences: webPreferences({ preload: path.join(__dirname, "preload.js"), packaged: app.isPackaged }),
  });
  w.once("ready-to-show", () => w.show());
  w.webContents.setWindowOpenHandler(() => ({ action: "deny" })); // links never spawn windows; external links are not opened silently
  w.webContents.on("will-navigate", (e, url) => { if (!isTrustedUrl(url, trust)) e.preventDefault(); });
  w.webContents.on("will-attach-webview", (e) => e.preventDefault());
  w.on("closed", () => { win = null; });
  return w;
}

function trusted(e: IpcMainInvokeEvent): boolean {
  return isTrustedUrl(e.senderFrame?.url ?? "", trust);
}

function registerIpc(): void {
  const guard = <T,>(fn: (e: IpcMainInvokeEvent, ...a: any[]) => T | Promise<T>) => async (e: IpcMainInvokeEvent, ...a: any[]) => {
    if (!trusted(e)) throw new Error("Untrusted sender");
    return fn(e, ...a);
  };
  ipcMain.handle("zonic:get-connection", guard(() => (backend.getStatus().state === "ready" ? { baseUrl: backend.baseUrl, token: backend.apiToken, version: app.getVersion(), platform: process.platform } : null)));
  ipcMain.handle("zonic:get-backend-state", guard(() => backend.getStatus()));
  ipcMain.handle("zonic:retry-backend", guard(async () => { await backend.retry().catch(() => undefined); }));
  ipcMain.handle("zonic:open-logs", guard(async () => { await shell.openPath(path.join(dataDir, "logs")); }));
  ipcMain.handle("zonic:pick-folder", guard(async () => {
    const r = await dialog.showOpenDialog(win!, { properties: ["openDirectory"], title: "Choose a workspace folder" });
    return r.canceled ? null : r.filePaths[0];
  }));
  ipcMain.handle("zonic:pick-executable", guard(async () => {
    const r = await dialog.showOpenDialog(win!, { properties: ["openFile"], title: "Choose an application", filters: process.platform === "win32" ? [{ name: "Applications", extensions: ["exe"] }] : [] });
    return r.canceled ? null : r.filePaths[0];
  }));
  ipcMain.handle("zonic:get-startup-launch", guard(() => app.getLoginItemSettings().openAtLogin));
  ipcMain.handle("zonic:set-startup-launch", guard((_e, v: boolean) => { app.setLoginItemSettings({ openAtLogin: !!v }); return app.getLoginItemSettings().openAtLogin; }));
}

function hardenSession(): void {
  const ses = session.defaultSession;
  ses.setPermissionRequestHandler((wc, permission, cb) => cb(isAllowedPermission(permission) && isTrustedUrl(wc.getURL(), trust)));
  ses.setPermissionCheckHandler((wc, permission) => isAllowedPermission(permission) && (wc ? isTrustedUrl(wc.getURL(), trust) : false));
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });

  app.whenReady().then(async () => {
    hardenSession();
    registerIpc();
    win = createWindow();
    backend.on("state", (s) => {
      win?.webContents.send("zonic:backend-state", s);
      if (!win) return;
      if (s.state === "ready" && !appLoaded) { appLoaded = true; void win.loadURL(appUrl()); }
      if (s.state === "failed" && appLoaded) { appLoaded = false; void win.loadURL(startupUrl()); } // fall back to the retry screen
    });
    await win.loadURL(startupUrl());
    backend.start().catch(() => undefined); // failure is surfaced on the startup page with Retry / logs
  });

  app.on("window-all-closed", () => app.quit());
  app.on("before-quit", (e) => {
    if (quitting) return;
    e.preventDefault();
    quitting = true;
    void backend.stop().finally(() => app.exit(0));
  });
}

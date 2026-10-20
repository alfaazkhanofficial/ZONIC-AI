import { describe, expect, it } from "vitest";
import { isAllowedPermission, isTrustedUrl, webPreferences } from "./security";

describe("renderer security configuration", () => {
  const p = webPreferences({ preload: "/x/preload.js", packaged: true });
  it("isolates the renderer", () => {
    expect(p.contextIsolation).toBe(true);
    expect(p.nodeIntegration).toBe(false);
    expect(p.sandbox).toBe(true);
    expect(p.webSecurity).toBe(true);
    expect(p.allowRunningInsecureContent).toBe(false);
    expect(p.webviewTag).toBe(false);
    expect(p.nodeIntegrationInWorker).toBe(false);
  });
  it("disables devtools only in packaged builds", () => {
    expect(p.devTools).toBe(false);
    expect(webPreferences({ preload: "x", packaged: false }).devTools).toBe(true);
  });
  it("grants only the microphone", () => {
    expect(isAllowedPermission("media")).toBe(true);
    for (const x of ["geolocation", "notifications", "clipboard-read", "midi", "openExternal", "fullscreen", "camera"]) expect(isAllowedPermission(x)).toBe(false);
  });
  it("trusts only the app's own pages", () => {
    const ctx = { devUrl: "http://127.0.0.1:5173", distFileUrlPrefix: "file:///app/dist/" };
    expect(isTrustedUrl("http://127.0.0.1:5173/startup.html", ctx)).toBe(true);
    expect(isTrustedUrl("file:///app/dist/index.html", ctx)).toBe(true);
    for (const bad of ["https://evil.example", "file:///etc/passwd", "http://127.0.0.1:5173.evil.com/", "http://127.0.0.1:9999/", "", "file:///app/dist-other/x.html"]) expect(isTrustedUrl(bad, ctx)).toBe(false);
    expect(isTrustedUrl("http://127.0.0.1:5173/x", { ...ctx, devUrl: null })).toBe(false);
  });
});

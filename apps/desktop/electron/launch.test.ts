import { describe, expect, it } from "vitest";
import { resolveBackendLaunch } from "./launch";

const base = { resourcesPath: "/res", repoRoot: "/repo", env: {}, exists: () => true };
describe("resolveBackendLaunch", () => {
  it("dev uses the venv interpreter and -m app.main", () => {
    const r = resolveBackendLaunch({ ...base, packaged: false, platform: "win32" });
    expect(r).toMatchObject({ args: ["-m", "app.main"] });
    expect("command" in r && r.command.replaceAll("\\", "/")).toBe("/repo/backend/.venv/Scripts/python.exe");
  });
  it("packaged uses the frozen executable", () => {
    const r = resolveBackendLaunch({ ...base, packaged: true, platform: "win32" });
    expect("command" in r && r.command.replaceAll("\\", "/")).toBe("/res/backend/zonic-backend.exe");
  });
  it("gives actionable errors when pieces are missing", () => {
    expect(resolveBackendLaunch({ ...base, packaged: false, platform: "win32", exists: () => false })).toEqual({ error: expect.stringContaining("setup.ps1") });
    expect(resolveBackendLaunch({ ...base, packaged: true, platform: "win32", exists: () => false })).toEqual({ error: expect.stringContaining("Reinstall") });
  });
  it("honours ZONIC_PYTHON", () => {
    expect(resolveBackendLaunch({ ...base, packaged: true, platform: "win32", env: { ZONIC_PYTHON: "C:/py/python.exe" } })).toMatchObject({ command: "C:/py/python.exe" });
  });
});

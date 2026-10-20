import { EventEmitter } from "events";
import { describe, expect, it } from "vitest";
import { BackendManager, type ChildLike, type Deps } from "./backend-manager";

class FakeChild extends EventEmitter implements ChildLike {
  pid = 1234;
  stdout = new EventEmitter();
  stderr = new EventEmitter();
  killed: string[] = [];
  kill(sig?: NodeJS.Signals) { this.killed.push(sig ?? "SIGTERM"); if (this.dieOnKill) setTimeout(() => this.die(0), 1); return true; }
  dieOnKill = true;
  die(code: number | null) { this.emit("exit", code, null); }
}

function rig(opts: { healthy?: () => boolean; shutdownKills?: boolean } = {}) {
  const children: FakeChild[] = [];
  const shutdowns: string[] = [];
  const deps: Deps = {
    spawn: () => { const c = new FakeChild(); children.push(c); return c; },
    health: async () => (opts.healthy ? opts.healthy() : true),
    requestShutdown: async (_u, token) => { shutdowns.push(token); if (opts.shutdownKills !== false) setTimeout(() => children.at(-1)!.die(0), 1); },
    pickPort: async () => 45678,
    newToken: () => "secret-token-abcdef",
    sleep: (ms) => new Promise((r) => setTimeout(r, Math.min(ms, 5))),
  };
  const mgr = new BackendManager(deps, { launch: () => ({ command: "py", args: ["-m", "app.main"], cwd: "." }), baseEnv: {}, startupTimeoutMs: 400, backoffMs: [1, 1, 1] });
  const states: string[] = [];
  mgr.on("state", (s) => states.push(s.state));
  return { mgr, children, shutdowns, states };
}

describe("BackendManager", () => {
  it("starts, gates on health, and exposes baseUrl/token only when ready", async () => {
    const { mgr, states } = rig();
    await mgr.start();
    expect(states).toEqual(["starting", "ready"]);
    expect(mgr.getStatus().baseUrl).toBe("http://127.0.0.1:45678");
    expect(mgr.apiToken).toBe("secret-token-abcdef");
  });

  it("fails honestly if the backend never becomes healthy, and kills the child", async () => {
    const { mgr, children } = rig({ healthy: () => false });
    await expect(mgr.start()).rejects.toThrow(/did not become healthy/);
    expect(mgr.getStatus().state).toBe("failed");
    expect(children[0].killed.length).toBeGreaterThan(0);
  });

  it("reports the TRUE reason when the backend crashes during startup (not a generic timeout)", async () => {
    const children: FakeChild[] = [];
    const deps: Deps = { spawn: () => { const c = new FakeChild(); children.push(c); setTimeout(() => c.die(1), 5); return c; }, health: async () => false, requestShutdown: async () => undefined,
      pickPort: async () => 1, newToken: () => "tok-tok-tok-tok-tok", sleep: (ms) => new Promise((r) => setTimeout(r, Math.min(ms, 5))) };
    const m = new BackendManager(deps, { launch: () => ({ command: "x", args: [], cwd: "." }), baseEnv: {}, startupTimeoutMs: 2000 });
    await expect(m.start()).rejects.toThrow(/exited unexpectedly \(code 1\)/);
    expect(m.getStatus().state).toBe("failed");
    expect(m.getStatus().detail).not.toMatch(/did not become healthy/);
  });

  it("reports a launch error (e.g. missing venv) without spawning", async () => {
    const m = new BackendManager({ spawn: () => { throw new Error("must not spawn"); } } as unknown as Deps, { launch: () => ({ error: "venv missing" }), baseEnv: {} });
    await expect(m.start()).rejects.toThrow("venv missing");
    expect(m.getStatus()).toMatchObject({ state: "failed", detail: "venv missing" });
  });

  it("restarts after an unexpected crash, keeping the same port and token, up to the limit", async () => {
    const { mgr, children, states } = rig();
    await mgr.start();
    children[0].die(1);
    await new Promise((r) => setTimeout(r, 60));
    expect(states).toContain("restarting");
    expect(children).toHaveLength(2);
    expect(mgr.getStatus()).toMatchObject({ state: "ready", baseUrl: "http://127.0.0.1:45678", restarts: 1 });
    for (let i = 0; i < 3; i++) { children.at(-1)!.die(1); await new Promise((r) => setTimeout(r, 60)); }
    expect(mgr.getStatus().state).toBe("failed");
    expect(mgr.getStatus().detail).toMatch(/restarts exhausted/);
  });

  it("stops gracefully through the shutdown API (no kill needed)", async () => {
    const { mgr, children, shutdowns } = rig();
    await mgr.start();
    await mgr.stop();
    expect(shutdowns).toEqual(["secret-token-abcdef"]);
    expect(children[0].killed).toEqual([]);
    expect(mgr.getStatus().state).toBe("stopped");
  });

  it("force-kills if graceful shutdown is ignored, so nothing is orphaned", async () => {
    const { mgr, children } = rig({ shutdownKills: false });
    await mgr.start();
    const stop = mgr.stop();
    await stop;
    expect(children[0].killed.length).toBeGreaterThan(0);
    expect(mgr.getStatus().state).toBe("stopped");
  }, 15000);

  it("keeps a redacted output tail for diagnostics", async () => {
    const { mgr, children } = rig();
    await mgr.start();
    children[0].stderr.emit("data", "boom with secret-token-abcdef inside\nsecond line");
    const tail = mgr.getStatus().tail.join("\n");
    expect(tail).toContain("second line");
    expect(tail).not.toContain("secret-token-abcdef");
  });

  it("retry() resets the restart budget and starts again", async () => {
    const { mgr, children } = rig();
    await mgr.start();
    await mgr.retry();
    expect(children).toHaveLength(2);
    expect(mgr.getStatus().state).toBe("ready");
  });
});

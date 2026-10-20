import { EventEmitter } from "events";

export type BackendState = "stopped" | "starting" | "ready" | "restarting" | "failed";
export interface BackendStatus {
  state: BackendState;
  detail: string;
  tail: string[];
  baseUrl: string | null;
  restarts: number;
}

export interface ChildLike {
  pid?: number;
  stdout: { on(ev: "data", cb: (b: Buffer | string) => void): unknown } | null;
  stderr: { on(ev: "data", cb: (b: Buffer | string) => void): unknown } | null;
  once(ev: "exit", cb: (code: number | null, signal: string | null) => void): unknown;
  kill(signal?: NodeJS.Signals): boolean;
}

export interface Deps {
  spawn: (command: string, args: string[], opts: { cwd: string; env: Record<string, string> }) => ChildLike;
  health: (baseUrl: string, timeoutMs: number) => Promise<boolean>;
  requestShutdown: (baseUrl: string, token: string) => Promise<void>;
  pickPort: () => Promise<number>;
  newToken: () => string;
  sleep: (ms: number) => Promise<void>;
}

export interface Options {
  launch: () => { command: string; args: string[]; cwd: string } | { error: string };
  baseEnv: Record<string, string>;
  startupTimeoutMs?: number;
  maxRestarts?: number;
  backoffMs?: number[];
}

const TAIL_LINES = 80;

/** Owns the Python backend process: start, health-gate, restart-with-limit, graceful stop. Never leaves it orphaned. */
export class BackendManager extends EventEmitter {
  private child: ChildLike | null = null;
  private port = 0;
  private token = "";
  private stopping = false;
  private exited = new EventEmitter();
  private tail: string[] = [];
  private restarts = 0;
  private status: BackendStatus = { state: "stopped", detail: "", tail: [], baseUrl: null, restarts: 0 };

  constructor(private deps: Deps, private opts: Options) {
    super();
  }

  get baseUrl(): string | null { return this.port ? `http://127.0.0.1:${this.port}` : null; }
  get apiToken(): string { return this.token; }
  getStatus(): BackendStatus { return { ...this.status, tail: [...this.tail] }; }

  private set(state: BackendState, detail: string): void {
    this.status = { state, detail, tail: [...this.tail], baseUrl: state === "ready" ? this.baseUrl : null, restarts: this.restarts };
    this.emit("state", this.getStatus());
  }

  async start(): Promise<void> {
    this.stopping = false;
    this.set("starting", "Launching the Python backend…");
    const spec = this.opts.launch();
    if ("error" in spec) { this.set("failed", spec.error); throw new Error(spec.error); }
    if (!this.port) { this.port = await this.deps.pickPort(); this.token = this.deps.newToken(); }
    const env = { ...this.opts.baseEnv, ZONIC_API_TOKEN: this.token, ZONIC_PORT: String(this.port), ZONIC_HOST: "127.0.0.1" };
    const child = this.deps.spawn(spec.command, spec.args, { cwd: spec.cwd, env });
    this.child = child;
    const onData = (b: Buffer | string) => {
      for (const line of String(b).split(/\r?\n/)) if (line.trim()) { this.tail.push(line.replaceAll(this.token, "[token]")); if (this.tail.length > TAIL_LINES) this.tail.shift(); }
    };
    child.stdout?.on("data", onData);
    child.stderr?.on("data", onData);
    child.once("exit", (code, signal) => this.onExit(child, code, signal));

    const timeout = this.opts.startupTimeoutMs ?? 30_000;
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      if (this.child !== child) break; // exited while starting
      if (await this.deps.health(this.baseUrl!, 1000)) { this.set("ready", "Backend healthy"); return; }
      await this.deps.sleep(250);
    }
    if (this.child !== child) throw new Error(this.status.detail); // it exited while starting; onExit already recorded the true reason
    await this.terminate(child); this.child = null;
    const why = `The backend did not become healthy within ${Math.round(timeout / 1000)}s.`;
    this.port = 0;
    this.set("failed", why);
    throw new Error(why);
  }

  private async onExit(child: ChildLike, code: number | null, signal: string | null): Promise<void> {
    this.exited.emit("exit", child);
    if (this.stopping || child !== this.child) return;
    this.child = null;
    const was = this.status.state;
    const detail = `The backend exited unexpectedly (code ${code ?? "?"}${signal ? `, signal ${signal}` : ""}).`;
    if (was === "starting") { this.port = 0; this.set("failed", detail); return; }
    const max = this.opts.maxRestarts ?? 3;
    if (this.restarts >= max) { this.port = 0; this.set("failed", `${detail} Automatic restarts exhausted.`); return; }
    const delay = (this.opts.backoffMs ?? [500, 1500, 4000])[Math.min(this.restarts, 2)];
    this.restarts += 1;
    this.set("restarting", `${detail} Restarting (${this.restarts}/${max})…`);
    await this.deps.sleep(delay);
    if (this.stopping) return;
    try { await this.start(); } catch { /* state already reported as failed */ }
  }

  async retry(): Promise<void> {
    this.restarts = 0;
    await this.stop();
    await this.start();
  }

  private waitExit(child: ChildLike, ms: number): Promise<boolean> {
    return new Promise((resolve) => {
      const t = setTimeout(() => { this.exited.off("exit", on); resolve(false); }, ms);
      const on = (c: ChildLike) => { if (c === child) { clearTimeout(t); this.exited.off("exit", on); resolve(true); } };
      this.exited.on("exit", on);
    });
  }

  private async terminate(child: ChildLike): Promise<void> {
    const gone = this.waitExit(child, 3000);
    child.kill();
    if (!(await gone)) { const gone2 = this.waitExit(child, 2000); child.kill("SIGKILL"); await gone2; }
  }

  async stop(): Promise<void> {
    this.stopping = true;
    const child = this.child;
    if (!child) { this.set("stopped", "Backend stopped"); return; }
    const exited = this.waitExit(child, 6000);
    try { if (this.baseUrl) await this.deps.requestShutdown(this.baseUrl, this.token); } catch { /* fall through to kill */ }
    if (!(await exited)) await this.terminate(child);
    this.child = null;
    this.set("stopped", "Backend stopped");
  }
}

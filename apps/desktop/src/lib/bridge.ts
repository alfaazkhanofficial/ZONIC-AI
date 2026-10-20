import type { Connection } from "./types";

export interface BackendStatusUi { state: "stopped" | "starting" | "ready" | "restarting" | "failed"; detail: string; tail: string[]; baseUrl: string | null; restarts: number }
export interface ZonicBridge {
  getConnection(): Promise<Connection | null>;
  getBackendState(): Promise<BackendStatusUi>;
  onBackendState(cb: (s: BackendStatusUi) => void): () => void;
  retryBackend(): Promise<void>;
  openLogs(): Promise<void>;
  pickFolder(): Promise<string | null>;
  pickExecutable(): Promise<string | null>;
  getStartupLaunch(): Promise<boolean>;
  setStartupLaunch(v: boolean): Promise<boolean>;
}
declare global { interface Window { zonic?: ZonicBridge } }

/** In Electron the preload bridge is used. In a plain browser (UI-only dev) a backend started by scripts/dev.ps1 is reached via Vite env vars. */
export function getBridge(): ZonicBridge {
  if (typeof window !== "undefined" && window.zonic) return window.zonic;
  const url = import.meta.env.VITE_ZONIC_URL as string | undefined;
  const token = import.meta.env.VITE_ZONIC_TOKEN as string | undefined;
  const noop = async () => undefined;
  return {
    getConnection: async () => (url && token ? { baseUrl: url, token } : null),
    getBackendState: async () => ({ state: url && token ? "ready" : "failed", detail: url && token ? "Browser dev mode" : "Set VITE_ZONIC_URL and VITE_ZONIC_TOKEN, or run inside Electron.", tail: [], baseUrl: url ?? null, restarts: 0 }),
    onBackendState: () => () => undefined,
    retryBackend: noop,
    openLogs: noop,
    pickFolder: async () => window.prompt("Absolute path of the folder to use as a workspace:") || null,
    pickExecutable: async () => window.prompt("Absolute path of the application (.exe):") || null,
    getStartupLaunch: async () => false,
    setStartupLaunch: async () => false,
  };
}

import { useCallback } from "react";
import { ApiError } from "./api";
import { useStore } from "./store";

export function useSettings() {
  const api = useStore((s) => s.api)!;
  const payload = useStore((s) => s.settings);
  const refresh = useStore((s) => s.refreshSettings);
  const refreshStatus = useStore((s) => s.refreshStatus);
  const toast = useStore((s) => s.toast);
  const patch = useCallback(async (group: string, p: Record<string, unknown>, confirm = false): Promise<boolean> => {
    try { await api.patchSettings(group, p, confirm); await Promise.all([refresh(), refreshStatus()]); return true; }
    catch (e) { toast("error", e instanceof ApiError ? e.message : "Could not save the setting."); return false; }
  }, [api, refresh, refreshStatus, toast]);
  return { s: payload?.settings, secrets: payload?.secrets, backend: payload?.secret_backend, patch, api, toast, refresh, refreshStatus };
}

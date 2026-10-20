import { useEffect, useState } from "react";
import { deriveAvatarState } from "./avatar";
import { isActive } from "./hooks";
import { useStore } from "./store";

const HOLD_MS = 15_000;

/** The AI Core / avatar state. Derived ONLY from real state: backend link, voice session, task state, approvals, failures, user cancels. */
export function useCoreState() {
  const link = useStore((s) => s.link);
  const voice = useStore((s) => s.voice.state);
  const approvals = useStore((s) => s.approvals.length);
  const tasks = useStore((s) => s.tasks);
  const toolCalls = useStore((s) => s.toolCalls);
  const lastFailureAt = useStore((s) => s.lastFailureAt);
  const lastCancelAt = useStore((s) => s.lastCancelAt);
  const [, tick] = useState(0);
  useEffect(() => {
    const at = Math.max(lastFailureAt, lastCancelAt);
    if (!at) return;
    const left = at + HOLD_MS - Date.now();
    if (left <= 0) return;
    const t = setTimeout(() => tick((n) => n + 1), left + 50);
    return () => clearTimeout(t);
  }, [lastFailureAt, lastCancelAt]);
  const active = tasks.find(isActive);
  const state = deriveAvatarState({
    backendReady: link === "live", voice, pendingApprovals: approvals,
    activeTask: active ? { state: active.status, toolCalls: toolCalls[active.id] ?? 0 } : null,
    recentFailure: !active && Date.now() - lastFailureAt < HOLD_MS,
    recentCancel: !active && Date.now() - lastCancelAt < HOLD_MS,
  });
  return { state, active };
}

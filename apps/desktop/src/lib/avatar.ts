import type { TaskState, VoiceState } from "./types";

export type AvatarState = "idle" | "listening" | "thinking" | "speaking" | "executing" | "approval" | "stopped" | "error" | "disconnected";

export interface AvatarInput {
  backendReady: boolean;
  voice: VoiceState;
  pendingApprovals: number;
  activeTask: { state: TaskState; toolCalls: number } | null;
  recentFailure: boolean;
  /** A task was cancelled by the user moments ago (real cancel event). */
  recentCancel?: boolean;
}

/** The avatar only ever reflects REAL state: backend health, voice session, task state, approvals. */
export function deriveAvatarState(i: AvatarInput): AvatarState {
  if (!i.backendReady) return "disconnected";
  if (i.pendingApprovals > 0) return "approval";
  if (i.voice === "error" || i.recentFailure) return "error";
  if (i.voice === "speaking") return "speaking";
  if (i.activeTask) {
    if (i.activeTask.state === "planning") return "thinking";
    if (i.activeTask.state === "running" || i.activeTask.state === "verifying") return i.activeTask.toolCalls > 0 ? "executing" : "thinking";
    if (i.activeTask.state === "waiting_for_approval") return "approval";
  }
  if (i.voice === "thinking") return "thinking";
  if (i.voice === "listening" || i.voice === "interrupted") return "listening";
  if (i.recentCancel) return "stopped";
  return "idle";
}

export interface Profile { label: string; color: string; spin: number; ring: number; pulse: number; pulseRate: number; audioGain: number; core: number; particles: number; dim: number }
const TEAL = "#258BFF", BRIGHT = "#49ADFF", TITANIUM = "#D6DDE6", AMBER = "#F2B84B", RED = "#FF6868", DIM = "#4A5566";
export const PROFILES: Record<AvatarState, Profile> = {
  idle:         { label: "Idle",                  color: TEAL,   spin: 0.10, ring: 0.18, pulse: 0.03, pulseRate: 1.1, audioGain: 0,   core: 0.45, particles: 0.05, dim: 1 },
  listening:    { label: "Listening",             color: BRIGHT, spin: 0.14, ring: 0.24, pulse: 0.05, pulseRate: 2.0, audioGain: 0.5, core: 0.60, particles: 0.08, dim: 1 },
  thinking:     { label: "Thinking",              color: TEAL,   spin: 0.34, ring: 0.62, pulse: 0.06, pulseRate: 2.6, audioGain: 0,   core: 0.70, particles: 0.16, dim: 1 },
  speaking:     { label: "Speaking",              color: TITANIUM, spin: 0.16, ring: 0.30, pulse: 0.06, pulseRate: 2.2, audioGain: 0.6, core: 0.75, particles: 0.10, dim: 1 },
  executing:    { label: "Executing",             color: TEAL,   spin: 0.22, ring: 0.80, pulse: 0.04, pulseRate: 3.2, audioGain: 0,   core: 0.72, particles: 0.20, dim: 1 },
  approval:     { label: "Waiting for approval",  color: AMBER,  spin: 0.05, ring: 0.10, pulse: 0.05, pulseRate: 1.6, audioGain: 0,   core: 0.55, particles: 0.04, dim: 1 },
  stopped:      { label: "Stopped",               color: TITANIUM, spin: 0.02, ring: 0.04, pulse: 0.01, pulseRate: 0.6, audioGain: 0,   core: 0.25, particles: 0.01, dim: 0.65 },
  error:        { label: "Error",                 color: RED,    spin: 0.03, ring: 0.06, pulse: 0.02, pulseRate: 0.8, audioGain: 0,   core: 0.30, particles: 0.02, dim: 0.7 },
  disconnected: { label: "Disconnected",          color: DIM,    spin: 0.00, ring: 0.00, pulse: 0.00, pulseRate: 0.0, audioGain: 0,   core: 0.18, particles: 0.00, dim: 0.5 },
};
export const STATE_GLYPH: Record<AvatarState, string> = { idle: "○", listening: "◉", thinking: "◐", speaking: "◍", executing: "▶", approval: "!", stopped: "■", error: "✕", disconnected: "–" };

export function webglAvailable(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch { return false; }
}

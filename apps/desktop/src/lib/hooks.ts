import { useEffect, useState } from "react";
import { useStore } from "./store";
import { VoiceClient } from "./voice";
import { TERMINAL, type Task } from "./types";

export function useReducedMotion(): boolean {
  const pref = useStore((s) => s.settings?.settings.interaction.reduced_motion ?? "system");
  const [sys, setSys] = useState(() => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false);
  useEffect(() => {
    const m = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!m) return;
    const f = () => setSys(m.matches);
    m.addEventListener("change", f);
    return () => m.removeEventListener("change", f);
  }, []);
  const reduced = pref === "on" || (pref === "system" && sys);
  useEffect(() => { document.documentElement.dataset.motion = pref; }, [pref]);
  return reduced;
}

export const isActive = (t: Task): boolean => !TERMINAL.includes(t.status);

let client: VoiceClient | null = null;
let clientKey = "";
const ACTIVE = ["connecting", "listening", "thinking", "speaking", "interrupted"];

export function useVoice() {
  const conn = useStore((s) => s.conn);
  const state = useStore((s) => s.voice.state);
  const configured = useStore((s) => s.status?.voice.state !== "not_configured");
  const devices = useStore((s) => s.settings?.settings.gemini);
  const active = ACTIVE.includes(state);

  async function start() {
    const st = useStore.getState();
    if (!conn) return;
    if (!configured) { st.toast("error", "Add your Gemini API key in Settings → Voice to use voice. Text chat works without it."); st.setView("settings"); return; }
    if (!client || clientKey !== conn.baseUrl) {
      client = new VoiceClient(conn, { onState: (s, d, c) => useStore.getState().setVoice(s, d, c), onTranscript: (r, t) => useStore.getState().addTranscript(r, t) });
      clientKey = conn.baseUrl;
    }
    await client.start({ inputId: devices?.input_device_id || undefined, outputId: devices?.output_device_id || undefined });
  }
  return { state, active, configured, start, stop: () => client?.stop(), interrupt: () => client?.interrupt() };
}

/** Reactive CSS media query (used to switch the side panels between columns and drawers). */
export function useMedia(query: string): boolean {
  const [m, setM] = useState(() => window.matchMedia?.(query).matches ?? false);
  useEffect(() => {
    const mq = window.matchMedia?.(query);
    if (!mq) return;
    const f = () => setM(mq.matches);
    f();
    mq.addEventListener("change", f);
    return () => mq.removeEventListener("change", f);
  }, [query]);
  return m;
}

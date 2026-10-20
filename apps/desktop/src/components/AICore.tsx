import { useEffect, useState } from "react";
import { getBridge } from "../lib/bridge";
import { PROFILES, type AvatarState } from "../lib/avatar";
import { useReducedMotion, useVoice } from "../lib/hooks";
import { useCoreState } from "../lib/useCoreState";
import { useStore } from "../lib/store";
import { TERMINAL } from "../lib/types";
import { Avatar } from "./Avatar";
import { IconMic, IconRefresh, IconSkip, IconStop } from "./icons";
import { Btn } from "./ui";

/** Technical-looking HUD around the 3D core. Purely presentational — what it LABELS is real state, what it ANIMATES is driven by data-state. */
function Hud({ state, link }: { state: AvatarState; link: string }) {
  const ticks = Array.from({ length: 72 }, (_, i) => i);
  return (
    <svg className="core-hud" viewBox="0 0 400 400" aria-hidden focusable="false">
      <defs>
        <linearGradient id="sweepG" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stopColor="var(--c)" stopOpacity="0" /><stop offset="1" stopColor="var(--c)" stopOpacity="0.9" /></linearGradient>
      </defs>
      <g className="ring-a">
        <circle cx="200" cy="200" r="186" fill="none" stroke="rgba(214,221,230,0.16)" strokeWidth="1" />
        {ticks.map((i) => { const a = (i / 72) * Math.PI * 2, l = i % 6 === 0 ? 9 : 4; return <line key={i} x1={200 + Math.cos(a) * 186} y1={200 + Math.sin(a) * 186} x2={200 + Math.cos(a) * (186 - l)} y2={200 + Math.sin(a) * (186 - l)} stroke={i % 6 === 0 ? "rgba(214,221,230,0.55)" : "rgba(214,221,230,0.2)"} strokeWidth="1" />; })}
      </g>
      <g className="ring-b">
        <circle cx="200" cy="200" r="160" fill="none" stroke="var(--c)" strokeOpacity="0.38" strokeWidth="1.2" strokeDasharray="2 7 46 7" />
        <circle cx="200" cy="200" r="148" fill="none" stroke="rgba(214,221,230,0.12)" strokeWidth="1" strokeDasharray="1 5" />
      </g>
      <g className="sweep"><path d="M200 200 L200 30 A170 170 0 0 1 335 98 Z" fill="url(#sweepG)" opacity="0.1" /><line x1="200" y1="200" x2="200" y2="30" stroke="var(--c)" strokeOpacity="0.55" strokeWidth="1" /></g>
      <circle cx="200" cy="200" r="118" fill="none" stroke="rgba(214,221,230,0.1)" strokeWidth="1" />
      {[[200, 8, 200, 22], [200, 378, 200, 392], [8, 200, 22, 200], [378, 200, 392, 200]].map((l, i) => <line key={i} x1={l[0]} y1={l[1]} x2={l[2]} y2={l[3]} stroke="var(--c)" strokeWidth="2" strokeOpacity="0.8" />)}
      <text x="24" y="380">CORE · {PROFILES[state].label.toUpperCase()}</text>
      <text x="376" y="380" textAnchor="end">LINK · {link === "live" ? "LIVE" : link === "connecting" ? "…" : "LOST"}</text>
    </svg>
  );
}

function useVisible() {
  const [v, setV] = useState(!document.hidden);
  useEffect(() => { const f = () => setV(!document.hidden); document.addEventListener("visibilitychange", f); return () => document.removeEventListener("visibilitychange", f); }, []);
  return v;
}

/** AICore: the signature hero. Start/stop controls call the real voice lifecycle and the real task-cancel API. */
export function AICore() {
  const { state, active } = useCoreState();
  const intensity = useStore((s) => s.settings?.settings.interaction.animation_intensity ?? 1);
  const link = useStore((s) => s.link);
  const status = useStore((s) => s.status);
  const voiceInfo = useStore((s) => s.voice);
  const tasks = useStore((s) => s.tasks);
  const approvals = useStore((s) => s.approvals.length);
  const cancel = useStore((s) => s.cancelTask);
  const setView = useStore((s) => s.setView);
  const refreshAll = useStore((s) => s.refreshAll);
  const reduced = useReducedMotion();
  const visible = useVisible();
  const voice = useVoice();
  const last = tasks.find((t) => TERMINAL.includes(t.status));
  const p = PROFILES[state];

  const sub = state === "disconnected" ? "Lost contact with the local backend. Reconnecting automatically…"
    : state === "approval" ? `${approvals || 1} action${approvals === 1 ? " is" : "s are"} waiting for your decision.`
    : active ? `Working on: ${active.goal}`
    : state === "error" ? (voiceInfo.state === "error" ? voiceInfo.detail ?? "Voice error." : last?.result.error ?? "The last task failed.")
    : state === "stopped" ? `Stopped: ${last?.goal ?? "the task was cancelled"}`
    : voice.active ? voiceInfo.detail ?? "Voice session active."
    : status?.limited_mode ? "Limited mode — no model is connected yet, so ZONIC can’t reason or act."
    : "Ready when you are.";

  const speaking = voiceInfo.state === "speaking" || voiceInfo.state === "thinking";
  const connecting = voiceInfo.state === "connecting";
  return (
    <section className="card core-card span-all" data-state={state} data-paused={String(!visible || reduced)} aria-label="AI Core" style={{ ["--c" as string]: p.color }}>
      <div className="core-stage">
        <Hud state={state} link={link} />
        <Avatar state={state} intensity={intensity} reduced={reduced} />
      </div>
      <div className="core-info">
        <div className="eyebrow">AI Core</div>
        <div className="core-state" aria-live="polite"><span className="gl" aria-hidden />{p.label}</div>
        <div className="core-sub" aria-live="polite" title={sub}>{sub}</div>
        <div className="core-actions">
          {link !== "live" ? (
            <Btn kind="primary" onClick={() => { void getBridge().retryBackend(); void refreshAll(); }}><IconRefresh size={15} />Reconnect now</Btn>
          ) : (
            <Btn kind={voice.active ? "danger" : "primary"} aria-pressed={voice.active} disabled={connecting} title={voice.configured ? "" : "Needs a Gemini API key — see Settings → Voice"}
              onClick={() => (voice.active ? voice.stop() : void voice.start())}>{voice.active ? <><IconStop size={15} />Stop voice</> : <><IconMic size={15} />{connecting ? "Connecting…" : "Start voice"}</>}</Btn>
          )}
          <Btn onClick={() => voice.interrupt()} disabled={!speaking} title={speaking ? "Stop ZONIC mid-sentence" : "Available while ZONIC is speaking"}><IconSkip size={15} />Interrupt</Btn>
          <Btn kind="danger" disabled={!active || active.cancel_requested} onClick={() => active && void cancel(active.id)} title={active ? "Cancel the running task" : "No task is running"}><IconStop size={15} />{active?.cancel_requested ? "Stopping…" : "Stop task"}</Btn>
        </div>
        <div className="core-meta">
          <span className="pill"><span className={`dot ${link === "live" ? "live" : "bad"}`} aria-hidden />Backend {link === "live" ? `v${status?.backend.version ?? ""}` : link === "connecting" ? "connecting" : "unreachable"}</span>
          {status && <span className="pill"><span className={`dot ${status.model.state === "ready" ? "live" : "wait"}`} aria-hidden />{status.model.state === "ready" ? status.model.model : `Model: ${status.model.state.replace("_", " ")}`}</span>}
          {status && voice.configured && <span className="pill"><span className={`dot ${voiceInfo.state === "error" ? "bad" : voice.active ? "live" : ""}`} aria-hidden />Voice {voice.active ? voiceInfo.state : "off"}</span>}
          {state === "approval" && <button type="button" className="pill warn" style={{ cursor: "pointer" }} onClick={() => setView("tasks")}>Review in Tasks →</button>}
        </div>
      </div>
    </section>
  );
}

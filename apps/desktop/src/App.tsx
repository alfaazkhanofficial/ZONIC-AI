import { useEffect, useState } from "react";
import { ApprovalDialog } from "./components/ApprovalDialog";
import { AppShell } from "./components/Shell";
import { Btn, Loading } from "./components/ui";
import { getBridge, type BackendStatusUi } from "./lib/bridge";
import { useStore } from "./lib/store";
import { Onboarding } from "./views/Onboarding";
import { useReducedMotion } from "./lib/hooks";

export default function App() {
  const [phase, setPhase] = useState<"boot" | "ready" | "failed">("boot");
  const [fail, setFail] = useState<BackendStatusUi | null>(null);
  useEffect(() => {
    const bridge = getBridge();
    let close: (() => void) | undefined;
    let started = false;
    const boot = async () => {
      const conn = await bridge.getConnection();
      if (conn && !started) { started = true; close = useStore.getState().connect(conn); setPhase("ready"); }
      else if (!conn) { setFail(await bridge.getBackendState()); setPhase("failed"); }
    };
    void boot();
    const off = bridge.onBackendState((st) => { if (st.state === "ready" && !started) void boot(); else if (!started) setFail(st); });
    return () => { off(); close?.(); };
  }, []);
  if (phase === "boot") return <div style={{ padding: 40 }}><Loading rows={3} /></div>;
  if (phase === "failed") {
    return (
      <div style={{ height: "100%", display: "grid", placeItems: "center" }}><div className="card" style={{ maxWidth: 560 }} role="alert">
        <div className="row" style={{ marginBottom: 10 }}><img src="./zonic-mark.png" alt="" width={34} height={34} /><h2>ZONIC’s backend isn’t running</h2></div><p className="muted">{fail?.detail ?? "No connection information is available."}</p>
        {fail?.tail?.length ? <pre className="code">{fail.tail.join("\n")}</pre> : null}
        <div className="row"><Btn kind="primary" onClick={() => { void getBridge().retryBackend().then(() => location.reload()); }}>Retry</Btn><Btn onClick={() => void getBridge().openLogs()}>Open logs folder</Btn></div></div></div>
    );
  }
  return <Gate />;
}

function Gate() {
  const status = useStore((s) => s.status);
  const settings = useStore((s) => s.settings);
  const link = useStore((s) => s.link);
  useReducedMotion();
  if (!status || !settings) return <div style={{ padding: 40 }}><Loading rows={4} />{link === "reconnecting" && <p className="muted">Waiting for the backend…</p>}</div>;
  return <>{settings.settings.onboarding.completed ? <AppShell /> : <Onboarding />}<ApprovalDialog /><Toasts /></>;
}

function Toasts() {
  const toasts = useStore((s) => s.toasts), dismiss = useStore((s) => s.dismissToast);
  return <div className="toasts" aria-live="polite">{toasts.map((t) => <div key={t.id} className={`toast ${t.kind}`} role="status" onClick={() => dismiss(t.id)}>{t.text}</div>)}</div>;
}

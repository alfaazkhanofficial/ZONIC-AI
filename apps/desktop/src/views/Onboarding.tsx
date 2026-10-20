import { useEffect, useState, type ReactNode } from "react";
import { Avatar } from "../components/Avatar";
import { AllowlistPanel, InteractionPanel, MemoryPanel, ModelPanel, PermissionsPanel, PersonalizationPanel, VoicePanel, WorkspacesPanel } from "../components/forms";
import { Btn, Card, Chip, ErrorNote, Loading, Note, Spinner, Toggle } from "../components/ui";
import { ApiError } from "../lib/api";
import { PROFILES, type AvatarState } from "../lib/avatar";
import { useReducedMotion } from "../lib/hooks";
import { useStore } from "../lib/store";
import { useSettings } from "../lib/useSettings";
import type { ReadinessItem } from "../lib/types";

const TITLES = ["Welcome", "How you’ll interact", "Main brain", "Voice", "Avatar", "Memory", "Computer permissions", "System discovery", "Personalization", "Readiness"];
const PREVIEW: AvatarState[] = ["idle", "listening", "thinking", "speaking", "executing", "approval", "error"];

export function Onboarding() {
  const { s, api, refresh, refreshStatus, toast } = useSettings();
  const ob = s?.onboarding;
  const [step, setStep] = useState(() => Math.min(10, Math.max(1, ob?.step ?? 1)));
  if (!s || !ob) return <div className="ob"><Loading /></div>;
  const go = (n: number) => { const c = Math.min(10, Math.max(1, n)); setStep(c); void api.patchOnboarding({ step: c }).catch(() => undefined); };
  const skip = (key: string) => { void api.patchOnboarding({ skipped: [...new Set([...ob.skipped, key])] }).then(refresh).catch(() => undefined); go(step + 1); };
  const enter = async () => {
    try { await api.completeOnboarding(); await Promise.all([refresh(), refreshStatus()]); } catch (e) { toast("error", e instanceof ApiError ? e.message : "Could not finish setup."); }
  };
  return (
    <div className="ob" data-step={step}>
      <header className="ob-head"><span className="wordmark">ZONIC M4</span>
        <div className="steps" role="progressbar" aria-valuemin={1} aria-valuemax={10} aria-valuenow={step} aria-label={`Step ${step} of 10: ${TITLES[step - 1]}`}>{TITLES.map((_, i) => <i key={i} className={i + 1 < step ? "done" : i + 1 === step ? "cur" : ""} />)}</div>
        <span className="muted small">Step {step} of 10</span></header>
      <main className="ob-body"><div className="ob-card">
        <Step n={step} go={go} skippedVoice={ob.skipped.includes("voice")} onEnter={enter} />
      </div></main>
      <footer className="ob-foot">
        <Btn onClick={() => go(step - 1)} disabled={step === 1}>Back</Btn>
        <div className="row">
          {[3, 4, 8].includes(step) && <Btn kind="ghost" onClick={() => skip(step === 3 ? "model" : step === 4 ? "voice" : "discovery")} title="You can set this up later in Settings">{step === 3 ? "Skip — limited mode" : step === 4 ? "Skip — text only" : "Skip"}</Btn>}
          {step < 10 && step !== 1 && <Btn kind="primary" onClick={() => go(step + 1)}>Continue</Btn>}
        </div>
      </footer>
    </div>
  );
}

const H = ({ children, sub }: { children: ReactNode; sub?: ReactNode }) => <><h1>{children}</h1>{sub && <p className="muted" style={{ fontSize: 15 }}>{sub}</p>}</>;

function Step({ n, go, skippedVoice, onEnter }: { n: number; go: (n: number) => void; skippedVoice: boolean; onEnter: () => void }) {
  const reduced = useReducedMotion();
  const intensity = useStore((s) => s.settings?.settings.interaction.animation_intensity ?? 1);
  const [learn, setLearn] = useState(false);
  const [pv, setPv] = useState<AvatarState>("idle");
  switch (n) {
    case 1: return (<>
      <div className="hero"><Avatar state="idle" intensity={intensity} reduced={reduced} /></div>
      <H sub="A personal AI agent for your Windows PC. It talks with you, remembers what you approve, and uses a fixed set of tools — always inside the permissions you set.">Welcome to ZONIC M4</H>
      <div className="row"><Btn kind="primary" onClick={() => go(2)}>Initialize ZONIC</Btn><Btn onClick={() => setLearn(!learn)} aria-expanded={learn}>Learn what it can do</Btn></div>
      {learn && <Card raised><ul style={{ margin: 0, paddingLeft: 18, lineHeight: 1.7 }}>
        <li>Converse by text or voice and answer questions.</li><li>Remember facts and preferences — only ones you approve, all viewable and deletable.</li>
        <li>Use registered tools: read and write files in folders you approve, launch apps you allow, open links, take screenshots, and (if you enable it) click and type.</li>
        <li>Check its own work: file writes are read back and compared; things it can’t confirm are labelled “not verified”.</li></ul>
        <p className="muted small" style={{ marginTop: 10 }}>It is not magic or fully autonomous: it only does what its tools allow, asks before anything risky, and tells you plainly when it can’t do something.</p></Card>}
    </>);
    case 2: return (<><H sub="Pick how you’d like to work. Everything is saved immediately and can be changed in Settings.">How you’ll interact</H><Card><InteractionPanel /></Card></>);
    case 3: return (<><H sub="ZONIC reasons with NVIDIA’s Nemotron 3 Super. Add your key to unlock it — or skip and explore in limited mode.">Connect the main brain</H><Card><ModelPanel /></Card></>);
    case 4: return (<><H sub="Voice uses Google’s Gemini Live. We only ask Windows for the microphone when you press a test button, and only to hear you.">Voice setup</H>{skippedVoice && <Note>You skipped voice earlier. Text chat works fine; you can add voice any time.</Note>}<Card><VoicePanel /></Card></>);
    case 5: return (<><H sub="Try the avatar’s states and set how lively it is.">Meet the avatar</H>
      <div className="hero" style={{ height: 340 }}><Avatar state={pv} intensity={intensity} reduced={reduced} /></div>
      <Note warn>Preview only — these states are simulated here. In the app the avatar only ever shows real status.</Note>
      <div className="row wrap">{PREVIEW.map((p) => <Btn key={p} small kind={p === pv ? "primary" : undefined} onClick={() => setPv(p)} aria-pressed={p === pv}>{PROFILES[p].label}</Btn>)}</div>
      <Card><InteractionPanel /></Card></>);
    case 6: return (<><H sub="Memory is optional and local. Choose what ZONIC may keep — the default is as little as possible.">What ZONIC may remember</H><Card><MemoryPanel /></Card></>);
    case 7: return (<><H sub="Everything starts OFF. Turn on only what you want; the backend enforces it.">Computer permissions</H><Card title="Permission groups"><PermissionsPanel /></Card>
      <Card title="Workspace folders"><WorkspacesPanel compact /></Card><Card title="Allowed applications"><AllowlistPanel /></Card></>);
    case 8: return <Discovery />;
    case 9: return (<><H sub="All optional — no personal details required. Edit or clear these any time.">Make it yours</H><Card><PersonalizationPanel /></Card></>);
    default: return <Readiness go={go} onEnter={onEnter} />;
  }
}

function Discovery() {
  const { api, s, refresh, toast } = useSettings();
  const [ok, setOk] = useState(false);
  const [busy, setBusy] = useState(false);
  const res = s?.discovery.result as Record<string, unknown> | null | undefined;
  const run = async () => {
    setBusy(true);
    try {
      let devs: { id: string; label: string }[] = [];
      try { devs = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind.startsWith("audio")).map((d) => ({ id: d.deviceId, label: d.label || `(${d.kind} — name hidden until mic permission)` })); } catch { /* none */ }
      await api.discovery(devs); await refresh();
    } catch (e) { toast("error", e instanceof ApiError ? e.message : "Discovery failed."); } finally { setBusy(false); }
  };
  const tools = res?.tools_found as Record<string, boolean> | undefined;
  return (<>
    <H sub="Optional. ZONIC can look at a few basics to suggest sensible defaults. Nothing leaves your PC.">System discovery</H>
    <Card title="What would be inspected">
      <ul style={{ margin: 0, paddingLeft: 18, lineHeight: 1.7 }}><li>Windows version and basic hardware size</li><li>Whether common developer tools are installed (checked by name only)</li><li>The workspace folders you approved</li><li>Names of your audio devices</li></ul>
      <p className="muted small" style={{ marginTop: 8 }}>Not inspected: your personal files, browser data, installed-program lists, or network. No recursive scanning.</p>
      <div style={{ marginTop: 10 }}><Toggle checked={ok} onChange={setOk} label="I consent to this check" /></div>
      <div style={{ marginTop: 10 }}><Btn kind="primary" disabled={!ok || busy} onClick={run}>{busy ? <><Spinner /> Checking…</> : res ? "Run again" : "Run discovery"}</Btn></div>
    </Card>
    {res && <Card title="Result" raised>
      <div className="small">OS: {String(res.os)} · {String(res.cpu_threads)} threads · {String(res.ram_gb)} GB RAM</div>
      {tools && <div className="row wrap" style={{ marginTop: 6 }}>{Object.entries(tools).map(([k, v]) => <Chip key={k} state={v ? "ready" : "unavailable"} label={`${k}: ${v ? "found" : "not found"}`} />)}</div>}
      <div className="small" style={{ marginTop: 6 }}>Workspaces: {(res.approved_workspaces as unknown[]).length || "none yet"} · Audio devices seen: {(res.audio_devices as unknown[]).length}{(res.audio_devices as { label: string }[]).some((d) => d.label.startsWith("(")) ? " (names appear after you grant microphone access — partial result)" : ""}</div>
    </Card>}
  </>);
}

function Readiness({ go, onEnter }: { go: (n: number) => void; onEnter: () => void }) {
  const api = useStore((s) => s.api)!;
  const [items, setItems] = useState<ReadinessItem[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [entering, setEntering] = useState(false);
  const run = async (live: boolean) => { setBusy(true); setErr(null); try { setItems((await api.readiness(live)).items); } catch (e) { setErr(e instanceof ApiError ? e.message : "Health checks failed."); } finally { setBusy(false); } };
  useEffect(() => { void run(false); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return (<>
    <H sub="Real checks, run just now. Anything that isn’t ready can be fixed later — you can still enter.">Readiness report</H>
    {err && <ErrorNote>{err}</ErrorNote>}
    {items === null ? <Loading rows={5} /> : <Card>{items.map((i) => (
      <div className="status-row" key={i.key}><strong style={{ fontWeight: 500 }}>{i.label}</strong><Chip state={i.state} />
        <span className="detail">{i.detail}{i.action && i.step && <> · <a href="#" style={{ color: "var(--teal-bright)" }} onClick={(e) => { e.preventDefault(); go(i.step!); }}>{i.action}</a></>}</span></div>))}</Card>}
    <div className="row wrap"><Btn onClick={() => void run(true)} disabled={busy}>{busy ? <><Spinner /> Checking…</> : "Run live checks (tests your keys)"}</Btn>
      <label className="row small muted">Review setup: <select aria-label="Jump to a step" defaultValue="" onChange={(e) => { if (e.target.value) go(Number(e.target.value)); }}><option value="" disabled>choose a step…</option>{TITLES.slice(0, 9).map((t, i) => <option key={t} value={i + 1}>{i + 1}. {t}</option>)}</select></label></div>
    <div><Btn kind="primary" disabled={entering} onClick={() => { setEntering(true); onEnter(); }}>{entering ? <Spinner /> : "Enter ZONIC M4"}</Btn></div>
  </>);
}

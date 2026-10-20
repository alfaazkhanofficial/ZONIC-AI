import { useEffect, useRef, useState } from "react";
import { ApiError } from "../lib/api";
import { getBridge } from "../lib/bridge";
import { useSettings } from "../lib/useSettings";
import { useStore } from "../lib/store";
import type { PermissionKey, TestResult, ToolInfo } from "../lib/types";
import { Btn, Card, Chip, Confirm, ErrorNote, Field, Modal, Note, Spinner, Toggle } from "./ui";

const errMsg = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong.");

function TestResultView({ r }: { r: TestResult | null | undefined }) {
  if (!r) return null;
  return (
    <div className={r.ok ? "note" : "errnote"} role="status" style={{ marginTop: 8 }}>
      <div className="row"><Chip state={r.ok ? "ready" : "error"} label={r.ok ? "Connected" : "Failed"} /><span className="muted small">{new Date(r.at).toLocaleTimeString()}</span></div>
      <div style={{ marginTop: 4 }}>{r.message}</div>{r.hint && !r.ok && <div className="small" style={{ marginTop: 4 }}>→ {r.hint}</div>}
    </div>
  );
}

function SecretField({ name, label, placeholder, onSaved }: { name: "nvidia_api_key" | "gemini_api_key"; label: string; placeholder: string; onSaved?: () => void }) {
  const { api, secrets, backend, toast, refresh, refreshStatus } = useSettings();
  const [val, setVal] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmDel, setConfirmDel] = useState(false);
  const st = secrets?.[name];
  const save = async () => {
    setBusy(true);
    try { await api.putSecret(name, val.trim()); setVal(""); await Promise.all([refresh(), refreshStatus()]); toast("success", "Key saved securely. It will not be shown again."); onSaved?.(); }
    catch (e) { toast("error", errMsg(e)); } finally { setBusy(false); }
  };
  return (
    <div className="col">
      <Field label={label} hint={st?.configured ? `A key is saved (${st.source === "environment" ? "from an environment variable" : backend === "os-keyring" ? "in Windows Credential Manager" : "in the app's restricted secrets file"}). Enter a new one to replace it.` : "Not saved yet. Keys are stored in the OS credential vault, never in settings, logs or this window."}>
        <input type="password" autoComplete="off" spellCheck={false} placeholder={st?.configured ? "••••••••••••••••" : placeholder} value={val} onChange={(e) => setVal(e.target.value)} />
      </Field>
      <div className="row"><Btn kind="primary" disabled={val.trim().length < 8 || busy} onClick={save}>{busy ? <Spinner /> : "Save key"}</Btn>
        {st?.configured && st.source !== "environment" && <Btn kind="danger" onClick={() => setConfirmDel(true)}>Remove key</Btn>}</div>
      {confirmDel && <Confirm title="Remove this key?" danger confirmLabel="Remove key" body={<p>ZONIC will stop working with this provider until you add a key again.</p>} onCancel={() => setConfirmDel(false)}
        onConfirm={async () => { setConfirmDel(false); try { await api.deleteSecret(name); await Promise.all([refresh(), refreshStatus()]); } catch (e) { toast("error", errMsg(e)); } }} />}
    </div>
  );
}

export function ModelPanel() {
  const { s, patch, api, refreshStatus } = useSettings();
  const last = useStore((x) => x.status?.model.last_test);
  const [form, setForm] = useState(s?.nemotron);
  const [res, setRes] = useState<TestResult | null>(null);
  const [testing, setTesting] = useState(false);
  useEffect(() => setForm(s?.nemotron), [s?.nemotron]);
  if (!s || !form) return null;
  const test = async () => {
    setTesting(true); setRes(null);
    try { setRes(await api.testNemotron()); await refreshStatus(); } catch (e) { setRes({ ok: false, code: "client", message: errMsg(e), latency_ms: null, model: null, hint: null, at: new Date().toISOString() }); } finally { setTesting(false); }
  };
  return (
    <div className="col gap-lg">
      <SecretField name="nvidia_api_key" label="NVIDIA API key" placeholder="nvapi-…" onSaved={() => setRes(null)} />
      <div className="grid2">
        <Field label="Endpoint (OpenAI-compatible)"><input value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} /></Field>
        <Field label="Model identifier"><input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} /></Field>
        <Field label="Request timeout (seconds)"><input type="number" min={5} max={300} value={form.timeout_s} onChange={(e) => setForm({ ...form, timeout_s: Number(e.target.value) })} /></Field>
        <Toggle checked={form.streaming} onChange={(v) => setForm({ ...form, streaming: v })} label="Stream replies" hint="Show text as it is generated." />
      </div>
      <div className="row"><Btn onClick={() => void patch("nemotron", { base_url: form.base_url, model: form.model, timeout_s: form.timeout_s, streaming: form.streaming })}>Save endpoint settings</Btn>
        <Btn kind="primary" onClick={test} disabled={testing}>{testing ? <><Spinner /> Testing…</> : "Test connection"}</Btn></div>
      <TestResultView r={testing ? null : (res ?? last)} />
      <Note>The test makes one tiny real request to the provider. Typical failures — missing or invalid key, network problems, rate limits, an unknown model ID, provider outages — are reported specifically. You can skip this and use ZONIC in limited mode.</Note>
    </div>
  );
}

function useDevices() {
  const [inputs, setIn] = useState<MediaDeviceInfo[]>([]);
  const [outputs, setOut] = useState<MediaDeviceInfo[]>([]);
  const refresh = async () => {
    try { const l = await navigator.mediaDevices.enumerateDevices(); setIn(l.filter((d) => d.kind === "audioinput")); setOut(l.filter((d) => d.kind === "audiooutput")); } catch { /* unsupported */ }
  };
  useEffect(() => { void refresh(); navigator.mediaDevices?.addEventListener?.("devicechange", refresh); return () => navigator.mediaDevices?.removeEventListener?.("devicechange", refresh); }, []);
  return { inputs, outputs, refresh };
}
export const useDeviceList = useDevices;

export function VoicePanel() {
  const { s, patch, api, refreshStatus } = useSettings();
  const last = useStore((x) => x.status?.voice.last_test);
  const { inputs, outputs, refresh } = useDevices();
  const [form, setForm] = useState(s?.gemini);
  const [res, setRes] = useState<TestResult | null>(null);
  const [testing, setTesting] = useState(false);
  const [mic, setMic] = useState<{ running: boolean; level: number; peak: number; error?: string; done?: boolean }>({ running: false, level: 0, peak: 0 });
  const stopMic = useRef<(() => void) | null>(null);
  useEffect(() => setForm(s?.gemini), [s?.gemini]);
  useEffect(() => () => stopMic.current?.(), []);
  if (!s || !form) return null;

  const testMic = async () => {
    stopMic.current?.();
    setMic({ running: true, level: 0, peak: 0 });
    let stream: MediaStream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: { deviceId: form.input_device_id ? { exact: form.input_device_id } : undefined } }); }
    catch (e) { const n = (e as DOMException).name; setMic({ running: false, level: 0, peak: 0, error: n === "NotAllowedError" ? "Microphone permission denied. Allow it in Windows Settings → Privacy → Microphone." : n === "NotFoundError" ? "No microphone found." : `Could not open the microphone (${n}).` }); return; }
    await refresh();
    const ctx = new AudioContext(), an = ctx.createAnalyser();
    an.fftSize = 1024; ctx.createMediaStreamSource(stream).connect(an);
    const buf = new Float32Array(an.fftSize);
    let peak = 0, raf = 0;
    const end = performance.now() + 5000;
    const loop = () => {
      an.getFloatTimeDomainData(buf);
      let sum = 0; for (const v of buf) sum += v * v;
      const lvl = Math.min(1, Math.sqrt(Math.sqrt(sum / buf.length)) * 1.8);
      peak = Math.max(peak, lvl);
      setMic({ running: true, level: lvl, peak });
      if (performance.now() < end) raf = requestAnimationFrame(loop); else stop();
    };
    const stop = () => { cancelAnimationFrame(raf); stream.getTracks().forEach((t) => t.stop()); void ctx.close(); setMic((m) => ({ ...m, running: false, level: 0, done: true })); stopMic.current = null; };
    stopMic.current = stop;
    loop();
  };
  const testSpeaker = async () => {
    const ctx = new AudioContext();
    try { if (form.output_device_id && "setSinkId" in ctx) await (ctx as AudioContext & { setSinkId(i: string): Promise<void> }).setSinkId(form.output_device_id); } catch { /* default output */ }
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.frequency.value = 523; g.gain.setValueAtTime(0.0001, ctx.currentTime); g.gain.exponentialRampToValueAtTime(0.15, ctx.currentTime + 0.05); g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.7);
    o.connect(g).connect(ctx.destination); o.start(); o.stop(ctx.currentTime + 0.75); setTimeout(() => void ctx.close(), 900);
  };
  const test = async () => { setTesting(true); setRes(null); try { setRes(await api.testGemini()); await refreshStatus(); } catch (e) { setRes({ ok: false, code: "client", message: errMsg(e), latency_ms: null, model: null, hint: null, at: new Date().toISOString() }); } finally { setTesting(false); } };
  const save = (p: Partial<typeof form>) => { setForm({ ...form, ...p }); void patch("gemini", p); };
  return (
    <div className="col gap-lg">
      <SecretField name="gemini_api_key" label="Gemini API key" placeholder="AIza…" onSaved={() => setRes(null)} />
      <div className="grid2">
        <Field label="Live model" hint="Preview model names change; update here if Google renames it."><input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} onBlur={() => void patch("gemini", { model: form.model })} /></Field>
        <Field label="Voice name (optional)" hint="A Gemini prebuilt voice, e.g. Puck or Kore."><input value={form.voice_name} onChange={(e) => setForm({ ...form, voice_name: e.target.value })} onBlur={() => void patch("gemini", { voice_name: form.voice_name })} /></Field>
        <Field label="Microphone"><select value={form.input_device_id} onChange={(e) => save({ input_device_id: e.target.value })}><option value="">System default</option>{inputs.filter((d) => d.deviceId && d.deviceId !== "default" && d.deviceId !== "communications").map((d) => <option key={d.deviceId} value={d.deviceId}>{d.label || "Microphone (name shown after permission)"}</option>)}</select></Field>
        <Field label="Speaker / output"><select value={form.output_device_id} onChange={(e) => save({ output_device_id: e.target.value })}><option value="">System default</option>{outputs.filter((d) => d.deviceId && d.deviceId !== "default" && d.deviceId !== "communications").map((d) => <option key={d.deviceId} value={d.deviceId}>{d.label || "Output device"}</option>)}</select></Field>
      </div>
      <Card title="Audio tests" raised>
        <p className="muted small">Why microphone access? So you can talk to ZONIC. The level test below analyses your mic on this PC only (nothing is sent anywhere) and asks Windows for permission the first time you press it.</p>
        <div className="row wrap"><Btn onClick={testMic} disabled={mic.running}>{mic.running ? "Listening… speak now" : "Test microphone level"}</Btn><span className="meter" aria-hidden><i style={{ width: `${Math.round(mic.level * 100)}%` }} /></span>
          <Btn onClick={testSpeaker}>Play test tone</Btn></div>
        {mic.error && <div style={{ marginTop: 8 }}><ErrorNote>{mic.error}</ErrorNote></div>}
        {mic.done && !mic.error && <p className="small" style={{ marginTop: 8 }} role="status">{mic.peak > 0.08 ? <Chip state="ready" label={`Heard sound (peak ${Math.round(mic.peak * 100)}%)`} /> : <Chip state="limited" label="No sound detected — check mute, device choice and Windows input volume" />}</p>}
      </Card>
      <div className="row"><Btn kind="primary" onClick={test} disabled={testing}>{testing ? <><Spinner /> Testing…</> : "Test Gemini Live connection"}</Btn></div>
      <TestResultView r={testing ? null : (res ?? last)} />
      <Note>The connection test opens and closes a real Live session. Whether audio flows end-to-end is only confirmed when you actually talk to ZONIC. Voice audio is processed by Google; skip voice to keep everything text-only.</Note>
    </div>
  );
}

export function InteractionPanel() {
  const { s, patch } = useSettings();
  const [launch, setLaunch] = useState<boolean | null>(null);
  useEffect(() => { void getBridge().getStartupLaunch().then(setLaunch); }, []);
  if (!s) return null;
  const i = s.interaction;
  return (
    <div className="col gap-lg">
      <Field label="How do you mostly want to talk to ZONIC?">
        <select value={i.mode} onChange={(e) => void patch("interaction", { mode: e.target.value })}>
          <option value="voice_and_text">Voice and text</option><option value="text_first">Text first</option><option value="voice_first">Voice first</option>
        </select>
      </Field>
      <Field label="Reduce motion"><select value={i.reduced_motion} onChange={(e) => void patch("interaction", { reduced_motion: e.target.value })}>
        <option value="system">Follow Windows setting</option><option value="on">Always reduce</option><option value="off">Never reduce</option></select></Field>
      <Field label={`Avatar animation intensity: ${Math.round(i.animation_intensity * 100)}%`}><input type="range" min={0} max={1} step={0.05} value={i.animation_intensity} onChange={(e) => void patch("interaction", { animation_intensity: Number(e.target.value) })} /></Field>
      <Toggle checked={launch ?? false} disabled={launch === null} onChange={async (v) => { const r = await getBridge().setStartupLaunch(v); setLaunch(r); void patch("interaction", { startup_launch: r }); }}
        label="Start ZONIC when I sign in to Windows" hint="Optional. You can turn this off at any time." />
    </div>
  );
}

export function MemoryPanel() {
  const { s, patch } = useSettings();
  if (!s) return null;
  const m = s.memory;
  const t = (k: keyof typeof m, label: string, hint: string) => <Toggle checked={m[k]} onChange={(v) => void patch("memory", { [k]: v })} label={label} hint={hint} disabled={k !== "enabled" && !m.enabled} />;
  return (
    <div className="col">
      {t("enabled", "Remember things between sessions", "Stored in a local SQLite database on this PC. Everything saved can be viewed, edited and deleted in the Memory center.")}
      {t("preferences", "Preferences", "How you like things done.")}
      {t("projects", "Projects", "Facts about your projects and folders.")}
      {t("workflows", "Workflow memories", "Routines and procedures you teach ZONIC.")}
      {t("conversation_history", "Conversation history", "Keep chat transcripts. Off = chats exist only until you close the app.")}
      {t("semantic_index", "Local similarity index", "Improves recall using a built-in local index (approximate, lexical).")}
      <Note>Secrets (API keys, passwords, card numbers) are never saved to memory. ZONIC proposes memories as candidates and only uses ones you approve. Default is data minimisation: nothing is saved unless you allow it.</Note>
    </div>
  );
}

export function PersonalizationPanel() {
  const { s, patch } = useSettings();
  const [f, setF] = useState(s?.personalization);
  useEffect(() => setF(s?.personalization), [s?.personalization]);
  if (!s || !f) return null;
  const blur = () => void patch("personalization", { address_as: f.address_as, language: f.language, voice_behavior: f.voice_behavior });
  return (
    <div className="grid2">
      <Field label="How should ZONIC address you? (optional)"><input value={f.address_as} onChange={(e) => setF({ ...f, address_as: e.target.value })} onBlur={blur} placeholder="A name or nickname — or leave blank" /></Field>
      <Field label="Response style"><select value={f.response_style} onChange={(e) => void patch("personalization", { response_style: e.target.value })}><option value="concise">Concise</option><option value="balanced">Balanced</option><option value="detailed">Detailed</option></select></Field>
      <Field label="Language"><input value={f.language} onChange={(e) => setF({ ...f, language: e.target.value })} onBlur={blur} placeholder="en" /></Field>
      <Field label="Default workspace"><select value={f.default_workspace_id} onChange={(e) => void patch("personalization", { default_workspace_id: e.target.value })}><option value="">First approved workspace</option>{s.workspaces.items.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</select></Field>
      <div style={{ gridColumn: "1 / -1" }}><Field label="Voice behaviour notes (optional)" hint="e.g. “keep spoken answers under two sentences”"><input value={f.voice_behavior} onChange={(e) => setF({ ...f, voice_behavior: e.target.value })} onBlur={blur} /></Field></div>
    </div>
  );
}

const PERMS: { key: PermissionKey; title: string; body: string; tools?: string }[] = [
  { key: "read_workspace", title: "Read files in approved workspaces", body: "ZONIC can list and read text files inside the folders you approve below — nothing else on the PC." },
  { key: "write_workspace", title: "Create and edit files in approved workspaces", body: "ZONIC can create folders and new files there. Replacing an existing file always asks you first, and every write is verified by reading it back." },
  { key: "launch_apps", title: "Launch allowlisted apps", body: "Only apps on your allowlist, started with no extra arguments." },
  { key: "browser", title: "Open links in your default browser", body: "Every link asks for your approval first. ZONIC cannot read or drive the page.", tools: "open_url" },
  { key: "screenshot", title: "Observe the screen", body: "Take screenshots (saved on this PC only, auto-deleted) and read the active window title.", tools: "capture_screenshot" },
  { key: "input_control", title: "Control mouse and keyboard", body: "One action at a time, each needing your approval. System shortcuts (Win key, Alt+F4, Ctrl+Alt+Del) are blocked. Move the mouse to a screen corner to abort.", tools: "mouse_action" },
  { key: "elevated", title: "Elevated and destructive actions", body: "Not available in this release. If added later it will always require approval." },
];

export function PermissionsPanel() {
  const { s, patch, api } = useSettings();
  const [ask, setAsk] = useState<(typeof PERMS)[number] | null>(null);
  const [tools, setTools] = useState<ToolInfo[]>([]);
  useEffect(() => { void api.tools().then((r) => setTools(r.items)).catch(() => undefined); }, [api, s?.permissions]);
  if (!s) return null;
  return (
    <div className="col">
      {PERMS.map((p) => {
        const on = s.permissions[p.key];
        const unavailable = p.tools ? tools.find((t) => t.name === p.tools && t.status === "unavailable") : undefined;
        return (
          <div className="row" key={p.key} style={{ alignItems: "flex-start", padding: "8px 0", borderBottom: "1px solid #1a3335" }}>
            <div className="grow"><Toggle checked={on} disabled={p.key === "elevated"} label={<strong style={{ fontWeight: 500 }}>{p.title}</strong>} hint={p.body}
              onChange={(v) => (v ? setAsk(p) : void patch("permissions", { [p.key]: false }))} />
              {unavailable && <div className="small" style={{ color: "var(--warning)", marginTop: 4, marginLeft: 50 }}>Granting this will not work yet: {unavailable.reason}</div>}</div>
            <Chip state={on ? "ready" : "disabled"} label={on ? "Allowed" : "Off"} />
          </div>
        );
      })}
      <Note>The backend enforces these. Even when a group is on, high-impact actions (overwriting files, opening links, mouse/keyboard) still ask first. Turning anything off takes effect immediately.</Note>
      {ask && <Confirm title="Allow this?" confirmLabel="Allow" body={<><p><strong>{ask.title}</strong></p><p className="muted">{ask.body}</p><p className="muted small">You can turn it off again at any time.</p></>} onCancel={() => setAsk(null)}
        onConfirm={async () => { const k = ask.key; setAsk(null); await patch("permissions", { [k]: true }, true); }} />}
    </div>
  );
}

const baseName = (p: string) => p.split(/[\\/]/).filter(Boolean).pop() ?? p;

export function WorkspacesPanel({ compact }: { compact?: boolean }) {
  const { s, patch, toast } = useSettings();
  const [pending, setPending] = useState<string | null>(null);
  const [gone, setGone] = useState<string | null>(null);
  if (!s) return null;
  const items = s.workspaces.items;
  const add = async () => { const p = await getBridge().pickFolder(); if (p) setPending(p); };
  return (
    <div className="col">
      {items.length === 0 && <Note>No workspace yet. ZONIC can only touch folders you add here.</Note>}
      {items.map((w) => (
        <div key={w.id} className="row spread" style={{ padding: "6px 0", borderBottom: "1px solid #1a3335" }}>
          <div className="grow"><strong style={{ fontWeight: 500 }}>{w.name}</strong>{s.personalization.default_workspace_id === w.id && <> <Chip state="active" label="Default" /></>}<div className="mono muted" style={{ overflowWrap: "anywhere" }}>{w.path}</div></div>
          {!compact && <Btn small onClick={() => void patch("personalization", { default_workspace_id: w.id })} disabled={s.personalization.default_workspace_id === w.id}>Make default</Btn>}
          <Btn small kind="danger" onClick={() => setGone(w.id)}>Remove</Btn>
        </div>
      ))}
      <div><Btn onClick={add}>Add a workspace folder…</Btn></div>
      {pending && <Confirm title="Give ZONIC access to this folder?" confirmLabel="Grant access" body={<><p className="mono" style={{ overflowWrap: "anywhere" }}>{pending}</p><p className="muted">ZONIC can only act inside it when the matching permission is on. Subfolders are included.</p></>} onCancel={() => setPending(null)}
        onConfirm={async () => { const p = pending; setPending(null); if (await patch("workspaces", { items: [...items, { name: baseName(p), path: p }] }, true)) toast("success", "Workspace added."); }} />}
      {gone && <Confirm title="Remove this workspace?" danger confirmLabel="Remove" body={<p>ZONIC will lose access to it. Your files are not touched.</p>} onCancel={() => setGone(null)}
        onConfirm={async () => { const id = gone; setGone(null); await patch("workspaces", { items: items.filter((w) => w.id !== id) }); }} />}
    </div>
  );
}

export function AllowlistPanel() {
  const { s, patch, toast } = useSettings();
  const [pending, setPending] = useState<{ exe: string; key: string; label: string } | null>(null);
  if (!s) return null;
  const items = s.app_allowlist.items;
  const pick = async () => { const exe = await getBridge().pickExecutable(); if (exe) { const b = baseName(exe).replace(/\.exe$/i, ""); setPending({ exe, key: b.toLowerCase().replace(/[^a-z0-9_-]/g, ""), label: b }); } };
  return (
    <div className="col">
      {Object.keys(items).length === 0 && <Note>No applications allowed yet.</Note>}
      {Object.entries(items).map(([k, e]) => (
        <div key={k} className="row spread" style={{ padding: "6px 0", borderBottom: "1px solid #1a3335" }}>
          <div className="grow"><strong style={{ fontWeight: 500 }}>{e.label || k}</strong> <span className="muted small">as “{k}”</span><div className="mono muted" style={{ overflowWrap: "anywhere" }}>{e.exe}</div></div>
          <Btn small kind="danger" onClick={() => { const { [k]: _gone, ...rest } = items; void patch("app_allowlist", { items: rest }); }}>Remove</Btn>
        </div>
      ))}
      <div><Btn onClick={pick}>Allow an application…</Btn></div>
      {pending && (
        <Modal title="Allow this application?" onClose={() => setPending(null)}>
          <div className="col"><p className="mono" style={{ overflowWrap: "anywhere" }}>{pending.exe}</p>
            <Field label="Short name ZONIC will use"><input value={pending.key} onChange={(e) => setPending({ ...pending, key: e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, "") })} /></Field>
            <Field label="Display name"><input value={pending.label} onChange={(e) => setPending({ ...pending, label: e.target.value })} /></Field>
            <p className="muted small">ZONIC will be able to start it (no arguments) when “Launch allowlisted apps” is on.</p>
            <div className="row spread"><Btn onClick={() => setPending(null)}>Cancel</Btn>
              <Btn kind="primary" disabled={!pending.key} onClick={async () => { const p = pending; setPending(null); if (await patch("app_allowlist", { items: { ...items, [p.key]: { exe: p.exe, label: p.label, process_names: [baseName(p.exe).toLowerCase()] } } }, true)) toast("success", "Application allowed."); }}>Allow</Btn></div></div>
        </Modal>
      )}
    </div>
  );
}

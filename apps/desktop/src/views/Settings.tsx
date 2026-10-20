import { useEffect, useState } from "react";
import { getBridge } from "../lib/bridge";
import { InteractionPanel, MemoryPanel, ModelPanel, PersonalizationPanel, VoicePanel } from "../components/forms";
import { Btn, Card, Confirm, Field, Note } from "../components/ui";
import { useSettings } from "../lib/useSettings";
import { useStore } from "../lib/store";

type Tab = "model" | "voice" | "personal" | "appearance" | "privacy" | "agent" | "diag";
const TABS: [Tab, string][] = [["model", "Model"], ["voice", "Voice"], ["personal", "Personalization"], ["appearance", "Appearance & startup"], ["privacy", "Memory & privacy"], ["agent", "Agent limits"], ["diag", "Diagnostics"]];

export function SettingsView() {
  const tab = useStore((s) => s.settingsTab) as Tab, setTab = useStore((s) => s.setSettingsTab);
  return (
    <div className="page">
      <div className="page-head"><h2>Settings</h2></div>
      <div className="tabs" role="tablist">{TABS.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{l}</button>)}</div>
      <Card>
        {tab === "model" && <><h3>Main brain — NVIDIA Nemotron 3 Super</h3><ModelPanel /></>}
        {tab === "voice" && <><h3>Voice — Gemini Live</h3><VoicePanel /></>}
        {tab === "personal" && <PersonalizationPanel />}
        {tab === "appearance" && <InteractionPanel />}
        {tab === "privacy" && <Privacy />}
        {tab === "agent" && <Limits />}
        {tab === "diag" && <Diagnostics />}
      </Card>
    </div>
  );
}

function Privacy() {
  const { s, patch, api, toast } = useSettings();
  const setView = useStore((x) => x.setView);
  const [clear, setClear] = useState(false);
  if (!s) return null;
  return (
    <div className="col gap-lg">
      <MemoryPanel />
      <Field label={`Delete screenshots after ${s.privacy.screenshot_retention_hours} hour(s)`}><input type="range" min={1} max={168} value={s.privacy.screenshot_retention_hours} onChange={(e) => void patch("privacy", { screenshot_retention_hours: Number(e.target.value) })} /></Field>
      <div className="row wrap"><Btn onClick={() => setView("memory")}>Open Memory center</Btn><Btn kind="danger" onClick={() => setClear(true)}>Delete all conversation history…</Btn></div>
      {clear && <Confirm title="Delete all conversations?" danger confirmLabel="Delete everything" body={<p>Every saved conversation and message is removed from this PC. Tasks and the audit trail are kept.</p>} onCancel={() => setClear(false)}
        onConfirm={async () => { setClear(false); try { await api.clearConversations(); await useStore.getState().loadConversation(null); toast("success", "Conversation history deleted."); } catch { toast("error", "Could not delete history."); } }} />}
    </div>
  );
}

function Limits() {
  const { s, patch } = useSettings();
  const [f, setF] = useState(s?.limits);
  useEffect(() => setF(s?.limits), [s?.limits]);
  if (!s || !f) return null;
  return (
    <div className="col gap-lg">
      <div className="grid3">
        <Field label="Max steps per task" hint="Stops runaway loops."><input type="number" min={1} max={40} value={f.max_steps} onChange={(e) => setF({ ...f, max_steps: Number(e.target.value) })} /></Field>
        <Field label="Task timeout (seconds)"><input type="number" min={30} max={1800} value={f.task_timeout_s} onChange={(e) => setF({ ...f, task_timeout_s: Number(e.target.value) })} /></Field>
        <Field label="Tasks at once"><input type="number" min={1} max={4} value={f.max_concurrent_tasks} onChange={(e) => setF({ ...f, max_concurrent_tasks: Number(e.target.value) })} /></Field>
      </div>
      <div><Btn kind="primary" onClick={() => void patch("limits", f)}>Save limits</Btn></div>
      <Note>Time spent waiting for your approval counts toward the task timeout.</Note>
    </div>
  );
}

function Diagnostics() {
  const status = useStore((s) => s.status);
  const { api, backend, toast, refresh, refreshStatus } = useSettings();
  const [redo, setRedo] = useState(false);
  const info = [["App version", getVersion()], ["Backend", status ? `v${status.backend.version}, up ${Math.round(status.backend.uptime_s)}s` : "—"], ["Credential storage", backend === "os-keyring" ? "Windows Credential Manager" : backend === "restricted-file" ? "Restricted local file (credential vault unavailable)" : "—"], ["Model endpoint", status?.model.base_url ?? "—"], ["Memory index", status ? `${status.memory.keyword_index}; ${status.memory.semantic_index.embedder}` : "—"]];
  return (
    <div className="col gap-lg">
      <table className="t"><tbody>{info.map(([k, v]) => <tr key={k}><td className="muted" style={{ width: 180 }}>{k}</td><td>{v}</td></tr>)}</tbody></table>
      <div className="row wrap"><Btn onClick={() => void getBridge().openLogs()}>Open logs folder</Btn><Btn onClick={() => void refreshStatus()}>Re-run status checks</Btn><Btn onClick={() => setRedo(true)}>Re-run setup…</Btn></div>
      <Note>Minimum supported window size is 960×640. Logs are redacted and stored locally; nothing is uploaded.</Note>
      {redo && <Confirm title="Re-run setup?" confirmLabel="Re-run setup" body={<p>The setup screens open again so you can review each step. Your saved settings, keys and memories are kept.</p>} onCancel={() => setRedo(false)}
        onConfirm={async () => { setRedo(false); try { await api.restartOnboarding(); await Promise.all([refresh(), refreshStatus()]); } catch { toast("error", "Could not restart setup."); } }} />}
    </div>
  );
}
const getVersion = () => useStore.getState().conn?.version ?? "dev";

import { useEffect, useRef, useState } from "react";
import { useNow, Btn, Card, Chip, EmptyState, ErrorState, LoadingState } from "./ui";
import { IconActivity, IconBolt, IconChat, IconMic, IconPlus, IconShield, IconStop, IconTasks, IconTools, IconLogs, IconChevron } from "./icons";
import { isActive, useVoice } from "../lib/hooks";
import { ApiError } from "../lib/api";
import { elapsed, timeOf, pretty } from "../lib/format";
import { useStore, type View } from "../lib/store";
import type { ActivityItem, ServiceState, Status, ToolInfo } from "../lib/types";

const SS: Record<ServiceState, string> = { ready: "ready", not_configured: "needs_setup", untested: "limited", error: "error" };

/** SystemStatusCard — only real values from /api/status. Unavailable things say so instead of inventing numbers. */
export function SystemStatusCard() {
  const status = useStore((s) => s.status);
  const link = useStore((s) => s.link);
  const setView = useStore((s) => s.setView);
  const refresh = useStore((s) => s.refreshStatus);
  const [busy, setBusy] = useState(false);
  if (!status) return <Card title="System status"><LoadingState /></Card>;
  const rows = buildRows(status, link === "live");
  return (
    <Card title="System status" action={<Btn small kind="ghost" disabled={busy} onClick={() => { setBusy(true); void refresh().finally(() => setBusy(false)); }} aria-label="Re-check system status">{busy ? "Checking…" : "Re-check"}</Btn>}>
      <div aria-live="polite">
        {rows.map((r) => (
          <div className="status-row" key={r.name}>
            <strong style={{ fontWeight: 500 }}>{r.name}</strong><Chip state={r.state} />
            <span className="detail">{r.detail}{r.view && <> · <a href="#" onClick={(e) => { e.preventDefault(); setView(r.view as View); }}>{r.action}</a></>}</span>
          </div>
        ))}
      </div>
      <p className="muted small" style={{ margin: "10px 0 0" }}>Last checked {timeOf(status.checked_at)}</p>
    </Card>
  );
}

function buildRows(s: Status, live: boolean) {
  const lt = (t: { at: string } | null) => (t ? ` (tested ${timeOf(t.at)})` : "");
  return [
    { name: "Python backend", state: live ? "ready" : "error", detail: live ? `v${s.backend.version}, up ${Math.round(s.backend.uptime_s)}s` : "Connection to the backend was lost — reconnecting." },
    { name: "Nemotron 3 Super", state: SS[s.model.state], detail: `${s.model.model} — ${s.model.detail}` + (s.model.state === "not_configured" ? "" : lt(s.model.last_test)), view: s.model.state === "ready" ? null : "settings", action: s.model.state === "not_configured" ? "Add API key" : "Open model settings" },
    { name: "Gemini Live voice", state: SS[s.voice.state], detail: s.voice.detail + (s.voice.state === "not_configured" ? "" : lt(s.voice.last_test)), view: s.voice.state === "ready" ? null : "settings", action: "Open voice settings" },
    { name: "Memory", state: s.memory.enabled ? "ready" : "limited", detail: s.memory.enabled ? `${s.memory.count} saved${s.memory.pending_review ? `, ${s.memory.pending_review} to review` : ""} · ${s.memory.keyword_index}` : "Memory is turned off.", view: "memory", action: "Open memory" },
    { name: "PC control", state: s.pc_control.granted.length ? "ready" : "limited", detail: s.pc_control.granted.length ? `${s.pc_control.granted.length} permission group(s), ${s.pc_control.workspaces} workspace(s)` : "Least privilege: nothing is allowed yet.", view: "permissions", action: "Review permissions" },
  ] as { name: string; state: string; detail: string; view?: string | null; action?: string }[];
}

/** ActiveTaskCard — the genuine task state. No percentage: the task system doesn't report one, so none is shown. */
export function ActiveTaskCard() {
  const tasks = useStore((s) => s.tasks);
  const toolCalls = useStore((s) => s.toolCalls);
  const events = useStore((s) => s.taskEvents);
  const cancel = useStore((s) => s.cancelTask);
  const open = useStore((s) => s.openTask);
  const setView = useStore((s) => s.setView);
  const active = tasks.filter(isActive);
  const last = tasks.find((t) => !isActive(t));
  const now = useNow(active.length > 0);
  const go = (id: string) => { open(id); setView("tasks"); };
  return (
    <Card title="Active task" action={<Btn small kind="ghost" onClick={() => setView("tasks")}>Task center</Btn>}>
      {active.length === 0 ? (
        <>
          <EmptyState icon={<IconTasks size={26} />} title="Nothing running">Ask ZONIC something in the conversation panel. Every request becomes a task you can inspect.</EmptyState>
          {last && (
            <div className="mini-list" style={{ marginTop: 12 }}>
              <div className="muted small" style={{ marginBottom: 2 }}>Last task</div>
              <button type="button" className="mi" onClick={() => go(last.id)} aria-label={`Open last task: ${last.goal}`}>
                <span className="grow"><span className="goal" style={{ display: "block" }}>{last.goal}</span><span className="row small" style={{ marginTop: 4 }}><Chip state={last.status} />{last.result.error && <span className="muted goal">{last.result.error}</span>}</span></span><IconChevron size={14} />
              </button>
            </div>
          )}
        </>
      ) : active.map((t) => {
        const ev = events[t.id]; const latest = ev?.length ? ev[ev.length - 1] : null;
        return (
          <div className="active-task" key={t.id} style={{ marginBottom: 10 }}>
            <div className="goal-full" title={t.goal}>{t.goal}</div>
            <div className="row wrap small"><Chip state={t.status} />{toolCalls[t.id] ? <span className="muted">{toolCalls[t.id]} tool call{toolCalls[t.id] === 1 ? "" : "s"}</span> : null}<span className="muted">· {elapsed(t.created_at, null, now)}</span>{t.cancel_requested && <span className="muted">· cancellation requested</span>}</div>
            {latest && <div className="step-line" aria-live="off">{pretty(latest.kind)}: {latest.message}</div>}
            <div className="row"><Btn small onClick={() => go(t.id)}>Details</Btn><Btn small kind="danger" disabled={t.cancel_requested} onClick={() => void cancel(t.id)} aria-label={`Cancel task: ${t.goal}`}><IconStop size={13} />{t.cancel_requested ? "Stopping…" : "Cancel"}</Btn></div>
          </div>
        );
      })}
    </Card>
  );
}

/** QuickActionsCard — every tile is wired to something that really exists in this app. */
export function QuickActionsCard() {
  const voice = useVoice();
  const api = useStore((s) => s.api)!;
  const link = useStore((s) => s.link);
  const toast = useStore((s) => s.toast);
  const setView = useStore((s) => s.setView);
  const setDrawer = useStore((s) => s.setDrawer);
  const newConvo = useStore((s) => s.newConversation);
  const refreshStatus = useStore((s) => s.refreshStatus);
  const [testing, setTesting] = useState(false);
  const live = link === "live";
  const testModel = async () => {
    setTesting(true);
    try {
      const r = await api.testNemotron();
      toast(r.ok ? "success" : "error", r.ok ? `Model reachable${r.latency_ms != null ? ` (${Math.round(r.latency_ms)} ms)` : ""}.` : `${r.message}${r.hint ? ` ${r.hint}` : ""}`);
      void refreshStatus();
    } catch (e) { toast("error", e instanceof ApiError ? e.message : "The connection test failed."); }
    finally { setTesting(false); }
  };
  const tiles: { key: string; icon: JSX.Element; title: string; desc: string; onClick: () => void; disabled?: boolean }[] = [
    { key: "voice", icon: voice.active ? <IconStop size={16} /> : <IconMic size={16} />, title: voice.active ? "Stop voice" : "Start voice", desc: voice.configured ? "Talk to ZONIC with Gemini Live" : "Needs a Gemini key — opens Settings", onClick: () => (voice.active ? voice.stop() : void voice.start()), disabled: !live },
    { key: "new", icon: <IconPlus size={16} />, title: "New conversation", desc: "Start fresh in the conversation panel", onClick: () => { newConvo(); setDrawer("chat"); } },
    { key: "test", icon: <IconBolt size={16} />, title: testing ? "Testing…" : "Test model link", desc: "Check the Nemotron connection now", onClick: () => void testModel(), disabled: !live || testing },
    { key: "tools", icon: <IconTools size={16} />, title: "Skills & Tools", desc: "Browse and toggle capabilities", onClick: () => setView("skills") },
    { key: "perm", icon: <IconShield size={16} />, title: "Permissions", desc: "Review what ZONIC may access", onClick: () => setView("permissions") },
    { key: "logs", icon: <IconLogs size={16} />, title: "Activity & logs", desc: "Audit trail and backend log", onClick: () => setView("activity") },
  ];
  return (
    <Card title="Quick actions">
      <div className="quick-grid">
        {tiles.map((t) => <button key={t.key} type="button" className="qa" disabled={t.disabled} onClick={t.onClick}><span className="qi" aria-hidden>{t.icon}</span><b>{t.title}</b><span className="d">{t.desc}</span></button>)}
      </div>
    </Card>
  );
}

/** RecentActivityCard — real events from /api/activity (task events + audit trail). */
export function RecentActivityCard() {
  const api = useStore((s) => s.api)!;
  const tasks = useStore((s) => s.tasks);
  const open = useStore((s) => s.openTask);
  const setView = useStore((s) => s.setView);
  const [items, setItems] = useState<ActivityItem[] | null>(null);
  const [err, setErr] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const sig = tasks.map((t) => t.id + t.status).join("|");
  const load = () => api.activity(8).then((r) => { setItems(r.items); setErr(false); }).catch(() => setErr(true));
  useEffect(() => { clearTimeout(timer.current); timer.current = setTimeout(() => void load(), items === null ? 0 : 500); return () => clearTimeout(timer.current); }, [api, sig]); // eslint-disable-line react-hooks/exhaustive-deps
  const tone = (e: ActivityItem) => (e.outcome === false || e.outcome === "failed" || e.outcome === "denied" ? "bad" : e.outcome === true || e.outcome === "ok" || e.outcome === "approved" ? "ok" : e.outcome === "pending" ? "act" : "");
  return (
    <Card title="Recent activity" action={<Btn small kind="ghost" onClick={() => setView("activity")}>All activity</Btn>}>
      {err && <ErrorState onRetry={() => void load()}>Could not load activity.</ErrorState>}
      {!err && items === null && <LoadingState rows={4} />}
      {!err && items?.length === 0 && <EmptyState icon={<IconActivity size={26} />} title="No activity yet">Task events and audit entries will appear here.</EmptyState>}
      {items && items.length > 0 && (
        <div className="feed">
          {items.slice(0, 7).map((e, i) => (
            <div className="ev" key={`${e.ts}-${i}`} style={{ cursor: e.task_id ? "pointer" : undefined }} onClick={() => { if (e.task_id) { open(e.task_id); setView("tasks"); } }}>
              <i className={tone(e)} aria-hidden /><span className="t">{timeOf(e.ts)}</span><span className="m" title={e.message}>{e.message}</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

export function RecentConversationsCard() {
  const list = useStore((s) => s.conversations);
  const load = useStore((s) => s.loadConversation);
  const setDrawer = useStore((s) => s.setDrawer);
  return (
    <Card title="Recent conversations">
      {list === null ? <LoadingState rows={3} /> : list.length === 0 ? <EmptyState icon={<IconChat size={26} />} title="No saved conversations">History saving can be changed in Settings → Memory &amp; privacy.</EmptyState> : (
        <div className="mini-list">
          {list.slice(0, 5).map((c) => (
            <button type="button" className="mi" key={c.id} onClick={() => { void load(c.id); setDrawer("chat"); }}>
              <IconChat size={15} /><span className="grow"><span className="goal" style={{ display: "block" }}>{c.title}</span><span className="muted small">{new Date(c.updated_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}</span></span><IconChevron size={14} />
            </button>
          ))}
        </div>
      )}
    </Card>
  );
}

/** CapabilitiesCard — the live tool inventory from /api/tools, summarised. Nothing is listed that the backend doesn't report. */
export function CapabilitiesCard() {
  const api = useStore((s) => s.api)!;
  const setView = useStore((s) => s.setView);
  const sig = useStore((s) => s.status?.checked_at);
  const [tools, setTools] = useState<ToolInfo[] | null>(null);
  const [err, setErr] = useState(false);
  const load = () => api.tools().then((r) => { setTools(r.items); setErr(false); }).catch(() => setErr(true));
  useEffect(() => { void load(); }, [api, sig]); // eslint-disable-line react-hooks/exhaustive-deps
  const by = (st: string) => tools?.filter((t) => t.status === st).length ?? 0;
  return (
    <Card title="Capabilities" action={<Btn small kind="ghost" onClick={() => setView("skills")}>Skills &amp; Tools</Btn>}>
      {err && <ErrorState onRetry={() => void load()}>Could not load the tool inventory.</ErrorState>}
      {!err && tools === null && <LoadingState rows={3} />}
      {tools && (
        <div className="col">
          <div className="row wrap small"><Chip state="available" label={`${by("available")} ready`} /><Chip state="permission_gated" label={`${by("permission_gated")} need permission`} />{by("disabled") > 0 && <Chip state="disabled" label={`${by("disabled")} turned off`} />}{by("unavailable") > 0 && <Chip state="unavailable" label={`${by("unavailable")} unavailable`} />}</div>
          <div className="cap-grid">{tools.slice(0, 12).map((t) => <span key={t.name} className="chip" title={t.reason ?? t.description}><span aria-hidden>{t.status === "available" ? "✓" : t.status === "permission_gated" ? "🔒" : "–"}</span>{t.name}</span>)}{tools.length > 12 && <span className="muted small">+{tools.length - 12} more</span>}</div>
        </div>
      )}
    </Card>
  );
}

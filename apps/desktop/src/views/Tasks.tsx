import { useEffect, useState } from "react";
import { Btn, Card, Chip, Empty, ErrorNote, Loading, useNow } from "../components/ui";
import { elapsed, pretty, timeOf } from "../lib/format";
import { isActive } from "../lib/hooks";
import { useStore } from "../lib/store";
import type { Task } from "../lib/types";

export function Tasks() {
  const tasks = useStore((s) => s.tasks);
  const detail = useStore((s) => s.taskDetail);
  const open = useStore((s) => s.openTask);
  const [filter, setFilter] = useState<"all" | "active">("all");
  const shown = filter === "active" ? tasks.filter(isActive) : tasks;
  const now = useNow(tasks.some(isActive));
  return (
    <div className="page">
      <div className="page-head"><h2>Task center</h2>
        <div className="tabs" role="tablist"><button role="tab" aria-selected={filter === "all"} onClick={() => setFilter("all")}>All ({tasks.length})</button><button role="tab" aria-selected={filter === "active"} onClick={() => setFilter("active")}>Active ({tasks.filter(isActive).length})</button></div></div>
      <div className="grid2" style={{ gridTemplateColumns: detail ? "minmax(0,1fr) minmax(0,1.1fr)" : "1fr", alignItems: "start" }}>
        <Card>
          {shown.length === 0 ? <Empty>{filter === "active" ? "Nothing is running right now." : "No tasks yet. Every request you send becomes a task you can inspect here."}</Empty> : (
            <table className="t"><thead><tr><th>Task</th><th>State</th><th>Time</th></tr></thead><tbody>
              {shown.map((t) => (
                <tr key={t.id} onClick={() => open(t.id)} style={{ cursor: "pointer", background: t.id === detail ? "var(--surface-raised)" : undefined }}>
                  <td><div className="goal" style={{ maxWidth: 320 }} title={t.goal}>{t.goal}</div><div className="muted small">{timeOf(t.created_at)}</div></td>
                  <td><Chip state={t.status} /></td>
                  <td className="muted small">{elapsed(t.created_at, isActive(t) ? null : t.updated_at, now)}</td>
                </tr>))}
            </tbody></table>)}
        </Card>
        {detail && <TaskDetail id={detail} onClose={() => open(null)} />}
      </div>
    </div>
  );
}

function TaskDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const api = useStore((s) => s.api)!;
  const tasks = useStore((s) => s.tasks);
  const cancel = useStore((s) => s.cancelTask);
  const [task, setTask] = useState<Task | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const listed = tasks.find((t) => t.id === id);
  useEffect(() => { setErr(null); api.task(id).then(setTask).catch(() => setErr("Could not load this task.")); }, [id, listed?.status, listed?.updated_at, api]);
  if (err) return <Card><ErrorNote>{err}</ErrorNote></Card>;
  if (!task) return <Card><Loading /></Card>;
  const v = task.result.verification;
  return (
    <Card title="Task details" action={<Btn small kind="ghost" onClick={onClose} aria-label="Close details">✕</Btn>}>
      <div className="col">
        <div><div className="muted small">Goal</div><div>{task.goal}</div></div>
        <div className="row wrap"><Chip state={task.status} />{task.cancel_requested && task.status !== "cancelled" && <span className="muted small">cancellation requested</span>}
          {isActive(task) && <Btn small kind="danger" onClick={() => void cancel(task.id)}>Cancel task</Btn>}</div>
        {task.result.error && <ErrorNote>{task.result.error}</ErrorNote>}
        {task.result.final && <div><div className="muted small">Result</div><div style={{ whiteSpace: "pre-wrap" }}>{task.result.final}</div></div>}
        {v && v.status !== "not_applicable" && (
          <div className="note"><div className="row"><strong>Verification</strong><Chip state={v.status} /></div>
            {v.failed.map((f, i) => <div key={i} className="small">✕ {f}</div>)}{v.unverified.map((f, i) => <div key={i} className="small">◐ {f}</div>)}
            {v.status === "verified" && <div className="small">All {v.checked} state-changing action(s) were confirmed by an independent check.</div>}</div>)}
        <div><div className="muted small" style={{ marginBottom: 4 }}>Timeline</div>
          <div className="timeline">{(task.events ?? []).map((e) => (
            <div className="tl" key={e.id}><span className="k mono">{timeOf(e.timestamp)}<br />{pretty(e.kind)}</span>
              <div>{e.message}{Array.isArray(e.data.evidence) && (e.data.evidence as { value: string; passed: boolean }[]).map((ev, i) => <div key={i} className="small muted">{ev.passed ? "✓" : "✕"} evidence: {ev.value}</div>)}</div></div>))}</div></div>
      </div>
    </Card>
  );
}

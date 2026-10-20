import { useEffect, useState } from "react";
import { getBridge } from "../lib/bridge";
import { Btn, Card, Chip, Empty, ErrorNote, Loading } from "../components/ui";
import { dateTimeOf, pretty } from "../lib/format";
import { useStore } from "../lib/store";
import type { ActivityItem } from "../lib/types";

export function Activity() {
  const api = useStore((s) => s.api)!;
  const tasks = useStore((s) => s.tasks);
  const open = useStore((s) => s.openTask);
  const setView = useStore((s) => s.setView);
  const [items, setItems] = useState<ActivityItem[] | null>(null);
  const [src, setSrc] = useState<"all" | "task" | "audit">("all");
  const [err, setErr] = useState(false);
  const [logs, setLogs] = useState<string[] | null>(null);
  useEffect(() => { api.activity(200).then((r) => { setItems(r.items); setErr(false); }).catch(() => setErr(true)); }, [api, tasks]);
  const shown = (items ?? []).filter((i) => src === "all" || i.source === src);
  return (
    <div className="page">
      <div className="page-head"><h2>Activity</h2><div className="tabs" role="tablist">{(["all", "task", "audit"] as const).map((k) => <button key={k} role="tab" aria-selected={src === k} onClick={() => setSrc(k)}>{k === "all" ? "Everything" : k === "task" ? "Task events" : "Audit trail"}</button>)}</div></div>
      <p className="muted">Real events only: what ZONIC did, what it was refused, and what you changed. Secrets are redacted.</p>
      {err && <ErrorNote>Could not load activity.</ErrorNote>}
      {items === null && !err ? <Loading /> : shown.length === 0 ? <Empty>No activity yet.</Empty> : (
        <Card><table className="t"><thead><tr><th>Time</th><th>Event</th><th>Outcome</th></tr></thead><tbody>
          {shown.map((e, i) => (
            <tr key={i} style={{ cursor: e.task_id ? "pointer" : undefined }} onClick={() => { if (e.task_id) { open(e.task_id); setView("tasks"); } }}>
              <td className="muted small mono" style={{ whiteSpace: "nowrap" }}>{dateTimeOf(e.ts)}</td>
              <td><div>{e.message}</div><div className="muted small">{e.source === "audit" ? "Audit" : "Task"} · {pretty(e.kind)}</div></td>
              <td>{e.outcome === true || e.outcome === "ok" ? <Chip state="ready" label="OK" /> : e.outcome === false ? <Chip state="failed" label="Failed" /> : typeof e.outcome === "string" && e.outcome !== "pending" ? <Chip state={["approved", "ok"].includes(e.outcome) ? "ready" : "failed"} label={pretty(e.outcome)} /> : ""}</td>
            </tr>))}
        </tbody></table></Card>)}
      <Card title="Backend log (redacted)" action={<div className="row"><Btn small onClick={() => api.logs(150).then((r) => setLogs(r.lines))}>{logs ? "Refresh" : "Show last 150 lines"}</Btn><Btn small onClick={() => void getBridge().openLogs()}>Open logs folder</Btn></div>}>
        {logs ? <pre className="code" style={{ maxHeight: 280 }}>{logs.join("\n") || "(empty)"}</pre> : <p className="muted small">Not loaded.</p>}
      </Card>
    </div>
  );
}

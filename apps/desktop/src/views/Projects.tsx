import { useEffect, useState } from "react";
import { AllowlistPanel, PermissionsPanel, WorkspacesPanel } from "../components/forms";
import { Card, Chip, Empty, Loading } from "../components/ui";
import { useStore } from "../lib/store";
import type { Project } from "../lib/types";

export function Projects() {
  const api = useStore((s) => s.api)!;
  const ws = useStore((s) => s.settings?.settings.workspaces.items);
  const [items, setItems] = useState<Project[] | null>(null);
  useEffect(() => { void api.projects().then((r) => setItems(r.items)).catch(() => setItems([])); }, [api, ws]);
  return (
    <div className="page">
      <div className="page-head"><h2>Projects</h2></div>
      <p className="muted">A project is a workspace folder you have approved. ZONIC can only read or write inside these folders, and only when the matching permission is on.</p>
      <Card title="Approved workspaces"><WorkspacesPanel /></Card>
      {items === null ? <Loading /> : items.length === 0 ? <Empty>No projects yet. Add a workspace folder above.</Empty> : items.map((p) => (
        <Card key={p.id} title={<span className="row">{p.name} <Chip state={p.exists ? "ready" : "error"} label={p.exists ? "Folder found" : "Folder missing"} /></span>}>
          <div className="mono muted" style={{ overflowWrap: "anywhere" }}>{p.path}</div>
          <div className="small muted" style={{ margin: "8px 0 4px" }}>{p.entry_count} top-level item(s){p.entry_count > p.preview.length ? `, first ${p.preview.length} shown` : ""}</div>
          {p.preview.length > 0 ? <div className="mono small" style={{ columns: 2, columnGap: 24 }}>{p.preview.map((n) => <div key={n} className="goal">{n}</div>)}</div> : <div className="muted small">Empty folder.</div>}
        </Card>))}
    </div>
  );
}

export function Permissions() {
  return (
    <div className="page">
      <div className="page-head"><h2>Permissions center</h2></div>
      <p className="muted">ZONIC starts with no access. Grant only what you need; the backend enforces every rule below, and you can revoke instantly.</p>
      <Card title="What ZONIC may do"><PermissionsPanel /></Card>
      <div className="grid2" style={{ alignItems: "start" }}>
        <Card title="Approved workspaces"><WorkspacesPanel compact /></Card>
        <Card title="Allowed applications"><AllowlistPanel /></Card>
      </div>
    </div>
  );
}

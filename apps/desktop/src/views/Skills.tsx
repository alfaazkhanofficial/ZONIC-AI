import { Fragment, useCallback, useEffect, useState } from "react";
import { ApiError } from "../lib/api";
import { Btn, Card, Chip, Confirm, Empty, ErrorNote, Field, Loading, Note, Toggle } from "../components/ui";
import { dateTimeOf, pretty } from "../lib/format";
import { useStore } from "../lib/store";
import type { SkillRow, ToolInfo } from "../lib/types";

const TEMPLATE = JSON.stringify({
  name: "daily-note", description: "Create a note file in the workspace and read it back",
  parameters: { filename: { type: "string", description: "File name" }, text: { type: "string", description: "Note text" } },
  steps: [{ tool: "write_approved_file", args: { path: "{{filename}}", content: "{{text}}" } }, { tool: "read_approved_file", args: { path: "{{filename}}" } }],
}, null, 2);

export function Skills() {
  const [tab, setTab] = useState<"tools" | "skills">("tools");
  return (
    <div className="page">
      <div className="page-head"><h2>Skills &amp; Tools</h2></div>
      <div className="tabs" role="tablist"><button role="tab" aria-selected={tab === "tools"} onClick={() => setTab("tools")}>Tools</button><button role="tab" aria-selected={tab === "skills"} onClick={() => setTab("skills")}>Skills</button></div>
      {tab === "tools" ? <Tools /> : <SkillsTab />}
    </div>
  );
}

function Tools() {
  const api = useStore((s) => s.api)!;
  const perms = useStore((s) => s.settings?.settings.permissions);
  const toast = useStore((s) => s.toast);
  const [tools, setTools] = useState<ToolInfo[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const load = useCallback(() => api.tools().then((r) => setTools(r.items)).catch(() => toast("error", "Could not load tools.")), [api, toast]);
  useEffect(() => { void load(); }, [load, perms]);
  if (!tools) return <Loading />;
  return (
    <div className="col">
      <Note>Tools are the only things ZONIC can do. Each has a schema, a permission group, a risk level and a verification method. Disabling a tool removes it from ZONIC’s options entirely.</Note>
      <Card><table className="t"><thead><tr><th>Tool</th><th>Status</th><th>Needs</th><th>Risk</th><th>Enabled</th></tr></thead><tbody>
        {tools.map((t) => (
          <Fragment key={t.name}>
            <tr>
              <td><button className="btn ghost small" onClick={() => setOpen(open === t.name ? null : t.name)} aria-expanded={open === t.name}><span className="mono">{t.name}</span></button><div className="muted small" style={{ maxWidth: 380 }}>{t.description}</div></td>
              <td><Chip state={t.status} />{t.reason && <div className="muted small" style={{ maxWidth: 220 }}>{t.reason}</div>}</td>
              <td className="small">{t.permission ? pretty(t.permission) : "—"}{t.approval !== "never" && <div className="muted">asks approval ({t.approval === "always" ? "always" : "when overwriting"})</div>}</td>
              <td><Chip state={t.risk} /></td>
              <td><Toggle checked={t.enabled} label={<span className="sr" style={{ position: "absolute", left: -9999 }}>Enable {t.name}</span>} onChange={async (v) => { try { await api.toggleTool(t.name, v); await load(); } catch (e) { toast("error", e instanceof ApiError ? e.message : "Failed."); } }} /></td>
            </tr>
            {open === t.name && <tr><td colSpan={5}><div className="small"><strong>Verification:</strong> {t.verification}<br /><strong>Timeout:</strong> {t.timeout_s}s · <strong>Side effect:</strong> {t.side_effect}</div><pre className="code">{JSON.stringify(t.input_schema, null, 2)}</pre></td></tr>}
          </Fragment>
        ))}
      </tbody></table></Card>
    </div>
  );
}

function SkillsTab() {
  const api = useStore((s) => s.api)!;
  const approvals = useStore((s) => s.approvals);
  const decide = useStore((s) => s.decide);
  const toast = useStore((s) => s.toast);
  const [rows, setRows] = useState<SkillRow[] | null>(null);
  const [draft, setDraft] = useState<string | null>(null);
  const [err, setErr] = useState<string[] | null>(null);
  const [del, setDel] = useState<string | null>(null);
  const load = useCallback(() => api.skills().then((r) => setRows(r.items)).catch(() => toast("error", "Could not load skills.")), [api, toast]);
  useEffect(() => { void load(); }, [load, approvals.length]);
  if (!rows) return <Loading />;
  const names = [...new Set(rows.map((r) => r.name))];
  const submit = async () => {
    let def: unknown;
    try { def = JSON.parse(draft ?? ""); } catch { setErr(["That is not valid JSON."]); return; }
    try {
      const r = await api.createSkill(def);
      if (r.status === "rejected") setErr(r.validation.errors); else { setErr(null); setDraft(null); toast("success", `Skill “${r.name}” validated. Approve it to activate.`); await load(); }
    } catch (e) { setErr([e instanceof ApiError ? e.message : "Failed."]); }
  };
  return (
    <div className="col">
      <Note>Skills are reusable workflows: a list of steps that call tools. They contain no code and cannot give themselves permissions — each step is checked by the same permission and approval rules as everything else. New skills (including ones ZONIC drafts) must be approved by you before they can run.</Note>
      <div><Btn kind="primary" onClick={() => { setDraft(TEMPLATE); setErr(null); }}>+ New skill</Btn></div>
      {draft !== null && (
        <Card title="New skill (JSON)">
          <Field label="Definition" hint="Use {{parameter}} placeholders inside step arguments."><textarea className="mono" rows={14} value={draft} onChange={(e) => setDraft(e.target.value)} spellCheck={false} /></Field>
          {err && <div style={{ marginTop: 8 }}><ErrorNote>{err.map((e, i) => <div key={i}>{e}</div>)}</ErrorNote></div>}
          <div className="row spread" style={{ marginTop: 10 }}><Btn onClick={() => setDraft(null)}>Cancel</Btn><Btn kind="primary" onClick={submit}>Validate &amp; submit for approval</Btn></div>
        </Card>)}
      {names.length === 0 && draft === null && <Empty>No skills yet. Ask ZONIC to “make a skill for …”, or create one yourself.</Empty>}
      {names.map((n) => {
        const vs = rows.filter((r) => r.name === n);
        return (
          <Card key={n} title={<span className="mono">{n}</span>} action={<Btn small kind="danger" onClick={() => setDel(n)}>Delete skill</Btn>}>
            {vs.map((v) => {
              const ap = approvals.find((a) => a.kind === "register_skill" && a.payload?.name === v.name && a.payload?.version === v.version);
              return (
                <div key={v.version} style={{ padding: "8px 0", borderTop: "1px solid #1a3335" }}>
                  <div className="row spread wrap"><div className="row"><strong>v{v.version}</strong><Chip state={v.status} /><span className="muted small">by {v.created_by === "user" ? "you" : "ZONIC"} · {dateTimeOf(v.created_at)}</span></div>
                    <div className="row">
                      {v.status === "pending_approval" && (ap ? <><Btn small kind="primary" onClick={() => void decide(ap.id, true)}>Approve</Btn><Btn small onClick={() => void decide(ap.id, false)}>Reject</Btn></>
                        : <Btn small onClick={async () => { try { await api.requestSkillApproval(v.name, v.version); toast("info", "Approval requested."); } catch (e) { toast("error", e instanceof ApiError ? e.message : "Failed."); } }}>Request approval</Btn>)}
                      {v.status === "superseded" && <Btn small onClick={async () => { await api.rollbackSkill(v.name, v.version); await load(); toast("success", `Rolled back to v${v.version}.`); }}>Roll back to this</Btn>}
                    </div></div>
                  <div className="small" style={{ marginTop: 4 }}>{v.definition.description}</div>
                  <div className="muted small">{v.definition.steps.length} step(s): {v.definition.steps.map((s) => s.tool).join(" → ")} · permissions: {v.validation.permissions.join(", ") || "none"} · risk: {v.validation.risk} · no code executed</div>
                </div>);
            })}
          </Card>);
      })}
      {del && <Confirm title="Delete this skill?" danger confirmLabel="Delete" body={<p>All versions of <span className="mono">{del}</span> will be removed.</p>} onCancel={() => setDel(null)} onConfirm={async () => { const n = del; setDel(null); try { await api.deleteSkill(n); await load(); } catch { toast("error", "Could not delete."); } }} />}
    </div>
  );
}

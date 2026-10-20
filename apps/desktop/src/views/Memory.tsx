import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../lib/api";
import { Btn, Card, Chip, Confirm, Empty, ErrorNote, Field, Loading, Modal, Note } from "../components/ui";
import { MemoryPanel } from "../components/forms";
import { dateTimeOf, pretty } from "../lib/format";
import { useStore } from "../lib/store";
import type { Memory as Mem, Status } from "../lib/types";

const CATS = ["preference", "project", "procedural", "knowledge", "working"];

export function MemoryView() {
  const api = useStore((s) => s.api)!;
  const toast = useStore((s) => s.toast);
  const refreshStatus = useStore((s) => s.refreshStatus);
  const [items, setItems] = useState<Mem[] | null>(null);
  const [info, setInfo] = useState<Status["memory"] | null>(null);
  const [tab, setTab] = useState<"approved" | "pending">("approved");
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [edit, setEdit] = useState<Mem | null>(null);
  const [add, setAdd] = useState(false);
  const [del, setDel] = useState<Mem | null>(null);
  const [clear, setClear] = useState(false);
  const [settings, setSettings] = useState(false);
  const load = useCallback(async () => {
    try { const r = await api.memories({ q: q || undefined, category: cat || undefined, approved: q ? undefined : tab === "approved" }); setItems(r.items); setInfo(r.status); setErr(null); }
    catch (e) { setErr(e instanceof ApiError ? e.message : "Could not load memories."); }
  }, [api, q, cat, tab]);
  useEffect(() => { const t = setTimeout(() => void load(), q ? 200 : 0); return () => clearTimeout(t); }, [load, q]);
  const shown = (items ?? []).filter((m) => (q ? (tab === "approved" ? m.user_approved : !m.user_approved) : true));
  const act = async (fn: () => Promise<unknown>, ok?: string) => { try { await fn(); await load(); void refreshStatus(); if (ok) toast("success", ok); } catch (e) { toast("error", e instanceof ApiError ? e.message : "Failed."); } };
  return (
    <div className="page">
      <div className="page-head"><h2>Memory center</h2><div className="row"><Btn onClick={() => setSettings(!settings)}>Memory settings</Btn><Btn kind="primary" onClick={() => setAdd(true)}>+ Add memory</Btn></div></div>
      {settings && <Card title="What ZONIC may remember"><MemoryPanel /></Card>}
      {info && <Note>{info.count} saved · {info.pending_review} waiting for your review · keyword search: {info.keyword_index} · similarity index: {info.semantic_index.enabled ? `${info.semantic_index.embedder} (${info.semantic_index.indexed} indexed — ${info.semantic_index.note})` : "off"}</Note>}
      <div className="row wrap">
        <div className="tabs" role="tablist"><button role="tab" aria-selected={tab === "approved"} onClick={() => setTab("approved")}>Saved</button><button role="tab" aria-selected={tab === "pending"} onClick={() => setTab("pending")}>To review{info?.pending_review ? ` (${info.pending_review})` : ""}</button></div>
        <div className="grow"><input aria-label="Search memories" placeholder="Search memories…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <select aria-label="Filter by category" style={{ width: 170 }} value={cat} onChange={(e) => setCat(e.target.value)}><option value="">All categories</option>{CATS.map((c) => <option key={c} value={c}>{pretty(c)}</option>)}</select>
      </div>
      {err && <ErrorNote>{err}</ErrorNote>}
      {items === null && !err ? <Loading /> : shown.length === 0 ? <Empty>{q ? "No memories match your search." : tab === "approved" ? "Nothing saved yet. Add a memory, or approve candidates ZONIC proposes." : "No candidates waiting. When ZONIC proposes something worth remembering it shows up here for your approval."}</Empty> : (
        <div className="col">{shown.map((m) => (
          <Card key={m.id}>
            <div className="row spread" style={{ alignItems: "flex-start" }}>
              <div className="grow"><div style={{ whiteSpace: "pre-wrap" }}>{m.content}</div>
                <div className="row wrap small muted" style={{ marginTop: 6 }}><Chip state="low" label={pretty(m.category)} /><span>{m.provenance.source === "user_ui" ? "Added by you" : `Proposed by ZONIC (${m.provenance.source})`}</span><span>· {dateTimeOf(m.updated_at)}</span>
                  {m.match && <span>· matched by {m.match.join(" + ")}</span>}</div></div>
              <div className="row">{!m.user_approved && <Btn small kind="primary" onClick={() => act(() => api.patchMemory(m.id, { user_approved: true }), "Memory approved.")}>Approve</Btn>}
                <Btn small onClick={() => setEdit(m)}>Edit</Btn><Btn small kind="danger" onClick={() => setDel(m)}>{m.user_approved ? "Delete" : "Reject"}</Btn></div>
            </div>
          </Card>))}</div>)}
      <div className="row spread"><span className="muted small">Secrets are never saved. Everything here lives only in the local database on this PC.</span><Btn kind="danger" small onClick={() => setClear(true)} disabled={!info?.count}>Delete all memories…</Btn></div>
      {(add || edit) && <MemoryEditor m={edit} onClose={() => { setAdd(false); setEdit(null); }} onSave={(content, category) => act(async () => { if (edit) await api.patchMemory(edit.id, { content, category }); else await api.createMemory(content, category); setAdd(false); setEdit(null); }, "Saved.")} />}
      {del && <Confirm title={del.user_approved ? "Delete this memory?" : "Reject this candidate?"} danger confirmLabel={del.user_approved ? "Delete" : "Reject"} body={<p>“{del.content.slice(0, 160)}”</p>} onCancel={() => setDel(null)} onConfirm={() => { const m = del; setDel(null); void act(() => api.deleteMemory(m.id)); }} />}
      {clear && <ClearAll count={info?.count ?? 0} onCancel={() => setClear(false)} onConfirm={() => { setClear(false); void act(() => api.clearMemories(), "All memories deleted."); }} />}
    </div>
  );
}

function MemoryEditor({ m, onClose, onSave }: { m: Mem | null; onClose: () => void; onSave: (c: string, cat: string) => void }) {
  const [content, setContent] = useState(m?.content ?? "");
  const [category, setCategory] = useState(m?.category ?? "knowledge");
  return (
    <Modal title={m ? "Edit memory" : "Add a memory"} onClose={onClose}>
      <div className="col"><Field label="What should ZONIC remember?" hint="Don't include passwords, API keys or card numbers — they will be refused."><textarea rows={4} value={content} maxLength={2000} onChange={(e) => setContent(e.target.value)} /></Field>
        <Field label="Category"><select value={category} onChange={(e) => setCategory(e.target.value)}>{CATS.map((c) => <option key={c} value={c}>{pretty(c)}</option>)}</select></Field>
        <div className="row spread"><Btn onClick={onClose}>Cancel</Btn><Btn kind="primary" disabled={content.trim().length < 3} onClick={() => onSave(content, category)}>Save</Btn></div></div>
    </Modal>
  );
}

function ClearAll({ count, onCancel, onConfirm }: { count: number; onCancel: () => void; onConfirm: () => void }) {
  const [t, setT] = useState("");
  return (
    <Modal title="Delete all memories?" onClose={onCancel}>
      <div className="col"><p>This permanently deletes all {count} memories from this PC. It cannot be undone.</p>
        <Field label="Type DELETE to confirm"><input value={t} onChange={(e) => setT(e.target.value)} /></Field>
        <div className="row spread"><Btn onClick={onCancel}>Cancel</Btn><Btn kind="danger" disabled={t !== "DELETE"} onClick={onConfirm}>Delete everything</Btn></div></div>
    </Modal>
  );
}

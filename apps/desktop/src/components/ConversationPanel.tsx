import { memo, useCallback, useLayoutEffect, useRef, useState } from "react";
import { isActive, useVoice } from "../lib/hooks";
import { dateTimeOf, pretty, timeOf } from "../lib/format";
import { useStore } from "../lib/store";
import type { Message, Task, TaskEvent } from "../lib/types";
import { Composer, MicMeter } from "./Composer";
import { IconChat, IconClose, IconHistory, IconPanel, IconPlus, IconTrash, IconBolt } from "./icons";
import { Btn, Chip, Confirm, EmptyState, IconButton, LoadingState } from "./ui";

const NEAR_BOTTOM = 96;

/** ToolActivityItem: compact, expandable view of the REAL events a finished task recorded (loaded on demand from the backend). */
function ToolActivityItem({ task }: { task: Task }) {
  const api = useStore((s) => s.api)!;
  const [events, setEvents] = useState<TaskEvent[] | null>(null);
  const [err, setErr] = useState(false);
  const n = task.result.tool_calls ?? 0;
  const load = (open: boolean) => { if (open && !events) api.task(task.id).then((t) => setEvents(t.events ?? [])).catch(() => setErr(true)); };
  return (
    <details className="tool-ev" onToggle={(e) => load((e.target as HTMLDetailsElement).open)}>
      <summary><IconBolt size={14} />{n} tool call{n === 1 ? "" : "s"}<span className="muted">· {task.result.steps ?? 0} step{task.result.steps === 1 ? "" : "s"}</span></summary>
      <div className="body">
        {err && <span className="rec">Could not load the task events.</span>}
        {!events && !err && <LoadingState rows={2} />}
        {events?.filter((e) => ["tool_call", "tool_result", "verification", "error"].includes(e.kind) || e.kind.startsWith("tool")).map((e) => (
          <div key={e.id}><span className="mono muted">{timeOf(e.timestamp)}</span> {e.message}</div>
        ))}
        {events && !events.some((e) => e.kind.startsWith("tool")) && <span className="muted">No tool events were recorded.</span>}
      </div>
    </details>
  );
}

const MessageItem = memo(function MessageItem({ m, task }: { m: Message; task?: Task }) {
  const v = m.metadata.verification;
  return (
    <>
      <div className={`msg ${m.role} ${m.metadata.error ? "error" : ""}`}>
        <div className="bubble">{m.content}</div>
        <div className="meta"><span>{dateTimeOf(m.created_at)}</span>{m.metadata.voice && <span>voice</span>}
          {m.metadata.error && <Chip state="failed" label="Error" />}
          {v && v.status !== "not_applicable" && <Chip state={v.status} label={`Actions ${v.status}`} />}</div>
      </div>
      {task && (task.result.tool_calls ?? 0) > 0 && <ToolActivityItem task={task} />}
    </>
  );
});

function LiveTask({ task }: { task: Task }) {
  const streaming = useStore((s) => s.streaming[task.id]);
  const events = useStore((s) => s.taskEvents[task.id]);
  const calls = (events ?? []).filter((e) => e.kind === "tool_call");
  return (
    <>
      {calls.length > 0 && (
        <details className="tool-ev" open>
          <summary><IconBolt size={14} />Working · {calls.length} tool call{calls.length === 1 ? "" : "s"}</summary>
          <div className="body">{calls.slice(-6).map((e) => <div key={e.id}><span className="mono muted">{timeOf(e.ts)}</span> {e.message}</div>)}</div>
        </details>
      )}
      <div className="msg assistant working">
        <div className="bubble">{streaming || <span>{pretty(task.status)}<span className="typing" aria-hidden><i /><i /><i /></span></span>}</div>
        <div className="meta"><Chip state={task.status} /></div>
      </div>
    </>
  );
}

/** MessageList: auto-follows new content only when the reader is already near the bottom, so history can be read while streaming. */
function MessageList() {
  const cid = useStore((s) => s.conversationId);
  const messages = useStore((s) => s.messages);
  const tasks = useStore((s) => s.tasks);
  const streamTick = useStore((s) => Object.values(s.streaming).join("").length);
  const link = useStore((s) => s.link);
  const loaded = useStore((s) => s.conversations !== null);
  const ref = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const [away, setAway] = useState(0);
  const running = tasks.filter((t) => isActive(t) && t.conversation_id === cid);
  const taskOf = (m: Message) => (m.metadata.task_id ? tasks.find((t) => t.id === m.metadata.task_id) : undefined);

  const toBottom = useCallback(() => { const el = ref.current; if (el) el.scrollTop = el.scrollHeight; }, []);
  const onScroll = () => { const el = ref.current!; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM; if (stick.current) setAway(0); };
  useLayoutEffect(() => { stick.current = true; setAway(0); toBottom(); }, [cid, toBottom]); // switching conversation always starts at the latest message
  const count = messages.length + running.length;
  const prev = useRef(count);
  useLayoutEffect(() => {
    if (stick.current) toBottom();
    else if (count > prev.current) setAway((n) => n + (count - prev.current));
    prev.current = count;
  }, [count, streamTick, toBottom]);

  const empty = messages.length === 0 && running.length === 0;
  return (
    <div className="msgs" ref={ref} onScroll={onScroll} role="log" aria-live="polite" aria-relevant="additions" aria-label="Conversation messages" tabIndex={0}>
      {empty && (link !== "live" ? <EmptyState icon={<IconChat size={26} />} title="Backend unreachable">Messages will be available again once the local backend reconnects.</EmptyState>
        : !loaded ? <LoadingState rows={3} />
        : <EmptyState icon={<IconChat size={26} />} title="Start a conversation">Ask a question or give ZONIC a task. Everything it does shows up here and in the Task center.</EmptyState>)}
      {messages.map((m) => <MessageItem key={m.id} m={m} task={taskOf(m)} />)}
      {running.map((t) => <LiveTask key={t.id} task={t} />)}
      {away > 0 && <button type="button" className="btn small primary jump" onClick={() => { stick.current = true; setAway(0); toBottom(); }}>↓ {away} new</button>}
    </div>
  );
}

function VoiceStrip() {
  const voice = useVoice();
  const vs = useStore((s) => s.voice);
  const transcript = useStore((s) => s.transcript);
  if (!voice.active && vs.state !== "error") return null;
  const last = transcript[transcript.length - 1];
  return (
    <div className="voice-strip col" style={{ gap: 6 }}>
      {voice.active && (
        <div className="note row" aria-live="polite"><span className="rec" aria-hidden>●</span><span>Voice: {vs.state}</span><MicMeter />
          <span className="grow muted small goal">{last ? `${last.role === "user" ? "You" : "ZONIC"}: ${last.text}` : vs.detail}</span>
          <Btn small onClick={() => voice.interrupt()} disabled={vs.state !== "speaking"}>Interrupt</Btn></div>
      )}
      {vs.state === "error" && <div className="errnote small" role="alert">{vs.detail}</div>}
    </div>
  );
}

function History({ onPick }: { onPick: () => void }) {
  const list = useStore((s) => s.conversations);
  const cid = useStore((s) => s.conversationId);
  const load = useStore((s) => s.loadConversation);
  const del = useStore((s) => s.deleteConversation);
  const [confirm, setConfirm] = useState<{ id: string; title: string } | null>(null);
  return (
    <div className="history-pop" aria-label="Conversation history">
      {list === null && <LoadingState rows={2} />}
      {list?.length === 0 && <p className="muted small" style={{ padding: 8, margin: 0 }}>No saved conversations. Saving can be changed in Settings → Memory &amp; privacy.</p>}
      {list?.map((c) => (
        <div key={c.id} className="h-item">
          <button type="button" className="pick" aria-current={c.id === cid} onClick={() => { void load(c.id); onPick(); }}><div className="goal">{c.title}</div><div className="small muted">{dateTimeOf(c.updated_at)}</div></button>
          <IconButton label={`Delete conversation ${c.title}`} onClick={() => setConfirm({ id: c.id, title: c.title })}><IconTrash size={15} /></IconButton>
        </div>
      ))}
      {confirm && <Confirm title="Delete this conversation?" danger confirmLabel="Delete" body={<p>“{confirm.title}” and its messages will be removed from this PC.</p>} onCancel={() => setConfirm(null)} onConfirm={() => { const c = confirm; setConfirm(null); void del(c.id); }} />}
    </div>
  );
}

/** ConversationPanel (right column): header, history, transcript, tool activity, composer. Stays mounted across every centre view. */
export function ConversationPanel({ drawer }: { drawer: boolean }) {
  const cid = useStore((s) => s.conversationId);
  const list = useStore((s) => s.conversations);
  const newConvo = useStore((s) => s.newConversation);
  const toggleChat = useStore((s) => s.toggleChat);
  const setDrawer = useStore((s) => s.setDrawer);
  const [hist, setHist] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const title = cid ? list?.find((c) => c.id === cid)?.title ?? "Conversation" : "New conversation";
  return (
    <>
      <div className="chat-head">
        <div className="ttl"><b title={title}>{title}</b><span>Conversation</span></div>
        <IconButton label="New conversation" onClick={() => { newConvo(); setHist(false); input.current?.focus(); }}><IconPlus size={17} /></IconButton>
        <IconButton label="Conversation history" pressed={hist} onClick={() => setHist((v) => !v)}><IconHistory size={17} /></IconButton>
        {drawer ? <IconButton label="Close conversation" onClick={() => setDrawer(null)}><IconClose size={17} /></IconButton>
          : <IconButton label="Collapse conversation panel" onClick={toggleChat}><IconPanel size={17} /></IconButton>}
      </div>
      {hist && <History onPick={() => setHist(false)} />}
      <MessageList />
      <VoiceStrip />
      <Composer inputRef={input} />
    </>
  );
}

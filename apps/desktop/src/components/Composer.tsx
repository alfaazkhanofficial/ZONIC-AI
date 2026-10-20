import { useEffect, useRef, useState } from "react";
import { isActive, useVoice } from "../lib/hooks";
import { audioLevel } from "../lib/voice";
import { useStore } from "../lib/store";
import { IconButton } from "./ui";
import { IconMic, IconSend, IconStop } from "./icons";

export function MicMeter() {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => { let raf = 0; const f = () => { if (ref.current) ref.current.style.width = `${Math.round(audioLevel.mic * 100)}%`; raf = requestAnimationFrame(f); }; raf = requestAnimationFrame(f); return () => cancelAnimationFrame(raf); }, []);
  return <span className="meter" aria-hidden><i ref={ref} style={{ width: 0 }} /></span>;
}

/** MessageComposer: Enter sends, Shift+Enter inserts a newline. Submits through the existing assistant message path (POST /api/chat). */
export function Composer({ onSent, inputRef }: { onSent?: () => void; inputRef?: React.RefObject<HTMLTextAreaElement> }) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const send = useStore((s) => s.send);
  const tasks = useStore((s) => s.tasks);
  const link = useStore((s) => s.link);
  const cancel = useStore((s) => s.cancelTask);
  const voice = useVoice();
  const own = useRef<HTMLTextAreaElement>(null);
  const ta = inputRef ?? own;
  const active = tasks.filter(isActive);
  const offline = link !== "live";
  // grow with content up to the CSS max-height
  useEffect(() => { const el = ta.current; if (!el) return; el.style.height = "auto"; el.style.height = `${Math.min(el.scrollHeight, 160)}px`; }, [text, ta]);
  const submit = async () => {
    const t = text.trim();
    if (!t || sending || offline) return; // the sending guard prevents accidental duplicate submissions
    setSending(true);
    try { await send(t); setText(""); onSent?.(); } finally { setSending(false); ta.current?.focus(); }
  };
  return (
    <div className="composer-wrap">
      <div className="composer" role="group" aria-label="Message composer">
        <textarea ref={ta} aria-label="Message ZONIC" rows={1} value={text} disabled={false}
          placeholder={offline ? "Backend unreachable — reconnecting…" : "Ask ZONIC or give it a task…"}
          onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void submit(); } }} />
        <div className="tools">
          <span className="hint" aria-hidden>{voice.active ? <span className="rec">● Voice on</span> : "Enter to send · Shift+Enter for a new line"}</span>
          {voice.active && <MicMeter />}
          <IconButton label={voice.active ? "Stop voice session" : voice.configured ? "Start voice session (Gemini Live)" : "Voice needs a Gemini API key — see Settings → Voice"} pressed={voice.active} onClick={() => (voice.active ? voice.stop() : void voice.start())}>
            {voice.active ? <IconStop size={17} /> : <IconMic size={17} />}
          </IconButton>
          {active.length > 0 && <IconButton label="Stop the running task" className="on" style={{ color: "var(--danger)" }} onClick={() => void cancel(active[0].id)}><IconStop size={17} /></IconButton>}
          <button type="button" className="send" onClick={() => void submit()} disabled={!text.trim() || sending || offline} title={offline ? "Backend unreachable" : text.trim() ? "Send (Enter)" : "Type a message first"}><IconSend size={15} />Send</button>
        </div>
      </div>
    </div>
  );
}

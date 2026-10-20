import type { Connection } from "./types";

export const EVENT_KINDS = ["task_state", "task_event", "assistant_delta", "message_added", "approval_requested", "approval_resolved", "voice_state", "status_changed", "skills_changed", "audit"] as const;
export interface EventHandlers {
  onOpen(): void;
  onError(): void;
  onResync(): void;
  onEvent(kind: string, data: Record<string, unknown>): void;
}

/** One SSE stream. EventSource reconnects by itself and resends Last-Event-ID, so the backend can replay what we missed. */
export function connectEvents(conn: Connection, h: EventHandlers, ES: typeof EventSource = EventSource): () => void {
  const es = new ES(`${conn.baseUrl}/api/events?token=${encodeURIComponent(conn.token)}`);
  es.onopen = () => h.onOpen();
  es.onerror = () => h.onError();
  es.addEventListener("hello", () => h.onOpen());
  es.addEventListener("resync", () => h.onResync());
  for (const k of EVENT_KINDS) {
    es.addEventListener(k, (ev) => {
      try { h.onEvent(k, JSON.parse((ev as MessageEvent).data)); } catch { /* ignore malformed frame */ }
    });
  }
  return () => es.close();
}

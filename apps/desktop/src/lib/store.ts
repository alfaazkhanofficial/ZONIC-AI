import { create } from "zustand";
import { ApiError, makeApi, type Api } from "./api";
import { connectEvents } from "./events";
import type { Approval, Connection, Conversation, Message, SettingsPayload, Status, Task, VoiceState } from "./types";
import { TERMINAL } from "./types";

export type View = "home" | "tasks" | "memory" | "skills" | "projects" | "permissions" | "activity" | "settings";
export type Drawer = "nav" | "chat" | null;
export type Link = "connecting" | "live" | "reconnecting";
export interface LiveEvent { id: number; kind: string; message: string; ts: string }
export interface Toast { id: number; kind: "info" | "success" | "error"; text: string }

interface State {
  conn: Connection | null;
  api: Api | null;
  link: Link;
  view: View;
  navCollapsed: boolean;
  chatCollapsed: boolean;
  drawer: Drawer;
  settingsTab: string;
  conversations: Conversation[] | null;
  status: Status | null;
  settings: SettingsPayload | null;
  tasks: Task[];
  approvals: Approval[];
  toolCalls: Record<string, number>;
  /** Real task events received over the event stream (bounded), keyed by task id. */
  taskEvents: Record<string, LiveEvent[]>;
  conversationId: string | null;
  messages: Message[];
  streaming: Record<string, string>;
  voice: { state: VoiceState; detail: string | null; code: string | null };
  transcript: { role: "user" | "assistant"; text: string }[];
  toasts: Toast[];
  taskDetail: string | null;
  lastFailureAt: number;
  lastCancelAt: number;
  // actions
  connect(conn: Connection): () => void;
  setView(v: View): void;
  toggleNav(): void;
  toggleChat(): void;
  setDrawer(d: Drawer): void;
  setSettingsTab(t: string): void;
  refreshConversations(): Promise<void>;
  newConversation(): void;
  deleteConversation(id: string): Promise<void>;
  toast(kind: Toast["kind"], text: string): void;
  dismissToast(id: number): void;
  refreshAll(): Promise<void>;
  refreshStatus(): Promise<void>;
  refreshSettings(): Promise<void>;
  refreshTasks(): Promise<void>;
  refreshApprovals(): Promise<void>;
  loadConversation(id: string | null): Promise<void>;
  send(text: string): Promise<void>;
  cancelTask(id: string): Promise<void>;
  decide(id: string, approve: boolean): Promise<void>;
  setVoice(state: VoiceState, detail: string | null, code: string | null): void;
  addTranscript(role: "user" | "assistant", text: string): void;
  openTask(id: string | null): void;
  handleEvent(kind: string, data: Record<string, unknown>): void;
}

let toastSeq = 1;
let tasksTimer: ReturnType<typeof setTimeout> | null = null;
const errText = (e: unknown): string => (e instanceof ApiError ? e.message : e instanceof Error ? e.message : "Something went wrong.");

export const useStore = create<State>((set, get) => ({
  conn: null, api: null, link: "connecting", view: "home", navCollapsed: false, chatCollapsed: false, drawer: null, settingsTab: "model", conversations: null,
  status: null, settings: null, tasks: [], approvals: [], toolCalls: {}, taskEvents: {},
  conversationId: null, messages: [], streaming: {},
  voice: { state: "disconnected", detail: null, code: null }, transcript: [],
  toasts: [], taskDetail: null, lastFailureAt: 0, lastCancelAt: 0,

  connect(conn) {
    const api = makeApi(conn);
    set({ conn, api, link: "connecting" });
    const close = connectEvents(conn, {
      onOpen: () => { if (get().link !== "live") { set({ link: "live" }); void get().refreshAll(); } },
      onError: () => set({ link: "reconnecting" }),
      onResync: () => void get().refreshAll(),
      onEvent: (k, d) => get().handleEvent(k, d),
    });
    void get().refreshAll();
    return close;
  },

  setView: (view) => set({ view, drawer: null }),
  toggleNav: () => set((s) => ({ navCollapsed: !s.navCollapsed })),
  toggleChat: () => set((s) => ({ chatCollapsed: !s.chatCollapsed })),
  setDrawer: (drawer) => set({ drawer }),
  setSettingsTab: (settingsTab) => set({ settingsTab }),
  async refreshConversations() {
    try { set({ conversations: (await get().api!.conversations()).items }); } catch { set((s) => ({ conversations: s.conversations ?? [] })); }
  },
  newConversation: () => { void get().loadConversation(null); },
  async deleteConversation(id) {
    try {
      await get().api!.deleteConversation(id);
      if (get().conversationId === id) await get().loadConversation(null);
      await get().refreshConversations();
    } catch { get().toast("error", "Could not delete the conversation."); }
  },
  toast(kind, text) {
    const id = toastSeq++;
    set((s) => ({ toasts: [...s.toasts.slice(-3), { id, kind, text }] }));
    setTimeout(() => get().dismissToast(id), kind === "error" ? 8000 : 4500);
  },
  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),

  async refreshAll() {
    await Promise.all([get().refreshStatus(), get().refreshSettings(), get().refreshTasks(), get().refreshApprovals(), get().refreshConversations()]);
  },
  async refreshStatus() {
    try { set({ status: await get().api!.status(), link: "live" }); } catch (e) { if (e instanceof ApiError && e.code === "network") set({ link: "reconnecting" }); }
  },
  async refreshSettings() {
    try { set({ settings: await get().api!.settings() }); } catch { /* shown via link state */ }
  },
  async refreshTasks() {
    try {
      const { items } = await get().api!.tasks({ limit: 60 });
      set({ tasks: items });
    } catch { /* ignore */ }
  },
  async refreshApprovals() {
    try { set({ approvals: (await get().api!.approvals()).items }); } catch { /* ignore */ }
  },

  async loadConversation(id) {
    if (!id) { set({ conversationId: null, messages: [], streaming: {} }); return; }
    try { set({ conversationId: id, messages: (await get().api!.messages(id)).items, streaming: {} }); } catch (e) { get().toast("error", errText(e)); }
  },

  async send(text) {
    const api = get().api;
    if (!api || !text.trim()) return;
    try {
      const r = await api.chat(text.trim(), get().conversationId);
      if (get().conversationId !== r.conversation_id) await get().loadConversation(r.conversation_id);
      void get().refreshTasks(); void get().refreshConversations();
    } catch (e) { get().toast("error", errText(e)); }
  },
  async cancelTask(id) {
    try { await get().api!.cancelTask(id); get().toast("info", "Cancellation requested."); } catch (e) { get().toast("error", errText(e)); }
  },
  async decide(id, approve) {
    try { await get().api!.decide(id, approve); } catch (e) { get().toast("error", errText(e)); }
    await Promise.all([get().refreshApprovals(), get().refreshTasks()]);
    if (get().view === "skills") void get().refreshStatus();
  },
  setVoice: (state, detail, code) => set({ voice: { state, detail, code } }),
  addTranscript: (role, text) => set((s) => ({ transcript: [...s.transcript.slice(-5), { role, text }] })),
  openTask: (id) => set({ taskDetail: id }),

  handleEvent(kind, d) {
    const s = get();
    const taskId = d.task_id as string | undefined;
    switch (kind) {
      case "task_state":
      case "task_event": {
        if (kind === "task_event" && d.kind === "tool_call" && taskId) set({ toolCalls: { ...s.toolCalls, [taskId]: (s.toolCalls[taskId] ?? 0) + 1 } });
        if (kind === "task_event" && taskId) {
          const ev: LiveEvent = { id: Number(d.event_id ?? Date.now()), kind: String(d.kind ?? "event"), message: String(d.message ?? ""), ts: String(d.timestamp ?? new Date().toISOString()) };
          const prev = get().taskEvents[taskId] ?? [];
          if (!prev.some((x) => x.id === ev.id)) {
            const next = { ...get().taskEvents, [taskId]: [...prev, ev].slice(-40) };
            const ids = Object.keys(next);
            if (ids.length > 15) delete next[ids[0]]; // keep memory bounded: only the most recent tasks
            set({ taskEvents: next });
          }
        }
        if (kind === "task_state" && (d.state === "failed")) set({ lastFailureAt: Date.now() });
        if (kind === "task_state" && d.state === "cancelled") set({ lastCancelAt: Date.now() });
        if (tasksTimer) clearTimeout(tasksTimer);
        tasksTimer = setTimeout(() => void get().refreshTasks(), 120);
        if (kind === "task_state" && TERMINAL.includes(d.state as never)) void get().refreshStatus();
        break;
      }
      case "assistant_delta":
        if (taskId) set({ streaming: { ...s.streaming, [taskId]: (s.streaming[taskId] ?? "") + String(d.text ?? "") } });
        break;
      case "message_added": {
        const m = d.message as Message;
        if (m.conversation_id !== s.conversationId && s.conversationId !== null) break;
        if (s.conversationId === null && m.role === "user") { set({ conversationId: m.conversation_id }); }
        if (s.messages.some((x) => x.id === m.id)) break;
        const streaming = { ...s.streaming };
        if (m.metadata?.task_id) delete streaming[m.metadata.task_id];
        set({ messages: [...s.messages, m], streaming });
        if (m.role === "assistant") void get().refreshConversations();
        break;
      }
      case "approval_requested":
      case "approval_resolved":
        void get().refreshApprovals(); void get().refreshTasks();
        break;
      case "voice_state":
        set({ voice: { state: d.state as VoiceState, detail: (d.detail as string) ?? null, code: (d.code as string) ?? null } });
        break;
      case "status_changed":
      case "skills_changed":
        void get().refreshStatus(); void get().refreshSettings();
        break;
      default:
        break;
    }
  },
}));

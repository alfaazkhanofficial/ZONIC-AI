import type { ActivityItem, Approval, Conversation, Memory, Message, Onboarding, Project, ReadinessItem, SettingsPayload, SkillRow, Status, Task, TestResult, ToolInfo, Connection } from "./types";

export class ApiError extends Error {
  constructor(public code: string, message: string, public status = 0) { super(message); }
}

export function makeApi(conn: Connection, fetchImpl: typeof fetch = fetch) {
  async function req<T>(method: string, path: string, body?: unknown, params?: Record<string, string | number | boolean | undefined | null>): Promise<T> {
    const qs = params ? "?" + Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "").map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join("&") : "";
    let res: Response;
    try {
      res = await fetchImpl(`${conn.baseUrl}${path}${qs === "?" ? "" : qs}`, {
        method, headers: { "X-Zonic-Token": conn.token, ...(body !== undefined ? { "Content-Type": "application/json" } : {}) }, body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch {
      throw new ApiError("network", "Cannot reach the local ZONIC backend. It may be restarting.");
    }
    const text = await res.text();
    let json: unknown = null;
    try { json = text ? JSON.parse(text) : null; } catch { /* non-JSON error body */ }
    if (!res.ok) {
      const e = (json as { error?: { code?: string; message?: string } } | null)?.error;
      throw new ApiError(e?.code ?? `http_${res.status}`, e?.message ?? `Request failed (HTTP ${res.status}).`, res.status);
    }
    return json as T;
  }
  const get = <T,>(p: string, params?: Record<string, string | number | boolean | undefined | null>) => req<T>("GET", p, undefined, params);
  return {
    status: () => get<Status>("/api/status"),
    readiness: (live = false) => get<{ checked_at: string; items: ReadinessItem[] }>("/api/readiness", { live }),
    chat: (message: string, conversation_id?: string | null) => req<{ task_id: string; conversation_id: string }>("POST", "/api/chat", { message, conversation_id }),
    conversations: () => get<{ items: Conversation[] }>("/api/conversations"),
    messages: (id: string) => get<{ items: Message[] }>(`/api/conversations/${id}/messages`),
    deleteConversation: (id: string) => req<{ deleted: boolean }>("DELETE", `/api/conversations/${id}`),
    clearConversations: () => req<{ cleared: boolean }>("DELETE", "/api/conversations", undefined, { confirm: true }),
    tasks: (p?: { active?: boolean; limit?: number }) => get<{ items: Task[] }>("/api/tasks", p),
    task: (id: string) => get<Task>(`/api/tasks/${id}`),
    cancelTask: (id: string) => req<{ accepted: boolean }>("POST", `/api/tasks/${id}/cancel`),
    approvals: () => get<{ items: Approval[] }>("/api/approvals"),
    decide: (id: string, approve: boolean) => req<{ state: string }>("POST", `/api/approvals/${id}`, { decision: approve ? "approve" : "deny" }),
    memories: (p?: { q?: string; category?: string; approved?: boolean }) => get<{ items: Memory[]; status: Status["memory"] }>("/api/memories", p),
    createMemory: (content: string, category: string) => req<Memory>("POST", "/api/memories", { content, category }),
    patchMemory: (id: string, patch: Partial<Pick<Memory, "content" | "category" | "importance" | "user_approved">>) => req<Memory>("PATCH", `/api/memories/${id}`, patch),
    deleteMemory: (id: string) => req<{ deleted: boolean }>("DELETE", `/api/memories/${id}`),
    clearMemories: () => req<{ deleted: number }>("DELETE", "/api/memories", undefined, { confirm: true }),
    tools: () => get<{ items: ToolInfo[] }>("/api/tools"),
    toggleTool: (name: string, enabled: boolean) => req<{ enabled: boolean }>("PATCH", `/api/tools/${name}`, { enabled }),
    skills: () => get<{ items: SkillRow[] }>("/api/skills"),
    createSkill: (definition: unknown) => req<{ status: string; validation: SkillRow["validation"]; name: string; version: number | null }>("POST", "/api/skills", { definition }),
    requestSkillApproval: (name: string, version: number) => req<{ approval_id: string }>("POST", `/api/skills/${name}/versions/${version}/request-approval`),
    rollbackSkill: (name: string, version: number) => req<{ ok: boolean }>("POST", `/api/skills/${name}/rollback`, { version }),
    deleteSkill: (name: string) => req<{ deleted: boolean }>("DELETE", `/api/skills/${name}`),
    settings: () => get<SettingsPayload>("/api/settings"),
    patchSettings: (group: string, patch: Record<string, unknown>, confirm = false) => req<{ group: string; value: unknown }>("PATCH", "/api/settings", { group, patch, confirm_permission_change: confirm }),
    putSecret: (name: "nvidia_api_key" | "gemini_api_key", value: string) => req<unknown>("PUT", `/api/secrets/${name}`, { value }),
    deleteSecret: (name: "nvidia_api_key" | "gemini_api_key") => req<{ deleted: boolean }>("DELETE", `/api/secrets/${name}`),
    testNemotron: () => req<TestResult>("POST", "/api/providers/nemotron/test"),
    testGemini: () => req<TestResult>("POST", "/api/providers/gemini/test"),
    onboarding: () => get<Onboarding>("/api/onboarding"),
    patchOnboarding: (p: { step?: number; skipped?: string[] }) => req<Onboarding>("PATCH", "/api/onboarding", p),
    completeOnboarding: () => req<Onboarding>("POST", "/api/onboarding/complete"),
    restartOnboarding: () => req<Onboarding>("POST", "/api/onboarding/restart"),
    discovery: (audio_devices: { id: string; label: string }[]) => req<Record<string, unknown>>("POST", "/api/discovery/run", { consent: true, audio_devices }),
    projects: () => get<{ items: Project[] }>("/api/projects"),
    activity: (limit = 100) => get<{ items: ActivityItem[] }>("/api/activity", { limit }),
    logs: (tail = 200) => get<{ lines: string[] }>("/api/logs", { tail }),
  };
}
export type Api = ReturnType<typeof makeApi>;

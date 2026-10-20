export interface Connection { baseUrl: string; token: string; version?: string; platform?: string }
export type ServiceState = "ready" | "not_configured" | "untested" | "error";
export type Readiness = "ready" | "needs_setup" | "limited" | "error";
export type VoiceState = "disconnected" | "connecting" | "listening" | "thinking" | "speaking" | "interrupted" | "error";
export type TaskState = "queued" | "planning" | "running" | "waiting_for_approval" | "verifying" | "completed" | "failed" | "cancelled";
export const TERMINAL: TaskState[] = ["completed", "failed", "cancelled"];

export interface TestResult { ok: boolean; code: string; message: string; latency_ms: number | null; model: string | null; hint: string | null; at: string }
export interface Status {
  checked_at: string; limited_mode: boolean;
  backend: { state: string; version: string; uptime_s: number; detail: string };
  model: { provider: string; model: string; base_url: string; streaming: boolean; configured: boolean; state: ServiceState; detail: string; last_test: TestResult | null };
  voice: { state: ServiceState; detail: string; session_state: VoiceState; model: string; last_test: TestResult | null };
  memory: { enabled: boolean; count: number; pending_review: number; keyword_index: string; semantic_index: { enabled: boolean; embedder: string; indexed: number; note: string } };
  pc_control: { granted: string[]; workspaces: number; tools: Record<string, number> };
  onboarding: Onboarding; active_tasks: number; pending_approvals: number;
  secrets: Record<string, unknown>;
}
export interface Onboarding { step: number; completed: boolean; completed_at: string | null; skipped: string[] }
export interface Task {
  id: string; conversation_id: string | null; goal: string; status: TaskState; created_at: string; updated_at: string; cancel_requested: boolean;
  result: { final?: string; error?: string; error_code?: string; verification?: Verification; steps?: number; tool_calls?: number };
  events?: TaskEvent[];
}
export interface TaskEvent { id: number; kind: string; message: string; timestamp: string; data: Record<string, unknown> }
export interface Verification { status: "verified" | "partial" | "failed" | "not_applicable"; checked: number; failed: string[]; unverified: string[] }
export interface Approval { id: string; task_id: string | null; kind: string; action_summary: string; risk_level: "low" | "medium" | "high"; state: string; created_at: string; payload?: { name?: string; version?: number } }
export interface Message { id: string; conversation_id: string; role: "user" | "assistant"; content: string; created_at: string; metadata: { task_id?: string; verification?: Verification; error?: boolean; voice?: boolean } }
export interface Conversation { id: string; title: string; created_at: string; updated_at: string }
export interface Memory {
  id: string; category: string; content: string; source: string; importance: number; user_approved: boolean; created_at: string; updated_at: string;
  provenance: { source: string; trust: "user_approved" | "unreviewed_candidate"; kind?: string }; score?: number; match?: string[];
}
export interface ToolInfo {
  name: string; version: string; description: string; input_schema: Record<string, unknown>; permission: string | null; risk: "low" | "medium" | "high";
  side_effect: string; timeout_s: number; verification: string; approval: string; status: "available" | "permission_gated" | "unavailable" | "disabled"; reason: string | null; enabled: boolean;
}
export interface SkillRow {
  name: string; version: number; status: string; created_at: string; decided_at: string | null; created_by: string;
  definition: { name: string; description: string; parameters?: Record<string, { type: string }>; steps: { tool: string; args?: Record<string, unknown> }[] };
  validation: { valid: boolean; errors: string[]; warnings: string[]; permissions: string[]; risk: string | null; executed_code: boolean };
}
export interface Workspace { id: string; name: string; path: string }
export interface AppEntry { exe: string; args?: string[]; process_names?: string[]; label?: string }
export interface Settings {
  onboarding: Onboarding;
  interaction: { mode: "voice_and_text" | "text_first" | "voice_first"; reduced_motion: "system" | "on" | "off"; startup_launch: boolean; animation_intensity: number };
  nemotron: { base_url: string; model: string; timeout_s: number; streaming: boolean; temperature: number | null };
  gemini: { model: string; voice_name: string; input_device_id: string; output_device_id: string };
  memory: { enabled: boolean; preferences: boolean; projects: boolean; workflows: boolean; conversation_history: boolean; semantic_index: boolean };
  permissions: Record<PermissionKey, boolean>;
  limits: { max_steps: number; task_timeout_s: number; max_concurrent_tasks: number };
  personalization: { address_as: string; response_style: "concise" | "balanced" | "detailed"; language: string; voice_behavior: string; default_workspace_id: string };
  privacy: { screenshot_retention_hours: number };
  workspaces: { items: Workspace[] };
  app_allowlist: { items: Record<string, AppEntry> };
  discovery: { result: Record<string, unknown> | null; ran_at: string | null };
}
export type PermissionKey = "read_workspace" | "write_workspace" | "launch_apps" | "browser" | "screenshot" | "input_control" | "elevated";
export interface SettingsPayload { settings: Settings; secrets: Record<string, { configured: boolean; source: string | null }>; secret_backend: string }
export interface ReadinessItem { key: string; label: string; state: Readiness; detail: string; action: string | null; step: number | null }
export interface ActivityItem { ts: string; source: "task" | "audit"; kind: string; message: string; task_id: string | null; outcome: unknown }
export interface Project extends Workspace { exists: boolean; entry_count: number; preview: string[] }

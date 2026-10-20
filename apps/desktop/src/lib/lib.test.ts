import { describe, expect, it, vi, beforeEach } from "vitest";
import { ApiError, makeApi } from "./api";
import { deriveAvatarState, PROFILES, type AvatarInput } from "./avatar";
import { elapsed } from "./format";
import { downsample, floatToInt16, int16ToFloat, rms, toLevel } from "./pcm";
import { useStore } from "./store";

const conn = { baseUrl: "http://127.0.0.1:1", token: "tok" };
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status });

describe("api client", () => {
  it("sends the token header and parses JSON", async () => {
    const f = vi.fn(async () => json(200, { ok: 1 }));
    await makeApi(conn, f as never).status();
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://127.0.0.1:1/api/status");
    expect((init.headers as Record<string, string>)["X-Zonic-Token"]).toBe("tok");
  });
  it("encodes params and drops empty ones", async () => {
    const f = vi.fn(async () => json(200, { items: [] }));
    await makeApi(conn, f as never).memories({ q: "a b", category: "" });
    expect((f.mock.calls[0] as unknown as [string])[0]).toBe("http://127.0.0.1:1/api/memories?q=a%20b");
  });
  it("maps backend errors and network failures to ApiError", async () => {
    const bad = makeApi(conn, (async () => json(409, { error: { code: "consent_required", message: "Needs confirmation" } })) as never);
    await expect(bad.patchSettings("permissions", {})).rejects.toMatchObject({ code: "consent_required", message: "Needs confirmation", status: 409 });
    const down = makeApi(conn, (async () => { throw new TypeError("fetch failed"); }) as never);
    await expect(down.status()).rejects.toBeInstanceOf(ApiError);
    await expect(down.status()).rejects.toMatchObject({ code: "network" });
  });
  it("sends the consent flag only when asked", async () => {
    const f = vi.fn(async () => json(200, { group: "permissions", value: {} }));
    await makeApi(conn, f as never).patchSettings("permissions", { browser: true }, true);
    expect(JSON.parse((f.mock.calls[0] as unknown as [string, RequestInit])[1].body as string)).toEqual({ group: "permissions", patch: { browser: true }, confirm_permission_change: true });
  });
});

describe("pcm", () => {
  it("round-trips int16 conversion within quantisation error", () => {
    const f = new Float32Array([0, 0.5, -0.5, 1, -1]);
    const back = int16ToFloat(floatToInt16(f));
    f.forEach((v, i) => expect(Math.abs(back[i] - v)).toBeLessThan(1e-3));
  });
  it("clips out-of-range samples", () => {
    expect(Array.from(floatToInt16(new Float32Array([2, -2])))).toEqual([32767, -32768]);
  });
  it("downsamples 48k -> 16k to a third of the length and preserves a DC level", () => {
    const out = downsample(new Float32Array(4800).fill(0.25), 48000, 16000);
    expect(out.length).toBe(1600);
    expect(out[10]).toBeCloseTo(0.25, 5);
    expect(downsample(new Float32Array(10), 8000, 16000).length).toBe(10);
  });
  it("computes rms/levels", () => {
    expect(rms(new Float32Array(4).fill(0.5))).toBeCloseTo(0.5);
    expect(rms(new Float32Array(0))).toBe(0);
    expect(toLevel(0)).toBe(0);
    expect(toLevel(10)).toBe(1);
  });
});

describe("avatar state derivation (only real state)", () => {
  const base: AvatarInput = { backendReady: true, voice: "disconnected", pendingApprovals: 0, activeTask: null, recentFailure: false };
  it("maps each real condition", () => {
    expect(deriveAvatarState(base)).toBe("idle");
    expect(deriveAvatarState({ ...base, backendReady: false })).toBe("disconnected");
    expect(deriveAvatarState({ ...base, voice: "listening" })).toBe("listening");
    expect(deriveAvatarState({ ...base, voice: "speaking" })).toBe("speaking");
    expect(deriveAvatarState({ ...base, voice: "thinking" })).toBe("thinking");
    expect(deriveAvatarState({ ...base, voice: "error" })).toBe("error");
    expect(deriveAvatarState({ ...base, recentFailure: true })).toBe("error");
    expect(deriveAvatarState({ ...base, activeTask: { state: "planning", toolCalls: 0 } })).toBe("thinking");
    expect(deriveAvatarState({ ...base, activeTask: { state: "running", toolCalls: 0 } })).toBe("thinking");
    expect(deriveAvatarState({ ...base, activeTask: { state: "running", toolCalls: 2 } })).toBe("executing");
  });
  it("shows 'stopped' only after a real cancel and yields to anything more current", () => {
    expect(deriveAvatarState({ ...base, recentCancel: true })).toBe("stopped");
    expect(deriveAvatarState({ ...base, recentCancel: true, voice: "listening" })).toBe("listening");
    expect(deriveAvatarState({ ...base, recentCancel: true, activeTask: { state: "planning", toolCalls: 0 } })).toBe("thinking");
    expect(deriveAvatarState({ ...base, recentCancel: true, backendReady: false })).toBe("disconnected");
  });
  it("approval and disconnect take priority over everything", () => {
    expect(deriveAvatarState({ ...base, pendingApprovals: 1, voice: "speaking", activeTask: { state: "running", toolCalls: 3 } })).toBe("approval");
    expect(deriveAvatarState({ ...base, backendReady: false, pendingApprovals: 1 })).toBe("disconnected");
  });
  it("every state has a label and the required spec names exist", () => {
    expect(Object.values(PROFILES).map((p) => p.label)).toEqual(["Idle", "Listening", "Thinking", "Speaking", "Executing", "Waiting for approval", "Stopped", "Error", "Disconnected"]);
    expect(PROFILES.approval.color).toBe("#F2B84B");
    expect(PROFILES.idle.color).toBe("#258BFF"); // electric blue, per the UI spec palette
  });
});

describe("format", () => {
  it("formats elapsed time", () => {
    expect(elapsed("2026-01-01T00:00:00Z", "2026-01-01T00:00:42Z")).toBe("42s");
    expect(elapsed("2026-01-01T00:00:00Z", "2026-01-01T00:03:05Z")).toBe("3m 5s");
    expect(elapsed("2026-01-01T00:00:00Z", null, Date.parse("2026-01-01T02:10:00Z"))).toBe("2h 10m");
  });
});

describe("store event handling", () => {
  beforeEach(() => {
    useStore.setState({ conversationId: "c1", messages: [], streaming: {}, toolCalls: {}, approvals: [], voice: { state: "disconnected", detail: null, code: null }, api: null });
  });
  const msg = (id: string, task?: string) => ({ id, conversation_id: "c1", role: "assistant", content: "hi", created_at: "t", metadata: task ? { task_id: task } : {} });

  it("accumulates streaming deltas and clears them when the final message arrives", () => {
    const h = useStore.getState().handleEvent;
    h("assistant_delta", { task_id: "t1", text: "Hel" });
    h("assistant_delta", { task_id: "t1", text: "lo" });
    expect(useStore.getState().streaming.t1).toBe("Hello");
    h("message_added", { conversation_id: "c1", message: msg("m1", "t1") });
    expect(useStore.getState().streaming.t1).toBeUndefined();
    expect(useStore.getState().messages).toHaveLength(1);
  });
  it("ignores duplicate and foreign-conversation messages", () => {
    const h = useStore.getState().handleEvent;
    h("message_added", { conversation_id: "c1", message: msg("m1") });
    h("message_added", { conversation_id: "c1", message: msg("m1") });
    h("message_added", { conversation_id: "other", message: { ...msg("m2"), conversation_id: "other" } });
    expect(useStore.getState().messages).toHaveLength(1);
  });
  it("counts tool calls per task and mirrors voice state", () => {
    const h = useStore.getState().handleEvent;
    h("task_event", { task_id: "t1", kind: "tool_call" });
    h("task_event", { task_id: "t1", kind: "tool_call" });
    h("task_event", { task_id: "t1", kind: "tool_result" });
    expect(useStore.getState().toolCalls.t1).toBe(2);
    h("voice_state", { state: "speaking", detail: "Speaking", code: null });
    expect(useStore.getState().voice.state).toBe("speaking");
  });
});

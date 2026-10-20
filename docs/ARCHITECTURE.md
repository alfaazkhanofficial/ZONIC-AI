# Architecture

```
┌──────────────────────── Electron main (apps/desktop/electron) ────────────────────────┐
│ BackendManager: pick port + 192-bit token → spawn backend → poll /health → supervise │
│ security.ts (webPreferences, permission allowlist, navigation lock)  preload.ts (9 fns)│
└───────────────┬────────────────────────────────────────────────┬──────────────────────┘
        contextBridge (IPC, trusted-sender check)                  │ spawn (loopback only, env: token/port/data dir/parent pid)
┌───────────────▼────────────────┐   HTTP + SSE + WebSocket    ┌──▼──────────────────────────────────────────┐
│ React UI (src/)                │◄───────────────────────────►│ FastAPI backend (backend/app)                │
│ zustand store · SSE events     │  X-Zonic-Token (header/query)│ api.py → Services container                  │
│ Avatar (R3F) · views · voice.ts│                              │ agent · tasks · tools · policy · memory · … │
└────────────────────────────────┘                              └───────┬──────────────┬───────────────┬──────┘
                                                                        │ HTTPS (SSE)  │ WSS (Live)    │ SQLite
                                                                  Nemotron 3 Super   Gemini Live     zonic.db
```

## Backend modules
| Module | Responsibility |
|---|---|
| `main.py` | app factory, CORS (dev origins + `null` for file://), request-id, parent-PID watchdog, refuses non-loopback / missing token |
| `services.py` | wires everything; the seam tests use to inject fakes |
| `settings_service.py` | validated settings groups; consent required to widen permissions/workspaces/allowlist |
| `permissions.py` | `PermissionPolicy.decide()` → allow / deny / approval; workspace path guard (resolve + normcase + symlink-safe) |
| `approvals.py` | persisted pending approvals; awaited by the executor; expire on restart |
| `tools/registry.py` | the single execution path: validate → availability → enabled → policy → approval → run (timeout, cancel) → audit |
| `tools/windows.py`, `tools/builtin.py` | tool implementations; adapters (`screen`, `input`, `window`, `open_url`) are injectable |
| `agent.py` | bounded loop, system prompt, loop detection, `verify_outcome()` evidence check, honest note appended by the system |
| `tasks.py` | state machine, event log, cancellation, concurrency, restart recovery |
| `providers/nemotron.py` | OpenAI-compatible adapter: SSE assembly of fragmented tool calls, error mapping, bounded retry, cancel |
| `voice.py` | Gemini Live connector + `VoiceSession` state machine; delegates tool-needing requests to the agent |
| `memory.py` | CRUD, FTS5/LIKE, local vector index, provenance, secret filter |
| `skills.py` | declarative workflows: validate, version, approve, run, roll back |
| `secrets_store.py`, `redaction.py`, `logging_setup.py` | credential vault/fallback, secret masking, JSON logs |

## Task lifecycle
`queued → planning → running ⇄ waiting_for_approval → verifying → completed | failed | cancelled` (transitions enforced; terminal states are final;
tasks left running by a crash are marked failed on restart).

## Verification model
Every state-changing tool returns `Evidence` and a `verified` flag set only by an *independent observation*
(file read-back + SHA-256, directory exists, process present). Dispatch-only actions (open URL, keystrokes, clicks) are
`verified=false` by construction. `verify_outcome()` aggregates → `verified | partial | failed | not_applicable`;
anything but verified appends a system-authored note to the reply.

## Security notes
* Backend binds loopback only; every route but `/health` needs the per-launch token (constant-time compare). The token travels via preload IPC, never disk.
* The token is passed in the WebSocket/SSE URL (browsers cannot set headers there); log redaction masks `token=…` (a real leak found and fixed by the e2e suite).
* CORS allows the Vite dev origins and `null` (file://). The token, not the origin, is the credential.
* Renderer CSP (production): `script-src 'self'`; connect only to `http(s)/ws://127.0.0.1`.

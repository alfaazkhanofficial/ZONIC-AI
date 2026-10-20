# ZONIC M4 — Verification report

**Environment:** Ubuntu 24 container (1 CPU, no GPU, no Windows, no audio hardware), Python 3.12.3, Node 22, Electron 33.2 (real binary under Xvfb, SwiftShader WebGL).
**Not available here:** Windows, NVIDIA/Google API keys or network egress to them, a physical microphone/speaker.
Anything that needed those is **BLOCKED**, not passed. Results below were produced by the final build; counts are from the last full run.

## Automated results
| Suite | Result | What it is |
|---|---|---|
| Backend `pytest` | **87 passed** | policy, tools, agent loop, memory, provider adapter (httpx mock), API, voice state machine, skills, real-process server boot |
| Frontend/Electron `vitest` | **32 passed** | API client, PCM, avatar state derivation, store events, BackendManager lifecycle, security config, launch resolution |
| `tsc` (renderer + Electron + tests) | **clean** | `npm run typecheck` |
| `vite build` | **ok** | production bundle with CSP |
| Real-app e2e `smoke.py` | **68/68** | Electron → backend → UI: onboarding, dashboard, every screen, approvals, restart, orphan check, clean shutdown |
| Real-app e2e `agent_smoke.py` | **26/26** | full agent loop against a local OpenAI-compatible mock (real HTTP + SSE), real tools on the real FS, approvals, cancel, 401/429 |
| Real-app e2e `voice_smoke.py` | **13/13** | Chromium synthetic mic → capture code → WebSocket → backend → scripted Live stand-in → playback; no-mic failure |
| Real-app e2e `ui_smoke.py` | **23/23** | startup failure + Retry, tokens, 3 window sizes, reduced motion, WebGL fallback, resume/re-run setup |

Bugs found **by the real-app tests** (unit tests with fakes missed all of them) and fixed: backend crashed when `pyautogui` called `sys.exit()` on import;
session token leaked into logs through the WebSocket URL; reduced-motion CSS was inverted; overwrite-without-flag asked for approval and hung.

## Acceptance checklist
Legend: **PASS** verified here · **BLOCKED** could not be verified here (reason given) · **FAIL** none.

### A. Build and startup
| Item | Status | Evidence / note |
|---|---|---|
| Clean dependency install | PASS (Linux) · **BLOCKED** (Windows) | fresh venv `pip install` + `npm install` succeeded; `setup.ps1` not run |
| Frontend typecheck | PASS | `npm run typecheck` |
| Frontend production build | PASS | `npm run build` |
| Python 3.12 env documented, backend starts | PASS on 3.12.3 · **BLOCKED** for exactly 3.12.10 | README, `setup.ps1` (requires ≥3.12) |
| Electron launches backend, gets real health | PASS | e2e: app loads only after `/health` answers |
| Backend failure shown accurately and retryable | PASS | `ui_smoke`: crash "code 3" + log tail shown; Retry recovers |
| No orphan backend on exit | PASS | SIGKILL of Electron → backend exits ≤15 s (watchdog); window close → graceful `/api/shutdown` |

### B. Desktop security
| Item | Status | Evidence |
|---|---|---|
| No unrestricted Node in renderer | PASS | unit test + runtime `typeof require/process === 'undefined'` |
| Context isolation | PASS | unit test + above |
| Preload exposes only documented methods | PASS | e2e asserts the exact 9-function key list |
| Secrets never in renderer storage / build output | PASS | `localStorage`/`sessionStorage` empty in e2e; grep of `dist/` and source finds no keys |
| Logs redact secrets | PASS | unit + e2e (log scanned for keys and session token) |

### C. UI / avatar
| Item | Status | Evidence |
|---|---|---|
| Dark teal tokens applied | PASS | computed CSS variables equal the spec values |
| Dashboard adapts to ≥2 sizes | PASS | 1440×900, 1100×700, 960×640: no overflow; right column stacks ≤1180 px |
| 3D avatar, no paid assets | PASS | procedural Three.js, canvas present |
| Avatar state from actual typed state | PASS | `deriveAvatarState` unit tests; e2e: Error after real failure, Listening/Speaking from voice session, approval amber |
| Reduced motion | PASS | frames static + CSS animations off (and on when "off") |
| WebGL failure fallback | PASS | GPU disabled → fallback orb + label, no canvas |
| System Status = real health | PASS | rows come from `/api/status` (config + last real test); e.g. Nemotron "Error: Network error" shown honestly |
| Current Tasks real state, no fake progress | PASS | no progress bar exists; shows state, tool-call count, elapsed |
| Every visible control works or explains why disabled | PASS (scoped) | exercised across e2e; disabled controls carry a reason; **no exhaustive per-control sweep** |

### D. Onboarding
| Item | Status | Evidence |
|---|---|---|
| Welcome + all 10 steps render | PASS | `smoke.py` walks 1→10 |
| Progress survives restart | PASS | hard-kill at step 6 → resumes at step 6 |
| Model test uses real backend adapter | PASS (adapter + failure paths + mock endpoint) · **BLOCKED** (real NVIDIA) | |
| Voice test uses real adapter | PASS for the real `GeminiLiveConnector` code path (no-key + DNS failure classified; frozen build imports SDK) · **BLOCKED** for a successful live session | |
| Skip providers → limited mode | PASS | limited banner; chat fails honestly with `not_configured` |
| Memory choices persist | PASS | toggled in UI → API → survives kill |
| PC permissions enforced in backend | PASS | 409 without consent flag; tools refused without permission; UI toggle cannot bypass |
| Readiness reflects actual checks | PASS | real DB check, key state, last tests, tool availability |
| Resume/re-run from Settings | PASS | prefs kept |

### E. Model / agent runtime
| Item | Status | Evidence |
|---|---|---|
| Nemotron adapter uses verified current provider details | PASS (docs) | endpoint `integrate.api.nvidia.com/v1`, model `nvidia/nemotron-3-super-120b-a12b`, OpenAI-style tools — checked against NVIDIA docs, Oct 2026 |
| Valid configured request reaches provider | **BLOCKED** (NVIDIA) · PASS (local OpenAI-compatible server) | request shape, Bearer header, tools, streaming asserted |
| Invalid credentials → useful error | PASS (mock 401, normalized + hint) · not observed on the real service | |
| Rate limit / timeout / network normalized | PASS | unit (429 Retry-After, 5xx bounded retry, timeout, connect error) + e2e |
| Structured states, bounded loop | PASS | state machine tests; step/time limits; loop detection |
| Tool args schema-validated | PASS | invalid/unknown tool results reach the model |
| Cancellation stops future steps | PASS | UI Stop mid-stream → provider connection closed, no further requests |
| Completion claims checked against evidence | PASS | `verified/partial/failed` + system-authored note |

### F. Voice
| Item | Status | Evidence |
|---|---|---|
| Uses current official integration | PASS (SDK) | `google-genai` `client.aio.live.connect`; types introspected; model id from Google docs. Not exercised against the live service |
| Mic permission/error states | PASS for no-device; permission-denied branch not exercised here | |
| Listening/speaking/interrupted/disconnected accurate | PASS | stand-in session |
| Interrupt/stop | PASS | remaining model audio dropped; session closed |
| Voice failure doesn't disable text | PASS | |
| Real audio round trip | **BLOCKED** | needs credentials + hardware — see `MANUAL_TEST_PLAN.md` |

### G. Memory and tasks
All **PASS**: conversation/task persistence across restart; memory create/search/edit/delete (UI + API); LIKE fallback when FTS5 is unavailable; provenance preserved; task events + final status; secrets refused as memory.

### H. PC control and skills
| Item | Status | Evidence |
|---|---|---|
| Typed tool metadata | PASS | catalog exposes schema, permission, risk, timeout, verification |
| Low-risk approved action on actual **Windows** | **BLOCKED** | verified on Linux only (file ops, real process launch + process-table check) |
| Workspace boundaries | PASS (Linux) · Windows path edge cases **BLOCKED** | `..`, absolute, symlink escapes refused; junctions/8.3/`\\?\`/case need Windows |
| Screenshot/input need permissions | PASS (gating, approvals, bounds, blocked combos, secret-text refusal with injected backends) · real capture/input **BLOCKED** | |
| Destructive/external actions confirm | PASS | overwrite, open URL, mouse, keyboard, skill registration |
| Evidence for consequential actions | PASS | SHA-256 read-back, dir check, process check; dispatch-only flagged *unverified* |
| Skill cannot bypass policy / self-grant | PASS | unknown fields rejected; permissions computed from tools; each step policy-checked |
| No unrestricted generated code | PASS | skills are declarative; no code-skill feature exists |
| Honest failure/uncertainty | PASS | |

### I. Release
| Item | Status |
|---|---|
| Windows packaged app from clean install | **BLOCKED** (PyInstaller freeze verified on Linux: boots, `/health`, SDK import, graceful stop) |
| Installer/uninstaller behaviour | **BLOCKED** |
| README (prereqs, config, run/test, limitations) | PASS |
| No real secrets in source/output | PASS (only obviously fake fixtures in tests) |
| Report distinguishes PASS/FAIL/BLOCKED | PASS |

## What is *not* claimed
That the Windows tools, installer, or either provider work in the wild. Those are implemented against their documented APIs and tested through
injected backends/mocks; the first real run on Windows with real keys is the next step (`docs/MANUAL_TEST_PLAN.md`).

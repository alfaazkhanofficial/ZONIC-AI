# ZONIC M4

A Windows-first personal AI desktop agent: an Electron + React shell with a live 3D avatar, a local Python (FastAPI) backend,
**NVIDIA Nemotron 3 Super** as the reasoning brain, **Gemini Live** for voice, SQLite memory, and a permission-gated set of
computer-control tools. Built from `ZONIC-M4-Spec-Pack-v1.0.0` (all 8 phases). Independent project — nothing shared with STONIC/JARVIS.

> **Read `docs/TEST_REPORT.md` first.** It separates what was verified (PASS), what failed (FAIL) and what could not be verified
> here (BLOCKED — notably: a real Windows run, real NVIDIA/Gemini calls, a physical microphone). Nothing is claimed beyond that evidence.

## What you get
| Area | Delivered |
|---|---|
| Shell | Electron (context isolation, sandbox, no Node in renderer, whitelisted preload bridge, locked navigation, mic-only permission), supervises the backend (health-gated start, bounded auto-restart, graceful stop, orphan watchdog) |
| UI | Three-column command centre (v2): workspace navigation · Home dashboard with AI Core · Conversation Studio on the right, plus Tasks, Memory, Skills & Tools, Projects, Permissions, Activity, Diagnostics, Settings, 10-step onboarding — charcoal/electric-blue/titanium tokens, reduced-motion, WebGL fallback. See `docs/UI_REDESIGN_REPORT.md` |
| Avatar | Procedural Three.js (no paid assets); 8 states derived **only** from real app state (backend link, voice session, task state, pending approvals); mic/speaker amplitude drives the pulse |
| Brain | Nemotron 3 Super through its OpenAI-compatible endpoint: streaming SSE, tool calls, normalized errors, bounded retries, cancellation |
| Agent | Plan → act → observe → verify loop with step/time limits, loop detection, schema-validated tools, approvals, evidence-checked completion claims |
| Voice | Gemini Live via the official `google-genai` SDK; key stays in the backend; renderer only captures/plays PCM; voice delegates real work to the same agent (so it cannot bypass policy) |
| Memory | SQLite + FTS5 keyword search (LIKE fallback) + local similarity index, provenance, candidate review, secret filter, full CRUD/delete-all |
| Tools | files (list/read/write/mkdir), launch allowlisted apps, open URL, screenshot, active window, mouse, keyboard — each with permission group, risk, timeout, verification strategy |
| Skills | Versioned **declarative** workflows over tools; validated before use; user approval required; cannot grant permissions; roll-back |

## Prerequisites (Windows 10/11 x64)
* **Python 3.12** (spec: 3.12.10; verified here on 3.12.3) — `winget install Python.Python.3.12`
* **Node.js 20+ LTS**
* API keys (both optional — the app runs in clearly-labelled *limited mode* without them):
  NVIDIA key from <https://build.nvidia.com>, Gemini key from <https://aistudio.google.com>.

## Run
```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1   # once: venv + pip + npm
powershell -File scripts\dev.ps1                              # starts Vite + Electron (Electron starts the backend)
```
The first launch walks you through onboarding. Keys are entered in the app (Settings → Model / Voice) and stored in
Windows Credential Manager; environment variables `NVIDIA_API_KEY` / `GEMINI_API_KEY` also work and take precedence.

## Test
```powershell
powershell -File scripts\test.ps1      # backend pytest + typecheck + vitest
```
Real-app end-to-end tests (Electron under Xvfb, Linux/CI only): `scripts/e2e-linux.sh` (see `apps/desktop/e2e/`).
Manual Windows checks: `docs/MANUAL_TEST_PLAN.md`.

## Build an installer
```powershell
powershell -File scripts\build-release.ps1   # tests → PyInstaller backend → electron-builder NSIS → apps\desktop\release\
```
The installer is unsigned and was **not built or run on Windows here** (BLOCKED). The PyInstaller freeze was verified on Linux.

## Configuration
| Setting | Default | Where |
|---|---|---|
| Nemotron endpoint / model | `https://integrate.api.nvidia.com/v1` / `nvidia/nemotron-3-super-120b-a12b` | Settings → Model (verified against NVIDIA docs Oct 2026) |
| Gemini Live model | `gemini-3.1-flash-live-preview` | Settings → Voice (preview names change — edit if Google renames it) |
| Data folder | `%APPDATA%\ZONIC M4` (DB, logs, screenshots) | Electron `userData` |
| Backend | `127.0.0.1` random port, per-launch 192-bit token | automatic |

## Safety model in one screen
* Everything is **off by default**; permissions/workspaces/app-allowlist changes need an explicit confirmation and are enforced in the backend, not the UI.
* File access is confined to approved workspace folders (`..`, absolute-path and symlink escapes are rejected).
* Overwriting a file, opening a link, mouse and keyboard actions **always ask first**; the dialog starts focused on *Deny*.
* Tool output (files, memories, window titles) is wrapped as untrusted data; the model is told never to obey it.
* Completion claims are checked against tool evidence; unverified/failed actions are labelled in the reply by the system, not the model.
* Secrets are never logged, never in memory, never returned by the API, never in renderer storage.

## Known limitations (honest list)
* **Not run on Windows.** Windows-specific code (`mss` capture, `pyautogui`, `ctypes` active-window, Credential Manager, path semantics, NSIS installer, PyInstaller on Windows) is reviewed but unexecuted.
* **Not run against NVIDIA or Google.** Provider behaviour is verified against documentation + a local OpenAI-compatible mock (real HTTP/SSE) and a stand-in Live session; no real audio round trip.
* Nemotron 3 Super is **text-only**: screenshots are saved as evidence for you; the agent cannot read pixels. Mouse/keyboard are coordinate-level and unreliable without vision. No UI-Automation tree reader yet.
* Skills are declarative only; generated *code* skills are intentionally not implemented.
* The "semantic" index is a local hashing/lexical approximation behind an `Embedder` interface (swap in a neural embedder later).
* Capture uses `ScriptProcessorNode` (deprecated but dependency-free); use headphones to avoid the assistant hearing itself.
* Elevated/destructive actions are not offered. No auto-update, code signing or default app icon yet.

See `docs/ARCHITECTURE.md` for the module map and data flows.

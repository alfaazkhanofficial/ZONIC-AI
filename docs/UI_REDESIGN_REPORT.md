# ZONIC M4 — UI redesign report (Zonic_M4_UI_Spec_Pack_v2)

Scope: UI redesign + integration only. No second AI engine, task runner, API client or config source was added. **No backend code changed for the redesign** (the only backend edits in this tree are the four supplied repair files: `agent.py`, `chat.py`, `test_agent.py`, `test_chat.py`).

## Layout (panel swap done)
Left = workspace navigation · Centre = active view (Home dashboard by default) · Right = Conversation Studio (history, transcript, tool activity, composer), mounted on **every** view.
- ≥1240 px: labelled nav (252 px, collapsible to an icon rail) + centre + 352 px conversation.
- 900–1239 px: nav becomes a 64 px icon rail, conversation 316 px. Conversation can be collapsed (top-bar button brings it back).
- <900 px: nav and conversation become drawers (top-bar buttons, scrim, Esc closes). The conversation is the same component/state, so nothing is lost.

## Navigation (all real view switches, no dead items)
Home · Tasks · Memory · Skills & Tools · Projects · Permissions · Activity · Diagnostics (opens Settings → Diagnostics) · Settings. Approvals waiting show as a badge on Tasks. Settings renders in the centre; the right panel stays the conversation.

## Home dashboard (all data real)
AI Core (3D core + SVG HUD) with real start/stop voice, interrupt, stop task, reconnect · System status (from `/api/status`) · Active task (state, elapsed, tool-call count, latest real event, cancel; **no percentages**) · Quick actions (voice, new conversation, model connection test, Skills & Tools, Permissions, Activity & logs) · Recent activity (`/api/activity`) · Recent conversations · Capabilities (live `/api/tools` inventory).
Core states: idle, listening, thinking, speaking, executing, approval, **stopped** (only for 15 s after a real cancel event), error, disconnected. Each is derived from backend link / voice session / task state / approvals / failures (`lib/avatar.ts` + `lib/useCoreState.ts`, unit-tested). Animation pauses when the window is hidden or reduced motion is on.

## Feature parity audit (Phase 0 inventory → new location)
| Existing capability | Now |
|---|---|
| Dashboard avatar, status, tasks, activity | Home |
| Conversation view, history list, delete one conversation, new conversation | Right panel (header: New, History with per-item delete + confirm) |
| Composer, Enter/Shift+Enter, mic, stop task | Right panel composer (+ voice strip with meter/interrupt/transcript) |
| Streaming tokens, verification chips, error messages | Right panel transcript |
| Task center + details/timeline/cancel | Tasks |
| Memory center (CRUD, search, review, delete all, settings) | Memory |
| Skills & Tools (toggle tools, skills approve/rollback/delete) | Skills & Tools |
| Projects / workspaces, Permissions, allowlist | Projects, Permissions |
| Activity + redacted backend log + open logs folder | Activity |
| Model/Voice/Personalization/Appearance/Privacy/Limits/Diagnostics, re-run setup | Settings (unchanged forms) |
| 10-step onboarding, approval dialog (focus starts on Deny), toasts, backend-failure screen | unchanged flow, new palette |
Nothing was removed. No new confirmation dialogs were added; the only confirms are the pre-existing ones (delete conversation/memories, permission changes, re-run setup). Protections for destructive actions, secrets and workspace confinement are untouched (they live in the backend).

## Fixes made along the way
- React "unique key" warning in the Tools table (pre-existing, keyless fragment) fixed.
- e2e: updated for new layout/tokens; denied-overwrite now expects task status `failed` (matches the supplied repair files, `test_agent.py:82`); composer Stop is an icon button.

## App icon
`ZONIC_LOGO.png` → `apps/desktop/build/icon.ico` (16–256 px) + `icon.png`; used by the Electron window, the NSIS installer/uninstaller and the packaged exe; `public/zonic-mark.png` is the top-bar mark, `favicon.png` the page icon.

## Verification actually run (Linux container)
| Check | Result |
|---|---|
| Backend `pytest` (repair files applied) | **88 passed** |
| `npm run typecheck` | clean |
| `vitest` | **33 passed** (added: stopped-state rules, palette) |
| `vite build` | ok |
| Real Electron e2e `smoke.py` | **67/67** |
| `ui_smoke.py` (tokens, 3 window sizes, reduced motion, WebGL fallback, resume) | **23/23** |
| `agent_smoke.py` | **26/26** |
| `voice_smoke.py` | **13/13** |
| Real backend + UI in Chromium: chat round-trip, streaming, long transcript, Shift+Enter, active task → cancel → "Stopped", kill backend → "Disconnected" + banner + Reconnect | observed; screenshots in `docs/screenshots/ui-v2/` |
| No console errors in the above flows (excluding the deliberate backend kill) | yes |

## Not verified / limits (honest)
- **Not run on Windows**, so the NSIS installer, the `.ico` in the taskbar and Windows fonts (Segoe UI Variable) are unverified.
- No real NVIDIA/Gemini calls or microphone (mock model + stand-ins only), as before.
- Screen-reader behaviour and keyboard-only flows were designed for (labels, `aria-current`, live regions, focus rings, Esc for drawers) but not tested with a screen reader.
- Contrast was chosen from the spec palette, not measured with a tool.
- Panel-collapse preference is not persisted (no suitable existing preference store).
- The dashboard has no CPU/RAM/latency tiles because the backend doesn't expose them.

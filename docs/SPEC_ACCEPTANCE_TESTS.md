# ZONIC M4 — Acceptance and Verification Checklist

Record each result as PASS, FAIL, or BLOCKED. Include command/output evidence for automated checks and steps for manual checks.

## A. Build and startup
- [ ] Clean dependency install succeeds.
- [ ] Frontend typecheck succeeds.
- [ ] Frontend production build succeeds.
- [ ] Python 3.12.10 environment is documented and backend starts.
- [ ] Electron launches backend and receives a real health response.
- [ ] Backend failure is shown accurately and can be retried.
- [ ] App shutdown does not leave orphan backend processes.

## B. Desktop security
- [ ] Renderer has no unrestricted Node integration.
- [ ] Context isolation is enabled.
- [ ] Preload bridge exposes only documented methods.
- [ ] API secrets never enter renderer localStorage or build output.
- [ ] Logs redact secrets.

## C. UI/avatar
- [ ] Dark teal design tokens are applied consistently.
- [ ] Dashboard layout adapts to at least two window sizes.
- [ ] 3D avatar renders with no paid asset requirement.
- [ ] Avatar state changes from actual typed app state.
- [ ] Reduced-motion mode works.
- [ ] WebGL failure has a useful fallback.
- [ ] System Status shows real health states.
- [ ] Current Tasks shows real task state and no fabricated progress.
- [ ] Every visible control works or clearly explains why disabled.

## D. Onboarding
- [ ] Welcome and all setup steps render.
- [ ] Progress survives app restart.
- [ ] Model connection test uses the real backend adapter.
- [ ] Voice connection test uses the real adapter.
- [ ] Provider setup can be skipped into limited mode.
- [ ] Memory choices persist.
- [ ] PC permissions are enforced in backend.
- [ ] Readiness report reflects actual checks.
- [ ] Setup can be resumed from Settings.

## E. Model/agent runtime
- [ ] Nemotron adapter uses verified current provider details.
- [ ] Valid configured request reaches provider.
- [ ] Invalid credentials show a useful error.
- [ ] Rate limits/timeouts/network failures are normalized.
- [ ] Agent uses structured task states and bounded loop.
- [ ] Tool arguments are schema-validated.
- [ ] Cancellation stops future agent steps.
- [ ] Completion claims are checked against tool evidence.

## F. Voice
- [ ] Gemini Live adapter uses current supported official integration.
- [ ] Microphone permission and error states work.
- [ ] Listening/speaking/interrupted/disconnected states are accurate.
- [ ] User can interrupt/stop.
- [ ] Voice failure does not disable text chat.
- [ ] Real audio round trip is recorded as PASS only if tested with credentials and hardware.

## G. Memory and tasks
- [ ] Conversation/task records persist across restart.
- [ ] Memory can be created, searched, edited, and deleted.
- [ ] Keyword/FTS fallback works if vector service is unavailable.
- [ ] Memory provenance is preserved.
- [ ] Task history includes events and final status.
- [ ] Secrets are not stored as memory.

## H. PC control and skills
- [ ] Tool registry exposes typed metadata.
- [ ] Low-risk approved action works on actual Windows environment.
- [ ] Workspace boundaries are enforced.
- [ ] Screenshot and input tools require correct permissions.
- [ ] Destructive or externally visible actions require confirmation.
- [ ] Every consequential action has suitable verification evidence.
- [ ] Generated skill cannot bypass policy or self-grant permissions.
- [ ] Arbitrary generated code is not executed unrestricted.
- [ ] Failure/uncertainty is reported honestly.

## I. Release
- [ ] Windows packaged app launches from a clean install.
- [ ] Installer/uninstaller behavior is checked.
- [ ] README contains prerequisites, configuration, run/test commands, and limitations.
- [ ] No real secrets are present in source or packaged output.
- [ ] Final report distinguishes PASS, FAIL, and BLOCKED.

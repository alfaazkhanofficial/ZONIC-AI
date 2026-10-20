# Manual test plan — things automation here could not cover (run on Windows 10/11)

Record PASS/FAIL with notes. These are the checklist's BLOCKED items.

## 1. Install & launch
1. `scripts\setup.ps1` completes on a clean machine (Python 3.12.10 + Node LTS).
2. `scripts\dev.ps1` opens the window; the top bar says *Backend ready*; System Status shows Python backend **Ready**.
3. Kill `python.exe` (the backend) in Task Manager → the app shows *restarting*, then recovers. Kill it 4× quickly → the startup screen with **Retry** appears.
4. Close the app → no `python.exe`/`zonic-backend.exe` remains after ~5 s.

## 2. Real providers
1. Settings → Model: paste a valid NVIDIA key → **Test connection** ✓. Paste a bad key → "Credentials rejected" + hint. Disconnect Wi-Fi → "Network error".
2. Chat "hello" → streamed reply. Chat "what files are in my workspace?" with read permission → tool call + listing.
3. Settings → Voice: valid Gemini key → **Test Gemini Live connection** ✓ → Start voice → speak → hear a reply; interrupt mid-sentence; stop. (Record audio quality/latency; use headphones.)
4. Deny Windows microphone permission (Settings → Privacy → Microphone) → Start voice shows the specific permission message; text chat still works.

## 3. Windows tools (grant permissions + a workspace first)
1. "Create notes\todo.txt containing 'buy milk' and read it back" → verified chip. Try a path outside the workspace (`C:\Windows\win.ini`, `..\`, a junction/symlink pointing out, a path with different letter-case, `\\?\` prefix, 8.3 short name) → all refused.
2. "Open Notepad" (allowlist has it by default) → Notepad appears; evidence says process check.
3. "Take a screenshot" → file appears under `%APPDATA%\ZONIC M4\screenshots`; deleted after the retention period.
4. Enable mouse/keyboard: "Open Notepad and type hello" → every step shows an approval; the result says *not independently verified*; `get_active_window` reports the Notepad title. Move the mouse to a screen corner mid-task → automation aborts. Try "press Win+R" → blocked.
5. "Open https://example.com" → approval shows the URL; browser opens.

## 4. Packaging
1. `scripts\build-release.ps1` → installer in `apps\desktop\release\`.
2. Install on a clean VM (no Python/Node) → app launches, onboarding appears, backend starts (frozen exe), no console window flashes.
3. Uninstall → program files removed; confirm what remains in `%APPDATA%\ZONIC M4` (user data is intentionally kept).
4. Check SmartScreen behaviour (unsigned build) and Defender false positives for the PyInstaller exe.

## 5. Visual QA on real hardware
Avatar frame rate on the integrated GPU (Ryzen 5 5500U class) at 100% and 150% display scaling; 1366×768 and 4K; high-contrast mode; screen-reader pass over the dashboard and approval dialog.

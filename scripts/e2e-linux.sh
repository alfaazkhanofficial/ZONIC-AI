#!/usr/bin/env bash
# Real-app end-to-end tests (Electron under Xvfb). For CI/Linux only; on Windows run the app and use docs/MANUAL_TEST_PLAN.md.
# Needs: Xvfb, backend/.venv (or $ZONIC_PYTHON), `npm install` done (electron binary downloaded).
set -euo pipefail
cd "$(dirname "$0")/../apps/desktop"
export ZONIC_PYTHON="${ZONIC_PYTHON:-$(cd ../../backend && pwd)/.venv/bin/python}"
export ZONIC_E2E_SHOTS="${ZONIC_E2E_SHOTS:-$(mktemp -d)}"
npm run build && npm run build:electron
"$ZONIC_PYTHON" e2e/smoke.py
"$ZONIC_PYTHON" e2e/voice_smoke.py

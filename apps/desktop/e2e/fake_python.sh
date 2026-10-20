#!/bin/sh
# Stand-in for ZONIC_PYTHON: ignores "-m app.main" and starts the test-only backend instead.
exec "${REAL_PY:-python3}" "$(dirname "$0")/fake_voice_backend.py"

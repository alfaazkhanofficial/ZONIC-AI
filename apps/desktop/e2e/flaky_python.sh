#!/bin/sh
# Stand-in for ZONIC_PYTHON that crashes on its first launch and works afterwards (tests the Retry path).
if [ ! -f "${FLAKY_MARKER:?}" ]; then touch "$FLAKY_MARKER"; echo "simulated backend crash: address already in use" >&2; exit 3; fi
exec "${REAL_PY:-python3}" -m app.main

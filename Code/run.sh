#!/usr/bin/env bash
# =============================================================================
# FairShare launcher (bash / Git Bash / macOS / Linux)
# -----------------------------------------------------------------------------
# Starts the Flask app with debug mode + the auto-reloader on a free port.
# Port selection lives in main.py's launch block, so this script, run.bat,
# and plain `python main.py` all behave identically.
#
# Usage:
#   ./run.sh               default port 5000, or the first free port
#   ./run.sh 8080          force a specific port (falls back if busy)
#
# Note: any PORT exported by the environment (e.g. an IDE preview agent) is
# ignored here so every launch behaves the same - use the argument form to
# pin a port.
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python >/dev/null 2>&1; then
    echo "ERROR: 'python' not found on PATH." >&2
    exit 1
fi

unset PORT 2>/dev/null || true

# SECRET_KEY is REQUIRED and the app fails closed without it (no public
# fallback). For local development generate a fresh random key per launch
# if the caller did not supply one. A real deployment must export its own.
if [ -z "${SECRET_KEY:-}" ]; then
    export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
    echo "Note: SECRET_KEY was not set - generated a fresh random key for this session."
fi

# Demo accounts (alice/bob/charlie/diana + marketplace data) are OPT-IN so a
# public deployment is never seeded with documented passwords. Local
# development wants them, so default to enabled here; a production deploy
# should NOT set SEED_DEMO_DATA.
if [ -z "${SEED_DEMO_DATA:-}" ]; then
    export SEED_DEMO_DATA=1
fi

echo "Starting FairShare (debug + auto-reloader) - press Ctrl+C to stop."
exec python main.py "$@"

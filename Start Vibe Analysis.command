#!/usr/bin/env bash
# Double-click this file in Finder to launch Vibe Analysis on macOS.
#
# It starts (or restarts) the local recovery service, waits for the server to
# come up on http://127.0.0.1:8900, and opens the research workspace in your
# browser. Everything runs locally against the project virtualenv.
set -u

# Resolve the repo root from this script's own location, so the launcher works
# no matter where the repo is checked out (unlike a hard-coded path).
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT" || exit 1

WATCHDOG="$PROJECT/scripts/analysis_watchdog.sh"
PID_FILE="$PROJECT/.runtime/watchdog.pid"
LOG_DIR="$PROJECT/logs"
HOST="127.0.0.1"
PORT="${VIBE_ANALYSIS_PORT:-8900}"
URL="http://$HOST:$PORT/"

if [ ! -f "$WATCHDOG" ]; then
  echo "The Vibe Analysis watchdog is missing ($WATCHDOG)."
  read -r -p "Press Return to close..." _
  exit 1
fi

# One-time setup guidance if the app was never installed.
if [ ! -x "$PROJECT/.venv/bin/python" ] && [ ! -x "$PROJECT/agent/.venv/bin/python" ]; then
  echo "No virtualenv found. First-time setup (run once in Terminal):"
  echo "  python3 -m venv .venv"
  echo "  ./.venv/bin/python -m pip install -e ."
  echo "  npm --prefix frontend ci && npm --prefix frontend run build"
  read -r -p "Press Return to close..." _
  exit 1
fi

# Warn (but continue) if the frontend has not been built yet.
if [ ! -d "$PROJECT/frontend/dist" ]; then
  echo "[warn] frontend/dist not found - the API will run but the UI may be empty."
  echo "[warn] Build it with: npm --prefix frontend run build"
fi

# Stop a previous watchdog and free the port so this launch owns the server.
if [ -f "$PID_FILE" ]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null)"
  [ -n "$OLD_PID" ] && kill "$OLD_PID" 2>/dev/null
fi
if command -v lsof >/dev/null 2>&1; then
  for pid in $(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null); do
    kill "$pid" 2>/dev/null
  done
fi

echo "Starting Vibe Analysis..."
# Launch the watchdog detached so it survives this launcher exiting.
nohup bash "$WATCHDOG" >/dev/null 2>&1 &

# Wait up to ~120s for the server to report healthy.
for _ in $(seq 1 120); do
  if curl -fsS --max-time 2 "http://$HOST:$PORT/health" >/dev/null 2>&1; then
    echo "Vibe Analysis is ready. Opening the research workspace..."
    open "$URL"
    exit 0
  fi
  sleep 1
done

echo "Vibe Analysis did not start in time. Review $LOG_DIR/server.err.log"
read -r -p "Press Return to close..." _
exit 1

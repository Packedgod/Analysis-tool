#!/usr/bin/env bash
# macOS/Linux recovery service for Vibe Analysis.
#
# Keeps the local API+frontend server alive on port 8900, restarting it if it
# exits. Mirrors scripts/analysis_watchdog.ps1 (the Windows equivalent) but uses
# only POSIX shell + the project virtualenv, so it works from a double-clicked
# "Start Vibe Analysis.command" on a Mac.
set -u

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$PROJECT/.runtime"
LOG_DIR="$PROJECT/logs"
PID_FILE="$RUNTIME_DIR/watchdog.pid"
WEB_STDOUT="$LOG_DIR/server.out.log"
WEB_STDERR="$LOG_DIR/server.err.log"
HOST="127.0.0.1"
PORT="${VIBE_ANALYSIS_PORT:-8900}"

mkdir -p "$RUNTIME_DIR" "$LOG_DIR"
echo $$ > "$PID_FILE"

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >> "$LOG_DIR/watchdog.log"; }

# Resolve a Python that has the app installed: project venv, agent venv, else PATH.
resolve_python() {
  for candidate in "$PROJECT/.venv/bin/python" "$PROJECT/agent/.venv/bin/python"; do
    if [ -x "$candidate" ]; then printf '%s' "$candidate"; return 0; fi
  done
  command -v python3 || command -v python
}
PYTHON="$(resolve_python)"

web_up() { curl -fsS --max-time 3 "http://$HOST:$PORT/health" >/dev/null 2>&1; }

start_web() {
  log "starting server on $HOST:$PORT via $PYTHON"
  # PYTHONPATH=agent makes `import cli` resolve to this repo's copy, matching
  # scripts/dev; prod mode (no --dev) serves the built frontend from frontend/dist.
  ( cd "$PROJECT" && PYTHONPATH="$PROJECT/agent" "$PYTHON" -c \
      'import cli, sys; raise SystemExit(cli.main(sys.argv[1:]))' \
      serve --host "$HOST" --port "$PORT" \
      >> "$WEB_STDOUT" 2>> "$WEB_STDERR" ) &
  echo $!
}

cleanup() {
  log "watchdog stopping"
  [ -n "${WEB_PID:-}" ] && kill "$WEB_PID" 2>/dev/null
  rm -f "$PID_FILE"
  exit 0
}
trap cleanup INT TERM

WEB_PID=""
while true; do
  if ! web_up; then
    if [ -z "$WEB_PID" ] || ! kill -0 "$WEB_PID" 2>/dev/null; then
      WEB_PID="$(start_web)"
      log "server pid $WEB_PID"
    fi
  fi
  sleep 5
done

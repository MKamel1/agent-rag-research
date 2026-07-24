#!/usr/bin/env bash
# scripts/dashboard.sh -- start/stop/status wrapper for the Corpus Dashboard (T-DOC78).
#
# Replaces the old by-hand sequence: a hand-run `nohup python -m app.dashboard.server ...
# --token $(cat .dashboard_token) &`, then managing the PID file by hand. Deliberately no process
# supervisor, no systemd unit, no --restart policy -- the operator starts this on demand, not at
# boot (TEI holds several GB of VRAM; pinning it at boot on a GPU with prior OOM trouble is the
# wrong default). See docs/RUNBOOK.md for the full bring-up sequence this fits into.
#
# Usage: scripts/dashboard.sh {start|stop|status}
# Override defaults via env vars: DASHBOARD_DATA_DIR, DASHBOARD_PORT, DASHBOARD_HOST,
# DASHBOARD_PYTHON (used by this repo's own test run against a scratch data-dir/port so it never
# touches the operator's real corpus).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"  # so `python -m app.dashboard.server` resolves regardless of the caller's cwd

DATA_DIR="${DASHBOARD_DATA_DIR:-$REPO_ROOT/../research-system-rag-data}"
PORT="${DASHBOARD_PORT:-8700}"
HOST="${DASHBOARD_HOST:-0.0.0.0}"
PYTHON="${DASHBOARD_PYTHON:-/home/omar/miniconda3/envs/agent-rag-research/bin/python}"
PIDFILE="$DATA_DIR/dashboard.pid"
LOGFILE="$DATA_DIR/dashboard.log"

# T-DOC78: the real bug this pattern fixes -- a naive `pgrep -f "dashboard"` (or anything else
# loose enough) ALSO matches this very wrapper's own invocation, since its own path
# ("scripts/dashboard.sh") contains that substring too, and `pgrep -f` matches a regex against
# each process's FULL command line, not just the target program's name. Anchored on the actual
# `-m app.dashboard.server` module invocation instead: only the real python server process's argv
# ever contains that exact substring -- `bash scripts/dashboard.sh anything` never does.
SERVER_PATTERN='-m app\.dashboard\.server'

_is_running() {
  [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null
}

start() {
  if _is_running; then
    echo "dashboard: already running (pid $(cat "$PIDFILE"))"
    return 0
  fi
  mkdir -p "$DATA_DIR"
  nohup "$PYTHON" -m app.dashboard.server --data-dir "$DATA_DIR" --port "$PORT" --host "$HOST" \
    >>"$LOGFILE" 2>&1 &
  # T-DOC78: `$!` -- the PID bash itself just assigned the backgrounded job -- is captured
  # directly, never rediscovered via a `pgrep` scan of the process table. This is what actually
  # guarantees "exactly one PID written": there is no search to match more than one process in
  # the first place, so the wrapper-self-match bug (see SERVER_PATTERN comment) can't recur here.
  local pid=$!
  echo "$pid" > "$PIDFILE"
  sleep 1
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "dashboard: failed to start -- check $LOGFILE" >&2
    rm -f "$PIDFILE"
    exit 1
  fi
  echo "dashboard: started (pid $pid) at http://$HOST:$PORT (data_dir=$DATA_DIR)"
  echo "dashboard: token at $DATA_DIR/.dashboard_token (generated on first run if it wasn't there)"
}

stop() {
  if ! _is_running; then
    echo "dashboard: not running"
    rm -f "$PIDFILE"
    return 0
  fi
  local pid
  pid="$(cat "$PIDFILE")"
  kill "$pid"
  for _ in $(seq 1 10); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  if kill -0 "$pid" 2>/dev/null; then
    echo "dashboard: pid $pid didn't exit after 10s, sending SIGKILL" >&2
    kill -9 "$pid"
  fi
  rm -f "$PIDFILE"
  echo "dashboard: stopped"
}

status() {
  if _is_running; then
    echo "dashboard: running (pid $(cat "$PIDFILE")) at http://$HOST:$PORT (data_dir=$DATA_DIR)"
    return 0
  fi
  # No (or a stale) pidfile -- fall back to a live process-table check, in case the server was
  # started by hand outside this script. Same anchored SERVER_PATTERN as above, so this fallback
  # can't fall into the exact bug it exists to avoid.
  # ponytail: reports every matching pid rather than picking one -- a real ambiguity (which one is
  # "the" server?) that this script can observe but shouldn't silently resolve. Upgrade path: if
  # this ever actually fires with >1 pid, investigate instead of teaching the script to guess.
  local found
  found="$(pgrep -f -- "$SERVER_PATTERN" || true)"
  if [[ -n "$found" ]]; then
    echo "dashboard: running, but no/stale pidfile -- found pid(s): $found (not started via this script?)"
    return 0
  fi
  echo "dashboard: not running"
  return 1
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  *)
    echo "usage: $0 {start|stop|status}" >&2
    exit 2
    ;;
esac

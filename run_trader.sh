#!/usr/bin/env bash
# Supervisor for the Kirktron paper trader.
#
# paper_trader.py already swallows transient API errors inside its own loop,
# so this wrapper exists only for genuine crashes (OOM, a kill, an unhandled
# fault). Every restart is stamped into supervisor.log so a run's history is
# never silently interrupted. Portfolio state lives in state_*.json, so a
# restart resumes exactly where it left off.
#
#   ./run_trader.sh            # foreground
#   nohup ./run_trader.sh &    # background
#   touch STOP                 # ask the supervisor to stop after this run

cd "$(dirname "$0")" || exit 1

SUPERVISOR_LOG="supervisor.log"
BACKOFF=5
MAX_BACKOFF=300
restarts=0

stamp() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
note()  { echo "[$(stamp)] $*" | tee -a "$SUPERVISOR_LOG"; }

# Refuse to start a second supervisor. Two of them race on the same state
# files and trade_log.csv, which silently corrupts both portfolios' books.
LOCK="supervisor.pid"
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
    note "supervisor already running (pid $(cat "$LOCK")); refusing to start a second"
    exit 0
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

note "supervisor starting (pid $$)"
trap 'note "supervisor received termination signal; exiting"; kill "$child" 2>/dev/null; exit 0' TERM INT

while true; do
    if [ -f STOP ]; then
        note "STOP file present; supervisor exiting without restarting"
        exit 0
    fi

    note "launching paper_trader.py (restart #$restarts)"
    python3 paper_trader.py &
    child=$!
    wait "$child"
    code=$?

    if [ -f STOP ]; then
        note "trader exited (code $code) and STOP file present; not restarting"
        exit 0
    fi

    if [ "$code" -eq 0 ]; then
        note "trader exited cleanly (code 0); not restarting"
        exit 0
    fi

    restarts=$((restarts + 1))
    note "trader died with code $code; restarting in ${BACKOFF}s (restart #$restarts)"
    sleep "$BACKOFF"
    # Back off on repeated crashes so a persistent fault does not hot-loop.
    BACKOFF=$(( BACKOFF * 2 ))
    [ "$BACKOFF" -gt "$MAX_BACKOFF" ] && BACKOFF=$MAX_BACKOFF
done

#!/usr/bin/env bash
# One command per supervision cycle: trade, record, export, summarise.
#
# The agent supervising this trader costs a conversation turn per action, and
# the old loop spent seven of them every eight minutes -- two trader segments,
# two dashboard exports, a snapshot, a staleness probe, and a re-armed prompt
# carrying every standing finding. None of that was needed on a cycle where
# nothing happened, which is most cycles overnight.
#
# So this does the whole cycle in one call and prints only what could change a
# decision: any trade that opened or closed, the four book values, and the
# health numbers. A quiet cycle prints five lines.
#
# Usage: ./run_headless.sh [seconds]   (default 540; keep it under the 600s
# tool timeout so the snapshot and export still fit in the same call.)

cd "$(dirname "$0")" || exit 1
DURATION="${1:-540}"

# Several supervisors can call this: the self-scheduled loop, the watchdog
# Routine, and the hourly check-in. Two traders on the same books interleave
# their writes to state_<book>.json and trade_log.csv and corrupt both, so
# take an exclusive lock and exit quietly rather than run a second copy.
exec 9>.headless.lock
if ! flock -n 9; then
    echo "another cycle is already running; skipping"
    exit 0
fi

before=$(wc -l < trade_log.csv 2>/dev/null || echo 0)
rm -f STOP

python3 paper_trader.py --duration "$DURATION" --interval 60 >/dev/null 2>&1
rc=$?
[ "$rc" -ne 0 ] && echo "TRADER EXITED $rc -- check trader.log"

./snapshot.sh >/dev/null 2>&1 || echo "SNAPSHOT FAILED"
python3 dashboard_export.py >/dev/null 2>&1 || echo "EXPORT FAILED"

after=$(wc -l < trade_log.csv 2>/dev/null || echo 0)
if [ "$after" -gt "$before" ]; then
    echo "TRADES ($((after - before))):"
    tail -n "$((after - before))" trade_log.csv | cut -d, -f1,2,3,4,5,7,9,10 | sed 's/^/  /'
else
    echo "trades: none"
fi

python3 summarise.py
echo "cycle failures: $(grep -c 'cycle failed' trader.log 2>/dev/null) | tracebacks: $(grep -c Traceback trader.log 2>/dev/null)"

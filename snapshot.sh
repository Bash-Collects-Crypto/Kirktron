#!/usr/bin/env bash
# Commit a snapshot of the live trading record.
#
# This container is ephemeral, so trade_log.csv and the portfolio state files
# are the only durable record of a run. Committing them on a schedule means the
# history survives the container, and the git log doubles as a readable
# performance timeline.

cd "$(dirname "$0")" || exit 1

git add -f trade_log.csv state_*.json exclusions_cache.json 2>/dev/null

if git diff --cached --quiet; then
    echo "snapshot: no changes to commit"
    exit 0
fi

SUMMARY=$(python3 - <<'PY'
import json, os
bits = []
for name in ("conservative", "aggressive"):
    path = "state_%s.json" % name
    if not os.path.exists(path):
        continue
    s = json.load(open(path))
    bits.append("%s: %d open / %d closed / %d moons / realized $%.2f"
                % (name, len(s.get("positions", {})), s.get("trades_closed", 0),
                   s.get("moons", 0), s.get("realized_pnl", 0.0)))
print(" | ".join(bits) if bits else "no state yet")
PY
)

git -c user.name="Claude" -c user.email="noreply@anthropic.com" commit -q -m "Snapshot trading record $(date -u +%Y-%m-%dT%H:%MZ)

${SUMMARY}

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Gojq3bG8ZCZuctb5UA8W6k" || exit 1

echo "snapshot: committed -- ${SUMMARY}"

for i in 1 2 3 4; do
    git push -u origin claude/kirktron-paper-trader-5mnt2m && exit 0
    echo "snapshot: push attempt $i failed, retrying"
    sleep $((2 ** i))
done
echo "snapshot: push failed after 4 attempts (commit is safe locally)"
exit 1

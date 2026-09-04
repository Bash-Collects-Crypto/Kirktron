#!/usr/bin/env bash
# Commit a snapshot of the live trading record to its OWN branch.
#
# The record is the project's real output -- every resolved trade is what the
# pattern models learn from -- and this container is ephemeral, so it has to be
# pushed somewhere durable. But a snapshot every few minutes on the feature
# branch buries the code change under hundreds of data commits and makes the
# pull request unreviewable.
#
# So the data goes to its own branch, written with plumbing against a temporary
# index. Nothing is checked out and the working tree is never touched, which
# matters because the trader may be mid-cycle when this runs.

cd "$(dirname "$0")" || exit 1

DATA_BRANCH="kirktron-trading-data"
FILES=(trade_log.csv state_conservative.json state_aggressive.json
       state_longshort.json state_daytrade.json equity_history.csv
       market_context.csv exclusions_cache.json)

present=()
for f in "${FILES[@]}"; do
    [ -f "$f" ] && present+=("$f")
done
if [ ${#present[@]} -eq 0 ]; then
    echo "snapshot: nothing to record yet"
    exit 0
fi

export GIT_INDEX_FILE="$(pwd)/.git/snapshot-index"
rm -f "$GIT_INDEX_FILE"

parent=$(git rev-parse -q --verify "refs/heads/$DATA_BRANCH")
git add -f -- "${present[@]}" || exit 1
tree=$(git write-tree) || exit 1

# Skip an empty commit when no figure moved since the last snapshot.
if [ -n "$parent" ] && [ "$tree" = "$(git rev-parse "$parent^{tree}")" ]; then
    echo "snapshot: no changes to record"
    rm -f "$GIT_INDEX_FILE"
    exit 0
fi

SUMMARY=$(python3 - <<'PY'
import json, os
bits = []
for name in ("conservative", "aggressive", "longshort", "daytrade"):
    path = "state_%s.json" % name
    if not os.path.exists(path):
        continue
    s = json.load(open(path))
    bits.append("%s %d open/%d closed/%d moons/$%.2f"
                % (name, len(s.get("positions", {})), s.get("trades_closed", 0),
                   s.get("moons", 0), s.get("realized_pnl", 0.0)))
print(" | ".join(bits) if bits else "no state yet")
PY
)

commit=$(printf 'Trading record %s\n\n%s\n' "$(date -u +%Y-%m-%dT%H:%MZ)" "$SUMMARY" \
    | git -c user.name="Claude" -c user.email="noreply@anthropic.com" \
          commit-tree "$tree" ${parent:+-p "$parent"}) || exit 1

git update-ref "refs/heads/$DATA_BRANCH" "$commit"
rm -f "$GIT_INDEX_FILE"
echo "snapshot: recorded -- ${SUMMARY}"

for i in 1 2 3 4; do
    git push -q origin "$DATA_BRANCH" && exit 0
    sleep $((2 ** i))
done
echo "snapshot: push failed after 4 attempts (commit is safe locally)"
exit 1

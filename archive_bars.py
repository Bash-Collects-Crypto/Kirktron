#!/usr/bin/env python3
"""Append the intraday cache's 5-minute bars to a permanent, growing archive.

intraday_cache.json is a rolling 24-hour window: CoinGecko's days=1 endpoint
only returns the last day, so a bar that ages out of that window is gone for
good -- it cannot be refetched at any price. The cache also lives only in the
container, which is ephemeral, so ending a session used to discard every bar
the program had ever paid an API call for.

Snapshotting the cache file itself would work but rewrites 120KB of JSON on
every commit. Bars are immutable once observed, so an append-only CSV keyed on
(coin, timestamp) stores the same information as a small delta each time and
accumulates the multi-regime history the strategy work actually needs.

Reads nothing the trader writes to and writes nothing the trader reads, so it
cannot affect trading behaviour.
"""

import csv
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "intraday_cache.json")
ARCHIVE = os.path.join(HERE, "intraday_bars.csv")
COLUMNS = ["coin", "ts_ms", "price"]


def load_seen(path):
    """Existing (coin, ts_ms) keys, so re-running is idempotent."""
    seen = set()
    if not os.path.exists(path):
        return seen
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            seen.add((row["coin"], row["ts_ms"]))
    return seen


def main():
    if not os.path.exists(CACHE):
        print("archive_bars: no intraday cache yet")
        return
    with open(CACHE) as fh:
        blob = json.load(fh)
    series, times = blob.get("series", {}), blob.get("times", {})

    seen = load_seen(ARCHIVE)
    fresh = []
    for coin, prices in series.items():
        stamps = times.get(coin)
        # Bars cached before timestamps were kept have no wall-clock anchor and
        # cannot be placed on a timeline, so they are not archivable.
        if not stamps or len(stamps) != len(prices):
            continue
        for ts, price in zip(stamps, prices):
            key = (coin, str(int(ts)))
            if key in seen:
                continue
            seen.add(key)
            fresh.append({"coin": coin, "ts_ms": int(ts), "price": price})

    if not fresh:
        print("archive_bars: no new bars")
        return
    fresh.sort(key=lambda r: (r["ts_ms"], r["coin"]))
    new_file = not os.path.exists(ARCHIVE)
    with open(ARCHIVE, "a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        if new_file:
            writer.writeheader()
        writer.writerows(fresh)
    print("archive_bars: +%d bars (%d coins), archive now %d rows"
          % (len(fresh), len({r["coin"] for r in fresh}), len(seen)))


if __name__ == "__main__":
    main()

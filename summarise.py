#!/usr/bin/env python3
"""The smallest status line that can still catch a problem.

Values are marked live each cycle, so the equity curve's last row is the
authoritative mark; the state files carry the counters.
"""

import csv
import json
import os
import time

row = None
with open("equity_history.csv") as fh:
    for row in csv.DictReader(fh):
        pass

parts = []
for book in ("conservative", "longshort", "daytrade", "aggressive"):
    path = "state_%s.json" % book
    state = json.load(open(path)) if os.path.exists(path) else {}
    value = float(row[book]) if row and row.get(book) else 0.0
    parts.append("%s $%.0f (%do/%dc/%dm)" % (
        book[:4], value, len(state.get("positions", {})),
        state.get("trades_closed", 0), state.get("moons", 0)))
print(" | ".join(parts))
print("combined $%s at %s" % (row["combined"], row["timestamp"]) if row
      else "no equity rows")

try:
    cache = json.load(open("intraday_cache.json"))
    stale = sorted((time.time() - v) / 60 for v in cache["stamp"].values())
    print("staleness max %.1fm | coins %d" % (stale[-1], len(stale)))
except (OSError, ValueError, KeyError, IndexError) as exc:
    print("staleness unavailable: %s" % exc)


def funding_line():
    """One line for the funding book, or a reason it is silent."""
    try:
        import funding_book, okx
        state = funding_book.load_state()
        marks = {}
        for coin in state["positions"]:
            try:
                marks[coin] = okx.basis(coin)
            except okx.OKXError:
                pass
        v = funding_book.book_value(state, marks)
        return ("fund $%.0f (%dp/%dc) | funding $%+.4f | fees $%.2f"
                % (v, len(state["positions"]), state["closed"],
                   funding_book.total_funding(state), state["fees_paid"]))
    except Exception as exc:                      # noqa: BLE001
        return "fund: unavailable (%s)" % exc


print(funding_line())

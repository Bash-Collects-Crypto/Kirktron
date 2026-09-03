#!/usr/bin/env python3
"""Export the live trading state as the dashboard's two documents.

Writes dashboard_current.json and dashboard_history.json, which are pushed
into the artifact's database. Kept separate from paper_trader.py so a
dashboard change can never break trading.
"""

import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paper_trader as pt

MAX_POINTS = 400          # one document holds the whole curve; downsample to fit


def build_current():
    rows = pt.read_trade_log()
    try:
        feed = pt.build_price_feed(pt.fetch_markets())
    except Exception:                              # noqa: BLE001
        feed = {}

    books, combined = [], 0.0
    for name in pt.STRATEGIES:
        pf = pt.Portfolio(name)
        pf.pattern.fit(pt.resolved_rows_for(name, rows))
        value = pf.value(feed)
        combined += value
        positions = []
        for symbol, pos in sorted(pf.positions.items()):
            price = feed.get(symbol, {}).get("price") or pos["last_price"]
            positions.append({
                "symbol": symbol,
                "side": pos.get("side", "long"),
                "changePct": round(pf.change_pct(pos, price), 2),
                "value": round(pf.position_value(pos, price), 2),
                "heldHours": round((pt.now_utc() - pt.parse_iso(pos["entry_time"])).total_seconds() / 3600, 1),
                "entry": pos["entry_price"],
                "orphan": symbol not in feed,
            })
        cfg = pf.cfg
        books.append({
            "name": name,
            "value": round(value, 2),
            "startValue": pt.INITIAL_CAPITAL,
            "returnPct": round((value / pt.INITIAL_CAPITAL - 1) * 100, 3),
            "cash": round(pf.cash, 2),
            "cashPct": round(100 * pf.cash / value, 1) if value else 0,
            "realized": round(pf.realized_pnl, 2),
            "opened": pf.trades_opened,
            "closed": pf.trades_closed,
            "wins": pf.wins,
            "winRate": round(100 * pf.wins / pf.trades_closed, 1) if pf.trades_closed else None,
            "moons": pf.moons,
            "moonPct": cfg.get("moon_pct", pt.MOON_THRESHOLD_PCT),
            "canShort": bool(cfg.get("allow_short")),
            "intraday": bool(cfg.get("intraday")),
            "costBps": cfg.get("cost_bps", 0),
            "fees": round(pf.fees_paid, 2),
            "maxPositions": cfg["max_positions"],
            "stopPct": cfg["stop_loss_pct"],
            "targetPct": cfg["take_profit_pct"],
            "maxRank": cfg["max_rank"],
            "positions": positions,
            "pattern": {
                "active": pf.pattern.active,
                "resolved": pf.pattern.resolved,
                "moons": pf.pattern.moons,
                "needResolved": pt.PATTERN_MIN_RESOLVED,
                "needMoons": pt.PATTERN_MIN_MOONS,
                "signals": [{"feature": f, "sd": round(v, 2)} for f, v in pf.pattern.top_signals(3)],
            },
        })

    tape = []
    for r in rows[-14:][::-1]:
        tape.append({
            "ts": r["timestamp"], "book": r["strategy"], "action": r["action"],
            "side": r.get("side", "long"), "symbol": r["symbol"],
            "price": float(r["price"]) if r.get("price") else None,
            "usd": float(r["usd_amount"]) if r.get("usd_amount") else None,
            "reason": r.get("reason", ""),
            "pnl": float(r["pnl"]) if r.get("pnl") else None,
            "pnlPct": float(r["pnl_pct"]) if r.get("pnl_pct") else None,
            "moon": str(r.get("moon", "")).lower() == "true",
        })

    return {
        "updated": pt.iso(),
        "combined": round(combined, 2),
        "combinedStart": pt.INITIAL_CAPITAL * len(pt.STRATEGIES),
        "universeSize": len(pt.EXCLUSIONS.layer1_ids),
        "allowlistEnforced": bool(pt.EXCLUSIONS.layer1_ids),
        "books": books,
        "tape": tape,
    }


def build_history():
    if not os.path.exists(pt.EQUITY_LOG):
        return {"points": [], "series": list(pt.STRATEGIES)}
    with open(pt.EQUITY_LOG) as fh:
        rows = list(csv.DictReader(fh))
    if len(rows) > MAX_POINTS:                     # keep first and last, thin the middle
        step = len(rows) / float(MAX_POINTS)
        rows = [rows[int(i * step)] for i in range(MAX_POINTS - 1)] + [rows[-1]]
    names = list(pt.STRATEGIES)
    points = []
    for r in rows:
        try:
            pt_row = {"t": r["timestamp"], "combined": float(r["combined"])}
            for n in names:                      # a blank means the book did not exist yet
                if r.get(n) not in (None, ""):
                    pt_row[n] = float(r[n])
            points.append(pt_row)
        except (KeyError, ValueError):
            continue
    return {"points": points, "series": names}


if __name__ == "__main__":
    cur, hist = build_current(), build_history()
    json.dump(cur, open("dashboard_current.json", "w"), indent=1)
    json.dump(hist, open("dashboard_history.json", "w"), indent=1)
    print("current: %d books, combined $%.2f, %d tape rows"
          % (len(cur["books"]), cur["combined"], len(cur["tape"])))
    print("history: %d points" % len(hist["points"]))

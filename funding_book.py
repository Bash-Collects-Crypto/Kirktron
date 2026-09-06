"""Funding capture: a fifth book that does not bet on direction.

The four original books are long-biased momentum, and 86 resolved trades put
every one of their per-trade confidence intervals across zero (FINDINGS
2026-09-06 09:40). Their only positive record came from ZEC, whose 18 trades
averaged +3.50% while the other 68 averaged -0.74% -- that is market exposure,
not skill.

This book takes the return from somewhere else. A perpetual future has no expiry,
so it is tethered to spot by a funding payment: when leveraged longs outnumber
shorts, longs pay shorts every 8 hours. Holding spot and shorting the perp
against it in equal size leaves no net exposure to the price -- if the coin
halves, the spot leg loses what the short leg gains -- while the funding accrues
either way. The return is a fee for providing the short side, not a forecast.

Measured on OKX over the 33 days to 2026-09-06, an equal-weight basket of 15
majors paid about +5.1%/year, 13 of 15 positive, BTC positive in 95% of its 8h
periods. That is 0.014%/day. It is small, and it is real, which is the opposite
of what the momentum books have.

Two frictions decide whether any of it survives, so both are modelled rather
than assumed away:

  * Costs. Entering means buying spot and selling the perp; exiting reverses
    both. At OKX taker rates that is about 0.20% for the round trip across both
    legs -- roughly fourteen days of median funding. This is therefore a
    low-turnover strategy by construction, and MIN_HOLD_HOURS enforces it.
  * Basis. The legs are only neutral if entered near parity. The perp has been
    trading about 0.05% under spot, which is 0.05% of entry cost on top of fees.
    Entry checks it and skips anything wide.

Funding can also simply go negative -- TRX averaged -7.76%/year over the same
window -- so a position whose recent funding turns negative is closed.
"""

import csv
import json
import os
import statistics as st
import time

import okx

BOOK = "funding"
INITIAL_CAPITAL = 10_000.0
STATE_PATH = "state_funding.json"
LOG_PATH = "funding_log.csv"

# OKX taker fees, both legs, one side each. Entering pays this twice (spot buy,
# perp sell) and exiting pays it twice more.
FEE_BPS_PER_LEG = 5.0

MAX_POSITIONS = 8
POSITION_PCT = 0.11            # 8 x 11% leaves headroom for basis drift
MIN_SPOT_VOL_USD = 20_000_000  # both legs must be liquid enough to exit
MIN_PERP_VOL_USD = 50_000_000
MAX_ABS_BASIS_PCT = 0.15       # skip anything not near parity at entry
MIN_ANN_FUNDING_PCT = 3.0      # must beat the round trip inside a month
MIN_RECENT_ANN_PCT = 3.0       # and still be paying now, not only historically
MIN_POSITIVE_SHARE = 0.70      # and pay reliably, not on one spike
FUNDING_LOOKBACK = 100         # about 33 days of 8h settles
MIN_HOLD_HOURS = 72            # costs need ~14 days; never churn
EXIT_ANN_FUNDING_PCT = 0.0     # close once recent funding turns negative
EXIT_LOOKBACK = 9              # three days of settles

FIELDS = [
    "timestamp", "action", "coin", "spot_px", "perp_px", "basis_pct",
    "notional_usd", "ann_funding_pct", "positive_share", "funding_earned_usd",
    "fees_usd", "net_usd", "hold_hours", "reason", "book_value",
]


def log(msg):
    print("[%s] %s" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), msg),
          flush=True)


def iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as fh:
            return json.load(fh)
    return {
        "name": BOOK, "cash": INITIAL_CAPITAL, "positions": {},
        "funding_earned": 0.0, "fees_paid": 0.0, "closed": 0, "opened": 0,
        "wins": 0, "started": iso(), "updated": iso(),
    }


def save_state(state):
    state["updated"] = iso()
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh, indent=2)
    os.replace(tmp, STATE_PATH)


def ensure_log():
    if not os.path.exists(LOG_PATH):
        with open(LOG_PATH, "w", newline="") as fh:
            csv.DictWriter(fh, FIELDS).writeheader()


def write_log(row):
    ensure_log()
    with open(LOG_PATH, "a", newline="") as fh:
        csv.DictWriter(fh, FIELDS).writerow(row)


def survey(coins):
    """Funding quality for each coin: annualised mean and how reliably positive.

    A single spike can lift a mean without being repeatable, so the share of
    positive settles is carried alongside it and both have to clear a floor.
    """
    out = []
    for coin in coins:
        inst = "%s-USDT-SWAP" % coin
        try:
            hist = okx.funding_history(inst, FUNDING_LOOKBACK)
        except okx.OKXError as exc:
            log("funding history unavailable for %s: %s" % (coin, exc))
            continue
        if len(hist) < 20:
            continue
        rates = [h["rate"] for h in hist]
        recent = rates[:EXIT_LOOKBACK]
        out.append({
            "coin": coin,
            "ann_pct": okx.annualised(st.mean(rates)),
            "recent_ann_pct": okx.annualised(st.mean(recent)),
            "positive_share": sum(1 for r in rates if r > 0) / len(rates),
            "n": len(rates),
        })
    return sorted(out, key=lambda d: -d["ann_pct"])


def pair_pnl_usd(pos, spot_now, perp_now):
    """Mark-to-market of the two legs together, in dollars.

    Long spot gains (spot_now/spot_entry - 1); the short perp gains the negative
    of (perp_now/perp_entry - 1). Almost all of that cancels, which is the point
    -- what is left is the change in basis between entry and now. A position can
    therefore lose money on price only to the extent the two legs decouple.
    """
    n = pos["notional_usd"]
    spot_leg = (spot_now / pos["spot_px"] - 1.0) * n
    perp_leg = -(perp_now / pos["perp_px"] - 1.0) * n
    return spot_leg + perp_leg


def accrue_funding(pos, rate_now, funding_time):
    """Credit funding for any settlement that has happened since the last mark.

    OKX pays every 8 hours. `fundingTime` is the next settlement, so when it
    moves past what the position last saw, one period has settled and the short
    leg is paid notional * rate. Positive rate means longs pay shorts, which is
    the side this book is on.
    """
    if pos.get("last_funding_time") is None:
        pos["last_funding_time"] = funding_time
        return 0.0
    if funding_time <= pos["last_funding_time"]:
        return 0.0
    periods = 0
    t = pos["last_funding_time"]
    while t < funding_time:
        periods += 1
        t += 8 * 3600 * 1000
    earned = pos["notional_usd"] * rate_now * periods
    pos["last_funding_time"] = funding_time
    pos["funding_earned_usd"] = pos.get("funding_earned_usd", 0.0) + earned
    return earned


def book_value(state, marks):
    """Cash plus each position's notional, accrued funding and basis drift."""
    total = state["cash"]
    for coin, pos in state["positions"].items():
        total += pos["notional_usd"] + pos.get("funding_earned_usd", 0.0)
        m = marks.get(coin)
        if m:
            total += pair_pnl_usd(pos, m["spot"], m["perp"])
    return total


def hours_held(pos):
    opened = time.mktime(time.strptime(pos["opened"], "%Y-%m-%dT%H:%M:%SZ"))
    return (time.time() - opened) / 3600.0


def close_position(state, coin, mark, reason, survey_row):
    pos = state["positions"].pop(coin)
    drift = pair_pnl_usd(pos, mark["spot"], mark["perp"])
    exit_fees = pos["notional_usd"] * 2 * FEE_BPS_PER_LEG / 10_000.0
    funding = pos.get("funding_earned_usd", 0.0)
    net = funding + drift - exit_fees
    state["cash"] += pos["notional_usd"] + net
    state["fees_paid"] += exit_fees
    state["funding_earned"] += funding
    state["closed"] += 1
    if net > 0:
        state["wins"] += 1
    write_log({
        "timestamp": iso(), "action": "CLOSE", "coin": coin,
        "spot_px": "%.8f" % mark["spot"], "perp_px": "%.8f" % mark["perp"],
        "basis_pct": "%.4f" % mark["basis_pct"],
        "notional_usd": "%.2f" % pos["notional_usd"],
        "ann_funding_pct": "%.2f" % (survey_row or {}).get("recent_ann_pct", 0.0),
        "positive_share": "%.3f" % (survey_row or {}).get("positive_share", 0.0),
        "funding_earned_usd": "%.4f" % funding,
        "fees_usd": "%.4f" % (exit_fees + pos.get("entry_fees_usd", 0.0)),
        "net_usd": "%.4f" % net, "hold_hours": "%.2f" % hours_held(pos),
        "reason": reason, "book_value": "%.2f" % state["cash"],
    })
    log("funding: CLOSE %s after %.1fh -- funding $%.2f, basis drift $%+.2f, "
        "fees $%.2f, net $%+.2f (%s)"
        % (coin, hours_held(pos), funding, drift, exit_fees, net, reason))


def open_position(state, coin, mark, row, portfolio_value):
    notional = portfolio_value * POSITION_PCT
    entry_fees = notional * 2 * FEE_BPS_PER_LEG / 10_000.0
    if state["cash"] < notional + entry_fees:
        return False
    state["cash"] -= notional + entry_fees
    state["fees_paid"] += entry_fees
    state["opened"] += 1
    state["positions"][coin] = {
        "coin": coin, "spot_px": mark["spot"], "perp_px": mark["perp"],
        "entry_basis_pct": mark["basis_pct"], "notional_usd": notional,
        "entry_fees_usd": entry_fees, "funding_earned_usd": 0.0,
        "last_funding_time": None, "opened": iso(),
        "entry_ann_pct": row["ann_pct"],
    }
    write_log({
        "timestamp": iso(), "action": "OPEN", "coin": coin,
        "spot_px": "%.8f" % mark["spot"], "perp_px": "%.8f" % mark["perp"],
        "basis_pct": "%.4f" % mark["basis_pct"],
        "notional_usd": "%.2f" % notional,
        "ann_funding_pct": "%.2f" % row["ann_pct"],
        "positive_share": "%.3f" % row["positive_share"],
        "funding_earned_usd": "", "fees_usd": "%.4f" % entry_fees,
        "net_usd": "", "hold_hours": "", "reason":
        "long spot / short perp, funding %.2f%%/yr, %.0f%% of settles positive"
        % (row["ann_pct"], 100 * row["positive_share"]),
        "book_value": "%.2f" % portfolio_value,
    })
    log("funding: OPEN %s $%.0f -- %.2f%%/yr, %.0f%% positive, basis %+.3f%%"
        % (coin, notional, row["ann_pct"], 100 * row["positive_share"],
           mark["basis_pct"]))
    return True


# The candidate pool. Deliberately majors only: the highest funding rates on
# OKX sit on illiquid altcoin perps where the spot leg cannot be exited at the
# marked price, so a rate that looks like 40%/year is really a liquidity
# premium the book would pay on the way out. Same principle as the other books'
# layer-1/blue-chip universe rule.
CANDIDATES = [
    "BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "LTC", "BCH",
    "TRX", "DOT", "NEAR", "ATOM", "UNI", "XLM", "HBAR", "SUI", "APT", "FIL",
]


def cycle():
    """One pass: accrue funding, mark, exit what has turned, enter what pays.

    Raises OKXError up to the caller if the venue is unreachable. The book must
    not trade on stale funding rates -- a rate that has flipped negative while
    the fetch was failing is exactly the case the exit rule exists for.
    """
    state = load_state()
    rows = {r["coin"]: r for r in survey(CANDIDATES)}
    if not rows:
        raise okx.OKXError("no funding data for any candidate")

    marks = {}
    for coin in set(list(state["positions"]) + list(rows)):
        try:
            marks[coin] = okx.basis(coin)
        except okx.OKXError as exc:
            log("funding: no mark for %s: %s" % (coin, exc))

    # Accrue first, so a position that is about to be closed is still paid for
    # the periods it actually held through.
    for coin, pos in state["positions"].items():
        try:
            f = okx.funding_rate("%s-USDT-SWAP" % coin)
        except okx.OKXError:
            continue
        accrue_funding(pos, f["rate"], f["funding_time"])

    value = book_value(state, marks)

    for coin in list(state["positions"]):
        pos = state["positions"][coin]
        mark = marks.get(coin)
        if not mark:
            continue
        row = rows.get(coin)
        held = hours_held(pos)
        if held < MIN_HOLD_HOURS:
            continue
        if row and row["recent_ann_pct"] <= EXIT_ANN_FUNDING_PCT:
            close_position(state, coin, mark, "recent funding %.2f%%/yr"
                           % row["recent_ann_pct"], row)

    open_slots = MAX_POSITIONS - len(state["positions"])
    for row in sorted(rows.values(), key=lambda d: -d["ann_pct"]):
        if open_slots <= 0:
            break
        coin = row["coin"]
        if coin in state["positions"]:
            continue
        if row["ann_pct"] < MIN_ANN_FUNDING_PCT:
            continue
        # Entry screened on the 33-day mean alone let SOL in at 3.97%/yr while
        # its last three days averaged 0.29% -- a decayed rate that the exit
        # rule would close as soon as the minimum hold expired, paying the
        # 0.20% round trip to earn almost nothing. Entry and exit now read the
        # same recent window.
        if row["recent_ann_pct"] < MIN_RECENT_ANN_PCT:
            continue
        if row["positive_share"] < MIN_POSITIVE_SHARE:
            continue
        mark = marks.get(coin)
        if not mark:
            continue
        if abs(mark["basis_pct"]) > MAX_ABS_BASIS_PCT:
            log("funding: skip %s, basis %+.3f%% too wide"
                % (coin, mark["basis_pct"]))
            continue
        if mark["spot_vol_usd"] < MIN_SPOT_VOL_USD:
            continue
        if mark["perp_vol_usd"] < MIN_PERP_VOL_USD:
            continue
        if open_position(state, coin, mark, row, value):
            open_slots -= 1

    save_state(state)
    return state, marks, rows


def report():
    state = load_state()
    marks = {}
    for coin in state["positions"]:
        try:
            marks[coin] = okx.basis(coin)
        except okx.OKXError:
            pass
    value = book_value(state, marks)
    print("=== FUNDING ===")
    print("  value $%.2f  (%+.2f%% vs $%.0f start) | cash $%.2f (%.0f%% of book)"
          % (value, 100 * (value / INITIAL_CAPITAL - 1), INITIAL_CAPITAL,
             state["cash"], 100 * state["cash"] / value if value else 0))
    print("  funding earned $%.2f | fees paid $%.2f | opened %d | closed %d | wins %d"
          % (state["funding_earned"], state["fees_paid"], state["opened"],
             state["closed"], state["wins"]))
    if not state["positions"]:
        print("  no open pairs")
    for coin, pos in sorted(state["positions"].items()):
        m = marks.get(coin)
        drift = pair_pnl_usd(pos, m["spot"], m["perp"]) if m else 0.0
        print("    %-5s $%7.0f  funding $%+6.2f  basis drift $%+6.2f  "
              "held %5.1fh  (entered %.2f%%/yr, basis %+.3f%%)"
              % (coin, pos["notional_usd"], pos.get("funding_earned_usd", 0.0),
                 drift, hours_held(pos), pos["entry_ann_pct"],
                 pos["entry_basis_pct"]))
    return value


if __name__ == "__main__":
    import sys
    if "--report" in sys.argv:
        report()
    else:
        cycle()
        report()

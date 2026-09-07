"""OKX market data: perpetual funding rates, spot and mark prices.

The four original books trade CoinGecko spot and bet on direction. This module
serves a different kind of strategy: funding capture holds spot and shorts the
perpetual against it, so its return comes from the funding payment leveraged
longs make to shorts, not from the price going anywhere.

OKX is the venue because it is the one that answers from here -- Binance returns
451 (restricted location) and Bybit 403 (CloudFront geo-block). Verified
2026-09-06. If OKX starts refusing too, funding capture has no data and the book
must halt rather than trade on stale rates; see fetch_funding_rates().

Python's urllib gets 403 from OKX regardless of the proxy, so every request goes
through curl, which is what the rest of the container uses successfully.
"""

import json
import subprocess
import time

BASE = "https://www.okx.com/api/v5"
TIMEOUT = 20

# Funding settles every 8 hours on OKX, so a rate of r per period annualises at
# r * 3 * 365. Kept as a named constant because getting this factor wrong is the
# easiest way to report a 3x-too-good number.
PERIODS_PER_YEAR = 3 * 365


class OKXError(RuntimeError):
    pass


def _get(path, params=None, attempts=4):
    """GET an OKX endpoint through curl, with backoff on transport failure."""
    url = BASE + path
    if params:
        url += "?" + "&".join("%s=%s" % kv for kv in params.items())
    last = None
    for i in range(attempts):
        try:
            out = subprocess.run(
                ["curl", "-s", "-m", str(TIMEOUT), url],
                capture_output=True, text=True, timeout=TIMEOUT + 10,
            )
            if out.returncode != 0:
                last = "curl exit %d" % out.returncode
            else:
                body = json.loads(out.stdout)
                if body.get("code") == "0":
                    return body["data"]
                last = "okx code %s: %s" % (body.get("code"), body.get("msg"))
        except (json.JSONDecodeError, subprocess.TimeoutExpired, OSError) as exc:
            last = str(exc)
        if i < attempts - 1:
            time.sleep(2 ** i)
    raise OKXError("%s failed after %d attempts: %s" % (path, attempts, last))


def usdt_perps():
    """Live USDT-margined perpetual instrument ids."""
    return [d["instId"] for d in _get("/public/instruments", {"instType": "SWAP"})
            if d["instId"].endswith("-USDT-SWAP") and d.get("state") == "live"]


def funding_rate(inst_id):
    """The current funding rate and when it settles, for one perpetual."""
    d = _get("/public/funding-rate", {"instId": inst_id})[0]
    return {
        "inst_id": inst_id,
        "rate": float(d["fundingRate"]),
        "next_rate": float(d["nextFundingRate"]) if d.get("nextFundingRate") else None,
        "funding_time": int(d["fundingTime"]),
    }


def funding_history(inst_id, limit=100):
    """Settled funding rates, newest first. 100 rows is about 33 days."""
    rows = _get("/public/funding-rate-history",
                {"instId": inst_id, "limit": str(limit)})
    return [{"rate": float(r["fundingRate"]), "time": int(r["fundingTime"])}
            for r in rows]


def _volume_usd(d):
    """24h turnover in dollars, from whichever convention the venue used."""
    v = float(d.get("volCcy24h") or 0.0)
    return v if d.get("instType") == "SPOT" else v * float(d["last"])


def ticker(inst_id):
    """Last, bid and ask for a spot or swap instrument."""
    d = _get("/market/ticker", {"instId": inst_id})[0]
    return {
        "inst_id": inst_id,
        "last": float(d["last"]),
        "bid": float(d["bidPx"]) if d.get("bidPx") else None,
        "ask": float(d["askPx"]) if d.get("askPx") else None,
        # volCcy24h means different things per instrument type, and getting it
        # wrong is silent: for SPOT it is already quote currency (USDT), so it
        # is the dollar figure directly; for SWAP it is base currency (coins),
        # so it needs the price applied. Reading it the same way for both made
        # BTC spot look like $16 trillion a day and BTC perp look like zero.
        "vol_24h_usd": _volume_usd(d),
    }


def basis(coin):
    """Perp mark minus spot, as a fraction of spot.

    A funding-capture position is only market-neutral if the two legs are
    entered near parity. A wide basis at entry is a real cost that funding has
    to earn back, so the strategy checks it rather than assuming it away.
    """
    spot = ticker("%s-USDT" % coin)
    perp = ticker("%s-USDT-SWAP" % coin)
    return {
        "coin": coin,
        "spot": spot["last"],
        "perp": perp["last"],
        "basis_pct": 100.0 * (perp["last"] - spot["last"]) / spot["last"],
        "spot_vol_usd": spot["vol_24h_usd"],
        "perp_vol_usd": perp["vol_24h_usd"],
    }


def annualised(rate_per_period):
    """A per-8h funding rate as an annual percentage."""
    return 100.0 * rate_per_period * PERIODS_PER_YEAR

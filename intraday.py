#!/usr/bin/env python3
"""Five-minute intraday bars and the indicators a day-trading book decides on.

The other books read multi-day momentum from one /coins/markets call. Intraday
signals need per-coin history, which is one call per coin, so this module keeps
a TTL cache and refreshes only a few coins per cycle -- enough to stay current
without spending the free tier's rate limit on a single pass.
"""

import math
import random
import time

import requests

CHART_URL = "https://api.coingecko.com/api/v3/coins/%s/market_chart"
BAR_MINUTES = 5             # what CoinGecko returns for days=1
CACHE_TTL = 300             # a bar's worth: refetching faster buys nothing
REFRESH_BUDGET = 4          # coins refreshed per cycle, round-robin
REQUEST_TIMEOUT = 40

INTRADAY_FEATURES = ["ret_30m", "ret_2h", "ema_spread", "rsi14", "range_pos", "vol_5m"]


def _ema(values, span):
    k = 2.0 / (span + 1.0)
    out = values[0]
    for v in values[1:]:
        out = v * k + out * (1 - k)
    return out


def _rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    gains = losses = 0.0
    for i in range(len(prices) - period, len(prices)):
        d = prices[i] - prices[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    if losses <= 1e-12:
        return 100.0 if gains > 0 else 50.0
    rs = (gains / period) / (losses / period)
    return 100.0 - 100.0 / (1.0 + rs)


def indicators(prices):
    """prices: chronological closes, 5 minutes apart. Returns feature dict."""
    n = len(prices)
    if n < 40:
        return None                       # not enough history to say anything
    last = prices[-1]

    def ret(bars):
        if n <= bars or prices[-1 - bars] <= 0:
            return 0.0
        return (last / prices[-1 - bars] - 1.0) * 100.0

    fast, slow = _ema(prices[-24:], 12), _ema(prices[-72:] if n >= 72 else prices, 36)
    spread = ((fast - slow) / slow * 100.0) if slow > 0 else 0.0

    window = prices[-288:] if n >= 288 else prices
    hi, lo = max(window), min(window)
    range_pos = ((last - lo) / (hi - lo) * 100.0) if hi > lo else 50.0

    rets = [(prices[i] / prices[i - 1] - 1.0) * 100.0
            for i in range(max(1, n - 24), n) if prices[i - 1] > 0]
    if len(rets) > 1:
        m = sum(rets) / len(rets)
        vol = math.sqrt(sum((r - m) ** 2 for r in rets) / len(rets))
    else:
        vol = 0.0

    return {
        "ret_30m": ret(6),
        "ret_2h": ret(24),
        "ema_spread": spread,
        "rsi14": _rsi(prices, 14),
        "range_pos": range_pos,
        "vol_5m": vol,
    }


class IntradayCache:
    """Per-coin 5-minute series, refreshed a few coins at a time."""

    def __init__(self, log=print):
        self.series = {}          # coin id -> list of closes
        self.stamp = {}           # coin id -> unix seconds of last successful fetch
        self.cursor = 0
        self.log = log
        self.last_error = None

    def _fetch(self, coin_id):
        resp = requests.get(
            CHART_URL % coin_id,
            params={"vs_currency": "usd", "days": 1},
            timeout=REQUEST_TIMEOUT,
            headers={"Accept": "application/json", "User-Agent": "kirktron-paper-trader/1.0"},
        )
        if resp.status_code == 429:
            raise RuntimeError("rate limited")
        resp.raise_for_status()
        prices = [p[1] for p in resp.json().get("prices", []) if p and p[1]]
        if len(prices) < 40:
            raise RuntimeError("only %d bars" % len(prices))
        return prices

    def refresh(self, coin_ids, budget=REFRESH_BUDGET):
        """Refresh up to `budget` of the stalest coins, round-robin."""
        if not coin_ids:
            return
        ids = sorted(coin_ids, key=lambda c: self.stamp.get(c, 0.0))
        done = 0
        for coin_id in ids:
            if done >= budget:
                break
            if time.time() - self.stamp.get(coin_id, 0.0) < CACHE_TTL:
                continue          # still fresh; nothing to gain
            try:
                self.series[coin_id] = self._fetch(coin_id)
                self.stamp[coin_id] = time.time()
                done += 1
            except Exception as exc:      # noqa: BLE001
                self.last_error = str(exc)
                self.stamp[coin_id] = time.time() - CACHE_TTL + 60   # retry in a minute
            time.sleep(1.5 + random.uniform(0, 1))

    def features(self, coin_id):
        prices = self.series.get(coin_id)
        return indicators(prices) if prices else None

    def coverage(self, coin_ids):
        fresh = sum(1 for c in coin_ids if self.series.get(c))
        return fresh, len(coin_ids)

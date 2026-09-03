#!/usr/bin/env python3
"""
Kirktron paper trader.

Watches the real crypto market via the CoinGecko public API looking for
consistent positive momentum, and simulates trading it with two
independently-managed $10,000 portfolios:

  conservative -- blue chips only, needs momentum agreement across every
                  timeframe, small positions, tight stop, modest target,
                  keeps a real cash reserve, diversified.
  aggressive   -- broader universe incl. mid caps, enters on short-term
                  momentum, big positions, wide stop, lets winners run.

Meme coins, stablecoins and wrapped/staked derivatives are excluded by
blacklist so we never trade noise or duplicate exposure to one asset.

Every fill is appended to trade_log.csv. Portfolio state is checkpointed to
state_<strategy>.json after each cycle so a crash/restart resumes cleanly.

Usage:
    python3 paper_trader.py            # run forever
    python3 paper_trader.py --report   # print a summary and exit
    python3 paper_trader.py --once     # run a single cycle and exit
"""

import argparse
import csv
import json
import math
import os
import random
import signal
import sys
import time
import traceback
from datetime import datetime, timezone

import requests

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRADE_LOG = os.path.join(BASE_DIR, "trade_log.csv")
RUN_LOG = os.path.join(BASE_DIR, "trader.log")
STATE_FILE = os.path.join(BASE_DIR, "state_{}.json")

# --------------------------------------------------------------------------
# Market data
# --------------------------------------------------------------------------

API_URL = "https://api.coingecko.com/api/v3/coins/markets"
UNIVERSE_DEPTH = 250          # how many coins we pull each cycle
POLL_SECONDS = 300            # 5 minutes between cycles (well inside rate limits)
REQUEST_TIMEOUT = 45
MAX_FETCH_ATTEMPTS = 4

# --------------------------------------------------------------------------
# Exclusions
# --------------------------------------------------------------------------

MEME_COINS = {
    "DOGE", "SHIB", "PEPE", "FLOKI", "BONK", "WIF", "BRETT", "MOG", "TURBO",
    "POPCAT", "MEME", "BABYDOGE", "ELON", "SAMO", "MYRO", "SPX", "GIGA",
    "PNUT", "GOAT", "ACT", "NEIRO", "MEW", "SLERF", "BOME", "TRUMP", "MELANIA",
    "FARTCOIN", "AI16Z", "CHILLGUY", "MOODENG", "PUPS", "DOG", "AIDOGE",
    "LADYS", "WOJAK", "TOSHI", "DEGEN", "HIPPO", "APU", "ANDY", "MUMU",
    "KISHU", "AKITA", "HOGE", "SNEK", "BANANA", "USELESS", "PENGU",
}

STABLECOINS = {
    "USDT", "USDC", "DAI", "BUSD", "TUSD", "FDUSD", "PYUSD", "USDE", "USDD",
    "FRAX", "LUSD", "GUSD", "USDP", "SUSD", "USDS", "USDJ", "EURC", "EURT",
    "EURS", "STEUR", "CRVUSD", "GHO", "MIM", "DOLA", "USR", "RLUSD", "BUIDL",
    "USD1", "USDX", "USDG", "USDF", "USDY", "SUSDE", "SUSDS", "SDAI", "USDL",
    "XAUT", "PAXG",  # metal-backed: same "no trend to trade" problem
}

# Wrapped / liquid-staked / receipt tokens: they track an underlying we may
# already hold, so trading them doubles exposure without diversifying.
WRAPPED_STAKED = {
    "WBTC", "WETH", "STETH", "WSTETH", "WEETH", "RETH", "CBBTC", "CBETH",
    "TBTC", "LBTC", "SOLVBTC", "BSC-USD", "WBETH", "METH", "EZETH", "RSETH",
    "OSETH", "SWETH", "ANKRETH", "SFRXETH", "FRXETH", "MSOL", "JITOSOL",
    "JUPSOL", "BNSOL", "WBNB", "WAVAX", "WMATIC", "WHYPE", "WSOL", "STSOL",
    "BETH", "RENBTC", "HBTC", "BTCB", "WBT", "SAVAX", "STX-STETH", "CLBTC",
    "WSTHYPE", "STHYPE", "XSOLVBTC", "PUMPBTC", "SUSDX", "STBTC",
}

EXCLUDED_SYMBOLS = MEME_COINS | STABLECOINS | WRAPPED_STAKED

# Anything whose name smells like a wrapper/derivative, caught by substring so
# new listings do not need a blacklist edit before they are filtered.
EXCLUDED_NAME_TOKENS = (
    "wrapped", "staked", "liquid staked", "restaked", "bridged",
    "tokenized", "usd coin", "tether", "binance-peg", "peg-",
)

# --------------------------------------------------------------------------
# Strategy configuration
# --------------------------------------------------------------------------

INITIAL_CAPITAL = 10_000.0

# A "moon" is a resolved (closed) trade whose realized gain was >= 50%.
# Starting threshold: high enough that it is a genuinely exceptional outcome
# rather than a lucky take-profit, low enough that the pattern model can
# actually accumulate 4 of them in a reasonable number of trades.
MOON_THRESHOLD_PCT = 50.0

# Pattern model activation gates.
PATTERN_MIN_RESOLVED = 20
PATTERN_MIN_MOONS = 4

FEATURE_NAMES = ["pc_1h", "pc_24h", "pc_7d", "pc_14d", "pc_30d", "vol_mcap", "cap_rank"]

# Features are clipped into a sane band before scoring/logging/pattern fitting.
# Without this a single blown-out number (a fresh listing showing +13,000% over
# 30d) dominates the weighted sum and the pattern model's standardization, and
# we end up buying the top of a parabola instead of a trend.
FEATURE_CLIP = {
    "pc_1h": 10.0, "pc_24h": 25.0, "pc_7d": 40.0, "pc_14d": 60.0,
    "pc_30d": 100.0, "vol_mcap": 60.0, "cap_rank": 100.0,
}


def clip(name, value):
    bound = FEATURE_CLIP.get(name)
    return value if bound is None else max(-bound, min(bound, value))

STRATEGIES = {
    "conservative": {
        # --- universe ---
        "max_rank": 30,
        "min_volume_usd": 50_000_000,
        # --- entry gates: momentum must agree on EVERY timeframe ---
        "gates": {
            "pc_1h": -1.0,     # allow a little intraday noise against us
            "pc_24h": 0.5,
            "pc_7d": 1.0,
            "pc_14d": 2.0,
            "pc_30d": 3.0,
        },
        # Refuse already-vertical moves: we want trends to join, not tops to buy.
        "max_gates": {
            "pc_1h": 8.0, "pc_24h": 15.0, "pc_7d": 35.0,
            "pc_14d": 60.0, "pc_30d": 120.0,
        },
        "min_score": 1.0,
        # --- sizing ---
        "position_pct": 0.10,       # 10% of INITIAL capital per trade
        "max_positions": 6,         # <= 60% deployed
        "min_cash_reserve_pct": 0.25,
        # --- risk ---
        "stop_loss_pct": 3.0,
        "take_profit_pct": 9.0,
        "trail_arm_pct": 5.0,       # once up 5%...
        "trail_giveback_pct": 2.5,  # ...exit if we give back 2.5% from the high
        "max_hold_hours": 168,
        "breakdown_24h": -3.0,      # momentum-breakdown exit
        "breakdown_7d": 0.0,
        "cooldown_hours": 4,
        # --- scoring weights over the feature vector ---
        "weights": {
            "pc_1h": 0.5, "pc_24h": 1.0, "pc_7d": 1.0,
            "pc_14d": 0.6, "pc_30d": 0.4,
        },
    },
    "aggressive": {
        "max_rank": 150,
        "min_volume_usd": 10_000_000,
        "gates": {
            "pc_1h": 0.2,
            "pc_24h": 2.0,
            "pc_7d": 0.0,
        },
        "max_gates": {
            "pc_1h": 12.0, "pc_24h": 35.0, "pc_7d": 70.0,
            "pc_14d": 130.0, "pc_30d": 250.0,
        },
        "min_score": 3.0,
        "position_pct": 0.22,       # 22% of INITIAL capital per trade
        "max_positions": 4,         # <= 88% deployed
        "min_cash_reserve_pct": 0.05,
        "stop_loss_pct": 8.0,
        "take_profit_pct": 22.0,
        "trail_arm_pct": 12.0,
        "trail_giveback_pct": 7.0,
        "max_hold_hours": 96,
        "breakdown_24h": -8.0,
        "breakdown_7d": -12.0,
        "cooldown_hours": 2,
        "weights": {
            "pc_1h": 1.5, "pc_24h": 2.0, "pc_7d": 0.8,
            "pc_14d": 0.2, "pc_30d": 0.1,
        },
    },
}

# How hard the pattern model is allowed to push the entry score around.
PATTERN_MAX_BONUS = 2.5

CSV_HEADER = [
    "timestamp", "strategy", "action", "symbol", "name", "price", "quantity",
    "usd_amount", "reason", "pnl", "pnl_pct", "resolved", "moon",
    "portfolio_value", "cash", "hold_hours", "score", "pattern_bonus",
] + ["f_" + f for f in FEATURE_NAMES]


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def now_utc():
    return datetime.now(timezone.utc)


def iso(dt=None):
    return (dt or now_utc()).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def log(msg):
    line = "[%s] %s" % (iso(), msg)
    print(line, flush=True)
    try:
        with open(RUN_LOG, "a") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def num(x, default=0.0):
    """CoinGecko hands back None for timeframes it has no data for."""
    if x is None:
        return default
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(v) or math.isinf(v) else v


# --------------------------------------------------------------------------
# Market data
# --------------------------------------------------------------------------

def fetch_markets():
    """Pull the top UNIVERSE_DEPTH coins with every momentum window we score on."""
    params = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": UNIVERSE_DEPTH,
        "page": 1,
        "sparkline": "false",
        "price_change_percentage": "1h,24h,7d,14d,30d",
    }
    last_err = None
    for attempt in range(MAX_FETCH_ATTEMPTS):
        try:
            resp = requests.get(
                API_URL, params=params, timeout=REQUEST_TIMEOUT,
                headers={"Accept": "application/json", "User-Agent": "kirktron-paper-trader/1.0"},
            )
            if resp.status_code == 429:
                raise RuntimeError("rate limited (429)")
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list) or not data:
                raise RuntimeError("empty market payload")
            return data
        except Exception as exc:          # noqa: BLE001 - transient network noise
            last_err = exc
            backoff = min(60, (2 ** attempt) * 5) + random.uniform(0, 3)
            log("fetch attempt %d/%d failed (%s); retrying in %.1fs"
                % (attempt + 1, MAX_FETCH_ATTEMPTS, exc, backoff))
            time.sleep(backoff)
    raise RuntimeError("market fetch failed after %d attempts: %s"
                       % (MAX_FETCH_ATTEMPTS, last_err))


def is_tradeable(coin):
    symbol = (coin.get("symbol") or "").upper()
    name = (coin.get("name") or "").lower()
    if not symbol or symbol in EXCLUDED_SYMBOLS:
        return False
    if any(tok in name for tok in EXCLUDED_NAME_TOKENS):
        return False
    if coin.get("market_cap_rank") is None:
        return False
    if not coin.get("current_price"):
        return False
    return True


def build_universe(markets):
    """symbol -> normalized coin record, exclusions already applied."""
    universe = {}
    for coin in markets:
        if not is_tradeable(coin):
            continue
        symbol = coin["symbol"].upper()
        if symbol in universe:            # keep the higher-cap listing
            continue
        mcap = num(coin.get("market_cap"))
        volume = num(coin.get("total_volume"))
        raw = {
            "pc_1h": num(coin.get("price_change_percentage_1h_in_currency")),
            "pc_24h": num(coin.get("price_change_percentage_24h_in_currency")),
            "pc_7d": num(coin.get("price_change_percentage_7d_in_currency")),
            "pc_14d": num(coin.get("price_change_percentage_14d_in_currency")),
            "pc_30d": num(coin.get("price_change_percentage_30d_in_currency")),
            "vol_mcap": (volume / mcap * 100.0) if mcap > 0 else 0.0,
            "cap_rank": 100.0 * (1.0 - min(coin["market_cap_rank"], UNIVERSE_DEPTH) / UNIVERSE_DEPTH),
        }
        universe[symbol] = {
            "symbol": symbol,
            "name": coin.get("name") or symbol,
            "price": num(coin.get("current_price")),
            "rank": int(coin["market_cap_rank"]),
            "market_cap": mcap,
            "volume": volume,
            "raw": raw,
            # Clipped copy is what we score, log and learn from.
            "features": {n: clip(n, v) for n, v in raw.items()},
        }
    return universe


# --------------------------------------------------------------------------
# Pattern model
# --------------------------------------------------------------------------

class PatternModel:
    """Lightweight centroid model over the entry features of resolved trades.

    Once a strategy has >= PATTERN_MIN_RESOLVED closed trades of which
    >= PATTERN_MIN_MOONS were moons, we standardize every resolved trade's
    entry feature vector, take the centroid of the moon group and of the
    non-moon group, and score new candidates by how much closer they sit to
    the moon centroid than to the non-moon one. No sklearn, no fitting loop --
    just "does this setup look like the setups that paid".
    """

    def __init__(self):
        self.active = False
        self.resolved = 0
        self.moons = 0
        self.mean = {}
        self.std = {}
        self.moon_centroid = {}
        self.dud_centroid = {}
        self.separation = {}     # per-feature moon-minus-dud, in std units

    def fit(self, resolved_rows):
        """resolved_rows: list of (features dict, is_moon bool)."""
        self.resolved = len(resolved_rows)
        self.moons = sum(1 for _, m in resolved_rows if m)
        self.active = (self.resolved >= PATTERN_MIN_RESOLVED
                       and self.moons >= PATTERN_MIN_MOONS)
        if not self.active:
            return
        moons = [f for f, m in resolved_rows if m]
        duds = [f for f, m in resolved_rows if not m]
        if not moons or not duds:
            self.active = False
            return
        for name in FEATURE_NAMES:
            vals = [f.get(name, 0.0) for f, _ in resolved_rows]
            mean = sum(vals) / len(vals)
            var = sum((v - mean) ** 2 for v in vals) / len(vals)
            self.mean[name] = mean
            self.std[name] = math.sqrt(var) if var > 1e-9 else 1.0
            self.moon_centroid[name] = self._z(name, moons)
            self.dud_centroid[name] = self._z(name, duds)
            self.separation[name] = self.moon_centroid[name] - self.dud_centroid[name]

    def _z(self, name, group):
        vals = [(f.get(name, 0.0) - self.mean[name]) / self.std[name] for f in group]
        return sum(vals) / len(vals)

    def bonus(self, features):
        """Score adjustment in the same units as the base entry score."""
        if not self.active:
            return 0.0
        vec = {n: (features.get(n, 0.0) - self.mean[n]) / self.std[n] for n in FEATURE_NAMES}
        d_moon = math.sqrt(sum((vec[n] - self.moon_centroid[n]) ** 2 for n in FEATURE_NAMES))
        d_dud = math.sqrt(sum((vec[n] - self.dud_centroid[n]) ** 2 for n in FEATURE_NAMES))
        total = d_moon + d_dud
        if total < 1e-9:
            return 0.0
        # (d_dud - d_moon)/total lives in [-1, 1]: +1 = sits exactly on the
        # moon centroid, -1 = exactly on the non-moon centroid.
        return PATTERN_MAX_BONUS * ((d_dud - d_moon) / total)

    def top_signals(self, k=3):
        if not self.active:
            return []
        ranked = sorted(self.separation.items(), key=lambda kv: -abs(kv[1]))
        return ranked[:k]

    def describe(self):
        if not self.active:
            return ("inactive (%d/%d resolved, %d/%d moons)"
                    % (self.resolved, PATTERN_MIN_RESOLVED, self.moons, PATTERN_MIN_MOONS))
        bits = ", ".join("%s %+.2fsd" % (n, v) for n, v in self.top_signals())
        return ("ACTIVE on %d resolved / %d moons; moon setups differ most by: %s"
                % (self.resolved, self.moons, bits))


# --------------------------------------------------------------------------
# Trade log
# --------------------------------------------------------------------------

def ensure_trade_log():
    if not os.path.exists(TRADE_LOG):
        with open(TRADE_LOG, "w", newline="") as fh:
            csv.writer(fh).writerow(CSV_HEADER)


def append_trade(row):
    ensure_trade_log()
    with open(TRADE_LOG, "a", newline="") as fh:
        csv.writer(fh).writerow([row.get(col, "") for col in CSV_HEADER])


def read_trade_log():
    if not os.path.exists(TRADE_LOG):
        return []
    with open(TRADE_LOG, newline="") as fh:
        return list(csv.DictReader(fh))


def resolved_rows_for(strategy, rows=None):
    """Entry-feature vectors of every closed trade, tagged moon / not moon."""
    out = []
    for row in (rows if rows is not None else read_trade_log()):
        if row.get("strategy") != strategy or row.get("action") != "SELL":
            continue
        if str(row.get("resolved", "")).lower() not in ("true", "1"):
            continue
        feats = {}
        for name in FEATURE_NAMES:
            try:
                feats[name] = float(row.get("f_" + name) or 0.0)
            except ValueError:
                feats[name] = 0.0
        out.append((feats, str(row.get("moon", "")).lower() in ("true", "1")))
    return out


# --------------------------------------------------------------------------
# Portfolio
# --------------------------------------------------------------------------

class Portfolio:
    def __init__(self, name):
        self.name = name
        self.cfg = STRATEGIES[name]
        self.cash = INITIAL_CAPITAL
        self.positions = {}       # symbol -> dict
        self.cooldowns = {}       # symbol -> iso timestamp tradeable again
        self.realized_pnl = 0.0
        self.trades_opened = 0
        self.trades_closed = 0
        self.moons = 0
        self.wins = 0
        self.started = iso()
        self.pattern = PatternModel()
        self.load()

    # ---- persistence -----------------------------------------------------

    @property
    def state_path(self):
        return STATE_FILE.format(self.name)

    def save(self):
        state = {
            "name": self.name, "cash": self.cash, "positions": self.positions,
            "cooldowns": self.cooldowns, "realized_pnl": self.realized_pnl,
            "trades_opened": self.trades_opened, "trades_closed": self.trades_closed,
            "moons": self.moons, "wins": self.wins, "started": self.started,
            "updated": iso(),
        }
        tmp = self.state_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(state, fh, indent=2)
        os.replace(tmp, self.state_path)     # atomic: a crash mid-write cannot corrupt state

    def load(self):
        if not os.path.exists(self.state_path):
            return
        try:
            with open(self.state_path) as fh:
                state = json.load(fh)
        except (OSError, ValueError) as exc:
            log("%s: could not read state (%s); starting fresh" % (self.name, exc))
            return
        self.cash = float(state.get("cash", INITIAL_CAPITAL))
        self.positions = state.get("positions", {})
        self.cooldowns = state.get("cooldowns", {})
        self.realized_pnl = float(state.get("realized_pnl", 0.0))
        self.trades_opened = int(state.get("trades_opened", 0))
        self.trades_closed = int(state.get("trades_closed", 0))
        self.moons = int(state.get("moons", 0))
        self.wins = int(state.get("wins", 0))
        self.started = state.get("started", self.started)
        log("%s: resumed -- cash $%.2f, %d open position(s), %d closed trade(s)"
            % (self.name, self.cash, len(self.positions), self.trades_closed))

    # ---- valuation -------------------------------------------------------

    def value(self, universe):
        total = self.cash
        for symbol, pos in self.positions.items():
            price = universe.get(symbol, {}).get("price") or pos["last_price"]
            total += pos["quantity"] * price
        return total

    # ---- scoring ---------------------------------------------------------

    def base_score(self, features):
        return sum(w * features.get(name, 0.0)
                   for name, w in self.cfg["weights"].items())

    def passes_gates(self, coin):
        cfg = self.cfg
        if coin["rank"] > cfg["max_rank"]:
            return False
        if coin["volume"] < cfg["min_volume_usd"]:
            return False
        raw = coin["raw"]
        for name, floor in cfg["gates"].items():
            if raw.get(name, 0.0) < floor:
                return False
        for name, ceiling in cfg.get("max_gates", {}).items():
            if raw.get(name, 0.0) > ceiling:
                return False   # already parabolic -- no edge left, huge reversal risk
        return True

    def on_cooldown(self, symbol):
        until = self.cooldowns.get(symbol)
        if not until:
            return False
        if now_utc() >= parse_iso(until):
            self.cooldowns.pop(symbol, None)
            return False
        return True

    # ---- trading ---------------------------------------------------------

    def open_position(self, coin, score, bonus, portfolio_value):
        cfg = self.cfg
        target_usd = INITIAL_CAPITAL * cfg["position_pct"]
        reserve = portfolio_value * cfg["min_cash_reserve_pct"]
        spendable = self.cash - reserve
        usd = min(target_usd, spendable)
        if usd < 50:
            return False
        price = coin["price"]
        qty = usd / price
        self.cash -= usd
        self.positions[coin["symbol"]] = {
            "symbol": coin["symbol"],
            "name": coin["name"],
            "quantity": qty,
            "entry_price": price,
            "entry_time": iso(),
            "high_price": price,
            "last_price": price,
            "entry_features": coin["features"],
            "entry_score": score,
            "pattern_bonus": bonus,
        }
        self.trades_opened += 1
        reason = "momentum entry (score %.2f%s)" % (
            score, ", pattern %+.2f" % bonus if abs(bonus) > 1e-9 else "")
        append_trade({
            "timestamp": iso(), "strategy": self.name, "action": "BUY",
            "symbol": coin["symbol"], "name": coin["name"], "price": "%.8f" % price,
            "quantity": "%.8f" % qty, "usd_amount": "%.2f" % usd, "reason": reason,
            "pnl": "", "pnl_pct": "", "resolved": "False", "moon": "False",
            "portfolio_value": "%.2f" % portfolio_value, "cash": "%.2f" % self.cash,
            "hold_hours": "", "score": "%.3f" % score, "pattern_bonus": "%.3f" % bonus,
            **{"f_" + n: "%.4f" % coin["features"][n] for n in FEATURE_NAMES},
        })
        log("%s BUY %s @ $%.6f  $%.2f (score %.2f, pattern %+.2f)"
            % (self.name, coin["symbol"], price, usd, score, bonus))
        return True

    def close_position(self, symbol, price, reason, universe):
        pos = self.positions.pop(symbol)
        proceeds = pos["quantity"] * price
        cost = pos["quantity"] * pos["entry_price"]
        pnl = proceeds - cost
        pnl_pct = (price / pos["entry_price"] - 1.0) * 100.0
        moon = pnl_pct >= MOON_THRESHOLD_PCT
        hold_hours = (now_utc() - parse_iso(pos["entry_time"])).total_seconds() / 3600.0

        self.cash += proceeds
        self.realized_pnl += pnl
        self.trades_closed += 1
        if pnl > 0:
            self.wins += 1
        if moon:
            self.moons += 1
        self.cooldowns[symbol] = iso(
            datetime.fromtimestamp(time.time() + self.cfg["cooldown_hours"] * 3600, timezone.utc))

        portfolio_value = self.value(universe)
        append_trade({
            "timestamp": iso(), "strategy": self.name, "action": "SELL",
            "symbol": symbol, "name": pos["name"], "price": "%.8f" % price,
            "quantity": "%.8f" % pos["quantity"], "usd_amount": "%.2f" % proceeds,
            "reason": reason, "pnl": "%.2f" % pnl, "pnl_pct": "%.3f" % pnl_pct,
            "resolved": "True", "moon": str(moon),
            "portfolio_value": "%.2f" % portfolio_value, "cash": "%.2f" % self.cash,
            "hold_hours": "%.2f" % hold_hours,
            "score": "%.3f" % pos.get("entry_score", 0.0),
            "pattern_bonus": "%.3f" % pos.get("pattern_bonus", 0.0),
            # the SELL row carries the ENTRY features -- that is the vector the
            # pattern model learns from, paired with the outcome it produced.
            **{"f_" + n: "%.4f" % pos["entry_features"].get(n, 0.0) for n in FEATURE_NAMES},
        })
        log("%s SELL %s @ $%.6f  pnl $%.2f (%+.2f%%) [%s]%s"
            % (self.name, symbol, price, pnl, pnl_pct, reason, "  *** MOON ***" if moon else ""))

    def exit_reason(self, pos, coin):
        """Return a reason string if this position should be closed now."""
        cfg = self.cfg
        price = coin["price"] if coin else pos["last_price"]
        change = (price / pos["entry_price"] - 1.0) * 100.0
        peak = (pos["high_price"] / pos["entry_price"] - 1.0) * 100.0
        drawdown = (price / pos["high_price"] - 1.0) * 100.0

        if change <= -cfg["stop_loss_pct"]:
            return "stop-loss %.2f%%" % change
        if change >= cfg["take_profit_pct"]:
            return "take-profit %.2f%%" % change
        if peak >= cfg["trail_arm_pct"] and drawdown <= -cfg["trail_giveback_pct"]:
            return "trailing stop (peak %+.2f%%, now %+.2f%%)" % (peak, change)
        hold_hours = (now_utc() - parse_iso(pos["entry_time"])).total_seconds() / 3600.0
        if hold_hours >= cfg["max_hold_hours"]:
            return "max hold %.0fh (%+.2f%%)" % (hold_hours, change)
        if coin:
            feats = coin["features"]
            if (feats["pc_24h"] <= cfg["breakdown_24h"]
                    and feats["pc_7d"] <= cfg["breakdown_7d"]):
                return "momentum breakdown (24h %+.2f%%, 7d %+.2f%%)" % (
                    feats["pc_24h"], feats["pc_7d"])
        return None

    # ---- one cycle -------------------------------------------------------

    def step(self, universe, log_rows):
        self.pattern.fit(resolved_rows_for(self.name, log_rows))

        # 1. mark to market and handle exits
        for symbol in list(self.positions):
            pos = self.positions[symbol]
            coin = universe.get(symbol)
            if coin:
                pos["last_price"] = coin["price"]
                pos["high_price"] = max(pos["high_price"], coin["price"])
            else:
                log("%s: %s missing from market feed this cycle; holding"
                    % (self.name, symbol))
            reason = self.exit_reason(pos, coin)
            if reason:
                self.close_position(symbol, pos["last_price"], reason, universe)

        # 2. look for entries
        portfolio_value = self.value(universe)
        candidates = []
        for symbol, coin in universe.items():
            if symbol in self.positions or self.on_cooldown(symbol):
                continue
            if not self.passes_gates(coin):
                continue
            base = self.base_score(coin["features"])
            bonus = self.pattern.bonus(coin["features"])
            total = base + bonus
            if total < self.cfg["min_score"]:
                continue
            candidates.append((total, base, bonus, coin))
        candidates.sort(key=lambda c: -c[0])

        for total, _base, bonus, coin in candidates:
            if len(self.positions) >= self.cfg["max_positions"]:
                break
            reserve = portfolio_value * self.cfg["min_cash_reserve_pct"]
            if self.cash - reserve < INITIAL_CAPITAL * self.cfg["position_pct"] * 0.5:
                break
            if self.open_position(coin, total, bonus, portfolio_value):
                portfolio_value = self.value(universe)

        self.save()
        return portfolio_value

    # ---- reporting -------------------------------------------------------

    def summary(self, universe=None, log_rows=None):
        self.pattern.fit(resolved_rows_for(self.name, log_rows))
        value = self.value(universe or {})
        lines = []
        lines.append("=== %s ===" % self.name.upper())
        lines.append("  value $%.2f  (%+.2f%% vs $%.0f start) | cash $%.2f (%.0f%% of book)"
                     % (value, (value / INITIAL_CAPITAL - 1) * 100, INITIAL_CAPITAL,
                        self.cash, 100 * self.cash / value if value else 0))
        lines.append("  realized P/L $%.2f | opened %d | closed %d | wins %d (%s) | moons %d"
                     % (self.realized_pnl, self.trades_opened, self.trades_closed,
                        self.wins,
                        "%.0f%%" % (100 * self.wins / self.trades_closed) if self.trades_closed else "n/a",
                        self.moons))
        lines.append("  pattern model: %s" % self.pattern.describe())
        if self.positions:
            lines.append("  open positions:")
            for symbol, pos in sorted(self.positions.items()):
                price = (universe or {}).get(symbol, {}).get("price") or pos["last_price"]
                change = (price / pos["entry_price"] - 1) * 100
                held = (now_utc() - parse_iso(pos["entry_time"])).total_seconds() / 3600
                lines.append("    %-8s %+7.2f%%  $%8.2f  held %5.1fh  (entry $%.6f)"
                             % (symbol, change, pos["quantity"] * price, held, pos["entry_price"]))
        else:
            lines.append("  open positions: none")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------

_stop = False


def _handle_signal(signum, _frame):
    global _stop
    _stop = True
    log("received signal %d; shutting down after this cycle" % signum)


def run_cycle(portfolios):
    markets = fetch_markets()
    universe = build_universe(markets)
    log_rows = read_trade_log()
    log("cycle: %d coins fetched, %d tradeable after exclusions"
        % (len(markets), len(universe)))
    for pf in portfolios:
        value = pf.step(universe, log_rows)
        log("  %-12s value $%.2f | cash $%.2f | %d open | %d closed | %d moons"
            % (pf.name, value, pf.cash, len(pf.positions), pf.trades_closed, pf.moons))
    return universe


def report():
    ensure_trade_log()
    rows = read_trade_log()
    portfolios = [Portfolio(n) for n in STRATEGIES]
    universe = {}
    try:
        universe = build_universe(fetch_markets())
    except Exception as exc:                      # noqa: BLE001
        print("(live prices unavailable: %s -- using last known marks)" % exc)
    print("KIRKTRON PAPER TRADER -- %s" % iso())
    print("combined value $%.2f" % sum(p.value(universe) for p in portfolios))
    for pf in portfolios:
        print(pf.summary(universe, rows))
    recent = [r for r in rows if r.get("action") == "SELL"][-10:]
    if recent:
        print("\nlast %d resolved trades:" % len(recent))
        for r in recent:
            print("  %s %-12s %-6s %+8s%%  %s"
                  % (r["timestamp"], r["strategy"], r["symbol"],
                     r.get("pnl_pct", "?"), r.get("reason", "")))


def main():
    parser = argparse.ArgumentParser(description="Kirktron paper trader")
    parser.add_argument("--report", action="store_true", help="print a summary and exit")
    parser.add_argument("--once", action="store_true", help="run a single cycle and exit")
    parser.add_argument("--interval", type=int, default=POLL_SECONDS,
                        help="seconds between cycles (default %d)" % POLL_SECONDS)
    args = parser.parse_args()

    ensure_trade_log()

    if args.report:
        report()
        return 0

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    portfolios = [Portfolio(name) for name in STRATEGIES]
    log("starting: %s | poll %ds | universe top %d | moon >= %.0f%%"
        % (", ".join(p.name for p in portfolios), args.interval,
           UNIVERSE_DEPTH, MOON_THRESHOLD_PCT))

    consecutive_failures = 0
    while not _stop:
        try:
            run_cycle(portfolios)
            consecutive_failures = 0
        except Exception as exc:                  # noqa: BLE001
            # A bad cycle must never kill the process: log it, back off, retry.
            consecutive_failures += 1
            log("cycle failed (%d in a row): %s" % (consecutive_failures, exc))
            log(traceback.format_exc().strip())
            if consecutive_failures >= 10:
                log("10 consecutive cycle failures; exiting so the supervisor restarts us")
                return 1
        if args.once:
            break
        for _ in range(args.interval):
            if _stop:
                break
            time.sleep(1)
    log("stopped cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())

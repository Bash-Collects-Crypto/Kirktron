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
EQUITY_LOG = os.path.join(BASE_DIR, "equity_history.csv")
RUN_LOG = os.path.join(BASE_DIR, "trader.log")
STATE_FILE = os.path.join(BASE_DIR, "state_{}.json")

# --------------------------------------------------------------------------
# Market data
# --------------------------------------------------------------------------

API_URL = "https://api.coingecko.com/api/v3/coins/markets"
UNIVERSE_DEPTH = 250          # how many coins we pull each cycle
POLL_SECONDS = 60             # live-ish: one market refresh a minute
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

# A hand-maintained blacklist does not scale -- new memes list constantly and
# symbols collide (CoinGecko's meme category alone carries two different
# "DOGE"s). So the static sets above are only a floor: the real filter is
# CoinGecko's own categorization, pulled live and cached. This is what catches
# things the static list missed, e.g. AI (a meme token that showed +13,315%
# over 30d), PUMP, M, CASHCAT.
# "Crypto" here means layer-1 chains and blue chips -- not DeFi tokens, gaming
# tokens, exchange tokens or long-tail alts. A coin qualifies if CoinGecko
# classes it as a layer-1, or if it is a top-rank asset by market cap.
INCLUDED_CATEGORIES = ("layer-1",)
BLUE_CHIP_MAX_RANK = 25

EXCLUDED_CATEGORIES = (
    "meme-token",
    "stablecoins",
    "liquid-staking-tokens",
    "wrapped-tokens",
)
CATEGORY_URL = "https://api.coingecko.com/api/v3/coins/markets"
EXCLUSIONS_CACHE = os.path.join(BASE_DIR, "exclusions_cache.json")
EXCLUSIONS_TTL_HOURS = 6

# Structural backstop for anything pegged that no category caught: tokenized
# treasuries, yield-bearing dollars, metal-backed tokens. Measured live these
# sit at 0.03-1.2% max move across EVERY timeframe. The threshold sits just
# above that band deliberately: at 3.0% it swallowed TRX (a real L1 having a
# quiet week, 2.43%), which is a filter mislabelling an asset rather than
# detecting a peg. Anything genuinely this flat has no trend to trade.
PEG_FLATNESS_PCT = 1.5

# Tokenized real-world instruments -- private credit, T-bills, home-equity
# lines, reinsurance, metals. They ride an off-chain yield curve, not a crypto
# trend, and some drift just enough to clear the peg filter.
RWA_TOKENS = {
    "FIGR_HELOC", "USYC", "OUSG", "JTRSY", "JAAA", "USTB", "EUTBL", "YLDS",
    "BCAP", "EURSAFO", "USTBL", "USDAI", "A7A5", "KAU", "XAUT", "PAXG",
    "BUIDL", "ONYC", "CRCLON", "SOFID", "APXUSD",
}

# --------------------------------------------------------------------------
# Strategy configuration
# --------------------------------------------------------------------------

INITIAL_CAPITAL = 10_000.0

# A "moon" is a resolved (closed) trade that delivered its full thesis.
#
# This started as a flat >= 50% gain, which was reachable when the universe
# still held meme-adjacent alts. It is not reachable now: exits test
# take-profit before the trailing stop, so every winner is closed at its
# target -- 9%, 12%, 22% -- and no trade in any book could ever be flagged a
# moon. The pattern model needs 4 moons to activate, so the feature was dead.
#
# So a moon is now defined per strategy, just under each book's take-profit:
# a full-target win, or a trailing exit close to it. Stop-outs, momentum
# breakdowns and max-hold scratches are not moons. That makes the model learn
# the question actually worth asking -- which setups reach their target rather
# than stopping out -- and makes 4 of them attainable.
MOON_THRESHOLD_PCT = 50.0        # legacy default; per-strategy moon_pct wins

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
        "moon_pct": 7.0,          # just under target: a win, not a scratch
        "max_entries_per_cycle": 2,
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
    # Its own separate book. Same blue-chip universe, but it can profit in
    # either direction: long on positive momentum, short on negative. The two
    # portfolios above stay long-only, so this isolates whether shorting adds
    # anything rather than muddying an existing strategy's record.
    "longshort": {
        "max_rank": 50,
        "min_volume_usd": 25_000_000,
        "allow_short": True,
        "gates": {                       # long side
            "pc_1h": 0.3, "pc_24h": 1.5, "pc_7d": 0.0,
        },
        "max_gates": {
            "pc_1h": 10.0, "pc_24h": 30.0, "pc_7d": 60.0,
            "pc_14d": 120.0, "pc_30d": 200.0,
        },
        # Short side: momentum must be falling on every short-term window.
        # The floors stop us shorting something that has already collapsed --
        # that is where violent short squeezes live, not easy downside.
        "short_gates": {
            "pc_1h": -0.3, "pc_24h": -1.5, "pc_7d": 0.0,
        },
        "short_floors": {
            "pc_1h": -10.0, "pc_24h": -25.0, "pc_7d": -45.0, "pc_30d": -70.0,
        },
        "min_score": 2.0,
        "position_pct": 0.15,
        "max_positions": 5,
        "min_cash_reserve_pct": 0.15,
        "stop_loss_pct": 5.0,
        "take_profit_pct": 12.0,
        "moon_pct": 9.5,          # just under target: a win, not a scratch
        "max_entries_per_cycle": 2,
        "trail_arm_pct": 7.0,
        "trail_giveback_pct": 3.5,
        "max_hold_hours": 48,
        "breakdown_24h": -5.0,
        "breakdown_7d": -8.0,
        "cooldown_hours": 2,
        "weights": {
            "pc_1h": 1.2, "pc_24h": 1.6, "pc_7d": 0.6,
            "pc_14d": 0.2, "pc_30d": 0.1,
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
        "moon_pct": 17.0,          # just under target: a win, not a scratch
        "max_entries_per_cycle": 2,
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
    "timestamp", "strategy", "action", "side", "symbol", "name", "price", "quantity",
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

class Exclusions:
    """Live meme/stablecoin/derivative registry from CoinGecko categories.

    Keyed by CoinGecko id (symbols are not unique) with symbols kept as a
    secondary match. Cached to disk so a restart does not need a refetch, and
    so a category-API outage can never silently open the gates to meme coins.
    """

    def __init__(self):
        self.ids = set()
        self.symbols = set()
        self.layer1_ids = set()
        self.fetched_at = None
        self.source = "none"
        self.load_cache()

    def load_cache(self):
        if not os.path.exists(EXCLUSIONS_CACHE):
            return
        try:
            with open(EXCLUSIONS_CACHE) as fh:
                blob = json.load(fh)
            self.ids = set(blob.get("ids", []))
            self.symbols = set(blob.get("symbols", []))
            self.layer1_ids = set(blob.get("layer1_ids", []))
            self.fetched_at = blob.get("fetched_at")
            self.source = "cache"
        except (OSError, ValueError) as exc:
            log("exclusions: cache unreadable (%s)" % exc)

    def save_cache(self):
        try:
            tmp = EXCLUSIONS_CACHE + ".tmp"
            with open(tmp, "w") as fh:
                json.dump({"ids": sorted(self.ids), "symbols": sorted(self.symbols),
                           "layer1_ids": sorted(self.layer1_ids),
                           "fetched_at": self.fetched_at,
                           "categories": list(EXCLUDED_CATEGORIES),
                           "included": list(INCLUDED_CATEGORIES)}, fh, indent=2)
            os.replace(tmp, EXCLUSIONS_CACHE)
        except OSError as exc:
            log("exclusions: could not write cache (%s)" % exc)

    def stale(self):
        if self.fetched_at is None:
            return True
        age = (now_utc() - parse_iso(self.fetched_at)).total_seconds() / 3600.0
        return age >= EXCLUSIONS_TTL_HOURS

    @staticmethod
    def _fetch_category(category):
        """One category, with retries. 429s are routine on the free tier."""
        last = None
        for attempt in range(3):
            try:
                resp = requests.get(
                    CATEGORY_URL,
                    params={"vs_currency": "usd", "category": category,
                            "order": "market_cap_desc", "per_page": 250, "page": 1},
                    timeout=REQUEST_TIMEOUT,
                    headers={"Accept": "application/json",
                             "User-Agent": "kirktron-paper-trader/1.0"},
                )
                if resp.status_code == 429:
                    raise RuntimeError("rate limited (429)")
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, list):
                    raise RuntimeError("unexpected payload")
                return data
            except Exception as exc:            # noqa: BLE001
                last = exc
                time.sleep(min(30, 5 * (2 ** attempt)) + random.uniform(0, 2))
        raise RuntimeError(str(last))

    def refresh(self, force=False):
        if not force and not self.stale():
            return
        ids, symbols, failed = set(), set(), []
        for category in EXCLUDED_CATEGORIES:
            try:
                data = self._fetch_category(category)
                for coin in data:
                    if coin.get("id"):
                        ids.add(coin["id"])
                    if coin.get("symbol"):
                        symbols.add(coin["symbol"].upper())
                log("exclusions: %s -> %d coins" % (category, len(data)))
            except Exception as exc:            # noqa: BLE001
                failed.append("%s (%s)" % (category, exc))
            time.sleep(3)                        # stay well inside the free rate limit

        layer1 = set()
        for category in INCLUDED_CATEGORIES:
            try:
                for coin in self._fetch_category(category):
                    if coin.get("id"):
                        layer1.add(coin["id"])
                log("universe: %s -> %d coins" % (category, len(layer1)))
            except Exception as exc:            # noqa: BLE001
                failed.append("%s (%s)" % (category, exc))
            time.sleep(3)
        if layer1:
            self.layer1_ids = layer1
        elif not self.layer1_ids:
            # Fail-open on the INCLUSION list silently widens the universe back
            # to every alt in the top 250, which is the opposite of what was
            # asked for. Say so loudly rather than trading a universe nobody chose.
            log("universe: WARNING -- layer-1 allowlist unavailable and no cached "
                "copy; the blue-chip restriction is NOT being enforced this cycle")

        if failed and not ids:
            # Total failure: keep whatever we already had rather than trading blind.
            log("exclusions: refresh FAILED for all categories: %s; "
                "keeping %s list of %d symbols"
                % ("; ".join(failed), self.source, len(self.symbols)))
            return
        if failed:
            log("exclusions: partial refresh, failed: %s" % "; ".join(failed))
        self.ids, self.symbols = ids, symbols
        self.fetched_at = iso()
        self.source = "live"
        self.save_cache()
        log("exclusions: %d ids / %d symbols across %d categories"
            % (len(self.ids), len(self.symbols), len(EXCLUDED_CATEGORIES)))

    def is_blue_chip(self, coin):
        """Layer-1 chain, or a top-rank asset. Anything else is out of scope."""
        if coin.get("id") in self.layer1_ids:
            return True
        rank = coin.get("market_cap_rank")
        return rank is not None and rank <= BLUE_CHIP_MAX_RANK

    def blocks(self, coin):
        # Match on CoinGecko id ONLY. Symbols are not unique across the
        # category lists -- wrapped/bridged tokens reuse the underlying's
        # ticker (wrapped-solana is symbol "SOL", bridged ether is "ETH"), so
        # symbol matching here excluded BTC, ETH and SOL outright. Ids come
        # from the same fetch, so this is just as complete and actually precise.
        # Symbol-level filtering stays with the curated static lists.
        return "category" if coin.get("id") in self.ids else None


EXCLUSIONS = Exclusions()


def is_pegged(coin):
    """True if the coin barely moves on any timeframe -- a peg, not a trend."""
    moves = [
        abs(num(coin.get("price_change_percentage_%s_in_currency" % w)))
        for w in ("1h", "24h", "7d", "14d", "30d")
    ]
    return max(moves) < PEG_FLATNESS_PCT if moves else False


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


def exclusion_reason(coin):
    """Why this coin is not tradeable, or None if it is."""
    symbol = (coin.get("symbol") or "").upper()
    name = (coin.get("name") or "").lower()
    if not symbol:
        return "no symbol"
    if symbol in MEME_COINS:
        return "meme (static)"
    if symbol in STABLECOINS:
        return "stablecoin (static)"
    if symbol in WRAPPED_STAKED:
        return "wrapped/staked (static)"
    if symbol in RWA_TOKENS or symbol.startswith("PC0000"):
        return "tokenized real-world asset"
    hit = EXCLUSIONS.blocks(coin)
    if hit:
        return "meme/stable/derivative (%s)" % hit
    if any(tok in name for tok in EXCLUDED_NAME_TOKENS):
        return "name filter"
    if is_pegged(coin):
        return "pegged (<%.1f%% move on every timeframe)" % PEG_FLATNESS_PCT
    if EXCLUSIONS.layer1_ids and not EXCLUSIONS.is_blue_chip(coin):
        return "not a layer-1 or blue chip"
    if coin.get("market_cap_rank") is None:
        return "unranked"
    if not coin.get("current_price"):
        return "no price"
    return None


def is_tradeable(coin):
    symbol = (coin.get("symbol") or "").upper()
    name = (coin.get("name") or "").lower()
    if not symbol or symbol in EXCLUDED_SYMBOLS:
        return False
    if symbol in RWA_TOKENS or symbol.startswith("PC0000"):
        return False
    if EXCLUSIONS.blocks(coin):
        return False
    if any(tok in name for tok in EXCLUDED_NAME_TOKENS):
        return False
    if is_pegged(coin):
        return False
    # Only enforce the allowlist once we actually have one -- an empty set
    # means the fetch never succeeded, and that must not empty the universe.
    if EXCLUSIONS.layer1_ids and not EXCLUSIONS.is_blue_chip(coin):
        return False
    if coin.get("market_cap_rank") is None:
        return False
    if not coin.get("current_price"):
        return False
    return True


def build_price_feed(markets):
    """symbol -> {price, features} for EVERY coin, exclusions ignored.

    Entries come from the tradeable universe, but exits must not: a coin we
    already hold can leave the universe (reclassified, or a filter tightened
    under it) and would otherwise become unpriceable, freezing the position
    open forever past its stop.
    """
    feed = {}
    for coin in markets:
        symbol = (coin.get("symbol") or "").upper()
        price = num(coin.get("current_price"))
        if not symbol or not price or symbol in feed:
            continue
        feed[symbol] = {
            "symbol": symbol,
            "name": coin.get("name") or symbol,
            "price": price,
            "features": {
                "pc_1h": clip("pc_1h", num(coin.get("price_change_percentage_1h_in_currency"))),
                "pc_24h": clip("pc_24h", num(coin.get("price_change_percentage_24h_in_currency"))),
                "pc_7d": clip("pc_7d", num(coin.get("price_change_percentage_7d_in_currency"))),
            },
        }
    return feed


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
            "id": coin.get("id"),
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
        if row.get("strategy") != strategy or row.get("action") not in ("SELL", "COVER"):
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

    @staticmethod
    def change_pct(pos, price):
        """Signed return on capital, correct for either direction."""
        entry = pos["entry_price"]
        if pos.get("side", "long") == "short":
            return (entry - price) / entry * 100.0
        return (price - entry) / entry * 100.0

    def position_value(self, pos, price):
        cost = pos["quantity"] * pos["entry_price"]
        if pos.get("side", "long") == "short":
            # Collateral is posted at entry; it returns with the P/L attached.
            return cost + (pos["entry_price"] - price) * pos["quantity"]
        return pos["quantity"] * price

    def value(self, universe):
        total = self.cash
        for symbol, pos in self.positions.items():
            price = universe.get(symbol, {}).get("price") or pos["last_price"]
            total += self.position_value(pos, price)
        return total

    # ---- scoring ---------------------------------------------------------

    def base_score(self, features):
        return sum(w * features.get(name, 0.0)
                   for name, w in self.cfg["weights"].items())

    def passes_short_gates(self, coin):
        cfg = self.cfg
        if not cfg.get("allow_short"):
            return False
        if coin["rank"] > cfg["max_rank"] or coin["volume"] < cfg["min_volume_usd"]:
            return False
        raw = coin["raw"]
        for name, ceiling in cfg.get("short_gates", {}).items():
            if raw.get(name, 0.0) > ceiling:
                return False
        for name, floor in cfg.get("short_floors", {}).items():
            if raw.get(name, 0.0) < floor:
                return False   # already collapsed -- squeeze risk, no edge left
        return True

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

    def open_position(self, coin, score, bonus, portfolio_value, side="long"):
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
            "side": side,
            "quantity": qty,
            "entry_price": price,
            "entry_time": iso(),
            "peak_pct": 0.0,
            "last_price": price,
            "entry_features": coin["features"],
            "entry_score": score,
            "pattern_bonus": bonus,
        }
        self.trades_opened += 1
        reason = "%s momentum entry (score %.2f%s)" % (
            side, score, ", pattern %+.2f" % bonus if abs(bonus) > 1e-9 else "")
        append_trade({
            "timestamp": iso(), "strategy": self.name,
            "action": "SHORT" if side == "short" else "BUY", "side": side,
            "symbol": coin["symbol"], "name": coin["name"], "price": "%.8f" % price,
            "quantity": "%.8f" % qty, "usd_amount": "%.2f" % usd, "reason": reason,
            "pnl": "", "pnl_pct": "", "resolved": "False", "moon": "False",
            "portfolio_value": "%.2f" % portfolio_value, "cash": "%.2f" % self.cash,
            "hold_hours": "", "score": "%.3f" % score, "pattern_bonus": "%.3f" % bonus,
            **{"f_" + n: "%.4f" % coin["features"][n] for n in FEATURE_NAMES},
        })
        log("%s %-5s %s @ $%.6f  $%.2f (score %.2f, pattern %+.2f)"
            % (self.name, "SHORT" if side == "short" else "BUY",
               coin["symbol"], price, usd, score, bonus))
        return True

    def close_position(self, symbol, price, reason, universe):
        pos = self.positions.pop(symbol)
        side = pos.get("side", "long")
        cost = pos["quantity"] * pos["entry_price"]
        if side == "short":
            pnl = (pos["entry_price"] - price) * pos["quantity"]
            proceeds = cost + pnl        # collateral back, plus or minus the move
        else:
            proceeds = pos["quantity"] * price
            pnl = proceeds - cost
        pnl_pct = self.change_pct(pos, price)
        moon = pnl_pct >= self.cfg.get("moon_pct", MOON_THRESHOLD_PCT)
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
            "timestamp": iso(), "strategy": self.name,
            "action": "COVER" if side == "short" else "SELL", "side": side,
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
        log("%s %-5s %s @ $%.6f  pnl $%.2f (%+.2f%%) [%s]%s"
            % (self.name, "COVER" if side == "short" else "SELL",
               symbol, price, pnl, pnl_pct, reason, "  *** MOON ***" if moon else ""))

    def exit_reason(self, pos, coin):
        """Return a reason string if this position should be closed now."""
        cfg = self.cfg
        price = coin["price"] if coin else pos["last_price"]
        side = pos.get("side", "long")
        # change/peak are returns ON CAPITAL, so a short that falls is a gain
        # and every rule below reads the same for both directions.
        change = self.change_pct(pos, price)
        peak = max(pos.get("peak_pct", 0.0), change)
        drawdown = change - peak

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
            if side == "short":
                # The thesis dies when momentum turns back UP against us.
                if (feats["pc_24h"] >= -cfg["breakdown_24h"]
                        and feats["pc_7d"] >= -cfg["breakdown_7d"]):
                    return "momentum recovered against short (24h %+.2f%%, 7d %+.2f%%)" % (
                        feats["pc_24h"], feats["pc_7d"])
            elif (feats["pc_24h"] <= cfg["breakdown_24h"]
                    and feats["pc_7d"] <= cfg["breakdown_7d"]):
                return "momentum breakdown (24h %+.2f%%, 7d %+.2f%%)" % (
                    feats["pc_24h"], feats["pc_7d"])
        return None

    # ---- one cycle -------------------------------------------------------

    def step(self, universe, log_rows, feed=None):
        feed = feed if feed is not None else universe
        self.pattern.fit(resolved_rows_for(self.name, log_rows))

        # 1. mark to market and handle exits
        for symbol in list(self.positions):
            pos = self.positions[symbol]
            coin = feed.get(symbol)      # price from the full feed, never the filtered universe
            if coin:
                pos["last_price"] = coin["price"]
                pos["peak_pct"] = max(pos.get("peak_pct", 0.0),
                                      self.change_pct(pos, coin["price"]))
            else:
                log("%s: %s missing from market feed this cycle; holding"
                    % (self.name, symbol))
            reason = self.exit_reason(pos, coin)
            if reason:
                self.close_position(symbol, pos["last_price"], reason, feed)

        # 2. look for entries
        portfolio_value = self.value(universe)
        candidates = []
        for symbol, coin in universe.items():
            if symbol in self.positions or self.on_cooldown(symbol):
                continue
            if not self.passes_gates(coin):
                continue
            bonus = self.pattern.bonus(coin["features"])
            if self.passes_gates(coin):
                total = self.base_score(coin["features"]) + bonus
                if total >= self.cfg["min_score"]:
                    candidates.append((total, bonus, coin, "long"))
            elif self.passes_short_gates(coin):
                # Falling momentum scores negative, so flip the sign: the
                # score means "conviction", not "direction".
                total = -self.base_score(coin["features"]) + bonus
                if total >= self.cfg["min_score"]:
                    candidates.append((total, bonus, coin, "short"))
        candidates.sort(key=lambda c: -c[0])

        opened = 0
        for total, bonus, coin, side in candidates:
            if len(self.positions) >= self.cfg["max_positions"]:
                break
            # Filling every slot in one cycle makes the whole book a single bet
            # on one instant of market conditions -- all 8 original positions
            # opened in the same second -- and gives the pattern model a
            # training set that encodes one timestamp rather than a setup.
            if opened >= self.cfg.get("max_entries_per_cycle", 99):
                break
            reserve = portfolio_value * self.cfg["min_cash_reserve_pct"]
            if self.cash - reserve < INITIAL_CAPITAL * self.cfg["position_pct"] * 0.5:
                break
            if self.open_position(coin, total, bonus, portfolio_value, side):
                opened += 1
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
        lines.append("  pattern model: %s  (moon >= %+.1f%%)"
                     % (self.pattern.describe(), self.cfg.get("moon_pct", MOON_THRESHOLD_PCT)))
        if self.positions:
            lines.append("  open positions:")
            for symbol, pos in sorted(self.positions.items()):
                price = (universe or {}).get(symbol, {}).get("price") or pos["last_price"]
                change = self.change_pct(pos, price)
                held = (now_utc() - parse_iso(pos["entry_time"])).total_seconds() / 3600
                lines.append("    %-5s %-8s %+7.2f%%  $%8.2f  held %5.1fh  (entry $%.6f)"
                             % (pos.get("side", "long").upper(), symbol, change,
                                self.position_value(pos, price), held, pos["entry_price"]))
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
    EXCLUSIONS.refresh()          # no-op unless the cached list is stale
    markets = fetch_markets()
    universe = build_universe(markets)
    log_rows = read_trade_log()
    log("cycle: %d coins fetched, %d tradeable after exclusions"
        % (len(markets), len(universe)))
    for pf in portfolios:
        orphans = [s for s in pf.positions if s not in universe]
        if orphans:
            log("  %s: holding %s -- outside the tradeable universe, "
                "still priced and still exitable" % (pf.name, ", ".join(orphans)))
    feed = build_price_feed(markets)
    values = {}
    for pf in portfolios:
        value = pf.step(universe, log_rows, feed)
        values[pf.name] = value
        log("  %-12s value $%.2f | cash $%.2f | %d open | %d closed | %d moons"
            % (pf.name, value, pf.cash, len(pf.positions), pf.trades_closed, pf.moons))
    record_equity(values)
    return universe


def record_equity(values):
    """One row per cycle: the equity curve the dashboard charts."""
    names = list(STRATEGIES)
    try:
        new_file = not os.path.exists(EQUITY_LOG)
        with open(EQUITY_LOG, "a", newline="") as fh:
            w = csv.writer(fh)
            if new_file:
                w.writerow(["timestamp"] + names + ["combined"])
            row = [values.get(n, 0.0) for n in names]
            w.writerow([iso()] + ["%.2f" % v for v in row] + ["%.2f" % sum(row)])
    except OSError as exc:
        log("equity log write failed: %s" % exc)


def report():
    ensure_trade_log()
    rows = read_trade_log()
    portfolios = [Portfolio(n) for n in STRATEGIES]
    universe = {}
    try:
        universe = build_price_feed(fetch_markets())
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


def audit():
    """Prove the universe we trade is real crypto -- no memes, no pegs."""
    EXCLUSIONS.refresh()
    markets = fetch_markets()
    universe = build_universe(markets)
    dropped = []
    for coin in markets:
        reason = exclusion_reason(coin)
        if reason:
            dropped.append((coin.get("market_cap_rank") or 9999,
                            (coin.get("symbol") or "?").upper(),
                            (coin.get("name") or "")[:26], reason))
    print("KIRKTRON UNIVERSE AUDIT -- %s" % iso())
    print("exclusion list: %s, %d ids / %d symbols, fetched %s"
          % (EXCLUSIONS.source, len(EXCLUSIONS.ids), len(EXCLUSIONS.symbols),
             EXCLUSIONS.fetched_at))
    print("layer-1 allowlist: %s"
          % ("%d chains + rank<=%d blue chips" % (len(EXCLUSIONS.layer1_ids), BLUE_CHIP_MAX_RANK)
             if EXCLUSIONS.layer1_ids else "*** UNAVAILABLE -- restriction NOT enforced ***"))
    print("%d coins fetched -> %d excluded -> %d tradeable\n"
          % (len(markets), len(dropped), len(universe)))

    buckets = {}
    for rank, sym, name, reason in dropped:
        buckets.setdefault(reason.split(" (")[0], []).append((rank, sym, name))
    print("EXCLUDED, by reason:")
    for reason in sorted(buckets, key=lambda r: -len(buckets[r])):
        rows = sorted(buckets[reason])
        print("  %-38s %3d  %s" % (reason, len(rows),
                                   ", ".join(s for _, s, _ in rows[:14])
                                   + (" ..." if len(rows) > 14 else "")))

    for name, cfg in STRATEGIES.items():
        elig = sorted([c for c in universe.values() if c["rank"] <= cfg["max_rank"]],
                      key=lambda c: c["rank"])
        print("\n%s TRADEABLE UNIVERSE (rank <= %d): %d coins"
              % (name.upper(), cfg["max_rank"], len(elig)))
        for i in range(0, len(elig), 6):
            print("  " + "".join("%-4s%-9s" % (c["rank"], c["symbol"]) for c in elig[i:i + 6]))


def main():
    parser = argparse.ArgumentParser(description="Kirktron paper trader")
    parser.add_argument("--report", action="store_true", help="print a summary and exit")
    parser.add_argument("--once", action="store_true", help="run a single cycle and exit")
    parser.add_argument("--audit", action="store_true",
                        help="show what is excluded and what is tradeable, then exit")
    parser.add_argument("--interval", type=int, default=POLL_SECONDS,
                        help="seconds between cycles (default %d)" % POLL_SECONDS)
    parser.add_argument("--duration", type=int, default=0,
                        help="trade live for N seconds then exit cleanly (0 = forever). "
                             "Used by the scheduled runner, which must return before "
                             "its own time limit rather than being killed mid-write.")
    args = parser.parse_args()

    ensure_trade_log()

    if args.report:
        report()
        return 0

    if args.audit:
        audit()
        return 0

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    portfolios = [Portfolio(name) for name in STRATEGIES]
    log("starting: %s | poll %ds%s | universe top %d | moons at %s"
        % (", ".join(p.name for p in portfolios), args.interval,
           (" | duration %ds" % args.duration) if args.duration else "",
           UNIVERSE_DEPTH,
           ", ".join("%s %+.1f%%" % (n, c.get("moon_pct", MOON_THRESHOLD_PCT))
                     for n, c in STRATEGIES.items())))

    deadline = (time.time() + args.duration) if args.duration else None
    consecutive_failures = 0
    while not _stop:
        if deadline and time.time() >= deadline:
            log("duration reached; exiting cleanly")
            break
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
            if _stop or (deadline and time.time() >= deadline):
                break
            time.sleep(1)
    log("stopped cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())

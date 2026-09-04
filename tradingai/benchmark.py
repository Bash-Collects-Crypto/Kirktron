"""Controls that say whether the entry rules did anything.

A positive R total proves nothing on its own: a long-only strategy gated on
a bullish regime will show a profit in a rising market whatever its entry
rules say. These arms give the strategy something to beat.

- **Buy and hold** — one entry at the start of the section, held to the end,
  expressed in the same risk units as the trades.
- **Random entries, any day** — the same number of trades, taken at random,
  managed by the same stop and target rules.
- **Random entries, bullish regime only** — the same, but drawn from the
  days the regime filter already allows. This is the arm that matters: it
  holds the regime filter constant, so what is left is the entry signal.

Random trades are drawn without replacement but are simulated
independently, so unlike the strategy's trades they may overlap in time.
That widens the spread of the distribution; it does not move its centre,
which is what the comparison reads.
"""

from dataclasses import dataclass, field

import numpy as np

from .regime import detect_market_regime
from .strategy import STOP_ATR_MULTIPLIER
from .trade import simulate_trade

DEFAULT_RUNS = 200
MAX_HOLDING_DAYS = 20

# How far above the random distribution the strategy has to sit before the
# entry rules have shown anything.
CLEARS_PERCENTILE = 95.0
SUGGESTIVE_PERCENTILE = 80.0


@dataclass
class ControlArm:
    """One control, run many times over the same section."""

    name: str
    runs: int
    trade_count: int
    average_r_samples: list = field(default_factory=list)

    @property
    def pool_was_empty(self):
        return not self.average_r_samples

    def summary(self):
        if self.pool_was_empty:
            return None

        samples = np.array(self.average_r_samples, dtype=float)

        return {
            "Mean": float(samples.mean()),
            "5th": float(np.percentile(samples, 5)),
            "50th": float(np.percentile(samples, 50)),
            "95th": float(np.percentile(samples, 95))
        }


@dataclass
class BenchmarkResult:
    """The strategy set against every control arm."""

    ticker: str
    section_name: str
    strategy_trades: int
    strategy_total_r: float
    strategy_average_r: float
    buy_and_hold: dict
    arms: list = field(default_factory=list)

    def percentile_against(self, arm_name):
        """How many of that arm's runs the strategy beat, as a percent."""

        for arm in self.arms:
            if arm.name == arm_name and not arm.pool_was_empty:
                return percentile_of(
                    self.strategy_average_r,
                    arm.average_r_samples
                )

        return None

    @property
    def verdict(self):
        """What the regime-held-constant arm supports saying out loud."""

        percentile = self.percentile_against("Random entries, bullish regime")

        if percentile is None:
            return (
                "No comparable random entries were available in this "
                "section."
            )

        if percentile >= CLEARS_PERCENTILE:
            return (
                f"The entry rules beat {percentile:.0f}% of random entries "
                f"taken in the same regime."
            )

        if percentile >= SUGGESTIVE_PERCENTILE:
            return (
                f"The entry rules beat {percentile:.0f}% of random entries "
                f"in the same regime, which is suggestive but under the "
                f"{CLEARS_PERCENTILE:.0f}% bar."
            )

        return (
            f"The entry rules beat only {percentile:.0f}% of random entries "
            f"in the same regime, so this section does not show an edge "
            f"beyond the regime filter."
        )


def percentile_of(value, samples):
    """The percent of samples the value is above."""

    samples = np.array(samples, dtype=float)

    if samples.size == 0:
        return None

    return float((samples < value).sum() / samples.size * 100.0)


def buy_and_hold(asset):
    """Hold the section from its first open to its last close.

    The R equivalent uses the same 1.5-ATR risk unit the trades use, so it
    can be read next to their R totals.
    """

    first = asset.iloc[0]
    last = asset.iloc[-1]

    entry_price = float(first["Open"])
    exit_price = float(last["Close"])

    risk_unit = float(first["ATR"]) * STOP_ATR_MULTIPLIER

    if risk_unit > 0:
        r_equivalent = (exit_price - entry_price) / risk_unit
    else:
        r_equivalent = 0.0

    if entry_price > 0:
        percent_return = (exit_price / entry_price - 1.0) * 100.0
    else:
        percent_return = 0.0

    return {
        "Start Date": asset.index[0],
        "End Date": asset.index[-1],
        "Entry Price": entry_price,
        "Exit Price": exit_price,
        "Percent Return": percent_return,
        "R Equivalent": r_equivalent
    }


def eligible_positions(
    asset,
    regime_only=False,
    max_holding_days=MAX_HOLDING_DAYS
):
    """Positions where a full trade could actually be simulated."""

    # A trade enters the next day and needs the whole holding period after.
    last_usable = len(asset) - max_holding_days - 1

    positions = []

    for position in range(max(last_usable, 0)):
        row = asset.iloc[position]

        if float(row["ATR"]) <= 0:
            continue

        if regime_only:
            regime = detect_market_regime(
                float(row["Close"]),
                float(row["EMA_50"]),
                float(row["EMA_200"]),
                float(row["EMA_200_SLOPE"])
            )

            if regime != "Bullish Trend":
                continue

        positions.append(position)

    return positions


def random_control(
    asset,
    trade_count,
    name,
    regime_only=False,
    runs=DEFAULT_RUNS,
    reward_multiple=4.0,
    use_trailing_stop=True,
    max_holding_days=MAX_HOLDING_DAYS,
    seed=None
):
    """Take ``trade_count`` random entries, ``runs`` times over."""

    arm = ControlArm(name=name, runs=runs, trade_count=trade_count)

    pool = eligible_positions(
        asset,
        regime_only=regime_only,
        max_holding_days=max_holding_days
    )

    if not pool or trade_count <= 0:
        return arm

    generator = np.random.default_rng(seed)

    # A pool smaller than the strategy's trade count has to repeat entries.
    replace = len(pool) < trade_count

    for _ in range(runs):
        chosen = generator.choice(
            pool,
            size=trade_count,
            replace=replace
        )

        r_multiples = []

        for position in chosen:
            trade = simulate_trade(
                asset,
                int(position),
                float(asset.iloc[int(position)]["ATR"]),
                reward_multiple=reward_multiple,
                max_holding_days=max_holding_days,
                use_trailing_stop=use_trailing_stop
            )

            if trade is not None:
                r_multiples.append(trade["R Multiple"])

        if r_multiples:
            arm.average_r_samples.append(
                sum(r_multiples) / len(r_multiples)
            )

    return arm


def benchmark_result(result, runs=DEFAULT_RUNS, seed=None):
    """Set a finished backtest against every control arm.

    Returns ``None`` when the backtest took no trades, since there is then
    nothing to compare.
    """

    if not result.trades:
        return None

    asset = result.section

    trade_count = len(result.trades)

    total_r = sum(trade["R Multiple"] for trade in result.trades)

    benchmark = BenchmarkResult(
        ticker=result.ticker,
        section_name=result.section_name,
        strategy_trades=trade_count,
        strategy_total_r=total_r,
        strategy_average_r=total_r / trade_count,
        buy_and_hold=buy_and_hold(asset)
    )

    arms = [
        ("Random entries, any day", False),
        ("Random entries, bullish regime", True)
    ]

    for offset, (name, regime_only) in enumerate(arms):
        benchmark.arms.append(
            random_control(
                asset,
                trade_count,
                name,
                regime_only=regime_only,
                runs=runs,
                reward_multiple=result.reward_multiple,
                use_trailing_stop=result.use_trailing_stop,
                # A fixed seed still gives each arm its own stream.
                seed=None if seed is None else seed + offset
            )
        )

    return benchmark

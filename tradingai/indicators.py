"""Technical indicators used by the TradingAI system.

These are faithful ports of the formulas in the ``ta`` library
(``ta.momentum.RSIIndicator``, ``ta.trend.MACD`` and
``ta.volatility.AverageTrueRange``) so results match the original
implementation, without depending on a package that no longer builds on
modern setuptools.
"""

import numpy as np
import pandas as pd

RSI_WINDOW = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
ATR_WINDOW = 14
VOLUME_WINDOW = 20


def exponential_moving_average(series, span, min_periods=0):
    """Exponential moving average with ``adjust=False`` smoothing."""

    return series.ewm(
        span=span,
        min_periods=min_periods,
        adjust=False
    ).mean()


def relative_strength_index(close, window=RSI_WINDOW):
    """Wilder's RSI, matching ``ta.momentum.RSIIndicator``."""

    difference = close.diff(1)

    up_direction = difference.where(difference > 0, 0.0)
    down_direction = -difference.where(difference < 0, 0.0)

    average_up = up_direction.ewm(
        alpha=1 / window,
        min_periods=window,
        adjust=False
    ).mean()

    average_down = down_direction.ewm(
        alpha=1 / window,
        min_periods=window,
        adjust=False
    ).mean()

    relative_strength = average_up / average_down

    # A window without a single down close has no relative strength.
    values = np.where(
        average_down == 0,
        100.0,
        100.0 - (100.0 / (1.0 + relative_strength))
    )

    return pd.Series(values, index=close.index, name="RSI")


def moving_average_convergence_divergence(
    close,
    window_fast=MACD_FAST,
    window_slow=MACD_SLOW,
    window_signal=MACD_SIGNAL
):
    """MACD line and signal line, matching ``ta.trend.MACD``."""

    fast_ema = exponential_moving_average(
        close,
        span=window_fast,
        min_periods=window_fast
    )

    slow_ema = exponential_moving_average(
        close,
        span=window_slow,
        min_periods=window_slow
    )

    macd_line = fast_ema - slow_ema
    macd_line.name = "MACD"

    signal_line = exponential_moving_average(
        macd_line,
        span=window_signal,
        min_periods=window_signal
    )

    signal_line.name = "MACD_SIGNAL"

    return macd_line, signal_line


def average_true_range(high, low, close, window=ATR_WINDOW):
    """Wilder's ATR, matching ``ta.volatility.AverageTrueRange``.

    Like the original, the first ``window - 1`` values are zero rather
    than missing, because the seed value is the mean of the first
    ``window`` true ranges.
    """

    previous_close = close.shift(1)

    highs = pd.concat([high, previous_close], axis=1)
    lows = pd.concat([low, previous_close], axis=1)

    # skipna=False keeps the leading NaN, exactly like numpy's amax/amin.
    true_range = (
        highs.max(axis=1, skipna=False)
        - lows.min(axis=1, skipna=False)
    )

    values = np.zeros(len(close))

    if len(close) >= window:
        values[window - 1] = true_range.iloc[:window].mean()

        for position in range(window, len(values)):
            values[position] = (
                values[position - 1] * (window - 1)
                + true_range.iloc[position]
            ) / float(window)

    return pd.Series(values, index=close.index, name="ATR")


def add_indicators(asset, extended=False):
    """Attach every indicator column the system reads.

    ``extended`` adds the longer-term regime columns and the previous
    candle columns that the backtest needs.
    """

    asset = asset.copy()

    close = asset["Close"]
    high = asset["High"]
    low = asset["Low"]
    volume = asset["Volume"]

    asset["EMA_20"] = exponential_moving_average(close, span=20)
    asset["EMA_50"] = exponential_moving_average(close, span=50)

    if extended:
        asset["EMA_200"] = exponential_moving_average(close, span=200)

        asset["EMA_200_SLOPE"] = asset["EMA_200"].pct_change(
            periods=20
        )

        asset["PREVIOUS_OPEN"] = asset["Open"].shift(1)
        asset["PREVIOUS_HIGH"] = asset["High"].shift(1)
        asset["PREVIOUS_LOW"] = asset["Low"].shift(1)
        asset["PREVIOUS_CLOSE"] = asset["Close"].shift(1)

    asset["RSI"] = relative_strength_index(close)

    macd_line, signal_line = moving_average_convergence_divergence(close)

    asset["MACD"] = macd_line
    asset["MACD_SIGNAL"] = signal_line

    asset["ATR"] = average_true_range(high, low, close)

    asset["VOLUME_AVG_20"] = volume.rolling(
        window=VOLUME_WINDOW
    ).mean()

    return asset

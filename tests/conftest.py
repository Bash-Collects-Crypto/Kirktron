"""Synthetic price data so the tests never touch the network."""

import numpy as np
import pandas as pd
import pytest


def make_candles(days=600, seed=7, drift=0.0006, volatility=0.012):
    """A reproducible random walk shaped like daily OHLCV data."""

    generator = np.random.default_rng(seed)

    returns = generator.normal(drift, volatility, days)
    close = 100.0 * np.exp(np.cumsum(returns))

    open_price = close * (
        1.0 + generator.normal(0.0, volatility / 3, days)
    )

    high = np.maximum(open_price, close) * (
        1.0 + np.abs(generator.normal(0.0, volatility / 2, days))
    )

    low = np.minimum(open_price, close) * (
        1.0 - np.abs(generator.normal(0.0, volatility / 2, days))
    )

    volume = generator.integers(1_000_000, 5_000_000, days)

    index = pd.date_range("2020-01-01", periods=days, freq="B")

    return pd.DataFrame(
        {
            "Open": open_price,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": volume.astype(float)
        },
        index=index
    )


def make_frame(rows):
    """Build a candle frame from a list of OHLCV tuples."""

    index = pd.date_range("2021-01-01", periods=len(rows), freq="B")

    return pd.DataFrame(
        rows,
        columns=["Open", "High", "Low", "Close", "Volume"],
        index=index
    )


@pytest.fixture
def candles():
    return make_candles()


@pytest.fixture
def short_candles():
    return make_candles(days=120, seed=3)

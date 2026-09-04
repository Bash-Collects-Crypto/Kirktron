import numpy as np
import pandas as pd
import pytest

from tradingai.indicators import (
    add_indicators,
    average_true_range,
    exponential_moving_average,
    moving_average_convergence_divergence,
    relative_strength_index
)


def test_rsi_stays_inside_its_bounds(candles):
    rsi = relative_strength_index(candles["Close"])

    valid = rsi.dropna()

    assert not valid.empty
    assert valid.min() >= 0.0
    assert valid.max() <= 100.0


def test_rsi_warms_up_for_one_window():
    close = pd.Series(np.linspace(100, 120, 40))

    rsi = relative_strength_index(close, window=14)

    assert rsi.iloc[:13].isna().all()
    assert not np.isnan(rsi.iloc[14])


def test_rsi_is_100_when_every_close_rises():
    close = pd.Series(np.linspace(100, 140, 40))

    rsi = relative_strength_index(close, window=14)

    assert rsi.iloc[-1] == pytest.approx(100.0)


def test_rsi_is_zero_when_every_close_falls():
    close = pd.Series(np.linspace(140, 100, 40))

    rsi = relative_strength_index(close, window=14)

    assert rsi.iloc[-1] == pytest.approx(0.0)


def test_macd_is_the_gap_between_two_emas(candles):
    close = candles["Close"]

    macd_line, signal_line = moving_average_convergence_divergence(close)

    fast = exponential_moving_average(close, span=12, min_periods=12)
    slow = exponential_moving_average(close, span=26, min_periods=26)

    pd.testing.assert_series_equal(
        macd_line,
        (fast - slow).rename("MACD")
    )

    assert macd_line.iloc[:25].isna().all()
    assert signal_line.iloc[:33].isna().all()
    assert not np.isnan(signal_line.iloc[34])


def test_atr_seeds_with_zeros_then_smooths(candles):
    window = 14

    atr = average_true_range(
        candles["High"],
        candles["Low"],
        candles["Close"],
        window=window
    )

    # The ta implementation leaves zeros before the seed value.
    assert (atr.iloc[: window - 1] == 0).all()
    assert atr.iloc[window - 1] > 0

    previous_close = candles["Close"].shift(1)

    highs = pd.concat([candles["High"], previous_close], axis=1)
    lows = pd.concat([candles["Low"], previous_close], axis=1)

    true_range = (
        highs.max(axis=1, skipna=False)
        - lows.min(axis=1, skipna=False)
    )

    expected_seed = true_range.iloc[:window].mean()

    assert atr.iloc[window - 1] == pytest.approx(expected_seed)

    expected_next = (
        atr.iloc[window - 1] * (window - 1)
        + true_range.iloc[window]
    ) / window

    assert atr.iloc[window] == pytest.approx(expected_next)


def test_atr_survives_a_frame_shorter_than_its_window():
    close = pd.Series([10.0, 11.0, 12.0])

    atr = average_true_range(close + 1, close - 1, close, window=14)

    assert (atr == 0).all()


def test_add_indicators_attaches_every_column(candles):
    plain = add_indicators(candles)

    for column in [
        "EMA_20",
        "EMA_50",
        "RSI",
        "MACD",
        "MACD_SIGNAL",
        "ATR",
        "VOLUME_AVG_20"
    ]:
        assert column in plain.columns

    assert "EMA_200" not in plain.columns

    extended = add_indicators(candles, extended=True)

    for column in [
        "EMA_200",
        "EMA_200_SLOPE",
        "PREVIOUS_OPEN",
        "PREVIOUS_HIGH",
        "PREVIOUS_LOW",
        "PREVIOUS_CLOSE"
    ]:
        assert column in extended.columns

    # The source frame is never modified in place.
    assert "EMA_20" not in candles.columns


def test_matches_the_ta_library_when_it_is_installed(candles):
    """Cross-check the ports against ``ta`` where it can be imported."""

    ta_momentum = pytest.importorskip("ta.momentum")
    ta_trend = pytest.importorskip("ta.trend")
    ta_volatility = pytest.importorskip("ta.volatility")

    close = candles["Close"]

    expected_rsi = ta_momentum.RSIIndicator(close=close).rsi()

    pd.testing.assert_series_equal(
        relative_strength_index(close),
        expected_rsi,
        check_names=False
    )

    expected_macd = ta_trend.MACD(close=close)
    macd_line, signal_line = moving_average_convergence_divergence(close)

    pd.testing.assert_series_equal(
        macd_line,
        expected_macd.macd(),
        check_names=False
    )

    pd.testing.assert_series_equal(
        signal_line,
        expected_macd.macd_signal(),
        check_names=False
    )

    expected_atr = ta_volatility.AverageTrueRange(
        high=candles["High"],
        low=candles["Low"],
        close=close,
        window=14
    ).average_true_range()

    pd.testing.assert_series_equal(
        average_true_range(
            candles["High"],
            candles["Low"],
            close,
            window=14
        ),
        expected_atr,
        check_names=False
    )

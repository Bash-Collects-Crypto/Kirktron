import pandas as pd
import pytest

from tradingai.candles import PATTERN_KEYS, interpret_candlestick


def candle_frame(rows, ema20=100.0, ema50=99.0, atr=2.0,
                 average_volume=1_000_000.0):
    """Two candles with hand-set indicator context around them."""

    index = pd.date_range("2021-01-01", periods=len(rows), freq="B")

    frame = pd.DataFrame(
        rows,
        columns=["Open", "High", "Low", "Close", "Volume"],
        index=index
    )

    frame["PREVIOUS_OPEN"] = frame["Open"].shift(1)
    frame["PREVIOUS_HIGH"] = frame["High"].shift(1)
    frame["PREVIOUS_LOW"] = frame["Low"].shift(1)
    frame["PREVIOUS_CLOSE"] = frame["Close"].shift(1)

    frame["EMA_20"] = ema20
    frame["EMA_50"] = ema50
    frame["ATR"] = atr
    frame["VOLUME_AVG_20"] = average_volume

    return frame


def test_every_reading_carries_the_full_key_set():
    """Degenerate candles must not be missing keys callers read."""

    frame = candle_frame([
        (100.0, 100.0, 100.0, 100.0, 1_000_000.0),
        (100.0, 100.0, 100.0, 100.0, 1_000_000.0)
    ])

    first = interpret_candlestick(frame, 0)
    zero_range = interpret_candlestick(frame, 1)

    assert first["Pattern"] == "Not enough candle history"
    assert zero_range["Pattern"] == "Zero-range candle"

    for reading in (first, zero_range):
        assert set(PATTERN_KEYS) <= set(reading)
        assert reading["Score"] == 0
        assert reading["Setup Type"] == "Unclear"
        assert reading["EMA20 Distance ATR"] == 0.0


def test_bullish_engulfing_scores_two():
    frame = candle_frame([
        (102.0, 102.5, 99.0, 99.5, 1_000_000.0),
        (99.0, 103.5, 98.5, 103.0, 1_000_000.0)
    ])

    reading = interpret_candlestick(frame, 1)

    assert "Bullish Engulfing" in reading["Pattern"]
    assert reading["Score"] >= 2


def test_bearish_engulfing_scores_minus_two():
    frame = candle_frame([
        (99.0, 103.0, 98.5, 102.5, 1_000_000.0),
        (103.0, 103.5, 98.0, 98.5, 1_000_000.0)
    ])

    reading = interpret_candlestick(frame, 1)

    assert "Bearish Engulfing" in reading["Pattern"]
    assert reading["Score"] <= -2


def test_hammer_near_ema20_in_an_uptrend_is_a_bullish_rejection():
    frame = candle_frame([
        (101.0, 101.5, 100.0, 100.5, 1_000_000.0),
        (99.0, 100.2, 96.0, 100.0, 1_000_000.0)
    ])

    reading = interpret_candlestick(frame, 1)

    assert "Hammer Rejection" in reading["Pattern"]
    assert "Hammer Near EMA20" in reading["Pattern"]
    assert reading["Setup Type"] == "Bullish Rejection"
    assert reading["Near EMA20"] is True
    assert reading["Score"] >= 2


def test_shooting_star_above_ema20_is_a_bearish_warning():
    # A bearish larger trend, so the reading is not read as a pullback.
    frame = candle_frame(
        [
            (100.0, 100.5, 99.5, 100.2, 1_000_000.0),
            (101.0, 103.0, 100.2, 100.4, 1_000_000.0)
        ],
        ema20=100.0,
        ema50=101.0
    )

    reading = interpret_candlestick(frame, 1)

    assert "Shooting Star" in reading["Pattern"]
    assert "Bearish Rejection Above EMA20" in reading["Pattern"]
    assert reading["Setup Type"] == "Bearish Warning"
    assert reading["Score"] <= -2


def test_strong_bullish_candle_on_heavy_volume():
    frame = candle_frame([
        (100.0, 100.5, 99.5, 100.2, 1_000_000.0),
        (100.0, 105.0, 99.9, 104.9, 3_000_000.0)
    ])

    reading = interpret_candlestick(frame, 1)

    assert "Strong Bullish Candle" in reading["Pattern"]
    assert "Bullish Volume Confirmation" in reading["Pattern"]
    assert reading["Volume Confirmation"] is True
    assert reading["Body Percent"] >= 0.60
    assert reading["Close Position"] >= 0.80


def test_inside_bar_reads_as_consolidation():
    frame = candle_frame([
        (100.0, 106.0, 94.0, 105.0, 1_000_000.0),
        (100.0, 102.0, 99.5, 101.0, 1_000_000.0)
    ])

    reading = interpret_candlestick(frame, 1)

    assert "Inside Bar" in reading["Pattern"]
    assert reading["Setup Type"] == "Consolidation"


def test_outside_bar_takes_the_direction_of_its_close():
    frame = candle_frame([
        (100.0, 101.0, 99.0, 100.5, 1_000_000.0),
        (99.5, 103.0, 97.0, 102.0, 1_000_000.0)
    ])

    reading = interpret_candlestick(frame, 1)

    assert "Bullish Outside Bar" in reading["Pattern"]


def test_distance_to_ema20_is_measured_in_atr():
    frame = candle_frame(
        [
            (100.0, 101.0, 99.0, 100.0, 1_000_000.0),
            (100.0, 104.5, 99.5, 104.0, 1_000_000.0)
        ],
        ema20=100.0,
        atr=2.0
    )

    reading = interpret_candlestick(frame, 1)

    assert reading["EMA20 Distance ATR"] == pytest.approx(2.0)


def test_a_flat_atr_leaves_the_distance_at_zero():
    frame = candle_frame(
        [
            (100.0, 101.0, 99.0, 100.0, 1_000_000.0),
            (100.0, 104.5, 99.5, 104.0, 1_000_000.0)
        ],
        atr=0.0
    )

    reading = interpret_candlestick(frame, 1)

    assert reading["EMA20 Distance ATR"] == 0.0


def test_a_candle_without_a_pattern_says_so():
    frame = candle_frame([
        (100.0, 101.0, 99.0, 100.4, 1_000_000.0),
        (100.4, 101.6, 100.0, 100.9, 1_000_000.0)
    ])

    reading = interpret_candlestick(frame, 1)

    assert "No Clear Pattern" in reading["Pattern"]

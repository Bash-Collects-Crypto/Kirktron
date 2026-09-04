import pytest

from tradingai.signals import (
    analyze_macd,
    analyze_momentum,
    analyze_price,
    analyze_rsi,
    analyze_volume,
    calculate_score,
    interpret_score
)


@pytest.mark.parametrize(
    "ema20, ema50, expected",
    [
        (11.0, 10.0, "Bullish"),
        (10.0, 11.0, "Bearish"),
        (10.0, 10.0, "Bearish")
    ]
)
def test_momentum_reads_the_ema_pair(ema20, ema50, expected):
    assert analyze_momentum(ema20, ema50) == expected


@pytest.mark.parametrize(
    "rsi, expected",
    [
        (70.1, "Overbought"),
        (70.0, "Neutral"),
        (50.0, "Neutral"),
        (30.0, "Neutral"),
        (29.9, "Oversold")
    ]
)
def test_rsi_thresholds(rsi, expected):
    assert analyze_rsi(rsi) == expected


def test_volume_and_price_and_macd_readings():
    assert analyze_volume(100, 101) == "Above average"
    assert analyze_volume(100, 100) == "Below average"

    assert analyze_price(11.0, 10.0) == "Above EMA20"
    assert analyze_price(10.0, 10.0) == "Below EMA20"

    assert analyze_macd(1.0, 0.5) == "Bullish"
    assert analyze_macd(0.5, 1.0) == "Bearish"


def test_best_and_worst_possible_scores():
    best = calculate_score(
        "Bullish",
        "Oversold",
        "Above average",
        "Above EMA20",
        "Bullish"
    )

    worst = calculate_score(
        "Bearish",
        "Overbought",
        "Below average",
        "Below EMA20",
        "Bearish"
    )

    assert best == 6
    assert worst == -5


def test_neutral_rsi_and_thin_volume_do_not_move_the_score():
    with_neutral = calculate_score(
        "Bullish",
        "Neutral",
        "Below average",
        "Above EMA20",
        "Bullish"
    )

    assert with_neutral == 4


@pytest.mark.parametrize(
    "score, expected",
    [
        (5, "Strong Buy"),
        (3, "Strong Buy"),
        (2, "Buy"),
        (1, "Weak Buy"),
        (0, "Neutral"),
        (-1, "Weak Sell"),
        (-2, "Sell"),
        (-3, "Strong Sell"),
        (-5, "Strong Sell")
    ]
)
def test_score_labels(score, expected):
    assert interpret_score(score) == expected

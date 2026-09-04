"""Long-term market regime detection."""


def detect_market_regime(close, ema50, ema200, ema200_slope):
    """Classify the larger trend the price is travelling inside."""

    if (
        close > ema200
        and ema50 > ema200
        and ema200_slope > 0
    ):
        return "Bullish Trend"

    if (
        close < ema200
        and ema50 < ema200
        and ema200_slope < 0
    ):
        return "Bearish Trend"

    return "Sideways"

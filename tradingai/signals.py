"""Indicator readings turned into words, and words turned into a score."""


def analyze_momentum(latest_ema20, latest_ema50):
    if latest_ema20 > latest_ema50:
        return "Bullish"

    return "Bearish"


def analyze_rsi(rsi):
    if rsi > 70:
        return "Overbought"

    if rsi < 30:
        return "Oversold"

    return "Neutral"


def analyze_volume(average_volume, current_volume):
    if current_volume > average_volume:
        return "Above average"

    return "Below average"


def analyze_price(close, ema20):
    if close > ema20:
        return "Above EMA20"

    return "Below EMA20"


def analyze_macd(macd_value, signal_value):
    if macd_value > signal_value:
        return "Bullish"

    return "Bearish"


def calculate_score(
    momentum,
    rsi_signal,
    volume_signal,
    price_signal,
    macd_signal
):
    """Combine the five readings into a score between -5 and +6."""

    score = 0

    # Trend
    if momentum == "Bullish":
        score += 2
    else:
        score -= 2

    # RSI
    if rsi_signal == "Oversold":
        score += 1
    elif rsi_signal == "Overbought":
        score -= 1

    # Volume
    if volume_signal == "Above average":
        score += 1

    # Price
    if price_signal == "Above EMA20":
        score += 1
    else:
        score -= 1

    # MACD
    if macd_signal == "Bullish":
        score += 1
    else:
        score -= 1

    return score


def interpret_score(score):
    if score >= 3:
        return "Strong Buy"

    if score == 2:
        return "Buy"

    if score == 1:
        return "Weak Buy"

    if score == 0:
        return "Neutral"

    if score == -1:
        return "Weak Sell"

    if score == -2:
        return "Sell"

    return "Strong Sell"

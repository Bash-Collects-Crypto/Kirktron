"""Candlestick reading: patterns, a score, and a trader-style setup label."""

import pandas as pd

PATTERN_KEYS = (
    "Score",
    "Pattern",
    "Setup Type",
    "Body Percent",
    "Close Position",
    "Near EMA20",
    "Volume Confirmation",
    "EMA20 Distance ATR"
)


def _unreadable_candle(reason):
    """A neutral reading with every key present.

    The full key set matters: callers read "Setup Type" and
    "EMA20 Distance ATR" from every reading, degenerate ones included.
    """

    return {
        "Score": 0,
        "Pattern": reason,
        "Setup Type": "Unclear",
        "Body Percent": 0.0,
        "Close Position": 0.5,
        "Near EMA20": False,
        "Volume Confirmation": False,
        "EMA20 Distance ATR": 0.0
    }


def interpret_candlestick(asset, position):
    """Read the candle at ``position`` in the context of its trend.

    The frame needs the indicator columns plus the ``PREVIOUS_*``
    columns, i.e. ``add_indicators(..., extended=True)``.
    """

    row = asset.iloc[position]

    open_price = float(row["Open"])
    high = float(row["High"])
    low = float(row["Low"])
    close = float(row["Close"])

    previous_open = float(row["PREVIOUS_OPEN"])
    previous_high = float(row["PREVIOUS_HIGH"])
    previous_low = float(row["PREVIOUS_LOW"])
    previous_close = float(row["PREVIOUS_CLOSE"])

    previous_values = [
        previous_open,
        previous_high,
        previous_low,
        previous_close
    ]

    if any(pd.isna(value) for value in previous_values):
        return _unreadable_candle("Not enough candle history")

    ema20 = float(row["EMA_20"])
    ema50 = float(row["EMA_50"])
    atr = float(row["ATR"])

    current_volume = float(row["Volume"])
    average_volume = float(row["VOLUME_AVG_20"])

    candle_range = high - low

    # Protect against a zero-range candle.
    if candle_range <= 0:
        return _unreadable_candle("Zero-range candle")

    body_size = abs(close - open_price)

    upper_wick = high - max(open_price, close)
    lower_wick = min(open_price, close) - low

    body_percent = body_size / candle_range

    # 0.0 means the candle closed at its low.
    # 1.0 means it closed at its high.
    close_position = (close - low) / candle_range

    bullish_candle = close > open_price
    bearish_candle = close < open_price

    previous_bullish = previous_close > previous_open
    previous_bearish = previous_close < previous_open

    bullish_trend = ema20 > ema50

    near_ema20 = abs(close - ema20) <= atr * 0.50

    volume_confirmation = current_volume > average_volume

    if atr > 0:
        ema20_distance_atr = (close - ema20) / atr
    else:
        ema20_distance_atr = 0.0

    patterns = []
    candle_score = 0

    # ------------------------------------
    # Bullish engulfing
    # ------------------------------------
    bullish_engulfing = (
        bullish_candle
        and previous_bearish
        and open_price <= previous_close
        and close >= previous_open
    )

    if bullish_engulfing:
        patterns.append("Bullish Engulfing")
        candle_score += 2

    # ------------------------------------
    # Bearish engulfing
    # ------------------------------------
    bearish_engulfing = (
        bearish_candle
        and previous_bullish
        and open_price >= previous_close
        and close <= previous_open
    )

    if bearish_engulfing:
        patterns.append("Bearish Engulfing")
        candle_score -= 2

    # ------------------------------------
    # Hammer / lower-wick rejection
    # ------------------------------------
    hammer = (
        body_percent >= 0.10
        and lower_wick >= body_size * 2
        and upper_wick <= max(body_size, candle_range * 0.15)
        and close_position >= 0.60
    )

    if hammer:
        patterns.append("Hammer Rejection")
        candle_score += 1

        # A hammer is more useful near support
        # while the larger trend is bullish.
        if near_ema20 and bullish_trend:
            patterns.append("Hammer Near EMA20")
            candle_score += 1

    # ------------------------------------
    # Shooting star / upper-wick rejection
    # ------------------------------------
    shooting_star = (
        body_percent >= 0.10
        and upper_wick >= body_size * 2
        and lower_wick <= max(body_size, candle_range * 0.15)
        and close_position <= 0.40
    )

    if shooting_star:
        patterns.append("Shooting Star")
        candle_score -= 1

        if close >= ema20:
            patterns.append("Bearish Rejection Above EMA20")
            candle_score -= 1

    # ------------------------------------
    # Strong bullish momentum candle
    # ------------------------------------
    strong_bullish_candle = (
        bullish_candle
        and body_percent >= 0.60
        and close_position >= 0.80
    )

    if strong_bullish_candle:
        patterns.append("Strong Bullish Candle")
        candle_score += 1

        if volume_confirmation:
            patterns.append("Bullish Volume Confirmation")
            candle_score += 1

    # ------------------------------------
    # Strong bearish momentum candle
    # ------------------------------------
    strong_bearish_candle = (
        bearish_candle
        and body_percent >= 0.60
        and close_position <= 0.20
    )

    if strong_bearish_candle:
        patterns.append("Strong Bearish Candle")
        candle_score -= 1

        if volume_confirmation:
            patterns.append("Bearish Volume Confirmation")
            candle_score -= 1

    # ------------------------------------
    # Doji
    # ------------------------------------
    doji = body_percent <= 0.10

    if doji:
        patterns.append("Doji / Indecision")

    # ------------------------------------
    # Inside bar
    # ------------------------------------
    inside_bar = (
        high < previous_high
        and low > previous_low
    )

    if inside_bar:
        patterns.append("Inside Bar")

    # ------------------------------------
    # Outside bar
    # ------------------------------------
    outside_bar = (
        high > previous_high
        and low < previous_low
    )

    if outside_bar:
        if bullish_candle:
            patterns.append("Bullish Outside Bar")
            candle_score += 1

        elif bearish_candle:
            patterns.append("Bearish Outside Bar")
            candle_score -= 1

    # ------------------------------------
    # Trader-style candle context
    # ------------------------------------

    if hammer and near_ema20 and bullish_trend:
        setup_type = "Bullish Rejection"

    elif inside_bar or doji:
        setup_type = "Consolidation"

    elif (
        bearish_candle
        and bullish_trend
        and ema20_distance_atr >= -0.50
        and ema20_distance_atr <= 1.00
    ):
        setup_type = "Bullish Pullback"

    elif strong_bullish_candle and bullish_trend:
        if ema20_distance_atr > 1.50:
            setup_type = "Extended Momentum"
        else:
            setup_type = "Momentum"

    elif (
        shooting_star
        or bearish_engulfing
        or strong_bearish_candle
    ):
        setup_type = "Bearish Warning"

    else:
        setup_type = "Unclear"

    if not patterns:
        patterns.append("No Clear Pattern")

    return {
        "Score": candle_score,
        "Pattern": ", ".join(patterns),
        "Setup Type": setup_type,
        "Body Percent": body_percent,
        "Close Position": close_position,
        "Near EMA20": near_ema20,
        "Volume Confirmation": volume_confirmation,
        "EMA20 Distance ATR": ema20_distance_atr
    }

"""Current-state analysis of a single asset."""

from .data import download_prices
from .indicators import add_indicators
from .signals import (
    analyze_macd,
    analyze_momentum,
    analyze_price,
    analyze_rsi,
    analyze_volume,
    calculate_score,
    interpret_score
)


def analyze_frame(ticker, asset):
    """Score the newest complete candle of an already-loaded frame.

    Returns ``None`` when no row has a full set of indicator values.
    """

    asset = add_indicators(asset)

    # Remove rows without complete indicator values.
    asset = asset.dropna()

    if asset.empty:
        return None

    latest_ema20 = float(asset["EMA_20"].iloc[-1])
    latest_ema50 = float(asset["EMA_50"].iloc[-1])
    latest_close = float(asset["Close"].iloc[-1])
    latest_rsi = float(asset["RSI"].iloc[-1])
    latest_macd = float(asset["MACD"].iloc[-1])
    latest_macd_signal = float(asset["MACD_SIGNAL"].iloc[-1])
    latest_atr = float(asset["ATR"].iloc[-1])

    average_volume = float(asset["VOLUME_AVG_20"].iloc[-1])
    current_volume = float(asset["Volume"].iloc[-1])

    momentum = analyze_momentum(latest_ema20, latest_ema50)
    rsi_signal = analyze_rsi(latest_rsi)
    volume_signal = analyze_volume(average_volume, current_volume)
    price_signal = analyze_price(latest_close, latest_ema20)
    macd_signal = analyze_macd(latest_macd, latest_macd_signal)

    score = calculate_score(
        momentum,
        rsi_signal,
        volume_signal,
        price_signal,
        macd_signal
    )

    return {
        "Ticker": ticker,
        "Current Price": round(latest_close, 2),
        "ATR": latest_atr,
        "Score": score,
        "Signal": interpret_score(score),
        "Momentum": momentum,
        "Price": price_signal,
        "RSI": round(latest_rsi, 2),
        "RSI Signal": rsi_signal,
        "Volume": volume_signal,
        "MACD": round(latest_macd, 2),
        "MACD Signal": round(latest_macd_signal, 2),
        "MACD Trend": macd_signal,
        "History": asset
    }


def analyze_asset(ticker, period="1y", loader=None):
    """Load one year of candles and score the newest one.

    ``loader`` defaults to the yfinance download and can be swapped for
    any callable taking ``(ticker, period)``.
    """

    if loader is None:
        loader = download_prices

    asset = loader(ticker, period=period)

    if asset.empty:
        return None

    return analyze_frame(ticker, asset)


def build_watchlist(results, account_size, risk_percent):
    """Rank analysed assets and attach a trade plan to every entry."""

    from .strategy import calculate_trade_plan, check_strategy

    ranked = sorted(
        results,
        key=lambda result: result["Score"],
        reverse=True
    )

    for result in ranked:
        strategy, strategy_reason = check_strategy(result)

        result["Strategy"] = strategy
        result["Strategy Reason"] = strategy_reason

        if strategy == "Enter":
            result["Trade Plan"] = calculate_trade_plan(
                result,
                account_size,
                risk_percent
            )
        else:
            result["Trade Plan"] = None

    return ranked

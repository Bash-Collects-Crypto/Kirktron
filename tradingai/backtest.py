"""Historical replay of the entry rules, split into train and test data."""

from dataclasses import dataclass, field

from .candles import interpret_candlestick
from .data import download_prices
from .indicators import add_indicators
from .regime import detect_market_regime
from .signals import (
    analyze_macd,
    analyze_momentum,
    analyze_price,
    analyze_rsi,
    analyze_volume,
    calculate_score
)
from .strategy import check_strategy
from .trade import simulate_trade

TRAINING_FRACTION = 0.80


@dataclass
class DataSplit:
    """Where the training period ends and the testing period begins."""

    training: object
    testing: object

    def describe(self):
        return {
            "Training Start": self.training.index[0],
            "Training End": self.training.index[-1],
            "Testing Start": self.testing.index[0],
            "Testing End": self.testing.index[-1],
            "Training Days": len(self.training),
            "Testing Days": len(self.testing)
        }


@dataclass
class BacktestResult:
    """Everything one backtest produced, before any printing."""

    ticker: str
    section_name: str
    reward_multiple: float
    use_trailing_stop: bool
    trading_days: int
    split: DataSplit
    entry_signals: list = field(default_factory=list)
    trades: list = field(default_factory=list)
    blocked_signals: list = field(default_factory=list)

    @property
    def stop_method(self):
        if self.use_trailing_stop:
            return "Trailing Stop"

        return "Fixed Stop"


def prepare_backtest_data(asset):
    """Add every indicator the backtest reads and drop incomplete rows."""

    asset = add_indicators(asset, extended=True)

    # Remove early rows that are missing indicator values.
    return asset.dropna()


def split_data(asset, training_fraction=TRAINING_FRACTION):
    """Oldest share of the data for development, newest for testing."""

    split_position = int(len(asset) * training_fraction)

    training = asset.iloc[:split_position].copy()
    testing = asset.iloc[split_position:].copy()

    return DataSplit(training=training, testing=testing)


def run_backtest(
    ticker,
    asset,
    data_section="testing",
    reward_multiple=4.0,
    use_trailing_stop=True
):
    """Replay the entry rules over one section of prepared data.

    Raises ``ValueError`` when ``data_section`` is not a known section.
    Returns ``None`` when the data cannot be split into two usable
    sections.
    """

    if data_section not in ("training", "testing"):
        raise ValueError(
            "data_section must be 'training' or 'testing'"
        )

    asset = prepare_backtest_data(asset)

    # Make sure enough usable historical data remains.
    if len(asset) < 2:
        return None

    split = split_data(asset)

    if split.training.empty or split.testing.empty:
        return None

    if data_section == "training":
        asset = split.training
        section_name = "Training"
    else:
        asset = split.testing
        section_name = "Out-of-Sample Testing"

    result = BacktestResult(
        ticker=ticker,
        section_name=section_name,
        reward_multiple=reward_multiple,
        use_trailing_stop=use_trailing_stop,
        trading_days=len(asset),
        split=split
    )

    next_available_position = 0

    # Analyze every historical trading day.
    for position, (date, row) in enumerate(asset.iterrows()):
        # Skip dates while the previous trade is still open.
        if position < next_available_position:
            continue

        close = float(row["Close"])
        atr = float(row["ATR"])
        ema20 = float(row["EMA_20"])

        momentum = analyze_momentum(ema20, float(row["EMA_50"]))
        rsi_signal = analyze_rsi(float(row["RSI"]))

        volume_signal = analyze_volume(
            float(row["VOLUME_AVG_20"]),
            float(row["Volume"])
        )

        price_signal = analyze_price(close, ema20)

        if atr > 0:
            ema20_extension_atr = (close - ema20) / atr
        else:
            ema20_extension_atr = 0.0

        macd_trend = analyze_macd(
            float(row["MACD"]),
            float(row["MACD_SIGNAL"])
        )

        market_regime = detect_market_regime(
            close,
            float(row["EMA_50"]),
            float(row["EMA_200"]),
            float(row["EMA_200_SLOPE"])
        )

        candle_info = interpret_candlestick(asset, position)

        score = calculate_score(
            momentum,
            rsi_signal,
            volume_signal,
            price_signal,
            macd_trend
        )

        strategy, _reason = check_strategy({
            "Score": score,
            "Momentum": momentum,
            "MACD Trend": macd_trend,
            "RSI": float(row["RSI"])
        })

        if strategy != "Enter":
            continue

        # Block long entries outside a bullish regime.
        if market_regime != "Bullish Trend":
            result.blocked_signals.append({
                "Date": date,
                "Regime": market_regime,
                "Score": score
            })

            continue

        next_position = position + 1

        if next_position >= len(asset):
            continue

        next_row = asset.iloc[next_position]

        signal_high = float(row["High"])
        next_day_high = float(next_row["High"])
        next_day_close = float(next_row["Close"])

        trade = simulate_trade(
            asset,
            position,
            atr,
            reward_multiple=reward_multiple,
            use_trailing_stop=use_trailing_stop
        )

        # Skip signals without enough future data.
        if trade is None:
            continue

        result.entry_signals.append({
            "Date": date,
            "Price": close,
            "Score": score,
            "RSI": float(row["RSI"]),
            "ATR": atr,
            "EMA20 Extension ATR": ema20_extension_atr,
            "Regime": market_regime,
            "Candle Score": candle_info["Score"],
            "Candlestick": candle_info["Pattern"],
            "Setup Type": candle_info["Setup Type"],
            "EMA20 Distance ATR": candle_info["EMA20 Distance ATR"]
        })

        trade["Signal Date"] = date
        trade["Score"] = score
        trade["EMA20 Extension ATR"] = ema20_extension_atr
        trade["Regime"] = market_regime
        trade["Candle Score"] = candle_info["Score"]
        trade["Candlestick"] = candle_info["Pattern"]
        trade["Setup Type"] = candle_info["Setup Type"]
        trade["EMA20 Distance ATR"] = candle_info["EMA20 Distance ATR"]
        trade["Signal High"] = signal_high
        trade["Next-Day High Breakout"] = next_day_high > signal_high
        trade["Next-Day Close Confirmation"] = (
            next_day_close > signal_high
        )

        result.trades.append(trade)

        # Do not enter another trade until this trade exits.
        next_available_position = trade["Exit Position"] + 1

    return result


def backtest_ticker(
    ticker,
    period="5y",
    data_section="testing",
    reward_multiple=4.0,
    use_trailing_stop=True,
    loader=None
):
    """Load five years of candles and backtest one section of them.

    ``loader`` defaults to the yfinance download and can be swapped for
    any callable taking ``(ticker, period)``.
    """

    if loader is None:
        loader = download_prices

    asset = loader(ticker, period=period)

    if asset.empty:
        return None

    return run_backtest(
        ticker,
        asset,
        data_section=data_section,
        reward_multiple=reward_multiple,
        use_trailing_stop=use_trailing_stop
    )

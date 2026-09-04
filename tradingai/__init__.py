"""TradingAI: an indicator-scored watchlist and a rule backtester."""

from .analysis import analyze_asset, analyze_frame, build_watchlist
from .backtest import (
    BacktestResult,
    backtest_ticker,
    prepare_backtest_data,
    run_backtest,
    split_data
)
from .benchmark import (
    BenchmarkResult,
    ControlArm,
    benchmark_result,
    buy_and_hold,
    eligible_positions,
    random_control
)
from .candles import interpret_candlestick
from .data import (
    DEFAULT_TICKERS,
    csv_loader,
    download_prices,
    load_prices_from_csv
)
from .indicators import (
    add_indicators,
    average_true_range,
    exponential_moving_average,
    moving_average_convergence_divergence,
    relative_strength_index
)
from .metrics import summarize_trades
from .regime import detect_market_regime
from .signals import (
    analyze_macd,
    analyze_momentum,
    analyze_price,
    analyze_rsi,
    analyze_volume,
    calculate_score,
    interpret_score
)
from .strategy import calculate_trade_plan, check_strategy
from .trade import simulate_trade

__version__ = "1.0.0"

__all__ = [
    "BacktestResult",
    "BenchmarkResult",
    "ControlArm",
    "DEFAULT_TICKERS",
    "add_indicators",
    "analyze_asset",
    "analyze_frame",
    "analyze_macd",
    "analyze_momentum",
    "analyze_price",
    "analyze_rsi",
    "analyze_volume",
    "average_true_range",
    "backtest_ticker",
    "benchmark_result",
    "buy_and_hold",
    "build_watchlist",
    "calculate_score",
    "calculate_trade_plan",
    "check_strategy",
    "csv_loader",
    "detect_market_regime",
    "download_prices",
    "eligible_positions",
    "exponential_moving_average",
    "interpret_candlestick",
    "interpret_score",
    "load_prices_from_csv",
    "moving_average_convergence_divergence",
    "prepare_backtest_data",
    "random_control",
    "relative_strength_index",
    "run_backtest",
    "simulate_trade",
    "split_data",
    "summarize_trades",
    "__version__"
]

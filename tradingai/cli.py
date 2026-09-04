"""Command line front end for the TradingAI system."""

import argparse

from .analysis import analyze_asset, build_watchlist
from .backtest import backtest_ticker
from .data import DEFAULT_TICKERS, csv_loader
from .reporting import (
    print_analysis_header,
    print_asset_analysis,
    print_backtest,
    print_watchlist
)

DEFAULT_ACCOUNT_SIZE = 10000
DEFAULT_RISK_PERCENT = 0.01
DEFAULT_REWARD_MULTIPLE = 4.0


def scan(
    tickers,
    account_size=DEFAULT_ACCOUNT_SIZE,
    risk_percent=DEFAULT_RISK_PERCENT,
    period="1y",
    show_history=True,
    loader=None
):
    """Analyze every ticker, then print the ranked watchlist."""

    results = []

    for ticker in tickers:
        print_analysis_header(ticker)

        result = analyze_asset(ticker, period=period, loader=loader)

        if result is None:
            print(f"No usable data found for {ticker}")
            continue

        print_asset_analysis(result, show_history=show_history)
        results.append(result)

    ranked = build_watchlist(results, account_size, risk_percent)

    print_watchlist(ranked)

    return ranked


def backtest(
    tickers,
    data_section="testing",
    reward_multiple=DEFAULT_REWARD_MULTIPLE,
    use_trailing_stop=True,
    period="5y",
    loader=None
):
    """Backtest every ticker and print each readout."""

    print("\n" + "=" * 40)
    print("   Candlestick Study: All Testing")
    print("=" * 40)

    results = []

    for ticker in tickers:
        print(f"\n\n############ {ticker} ############")

        result = backtest_ticker(
            ticker,
            period=period,
            data_section=data_section,
            reward_multiple=reward_multiple,
            use_trailing_stop=use_trailing_stop,
            loader=loader
        )

        if result is None:
            print(f"Not enough backtest data for {ticker}")
            continue

        print_backtest(result)
        results.append(result)

    return results


def build_parser():
    parser = argparse.ArgumentParser(
        prog="tradingai",
        description=(
            "Score a watchlist from indicators and backtest "
            "the entry rules."
        )
    )

    parser.add_argument(
        "command",
        nargs="?",
        default="all",
        choices=["all", "scan", "backtest"],
        help="what to run (default: all)"
    )

    parser.add_argument(
        "--tickers",
        nargs="+",
        default=DEFAULT_TICKERS,
        help="tickers to work on"
    )

    parser.add_argument(
        "--account-size",
        type=float,
        default=DEFAULT_ACCOUNT_SIZE,
        help="account size used for position sizing"
    )

    parser.add_argument(
        "--risk-percent",
        type=float,
        default=DEFAULT_RISK_PERCENT,
        help="fraction of the account risked per trade"
    )

    parser.add_argument(
        "--section",
        default="testing",
        choices=["training", "testing"],
        help="which half of the history to backtest"
    )

    parser.add_argument(
        "--reward-multiple",
        type=float,
        default=DEFAULT_REWARD_MULTIPLE,
        help="profit target in R"
    )

    parser.add_argument(
        "--fixed-stop",
        action="store_true",
        help="disable the trailing stop and hold the original stop"
    )

    parser.add_argument(
        "--csv-dir",
        help=(
            "read <TICKER>.csv from this directory instead of "
            "downloading prices"
        )
    )

    parser.add_argument(
        "--no-history",
        action="store_true",
        help="skip the candle table printed with each analysis"
    )

    return parser


def main(argv=None):
    arguments = build_parser().parse_args(argv)

    loader = None

    if arguments.csv_dir:
        loader = csv_loader(arguments.csv_dir)

    if arguments.command in ("all", "scan"):
        scan(
            arguments.tickers,
            account_size=arguments.account_size,
            risk_percent=arguments.risk_percent,
            show_history=not arguments.no_history,
            loader=loader
        )

    if arguments.command in ("all", "backtest"):
        backtest(
            arguments.tickers,
            data_section=arguments.section,
            reward_multiple=arguments.reward_multiple,
            use_trailing_stop=not arguments.fixed_stop,
            loader=loader
        )

    return 0

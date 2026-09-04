"""Every line the program prints."""

from .metrics import (
    group_by_breakout,
    group_by_candle_score,
    group_by_pattern,
    group_by_setup_type,
    group_performance,
    summarize_trades
)

LINE = "=" * 40


def print_title():
    print("====================================")
    print("      TradingAI")
    print("====================================")


def print_analysis_header(ticker):
    print("\n" + "=" * 50)
    print(f"Analyzing: {ticker}")
    print("=" * 50)


def print_asset_analysis(result, show_history=True):
    """The detailed readout for one analysed asset."""

    print_title()

    if show_history and result.get("History") is not None:
        print(result["History"].tail())

    print("Momentum:", result["Momentum"])
    print("Price:", result["Price"])
    print("RSI:", result["RSI"])
    print("RSI Signal:", result["RSI Signal"])
    print("Volume:", result["Volume"])
    print("MACD:", result["MACD"])
    print("MACD Signal Line:", result["MACD Signal"])
    print("MACD Trend:", result["MACD Trend"])
    print("Trading Score:", result["Score"])
    print("Signal:", result["Signal"])


def print_watchlist(ranked_results):
    """The ranked summary, one block per asset."""

    print("\n" + LINE)
    print("        TradingAI Summary")
    print(LINE)

    for rank, result in enumerate(ranked_results, start=1):
        print(f"\nRank: #{rank}")
        print(f"Ticker: {result['Ticker']}")
        print(f"Strategy: {result['Strategy']}")
        print(f"Strategy Reason: {result['Strategy Reason']}")
        print(f"Score: {result['Score']}")
        print(f"Signal: {result['Signal']}")
        print(f"Momentum: {result['Momentum']}")
        print(f"Price: {result['Price']}")
        print(f"RSI: {result['RSI']} ({result['RSI Signal']})")
        print(f"Volume: {result['Volume']}")
        print(f"MACD Trend: {result['MACD Trend']}")
        print(f"Current Price: ${result['Current Price']:.2f}")
        print(f"ATR: ${result['ATR']:.2f}")

        trade_plan = result.get("Trade Plan")

        if trade_plan is not None:
            print(f"Entry Price: ${trade_plan['Entry Price']:.2f}")
            print(f"Stop Loss: ${trade_plan['Stop Loss']:.2f}")
            print(f"Take Profit: ${trade_plan['Take Profit']:.2f}")
            print(f"Shares: {trade_plan['Shares']}")
            print(
                f"Position Cost: "
                f"${trade_plan['Position Cost']:.2f}"
            )
            print(
                f"Maximum Loss: "
                f"${trade_plan['Maximum Loss']:.2f}"
            )
        else:
            print("Trade Plan: No entry")

        print("-" * 40)


def print_data_split(result):
    description = result.split.describe()

    def as_date(value):
        return value.strftime("%Y-%m-%d")

    print("\n" + LINE)
    print(f"        Data Split: {result.ticker}")
    print(LINE)
    print(
        f"Training Period: "
        f"{as_date(description['Training Start'])} "
        f"through {as_date(description['Training End'])}"
    )
    print(
        f"Testing Period: "
        f"{as_date(description['Testing Start'])} "
        f"through {as_date(description['Testing End'])}"
    )
    print(f"Training Days: {description['Training Days']}")
    print(f"Testing Days: {description['Testing Days']}")


def _print_group_line(name, trades, show_rate=False):
    performance = group_performance(trades)

    if performance["Trades"] == 0:
        print(f"{name}: 0 trades")
        return

    rate = ""

    if show_rate:
        rate = (
            f"Profitable Rate: "
            f"{performance['Profitable Rate']:.2f}% | "
        )

    print(
        f"{name}: "
        f"{performance['Trades']} trades | "
        f"Profitable: {performance['Profitable']} | "
        f"Losses: {performance['Losses']} | "
        f"Breakevens: {performance['Breakevens']} | "
        f"{rate}"
        f"Total: {performance['Total R']:.2f}R | "
        f"Average: {performance['Average R']:.2f}R"
    )


def _print_groups_by_size(groups, show_rate=False):
    ordered = sorted(
        groups.items(),
        key=lambda item: len(item[1]),
        reverse=True
    )

    for name, trades in ordered:
        _print_group_line(name, trades, show_rate=show_rate)


def print_backtest(result):
    """The full backtest readout for one ticker."""

    print_data_split(result)

    print("\n" + LINE)
    print(f"     Signal Backtest: {result.ticker}")
    print(LINE)
    print(f"Trading days tested: {result.trading_days}")
    print(f"Entry signals found: {len(result.entry_signals)}")
    print(
        f"Signals blocked by regime: "
        f"{len(result.blocked_signals)}"
    )

    print("\nMost recent entry signals:")

    if result.entry_signals:
        for signal in result.entry_signals[-5:]:
            print(
                f"{signal['Date'].strftime('%Y-%m-%d')} | "
                f"Price: ${signal['Price']:.2f} | "
                f"Score: {signal['Score']} | "
                f"RSI: {signal['RSI']:.2f} | "
                f"ATR: ${signal['ATR']:.2f} | "
                f"Regime: {signal['Regime']} | "
                f"Candle Score: {signal['Candle Score']} | "
                f"Candle: {signal['Candlestick']} | "
                f"Setup: {signal['Setup Type']} | "
                f"EMA20 Distance: "
                f"{signal['EMA20 Distance ATR']:.2f} ATR"
            )
    else:
        print("No complete entry signals found.")

    print("\nMost recent simulated trades:")

    if result.trades:
        for trade in result.trades[-5:]:
            print(
                f"{trade['Outcome']} | "
                f"({trade['Exit Reason']}) | "
                f"Signal: "
                f"{trade['Signal Date'].strftime('%Y-%m-%d')} | "
                f"Entry: "
                f"{trade['Entry Date'].strftime('%Y-%m-%d')} "
                f"at ${trade['Entry Price']:.2f} | "
                f"Exit: "
                f"{trade['Exit Date'].strftime('%Y-%m-%d')} "
                f"at ${trade['Exit Price']:.2f} | "
                f"Result: {trade['R Multiple']:.2f}R | "
                f"Max Reached: {trade['Highest R Reached']:.2f}R"
            )
    else:
        print("No trades were simulated.")

    statistics = summarize_trades(result.trades)

    print("\n" + LINE)
    print(f"        {result.section_name} Results")
    print(LINE)
    print(f"Total Trades: {statistics['Total Trades']}")
    print(f"Wins: {statistics['Wins']}")
    print(f"Losses: {statistics['Losses']}")
    print(f"Timed Exits: {statistics['Timed Exits']}")
    print(f"Win Rate: {statistics['Win Rate']:.2f}%")
    print(f"Total Result: {statistics['Total R']:.2f}R")
    print(f"Average Result: {statistics['Average R']:.2f}R")
    print(
        f"Average Winner EMA20 Extension: "
        f"{statistics['Average Winner Extension']:.2f} ATR"
    )
    print(f"Profit Target: {result.reward_multiple:.1f}R")
    print(
        f"Average Loser EMA20 Extension: "
        f"{statistics['Average Loser Extension']:.2f} ATR"
    )
    print(
        f"Average Timed Exit EMA20 Extension: "
        f"{statistics['Average Timed Exit Extension']:.2f} ATR"
    )
    print(f"Breakevens: {statistics['Breakevens']}")

    print("\nExit Reasons:")

    for reason, count in statistics["Exit Reasons"].items():
        print(f"{reason}: {count}")

    print("\nCandlestick Score Performance:")

    for name, trades in group_by_candle_score(result.trades).items():
        _print_group_line(name, trades, show_rate=True)

    print("\nNext-Day High Breakout Performance:")

    for name, trades in group_by_breakout(result.trades).items():
        _print_group_line(name, trades)

    print("\nTrader-Style Setup Performance:")

    _print_groups_by_size(group_by_setup_type(result.trades))

    print("\nIndividual Candlestick Patterns:")

    _print_groups_by_size(group_by_pattern(result.trades))

    print(f"Stop Management: {result.stop_method}")

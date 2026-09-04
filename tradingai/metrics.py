"""Aggregate statistics over a list of simulated trades."""


def average_or_zero(values):
    if values:
        return sum(values) / len(values)

    return 0


def group_performance(trades):
    """Count outcomes and R totals for one group of trades."""

    trade_count = len(trades)

    total_r = sum(trade["R Multiple"] for trade in trades)

    profitable = sum(
        1 for trade in trades if trade["R Multiple"] > 0
    )

    losses = sum(
        1 for trade in trades if trade["R Multiple"] < 0
    )

    breakevens = sum(
        1 for trade in trades if trade["R Multiple"] == 0
    )

    if trade_count > 0:
        average_r = total_r / trade_count
        profitable_rate = profitable / trade_count * 100
    else:
        average_r = 0
        profitable_rate = 0

    return {
        "Trades": trade_count,
        "Profitable": profitable,
        "Losses": losses,
        "Breakevens": breakevens,
        "Profitable Rate": profitable_rate,
        "Total R": total_r,
        "Average R": average_r
    }


def group_by_candle_score(trades):
    groups = {
        "Positive": [],
        "Neutral": [],
        "Negative": []
    }

    for trade in trades:
        candle_score = trade["Candle Score"]

        if candle_score > 0:
            groups["Positive"].append(trade)
        elif candle_score < 0:
            groups["Negative"].append(trade)
        else:
            groups["Neutral"].append(trade)

    return groups


def group_by_breakout(trades):
    groups = {
        "High Breakout": [],
        "No High Breakout": []
    }

    for trade in trades:
        if trade["Next-Day High Breakout"]:
            groups["High Breakout"].append(trade)
        else:
            groups["No High Breakout"].append(trade)

    return groups


def group_by_setup_type(trades):
    groups = {}

    for trade in trades:
        groups.setdefault(trade["Setup Type"], []).append(trade)

    return groups


def group_by_pattern(trades):
    """One group per individual pattern name.

    A candle listing several patterns is counted in each of them.
    """

    groups = {}

    for trade in trades:
        for pattern in trade["Candlestick"].split(", "):
            groups.setdefault(pattern, []).append(trade)

    return groups


def count_exit_reasons(trades):
    counts = {}

    for trade in trades:
        reason = trade["Exit Reason"]

        counts[reason] = counts.get(reason, 0) + 1

    return counts


def summarize_trades(trades):
    """Headline numbers for a completed backtest."""

    total_trades = len(trades)

    def count_outcome(name):
        return sum(
            1 for trade in trades if trade["Outcome"] == name
        )

    def extensions_for(name):
        return [
            trade["EMA20 Extension ATR"]
            for trade in trades
            if trade["Outcome"] == name
        ]

    wins = count_outcome("Win")
    total_r = sum(trade["R Multiple"] for trade in trades)

    if total_trades > 0:
        win_rate = (wins / total_trades) * 100
        average_r = total_r / total_trades
    else:
        win_rate = 0
        average_r = 0

    return {
        "Total Trades": total_trades,
        "Wins": wins,
        "Losses": count_outcome("Loss"),
        "Breakevens": count_outcome("Breakeven"),
        "Timed Exits": count_outcome("Timed Exit"),
        "Win Rate": win_rate,
        "Total R": total_r,
        "Average R": average_r,
        "Average Winner Extension": average_or_zero(
            extensions_for("Win")
        ),
        "Average Loser Extension": average_or_zero(
            extensions_for("Loss")
        ),
        "Average Timed Exit Extension": average_or_zero(
            extensions_for("Timed Exit")
        ),
        "Exit Reasons": count_exit_reasons(trades)
    }

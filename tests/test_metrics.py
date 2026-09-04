from tradingai.metrics import (
    average_or_zero,
    count_exit_reasons,
    group_by_breakout,
    group_by_candle_score,
    group_by_pattern,
    group_by_setup_type,
    group_performance,
    summarize_trades
)


def trade(
    r_multiple,
    outcome,
    candle_score=0,
    setup="Momentum",
    patterns="Doji / Indecision",
    breakout=True,
    exit_reason="Profit Target",
    extension=1.0
):
    return {
        "R Multiple": r_multiple,
        "Outcome": outcome,
        "Candle Score": candle_score,
        "Setup Type": setup,
        "Candlestick": patterns,
        "Next-Day High Breakout": breakout,
        "Exit Reason": exit_reason,
        "EMA20 Extension ATR": extension
    }


TRADES = [
    trade(4.0, "Win", candle_score=2, extension=0.5),
    trade(-1.0, "Loss", candle_score=-1, setup="Bearish Warning",
          patterns="Shooting Star, Inside Bar", breakout=False,
          exit_reason="Original Stop", extension=2.5),
    trade(0.0, "Breakeven", exit_reason="Breakeven Stop"),
    trade(0.4, "Timed Exit", candle_score=1, setup="Momentum",
          exit_reason="Timed Exit", extension=1.5)
]


def test_average_or_zero_handles_an_empty_list():
    assert average_or_zero([]) == 0
    assert average_or_zero([1.0, 2.0]) == 1.5


def test_group_performance_counts_outcomes():
    performance = group_performance(TRADES)

    assert performance["Trades"] == 4
    assert performance["Profitable"] == 2
    assert performance["Losses"] == 1
    assert performance["Breakevens"] == 1
    assert performance["Total R"] == 3.4
    assert performance["Average R"] == 0.85
    assert performance["Profitable Rate"] == 50.0


def test_group_performance_of_nothing_is_all_zeros():
    performance = group_performance([])

    assert performance["Trades"] == 0
    assert performance["Average R"] == 0
    assert performance["Profitable Rate"] == 0


def test_candle_score_grouping():
    groups = group_by_candle_score(TRADES)

    assert len(groups["Positive"]) == 2
    assert len(groups["Negative"]) == 1
    assert len(groups["Neutral"]) == 1


def test_breakout_and_setup_grouping():
    breakouts = group_by_breakout(TRADES)

    assert len(breakouts["High Breakout"]) == 3
    assert len(breakouts["No High Breakout"]) == 1

    setups = group_by_setup_type(TRADES)

    assert len(setups["Momentum"]) == 3
    assert len(setups["Bearish Warning"]) == 1


def test_a_multi_pattern_candle_counts_in_every_pattern():
    patterns = group_by_pattern(TRADES)

    assert len(patterns["Doji / Indecision"]) == 3
    assert len(patterns["Shooting Star"]) == 1
    assert len(patterns["Inside Bar"]) == 1


def test_exit_reasons_are_counted():
    counts = count_exit_reasons(TRADES)

    assert counts == {
        "Profit Target": 1,
        "Original Stop": 1,
        "Breakeven Stop": 1,
        "Timed Exit": 1
    }


def test_the_summary_separates_timed_exits_from_wins():
    summary = summarize_trades(TRADES)

    assert summary["Total Trades"] == 4
    assert summary["Wins"] == 1
    assert summary["Losses"] == 1
    assert summary["Breakevens"] == 1
    assert summary["Timed Exits"] == 1
    assert summary["Win Rate"] == 25.0
    assert summary["Total R"] == 3.4
    assert summary["Average R"] == 0.85
    assert summary["Average Winner Extension"] == 0.5
    assert summary["Average Loser Extension"] == 2.5
    assert summary["Average Timed Exit Extension"] == 1.5


def test_an_empty_backtest_summarizes_to_zero():
    summary = summarize_trades([])

    assert summary["Total Trades"] == 0
    assert summary["Win Rate"] == 0
    assert summary["Average R"] == 0
    assert summary["Exit Reasons"] == {}

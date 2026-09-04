import pytest

from tradingai.analysis import analyze_frame, build_watchlist
from tradingai.backtest import (
    prepare_backtest_data,
    run_backtest,
    split_data
)
from tradingai.reporting import print_backtest, print_watchlist

from conftest import make_candles

SETUP_TYPES = {
    "Bullish Rejection",
    "Consolidation",
    "Bullish Pullback",
    "Momentum",
    "Extended Momentum",
    "Bearish Warning",
    "Unclear"
}


def test_preparation_leaves_only_complete_rows(candles):
    prepared = prepare_backtest_data(candles)

    assert not prepared.isna().any().any()

    # The 200-day EMA slope is the slowest column to warm up.
    assert len(prepared) < len(candles)


def test_the_split_keeps_the_newest_fifth_for_testing(candles):
    prepared = prepare_backtest_data(candles)

    split = split_data(prepared)

    assert len(split.training) + len(split.testing) == len(prepared)
    assert len(split.training) == int(len(prepared) * 0.80)
    assert split.training.index[-1] < split.testing.index[0]


def test_an_unknown_section_is_rejected(candles):
    with pytest.raises(ValueError):
        run_backtest("TEST", candles, data_section="everything")


def test_too_little_history_produces_no_result():
    with_two_rows = make_candles(days=2)

    assert run_backtest("TEST", with_two_rows) is None


def test_a_backtest_produces_consistent_trades(candles):
    result = run_backtest(
        "TEST",
        candles,
        data_section="training",
        reward_multiple=4.0
    )

    assert result is not None
    assert result.ticker == "TEST"
    assert result.section_name == "Training"
    assert result.stop_method == "Trailing Stop"
    assert result.trades

    for trade in result.trades:
        # Every entry cleared the score and regime filters.
        assert trade["Score"] >= 3
        assert trade["Regime"] == "Bullish Trend"

        assert trade["Entry Date"] > trade["Signal Date"]
        assert trade["Exit Date"] >= trade["Entry Date"]

        assert trade["Outcome"] in (
            "Win",
            "Loss",
            "Breakeven",
            "Timed Exit"
        )

        for key in ("Setup Type", "Candlestick", "Candle Score"):
            assert key in trade

    entry_dates = [trade["Signal Date"] for trade in result.trades]

    assert entry_dates == sorted(entry_dates)


def test_trades_never_overlap(candles):
    result = run_backtest("TEST", candles, data_section="training")

    previous_exit = None

    for trade in result.trades:
        if previous_exit is not None:
            assert trade["Entry Date"] > previous_exit

        previous_exit = trade["Exit Date"]


def test_every_signal_carries_a_full_candle_reading(candles):
    result = run_backtest("TEST", candles, data_section="training")

    assert result.entry_signals

    for signal in result.entry_signals:
        for key in (
            "Candle Score",
            "Candlestick",
            "Setup Type",
            "EMA20 Distance ATR"
        ):
            assert key in signal

        assert signal["Candlestick"]
        assert signal["Setup Type"] in SETUP_TYPES


def test_a_bearish_market_blocks_entries():
    falling = make_candles(days=700, seed=11, drift=-0.0015)

    result = run_backtest("TEST", falling, data_section="training")

    assert result is not None
    assert result.trades == [] or all(
        trade["Regime"] == "Bullish Trend" for trade in result.trades
    )


def test_a_fixed_stop_changes_the_reported_method(candles):
    result = run_backtest(
        "TEST",
        candles,
        data_section="testing",
        use_trailing_stop=False
    )

    assert result.stop_method == "Fixed Stop"

    for trade in result.trades:
        assert trade["Final Stop Loss"] == pytest.approx(
            trade["Initial Stop Loss"]
        )


def test_the_whole_readout_prints(candles, capsys):
    result = run_backtest("TEST", candles, data_section="testing")

    print_backtest(result)

    printed = capsys.readouterr().out

    assert "Signal Backtest: TEST" in printed
    assert "Out-of-Sample Testing Results" in printed
    assert "Candlestick Score Performance:" in printed
    assert "Individual Candlestick Patterns:" in printed
    assert "Stop Management: Trailing Stop" in printed


def test_analysis_and_watchlist_rank_by_score(candles, capsys):
    rising = analyze_frame("UP", candles)
    falling = analyze_frame(
        "DOWN",
        make_candles(days=400, seed=5, drift=-0.002)
    )

    assert rising is not None
    assert falling is not None

    ranked = build_watchlist([falling, rising], 10000, 0.01)

    assert [result["Ticker"] for result in ranked] == ["UP", "DOWN"]
    assert ranked[0]["Score"] >= ranked[1]["Score"]

    for result in ranked:
        assert result["Strategy"] in ("Enter", "Avoid")

        if result["Strategy"] == "Enter":
            assert result["Trade Plan"]["Shares"] >= 0
        else:
            assert result["Trade Plan"] is None

    print_watchlist(ranked)

    printed = capsys.readouterr().out

    assert "TradingAI Summary" in printed
    assert "Ticker: UP" in printed


def test_analysis_needs_enough_history():
    assert analyze_frame("TEST", make_candles(days=5)) is None

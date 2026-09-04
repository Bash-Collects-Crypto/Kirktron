import numpy as np
import pandas as pd
import pytest

from tradingai.backtest import run_backtest
from tradingai.benchmark import (
    BenchmarkResult,
    ControlArm,
    benchmark_result,
    buy_and_hold,
    eligible_positions,
    percentile_of,
    random_control
)
from tradingai.reporting import print_benchmark


def control_frame(days=60, price=100.0, atr=2.0, bullish=True):
    """A flat frame with the regime columns set by hand."""

    index = pd.date_range("2021-01-01", periods=days, freq="B")

    frame = pd.DataFrame(
        {
            "Open": price,
            "High": price + 1.0,
            "Low": price - 1.0,
            "Close": price,
            "Volume": 1_000_000.0,
            "ATR": atr,
            "EMA_20": price - 1.0,
            "EMA_50": price - 2.0,
            "MACD": 1.0,
            "MACD_SIGNAL": 0.5
        },
        index=index
    )

    if bullish:
        frame["EMA_200"] = price - 5.0
        frame["EMA_200_SLOPE"] = 0.01
    else:
        frame["EMA_200"] = price + 5.0
        frame["EMA_200_SLOPE"] = -0.01

    return frame


def test_percentile_of_reads_the_position_in_a_sample():
    samples = [0.0, 1.0, 2.0, 3.0]

    assert percentile_of(-1.0, samples) == 0.0
    assert percentile_of(2.5, samples) == 75.0
    assert percentile_of(10.0, samples) == 100.0
    assert percentile_of(1.0, []) is None


def test_buy_and_hold_measures_the_section_in_percent_and_r():
    frame = control_frame(days=10)

    frame.iloc[-1, frame.columns.get_loc("Close")] = 130.0

    holding = buy_and_hold(frame)

    assert holding["Entry Price"] == 100.0
    assert holding["Exit Price"] == 130.0
    assert holding["Percent Return"] == pytest.approx(30.0)

    # 30 points over a 1.5 x 2.0 risk unit.
    assert holding["R Equivalent"] == pytest.approx(10.0)


def test_buy_and_hold_survives_a_flat_atr():
    frame = control_frame(days=10, atr=0.0)

    holding = buy_and_hold(frame)

    assert holding["R Equivalent"] == 0.0


def test_eligible_positions_leave_room_for_a_whole_trade():
    frame = control_frame(days=60)

    positions = eligible_positions(frame, max_holding_days=20)

    assert positions
    assert max(positions) == 60 - 20 - 2


def test_eligible_positions_skip_days_outside_the_regime():
    frame = control_frame(days=60, bullish=False)

    assert eligible_positions(frame, regime_only=True) == []
    assert eligible_positions(frame, regime_only=False) != []


def test_eligible_positions_skip_a_flat_atr():
    frame = control_frame(days=60, atr=0.0)

    assert eligible_positions(frame) == []


def test_a_control_arm_runs_the_requested_number_of_times():
    frame = control_frame(days=80)

    arm = random_control(frame, trade_count=5, name="test", runs=25, seed=1)

    assert arm.runs == 25
    assert arm.trade_count == 5
    assert len(arm.average_r_samples) == 25

    summary = arm.summary()

    assert summary["5th"] <= summary["50th"] <= summary["95th"]


def test_a_control_arm_is_reproducible_from_its_seed(candles):
    prepared = run_backtest("TEST", candles, data_section="training")

    first = random_control(
        prepared.section, trade_count=6, name="a", runs=30, seed=99
    )

    second = random_control(
        prepared.section, trade_count=6, name="a", runs=30, seed=99
    )

    different = random_control(
        prepared.section, trade_count=6, name="a", runs=30, seed=100
    )

    assert first.average_r_samples == second.average_r_samples
    assert first.average_r_samples != different.average_r_samples


def test_an_empty_pool_leaves_the_arm_empty():
    frame = control_frame(days=60, bullish=False)

    arm = random_control(frame, trade_count=5, name="test", regime_only=True)

    assert arm.pool_was_empty
    assert arm.summary() is None


def test_a_backtest_without_trades_has_nothing_to_compare(candles):
    result = run_backtest("TEST", candles, data_section="training")

    result.trades = []

    assert benchmark_result(result) is None


def test_the_benchmark_compares_both_arms(candles):
    result = run_backtest("TEST", candles, data_section="training")

    benchmark = benchmark_result(result, runs=40, seed=3)

    assert benchmark is not None
    assert benchmark.ticker == "TEST"
    assert benchmark.strategy_trades == len(result.trades)

    assert benchmark.strategy_total_r == pytest.approx(
        sum(trade["R Multiple"] for trade in result.trades)
    )

    names = [arm.name for arm in benchmark.arms]

    assert names == [
        "Random entries, any day",
        "Random entries, bullish regime"
    ]

    for name in names:
        percentile = benchmark.percentile_against(name)

        assert 0.0 <= percentile <= 100.0

    assert benchmark.percentile_against("nothing named this") is None


def test_the_arms_are_drawn_from_different_streams(candles):
    result = run_backtest("TEST", candles, data_section="training")

    benchmark = benchmark_result(result, runs=40, seed=7)

    any_day, in_regime = benchmark.arms

    assert any_day.average_r_samples != in_regime.average_r_samples


def make_benchmark(strategy_average_r, samples):
    """A benchmark with the regime arm's distribution set by hand."""

    return BenchmarkResult(
        ticker="TEST",
        section_name="Training",
        strategy_trades=len(samples),
        strategy_total_r=strategy_average_r * len(samples),
        strategy_average_r=strategy_average_r,
        buy_and_hold={
            "Start Date": pd.Timestamp("2021-01-01"),
            "End Date": pd.Timestamp("2021-12-31"),
            "Entry Price": 100.0,
            "Exit Price": 110.0,
            "Percent Return": 10.0,
            "R Equivalent": 3.3
        },
        arms=[
            ControlArm(
                name="Random entries, bullish regime",
                runs=len(samples),
                trade_count=10,
                average_r_samples=list(samples)
            )
        ]
    )


def test_a_strategy_above_the_distribution_clears_the_bar():
    samples = list(np.linspace(-1.0, 1.0, 100))

    verdict = make_benchmark(2.0, samples).verdict

    assert "beat 100%" in verdict
    assert "does not show an edge" not in verdict


def test_a_middling_strategy_is_called_middling():
    samples = list(np.linspace(-1.0, 1.0, 100))

    verdict = make_benchmark(0.0, samples).verdict

    assert "does not show an edge" in verdict


def test_a_suggestive_strategy_is_not_oversold():
    samples = list(np.linspace(0.0, 1.0, 100))

    verdict = make_benchmark(0.85, samples).verdict

    assert "suggestive" in verdict


def test_an_empty_arm_leaves_the_verdict_honest():
    benchmark = make_benchmark(1.0, [])

    assert "No comparable random entries" in benchmark.verdict


def test_the_comparison_prints(candles, capsys):
    result = run_backtest("TEST", candles, data_section="training")

    print_benchmark(benchmark_result(result, runs=20, seed=5))

    printed = capsys.readouterr().out

    assert "Control Comparison: TEST" in printed
    assert "Buy and Hold:" in printed
    assert "Random entries, any day" in printed
    assert "Random entries, bullish regime" in printed
    assert "Reading:" in printed


def test_printing_nothing_to_compare_says_so(capsys):
    print_benchmark(None)

    assert "nothing to compare" in capsys.readouterr().out

import pytest

from tradingai.strategy import calculate_trade_plan, check_strategy


def entry_result(**overrides):
    result = {
        "Score": 4,
        "Momentum": "Bullish",
        "MACD Trend": "Bullish",
        "RSI": 55.0,
        "Current Price": 100.0,
        "ATR": 2.0
    }

    result.update(overrides)

    return result


def test_a_clean_result_is_allowed_to_enter():
    strategy, reason = check_strategy(entry_result())

    assert strategy == "Enter"
    assert reason == "All entry conditions passed"


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"Score": 2}, "Score is below 3"),
        ({"Momentum": "Bearish"}, "Momentum is bearish"),
        ({"MACD Trend": "Bearish"}, "MACD is bearish"),
        ({"RSI": 70.0}, "RSI is overbought")
    ]
)
def test_each_condition_can_block_an_entry(overrides, reason):
    strategy, blocked_reason = check_strategy(
        entry_result(**overrides)
    )

    assert strategy == "Avoid"
    assert blocked_reason == reason


def test_trade_plan_sizes_the_position_from_risk():
    plan = calculate_trade_plan(
        entry_result(),
        account_size=10000,
        risk_percent=0.01
    )

    # 1.5 ATR below a $100 entry.
    assert plan["Stop Loss"] == 97.0
    assert plan["Take Profit"] == 106.0

    # $100 of risk over $3 per share.
    assert plan["Shares"] == 33
    assert plan["Position Cost"] == 3300.0
    assert plan["Maximum Loss"] == 99.0


def test_trade_plan_is_capped_by_available_cash():
    plan = calculate_trade_plan(
        entry_result(**{"Current Price": 500.0, "ATR": 1.0}),
        account_size=10000,
        risk_percent=0.10
    )

    # Risk alone would allow 666 shares; cash allows 20.
    assert plan["Shares"] == 20


def test_trade_plan_refuses_to_size_without_a_stop_distance():
    plan = calculate_trade_plan(
        entry_result(ATR=0.0),
        account_size=10000,
        risk_percent=0.01
    )

    assert plan["Shares"] == 0
    assert plan["Position Cost"] == 0.0
    assert plan["Maximum Loss"] == 0.0

import pandas as pd
import pytest

from tradingai.trade import simulate_trade


def trade_frame(rows, ema20=100.0, ema50=99.0, atr=2.0,
                macd=1.0, macd_signal=0.5):
    index = pd.date_range("2021-01-01", periods=len(rows), freq="B")

    frame = pd.DataFrame(
        rows,
        columns=["Open", "High", "Low", "Close"],
        index=index
    )

    frame["Volume"] = 1_000_000.0
    frame["ATR"] = atr
    frame["EMA_20"] = ema20
    frame["EMA_50"] = ema50
    frame["MACD"] = macd
    frame["MACD_SIGNAL"] = macd_signal

    return frame


def flat_rows(count, price=100.0):
    return [(price, price + 0.1, price - 0.1, price)] * count


def test_no_entry_without_a_following_candle():
    frame = trade_frame(flat_rows(1))

    assert simulate_trade(frame, 0, atr=2.0) is None


def test_no_entry_without_a_complete_holding_period():
    frame = trade_frame(flat_rows(10))

    assert simulate_trade(frame, 0, atr=2.0, max_holding_days=20) is None


def test_no_entry_without_a_stop_distance():
    frame = trade_frame(flat_rows(30))

    assert simulate_trade(frame, 0, atr=0.0) is None


def test_the_original_stop_is_a_one_r_loss():
    rows = flat_rows(30)

    # The second candle after the signal digs through the stop.
    rows[2] = (100.0, 100.5, 96.0, 96.5)

    frame = trade_frame(rows)

    trade = simulate_trade(frame, 0, atr=2.0)

    assert trade["Exit Reason"] == "Original Stop"
    assert trade["Outcome"] == "Loss"
    assert trade["Exit Price"] == pytest.approx(97.0)
    assert trade["R Multiple"] == pytest.approx(-1.0)


def test_a_gap_below_the_stop_exits_at_the_open():
    rows = flat_rows(30)

    rows[2] = (95.0, 95.5, 94.0, 94.5)

    frame = trade_frame(rows)

    trade = simulate_trade(frame, 0, atr=2.0)

    assert trade["Exit Reason"] == "Original Stop"
    assert trade["Exit Price"] == pytest.approx(95.0)
    assert trade["R Multiple"] == pytest.approx(-5.0 / 3.0)


def test_the_profit_target_pays_the_reward_multiple():
    rows = flat_rows(30)

    rows[3] = (100.0, 113.0, 99.9, 112.5)

    frame = trade_frame(rows)

    trade = simulate_trade(frame, 0, atr=2.0, reward_multiple=4.0)

    assert trade["Exit Reason"] == "Profit Target"
    assert trade["Outcome"] == "Win"
    assert trade["Exit Price"] == pytest.approx(112.0)
    assert trade["R Multiple"] == pytest.approx(4.0)


def test_a_gap_above_the_target_exits_at_the_open():
    rows = flat_rows(30)

    rows[3] = (115.0, 116.0, 114.0, 115.5)

    frame = trade_frame(rows)

    trade = simulate_trade(frame, 0, atr=2.0, reward_multiple=4.0)

    assert trade["Exit Reason"] == "Profit Target"
    assert trade["Exit Price"] == pytest.approx(115.0)
    assert trade["R Multiple"] == pytest.approx(5.0)


def test_a_stop_and_a_target_in_one_candle_assume_the_stop():
    rows = flat_rows(30)

    rows[2] = (100.0, 113.0, 96.0, 100.0)

    frame = trade_frame(rows)

    trade = simulate_trade(frame, 0, atr=2.0, reward_multiple=4.0)

    assert trade["Exit Reason"] == "Original Stop"
    assert trade["R Multiple"] == pytest.approx(-1.0)


def test_a_quiet_trade_ends_with_a_timed_exit():
    frame = trade_frame(flat_rows(30))

    trade = simulate_trade(frame, 0, atr=2.0, max_holding_days=20)

    assert trade["Exit Reason"] == "Timed Exit"
    assert trade["Outcome"] == "Timed Exit"
    assert trade["Exit Position"] == 20


def test_the_stop_moves_to_breakeven_after_one_and_a_half_r():
    rows = flat_rows(30)

    # +2R intraday lifts the stop to the entry price,
    # and the next candle trades back down through it.
    rows[2] = (100.0, 106.0, 99.5, 105.0)
    rows[3] = (100.5, 100.8, 96.0, 96.5)

    frame = trade_frame(rows)

    trade = simulate_trade(frame, 0, atr=2.0, reward_multiple=8.0)

    assert trade["Exit Reason"] == "Breakeven Stop"
    assert trade["Exit Price"] == pytest.approx(100.0)
    assert trade["R Multiple"] == pytest.approx(0.0)
    assert trade["Outcome"] == "Breakeven"


def test_the_stop_locks_in_one_r_after_two_and_a_half_r():
    rows = flat_rows(30)

    # +2.67R stays under the +3R trailing trigger.
    rows[2] = (100.0, 108.0, 99.5, 107.0)
    rows[3] = (105.0, 105.5, 100.0, 100.5)

    frame = trade_frame(rows)

    trade = simulate_trade(frame, 0, atr=2.0, reward_multiple=8.0)

    assert trade["Exit Reason"] == "+1R Stop"
    assert trade["Exit Price"] == pytest.approx(103.0)
    assert trade["R Multiple"] == pytest.approx(1.0)


def test_the_trailing_stop_takes_over_after_three_r():
    rows = flat_rows(30)

    rows[2] = (100.0, 110.0, 99.5, 110.0)
    rows[3] = (109.0, 109.5, 105.0, 105.5)

    frame = trade_frame(rows, ema20=104.0, ema50=103.0)

    trade = simulate_trade(frame, 0, atr=2.0, reward_multiple=8.0)

    # Strong conditions trail two ATR below the highest close.
    assert trade["Exit Reason"] == "ATR Trailing Stop"
    assert trade["Exit Price"] == pytest.approx(106.0)
    assert trade["R Multiple"] == pytest.approx(2.0)


def test_a_fixed_stop_never_ratchets_upward():
    rows = flat_rows(30)

    rows[2] = (100.0, 110.0, 99.5, 110.0)
    rows[3] = (109.0, 109.5, 105.0, 105.5)

    frame = trade_frame(rows)

    trade = simulate_trade(
        frame,
        0,
        atr=2.0,
        reward_multiple=8.0,
        use_trailing_stop=False
    )

    assert trade["Final Stop Loss"] == pytest.approx(97.0)
    assert trade["Exit Reason"] == "Timed Exit"
    assert trade["Highest R Reached"] == pytest.approx(10.0 / 3.0)

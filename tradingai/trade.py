"""Forward simulation of a single long trade."""

STOP_ATR_MULTIPLIER = 1.5

BREAKEVEN_TRIGGER_R = 1.5
ONE_R_TRIGGER_R = 2.5
TRAILING_TRIGGER_R = 3.0


def _stop_reason(
    active_stop,
    entry_price,
    initial_stop_distance,
    trailing_stop_active
):
    """Name the stop that is actually being hit."""

    if trailing_stop_active:
        return "ATR Trailing Stop"

    if active_stop >= entry_price + initial_stop_distance:
        return "+1R Stop"

    if active_stop >= entry_price:
        return "Breakeven Stop"

    return "Original Stop"


def simulate_trade(
    asset,
    signal_position,
    atr,
    reward_multiple=4.0,
    max_holding_days=20,
    use_trailing_stop=True
):
    """Enter on the open after the signal and manage the trade forward.

    Returns ``None`` when there is no next day to enter on, or when the
    holding period would run past the end of the data.
    """

    entry_position = signal_position + 1

    # There must be another day available to enter.
    if entry_position >= len(asset):
        return None

    entry_row = asset.iloc[entry_position]
    entry_date = asset.index[entry_position]
    entry_price = float(entry_row["Open"])

    initial_stop_distance = atr * STOP_ATR_MULTIPLIER

    # Without a stop distance there is no risk unit to measure against.
    if initial_stop_distance <= 0:
        return None

    initial_stop_loss = entry_price - initial_stop_distance

    current_stop_loss = initial_stop_loss

    take_profit = (
        entry_price
        + initial_stop_distance * reward_multiple
    )

    final_position = entry_position + max_holding_days - 1

    # Reject trades without a complete holding period.
    if final_position >= len(asset):
        return None

    highest_close = entry_price
    highest_r_reached = 0.0

    trailing_stop_active = False

    exit_price = None
    exit_date = None
    exit_position = None
    exit_reason = None

    for position in range(entry_position, final_position + 1):
        row = asset.iloc[position]
        current_date = asset.index[position]

        current_open = float(row["Open"])
        current_high = float(row["High"])
        current_low = float(row["Low"])
        current_close = float(row["Close"])
        current_atr = float(row["ATR"])

        current_ema20 = float(row["EMA_20"])
        current_ema50 = float(row["EMA_50"])
        current_macd = float(row["MACD"])
        current_macd_signal = float(row["MACD_SIGNAL"])

        # Measure today's maximum progress.
        current_high_r = (
            current_high - entry_price
        ) / initial_stop_distance

        highest_r_reached = max(highest_r_reached, current_high_r)

        # This stop was established on a previous candle.
        active_stop = current_stop_loss

        # Handle a gap below the stop.
        if current_open <= active_stop:
            exit_price = current_open
            exit_date = current_date
            exit_position = position

            exit_reason = _stop_reason(
                active_stop,
                entry_price,
                initial_stop_distance,
                trailing_stop_active
            )

            break

        # Handle a gap above the target.
        if current_open >= take_profit:
            exit_price = current_open
            exit_date = current_date
            exit_position = position
            exit_reason = "Profit Target"
            break

        hit_stop = current_low <= active_stop
        hit_target = current_high >= take_profit

        # Conservative assumption when both levels
        # are touched during the same daily candle.
        if hit_stop:
            exit_price = active_stop
            exit_date = current_date
            exit_position = position

            exit_reason = _stop_reason(
                active_stop,
                entry_price,
                initial_stop_distance,
                trailing_stop_active
            )

            break

        if hit_target:
            exit_price = take_profit
            exit_date = current_date
            exit_position = position
            exit_reason = "Profit Target"
            break

        # No exit occurred today.
        # Update information at today's close.
        highest_close = max(highest_close, current_close)

        next_stop_loss = current_stop_loss

        # These stop changes become active
        # on the following candle.
        if use_trailing_stop:

            # At +1.5R, remove the initial risk.
            if highest_r_reached >= BREAKEVEN_TRIGGER_R:
                next_stop_loss = max(next_stop_loss, entry_price)

            # At +2.5R, lock in at least +1R.
            if highest_r_reached >= ONE_R_TRIGGER_R:
                one_r_stop = entry_price + initial_stop_distance

                next_stop_loss = max(next_stop_loss, one_r_stop)

            # At +3R, begin ATR-based trailing.
            if highest_r_reached >= TRAILING_TRIGGER_R:
                strong_conditions = (
                    current_close > current_ema20
                    and current_ema20 > current_ema50
                    and current_macd > current_macd_signal
                )

                if strong_conditions:
                    trail_atr_multiplier = 2.0
                else:
                    trail_atr_multiplier = 1.0

                atr_trailing_stop = (
                    highest_close
                    - current_atr * trail_atr_multiplier
                )

                next_stop_loss = max(next_stop_loss, atr_trailing_stop)

                trailing_stop_active = True

        # The stop can rise but never move downward.
        current_stop_loss = max(current_stop_loss, next_stop_loss)

    # If no stop or target was reached,
    # exit at the end of the holding period.
    if exit_price is None:
        final_row = asset.iloc[final_position]

        exit_price = float(final_row["Close"])
        exit_date = asset.index[final_position]
        exit_position = final_position
        exit_reason = "Timed Exit"

    initial_risk_per_share = entry_price - initial_stop_loss

    profit_per_share = exit_price - entry_price

    r_multiple = profit_per_share / initial_risk_per_share

    if exit_reason == "Timed Exit":
        outcome = "Timed Exit"
    elif r_multiple > 0:
        outcome = "Win"
    elif r_multiple < 0:
        outcome = "Loss"
    else:
        outcome = "Breakeven"

    return {
        "Entry Date": entry_date,
        "Entry Price": entry_price,
        "Initial Stop Loss": initial_stop_loss,
        "Final Stop Loss": current_stop_loss,
        "Take Profit": take_profit,
        "Exit Date": exit_date,
        "Exit Price": exit_price,
        "Exit Position": exit_position,
        "Outcome": outcome,
        "Exit Reason": exit_reason,
        "R Multiple": r_multiple,
        "Highest R Reached": highest_r_reached
    }

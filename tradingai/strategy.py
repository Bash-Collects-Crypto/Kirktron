"""Entry rules and position sizing."""

STOP_ATR_MULTIPLIER = 1.5
MINIMUM_ENTRY_SCORE = 3


def check_strategy(result):
    """Decide whether an analysis result clears every entry condition."""

    if result["Score"] < MINIMUM_ENTRY_SCORE:
        return "Avoid", "Score is below 3"

    if result["Momentum"] != "Bullish":
        return "Avoid", "Momentum is bearish"

    if result["MACD Trend"] != "Bullish":
        return "Avoid", "MACD is bearish"

    if result["RSI"] >= 70:
        return "Avoid", "RSI is overbought"

    return "Enter", "All entry conditions passed"


def calculate_trade_plan(
    result,
    account_size,
    risk_percent,
    reward_multiple=2.0
):
    """Build a stop, a target and a share count from ATR and risk."""

    entry_price = result["Current Price"]
    atr = result["ATR"]

    stop_distance = atr * STOP_ATR_MULTIPLIER

    stop_loss = entry_price - stop_distance

    take_profit = entry_price + (stop_distance * reward_multiple)

    money_at_risk = account_size * risk_percent
    risk_per_share = entry_price - stop_loss

    # A flat ATR would leave nothing to size against.
    if risk_per_share <= 0 or entry_price <= 0:
        shares = 0
    else:
        shares_by_risk = int(money_at_risk / risk_per_share)
        shares_by_cash = int(account_size / entry_price)

        shares = min(shares_by_risk, shares_by_cash)

    return {
        "Entry Price": round(entry_price, 2),
        "Stop Loss": round(stop_loss, 2),
        "Take Profit": round(take_profit, 2),
        "Shares": shares,
        "Position Cost": round(shares * entry_price, 2),
        "Maximum Loss": round(shares * risk_per_share, 2)
    }

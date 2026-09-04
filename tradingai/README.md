# TradingAI

TradingAI scores a watchlist from daily candles and replays the same entry
rules over history so the rules can be judged before they are traded.

Two things run from one entry point:

- **Scan** — download a year of candles per ticker, read five indicators on
  the newest complete candle, score them, and rank the watchlist. Every
  ticker that clears the entry rules also gets a stop, a target and a share
  count sized to a fixed fraction of the account.
- **Backtest** — download five years, split the history 80/20, and replay
  the entry rules over one half. Each signal becomes a simulated trade with
  a managed stop, and the trades are grouped by candle score, setup type,
  next-day breakout and individual pattern.

### Running it

```bash
pip install -r requirements.txt

python main.py                       # scan the default tickers, then backtest
python main.py scan                  # just the ranked watchlist
python main.py backtest --section training
python main.py --tickers NVDA BTC-USD --account-size 25000 --risk-percent 0.005
python main.py backtest --reward-multiple 3 --fixed-stop
python main.py --csv-dir ./prices    # read <TICKER>.csv instead of downloading
python main.py backtest --controls --seed 1   # compare against the controls
```

`python -m tradingai` and the installed `tradingai` command take the same
arguments. `--csv-dir` reads `<TICKER>.csv` (a date index plus Open, High,
Low, Close, Volume) so a run is reproducible and works without network
access.

### How a decision is made

**The score.** Five readings on the newest candle, worth `-5` to `+6`:

| Reading | Rule | Score |
| --- | --- | --- |
| Momentum | EMA20 above EMA50 | ±2 |
| RSI | below 30 / above 70 | +1 / -1 |
| Volume | above the 20-day average | +1 |
| Price | above EMA20 | ±1 |
| MACD | line above signal | ±1 |

`+3` and up reads as a Strong Buy, down through `-3` as a Strong Sell.

**The entry rules.** A signal has to clear all four: a score of at least 3,
bullish momentum, a bullish MACD, and an RSI under 70. In the backtest a
fifth filter applies — price above a rising EMA200 with EMA50 above it, so
long entries are only taken inside a bullish regime.

**The trade.** Entry is the next day's open. The initial stop sits 1.5 ATR
below it and the target is a multiple of that risk (4R in the backtest, 2R
in the live trade plan). With the trailing stop enabled the stop ratchets
up, never down, and only takes effect on the following candle:

- at +1.5R it moves to breakeven,
- at +2.5R it locks in +1R,
- at +3R it trails the highest close by 1 ATR, or 2 ATR while price holds
  above a rising EMA20 with a bullish MACD.

A trade that reaches neither level within 20 trading days is closed at the
close as a *Timed Exit*. When a candle touches both the stop and the target,
the simulation assumes the stop. Only one position is open at a time.

**Position sizing.** Shares are the smaller of what the risk budget allows
(`account size × risk percent ÷ risk per share`) and what the cash allows.

### Reading a backtest honestly

`--controls` is the part that says whether the entry rules did anything. A
positive R total on its own proves very little: a long-only strategy gated
on a bullish regime will show a profit in a rising market whatever its entry
rules say. The flag adds three arms over the same section:

- **Buy and hold** — held from the section's first open to its last close,
  reported in percent and in the same 1.5-ATR risk unit the trades use.
- **Random entries, any day** — the same number of trades, taken at random,
  managed by the same stop and target rules.
- **Random entries, bullish regime only** — the same, drawn only from days
  the regime filter already allows.

The third arm is the one that matters. It holds the regime filter constant,
so whatever separates the strategy from it is the entry signal itself. The
report says which percentile of that distribution the strategy landed in,
and will say plainly when the answer is "no edge beyond the regime filter".

Two cautions the report cannot enforce:

- **Sample size.** One position at a time with 20-day holds caps you near 12
  trades per ticker per year, and the testing split is one year of a
  five-year download. Averages over that few trades are mostly noise.
- **Costs.** Nothing here charges commission, spread or slippage, and
  next-day-open fills are optimistic. The marginal setups are the ones those
  costs remove first.

Random control entries are drawn without replacement but simulated
independently, so unlike the strategy's trades they may overlap in time.
That widens the distribution; it does not move its centre.

### Layout

| Module | Responsibility |
| --- | --- |
| `tradingai/indicators.py` | EMA, RSI, MACD, ATR and the column set they produce |
| `tradingai/data.py` | Downloading candles, CSV loading, column flattening |
| `tradingai/signals.py` | Indicator readings and the score |
| `tradingai/candles.py` | Candlestick patterns, candle score, setup type |
| `tradingai/regime.py` | Bullish / bearish / sideways regime |
| `tradingai/strategy.py` | Entry rules and position sizing |
| `tradingai/trade.py` | Forward simulation of one managed trade |
| `tradingai/backtest.py` | Data split and the historical replay |
| `tradingai/benchmark.py` | Buy-and-hold and random-entry control arms |
| `tradingai/metrics.py` | Grouping and summary statistics |
| `tradingai/analysis.py` | Scoring one asset, ranking the watchlist |
| `tradingai/reporting.py` | Every printed line |
| `tradingai/cli.py` | Argument parsing and the two commands |

Calculation is kept apart from printing: `run_backtest` returns a
`BacktestResult` and `reporting.print_backtest` renders it, so the numbers
can be used from a notebook or another program without capturing stdout.

### Indicators

RSI, MACD and ATR are ports of the formulas in the [`ta`](https://github.com/bukosabino/ta)
library — Wilder's RSI over `ewm(alpha=1/14)`, the 12/26/9 MACD, and
Wilder's ATR seeded with the mean of the first 14 true ranges (which is why
the first 13 ATR values are zero rather than missing). `ta` no longer builds
against current setuptools, so the formulas live in `indicators.py` instead
of being imported. `tests/test_indicators.py` cross-checks them against `ta`
directly and skips when it is not installed.

### Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

The suite runs on generated candles and never touches the network.

### Notes on this implementation

Behaviour follows the original script, with these deliberate changes:

- A candle with no history before it, or with a zero range, now returns the
  full set of keys. The original returned a shorter dictionary, and the
  backtest raised `KeyError: 'Setup Type'` the first time it met one.
- Sizing a position, measuring EMA20 extension, and simulating a trade all
  guard against a zero ATR instead of dividing by zero.
- The duplicated stop-exit branches share one `_stop_reason` helper, and the
  "profit Target: 4.0r" line reads `Profit Target: 4.0R`.
- `analyze_asset` and `backtest_ticker` take an optional `loader`, which is
  what `--csv-dir` and the tests use in place of a download.

Nothing here is financial advice; it is a rule tester.

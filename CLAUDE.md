# Kirktron — crypto paper trader

Simulated trading against live CoinGecko data. Four independent $10,000 books.
Nothing here touches real money or a real exchange.

**Read `FINDINGS.md` before proposing any strategy change.** It records what the
live data has already shown, including changes that were analysed and rejected,
so the same ground is not re-covered.

## Layout

| file | role |
|---|---|
| `paper_trader.py` | the engine: universe filtering, strategies, exits, pattern model |
| `intraday.py` | 5-minute bars and indicators for the day-trading book |
| `dashboard_export.py` / `build_dashboard.py` / `dashboard.html` | the live dashboard |
| `snapshot.sh` | records the trading data to the `kirktron-trading-data` branch |
| `run_trader.sh` | supervisor with a PID lock and restart backoff |
| `FINDINGS.md` | what the data has shown, with sample sizes |

## The four books

| book | universe | direction | hold | stop / target | costs |
|---|---|---|---|---|---|
| conservative | rank <= 30 | long | <= 168h | 3% / 9% | none |
| aggressive | rank <= 150 | long | <= 48h | 8% / 22% | none |
| longshort | rank <= 50 | both | <= 48h | 5% / 12% | none |
| daytrade | rank <= 25, 5-min bars | both | <= 6h | 1.2% / 2.5% | 15bps/side |

`daytrade` is the only book charged trading costs, so **its P/L is not directly
comparable** to the others — it carries a handicap they do not.

## Rules that matter

- **The universe is layer-1 chains and blue chips only.** No meme coins,
  stablecoins, wrapped/staked derivatives or tokenized real-world assets.
  Verify any time with `python3 paper_trader.py --audit`.
- **Category filtering matches on CoinGecko id, never symbol.** Wrapped tokens
  reuse the underlying's ticker; symbol matching once excluded BTC, ETH and SOL.
- **An inclusion list that fails to load fails OPEN.** If the layer-1 allowlist
  cannot be fetched the universe silently widens. The code warns loudly; treat
  that warning as urgent.
- **A moon is a closed trade that delivered its full thesis**, set just under
  each book's take-profit — not a flat percentage. A pattern model activates at
  20 resolved trades including 4 moons.
- **Do not change strategy parameters without the owner's say-so.** Correctness
  bugs (a meme coin reaching the universe, a P/L or fee accounting error, a
  schema mismatch, a cache that cannot reach coverage) are bugs, not strategy
  changes — fix those and say what was done.

## Running it

```bash
python3 paper_trader.py --duration 260 --interval 60   # a bounded live run
python3 paper_trader.py --report                        # all four books
python3 paper_trader.py --audit                         # prove the universe is clean
./snapshot.sh                                           # persist the record
```

The container is ephemeral and background processes do not survive it, so the
trader is run in bounded foreground segments and the record is pushed to the
`kirktron-trading-data` branch. Code changes go to the feature branch and
PR #1; trading data never does, or the diff becomes unreviewable.

## What gets recorded

- `trade_log.csv` — every fill, with the full feature vector at entry and the
  outcome. This is what the pattern models learn from.
- `equity_history.csv` — one row per cycle per book, the equity curve.
- `market_context.csv` — one row per cycle: breadth, median and decile 24h
  moves, BTC/ETH, total volume. Without it a later analysis cannot separate
  "bad setup" from "bad market".
- `state_<book>.json` — checkpointed positions, cash, counters, fees.

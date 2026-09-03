# Kirktron

Crypto paper trader: watches the real market via the CoinGecko public API for
consistently positive momentum and simulates trading it with two independently
managed $10,000 portfolios. Meme coins, stablecoins and wrapped/staked
derivatives are excluded by blacklist.

## The two strategies

|                    | conservative              | aggressive                  |
|--------------------|---------------------------|-----------------------------|
| universe           | market-cap rank <= 30     | rank <= 150                 |
| min 24h volume     | $50M                      | $10M                        |
| entry              | positive on 1h/24h/7d/14d/30d | 1h & 24h strong, 7d positive |
| position size      | 10% of initial ($1,000)   | 22% of initial ($2,200)     |
| max positions      | 6 (>= 25% cash reserve)   | 4 (>= 5% cash reserve)      |
| stop loss          | 3%                        | 8%                          |
| take profit        | 9%                        | 22%                         |
| trailing stop      | arms at +5%, gives back 2.5% | arms at +12%, gives back 7% |
| max hold           | 168h                      | 96h                         |
| re-entry cooldown  | 4h                        | 2h                          |

Both also exit on momentum breakdown, and both refuse candidates that are
already parabolic (an overheat ceiling per timeframe) — the goal is to join a
trend, not to buy the top of a vertical move.

## Pattern model

Each portfolio keeps a lightweight per-strategy model over the entry feature
vectors of its closed trades. A **resolved** trade is a closed (sold) position;
a **moon** is a resolved trade with a realized gain of **>= 50%**.

The model activates once a strategy has **>= 20 resolved trades** of which
**>= 4 were moons**. Once active it standardizes every resolved trade's entry
features, takes the centroid of the moon group and of the non-moon group, and
scores new candidates by how much closer they sit to the moon centroid than to
the non-moon one. That similarity becomes a bounded bonus (+/- 2.5) on the
entry score, so setups resembling past winners get ranked up. It is a plain
centroid heuristic — no sklearn, no training loop.

## Running it

```bash
python3 paper_trader.py            # run forever
python3 paper_trader.py --once     # a single cycle
python3 paper_trader.py --report   # summary of both portfolios
nohup ./run_trader.sh &             # supervised, auto-restarts on a crash
touch STOP                          # stop after the current run
```

Polls every 5 minutes. State is checkpointed to `state_<strategy>.json` after
every cycle (atomic writes), so a crash or restart resumes exactly where it
left off. Every fill is appended to `trade_log.csv` along with the momentum
features that triggered it.

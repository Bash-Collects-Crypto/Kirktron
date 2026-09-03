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
python3 paper_trader.py --audit    # prove the universe is real crypto, no memes
./snapshot.sh                      # commit + push the trading record
touch STOP                          # stop after the current run
```

Polls every 5 minutes. State is checkpointed to `state_<strategy>.json` after
every cycle (atomic writes), so a crash or restart resumes exactly where it
left off. Every fill is appended to `trade_log.csv` along with the momentum
features that triggered it.

## What we exclude, and how

The universe must be real crypto — never meme coins, stablecoins, wrapped or
staked derivatives, or tokenized real-world assets. A hand-maintained symbol
blacklist could not hold that line: new memes list constantly, and symbols are
not unique. So the primary filter is **CoinGecko's own categorization**
(`meme-token`, `stablecoins`, `liquid-staking-tokens`, `wrapped-tokens`),
pulled live and cached for 6 hours. The curated static lists remain as a floor.

Two details that matter:

- **Category matching is by CoinGecko id, never by symbol.** Wrapped and
  bridged tokens reuse the underlying's ticker (`wrapped-solana` is symbol
  `SOL`), so symbol matching excluded BTC, ETH and SOL from the universe.
- **A failed category refresh keeps the previous list** rather than trading
  blind. A total failure never opens the gates.

Backstopping both is a **peg detector**: if a coin's largest move across every
timeframe is under 1.5%, it is riding a peg, not a trend. Tokenized treasuries
measure 0.03–1.2% there; real crypto measures 15–26%.

Run `python3 paper_trader.py --audit` to see exactly what was excluded, why,
and what each strategy can currently trade. As of the last audit that filtered
88 of 250 coins, including DOGE, SHIB, PEPE, TRUMP, PENGU, BONK, FLOKI, WIF,
FARTCOIN, MemeCore, pump.fun and CASHCAT.

## The trading record in git

This container is ephemeral, so `trade_log.csv` and the `state_*.json` files
are the only durable record of a run. `./snapshot.sh` commits and pushes them,
and runs hourly, so the history survives the container and the git log doubles
as a performance timeline.

## The long/short book

A third portfolio, `longshort`, trades the same blue-chip universe in either
direction. The conservative and aggressive books stay long-only, so this
isolates whether shorting adds anything rather than muddying a record that
already exists.

|                | longshort                                  |
|----------------|--------------------------------------------|
| universe       | rank <= 50, layer-1/blue-chip, $25M volume  |
| long entry     | 1h > +0.3%, 24h > +1.5%, 7d >= 0            |
| short entry    | 1h < -0.3%, 24h < -1.5%, 7d <= 0            |
| position size  | 15% of initial ($1,500), max 5 concurrent   |
| stop / target  | 5% / 12%, trailing arms at +7% (gives 3.5%) |
| max hold       | 48h, 2h re-entry cooldown                   |

Returns are measured **on capital**, so a short that falls is a gain and every
exit rule reads identically for both directions. A short posts its notional as
collateral at entry; covering returns the collateral with the P/L attached,
which bounds the loss and avoids modelling fake leverage. Shorts exit when
momentum *recovers* against them, the mirror of the long breakdown exit.

Short entries have floors as well as ceilings (no shorting something already
down 25% on the day) — a collapsed coin is where short squeezes live, not easy
downside. The log records `SHORT`/`COVER` alongside `BUY`/`SELL` and a `side`
column; a `COVER` is a resolved trade like any other.

## Live dashboard

`dashboard.html` is the source template and `dashboard_export.py` turns the live
state into the two documents the page reads. Build and publish with:

```bash
python3 dashboard_export.py          # -> dashboard_current.json, dashboard_history.json
python3 build_dashboard.py           # -> dashboard_build.html (seeds the page)
```

The published page reads its two documents from the artifact's database and
subscribes to them, so it re-renders whenever the data is pushed — every loop
iteration, roughly every ten minutes. The seeded copy inside the HTML is what a
first paint (or a viewer without database access) shows, so the page is never
blank. `equity_history.csv` gains a row every trading cycle, which is the curve
the chart draws.

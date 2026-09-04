# Kirktron — what the data has actually shown

Running notes on what has been learned from live paper trading. Conclusions
only, with the evidence that supports them and an honest note on sample size.
Update this as evidence accumulates; do not delete superseded entries, mark
them.

---

## Open question: does entry position within the daily range predict outcome?

**Status: weakened by new data. 7 resolutions.**

Every `daytrade` entry so far has landed in the top ~11% of the coin's 24-hour
range. Through five resolutions the ordering was perfectly monotonic; the sixth
and seventh broke it:

| entry `range_pos` | outcome |
|---|---|
| 88.9% | **+2.57%** (take-profit, moon) |
| 89.5% | −1.24% (stop) — *breaks the monotonic run* |
| 94.2% | −1.52% (stop) |
| 96.0% | −1.24% (stop) |
| 97.6% | −1.26% (stop) |
| 98.9% | −1.35% (stop) |
| 99.6% | −0.25% (max hold) |

The 89.5% entry sits 0.6pp above the only winner and lost at the stop, so the
"lower in the range is better" reading no longer survives its own data. What
remains is weaker and nearly untestable: the single win happens to be the
lowest entry, but with 1 win in 7 that is exactly what one win of any kind
would look like wherever it landed.

The deeper problem is variance, not sample size. All ten fills so far sit
between 88.9% and 99.6% — a 10.7-point spread. A feature that barely varies
across the fills cannot discriminate between them, so the pattern model will
not be able to test this at 20 resolutions either unless the spread widens.
Measuring the `range_pos` of *rejected* candidates would say whether that
narrowness is the market's (nothing lower exists in an up tape) or the
scorer's (it systematically prefers extension).

Mechanically it is plausible: the long gate needs `range_pos > 55`, but combined
with the momentum filters it only ever selects near-ceiling entries, so the book
systematically buys local highs. The same asymmetry is why the short side has
never fired — it demands `range_pos < 45`, which after any up-day nothing meets.

---

## Established: exit geometry alone cannot create edge

**Status: proven arithmetic, not a hypothesis.**

For a price with no predictable drift, the probability of hitting target `T`
before stop `S` is `S/(T+S)`. The win rate a setting *achieves* therefore moves
in lockstep with the win rate it *requires* to break even:

| setting | achieves | needs | gap |
|---|---|---|---|
| daytrade 2.5/1.2 (+0.30% costs) | 32.4% | 40.5% | −8.11 pp |
| daytrade 3.2/1.0 (+0.30% costs) | 23.8% | 31.0% | −7.14 pp |
| longshort 12.0/5.0 | 29.4% | 29.4% | 0.00 pp |
| longshort 9.0/3.5 | 28.0% | 28.0% | 0.00 pp |
| conservative 9.0/3.0 | 25.0% | 25.0% | 0.00 pp |
| aggressive 22.0/8.0 | 26.7% | 26.7% | 0.00 pp |

Cost-free books sit exactly on zero whatever their target and stop. Tuning
target/stop slides along the line; it does not lift off it. **Any real
improvement has to come from entry selection, hold logic, or lower costs — not
from re-shaping the payoff.**

A proposed `daytrade` change to 3.2/1.0 was analysed and rejected on this basis;
it was initially, and wrongly, presented as cutting breakeven from 40.5% to
30.6% without noting that the achieved win rate falls just as far.

---

## Established: costs dominate the day-trading book's result

`daytrade` has paid **$25.17** in fees and slippage against **−$30.69** realized
over five trades. Fees are ~82% of the entire loss; gross P/L is roughly −$5.50,
i.e. close to flat before friction. It is the only book charged costs (15bps a
side), so its headline number is **not comparable** to the other three.

---

## Established: measurement timelines differ by two orders of magnitude

Guaranteed throughput floor is `max_positions / max_hold_hours`, since every
slot must free itself within `max_hold` whatever the price does.

| book | slots | max hold | floor | 20 trades | 200 trades |
|---|---|---|---|---|---|
| daytrade | 4 | 6h | 16.0/day | ~1 day | ~12 days |
| longshort | 5 | 48h | 2.5/day | ~8 days | ~80 days |
| conservative | 6 | 168h | 0.9/day | ~8 days | ~83 days |
| aggressive | 4 | 96h | 1.0/day | ~20 days | ~200 days |

A win rate measured at n=20 carries a 95% interval of ±21 points and means
nothing; n=200 gives ±6.6 points. **`aggressive` cannot be evaluated on any
practical timeline as configured** — four slots and 96-hour holds cap it near
one trade a day.

Shortening max holds would raise throughput but truncate winners before their
thesis resolves, which for `aggressive` contradicts its whole premise. That
trade — measurement speed for strategy integrity — was considered and rejected.

---

## Established: the short side has never fired, and it is the gates, not the market

Across 10+ hours spanning both an up move and a down move, zero shorts opened in
either two-way book. Traced to the specific blocking gate:

- **longshort** requires `pc_24h < −1.5`; coins were down on 7d but still up on
  24h. Correctly unmet — no confirmed multi-day downtrend existed.
- **daytrade** requires `range_pos < 45`; falling coins showed textbook short
  setups on the other three conditions (RSI in the 20s, EMA rolled over,
  negative 30-min return) and were rejected *only* for sitting high in the daily
  range. After an up-day everything sits high in its range, so the gate blocks
  every early-stage reversal — which is when shorting works.

---

## Infrastructure lessons (bugs found in live running)

- **Fail-open on an inclusion list is invisible.** A rate-limited `layer-1`
  fetch silently widened the universe from 59 back to 162 with no error. An
  exclusion list failing blocks nothing; an inclusion list failing admits
  everything. It now retries, caches, and warns loudly when unenforceable.
- **Category matching must be by id, never symbol.** Wrapped and bridged tokens
  reuse the underlying's ticker (`wrapped-solana` is symbol `SOL`), so symbol
  matching excluded BTC, ETH and SOL from the tradeable universe.
- **An in-memory cache is worthless under short process lifetimes.** The
  intraday cache rebuilt from zero every restart and never got past 4 of 12
  coins while burning the rate limit refetching the same ones.
- **Adding a strategy changes the equity file's shape.** Rows kept appending
  positionally into the old header, shifting every value one column left. Row
  width identified the schema and all points were recovered.
- **Moons were unreachable by construction.** Exits test take-profit before the
  trailing stop, so every winner closed at its target — all far below the flat
  50% moon threshold. No pattern model could ever have activated.

---

## Data note: market context before 04:03 is reconstructed, not measured

`market_context.csv` only begins at 2026-09-04T04:03Z, when the logging was
added. The preceding ~10.5 hours of trading has no measured market context.

`market_context_reconstructed.csv` fills that gap from the intraday bar cache
(276 rows, 2026-09-03T05:25Z onward), and it is **a different metric** — 12
coins rather than 59, 1-hour change rather than 24-hour, and timestamps inferred
from bar spacing rather than recorded. Do not merge the two series or compare
their numbers directly. It exists because the bar cache holds only a rolling
24-hour window: had this not been reconstructed the same day, the period would
have been unrecoverable.

The lesson generalises: **instrumentation added after the fact can rarely be
backfilled.** Log the context when the run starts, not when the question comes up.

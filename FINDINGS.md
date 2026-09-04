# Kirktron — what the data has actually shown

Running notes on what has been learned from live paper trading. Conclusions
only, with the evidence that supports them and an honest note on sample size.
Update this as evidence accumulates; do not delete superseded entries, mark
them.

---

## Closed question: entry position within the daily range does NOT predict outcome

**Status: hypothesis rejected. 11 resolutions.**

This started as the project's most promising signal and did not survive its own
data. Through five resolutions the ordering was perfectly monotonic and the only
winner was the lowest entry. Eleven resolutions later:

| entry `range_pos` | outcome |
|---|---|
| 85.3% | **+1.32%** (trailing stop) |
| 88.9% | **+2.57%** (take-profit, moon) |
| 89.5% | −1.24% (stop) |
| 93.9% | −0.45% (max hold) |
| 94.2% | −1.52% (stop) |
| 95.3% | **+3.87%** (take-profit, moon) |
| 96.0% | −1.24% (stop) |
| 97.6% | −1.26% (stop) |
| 98.9% | −1.35% (stop) |
| 99.6% | −0.25% (max hold) |
| 99.7% | −0.84% (max hold) |

The three winners sit at 85.3%, 88.9% **and 95.3%**, and the largest winner came
from the middle of what had looked like a losing band. There is no ordering
left. A monotonic run of five has about a 1-in-120 chance under pure noise, and
noise is what it turned out to be — the honest lesson is that a five-point
streak in a feature was never evidence, however clean it looked.

Two mechanical caveats worth carrying forward, both learned here:

- **A feature the fills do not vary over cannot be tested.** The first eleven
  fills all sat between 85.3% and 99.6%. `range_pos_survey.csv` was added to ask
  whether that narrowness belonged to the market or the scorer; the 08:52 fills
  at 76.0% and 77.0% finally widened it. Before that, no amount of waiting would
  have let the pattern model separate anything.
- **The 12-coin and 8-coin eras are not comparable.** Before the intraday
  universe was cut to 8, every one of 38 surveyed cycles offered a coin under
  55% `range_pos`; after the cut, none of the first 28 did, because those coins
  lived in the 9th-12th volume slots. Any conclusion drawn across that boundary
  is measuring the cut, not the market.

What survives is the *mechanical* observation, not the predictive one: the long
gate needs `range_pos > 55` and, combined with the momentum filters, it selects
near-ceiling entries, so the book systematically buys local highs. That is a
true description of what gets bought. It simply does not predict what wins. The
same asymmetry is why the short side has never fired — it demands
`range_pos < 45`, which after any up-day nothing meets.

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

---

## Owner decision: aggressive resized for data rate (2026-09-04 06:38 UTC)

The book had resolved **0 trades in 13 hours**. Four slots on a 96-hour hold
guarantee only `4 / 96 = 0.042` resolutions an hour — one a day — so 20
resolutions was roughly three weeks away and the pattern model could not be
tested this month. The owner asked for a timelier data rate.

| | before | after |
|---|---|---|
| positions | 4 | 12 |
| size each | 22% of start | 7.5% of start |
| deployed | 88% | 90% |
| max hold | 96h | 48h |
| guaranteed floor | 1.0 / day | **6.0 / day** |

Untouched: entry gates, `min_score`, 8% stop, 22% target, 17% moon line,
rank <= 150, weights. So each trade is still drawn from the same distribution;
there are simply more of them.

**The two halves are not equally clean.** More slots is pure sample rate — no
distortion at all. Halving the hold is *not* free: a 22% target on a rank-150
alt can take days, so trades that would have run to a moon can now exit flat at
max hold. Since 4 moons is the binding half of the pattern gate, that works
partly against the goal it serves. Position count alone would have been the
undistorted change, but with 88% of the book locked in four multi-day positions
it would not have taken effect for days.

Watch for: a rising share of `max hold` exit reasons in `aggressive` rows of
`trade_log.csv`. If most resolutions arrive as flat max-hold exits rather than
stops and targets, the shorter hold is truncating the thesis rather than
measuring it, and the hold is the thing to put back.

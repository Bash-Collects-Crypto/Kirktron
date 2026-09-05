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

---

## Established: 60-second polling fattens BOTH tails of every exit

**Status: measured. 16 barrier exits (14 stop-loss, 2 take-profit).**

Exits are evaluated once a minute, so price can travel past a trigger before
the trader sees it. The fill is booked at the observed price, not the trigger,
and the gap is not small:

| book | exit | n | mean realised − trigger |
|---|---|---|---|
| daytrade | stop-loss | 10 | **−0.45 pp** |
| daytrade | take-profit | 2 | **+0.72 pp** |
| conservative | stop-loss | 3 | −0.13 pp |
| longshort | stop-loss | 1 | −0.01 pp |

For `daytrade` that means a 1.2% stop really costs about 1.65%, while a 2.5%
target sometimes pays 3.9% — one exit filled at −2.52% against the 1.2% stop,
and the second moon only cleared the 2.0% line because price gapped through
the target to +3.87%.

Two things follow, and the first is easy to get wrong:

- **It is not a one-sided penalty.** The loss tail and the win tail are both
  stretched. A first look at four consecutive stop-outs suggested the book's
  downside was quietly doubled; adding the take-profit side showed the effect
  is symmetric in direction, though larger in the stop column so far.
- **It scales with the book's own geometry.** Slippage is roughly a fixed
  price-move quantity, so it is a large fraction of `daytrade`'s 1.2% stop and
  a small fraction of `conservative`'s 3%. The intraday book is the one whose
  measured P/L should be trusted least.

This is a property of the simulation's polling rate, not of any strategy. It
argues for reading `daytrade`'s numbers with a wider error bar, not for moving
its stop — and per the exit-geometry finding above, moving the stop could not
create edge anyway.

---

## Owner decision: widen the day-trading book for data rate (2026-09-04 16:00)

The owner asked for whatever changes best produce information useful for
profit later. Three were made, all aimed at the one book that actually
generates data: `daytrade` has produced **16 of the project's 23 resolutions**,
and it spent **49% of its holding time pinned at its 4-slot cap**, unable to
take another trade.

| | before | after |
|---|---|---|
| candidate pool | 8 coins | 12 coins |
| slots | 4 | 6 |
| size each | 12% | 10% |
| deployed when full | 48% | 60% |
| guaranteed floor | 0.67 res/h | **1.00 res/h** |

Untouched: gates, `min_score`, the 1.2% stop, 2.5% target, 2.0% moon line,
6-hour hold, 15bps costs, cooldown. More samples of the same distribution.

**The enabling fix was a data-integrity bug, not a parameter.** `IntradayCache.features()`
returned indicators from whatever bars were cached, *however old they were*.
When rate limiting pushed staleness to 12.6 minutes against a 5-minute TTL,
the book kept scoring entries on bars from two and a half TTLs ago and had no
way to know. Cutting the pool 12 → 8 at 07:00 fixed the symptom by letting
refresh keep up; it never addressed the behaviour.

`features()` now returns `None` past `STALE_LIMIT` (600s), so the book scores
only genuinely fresh coins and **degrades gracefully** instead of silently
trading on old data. That is what makes a 12-coin pool safe again: if refresh
falls behind, the candidate list shrinks rather than rotting. Verified at
12/12 scoreable with 3.3-minute staleness immediately after the change.

## The drought has one cause, and it is the same one in all four books (2026-09-04 16:15)

Added `gate_census.csv`: every cycle, every book walks the coins it is eligible
to trade and attributes each one to the **first gate that rejects it**, long
side and short side separately. Log-only — it reads the same config the live
gates read and changes nothing. A book reporting "no candidates" is no longer
self-explaining only as "quiet market".

First census, 16:14:53Z:

| book | eligible | pass long | pass short | top long blocker | top short blocker |
|---|---|---|---|---|---|
| conservative | 15 | 1 | n/a | `pc_24h` low, 13 | — |
| longshort | 21 | 1 | 0 | `pc_24h` low, 18 | `pc_1h` high, **21 of 21** |
| daytrade | 12 | 0 | 0 | `ret_30m` low, 8 | `ret_30m` high, 11 |
| aggressive | 36 | 1 | n/a | `pc_24h` low, 29 | — |

**One feature is doing all the rejecting, on both sides at once.** Every book
is a momentum book: the long gates demand momentum up, the short gates demand
momentum down, and both read the same feature with the sign flipped. The tape
right now is a bounce off the day's low — 24h returns still negative (long
gates blocked) while 1h and 30m returns have turned positive (short gates
blocked). Neither side can fire, and that is the gates working as written, not
a fault.

Confirmed on the daytrade universe directly: all 12 coins showed 14-bar RSI
between 70.5 and 82.0 while sitting at 16.8–68.1% of their 24-hour range. That
is not a contradiction — RSI-14 on 5-minute bars is a 70-minute measure and
`range_pos` is a 24-hour one — but it is the whole story in one line: **sharply
up over the last hour, still far below where the day started.**

The structural consequence, unapplied and stated as an observation: daytrade's
long gate combines a 70-minute momentum floor with a *24-hour* range-position
floor of 55. On a V-shaped bounce day those two cannot be satisfied at the same
time until the bounce carries price back through the middle of the day's range,
which is hours of holding time the 6-hour cap may not have. This is a candidate
explanation for daytrade's flat spell since 13:14 — the book was 100% cash for
three hours with 12 fresh coins and 6 free slots, so neither the slot cap nor
the candidate pool was binding. **No gate, threshold or weight was changed.**
The census now records the answer every cycle, so the next regime settles it
with data instead of argument.

## The four books are not four independent experiments (2026-09-04 16:40)

Measured over every position ever opened: **8 of the 18 distinct symbols traded
(44%) were opened by more than one book.** ZEC has been held by all four; HYPE
by three; ADA, BNB, BTC, XMR, XRP and LINK by two each. Right now ZEC is open
in conservative, longshort and aggressive at once — $3,380 across three books,
about 8.6% of combined equity — and it is the best position in every one of
them.

The books were built with different universes, horizons and exit geometry, so
the overlap was not designed in; it follows from all four scoring momentum over
a top-25-to-150 universe on the same day. When the tape is narrow, the momentum
leaders are the same handful of coins whatever the lookback.

Two consequences for reading the record:

1. **Combined equity is less diversified than "four $10,000 books" suggests.**
   A single coin's move shows up three or four times in the total. Today ZEC is
   carrying the combined number almost alone; a reversal in it would show up as
   a simultaneous drawdown in three books and read like a strategy failure
   rather than one position.
2. **Per-book win rates are correlated, so they cannot simply be pooled.** Two
   books resolving the same coin on the same thesis are not two samples. Any
   future pooled statistic has to count distinct (symbol, entry window) pairs,
   not trades.

No change made. This is a property of the design worth stating before any
cross-book comparison is drawn from the record, not a fault to fix.

## daytrade's third moon (2026-09-04 16:35)

ZEC LONG opened 16:17 at $991.62, closed 16:35:48 at $1,017.75 on the
take-profit — **+$23.31, +2.635% net of both 15bps legs, an 18-minute hold**.
Moon (threshold +2.0%). daytrade now stands at **17/20 resolved and 3/4 moons**:
three more resolutions and one more moon and its pattern model activates.

Take-profit slippage now n=3: overshoots of +0.72pp, +0.72pp and +0.135pp above
the 2.5% target, mean **+0.52pp**. The stop-loss side stays n=10 at -0.445pp.
The 60-second poll still fattens both tails; the take-profit sample is too small
to say the asymmetry is real.

## Universe audit 17:01 — clean by the exclusion rules, one coin fails the positive rule

Counts unchanged from the 11:25 audit: **250 fetched → 190 excluded → 60
tradeable**, exclusion cache 977 ids / 894 symbols fetched 13:04. Every banned
class is being caught — 22 stablecoins, 22 tokenized RWAs, 12 memes, 5 pegged,
1 wrapped, 24 mixed. No meme coin, stablecoin or wrapper reached any book.

But the rule in CLAUDE.md is stated positively — *layer-1 chains and blue chips
only* — and one coin fails it: **RAIN, rank 13.**

CoinGecko's own categories for `rain`: *Gambling (GambleFi), Decentralized
Finance (DeFi), Options, Prediction Markets, Arbitrum Ecosystem.* It is a
decentralized options and prediction-market protocol on Arbitrum. It is not a
layer-1 (confirmed absent from the 250-id allowlist) and not a blue chip in any
sense except market-cap rank.

**How it gets in:** the universe admits `layer-1 allowlist OR rank <= 25`. That
second clause is an unconditional rank bypass — anything reaching the top 25
enters unless one of the exclusion lists catches it, and none of them lists
GambleFi or DeFi protocol tokens. Checking every coin admitted by the bypass
alone, the exclusion lists catch all of them (USDT, USDC, DOGE, DAI, USDS, USDE,
USD1, WBT, FIGR_HELOC) except three: LINK, which is a genuine blue chip; LEO,
whose ~$0M daily volume puts it below every book's volume floor; and RAIN.

**Live exposure:** RAIN trades $42M a day against an $11.8B market cap — a 0.36%
turnover ratio, thin for a rank-13 asset. That clears longshort's $25M floor and
aggressive's $10M floor, so **both books can buy it right now**. It is blocked
in conservative ($50M floor) and daytrade ($100M floor). It has never been
traded — 0 rows in trade_log.csv — so nothing in the record is contaminated.

**Not fixed, surfaced.** The obvious repair is to drop the unconditional rank
bypass and require allowlist membership, with a small explicit blue-chip id set
for names the layer-1 category misses (LINK is the only one that currently
matters). That narrows what all four books may trade, which is the owner's call,
not a correctness fix I should make alone — RAIN has never traded and no book
holds it. Recording it so the decision is made on evidence rather than
discovered later inside a position.

## The short side works, and the two books find it at different speeds (2026-09-04 17:35)

Four shorts are now open, all since the 15:29 fix that made the short branch
reachable. **daytrade is 100% short for the first time** — its whole book is
ADA, XMR and XRP on the sell side, opened within 15 minutes of each other:

| book | symbol | entry | size | costs | moon line |
|---|---|---|---|---|---|
| longshort | SUI | $0.747839 | $1,500 | none | +9.5% |
| daytrade | XRP | $1.400000 | $1,000 | 15bps/side | +2.0% |
| daytrade | ADA | $0.212847 | $1,000 | 15bps/side | +2.0% |
| daytrade | XMR | $522.000000 | $1,000 | 15bps/side | +2.0% |

Zero have resolved, so **every short-side statistic is still n=0.** Nothing is
known about whether shorting works here; it is only, finally, being tested.

The census explains why one book found three shorts in 15 minutes while the
other found one in two hours, and it is about **lookback, not strictness.**
longshort's short gate reads `pc_1h <= -0.3` — a one-hour window — and `pc_1h`
has rejected 21 of 21 eligible coins in every census taken since 16:14. daytrade
reads `ret_30m <= -0.15` on 5-minute bars, a thirty-minute window. In a tape
that is drifting down over half-hour stretches while each hour still nets out
positive from the bounce, the 30-minute window sees the downtrend and the
1-hour window does not. Same market, same direction, different clock.

That is an observation about gate *shape*, not a case for loosening a threshold,
and no gate was touched. It does predict something checkable: if the tape rolls
over for a full hour, longshort's short side should unlock without any change to
the code. Watching for that is a cleaner test than arguing about the number.

## The trailing stop can cancel a moon, and for daytrade the window is exact (2026-09-04 17:57)

Three trailing-stop exits now exist, all profitable, and **all three on ZEC** —
so this says as much about ZEC's path today as about the rule. With that caveat:

| book | peak | exit | giveback | moon line | counted a moon? |
|---|---|---|---|---|---|
| daytrade 07:41 | +2.11% | +1.32% | 0.79pp | +2.0% | **no** |
| conservative 17:28 | +6.77% | +4.27% | 2.50pp | +7.0% | no |
| longshort 17:48 | +8.03% | +4.17% | 3.86pp | +9.5% | no |

The daytrade row is the one that matters. **Its peak crossed the moon line and
the recorded outcome did not.** A moon is scored on the closed P/L, correctly —
the trade did not deliver its thesis — but the consequence is structural, and for
daytrade the window can be written down exactly.

daytrade arms its trail at +1.5% and gives back 0.7%, takes profit at +2.5%, and
its moon line is +2.0%. So a trade peaking at P exits at P − 0.7% unless it
reaches +2.5% first. For the exit to reach the moon line it needs P ≥ +2.7% —
but at +2.5% the take-profit already fired and banked a moon. **Therefore every
daytrade trade that peaks between +2.0% and +2.5% is guaranteed to be recorded
as a non-moon**, no matter how the tape moves. The moon line sits inside the
trail's giveback band.

That band is 0.5pp wide out of a 2.5pp target, and it costs moons specifically —
the scarcer half of the pattern-model gate. daytrade is at 3 of 4 moons and 17 of
20 resolutions; the 07:41 ZEC trade is one observation of a trade that fell into
this band, and had it counted, the book would be at 4 moons now.

**Nothing changed.** This is a real interaction between three parameters the
owner set, not a bug: the numbers do exactly what they say. It is worth stating
because "why is the pattern model taking so long" now has a precise partial
answer, and because any future change to the trail, the target or the moon line
should be made knowing these three interact. The same arithmetic applies to the
other books but their gaps are wider (conservative arms at 3.0/gives back 2.5
against a 9% target and a 7% moon), so the band there is not a near-miss zone in
the same way.

## The lookback prediction resolved, correctly (2026-09-04 18:01)

Stated at 17:35 and testable without touching code: longshort and daytrade were
finding shorts at wildly different rates *because their short gates read
different lookback windows*, not because one was stricter. longshort's short gate
reads `pc_1h`; daytrade reads a 30-minute return on 5-minute bars. The prediction
was that if the decline persisted through a full hour, **longshort's short side
would unlock by itself with no code change.**

It did. At **18:01:34 longshort opened XLM SHORT @ $0.178064** ($1,500, score
9.71) — its second short ever and the first one the gate let through on its own
terms rather than on a squeeze-shaped setup.

The census makes the flip unambiguous. Since 16:14, `pc_1h` had rejected **21 of
21** eligible coins in every single census. At 18:02:35:

| book | pass long | pass short | top long blocker | top short blocker |
|---|---|---|---|---|
| longshort | **0** of 21 | **4** of 21 | `pc_1h` low, 20 | `pc_7d` high, 8 |
| conservative | 1 of 15 | n/a | `pc_24h` low, 12 | — |
| daytrade | 0 of 12 | 0 of 12 | `ret_30m` low, 12 | `rsi14` low, 5 |
| aggressive | 0 of 36 | n/a | `pc_1h` low, 33 | — |

`pc_1h` went from blocking every short to blocking **zero** of them, and it is
now the top *long* blocker instead — in longshort (20 of 21) and in aggressive
(33 of 36). The same feature flipped sides across all three books at once, which
is what a genuine regime change looks like rather than a threshold quirk. The
binding short-side constraint has moved on to `pc_7d`, a seven-day window that
the last hour cannot move.

**No gate, threshold, weight or size was changed to produce this.** The value of
the result is not the XLM trade; it is that the gate census turned a vague
complaint — "the shorts don't fire" — into a falsifiable statement that the
market then settled in 26 minutes. Where a gate's lookback disagrees with the
horizon a book trades on, the census now says so directly and the fix, if one is
ever wanted, is a matched window rather than a looser number.

## min_score filters nothing; the gates are the whole constraint (19:36)

The gate census recorded `n_pass_long` (coins clearing the gates) beside
`n_candidates` (coins that reached the entry loop). Across 560 census rows
from 16:14 to 19:32 the two counts diverged constantly — for conservative in
139 of 140 cycles — which reads as `min_score` silently discarding everything
the gates admit.

It was an artefact of the instrument. The entry loop skips a coin that the
book already holds or has on cooldown *before* it tests any gate; the census
tested the gates first and counted those coins as passing. A book holding 5 of
the ~15 names it can reach therefore showed a permanent, meaningless gap.

The census now skips held and cooldown coins (recording them as `n_busy`) and
writes `n_score_cut` explicitly. The answer since the fix is unambiguous:

    n_score_cut = 0, every book, every cycle

Every coin that cleared the gates in that sample became a candidate. But the
sample contained no daytrade passes at all, and the claim did not survive
contact with the first one — see the correction below.

The corrected counts also sharpen how narrow the reachable universe is. At
19:35 conservative could act on **9** coins, not 15: six of its fifteen
eligible names were already held or cooling. `pc_24h` blocked all nine. A book
with five open positions out of six slots is choosing from a pool a third
smaller than the eligibility count suggests.

The old-schema rows are preserved as `gate_census_v1.csv`; the file was
rotated rather than extended, because appending columns to a live CSV writes
rows that no longer line up with their header.

## The report's percent column is return on capital, not a price move (19:47)

`--report` prints each open position through `change_pct`, which is already
direction-corrected: for a short it returns `(entry - price) / entry`. A line
reading

    SHORT SUI  -1.44%  $1478.45  held 4.0h  (entry $0.747839)

therefore means **the short is down 1.44%** — $1478.45 against $1500 posted —
not that SUI fell 1.44%. The position-value column confirms it independently
and is the check to use when the sign is in doubt.

Read the other way, a losing short book looks like a winning one. That
misreading was made and published twice before the position values were
reconciled against it. At 19:46 the true state of the six live shorts was:

| book | short | return on capital |
|---|---|---|
| longshort | SUI | −1.37% |
| longshort | XLM | −0.59% |
| daytrade | XMR | −1.13% |
| daytrade | LINK | −0.69% |
| daytrade | ADA | −0.36% |
| daytrade | XRP | −0.00% |

All six losing or flat. daytrade's XMR at −1.13% sits just inside its 1.2%
stop. The short side's record remains n=0 resolved and there is, as yet, no
evidence in either direction about whether it works.

## The first short in the program's history resolved, and it lost (19:51)

daytrade covered XMR at $529.08 against a $522.00 entry — a stop-loss after
2.29 hours. **−$16.54, −1.356% on price, −1.654% after the 15bps-per-side
costs. Not a moon.** The short-side record opens at 0 for 1.

Two things are worth keeping from a single trade, and one thing is not.

Worth keeping: the stop fired at −1.356% against a 1.2% stop, so it gave up
**0.156pp** past its trigger. That is markedly tighter than the long-side
stop-loss series (n=10, mean −0.445pp) and is the first short-side entry in
the slippage measurement. One observation is not a comparison, but the
number goes on the board.

Also worth keeping: the position was the one flagged as nearest its stop at
19:46, at −1.13% with 0.07pp of room. It resolved five minutes later. The
open-position marks track the exit logic closely enough to anticipate a
resolution one cycle ahead.

Not worth anything yet: whether the short side works. n=1. The 95% interval
on a one-trade win rate spans essentially the whole unit interval. The three
remaining daytrade shorts hit their 6-hour cap between 23:20 and 23:40 and
will carry the count to 4; longshort's two run to a 48-hour cap. Nothing
about the short thesis should be claimed before those land, and even then
n=6 is worth ±40pp.

daytrade now stands at **18 of 20 resolved, 3 of 4 moons** — two resolutions
from the first half of the pattern-model gate.

## Correction: min_score does bind, but only in daytrade (20:26)

The entry above claimed `n_score_cut` was zero in every book every cycle. That
held for the sample it was written from and stopped holding fifty minutes
later. Over the 34 census cycles since the instrument was fixed:

| book | cycles with a gate pass | of those, cut by min_score |
|---|---|---|
| conservative | 0 | — |
| longshort | 34 | 0 |
| aggressive | 34 | 0 |
| daytrade | 3 | **3** |

For the three multi-day books the original claim stands unqualified: 68 cycles
in which coins cleared the gates, not one discarded by score. For daytrade it
is exactly inverted — every coin that has cleared its gates since the fix has
then been cut by `min_score`, three for three.

The asymmetry is in the thresholds, not the market. daytrade scores off
intraday features and sets `min_score` at 0.6 while conservative sits at 1.0,
longshort 2.0 and aggressive 3.0 — but daytrade's gates are so much tighter
that almost nothing reaches the score at all, and what does arrives weak.

This matters more than the raw count suggests: daytrade has two free slots and
$5,820 in cash, and is the only book with room to open. Its droughts are
therefore *not* purely gate droughts, and a blocker attribution from the
census does not fully explain why it is not trading — the score is the last
filter and it is currently rejecting everything the gates admit. n=3.
Surfaced, not actioned; `min_score` is a strategy parameter and the owner's
call.

## pc_1h flipped a fourth time, and conservative did not follow (21:22)

At 21:07 `pc_1h` displaced `pc_24h` as the top long blocker in longshort (13
of 16 eligible coins) and aggressive (26 of 33), and held there with identical
counts through five consecutive censuses to 21:21. On the short side its
longshort block eased from 16 of 16 to 11, with `pc_24h` and `pc_7d` appearing
behind it for the first time.

That is the fourth `pc_1h` regime change today and reinforces what the
18:01 lookback prediction established: `pc_1h` is the feature that decides
which side a book can trade, and it turns over on roughly an hourly cadence.

The new part is what conservative did, which is nothing. Its top blocker
stayed `pc_24h` at 9 of 9 through every cycle of the flip. On the three
previous flips all three multi-day books moved together. The divergence is
explained by universe, not by disagreement: conservative reaches rank ≤ 30
while aggressive reaches rank ≤ 150, so conservative's nine reachable coins
are all large caps whose 24-hour move is still negative even as the 1-hour
move turned. A blocker census is therefore a statement about a book's
*reachable set*, not about the market — two books can report different
binding constraints at the same instant and both be right.

No parameter changed. n = 5 consecutive censuses for the flip itself; the
conservative divergence is a single episode.

## XRP is marked at cent precision, and that is coarser than daytrade's stop (22:38)

daytrade's XRP short has read exactly +0.00% for over five hours. The price
has not been still: the 5-minute bar series shows XRP ranging 1.3964 to 1.4020
in the last 70 minutes alone. The mark cannot express the move.

The CoinGecko `/coins/markets` feed returns XRP at three significant figures
while its peers come back at six:

| symbol | current_price | high_24h | low_24h |
|---|---|---|---|
| XRP | **1.4** | 1.46 | 1.38 |
| LINK | 11.64 | 12.15 | 11.48 |
| ADA | 0.210806 | 0.226776 | 0.209675 |
| XLM | 0.179253 | 0.186742 | 0.177583 |

Every one of the seven XRP fills in `trade_log.csv`, spanning 26 hours, is an
exact cent: 1.47, 1.48, 1.46, 1.45, 1.42, 1.39, 1.40.

Positions are marked and exited on this feed (`build_universe` → the entry
loop's `coin["price"]`), while daytrade's *signals* come from the
full-precision 5-minute bars. So for XRP the signal is fine and the exit is
quantised, in steps of one cent = **0.714%** at $1.40. Against daytrade's
parameters that means:

- the 1.2% stop cannot fire until a two-cent move, i.e. **1.43%** — a
  guaranteed 0.23pp of excess slippage on top of whatever the market gives;
- the +2.0% moon line needs three cents, i.e. **2.14%**;
- the position reads 0.00%, ±0.71%, ±1.43% and nothing between.

Consequences for the record already collected: XRP outcomes carry a
quantisation error the other coins do not, so XRP rows should be excluded from
the slippage series rather than averaged into it. LINK's step is 0.086% and
every other coin in daytrade's pool is finer still, so this is an XRP-specific
defect, not a systematic one — of the 13 coins daytrade can reach, only XRP is
affected.

No parameter changed and no code changed. The obvious remedy — mark daytrade
positions from the intraday series, which already carries full precision for
exactly these twelve coins — would change when trades close, so it is the
owner's call, not a correctness fix to make unasked.

## Universe audit 22:58 — counts unchanged, and the rank bypass has a second passenger

Counts are identical to the 17:01 audit: **250 fetched → 190 excluded → 60
tradeable**, with the exclusion list at 977 ids / 894 symbols. No meme coin,
stablecoin, pegged token, wrapped or staked derivative or tokenized RWA
reached any book's universe, and the allowlist loaded cleanly — no
fails-open warning. By the exclusion rules the universe is clean.

The positive rule is where it leaks, and RAIN is not alone. Walking the
admitted names by id rather than ticker turns up a second one:

| ticker | id | rank | what it is | 24h volume |
|---|---|---|---|---|
| RAIN | — | 13 | GambleFi / prediction market on Arbitrum | $42M |
| **LEO** | `leo-token` | 18 | **Bitfinex exchange token** | **$0.19M** |

Both are admitted by the same unconditional `rank <= 25` bypass, and neither
is a layer-1 or a blue chip. The others checked are legitimate: `GRAM` is
`the-open-network` (TON, a real layer-1), `CC` is `canton-network`, and
`STABLE` — despite the ticker — is `stable-2` trading at $0.0289, so it is
not a pegged asset and the stablecoin filter is right to leave it alone.

LEO is harmless in practice: at $186,590 of daily volume it fails every
book's volume floor by two orders of magnitude, so no book can ever open it.
RAIN, at $42M, clears longshort's $25M and aggressive's $10M. So the exposure
is unchanged — one reachable coin that should not be reachable — but the
bypass now has two demonstrated passengers rather than one, which is a
stronger argument for the fix already proposed and still awaiting the owner:
drop the unconditional rank bypass and keep a small explicit blue-chip id set.
Only LINK currently needs it. Nothing actioned.

## daytrade's max-hold exits are its least-bad category, and partly by definition (23:40)

With 21 resolved trades, daytrade's exits split cleanly:

| exit type | n | share | mean return | mean |return| | total P/L |
|---|---|---|---|---|---|
| max hold (6h) | 5 | 24% | −0.113% | 0.503% | **−$25.49** |
| stop / target / trail | 16 | 76% | −0.540% | 1.839% | **−$159.49** |

The five max-hold exits, worst to best: BNB −0.835%, ETH −0.452%, LINK −0.252%,
XRP 0.000%, ADA +0.976%. Three of the five are long-side and from this morning;
the two shorts landed tonight when the 17:18–17:38 cohort hit its cap.

**Half of this is a tautology and it would be dishonest not to say so.** A trade
reaches six hours precisely because it never moved far enough to trigger a stop
or a target, so "trades that expired are flat" is close to definitional. The
comparison of *means* carries no information on its own.

What is not definitional is the shape of the population. daytrade's outcomes
are bimodal: roughly a quarter of its trades go essentially nowhere for six
hours (mean absolute move 0.50%), and the other three quarters move about
1.84% — and that moving group is where all the losses live. The stop is
catching real adverse moves, not noise; the book's problem is direction, not
exit placement.

The one number that is actionable rather than definitional: those five
non-movers paid **30bps of round-trip cost each** and returned −$25.49 in
aggregate, of which the XRP trade is pure friction — it closed at exactly
0.000% and lost $3.00, entirely in fees, on a position whose mark never once
expressed a move (see the cent-precision finding above).

That points at a possible time-based early exit for positions showing no
movement well before the cap — but it is a hold-logic change, so it is the
owner's call and nothing has been changed. n=5 max-hold exits, which is far
too few to size such a rule from.

## daytrade deploys under half its capital, and that halves whatever edge exists (00:35)

Reconstructing slot occupancy from every open and close in `trade_log.csv`
across 28.0 hours of live trading:

| open positions | share of time | hours |
|---|---|---|
| 0 | 15.2% | 4.3 |
| 1 | 9.9% | 2.8 |
| 2 | 8.6% | 2.4 |
| 3 | 15.7% | 4.4 |
| 4 | **37.9%** | 10.6 |
| 5 | 12.0% | 3.4 |
| 6 | 0.7% | 0.2 |

Time-weighted average: **2.90 positions of a possible 6 — 48% of capital
deployed.** The book has been completely flat 15% of the time and has touched
its six-position cap for twelve minutes in twenty-eight hours.

This matters for two separate reasons and they should not be confused.

**For returns:** if the strategy has a positive expectancy per unit of capital
per unit of time, running at 48% deployment collects roughly half of it. That
is a straightforward scaling loss, not a subtlety — though it cuts both ways,
and with the book currently at −1.90% the idle half has been protective, not
costly.

**For measurement, which matters more right now:** half-idle capital is also
half the resolutions per day. The 21-per-day rate that puts a meaningful win
rate ten days out is itself a consequence of this, so utilisation and
statistical convergence are the same problem wearing two hats.

The cause is not slot capacity or cash — the book holds $7,792 idle with four
free slots as this is written. It is the gates: the census shows `ret_30m`
rejecting 9 of 10 eligible coins on both sides for the last hour. Raising
utilisation therefore means loosening entry admission, which is exactly the
change the live scorer evidence currently argues against (the highest-scoring
recent entry resolved worst). Those two pull in opposite directions, and n is
far too small to resolve the tension.

Surfaced, not actioned. No parameter changed. 28 hours, one book, one regime.

## The cross-coin lead-lag study: run, and it found nothing (00:52)

The owner asked for this study and it is now done. **No cross-coin lead-lag
relationship survives at 5-minute resolution over the last 24 hours.**

### The first run was wrong, and how it was wrong is the more useful finding

The initial run aligned each coin's return series **by list index from the
end** and produced spectacular results: `ethereum` "leads" `bitcoin` by 5
minutes at **r = 0.935**, with everything appearing to lead BTC and BCH at
r ≈ 0.8–0.9, twenty-eight pairs clearing a Bonferroni threshold.

None of it was real. The cache stored bare prices with **no timestamps**;
coins are fetched minutes apart (up to 4.6 minutes of spread was observed) and
come back with different bar counts (288 vs 289). Aligning by index therefore
compares different instants, and shifting a contemporaneous correlation by one
bar reproduces it almost exactly. The giveaway was that the "lagged"
correlations exceeded the contemporaneous ones — impossible for a genuine
predictive relationship, and a money machine if true.

This is precisely the failure mode worth guarding against: a plausible
pipeline, a clean-looking output, an effect size that should have been
unbelievable, and a result that would have lost money live.

**Fix applied to `intraday.py`:** `_fetch` now keeps the exchange timestamp
alongside each close, stored in a parallel `times` map. `series` keeps its
exact previous shape so `indicators()` and every existing consumer are
untouched; the change is purely additive and alters no trading behaviour.
Confirmed live: all 12 coins now carry timestamps aligned 1:1 with their bars.

### The corrected result

Aligning on 5-minute wall-clock buckets and keeping only buckets every coin
shares (288 of 289; one bar discarded as unalignable):

- 12 coins, 287 returns, 24.0 hours, null SE **0.0590**
- 528 directed pair × lag tests at 5, 10, 15 and 30 minutes
- family-wise threshold |r| > **0.236** (z = 4.0; 0.03 false positives expected)
- **pairs passing: 0 of 528**

Strongest observed: `ripple` → `bitcoin` at 15 minutes, r = 0.212 (z = 3.58).
At 528 tests roughly one result of that size is expected by chance.

**Bitcoin does not lead the pool.** Across 44 BTC-leads tests the largest is
z = 2.50, against a threshold of 4.0. The 5-minute column is uniformly
*negative* (−0.001 to −0.148), the 15-minute column uniformly slightly
positive — a sign flip with no magnitude behind it.

Meanwhile contemporaneous correlation is **mean 0.639, max 0.949**. The coins
move together *now* and predict nothing about each other later. That is one
coherent picture, not a null: it is a market where cross-sectional information
is already in the price within one bar.

### What this rules out

Mean 5-minute return sigma across the pool is **0.244%**, against daytrade's
**0.30% round-trip cost**. A predictor with correlation r delivers about
r × sigma of expected move per bar, so:

| r | edge per bar | bars to clear costs |
|---|---|---|
| 0.10 | 0.024% | 12.3 |
| 0.20 | 0.049% | 6.2 |
| **0.236** (detection limit) | 0.058% | **5.2** |

Anything strong enough to be worth trading after costs would have had to be
close to the detection threshold, and nothing came near it. The study does not
prove no lead-lag exists — it bounds it: **no relationship stronger than
|r| ≈ 0.24 was present in this window**, and weaker ones need five or more
bars of holding to pay for the spread, by which point the effect must persist
far longer than anything measured here does (see the 30-minute-signal cohort
above, which did not survive six hours).

**Not implemented as a trading signal, and it should not be.** A negative
result is the correct place to stop. n = 287 returns, 12 coins, **one
regime** — a 24-hour window that was a single sustained selloff. Worth
re-running across a different regime before treating the bound as general.

## 01:22 — What survives the container, and the one thing that did not

The container is ephemeral, so it is worth stating precisely what is durable.

Durable, pushed to GitHub:

- **`trade_log.csv`** — every fill with its full entry feature vector and its
  outcome. This is the pattern models' entire training set. The models are not
  a saved artifact; they are derived from this file at runtime, so as long as
  it is on the data branch nothing about them is lost.
- `state_<book>.json`, `equity_history.csv`, `market_context.csv`,
  `gate_census.csv`, `exclusions_cache.json` — on `kirktron-trading-data`.
- All code and this file — on the feature branch.

Not durable, and one of them mattered: **`intraday_cache.json`**. It holds
5-minute bars for the day-trading universe, and CoinGecko's `days=1` endpoint
only serves the last 24 hours, so a bar that ages out of that window cannot be
refetched at any price. The cache was gitignored and never snapshotted, so
every bar the program had paid an API call for was discarded when the container
went away — and the multi-regime bar history the strategy work needs can only
be accumulated, never backfilled.

Fixed with `archive_bars.py`: bars are immutable once observed, so it merges
`(coin, ts_ms, price)` into an append-only `intraday_bars.csv`, deduplicated
and idempotent, and `snapshot.sh` runs it before each commit. Archiving the
cache file itself would have rewritten 120KB of JSON per snapshot; the archive
grows by only the genuinely new bars — 34 rows on the second run of the same
iteration. First run captured 3,462 bars across 12 coins.

This depends on the timestamp fix from 00:52 (`f2f850e`). Bars cached before
that have no wall-clock anchor and are skipped — they cannot be placed on a
timeline. It reads nothing the trader writes and writes nothing the trader
reads, so trading behaviour is untouched.

The remaining loss on a session ending is real but bounded: the trader stops,
so positions stop being marked and stops do not fire until it is restarted,
and that gap is a hole in `equity_history.csv` rather than an error.

## 01:31 — Across all four books, return is 93% explained by exposure alone

The four books differ in nearly everything a strategy can differ in: universe
(rank ≤ 25 / 30 / 50 / 150), direction (long-only vs both), hold (6h to 168h),
stop and target geometry, and costs. If any of that were producing selection
skill over the last 30.2 hours, the books should not line up on a single line.

They do. Time-weighted capital deployment reconstructed from `trade_log.csv`
(each position's `usd_amount` integrated over its life, divided by $10,000 ×
30.2h), against return with daytrade's $81.41 of costs added back so the
comparison is like-for-like:

| book | deployed | return | ex-cost return | residual |
|---|---|---|---|---|
| daytrade | 29.7% | −1.86% | −1.05% | −0.07pp |
| conservative | 55.4% | −1.49% | −1.49% | +0.29pp |
| longshort | 69.1% | −2.47% | −2.47% | −0.26pp |
| aggressive | 92.1% | −2.87% | −2.87% | +0.05pp |

`ex-cost return = −0.0312 × deployed% − 0.048`, **r = −0.963, r² = 0.927**.
Every book sits within 0.29pp of that line. The slope says a fully deployed
long book gives up about 3.1% over this window — which is simply what the
market did.

**No book has yet demonstrated selection skill.** The entire performance spread
between four quite different strategies is accounted for by how much money each
had at risk, not by which coins it chose or when it exited. That is not a
verdict on the strategies; it is a statement about what 30 hours of a single
directional selloff can resolve. Skill, if present, is currently smaller than
the ±0.29pp of residual.

Worth noting separately: **longshort's residual is the worst of the four
(−0.26pp) despite being the only book that can go short.** Its ability to
hedge has produced nothing so far — consistent with its two live shorts, which
have never once been in profit.

Sample caveats, which are severe. n = 4 books gives the regression 2 degrees of
freedom; r = −0.963 there is t = −5.03, p ≈ 0.04, marginal on its own. And the
four books are not independent observations — they trade overlapping universes
(HYPE is held by three of them, ZEC by two) over the same 30 hours of one
regime. This is closer to one observation than to four.

What it is good for is a **measurement standard**: from here, judge a book by
its residual from this line rather than by raw return, so that a book which
merely held more cash during a selloff is not mistaken for a book that picked
better. Recording deployment per cycle is unnecessary — `trade_log.csv`
reconstructs it exactly, as above.

## 02:35 — `score` is not comparable across books, and the shared column is a trap

`trade_log.csv` has a single `score` column written by all four books, but each
book scores on its own scale. Across all 53 entries so far:

| book | n | min | median | max |
|---|---|---|---|---|
| daytrade | 27 | 0.62 | 0.77 | 2.62 |
| longshort | 8 | 9.71 | 18.28 | 65.38 |
| conservative | 13 | 16.37 | 31.62 | 104.80 |
| aggressive | 5 | 45.66 | 55.86 | 67.92 |

The medians differ by **41×** between daytrade and conservative, and the ranges
do not overlap at all: daytrade's best entry ever (2.62) scores below
conservative's worst (16.37). This is by design — daytrade scores intraday
features while the others score multi-day momentum percentages — but the log
does not say so anywhere.

The trap is that `trade_log.csv` is the training set, and it is one file. Any
model fitted on the pooled log with `score` as a feature would learn **book
identity**, not signal: "score below 3" perfectly separates daytrade from
everything else, and daytrade has 23 of the 33 resolutions, so the feature
would look strongly predictive while carrying no information about the trade.

Nothing is broken today — the pattern models are per-book and never see another
book's rows. But this is a live tripwire for exactly the analysis the project
is accumulating data for, so:

**Rule: never pool `score` across books.** Compare a score only within its own
book, or rank-normalise per book first. `min_score` thresholds (conservative
1.0, longshort 2.0, daytrade 0.6, aggressive 3.0) are likewise per-book and
carry no cross-book meaning.

No code change. Adding a normalised column would require rotating the log's
schema, and the rule costs nothing to follow.

## 03:01 — BCH resolved exactly on the predicted line; the model did NOT activate

The trailing-stop/moon interaction predicted at 17:57 was tested live and held
to four decimal places.

daytrade SHORT BCH @ $249.82 (23:09, score 1.671) covered at $247.05 on a
**trailing stop, peak +1.813%, exit +1.109%, +$8.07**, held 3.9h against a 6h
cap. The trail arms at +1.5% and gives back 0.7%, so from that peak the exit
line sat at **+1.113%** — the fill came in at +1.109%, 0.004pp away.

**It never entered the dead band.** The +2.0%–+2.5% band is where a peak is
high enough to look like a moon but too low for the take-profit to fire; BCH
peaked at +1.813%, below the moon line entirely, so it was a non-moon by a
clearer margin than the mechanism being tested. The prediction that it could
only moon by hitting +2.5% outright was never put to the test.

**daytrade stays at 3/4 moons with 25 resolved. The pattern model did not
activate.** It remains one moon short.

### The scorer test set, now fully resolved

| coin | score | outcome | exit |
|---|---|---|---|
| XMR | 2.615 | **−1.229%** | stop-loss |
| BCH | 1.671 | **+1.109%** | trailing stop |
| HYPE | 0.630 | **+0.837%** | max hold 6h |

**Correction to the 20:33 and 02:44 readings:** while only XMR and HYPE had
resolved, the outcome ordering was the exact reverse of the score ordering, and
that is how it was reported. With BCH resolved it is no longer a clean reverse
— the middle-scored trade did best. What survives is narrower and weaker: the
**highest-scored** setup was the only loser, and Spearman's rho over the three
is −0.5. At n=3 that is worth nothing on its own; it is one weak strike against
the scorer, not the clean inversion previously described.

It still does not support loosening `min_score` 0.6 → 0.4, but it no longer
argues against it as strongly as reported an hour ago.

### What the exit itself shows

The trailing stop did its job precisely: it converted a position that had given
back 39% of its peak into a locked +1.11% instead of riding to expiry. Against
daytrade's 0.30% round-trip cost that is a real, if small, win — the sixth of
25 resolutions. But it also means **a trade can run 3.9 hours, peak within
0.19pp of the moon line, and still resolve as an ordinary winner.** The gap
between "nearly a full thesis" and "counts as a moon" is unforgiving, which is
why the moon half of the pattern-model gate is the binding one.

## 03:33 — The four books stack rather than diversify: 27.7% of exposure is shared, all same-side

The books are described as independent, and they choose independently, but they
draw from overlapping universes (rank ≤ 25 / 30 / 50 / 150) and so keep landing
on the same names. Measured across all 19 open positions, $26,018 gross:

| name | gross | net | books |
|---|---|---|---|
| ZEC | $2,718 | **+$2,718** | conservative, daytrade, aggressive |
| HYPE | $2,500 | **+$2,500** | conservative, longshort |
| BNB | $2,000 | **+$2,000** | conservative, daytrade |

**$7,218 — 27.7% of gross exposure — sits in names held by more than one book,
and every overlap is on the same side.** Net equals gross in all three: not one
dollar of the shared exposure offsets. The books are not hedging each other,
they are concentrating.

By name count the spread looks healthy — Herfindahl 0.0739, an effective 13.5
independent names of 15. That number is misleading on its own, because it
counts names, not co-movement: the 00:52 study measured mean pairwise 5-minute
correlation at 0.308 across the intraday universe, which puts the effective
independent count nearer 3 than 13.

**ZEC is the sharpest case.** It is the single largest exposure at 10.4% of
gross, held long by three of the four books at once (conservative +1.13%,
aggressive +8.40%, daytrade +0.03%), and it produced four of the program's
first five resolved wins. Aggressive's ZEC is currently its only position in
profit — the one thing holding that book off its lows. If ZEC reverses, three
books take the loss in the same hour, and the equity curves that look like four
independent experiments will move as one.

This sharpens the 01:31 exposure finding rather than repeating it. That one said
returns are explained by *how much* capital is deployed; this one says the four
books' deployments are not independent draws, so the combined P/L has fewer
effective bets behind it than four books × five positions suggests.

**Proposed, not actioned — a cross-book exposure cap.** A shared ledger that
refuses an entry when a symbol already carries more than some fraction of total
gross across all books would prevent a three-book stack in one name. It changes
which candidates get filled, so it is a strategy change and the owner's call.
The counter-argument is real: each book is meant to be an independent test of
its own parameters, and a shared veto couples them by construction. n = 19
positions, one regime.

## 04:35 — daytrade's gross edge is ~zero; the entire realized loss is transaction costs

Over 25 resolved trades, daytrade's mean outcome is **−0.346%** net. It pays a
0.30% round trip (15bps per side), so its mean **before costs is −0.046%** —
statistically indistinguishable from zero.

**Every dollar of daytrade's realized loss is friction, not selection.** The
book has paid $88.94 in costs against a −$191.53 realized P/L; the entry logic
itself has neither made nor lost money over this sample.

By exit reason:

| exit | n | mean |
|---|---|---|
| stop-loss | 13 | **−1.559%** |
| max hold 6h | 7 | +0.015% |
| take-profit | 3 | +3.023% |
| trailing stop | 2 | +1.216% |

The five triggered winners average **+2.30%** against thirteen stops averaging
**−1.56%**, which puts breakeven at a 40.4% win rate on triggered exits. The
achieved rate is 5 of 18, **27.8%** — below breakeven, but the shortfall is
almost exactly the cost drag.

The seven max-hold exits average **+0.015%**: dead flat, and each one still paid
0.30% to get there. Four of 25 trades resolved inside ±0.5% and seven inside
±1.0% — 28% of the book's activity is churn that pays full freight for a
non-event. This is the same bimodality recorded at 23:40, now with a price tag
attached.

**What this rules out.** It is not a stop/target geometry problem — that was
settled earlier, and gross return being zero confirms it: no rearrangement of
exits improves a signal that has no gross edge. It is also not a "bad market"
problem in the way it looked; a book with genuinely negative selection would
show a negative *gross* mean, and this one does not.

**What it points at, in order.** First, **fewer trades** — if the gross edge is
zero, every avoided trade saves 0.30% and every added one costs it, so the churn
is pure loss. That argues directly *against* the pending `min_score` 0.6 → 0.4
loosening, which would add marginal trades to a book whose marginal trade is
worth −0.30%. Second, **cost per trade**: 15bps/side is a plausible retail
figure, but it is the single largest term in this book's P/L and worth stating
as an assumption rather than a fact.

Sample: n = 25 resolved, one regime, 12 distinct symbols. The gross mean of
−0.046% has a standard error around ±0.31pp, so "zero" here means "cannot be
distinguished from zero", not "proven to be zero". A real edge of ±0.3% per
trade would be invisible at this sample size.

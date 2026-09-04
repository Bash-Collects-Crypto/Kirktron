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

Every coin that clears the gates becomes a candidate. `min_score` is not a
binding constraint in any of the four books at present, so the blocker
attributions reported all afternoon stand exactly as given — a drought is a
gate drought, and the named top blocker is the real cause.

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

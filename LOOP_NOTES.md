# Loop notes — standing context for the supervising agent

The supervision loop used to carry all of this inside its re-armed prompt,
re-sent every few minutes whether or not anything had happened. That was the
single largest token cost in the project, and none of it changes between
cycles. It lives here instead. **Read this file when you need context; do not
copy it into the loop prompt.**

`FINDINGS.md` is the evidence record and takes precedence over this file, which
is only an index and an operating manual.

## The cycle

```bash
./run_headless.sh 540      # trade, snapshot, export, summarise -- one call
```

It takes an exclusive `flock` on `.headless.lock` and exits quietly if another
supervisor is mid-cycle. That is the correct outcome, not a fault: several
supervisors call it and two traders on the same books would interleave writes
to `state_<book>.json` and `trade_log.csv` and corrupt both.

**Supervisors, in order of reliability.** Self-scheduled `ScheduleWakeup` ticks
are the cheapest but have missed outright — two consecutive failures on the
night of 5 September left 21- and 20-minute holes. The cron Routines are what
actually kept it alive, so cycle Routines now fire at **:03, :13, :33 and :43**,
with the hourly check-in at **:23** and the watchdog at **:53**. That is roughly
ten-minute coverage from a mechanism that does not silently skip. Cron cannot go
below hourly here, which is why it is six separate Routines rather than one.

Compare `tail -1 trader.log` to the clock at the start of every tick and say the
gap if it exceeds ten minutes. Stops and targets are evaluated only during a
cycle, so a gap means an exit fires late, at the next cycle's price.

Then push the dashboard (Artifact `write_db`, `db_op` batch, url
`https://claude.ai/code/artifact/1a3f5653-a47e-405f-8aaf-79a0fa22d212`,
writes = `state/current` ← `dashboard_current.json`, `state/history` ←
`dashboard_history.json`), and re-arm. That is the whole loop. Report one line
unless something resolved.

Escalate only on: a **rise** above 11 in `cycle failures`, a traceback, a
resolved trade, staleness over 10 minutes, or coverage under 8/12. A 429 is
routine and self-heals. A quiet overnight cycle is not a fault.

If a segment dies with exit 137 the harness killed it: check `tail -3
trader.log` for "received signal 15", confirm `tail -40 equity_history.csv |
cut -d, -f1,2 | sort | uniq -d` is empty, `rm -f STOP`, run another cycle.

Never `pkill` a pattern matching `paper_trader.py` — it matches the agent's own
shell. Use `touch STOP` or kill by PID.

## The funding book (added 2026-09-06 10:00)

A FIFTH book, `funding_book.py`, on `okx.py` data. It is not a momentum book: it
holds spot and shorts the perpetual in equal size, so it has no net price
exposure, and its return is the 8-hourly funding payment leveraged longs make to
shorts. Measured over 33 days an equal-weight basket of majors paid ~+5.1%/year,
13 of 15 positive. That is ~$1.40/day on $10,000 -- small and real, against four
momentum books whose per-trade intervals all straddle zero.

- It runs once per cycle from `run_headless.sh`; a venue outage is reported, not
  fatal, because the book halts rather than trade on stale rates.
- OKX is the only reachable venue: Binance 451, Bybit 403 (checked 2026-09-06).
- Costs are charged from the first tick: 5bps per leg, 0.20% per round trip
  across both legs, about fourteen days of median funding. Hence
  `MIN_HOLD_HOURS = 72`. **This strategy dies if it churns.**
- Majors only. The fattest OKX funding sits on illiquid alt perps where the spot
  leg cannot be exited at the mark -- that is a liquidity premium, not a return.
- Its first cycle opened 7 pairs and paid $7.70 in entry fees, so it starts
  BELOW $10,000 and needs about five days just to recover them. Do not read the
  first week's drawdown as failure.
- `funding.log` is gitignored; `funding_log.csv` and `state_funding.json` go to
  the data branch via `snapshot.sh`.

**THE 3%/DAY TARGET IS NOT REACHABLE.** It compounds to 48,500x a year, roughly
20x the best sustained record in financial history. Report actual numbers and say
plainly where they stand; never score progress against it as though it were in
range. Recorded here because it will be asked again.

**daytrade's pattern model is ACTIVE** as of 2026-09-06T01:06:12Z (48 resolved,
5 moons). It scores on pc_14d / pc_30d / pc_7d and its bonus now moves live
entries. The other three books remain inactive.

## Open decisions — surfaced, deliberately not actioned

The owner decides these. Do not action them unilaterally; do not re-argue one
the owner has reaffirmed.

- **Consolidating to one book.** Proposed 01:39. The case against is the 01:31
  exposure finding below; the case for is daytrade's learning rate. Both
  conditions it was waiting on have now happened (the caps fired 5 Sept 17:33;
  the model activated 6 Sept 01:06), so this one is ripe for the owner.
- **`min_score` 0.6 → 0.4 for daytrade.** The scorer test set cuts against it.
- **Excluding ZEC from the model's training rows**, or weighting rows by symbol.
  Three of five moons are ZEC and the only positive live bonus so far went to
  ZEC. See FINDINGS 01:20 and 01:45. Not a strategy parameter, but not a bug
  either — the owner decides.
- ~~A same-symbol or direction-change cooldown for daytrade.~~ **Closed 6 Sept**
  by FINDINGS 00:45: re-entries within 2h beat fresh entries and one of the five
  moons is itself a 0.5h re-entry. Do not re-propose without new data.
- **Dropping the `rank <= 25` universe bypass**, keeping an explicit blue-chip
  id set. RAIN (rank 13, GambleFi, $42M volume) is reachable through it.
- **A time-based early exit for non-movers.** n=5, far too small.
- **Marking daytrade positions from the intraday series** instead of
  `/coins/markets`. More feasible now bars carry timestamps, but it changes
  exit timing.

## What the data has already settled

Full statements with sample sizes are in `FINDINGS.md`; these are the
conclusions the loop must not re-derive.

- **Return is 93% exposure, not selection** (01:31). Time-weighted deployment
  vs ex-cost return across the four books: r = −0.963, r² = 0.927, residuals
  within 0.29pp. No book has shown selection skill. Caveat: n = 4 books over
  one regime is closer to one observation than four. Judge a book by its
  residual from that line, not raw return.
- **Cross-coin lead-lag: nothing.** 528 directed pair×lag tests, zero pass a
  family-wise |r| > 0.236. Bitcoin does not lead. The first run was invalid
  (index alignment on untimestamped bars) and is a live example of a confident
  false edge — it is the standing warning against activating a model early.
- **The 30-minute signal does not persist over six hours** — the 17:18–17:38
  cohort ran full-term at +0.98%, 0.00%, −0.17%.
- **`range_pos` is rejected as a predictor**, despite the scorer tilting toward
  it in 13 of 18 episodes.
- **Outcomes are bimodal**, so the stop catches real adverse moves, not noise.
- **Target/stop geometry cannot create edge** — achieved win rate moves in
  lockstep with breakeven.
- A **blocker census describes a book's reachable set, not the market**;
  `pc_1h` turns over hourly and decides which side a book can trade.
- **`score` is not comparable across books** — medians run 0.77 (daytrade) to
  55.86 (aggressive), a 41× spread with non-overlapping ranges. Never pool it;
  a model fitted on the pooled log would learn book identity, not signal.
- **XRP is marked at cent precision** (0.714% quantisation at $1.40) — exclude
  it from the slippage series.
- **The `--report` percent column is `change_pct`**, the signed return on
  capital, already direction-corrected. "SHORT SUI −2.35%" means the short has
  *lost* 2.35%. The dollar column is the independent check.
- **`trail_armed` is not a stored field** — arming is recomputed from
  `peak_pct` each cycle, so a missing key does not mean "not armed".
- **Data sufficiency:** ~1.2 resolutions/hour combined; Kish effective sample
  7.7 across 12 symbols. 95% CI half-width at p=0.5 is ±21.9pp at n=20 and
  ±6.9pp at n=200. Volume, breadth *and* regimes must all accumulate.

## Durability

`trade_log.csv` is the deliverable — every fill with its entry feature vector
and outcome. The pattern models are derived from it at runtime, not saved, so
they cannot be lost while it is on `kirktron-trading-data`. `archive_bars.py`
keeps 5-minute bars permanently in `intraday_bars.csv` because CoinGecko only
serves the last 24 hours. Ending a session stops the trader — marking and stops
pause, and the gap is a hole in the equity curve, not an error.

## Branch discipline

Trading data goes **only** to `kirktron-trading-data` via `snapshot.sh`. Code
and docs go to the feature branch. State files, logs and caches are gitignored,
so **switching branches does not switch the data** — an experimental strategy
run in this directory writes into the live `trade_log.csv`. For anything that
changes trading behaviour, copy the directory instead of branching.

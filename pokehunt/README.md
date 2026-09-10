# pokehunt

Watches eBay for Pokémon auctions that are about to end unnoticed, reads the
listing photos with a vision model, prices the cards it recognises against
pokemontcg.io, and posts the result to Discord.

It never bids. There is no bidding code in the package. The point of the first
month is to find out whether the recognition layer is worth trusting with money
*before* any exists.

```
eBay Taxonomy API   → real category ids for Pokémon singles + lots
eBay Browse API     → auctions in those categories, ending < 24h
local filters       → < 3 watchers, low-feedback seller, has photos
vision model        → structured card identities, each with a confidence
pokemontcg.io       → market price per identified card
Discord webhook     → photos, cards, summed value, red flags
SQLite              → every alert, so it can be scored later
```

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in the four credentials
set -a && source .env && set +a
```

You need:

- **eBay application keyset** from developer.ebay.com. Browse and Taxonomy both
  run off the client-credentials grant, so there is no user-consent flow.
- **Anthropic API key** for the vision pass.
- **Discord webhook URL** — channel settings → Integrations → Webhooks.
- **pokemontcg.io API key** is optional; it only raises the rate limit.

## Commands

```bash
python -m pokehunt categories          # what category ids discovery found
python -m pokehunt scan --dry-run      # full pass, posts nothing, writes nothing
python -m pokehunt scan                # the real thing
python -m pokehunt settle              # capture realised prices for ended lots
python -m pokehunt score --days 30     # the verdict
```

Start with `categories`. It prints the ids it discovered and the path it walked
to reach them. If those look wrong, everything downstream is wrong, and no
amount of good vision work will save it.

## Category discovery

Nothing hardcodes a category id. On the first run the taxonomy client asks eBay
for the marketplace's default category tree, requests suggestions for several
Pokémon queries, walks up to the nearest Pokémon ancestor node, pulls that whole
subtree, and classifies the leaves into singles and lots by name.

If it cannot find both a singles leaf and a lots leaf it raises and lists every
candidate it saw, rather than falling back to a guess. A wrong category id
produces a scan that looks healthy and is silently searching the wrong shelf.

Results cache to `.pokehunt-cache/categories-EBAY_US.json` for 30 days.
`--refresh` ignores the cache.

## The filters

Browse can only filter server-side on buying format, the end-date window and
price, so those go into the API query. Watch count and seller feedback are
applied locally, and every rejection is counted and printed:

```
rejections:
  ends_too_late                412
  seller_feedback_too_high     198
  too_many_watchers             87
  not_auction                   31
```

Watch that breakdown. A filter quietly eating everything is how a month gets
wasted.

**One caveat worth knowing up front:** eBay does not reliably expose a watch
count on the Browse tier. The code reads it wherever it appears and falls back
to `None` when it is absent, and `POKEHUNT_UNKNOWN_WATCHERS` decides what
happens then — `allow` (default, noisier) or `skip` (conservative, and if eBay
never returns the field, this filters out everything). Run `scan --dry-run`
once and check whether the `Watchers` field in the output says a number or
`unknown` before you commit to `skip`. If it is always `unknown`, the
under-3-watchers criterion is not actually being enforced, and you should know
that rather than assume it is working.

## Confidence and the red flag

The vision model returns a calibrated confidence per card. That gets multiplied
by a *match score* — how well the identity resolved against the pokemontcg.io
catalogue — so a confident read of a card we could only fuzzily match is
correctly treated as shaky.

Two aggregate numbers come out of a lot:

- **minimum confidence** — the weakest link.
- **value-weighted confidence** — confidence weighted by the money each card
  contributes. A blurry bulk common barely matters; a blurry card carrying 80%
  of the estimate matters enormously. This is the number the scoring report
  buckets on.

Anything below `POKEHUNT_CONFIDENCE_THRESHOLD` turns the embed red, prefixes the
title with 🚩, and adds a field naming the shaky cards and **how much of the
estimate rests on them**.

Ambiguous reprints get valued at the *median* of the candidate printings, not
the best one, and an unidentified variant falls back cheapest-first. Both
choices bias estimates down. That is deliberate: the month is meant to find out
whether the estimates are honest, and an optimistic thumb on the scale would
answer the wrong question.

## Running it for a month

Two cron entries. Scan often enough to catch short windows, settle often enough
to read final bids before eBay drops the ended item:

```cron
*/20 * * * *  cd /srv/pokehunt && set -a && . ./.env && set +a && python -m pokehunt scan   >> scan.log 2>&1
*/30 * * * *  cd /srv/pokehunt && set -a && . ./.env && set +a && python -m pokehunt settle >> settle.log 2>&1
```

Budget before you start: at `POKEHUNT_MAX_VISION_CALLS=40`, a 20-minute cadence
is up to 2,880 vision calls a day. Start lower — 10 or so — and raise it once
you have seen what the filters actually let through.

## How outcomes get captured

eBay's public APIs have no sold-price feed at the Browse tier, but an ended
auction stays retrievable through `getItem` for a while after it closes. So
`settle` polls each alerted item after its end time and reads the final bid off
the record. Items that vanish before we read them stay pending and get retried
for 7 days, then get recorded as `unavailable` so they stop being polled.

Anything missed can be backfilled by hand:

```bash
python -m pokehunt import-outcomes outcomes.csv   # item_id,final_price,sold,notes
```

The scoring report prints how many alerts never resolved. If that fraction is
large, the sample is biased toward lots eBay happened to keep queryable, and the
verdict is worth less than it looks.

## Scoring: does the recognition layer deserve money?

```bash
python -m pokehunt score --days 30
```

Two things get measured, because they fail separately.

**Calibration.** The ratio of realised sale price to our estimate. Lots reliably
clear below summed retail — that is the whole business — so a median ratio of,
say, 0.35 is not an error, it is the multiplier a bid would be built on. What
matters is the *spread*: q75/q25. A tight spread means the estimate is usable
even though it is biased, because a constant bias just divides out. A wide
spread means the estimate is a coin flip wearing a dollar sign.

**Information.** Whether the estimate beats a baseline that ignores the photos
entirely and guesses the same number every time. Both the calibration factor and
the baseline are fitted **leave-one-out**, so neither gets to fit the sale it is
being scored against. This is the test that catches a pipeline which produces
beautiful alerts and ranks lots no better than a constant.

The verdict grades four criteria, stated up front rather than rationalised after
seeing the numbers:

| criterion | bar |
|---|---|
| settled sales in the window | ≥ 30 |
| rank correlation, estimate vs realised | ≥ 0.60 |
| improvement on the constant-guess baseline | ≥ 25% median absolute error |
| realised/estimate spread in the top confidence bucket | q75/q25 ≤ 3.0 |
| simulated P&L in the top confidence bucket | > 0 |

All five → `TRUSTWORTHY ENOUGH TO RISK MONEY (start small)`. Three or four →
`PROMISING BUT NOT PROVEN`. Fewer → `DO NOT TRUST WITH MONEY`.

The report also breaks everything down by confidence bucket and by red flag. The
bucket table is the actionable part: if the estimate only holds up above 85%
confidence, then that is where the threshold belongs, and everything below it
stays alert-only however tempting it looks.

### What the simulated P&L is and is not

The policy is the same in both columns:

```
bid up to  bid_fraction × estimated_value
win when   that cap clears the realised price
pay        roughly the realised price
```

What differs is where the resale proceeds come from, and the gap between the two
is the most useful number in the report.

- **`opt`** recovers `resale_rate × estimated_value`. This trusts the
  recognition layer completely, which makes it circular: an over-read both wins
  the auction *and* books a fat imaginary profit on its own inflated number.
- **`scep`** recovers `resale_rate × (realised price ÷ clearing rate)`. This
  ignores the estimate when valuing what you bought and lets the market price
  stand in for the contents — so an over-read buys an overpriced lot and books
  the loss. It errs the other way, assuming the auction price already knew what
  the lot was worth, which is the assumption this whole system exists to bet
  against.

The truth sits between them. **If only `opt` is positive, the entire edge is an
assumption about your own recogniser**, and the report says so in as many words.
Where the estimates are honest the two columns converge; where they are noisy
they diverge, which is why the split is reported per confidence bucket. The
verdict requires both to clear zero.

Two further limits worth keeping in view:

1. **Your own bidding would have moved the prices you won.** Every simulated win
   is a lot where you would have become the new top bid. Treat the win count as
   an upper bound and both P&L columns as ceilings.
2. **`resale_rate` is an assumption, not a measurement.** Nothing in a month of
   alert-only data tells you what you would actually net reselling singles after
   fees, shipping and time. Set it from your own numbers, and notice how far the
   verdict moves when you change it — that sensitivity tells you how much of the
   apparent edge is a finding and how much is that one input.

A note on bias: a *consistent* over- or under-estimate is harmless. It divides
straight out into the clearing rate, and both P&L models agree about it. Only
inconsistency — lots wrong in different directions by different amounts — costs
money, which is why the report grades spread rather than accuracy.

The realised sale price is treated as the market's verdict on a lot. It is not a
clean ground truth for *what the cards are*: an unattended auction sells cheap
regardless of contents, which is precisely the inefficiency being hunted. That
noise shows up as spread, which is why spread is graded and a point estimate is
not.

## Tests

```bash
pytest -q
```

Every external service is mocked, including a full scan end-to-end. The scoring
tests include a pipeline whose estimates track reality (must pass) and one whose
estimates are noise (must fail) — a scorer that cannot fail its own subject is
not a scorer.

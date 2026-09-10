"""Score a month of alert-only output against what the lots actually sold for.

The question this answers is narrow and specific: does the estimated value the
recognition layer produces carry real information about what a lot is worth?

Two things get measured separately, because they fail separately:

  * calibration -- the ratio of the realised sale price to our estimate, and
    how tightly that ratio clusters. A stable ratio means the estimate is
    usable even if it is biased, because a constant bias is just a multiplier.
  * information -- whether the estimate beats a dumb baseline that ignores the
    photos entirely. A pipeline that ranks lots no better than a constant
    guess is an expensive random number generator, however pretty the alerts.

The realised sale price is treated as the market's verdict on the lot. It is
not a perfect ground truth for "what the cards are" -- an under-attended
auction sells cheap regardless of contents -- so the report also reports the
dispersion, which is where that noise shows up.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ..store.db import Store

# Value-weighted confidence buckets. The top bucket is the one that has to
# hold up before any money gets involved.
CONFIDENCE_BUCKETS = (
    (0.00, 0.50, "very low  <50%"),
    (0.50, 0.70, "low    50-70%"),
    (0.70, 0.85, "medium 70-85%"),
    (0.85, 1.01, "high     >85%"),
)

# Thresholds the verdict is graded against. These are the bar for "trust this
# with money", stated up front rather than rationalised after seeing results.
MIN_SETTLED_FOR_VERDICT = 30
MIN_SPEARMAN = 0.60
MIN_BASELINE_IMPROVEMENT = 0.25
MAX_RATIO_SPREAD = 3.0


def median(values: list[float]) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def quantile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = q * (len(ordered) - 1)
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[int(position)]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _ranks(values: list[float]) -> list[float]:
    """Average ranks, so ties do not distort the correlation."""
    indexed = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and values[indexed[j + 1]] == values[indexed[i]]:
            j += 1
        average = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[indexed[k]] = average
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 3 or len(xs) != len(ys):
        return float("nan")
    rx, ry = _ranks(xs), _ranks(ys)
    mean_x = sum(rx) / len(rx)
    mean_y = sum(ry) / len(ry)
    num = sum((a - mean_x) * (b - mean_y) for a, b in zip(rx, ry))
    den_x = math.sqrt(sum((a - mean_x) ** 2 for a in rx))
    den_y = math.sqrt(sum((b - mean_y) ** 2 for b in ry))
    if den_x == 0 or den_y == 0:
        return float("nan")
    return num / (den_x * den_y)


@dataclass
class ScoredAlert:
    item_id: str
    title: str
    url: str
    estimated_value: float
    final_price: float
    price_at_alert: float | None
    confidence: float
    min_confidence: float
    flagged: bool
    matched_cards: int
    unmatched_cards: int

    @property
    def ratio(self) -> float:
        """Realised price as a fraction of our estimate."""
        if self.estimated_value <= 0:
            return float("nan")
        return self.final_price / self.estimated_value

    @property
    def absolute_error(self) -> float:
        return abs(self.estimated_value - self.final_price)


@dataclass
class BucketScore:
    label: str
    n: int
    median_ratio: float
    q25_ratio: float
    q75_ratio: float
    spearman: float
    # Error of the CALIBRATED prediction (calibration_factor x estimate),
    # measured leave-one-out. Comparing a raw summed-retail estimate against a
    # lot's clearing price would only measure the scale gap between the two,
    # which is a constant we can just divide out.
    median_abs_error: float
    # Error of the raw estimate, kept so the scale gap stays visible.
    median_abs_error_raw: float
    calibration_factor: float
    mean_final_price: float
    simulated_pnl: float
    simulated_pnl_sceptical: float
    simulated_wins: int

    @property
    def ratio_spread(self) -> float:
        if self.q25_ratio <= 0 or math.isnan(self.q25_ratio):
            return float("inf")
        return self.q75_ratio / self.q25_ratio


@dataclass
class ScoreReport:
    window_start: str
    window_end: str
    alerts: int
    settled: int
    sold: int
    unresolved: int
    zero_value_alerts: int
    overall: BucketScore | None
    buckets: list[BucketScore] = field(default_factory=list)
    flagged: BucketScore | None = None
    unflagged: BucketScore | None = None
    baseline_median_abs_error: float = float("nan")
    baseline_improvement: float = float("nan")
    bid_fraction: float = 0.5
    resale_rate: float = 0.6
    run_stats: dict = field(default_factory=dict)
    verdict: str = ""
    verdict_reasons: list[str] = field(default_factory=list)


def simulate(
    scored: list[ScoredAlert],
    bid_fraction: float,
    resale_rate: float,
    calibration_factor: float | None = None,
) -> tuple[float, float, int]:
    """P&L of a policy that never ran, under two different assumptions.

    The policy is the same either way: bid up to bid_fraction * estimated_value,
    win when that cap clears the realised price, pay roughly the realised price
    (in an ascending auction the winner pays about one increment over the
    runner-up, which is what the observed final price already is). What differs
    is where the resale proceeds come from.

    * optimistic -- you recover resale_rate * estimated_value. This trusts the
      recognition layer completely, which makes it circular: an inflated
      estimate both wins the auction and books a fat imaginary profit. It is
      the number to quote only once the estimate has earned it.

    * sceptical -- you recover resale_rate * (final_price / k), where k is the
      rate at which lots clear against summed retail. This ignores the estimate
      when valuing what you bought and lets the market price stand in for the
      contents, so an inflated estimate buys an overpriced lot and books the
      loss. It is pessimistic in the opposite direction: it assumes the auction
      price already knew what the lot was worth, which is the assumption this
      whole system exists to bet against.

    The truth sits between them. If only the optimistic number is positive, the
    entire edge is an assumption about your own recogniser.

    Neither captures that your own bidding would have moved the prices you won,
    so treat both win counts as upper bounds.
    """
    optimistic = 0.0
    sceptical = 0.0
    wins = 0
    for alert in scored:
        cap = bid_fraction * alert.estimated_value
        if cap < alert.final_price:
            continue
        wins += 1
        optimistic += resale_rate * alert.estimated_value - alert.final_price
        if calibration_factor and calibration_factor > 0:
            implied_value = alert.final_price / calibration_factor
            sceptical += resale_rate * implied_value - alert.final_price
    return optimistic, sceptical, wins


def leave_one_out_calibrated_errors(scored: list[ScoredAlert]) -> list[float]:
    """|k_i * estimate_i - final_i|, where k_i is fitted without alert i.

    Fitting the scale factor on the same sale you then score against would
    flatter the pipeline. Holding each sale out keeps the comparison against
    the baseline honest.
    """
    errors: list[float] = []
    for index, alert in enumerate(scored):
        others = [
            other.ratio
            for j, other in enumerate(scored)
            if j != index and not math.isnan(other.ratio)
        ]
        if not others:
            continue
        factor = median(others)
        errors.append(abs(factor * alert.estimated_value - alert.final_price))
    return errors


def score_group(
    label: str, scored: list[ScoredAlert], bid_fraction: float, resale_rate: float
) -> BucketScore:
    ratios = [a.ratio for a in scored if not math.isnan(a.ratio)]
    factor = median(ratios)
    pnl, pnl_sceptical, wins = simulate(scored, bid_fraction, resale_rate, factor)
    calibrated_errors = leave_one_out_calibrated_errors(scored)
    return BucketScore(
        label=label,
        n=len(scored),
        median_ratio=median(ratios),
        q25_ratio=quantile(ratios, 0.25),
        q75_ratio=quantile(ratios, 0.75),
        spearman=spearman(
            [a.estimated_value for a in scored], [a.final_price for a in scored]
        ),
        median_abs_error=median(calibrated_errors) if calibrated_errors else float("nan"),
        median_abs_error_raw=median([a.absolute_error for a in scored]),
        calibration_factor=median(ratios),
        mean_final_price=(
            sum(a.final_price for a in scored) / len(scored) if scored else float("nan")
        ),
        simulated_pnl=pnl,
        simulated_pnl_sceptical=pnl_sceptical,
        simulated_wins=wins,
    )


def build_report(
    store: Store,
    days: int = 30,
    end: datetime | None = None,
    bid_fraction: float = 0.5,
    resale_rate: float = 0.6,
) -> ScoreReport:
    end = end or datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    rows = store.alerts_between(start.isoformat(), end.isoformat())

    scored: list[ScoredAlert] = []
    settled = 0
    sold = 0
    zero_value = 0

    for row in rows:
        if row["estimated_value"] is not None and row["estimated_value"] <= 0:
            zero_value += 1
        if row["outcome_source"] is None:
            continue
        settled += 1
        if not row["sold"]:
            continue
        sold += 1
        final_price = row["final_price"]
        if final_price is None or final_price <= 0:
            continue
        scored.append(
            ScoredAlert(
                item_id=row["item_id"],
                title=row["title"],
                url=row["url"],
                estimated_value=float(row["estimated_value"] or 0.0),
                final_price=float(final_price),
                price_at_alert=row["price_at_alert"],
                confidence=float(row["value_weighted_confidence"] or 0.0),
                min_confidence=float(row["min_confidence"] or 0.0),
                flagged=bool(row["flagged_low_confidence"]),
                matched_cards=int(row["matched_card_count"] or 0),
                unmatched_cards=int(row["unmatched_card_count"] or 0),
            )
        )

    report = ScoreReport(
        window_start=start.isoformat(),
        window_end=end.isoformat(),
        alerts=len(rows),
        settled=settled,
        sold=sold,
        unresolved=len(rows) - settled,
        zero_value_alerts=zero_value,
        overall=None,
        bid_fraction=bid_fraction,
        resale_rate=resale_rate,
        run_stats=store.run_stats(start.isoformat(), end.isoformat()),
    )

    if not scored:
        report.verdict = "INSUFFICIENT DATA"
        report.verdict_reasons = ["no settled alerts with a realised sale price"]
        return report

    report.overall = score_group("overall", scored, bid_fraction, resale_rate)

    for low, high, label in CONFIDENCE_BUCKETS:
        members = [a for a in scored if low <= a.confidence < high]
        if members:
            report.buckets.append(score_group(label, members, bid_fraction, resale_rate))

    flagged = [a for a in scored if a.flagged]
    unflagged = [a for a in scored if not a.flagged]
    if flagged:
        report.flagged = score_group("flagged", flagged, bid_fraction, resale_rate)
    if unflagged:
        report.unflagged = score_group("unflagged", unflagged, bid_fraction, resale_rate)

    # Baseline: ignore the photos entirely and guess the same number for every
    # lot -- the median realised price, again fitted leave-one-out so both
    # sides of the comparison get the same handicap. Beating this is the
    # minimum bar for the recognition layer mattering at all.
    baseline_errors = []
    for index, alert in enumerate(scored):
        others = [other.final_price for j, other in enumerate(scored) if j != index]
        if others:
            baseline_errors.append(abs(median(others) - alert.final_price))
    report.baseline_median_abs_error = (
        median(baseline_errors) if baseline_errors else float("nan")
    )
    if report.baseline_median_abs_error > 0:
        report.baseline_improvement = (
            report.baseline_median_abs_error - report.overall.median_abs_error
        ) / report.baseline_median_abs_error

    _grade(report)
    return report


def _grade(report: ScoreReport) -> None:
    reasons: list[str] = []
    overall = report.overall
    assert overall is not None

    if overall.n < MIN_SETTLED_FOR_VERDICT:
        report.verdict = "INSUFFICIENT DATA"
        reasons.append(
            f"only {overall.n} settled sales; need {MIN_SETTLED_FOR_VERDICT} before "
            "any of these numbers mean anything"
        )
        report.verdict_reasons = reasons
        return

    passes = []

    rho_ok = not math.isnan(overall.spearman) and overall.spearman >= MIN_SPEARMAN
    passes.append(rho_ok)
    reasons.append(
        f"{'PASS' if rho_ok else 'FAIL'} rank correlation estimate vs realised: "
        f"{overall.spearman:.2f} (need >= {MIN_SPEARMAN:.2f})"
    )

    baseline_ok = (
        not math.isnan(report.baseline_improvement)
        and report.baseline_improvement >= MIN_BASELINE_IMPROVEMENT
    )
    passes.append(baseline_ok)
    reasons.append(
        f"{'PASS' if baseline_ok else 'FAIL'} calibrated estimate beats constant-guess baseline by "
        f"{report.baseline_improvement * 100:.0f}% median absolute error "
        f"(need >= {MIN_BASELINE_IMPROVEMENT * 100:.0f}%)"
    )

    top_bucket = report.buckets[-1] if report.buckets else None
    spread_ok = top_bucket is not None and top_bucket.ratio_spread <= MAX_RATIO_SPREAD
    passes.append(spread_ok)
    if top_bucket is None:
        reasons.append("FAIL no alerts landed in any confidence bucket")
    else:
        reasons.append(
            f"{'PASS' if spread_ok else 'FAIL'} realised/estimate spread in the "
            f"'{top_bucket.label}' bucket: q75/q25 = {top_bucket.ratio_spread:.1f} "
            f"(need <= {MAX_RATIO_SPREAD:.1f})"
        )

    # Both models have to clear zero. Passing only the optimistic one means the
    # edge is an assumption about the recogniser rather than a measurement.
    pnl_ok = (
        top_bucket is not None
        and top_bucket.simulated_pnl > 0
        and top_bucket.simulated_pnl_sceptical > 0
    )
    passes.append(pnl_ok)
    if top_bucket is not None:
        reasons.append(
            f"{'PASS' if pnl_ok else 'FAIL'} simulated P&L in the top bucket over "
            f"{top_bucket.simulated_wins} wins at bid={report.bid_fraction:.0%} of "
            f"estimate, resale={report.resale_rate:.0%}: "
            f"${top_bucket.simulated_pnl:,.2f} trusting the estimate, "
            f"${top_bucket.simulated_pnl_sceptical:,.2f} ignoring it"
        )
        if top_bucket.simulated_pnl > 0 >= top_bucket.simulated_pnl_sceptical:
            reasons.append(
                "INFO the top bucket only profits when the estimate is taken at "
                "face value — that is the recogniser marking its own homework"
            )

    if all(passes):
        report.verdict = "TRUSTWORTHY ENOUGH TO RISK MONEY (start small)"
    elif sum(passes) >= 3:
        report.verdict = "PROMISING BUT NOT PROVEN — keep it alert-only"
    else:
        report.verdict = "DO NOT TRUST WITH MONEY"

    reasons.append(
        f"INFO lots cleared at a median of {overall.median_ratio:.2f}x the summed "
        f"market value; that multiplier, not the raw estimate, is what a bid "
        f"would have to be built on"
    )

    if report.flagged and report.unflagged:
        delta = report.flagged.ratio_spread - report.unflagged.ratio_spread
        reasons.append(
            f"INFO red-flagged lots are {'noisier' if delta > 0 else 'no noisier'} "
            f"than clean ones (spread {report.flagged.ratio_spread:.1f} vs "
            f"{report.unflagged.ratio_spread:.1f}) — "
            + (
                "the flag is doing its job"
                if delta > 0
                else "the flag is not separating anything, retune the threshold"
            )
        )

    if report.unresolved:
        reasons.append(
            f"INFO {report.unresolved} of {report.alerts} alerts never got a realised "
            "price; if that fraction is large the sample is biased toward lots eBay "
            "kept queryable"
        )

    report.verdict_reasons = reasons


def _fmt(value: float, spec: str = ".2f") -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    return format(value, spec)


def _bucket_row(bucket: BucketScore) -> str:
    return (
        f"  {bucket.label:<16} n={bucket.n:<4} "
        f"median realised/est={_fmt(bucket.median_ratio):>6} "
        f"[{_fmt(bucket.q25_ratio)}–{_fmt(bucket.q75_ratio)}] "
        f"rho={_fmt(bucket.spearman):>6} "
        f"k={_fmt(bucket.calibration_factor)} "
        f"calAE=${_fmt(bucket.median_abs_error):>8} "
        f"P&L opt=${_fmt(bucket.simulated_pnl):>9} "
        f"scep=${_fmt(bucket.simulated_pnl_sceptical):>9} "
        f"({bucket.simulated_wins} wins)"
    )


def render(report: ScoreReport) -> str:
    lines = [
        "=" * 78,
        f"pokehunt scoring report  {report.window_start[:10]} .. {report.window_end[:10]}",
        "=" * 78,
        "",
        f"alerts sent:            {report.alerts}",
        f"settled (outcome known):{report.settled}",
        f"sold with a price:      {report.sold}",
        f"never resolved:         {report.unresolved}",
        f"alerts valued at $0:    {report.zero_value_alerts}",
    ]

    if report.run_stats:
        lines.append(
            f"scans: {report.run_stats.get('runs', 0)} runs, "
            f"{report.run_stats.get('candidates_seen', 0)} candidates seen, "
            f"{report.run_stats.get('vision_calls', 0)} vision calls"
        )

    if report.overall is None:
        lines += ["", f"VERDICT: {report.verdict}"]
        lines += [f"  - {reason}" for reason in report.verdict_reasons]
        return "\n".join(lines)

    lines += [
        "",
        "OVERALL",
        _bucket_row(report.overall),
        f"  raw (uncalibrated) medAE=${_fmt(report.overall.median_abs_error_raw)}"
        f" — the gap between summed retail and lot clearing price",
        f"  constant-guess baseline medAE=${_fmt(report.baseline_median_abs_error)}"
        f"  → calibrated estimate improves on it by "
        f"{_fmt(report.baseline_improvement * 100, '.0f')}%",
        "",
        "BY VALUE-WEIGHTED CONFIDENCE",
    ]
    lines += [_bucket_row(bucket) for bucket in report.buckets]

    if report.flagged or report.unflagged:
        lines += ["", "BY RED FLAG"]
        if report.unflagged:
            lines.append(_bucket_row(report.unflagged))
        if report.flagged:
            lines.append(_bucket_row(report.flagged))

    lines += [
        "",
        "SIMULATION ASSUMPTIONS",
        f"  bid cap = {report.bid_fraction:.0%} of estimated value; "
        f"resale nets {report.resale_rate:.0%}",
        "  opt  = resale on the ESTIMATE — trusts the recogniser, so an inflated",
        "         estimate books an imaginary profit. Circular by construction.",
        "  scep = resale on the realised price divided by the clearing rate —",
        "         ignores the estimate, so an inflated one books a real loss.",
        "  The truth is between them. Only the optimistic number being positive",
        "  means the edge is an assumption about your recogniser, not a finding.",
        "  Neither captures that your own bids would have pushed prices up, so",
        "  both win counts are upper bounds.",
        "",
        f"VERDICT: {report.verdict}",
    ]
    lines += [f"  - {reason}" for reason in report.verdict_reasons]
    lines.append("")
    return "\n".join(lines)


def to_json(report: ScoreReport) -> str:
    def encode(obj):
        if isinstance(obj, BucketScore):
            data = obj.__dict__.copy()
            data["ratio_spread"] = obj.ratio_spread
            return data
        if isinstance(obj, float) and math.isnan(obj):
            return None
        raise TypeError(type(obj))

    return json.dumps(report.__dict__, default=encode, indent=2)

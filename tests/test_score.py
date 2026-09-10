import json
import math
import random
from datetime import datetime, timedelta, timezone

import pytest

from pokehunt.pipeline.score import (
    MIN_SETTLED_FOR_VERDICT,
    build_report,
    median,
    quantile,
    render,
    simulate,
    spearman,
    to_json,
)
from pokehunt.store.db import Store

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


def seed_alert(store, item_id, estimated, final, confidence, flagged=False, days_ago=5, sold=True):
    scanned = (NOW - timedelta(days=days_ago)).isoformat()
    store.record_alert(
        item_id=item_id,
        scanned_at=scanned,
        title=f"lot {item_id}",
        url=f"https://ebay.com/itm/{item_id}",
        category_id="99011",
        category_kind="lots",
        end_time=(NOW - timedelta(days=days_ago - 1)).isoformat(),
        price_at_alert=(final * 0.4) if final is not None else None,
        currency="USD",
        bid_count_at_alert=1,
        watch_count=1,
        seller_username="s",
        seller_feedback_score=10,
        seller_feedback_pct=100.0,
        estimated_value=estimated,
        matched_card_count=3,
        unmatched_card_count=0,
        min_confidence=confidence,
        value_weighted_confidence=confidence,
        flagged_low_confidence=int(flagged),
        vision_model="test",
        vision_error=None,
        identified_json="{}",
        images_json="[]",
    )
    if final is not None:
        store.record_outcome(item_id, sold=sold, final_price=final, final_bid_count=4, source="browse_poll")


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "test.db")
    yield s
    s.close()


def test_median_and_quantile():
    assert median([3, 1, 2]) == 2
    assert median([4, 1, 2, 3]) == 2.5
    assert math.isnan(median([]))
    assert quantile([1, 2, 3, 4], 0.25) == pytest.approx(1.75)
    assert quantile([5], 0.9) == 5


def test_spearman_detects_monotonic_and_random_relationships():
    xs = list(range(20))
    assert spearman(xs, [x * 3 for x in xs]) == pytest.approx(1.0)
    assert spearman(xs, [-x for x in xs]) == pytest.approx(-1.0)
    assert math.isnan(spearman([1, 2], [1, 2]))
    # Ties must not blow it up.
    assert spearman([1, 1, 1, 2], [1, 2, 3, 4]) == pytest.approx(0.7745966, abs=1e-5)


def test_simulate_only_wins_when_the_bid_cap_clears_the_price():
    class Fake:
        def __init__(self, estimated, final):
            self.estimated_value = estimated
            self.final_price = final

    alerts = [Fake(100.0, 40.0), Fake(100.0, 80.0)]
    # cap = 50: wins only the $40 lot; nets 0.6*100 - 40 = +20
    pnl, _, wins = simulate(alerts, bid_fraction=0.5, resale_rate=0.6)
    assert wins == 1 and pnl == pytest.approx(20.0)

    # cap = 100: wins both; the $80 lot loses 0.6*100 - 80 = -20
    pnl, _, wins = simulate(alerts, bid_fraction=1.0, resale_rate=0.6)
    assert wins == 2 and pnl == pytest.approx(0.0)


def test_sceptical_pnl_ignores_the_estimate_when_valuing_the_purchase():
    """An inflated estimate must book a loss, not an imaginary profit."""

    class Fake:
        def __init__(self, estimated, final):
            self.estimated_value = estimated
            self.final_price = final

    # Lots normally clear at 0.5x. This one was estimated at $1000 and sold for
    # $100, so the estimate was 5x too high.
    alerts = [Fake(1000.0, 100.0)]
    optimistic, sceptical, wins = simulate(
        alerts, bid_fraction=0.5, resale_rate=0.6, calibration_factor=0.5
    )
    assert wins == 1
    # Trusting the estimate: 0.6 * 1000 - 100 = +500. Pure fiction.
    assert optimistic == pytest.approx(500.0)
    # Ignoring it: the lot is really worth about 100/0.5 = 200, so
    # 0.6 * 200 - 100 = +20. Two orders of magnitude of difference is the
    # whole point of reporting both.
    assert sceptical == pytest.approx(20.0)


def test_a_consistent_bias_is_absorbed_by_the_calibration_factor(store):
    """Estimates 5x too high but uniformly so: both P&L models must agree.

    A constant bias is harmless — it divides straight out into the clearing
    rate — so the two simulations should not disagree about it.
    """
    rng = random.Random(23)
    for i in range(40):
        final = rng.uniform(20, 200)
        seed_alert(store, f"inf{i}", final * 5 * rng.uniform(0.98, 1.02), final, 0.9)

    report = build_report(store, days=30, end=NOW, bid_fraction=0.5, resale_rate=0.6)
    top = report.buckets[-1]
    assert top.calibration_factor == pytest.approx(0.2, abs=0.01)
    assert top.simulated_pnl == pytest.approx(top.simulated_pnl_sceptical, rel=0.05)


def test_a_pipeline_that_only_profits_by_trusting_itself_is_called_out(store):
    """Estimates inflated inconsistently: the two models must diverge.

    Half the lots are estimated sanely and half are wild over-reads. The
    over-reads are exactly the ones a bid cap set as a fraction of the estimate
    wins, so trusting the estimate books a fortune while valuing the purchase
    off the market price books a loss.
    """
    rng = random.Random(5)
    for i in range(40):
        final = rng.uniform(20, 200)
        estimated = final / 0.4 if i % 2 else final / 0.04
        seed_alert(store, f"mix{i}", estimated, final, 0.9)

    report = build_report(store, days=30, end=NOW, bid_fraction=0.5, resale_rate=0.2)
    top = report.buckets[-1]
    assert top.simulated_pnl > 0
    assert top.simulated_pnl_sceptical < 0
    assert any("marking its own homework" in r for r in report.verdict_reasons)
    assert not report.verdict.startswith("TRUSTWORTHY")


def test_no_settled_alerts_reports_insufficient_data(store):
    seed_alert(store, "a", 100.0, None, 0.9)
    report = build_report(store, days=30, end=NOW)
    assert report.verdict == "INSUFFICIENT DATA"
    assert report.unresolved == 1
    assert "no settled alerts" in report.verdict_reasons[0]
    assert "INSUFFICIENT DATA" in render(report)


def test_small_sample_refuses_to_render_a_verdict(store):
    for i in range(5):
        seed_alert(store, f"i{i}", 100.0, 50.0, 0.9)
    report = build_report(store, days=30, end=NOW)
    assert report.verdict == "INSUFFICIENT DATA"
    assert str(MIN_SETTLED_FOR_VERDICT) in report.verdict_reasons[0]


def test_a_recognition_layer_that_works_passes(store):
    """Estimates track realised prices closely -> the pipeline should pass."""
    rng = random.Random(7)
    for i in range(60):
        final = rng.uniform(20, 400)
        estimated = final / 0.5 * rng.uniform(0.92, 1.08)
        seed_alert(store, f"good{i}", estimated, final, confidence=0.9)

    report = build_report(store, days=30, end=NOW, bid_fraction=0.5, resale_rate=0.6)
    assert report.sold == 60
    assert report.overall.spearman > 0.9
    assert report.overall.median_ratio == pytest.approx(0.5, abs=0.05)
    assert report.overall.ratio_spread < 1.5
    assert report.verdict.startswith("TRUSTWORTHY")

    text = render(report)
    assert "OVERALL" in text and "VERDICT" in text
    assert "BY VALUE-WEIGHTED CONFIDENCE" in text


def test_a_recognition_layer_that_is_noise_fails(store):
    """Estimates unrelated to realised prices must not earn any trust."""
    rng = random.Random(11)
    for i in range(60):
        final = rng.uniform(20, 400)
        estimated = rng.uniform(20, 2000)
        seed_alert(store, f"bad{i}", estimated, final, confidence=0.9)

    report = build_report(store, days=30, end=NOW)
    assert abs(report.overall.spearman) < 0.4
    assert report.verdict == "DO NOT TRUST WITH MONEY"
    assert any(reason.startswith("FAIL") for reason in report.verdict_reasons)


def test_confidence_buckets_separate_good_reads_from_bad_ones(store):
    rng = random.Random(3)
    for i in range(40):
        final = rng.uniform(50, 300)
        seed_alert(store, f"hi{i}", final / 0.5 * rng.uniform(0.95, 1.05), final, confidence=0.92)
    for i in range(40):
        final = rng.uniform(50, 300)
        seed_alert(store, f"lo{i}", rng.uniform(50, 3000), final, confidence=0.4, flagged=True)

    report = build_report(store, days=30, end=NOW)
    labels = {b.label: b for b in report.buckets}
    high = labels["high     >85%"]
    low = labels["very low  <50%"]
    assert high.n == 40 and low.n == 40
    assert high.ratio_spread < low.ratio_spread
    assert report.flagged is not None and report.unflagged is not None
    assert any("the flag is doing its job" in r for r in report.verdict_reasons)


def test_report_counts_unsold_and_unresolved_separately(store):
    seed_alert(store, "sold", 100.0, 40.0, 0.9)
    seed_alert(store, "unsold", 100.0, 0.0, 0.9, sold=False)
    seed_alert(store, "pending", 100.0, None, 0.9)
    report = build_report(store, days=30, end=NOW)
    assert report.alerts == 3
    assert report.settled == 2
    assert report.sold == 1
    assert report.unresolved == 1


def test_window_excludes_older_alerts(store):
    seed_alert(store, "recent", 100.0, 40.0, 0.9, days_ago=5)
    seed_alert(store, "ancient", 100.0, 40.0, 0.9, days_ago=200)
    report = build_report(store, days=30, end=NOW)
    assert report.alerts == 1


def test_json_output_is_serialisable(store):
    for i in range(35):
        seed_alert(store, f"j{i}", 100.0 + i, 50.0 + i, 0.9)
    report = build_report(store, days=30, end=NOW)
    parsed = json.loads(to_json(report))
    assert parsed["verdict"]
    assert parsed["overall"]["n"] == 35
    assert "ratio_spread" in parsed["overall"]


def test_calibration_is_fitted_leave_one_out(store):
    """The scale factor must not be fitted on the sale it is scored against."""
    from pokehunt.pipeline.score import ScoredAlert, leave_one_out_calibrated_errors

    def alert(estimated, final):
        return ScoredAlert(
            item_id="x", title="t", url="u", estimated_value=estimated,
            final_price=final, price_at_alert=None, confidence=0.9,
            min_confidence=0.9, flagged=False, matched_cards=1, unmatched_cards=0,
        )

    # Three lots clear at exactly 0.5x; the fourth is an outlier at 2.0x.
    scored = [alert(100.0, 50.0), alert(200.0, 100.0), alert(300.0, 150.0), alert(100.0, 200.0)]
    errors = leave_one_out_calibrated_errors(scored)
    # The clean lots are predicted exactly by the others' factor of 0.5.
    assert errors[:3] == pytest.approx([0.0, 0.0, 0.0])
    # The outlier is not allowed to fit itself.
    assert errors[3] == pytest.approx(150.0)


def test_calibration_factor_is_reported_for_bidding(store):
    rng = random.Random(19)
    for i in range(40):
        final = rng.uniform(30, 300)
        seed_alert(store, f"c{i}", final / 0.35, final, confidence=0.9)
    report = build_report(store, days=30, end=NOW)
    assert report.overall.calibration_factor == pytest.approx(0.35, abs=0.01)
    assert any("median of 0.35x" in reason for reason in report.verdict_reasons)

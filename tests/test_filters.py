from datetime import datetime, timedelta, timezone

from pokehunt.config import FilterConfig
from pokehunt.ebay.browse import build_filter
from pokehunt.ebay.models import Listing, extract_watch_count
from pokehunt.pipeline.filters import apply_filters, reject_reason

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def make_listing(**overrides) -> Listing:
    defaults = dict(
        item_id="v1|1|0",
        title="Pokemon card lot",
        url="https://ebay.com/itm/1",
        category_id="99011",
        buying_options=["AUCTION"],
        end_time=NOW + timedelta(hours=6),
        current_price=25.0,
        currency="USD",
        bid_count=1,
        watch_count=1,
        seller_username="newseller",
        seller_feedback_score=12,
        seller_feedback_pct=100.0,
        image_urls=["https://img/1.jpg"],
    )
    defaults.update(overrides)
    return Listing(**defaults)


def test_clean_listing_passes():
    assert reject_reason(make_listing(), FilterConfig(), NOW) is None


def test_rejects_non_auction():
    listing = make_listing(buying_options=["FIXED_PRICE"])
    assert reject_reason(listing, FilterConfig(), NOW) == "not_auction"


def test_rejects_ending_outside_window():
    listing = make_listing(end_time=NOW + timedelta(hours=48))
    assert reject_reason(listing, FilterConfig(), NOW) == "ends_too_late"


def test_rejects_already_ended():
    listing = make_listing(end_time=NOW - timedelta(minutes=1))
    assert reject_reason(listing, FilterConfig(), NOW) == "already_ended"


def test_watcher_threshold_is_exclusive():
    assert reject_reason(make_listing(watch_count=2), FilterConfig(), NOW) is None
    assert (
        reject_reason(make_listing(watch_count=3), FilterConfig(), NOW)
        == "too_many_watchers"
    )


def test_unknown_watchers_respects_policy():
    listing = make_listing(watch_count=None)
    assert reject_reason(listing, FilterConfig(unknown_watchers="allow"), NOW) is None
    assert (
        reject_reason(listing, FilterConfig(unknown_watchers="skip"), NOW)
        == "watchers_unknown"
    )


def test_rejects_established_sellers():
    listing = make_listing(seller_feedback_score=5000)
    assert reject_reason(listing, FilterConfig(), NOW) == "seller_feedback_too_high"


def test_brand_new_seller_with_no_percentage_is_kept():
    listing = make_listing(seller_feedback_score=0, seller_feedback_pct=None)
    assert reject_reason(listing, FilterConfig(), NOW) is None


def test_rejects_burned_seller():
    listing = make_listing(seller_feedback_score=40, seller_feedback_pct=62.0)
    assert (
        reject_reason(listing, FilterConfig(), NOW) == "seller_feedback_pct_too_low"
    )


def test_rejects_listing_without_photos():
    assert reject_reason(make_listing(image_urls=[]), FilterConfig(), NOW) == "no_images"


def test_apply_filters_counts_rejections():
    listings = [
        make_listing(item_id="a"),
        make_listing(item_id="b", watch_count=9),
        make_listing(item_id="c", buying_options=["FIXED_PRICE"]),
        make_listing(item_id="d", watch_count=20),
    ]
    result = apply_filters(listings, FilterConfig(), NOW)
    assert [l.item_id for l in result.kept] == ["a"]
    assert result.rejections["too_many_watchers"] == 2
    assert result.rejections["not_auction"] == 1
    assert "too_many_watchers=2" in result.summary()


def test_build_filter_is_auction_scoped_and_time_boxed():
    filter_string = build_filter(24.0, 400.0, now=NOW)
    assert "buyingOptions:{AUCTION}" in filter_string
    assert "itemEndDate:[2026-09-10T12:00:00.000Z..2026-09-11T12:00:00.000Z]" in filter_string
    assert "price:[..400.00]" in filter_string
    assert "priceCurrency:USD" in filter_string


def test_extract_watch_count_handles_absent_field():
    assert extract_watch_count({"itemId": "1"}) is None
    assert extract_watch_count({"watchCount": 4}) == 4
    assert extract_watch_count({"listingInfo": {"watchCount": "7"}}) == 7

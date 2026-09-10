"""The local half of the hunt criteria.

Browse can filter on format, end window and price. Watch count and seller
feedback it cannot, so they are applied here -- with an explicit record of why
each listing was dropped, because a filter that silently eats everything is the
failure mode that wastes a month.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

from ..config import FilterConfig
from ..ebay.models import Listing


@dataclass
class FilterResult:
    kept: list[Listing]
    rejections: Counter

    def summary(self) -> str:
        if not self.rejections:
            return "no rejections"
        return ", ".join(f"{reason}={count}" for reason, count in self.rejections.most_common())


def reject_reason(
    listing: Listing, config: FilterConfig, now: datetime | None = None
) -> str | None:
    now = now or datetime.now(timezone.utc)

    if not listing.is_auction:
        return "not_auction"

    hours = listing.hours_to_end(now)
    if hours is None:
        return "no_end_time"
    if hours < 0:
        return "already_ended"
    if hours > config.ending_within_hours:
        return "ends_too_late"

    if listing.watch_count is None:
        if config.unknown_watchers == "skip":
            return "watchers_unknown"
    elif listing.watch_count >= config.max_watchers:
        return "too_many_watchers"

    score = listing.seller_feedback_score
    if score is None:
        return "seller_feedback_unknown"
    if score >= config.max_seller_feedback:
        return "seller_feedback_too_high"

    pct = listing.seller_feedback_pct
    # A brand-new seller with no ratings yet has no percentage; that is the
    # population we want, so only reject a percentage we can actually read.
    if pct is not None and pct < config.min_seller_feedback_pct and score > 0:
        return "seller_feedback_pct_too_low"

    if listing.current_price is not None and listing.current_price > config.max_current_price:
        return "price_too_high"

    if not listing.image_urls:
        return "no_images"

    return None


def apply_filters(
    listings: list[Listing], config: FilterConfig, now: datetime | None = None
) -> FilterResult:
    kept: list[Listing] = []
    rejections: Counter = Counter()

    for listing in listings:
        reason = reject_reason(listing, config, now)
        if reason is None:
            kept.append(listing)
        else:
            rejections[reason] += 1

    return FilterResult(kept=kept, rejections=rejections)

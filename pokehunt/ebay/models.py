"""Normalised views over eBay Browse API payloads."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def parse_ebay_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _money(node: dict | None) -> float | None:
    if not node:
        return None
    raw = node.get("value")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


# Places a watch count has been observed to appear across Browse responses and
# response variants. It is not a guaranteed field -- see Listing.watch_count.
_WATCH_COUNT_KEYS = ("watchCount", "itemWatchCount")


def extract_watch_count(payload: dict) -> int | None:
    for key in _WATCH_COUNT_KEYS:
        value = payload.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    listing_info = payload.get("listingInfo") or {}
    value = listing_info.get("watchCount")
    if value is not None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None


@dataclass
class Listing:
    item_id: str
    title: str
    url: str
    category_id: str | None
    buying_options: list[str]
    end_time: datetime | None
    current_price: float | None
    currency: str | None
    bid_count: int | None
    # None means eBay did not tell us. That is different from zero, and the
    # filter treats it differently (see FilterConfig.unknown_watchers).
    watch_count: int | None
    seller_username: str | None
    seller_feedback_score: int | None
    seller_feedback_pct: float | None
    image_urls: list[str] = field(default_factory=list)
    condition: str | None = None
    raw: dict = field(default_factory=dict)

    @property
    def is_auction(self) -> bool:
        return "AUCTION" in self.buying_options

    def hours_to_end(self, now: datetime | None = None) -> float | None:
        if self.end_time is None:
            return None
        now = now or datetime.now(timezone.utc)
        return (self.end_time - now).total_seconds() / 3600.0

    @classmethod
    def from_summary(cls, payload: dict) -> "Listing":
        seller = payload.get("seller") or {}
        images = []
        primary = (payload.get("image") or {}).get("imageUrl")
        if primary:
            images.append(primary)
        for extra in payload.get("additionalImages") or []:
            url = extra.get("imageUrl")
            if url:
                images.append(url)

        price_node = payload.get("currentBidPrice") or payload.get("price") or {}

        feedback_pct = seller.get("feedbackPercentage")
        try:
            feedback_pct = float(feedback_pct) if feedback_pct is not None else None
        except (TypeError, ValueError):
            feedback_pct = None

        feedback_score = seller.get("feedbackScore")
        try:
            feedback_score = int(feedback_score) if feedback_score is not None else None
        except (TypeError, ValueError):
            feedback_score = None

        return cls(
            item_id=payload.get("itemId", ""),
            title=payload.get("title", ""),
            url=payload.get("itemWebUrl", ""),
            category_id=str(payload["categoryId"]) if payload.get("categoryId") else None,
            buying_options=list(payload.get("buyingOptions") or []),
            end_time=parse_ebay_time(payload.get("itemEndDate")),
            current_price=_money(price_node),
            currency=price_node.get("currency"),
            bid_count=payload.get("bidCount"),
            watch_count=extract_watch_count(payload),
            seller_username=seller.get("username"),
            seller_feedback_score=feedback_score,
            seller_feedback_pct=feedback_pct,
            image_urls=images,
            condition=payload.get("condition"),
            raw=payload,
        )

    def merge_detail(self, detail: dict) -> "Listing":
        """Fold a getItem payload into this summary.

        getItem carries the full image set and, when eBay chooses to expose it,
        the watch count. Only fill gaps -- the summary's numbers are fine.
        """
        images = list(self.image_urls)
        primary = (detail.get("image") or {}).get("imageUrl")
        if primary and primary not in images:
            images.append(primary)
        for extra in detail.get("additionalImages") or []:
            url = extra.get("imageUrl")
            if url and url not in images:
                images.append(url)
        self.image_urls = images

        detail_watchers = extract_watch_count(detail)
        if detail_watchers is not None:
            self.watch_count = detail_watchers

        if detail.get("bidCount") is not None:
            self.bid_count = detail["bidCount"]

        detail_price = _money(detail.get("currentBidPrice") or detail.get("price"))
        if detail_price is not None:
            self.current_price = detail_price

        if self.category_id is None and detail.get("categoryId"):
            self.category_id = str(detail["categoryId"])

        if self.end_time is None:
            self.end_time = parse_ebay_time(detail.get("itemEndDate"))

        self.raw = {**self.raw, "detail": detail}
        return self

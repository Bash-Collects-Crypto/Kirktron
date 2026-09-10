"""One scan: search -> filter -> vision -> value -> alert -> record.

Alert-only by design. There is no bidding code anywhere in this package, so a
misconfigured run can waste API spend but cannot spend money on cards.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from ..alerts.discord import build_payload
from ..context import Clients
from ..ebay.browse import build_filter
from ..ebay.models import Listing
from ..ebay.taxonomy import CategorySet, discover_categories
from ..tcg.matcher import LotValuation, value_lot
from ..vision.schema import LotIdentification
from .filters import apply_filters

log = logging.getLogger(__name__)


@dataclass
class ScanReport:
    candidates_seen: int = 0
    passed_prefilter: int = 0
    passed_filters: int = 0
    vision_calls: int = 0
    alerts_sent: int = 0
    skipped_already_alerted: int = 0
    rejections: dict | None = None
    errors: list[str] | None = None

    def render(self) -> str:
        lines = [
            f"candidates seen:      {self.candidates_seen}",
            f"passed prefilter:     {self.passed_prefilter}",
            f"passed full filters:  {self.passed_filters}",
            f"already alerted:      {self.skipped_already_alerted}",
            f"vision calls:         {self.vision_calls}",
            f"alerts sent:          {self.alerts_sent}",
        ]
        if self.rejections:
            lines.append("rejections:")
            for reason, count in sorted(
                self.rejections.items(), key=lambda kv: kv[1], reverse=True
            ):
                lines.append(f"  {reason:<28} {count}")
        if self.errors:
            lines.append(f"errors: {len(self.errors)}")
            lines.extend(f"  {err}" for err in self.errors[:10])
        return "\n".join(lines)


def _serialise_identities(
    identification: LotIdentification, valuation: LotValuation
) -> str:
    return json.dumps(
        {
            "model": identification.model,
            "error": identification.error,
            "total_cards_visible": identification.total_cards_visible,
            "identified_fraction": identification.identified_fraction,
            "obstructions": identification.obstructions,
            "cards": [
                {
                    "name": valued.identity.name,
                    "set_name": valued.identity.set_name,
                    "set_code": valued.identity.set_code,
                    "card_number": valued.identity.card_number,
                    "variant": valued.identity.variant,
                    "language": valued.identity.language,
                    "condition_estimate": valued.identity.condition_estimate,
                    "quantity": valued.identity.quantity,
                    "vision_confidence": valued.identity.confidence,
                    "match_score": valued.match_score,
                    "confidence": valued.confidence,
                    "notes": valued.identity.notes,
                    "matched_card_id": valued.card.card_id if valued.card else None,
                    "matched_set": valued.card.set_name if valued.card else None,
                    "matched_number": valued.card.number if valued.card else None,
                    "unit_value": valued.unit_value,
                    "condition_multiplier": valued.condition_multiplier,
                    "extended_value": valued.extended_value,
                    "price_source": valued.price_source,
                }
                for valued in valuation.cards
            ],
        }
    )


async def run_scan(
    clients: Clients,
    dry_run: bool = False,
    force_category_refresh: bool = False,
    now: datetime | None = None,
) -> ScanReport:
    config = clients.config
    now = now or datetime.now(timezone.utc)
    report = ScanReport(errors=[])
    run_id = clients.store.start_run()

    categories: CategorySet = await discover_categories(
        clients.taxonomy,
        config.ebay.marketplace_id,
        cache_dir=config.cache_dir,
        force_refresh=force_category_refresh,
    )
    log.info(
        "categories: singles=%s lots=%s",
        [f"{c.category_id}({c.name})" for c in categories.singles],
        [f"{c.category_id}({c.name})" for c in categories.lots],
    )

    filter_string = build_filter(
        ending_within_hours=config.filters.ending_within_hours,
        max_price=config.filters.max_current_price,
        now=now,
    )
    listings = await clients.browse.search(categories.all_ids, filter_string)
    report.candidates_seen = len(listings)

    # Watch counts and the full image set only arrive with getItem, so the
    # first pass deliberately ignores the watcher rule.
    prefilter_config = replace(config.filters, unknown_watchers="allow")
    prefiltered = apply_filters(listings, prefilter_config, now)
    report.passed_prefilter = len(prefiltered.kept)

    fresh = [l for l in prefiltered.kept if not clients.store.already_alerted(l.item_id)]
    report.skipped_already_alerted = len(prefiltered.kept) - len(fresh)

    # Hydrating is one API call each, so cap it generously above the vision
    # budget and let the real filter cut it down from there.
    hydration_budget = config.filters.max_vision_calls_per_scan * 3
    hydrated: list[Listing] = []
    for listing in fresh[:hydration_budget]:
        try:
            hydrated.append(await clients.browse.hydrate(listing))
        except Exception as exc:  # noqa: BLE001 - one bad item must not kill a scan
            report.errors.append(f"hydrate {listing.item_id}: {exc}")
            hydrated.append(listing)

    final = apply_filters(hydrated, config.filters, now)
    report.passed_filters = len(final.kept)
    report.rejections = dict(prefiltered.rejections + final.rejections)

    for listing in final.kept[: config.filters.max_vision_calls_per_scan]:
        try:
            identification = await clients.vision.identify(
                listing.image_urls,
                listing.title,
                max_images=config.filters.max_images_per_listing,
            )
            report.vision_calls += 1

            valuation = await value_lot(identification.cards, clients.tcg, config.tcg)

            flagged = valuation.low_confidence_cards(config.vision.confidence_threshold)
            payload = build_payload(
                listing=listing,
                identification=identification,
                valuation=valuation,
                confidence_threshold=config.vision.confidence_threshold,
                config=config.discord,
                category_kind=categories.kind_for(listing.category_id),
                now=now,
            )

            if dry_run:
                # Deliberately record nothing: a dry run that wrote alert rows
                # would seed the scoring set with alerts nobody ever saw, and
                # would mark these listings as already-alerted so the next real
                # scan skipped them.
                log.info(
                    "[dry-run] would alert %s (%s) — $%.2f estimated, %s",
                    listing.item_id,
                    listing.title,
                    valuation.total_value,
                    "FLAGGED" if flagged else "clean",
                )
                continue

            sent = await clients.discord.send(payload)
            if not sent:
                report.errors.append(f"discord send failed for {listing.item_id}")
                continue

            clients.store.record_alert(
                item_id=listing.item_id,
                title=listing.title,
                url=listing.url,
                category_id=listing.category_id,
                category_kind=categories.kind_for(listing.category_id),
                end_time=listing.end_time.isoformat() if listing.end_time else None,
                price_at_alert=listing.current_price,
                currency=listing.currency,
                bid_count_at_alert=listing.bid_count,
                watch_count=listing.watch_count,
                seller_username=listing.seller_username,
                seller_feedback_score=listing.seller_feedback_score,
                seller_feedback_pct=listing.seller_feedback_pct,
                estimated_value=valuation.total_value,
                matched_card_count=len(valuation.matched_cards),
                unmatched_card_count=len(valuation.unmatched_cards),
                min_confidence=valuation.min_confidence,
                value_weighted_confidence=valuation.value_weighted_confidence(),
                flagged_low_confidence=int(bool(flagged) or identification.error is not None),
                vision_model=identification.model,
                vision_error=identification.error,
                identified_json=_serialise_identities(identification, valuation),
                images_json=json.dumps(listing.image_urls),
            )
            report.alerts_sent += 1

        except Exception as exc:  # noqa: BLE001 - keep scanning the rest
            log.exception("failed processing %s", listing.item_id)
            report.errors.append(f"process {listing.item_id}: {exc}")

    clients.store.finish_run(
        run_id,
        candidates_seen=report.candidates_seen,
        passed_filters=report.passed_filters,
        vision_calls=report.vision_calls,
        alerts_sent=report.alerts_sent,
        errors=report.errors,
    )
    return report

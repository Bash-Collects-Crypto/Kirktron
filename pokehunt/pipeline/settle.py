"""Capture what each alerted auction actually sold for.

eBay's public APIs do not expose a sold-price feed on the Browse tier, but an
ended auction stays retrievable through getItem for a while after close. So we
poll each alerted item shortly after its end time and read the final bid off
the item record. Anything we miss can be filled in by hand from a CSV.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..context import Clients
from ..ebay.models import _money, parse_ebay_time

log = logging.getLogger(__name__)

# How long to keep retrying an ended item before giving up on it.
GIVE_UP_AFTER_DAYS = 7


@dataclass
class SettleReport:
    checked: int = 0
    settled: int = 0
    still_pending: int = 0
    gave_up: int = 0
    errors: list[str] | None = None

    def render(self) -> str:
        lines = [
            f"ended alerts checked: {self.checked}",
            f"settled:              {self.settled}",
            f"still pending:        {self.still_pending}",
            f"gave up (stale):      {self.gave_up}",
        ]
        if self.errors:
            lines.append(f"errors: {len(self.errors)}")
            lines.extend(f"  {e}" for e in self.errors[:10])
        return "\n".join(lines)


def read_outcome(
    detail: dict, now: datetime | None = None
) -> tuple[bool | None, float | None, int | None]:
    """Pull (sold, final_price, bid_count) out of an ended item record."""
    now = now or datetime.now(timezone.utc)
    bid_count = detail.get("bidCount")
    try:
        bid_count = int(bid_count) if bid_count is not None else None
    except (TypeError, ValueError):
        bid_count = None

    final_price = _money(detail.get("currentBidPrice")) or _money(detail.get("price"))

    end_time = parse_ebay_time(detail.get("itemEndDate"))
    if end_time is not None and end_time > now:
        # Auction was extended or we polled early; not settled yet.
        return None, None, bid_count

    if bid_count is None:
        return None, final_price, None

    # A reserve that never got met still shows bids, so this is "sold" in the
    # sense of "the market cleared at this price", which is what the scorer
    # actually needs. Reserve-not-met lots are rare in this segment.
    return bid_count > 0, final_price, bid_count


async def run_settle(clients: Clients, now: datetime | None = None) -> SettleReport:
    now = now or datetime.now(timezone.utc)
    report = SettleReport(errors=[])

    pending = clients.store.alerts_awaiting_settlement(now.isoformat())
    report.checked = len(pending)

    for row in pending:
        item_id = row["item_id"]
        end_time = parse_ebay_time(row["end_time"])
        stale = end_time is not None and now - end_time > timedelta(days=GIVE_UP_AFTER_DAYS)

        try:
            detail = await clients.browse.get_item(item_id)
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"{item_id}: {exc}")
            continue

        if detail is None:
            if stale:
                clients.store.record_outcome(
                    item_id,
                    sold=None,
                    final_price=None,
                    final_bid_count=None,
                    source="unavailable",
                    notes="eBay dropped the item before we could read the final bid",
                )
                report.gave_up += 1
            else:
                report.still_pending += 1
            continue

        sold, final_price, bid_count = read_outcome(detail, now)
        if sold is None and not stale:
            report.still_pending += 1
            continue

        clients.store.record_outcome(
            item_id,
            sold=sold,
            final_price=final_price,
            final_bid_count=bid_count,
            source="browse_poll",
        )
        report.settled += 1

    return report


def import_manual_outcomes(clients: Clients, csv_path: Path) -> int:
    """Backfill outcomes from a CSV: item_id,final_price[,sold][,notes]."""
    imported = 0
    with Path(csv_path).open() as handle:
        for row in csv.DictReader(handle):
            item_id = (row.get("item_id") or "").strip()
            if not item_id:
                continue
            raw_price = (row.get("final_price") or "").strip()
            final_price = float(raw_price) if raw_price else None
            raw_sold = (row.get("sold") or "").strip().lower()
            if raw_sold:
                sold = raw_sold in {"1", "true", "yes", "y"}
            else:
                sold = final_price is not None and final_price > 0
            clients.store.record_outcome(
                item_id,
                sold=sold,
                final_price=final_price,
                final_bid_count=None,
                source="manual",
                notes=(row.get("notes") or None),
            )
            imported += 1
    return imported

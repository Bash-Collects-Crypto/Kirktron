"""Browse API search, scoped to discovered categories and auction format."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from .auth import EbayAuth
from .models import Listing

# Browse caps a single page at 200 and the offset at 10,000.
MAX_PAGE_SIZE = 200


def _ebay_timestamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def build_filter(
    ending_within_hours: float,
    max_price: float | None,
    currency: str = "USD",
    now: datetime | None = None,
) -> str:
    """Server-side filter string.

    Only the things Browse can filter on go here: buying format, the end-date
    window, and a price ceiling. Watch count and seller feedback are not
    filterable server-side, so those are applied locally in pokehunt.pipeline.
    """
    now = now or datetime.now(timezone.utc)
    window_end = now + timedelta(hours=ending_within_hours)

    clauses = [
        "buyingOptions:{AUCTION}",
        f"itemEndDate:[{_ebay_timestamp(now)}..{_ebay_timestamp(window_end)}]",
    ]
    if max_price is not None:
        clauses.append(f"price:[..{max_price:.2f}]")
        clauses.append(f"priceCurrency:{currency}")
    return ",".join(clauses)


class BrowseClient:
    def __init__(
        self,
        auth: EbayAuth,
        client: httpx.AsyncClient,
        base_url: str,
        marketplace_id: str,
    ) -> None:
        self._auth = auth
        self._client = client
        self._base = f"{base_url}/buy/browse/v1"
        self._marketplace_id = marketplace_id

    async def search(
        self,
        category_ids: list[str],
        filter_string: str,
        limit: int = MAX_PAGE_SIZE,
        max_items: int = 400,
    ) -> list[Listing]:
        """Page through item_summary/search for the given categories.

        eBay ANDs category_ids with the filter, and a comma-separated
        category_ids list is treated as a union of those categories.
        """
        results: list[Listing] = []
        offset = 0
        page_size = min(limit, MAX_PAGE_SIZE)

        while len(results) < max_items:
            params = {
                "category_ids": ",".join(category_ids),
                "filter": filter_string,
                "limit": str(min(page_size, max_items - len(results))),
                "offset": str(offset),
                "sort": "endingSoonest",
            }
            response = await self._client.get(
                f"{self._base}/item_summary/search",
                params=params,
                headers=await self._auth.headers(self._marketplace_id),
            )
            response.raise_for_status()
            payload = response.json()

            summaries = payload.get("itemSummaries") or []
            if not summaries:
                break

            results.extend(Listing.from_summary(item) for item in summaries)

            total = payload.get("total", 0)
            offset += len(summaries)
            if offset >= total or len(summaries) < int(params["limit"]):
                break

        return results[:max_items]

    async def get_item(self, item_id: str) -> dict | None:
        """Full item record. Returns None once eBay drops an ended listing."""
        response = await self._client.get(
            f"{self._base}/item/{item_id}",
            headers=await self._auth.headers(self._marketplace_id),
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    async def hydrate(self, listing: Listing) -> Listing:
        detail = await self.get_item(listing.item_id)
        if detail:
            listing.merge_detail(detail)
        return listing

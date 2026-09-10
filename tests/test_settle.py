from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from pokehunt.config import (
    Config, DiscordConfig, EbayConfig, FilterConfig, TcgConfig, VisionConfig,
)
from pokehunt.context import Clients
from pokehunt.ebay.auth import EbayAuth
from pokehunt.ebay.browse import BrowseClient
from pokehunt.ebay.taxonomy import TaxonomyClient
from pokehunt.pipeline.settle import import_manual_outcomes, read_outcome, run_settle
from pokehunt.store.db import Store

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
ENDED = (NOW - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
FUTURE = (NOW + timedelta(hours=2)).isoformat().replace("+00:00", "Z")


def test_read_outcome_of_a_sold_auction():
    sold, price, bids = read_outcome(
        {"itemEndDate": ENDED, "bidCount": 7, "currentBidPrice": {"value": "88.50", "currency": "USD"}},
        NOW,
    )
    assert sold is True and price == 88.5 and bids == 7


def test_read_outcome_of_an_auction_that_got_no_bids():
    sold, price, bids = read_outcome(
        {"itemEndDate": ENDED, "bidCount": 0, "price": {"value": "9.99"}}, NOW
    )
    assert sold is False and price == 9.99 and bids == 0


def test_read_outcome_refuses_to_settle_a_live_auction():
    sold, price, bids = read_outcome({"itemEndDate": FUTURE, "bidCount": 3}, NOW)
    assert sold is None


def _clients(tmp_path, handler):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ebay = EbayConfig(client_id="i", client_secret="s")
    auth = EbayAuth(ebay, http)
    store = Store(tmp_path / "s.db")
    config = Config(
        ebay=ebay,
        vision=VisionConfig(api_key="k"),
        tcg=TcgConfig(),
        discord=DiscordConfig(webhook_url="https://discord/x"),
        filters=FilterConfig(),
        db_path=tmp_path / "s.db",
        cache_dir=tmp_path / "cache",
    )
    return Clients(
        config=config, http=http,
        browse=BrowseClient(auth, http, ebay.base_url, "EBAY_US"),
        taxonomy=TaxonomyClient(auth, http, ebay.base_url, "EBAY_US"),
        tcg=None, vision=None, discord=None, store=store,
    )


def _seed(store, item_id, end_time):
    store.record_alert(
        item_id=item_id, title="lot", url="u", category_id="1", category_kind="lots",
        end_time=end_time, price_at_alert=10.0, currency="USD", bid_count_at_alert=1,
        watch_count=1, seller_username="s", seller_feedback_score=5,
        seller_feedback_pct=100.0, estimated_value=100.0, matched_card_count=1,
        unmatched_card_count=0, min_confidence=0.9, value_weighted_confidence=0.9,
        flagged_low_confidence=0, vision_model="m", vision_error=None,
        identified_json="{}", images_json="[]",
    )


@pytest.mark.asyncio
async def test_settle_records_the_final_bid(tmp_path):
    def handler(request):
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 7200})
        return httpx.Response(200, json={
            "itemId": "v1|1|0", "itemEndDate": ENDED, "bidCount": 5,
            "currentBidPrice": {"value": "62.00", "currency": "USD"},
        })

    clients = _clients(tmp_path, handler)
    _seed(clients.store, "v1|1|0", (NOW - timedelta(hours=1)).isoformat())

    report = await run_settle(clients, now=NOW)
    assert report.checked == 1 and report.settled == 1

    row = clients.store.alerts_between("2000-01-01", "2100-01-01")[0]
    assert row["final_price"] == 62.0 and row["sold"] == 1
    clients.store.close()
    await clients.http.aclose()


@pytest.mark.asyncio
async def test_settle_leaves_a_recently_dropped_item_pending_then_gives_up(tmp_path):
    def handler(request):
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 7200})
        return httpx.Response(404)

    clients = _clients(tmp_path, handler)
    _seed(clients.store, "recent", (NOW - timedelta(hours=1)).isoformat())
    _seed(clients.store, "stale", (NOW - timedelta(days=30)).isoformat())

    report = await run_settle(clients, now=NOW)
    assert report.still_pending == 1
    assert report.gave_up == 1

    rows = {r["item_id"]: r for r in clients.store.alerts_between("2000-01-01", "2100-01-01")}
    assert rows["recent"]["outcome_source"] is None
    assert rows["stale"]["outcome_source"] == "unavailable"
    clients.store.close()
    await clients.http.aclose()


@pytest.mark.asyncio
async def test_settle_ignores_alerts_that_have_not_ended(tmp_path):
    def handler(request):
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 7200})
        raise AssertionError("should not have polled a live auction")

    clients = _clients(tmp_path, handler)
    _seed(clients.store, "live", (NOW + timedelta(hours=5)).isoformat())
    report = await run_settle(clients, now=NOW)
    assert report.checked == 0
    clients.store.close()
    await clients.http.aclose()


def test_manual_csv_backfill(tmp_path):
    clients = _clients(tmp_path, lambda r: httpx.Response(200, json={}))
    _seed(clients.store, "a", (NOW - timedelta(hours=1)).isoformat())
    _seed(clients.store, "b", (NOW - timedelta(hours=1)).isoformat())

    csv_path = Path(tmp_path) / "outcomes.csv"
    csv_path.write_text("item_id,final_price,sold,notes\na,120.50,yes,watched it close\nb,,no,no bids\n")

    assert import_manual_outcomes(clients, csv_path) == 2
    rows = {r["item_id"]: r for r in clients.store.alerts_between("2000-01-01", "2100-01-01")}
    assert rows["a"]["final_price"] == 120.5 and rows["a"]["sold"] == 1
    assert rows["b"]["sold"] == 0
    assert rows["a"]["outcome_source"] == "manual"
    clients.store.close()

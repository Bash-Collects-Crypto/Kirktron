"""End-to-end: eBay -> filters -> vision -> pokemontcg.io -> Discord -> SQLite.

Every external service is mocked, so this exercises the wiring rather than the
network: that discovered category ids actually reach the search call, that the
watcher/feedback filters cut the right listings, and that what lands in Discord
matches what lands in the database.
"""

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from pokehunt.config import (
    Config, DiscordConfig, EbayConfig, FilterConfig, TcgConfig, VisionConfig,
)
from pokehunt.context import Clients
from pokehunt.alerts.discord import DiscordNotifier
from pokehunt.ebay.auth import EbayAuth
from pokehunt.ebay.browse import BrowseClient
from pokehunt.ebay.taxonomy import TaxonomyClient
from pokehunt.pipeline.scan import run_scan
from pokehunt.store.db import Store
from pokehunt.tcg.pokemontcg import PokemonTcgClient
from pokehunt.vision.schema import CardIdentity, LotIdentification

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def ebay_time(hours):
    return (NOW + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def summary(item_id, *, watchers=None, feedback=10, hours=6, price=20.0, options=None):
    payload = {
        "itemId": item_id,
        "title": f"pokemon lot {item_id}",
        "itemWebUrl": f"https://ebay.com/itm/{item_id}",
        "categoryId": "99011",
        "buyingOptions": options or ["AUCTION"],
        "itemEndDate": ebay_time(hours),
        "currentBidPrice": {"value": str(price), "currency": "USD"},
        "bidCount": 1,
        "seller": {"username": f"seller_{item_id}", "feedbackScore": feedback,
                   "feedbackPercentage": "100.0"},
        "image": {"imageUrl": f"https://img/{item_id}-0.jpg"},
    }
    if watchers is not None:
        payload["watchCount"] = watchers
    return payload


class FakeVision:
    """Stands in for the vision model; records what it was asked to look at."""

    def __init__(self):
        self.calls = []

    async def identify(self, image_urls, title, max_images=8, retries=2):
        self.calls.append((image_urls, title))
        return LotIdentification(
            cards=[
                CardIdentity(name="Charizard", quantity=1, confidence=0.95,
                             image_index=0, set_name="Base Set", card_number="4/102",
                             condition_estimate="near_mint"),
                CardIdentity(name="Pikachu", quantity=2, confidence=0.30,
                             image_index=1, set_name="Base Set", card_number="58/102",
                             condition_estimate="near_mint", notes="blurry"),
            ],
            total_cards_visible=12,
            identified_fraction=0.2,
            model="fake-vision",
        )


@pytest.fixture
def rig(tmp_path):
    searches = []
    posted = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 7200})
        if path.endswith("/get_default_category_tree_id"):
            return httpx.Response(200, json={"categoryTreeId": "0"})
        if path.endswith("/get_category_suggestions"):
            return httpx.Response(200, json={"categorySuggestions": [{
                "category": {"categoryId": "99010", "categoryName": "Pokémon Individual Cards"},
                "categoryTreeNodeAncestors": [
                    {"categoryId": "99001", "categoryName": "Pokémon Trading Card Game"}],
            }]})
        if "/get_category_subtree" in path:
            return httpx.Response(200, json={"categorySubtreeNode": {
                "category": {"categoryId": "99001", "categoryName": "Pokémon Trading Card Game"},
                "childCategoryTreeNodes": [
                    {"category": {"categoryId": "99010", "categoryName": "Pokémon Individual Cards"}},
                    {"category": {"categoryId": "99011", "categoryName": "Pokémon Card Lots"}},
                ],
            }})
        if path.endswith("/item_summary/search"):
            searches.append(request.url)
            return httpx.Response(200, json={
                "total": 4,
                "itemSummaries": [
                    summary("keep"),
                    summary("watched", watchers=11),
                    summary("bigseller", feedback=9000),
                    summary("buynow", options=["FIXED_PRICE"]),
                ],
            })
        if "/buy/browse/v1/item/" in path:
            item_id = path.rsplit("/", 1)[-1]
            watchers = 11 if item_id == "watched" else 1
            return httpx.Response(200, json={
                "itemId": item_id, "watchCount": watchers,
                "itemEndDate": ebay_time(6),
                "additionalImages": [{"imageUrl": f"https://img/{item_id}-1.jpg"}],
            })
        if "api.pokemontcg.io" in str(request.url):
            query = request.url.params.get("q", "")
            if "Charizard" in query:
                return httpx.Response(200, json={"data": [{
                    "id": "base1-4", "name": "Charizard", "number": "4",
                    "rarity": "Rare Holo", "set": {"id": "base1", "name": "Base Set"},
                    "tcgplayer": {"prices": {"holofoil": {"market": 300.0}}},
                }]})
            return httpx.Response(200, json={"data": [{
                "id": "base1-58", "name": "Pikachu", "number": "58",
                "rarity": "Common", "set": {"id": "base1", "name": "Base Set"},
                "tcgplayer": {"prices": {"normal": {"market": 5.0}}},
            }]})
        if "discord" in str(request.url):
            posted.append(json.loads(request.content))
            return httpx.Response(204)
        return httpx.Response(404, text=str(request.url))

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ebay = EbayConfig(client_id="i", client_secret="s")
    auth = EbayAuth(ebay, http)
    store = Store(tmp_path / "e2e.db")
    vision = FakeVision()
    config = Config(
        ebay=ebay,
        vision=VisionConfig(api_key="k", confidence_threshold=0.7),
        tcg=TcgConfig(),
        discord=DiscordConfig(webhook_url="https://discord.com/api/webhooks/x"),
        filters=FilterConfig(),
        db_path=tmp_path / "e2e.db",
        cache_dir=tmp_path / "cache",
    )
    clients = Clients(
        config=config, http=http,
        browse=BrowseClient(auth, http, ebay.base_url, "EBAY_US"),
        taxonomy=TaxonomyClient(auth, http, ebay.base_url, "EBAY_US"),
        tcg=PokemonTcgClient(config.tcg, http, config.cache_dir),
        vision=vision,
        discord=DiscordNotifier(config.discord, http),
        store=store,
    )
    yield clients, searches, posted, vision
    store.close()


@pytest.mark.asyncio
async def test_scan_alerts_only_on_listings_that_clear_every_filter(rig):
    clients, searches, posted, vision = rig
    report = await run_scan(clients, now=NOW)

    assert report.candidates_seen == 4
    assert report.passed_filters == 1
    assert report.vision_calls == 1
    assert report.alerts_sent == 1
    assert report.rejections["not_auction"] == 1
    assert report.rejections["seller_feedback_too_high"] == 1
    assert report.rejections["too_many_watchers"] == 1


@pytest.mark.asyncio
async def test_search_uses_the_discovered_category_ids_and_auction_filter(rig):
    clients, searches, posted, vision = rig
    await run_scan(clients, now=NOW)

    assert len(searches) == 1
    params = searches[0].params
    # Both discovered ids, neither of them hardcoded anywhere in the package.
    assert set(params["category_ids"].split(",")) == {"99010", "99011"}
    assert "buyingOptions:{AUCTION}" in params["filter"]
    assert "itemEndDate:[2026-09-10T12:00:00.000Z..2026-09-11T12:00:00.000Z]" in params["filter"]
    assert params["sort"] == "endingSoonest"


@pytest.mark.asyncio
async def test_vision_sees_the_hydrated_image_set(rig):
    clients, searches, posted, vision = rig
    await run_scan(clients, now=NOW)
    image_urls, title = vision.calls[0]
    # The summary carried one photo; getItem added the second.
    assert image_urls == ["https://img/keep-0.jpg", "https://img/keep-1.jpg"]
    assert title == "pokemon lot keep"


@pytest.mark.asyncio
async def test_alert_carries_photos_value_and_the_red_flag(rig):
    clients, searches, posted, vision = rig
    await run_scan(clients, now=NOW)

    payload = posted[0]
    embed = payload["embeds"][0]
    # $300 Charizard + 2 x $5 Pikachu = $310
    fields = {f["name"]: f["value"] for f in embed["fields"]}
    assert "$310.00" in fields["Summed market value"]
    assert embed["title"].startswith("🚩")  # the 0.30-confidence Pikachu
    assert any(f["name"].startswith("🚩 BELOW") for f in embed["fields"])
    assert [e["image"]["url"] for e in payload["embeds"]] == [
        "https://img/keep-0.jpg", "https://img/keep-1.jpg"
    ]


@pytest.mark.asyncio
async def test_alert_is_recorded_for_scoring(rig):
    clients, searches, posted, vision = rig
    await run_scan(clients, now=NOW)

    rows = clients.store.alerts_between("2000-01-01", "2100-01-01")
    assert len(rows) == 1
    row = rows[0]
    assert row["item_id"] == "keep"
    assert row["estimated_value"] == pytest.approx(310.0)
    assert row["min_confidence"] == pytest.approx(0.30)
    assert row["value_weighted_confidence"] > 0.9
    assert row["flagged_low_confidence"] == 1
    assert row["category_kind"] == "lots"
    assert row["watch_count"] == 1

    identified = json.loads(row["identified_json"])
    assert {c["name"] for c in identified["cards"]} == {"Charizard", "Pikachu"}
    charizard = next(c for c in identified["cards"] if c["name"] == "Charizard")
    assert charizard["matched_card_id"] == "base1-4"
    assert charizard["extended_value"] == pytest.approx(300.0)


@pytest.mark.asyncio
async def test_rescan_does_not_realert_the_same_listing(rig):
    clients, searches, posted, vision = rig
    await run_scan(clients, now=NOW)
    second = await run_scan(clients, now=NOW)

    assert second.skipped_already_alerted == 1
    assert second.alerts_sent == 0
    assert len(posted) == 1


@pytest.mark.asyncio
async def test_dry_run_records_nothing_and_posts_nothing(rig):
    clients, searches, posted, vision = rig
    report = await run_scan(clients, dry_run=True, now=NOW)

    assert report.vision_calls == 1
    assert report.alerts_sent == 0
    assert posted == []
    assert clients.store.alerts_between("2000-01-01", "2100-01-01") == []

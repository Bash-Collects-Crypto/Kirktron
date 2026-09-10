import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from pokehunt.alerts.discord import (
    COLOR_ERROR,
    COLOR_FLAGGED,
    COLOR_OK,
    DiscordNotifier,
    build_payload,
)
from pokehunt.config import DiscordConfig, TcgConfig
from pokehunt.ebay.models import Listing
from pokehunt.tcg.matcher import LotValuation, ValuedCard
from pokehunt.tcg.pokemontcg import TcgCard
from pokehunt.vision.schema import CardIdentity, LotIdentification

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def listing():
    return Listing(
        item_id="v1|1|0",
        title="Vintage Pokemon binder lot untested",
        url="https://ebay.com/itm/1",
        category_id="99011",
        buying_options=["AUCTION"],
        end_time=NOW + timedelta(hours=3),
        current_price=41.0,
        currency="USD",
        bid_count=2,
        watch_count=1,
        seller_username="attic_finds",
        seller_feedback_score=8,
        seller_feedback_pct=100.0,
        image_urls=[f"https://img/{i}.jpg" for i in range(6)],
    )


def valued(name, confidence, value, match_score=1.0, notes=None):
    identity = CardIdentity(
        name=name, quantity=1, confidence=confidence, image_index=0, notes=notes,
        condition_estimate="near_mint",
    )
    card = TcgCard.from_payload({
        "id": "base1-4", "name": name, "number": "4",
        "set": {"id": "base1", "name": "Base Set"},
    })
    return ValuedCard(
        identity=identity, card=card, unit_value=value,
        price_source="tcgplayer.holofoil.market", match_score=match_score,
        condition_multiplier=1.0,
    )


def test_clean_lot_is_green_and_carries_the_numbers():
    valuation = LotValuation(cards=[valued("Charizard", 0.95, 300.0), valued("Blastoise", 0.9, 80.0)])
    payload = build_payload(
        listing(), LotIdentification(model="claude-sonnet-5"), valuation, 0.7,
        DiscordConfig(webhook_url="https://discord/x"), category_kind="lots", now=NOW,
    )
    embed = payload["embeds"][0]
    assert embed["color"] == COLOR_OK
    assert "🚩" not in embed["title"]

    fields = {f["name"]: f["value"] for f in embed["fields"]}
    assert "$380.00" in fields["Summed market value"]
    assert "9.3x current bid" in fields["Summed market value"]
    assert "$41.00 (2 bids)" in fields["Current bid"]
    assert fields["Ends in"] == "3.0h"
    assert fields["Watchers"] == "1"
    assert "attic_finds" in fields["Seller"]
    assert "Charizard" in fields["Identified cards (2)"]


def test_low_confidence_card_raises_a_red_flag():
    valuation = LotValuation(cards=[
        valued("Charizard", 0.35, 300.0, notes="blurry, could be a Celebrations reprint"),
        valued("Rattata", 0.99, 1.0),
    ])
    payload = build_payload(
        listing(), LotIdentification(model="m"), valuation, 0.7,
        DiscordConfig(webhook_url="https://discord/x"), now=NOW,
    )
    embed = payload["embeds"][0]
    assert embed["color"] == COLOR_FLAGGED
    assert embed["title"].startswith("🚩")
    assert payload["content"].startswith("🚩 LOW CONFIDENCE")

    flag_field = next(f for f in embed["fields"] if f["name"].startswith("🚩 BELOW"))
    assert "Charizard" in flag_field["value"]
    assert "Celebrations reprint" in flag_field["value"]
    # The flag has to say how much money is riding on the shaky read.
    assert "$300.00" in flag_field["value"] and "100%" in flag_field["value"]


def test_match_score_drags_confidence_below_the_threshold():
    """A confident read of a card we could only fuzzily match is still shaky."""
    valuation = LotValuation(cards=[valued("Charizard", 0.95, 300.0, match_score=0.5)])
    payload = build_payload(
        listing(), LotIdentification(model="m"), valuation, 0.7,
        DiscordConfig(webhook_url="https://discord/x"), now=NOW,
    )
    assert payload["embeds"][0]["color"] == COLOR_FLAGGED


def test_vision_failure_is_flagged_not_swallowed():
    payload = build_payload(
        listing(), LotIdentification(model="m", error="overloaded_error"),
        LotValuation(cards=[]), 0.7,
        DiscordConfig(webhook_url="https://discord/x"), now=NOW,
    )
    embed = payload["embeds"][0]
    assert embed["color"] == COLOR_ERROR
    assert any(f["name"] == "🚩 Vision error" for f in embed["fields"])


def test_photos_become_a_gallery_sharing_one_url():
    valuation = LotValuation(cards=[valued("Charizard", 0.95, 300.0)])
    payload = build_payload(
        listing(), LotIdentification(model="m"), valuation, 0.7,
        DiscordConfig(webhook_url="https://discord/x"), now=NOW,
    )
    embeds = payload["embeds"]
    assert len(embeds) == 4
    assert all(e["url"] == "https://ebay.com/itm/1" for e in embeds)
    assert [e["image"]["url"] for e in embeds] == [f"https://img/{i}.jpg" for i in range(4)]


def test_long_card_lists_stay_inside_discord_field_limits():
    valuation = LotValuation(cards=[
        valued(f"Some Very Long Pokemon Card Name Number {i}", 0.9, 10.0) for i in range(60)
    ])
    payload = build_payload(
        listing(), LotIdentification(model="m"), valuation, 0.7,
        DiscordConfig(webhook_url="https://discord/x"), now=NOW,
    )
    for field in payload["embeds"][0]["fields"]:
        assert len(field["value"]) <= 1024, field["name"]
    assert len(payload["content"]) <= 2000
    assert len(json.dumps(payload)) < 6000


@pytest.mark.asyncio
async def test_notifier_retries_on_rate_limit():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, json={"retry_after": 0.01})
        return httpx.Response(204)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        notifier = DiscordNotifier(DiscordConfig(webhook_url="https://discord/x"), client)
        assert await notifier.send({"content": "hi"}) is True
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_notifier_gives_up_on_a_bad_webhook():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(404, text="unknown webhook"))
    ) as client:
        notifier = DiscordNotifier(DiscordConfig(webhook_url="https://discord/x"), client)
        assert await notifier.send({"content": "hi"}) is False

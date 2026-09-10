import pytest

from pokehunt.config import TcgConfig
from pokehunt.tcg.matcher import (
    build_queries,
    normalise_number,
    value_identity,
    value_lot,
)
from pokehunt.tcg.pokemontcg import TcgCard, market_value
from pokehunt.vision.schema import CardIdentity


def card_payload(card_id, name, set_name, number, market, rarity="Rare Holo", set_id="base1"):
    return {
        "id": card_id,
        "name": name,
        "number": number,
        "rarity": rarity,
        "set": {"id": set_id, "name": set_name},
        "images": {"small": "https://img/x.png"},
        "tcgplayer": {"prices": {"holofoil": {"market": market, "mid": market * 1.1}}},
    }


class FakeTcgClient:
    """Returns canned results keyed by whichever query fragment matches."""

    def __init__(self, responses):
        self.responses = responses
        self.queries = []

    async def search(self, query, page_size=24):
        self.queries.append(query)
        for fragment, cards in self.responses.items():
            if fragment in query:
                return [TcgCard.from_payload(c) for c in cards]
        return []


def test_normalise_number():
    assert normalise_number("4/102") == "4"
    assert normalise_number("004") == "4"
    assert normalise_number("SWSH123") == "swsh123"
    assert normalise_number(None) is None
    assert normalise_number("  ") is None


def test_build_queries_goes_specific_to_general():
    identity = CardIdentity(
        name="Charizard", quantity=1, confidence=0.9, image_index=0,
        set_name="Base Set", card_number="4/102",
    )
    queries = build_queries(identity)
    assert "set.name" in queries[0] and "number" in queries[0]
    assert queries[-1] == 'name:"Charizard"'


@pytest.mark.asyncio
async def test_value_identity_matches_on_number_and_set():
    identity = CardIdentity(
        name="Charizard", quantity=1, confidence=0.9, image_index=0,
        set_name="Base Set", card_number="4/102", variant="holofoil",
        condition_estimate="near_mint",
    )
    client = FakeTcgClient({
        'set.name:"Base Set"': [card_payload("base1-4", "Charizard", "Base Set", "4", 300.0)]
    })
    valued = await value_identity(identity, client, TcgConfig())
    assert valued.matched
    assert valued.unit_value == 300.0
    assert valued.extended_value == pytest.approx(300.0)
    assert valued.match_score == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_condition_discounts_the_estimate():
    identity = CardIdentity(
        name="Charizard", quantity=2, confidence=0.9, image_index=0,
        card_number="4", condition_estimate="heavily_played",
    )
    client = FakeTcgClient({
        'name:"Charizard"': [card_payload("base1-4", "Charizard", "Base Set", "4", 100.0)]
    })
    valued = await value_identity(identity, client, TcgConfig())
    # 2 copies x $100 x 0.5 heavily-played multiplier
    assert valued.extended_value == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_unknown_condition_takes_a_haircut():
    identity = CardIdentity(name="Pikachu", quantity=1, confidence=0.8, image_index=0)
    client = FakeTcgClient({
        'name:"Pikachu"': [card_payload("base1-58", "Pikachu", "Base Set", "58", 10.0)]
    })
    valued = await value_identity(identity, client, TcgConfig())
    assert valued.extended_value == pytest.approx(8.5)


@pytest.mark.asyncio
async def test_ambiguous_reprints_take_the_median_price_not_the_best_one():
    """A name-only match across four printings must not be valued at the top one."""
    identity = CardIdentity(name="Charizard", quantity=1, confidence=0.6, image_index=0,
                            condition_estimate="near_mint")
    client = FakeTcgClient({
        'name:"Charizard"': [
            card_payload("base1-4", "Charizard", "Base Set", "4", 400.0),
            card_payload("cel25-4", "Charizard", "Celebrations", "4", 25.0),
            card_payload("base2-4", "Charizard", "Base Set 2", "4", 90.0),
            card_payload("lc-3", "Charizard", "Legendary Collection", "3", 150.0),
        ]
    })
    valued = await value_identity(identity, client, TcgConfig())
    assert valued.unit_value == 150.0
    assert "median" in valued.price_source


@pytest.mark.asyncio
async def test_unmatched_identity_contributes_no_value():
    identity = CardIdentity(name="Nonexistent Card", quantity=3, confidence=0.4, image_index=0)
    client = FakeTcgClient({})
    valued = await value_identity(identity, client, TcgConfig())
    assert not valued.matched
    assert valued.extended_value == 0.0
    assert valued.confidence == 0.0


@pytest.mark.asyncio
async def test_lot_totals_and_confidence_weighting():
    identities = [
        CardIdentity(name="Charizard", quantity=1, confidence=0.95, image_index=0,
                     card_number="4", set_name="Base Set", condition_estimate="near_mint"),
        CardIdentity(name="Pikachu", quantity=4, confidence=0.30, image_index=1,
                     card_number="58", set_name="Base Set", condition_estimate="near_mint"),
    ]
    client = FakeTcgClient({
        '"Charizard"': [card_payload("base1-4", "Charizard", "Base Set", "4", 300.0)],
        '"Pikachu"': [card_payload("base1-58", "Pikachu", "Base Set", "58", 5.0)],
    })
    valuation = await value_lot(identities, client, TcgConfig())
    assert valuation.total_value == pytest.approx(320.0)
    assert valuation.min_confidence == pytest.approx(0.30)
    # The $300 Charizard dominates, so the value-weighted confidence stays high
    # even though a low-confidence card is in the lot.
    assert valuation.value_weighted_confidence() > 0.9
    assert len(valuation.low_confidence_cards(0.7)) == 1


def test_market_value_prefers_variant_series_then_falls_back():
    card = TcgCard.from_payload({
        "id": "x", "name": "X", "number": "1", "rarity": "Rare",
        "set": {"id": "s", "name": "S"},
        "tcgplayer": {"prices": {
            "normal": {"market": 5.0},
            "reverseHolofoil": {"market": 12.0},
        }},
    })
    value, source = market_value(card, TcgConfig(), "reverse_holofoil")
    assert value == 12.0 and "reverseHolofoil" in source

    # Unknown variant falls back cheapest-first rather than assuming the
    # priciest printing.
    value, source = market_value(card, TcgConfig(), None)
    assert value == 5.0 and "normal" in source


def test_market_value_falls_back_to_cardmarket_then_gives_up():
    card = TcgCard.from_payload({
        "id": "x", "name": "X", "number": "1",
        "set": {"id": "s", "name": "S"},
        "cardmarket": {"prices": {"averageSellPrice": 3.25}},
    })
    value, source = market_value(card, TcgConfig(), None)
    assert value == 3.25 and source == "cardmarket.averageSellPrice"

    empty = TcgCard.from_payload({"id": "y", "name": "Y", "number": "2", "set": {}})
    value, source = market_value(empty, TcgConfig(), None)
    assert value is None and source == "no price data"

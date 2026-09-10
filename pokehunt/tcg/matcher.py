"""Turn vision identities into priced pokemontcg.io matches."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..config import TcgConfig
from ..vision.schema import CardIdentity
from .pokemontcg import PokemonTcgClient, TcgCard, _escape, market_value

# Market prices quote near-mint. Anything rougher is worth less, and an unknown
# condition gets a haircut because listing photos flatter cards.
CONDITION_MULTIPLIERS = {
    "mint": 1.0,
    "near_mint": 1.0,
    "lightly_played": 0.85,
    "moderately_played": 0.70,
    "heavily_played": 0.50,
    "damaged": 0.30,
    None: 0.85,
}


def normalise_number(raw: str | None) -> str | None:
    """'4/102' -> '4'; '004' -> '4'; 'SWSH123' -> 'swsh123'."""
    if not raw:
        return None
    text = raw.strip().lower()
    text = text.split("/")[0]
    text = re.sub(r"[^a-z0-9]", "", text)
    if not text:
        return None
    if text.isdigit():
        return str(int(text))
    return text


@dataclass
class ValuedCard:
    identity: CardIdentity
    card: TcgCard | None
    unit_value: float | None
    price_source: str
    match_score: float
    condition_multiplier: float

    @property
    def matched(self) -> bool:
        return self.card is not None and self.unit_value is not None

    @property
    def extended_value(self) -> float:
        if self.unit_value is None:
            return 0.0
        return self.unit_value * self.identity.quantity * self.condition_multiplier

    @property
    def confidence(self) -> float:
        """Vision confidence tempered by how well the catalogue match landed."""
        return self.identity.confidence * self.match_score


@dataclass
class LotValuation:
    cards: list[ValuedCard] = field(default_factory=list)

    @property
    def total_value(self) -> float:
        return sum(card.extended_value for card in self.cards)

    @property
    def matched_cards(self) -> list[ValuedCard]:
        return [c for c in self.cards if c.matched]

    @property
    def unmatched_cards(self) -> list[ValuedCard]:
        return [c for c in self.cards if not c.matched]

    @property
    def min_confidence(self) -> float:
        if not self.cards:
            return 0.0
        return min(card.confidence for card in self.cards)

    def value_weighted_confidence(self) -> float:
        """Confidence weighted by the money each card contributes.

        A blurry bulk common dragging the minimum down matters far less than a
        blurry card carrying 80% of the estimate, and this is the number the
        scoring report cares about.
        """
        total = self.total_value
        if total <= 0:
            return self.min_confidence
        return sum(c.confidence * c.extended_value for c in self.cards) / total

    def low_confidence_cards(self, threshold: float) -> list[ValuedCard]:
        return [c for c in self.cards if c.confidence < threshold]


def _score_candidate(identity: CardIdentity, card: TcgCard) -> float:
    """0..1 -- how well a catalogue card answers the identity."""
    score = 0.0
    weight = 0.0

    weight += 3.0
    if identity.name and identity.name.strip().lower() == card.name.strip().lower():
        score += 3.0
    elif identity.name and identity.name.strip().lower() in card.name.strip().lower():
        score += 2.0

    wanted_number = normalise_number(identity.card_number)
    if wanted_number:
        weight += 3.0
        if wanted_number == normalise_number(card.number):
            score += 3.0

    if identity.set_name:
        weight += 2.0
        wanted_set = identity.set_name.strip().lower()
        actual_set = card.set_name.strip().lower()
        if wanted_set == actual_set:
            score += 2.0
        elif wanted_set in actual_set or actual_set in wanted_set:
            score += 1.0

    if identity.variant and card.rarity:
        weight += 1.0
        rarity = card.rarity.lower()
        variant = identity.variant.lower()
        if ("holo" in variant and "holo" in rarity) or ("promo" in variant and "promo" in rarity):
            score += 1.0
        elif variant == "normal" and "holo" not in rarity:
            score += 1.0

    if weight == 0:
        return 0.0
    return score / weight


def build_queries(identity: CardIdentity) -> list[str]:
    """Most specific first; we stop at the first query that returns anything."""
    name = identity.name.strip()
    if not name:
        return []

    queries: list[str] = []
    number = normalise_number(identity.card_number)

    if identity.set_name and number:
        queries.append(f"name:{_escape(name)} set.name:{_escape(identity.set_name)} number:{_escape(number)}")
    if number:
        queries.append(f"name:{_escape(name)} number:{_escape(number)}")
    if identity.set_name:
        queries.append(f"name:{_escape(name)} set.name:{_escape(identity.set_name)}")
    queries.append(f"name:{_escape(name)}")
    return queries


async def value_identity(
    identity: CardIdentity,
    client: PokemonTcgClient,
    config: TcgConfig,
) -> ValuedCard:
    multiplier = CONDITION_MULTIPLIERS.get(identity.condition_estimate, 0.85)

    candidates: list[TcgCard] = []
    for query in build_queries(identity):
        candidates = await client.search(query)
        if candidates:
            break

    if not candidates:
        return ValuedCard(
            identity=identity,
            card=None,
            unit_value=None,
            price_source="no catalogue match",
            match_score=0.0,
            condition_multiplier=multiplier,
        )

    scored = sorted(
        ((_score_candidate(identity, card), card) for card in candidates),
        key=lambda pair: pair[0],
        reverse=True,
    )
    best_score, best_card = scored[0]

    # When the name matched but nothing else pins the printing down, several
    # candidates tie. Take the median-priced tie rather than the top one, so an
    # ambiguous reprint does not get valued at its most expensive printing.
    tied = [card for score, card in scored if abs(score - best_score) < 1e-9]
    if len(tied) > 1:
        priced = [
            (market_value(card, config, identity.variant), card) for card in tied
        ]
        priced = [(value, source, card) for (value, source), card in priced if value is not None]
        if priced:
            priced.sort(key=lambda triple: triple[0])
            value, source, best_card = priced[len(priced) // 2]
            return ValuedCard(
                identity=identity,
                card=best_card,
                unit_value=value,
                price_source=f"{source} (median of {len(priced)} ambiguous printings)",
                match_score=best_score,
                condition_multiplier=multiplier,
            )

    value, source = market_value(best_card, config, identity.variant)
    return ValuedCard(
        identity=identity,
        card=best_card,
        unit_value=value,
        price_source=source,
        match_score=best_score,
        condition_multiplier=multiplier,
    )


async def value_lot(
    identities: list[CardIdentity],
    client: PokemonTcgClient,
    config: TcgConfig,
) -> LotValuation:
    return LotValuation(
        cards=[await value_identity(identity, client, config) for identity in identities]
    )

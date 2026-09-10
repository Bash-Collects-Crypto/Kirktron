"""pokemontcg.io lookups with an on-disk cache."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

from ..config import TcgConfig

log = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 24 * 3600


def _escape(value: str) -> str:
    """Quote a Lucene-ish query term for the pokemontcg.io q parameter."""
    cleaned = value.replace('"', "").replace("\\", "").strip()
    return f'"{cleaned}"'


@dataclass
class TcgCard:
    card_id: str
    name: str
    set_id: str
    set_name: str
    number: str
    rarity: str | None
    image_small: str | None
    tcgplayer_prices: dict
    cardmarket_prices: dict
    raw: dict

    @classmethod
    def from_payload(cls, payload: dict) -> "TcgCard":
        card_set = payload.get("set") or {}
        return cls(
            card_id=payload.get("id", ""),
            name=payload.get("name", ""),
            set_id=card_set.get("id", ""),
            set_name=card_set.get("name", ""),
            number=str(payload.get("number", "")),
            rarity=payload.get("rarity"),
            image_small=(payload.get("images") or {}).get("small"),
            tcgplayer_prices=((payload.get("tcgplayer") or {}).get("prices") or {}),
            cardmarket_prices=((payload.get("cardmarket") or {}).get("prices") or {}),
            raw=payload,
        )


class PokemonTcgClient:
    def __init__(
        self,
        config: TcgConfig,
        client: httpx.AsyncClient,
        cache_dir: Path | None = None,
    ) -> None:
        self._config = config
        self._client = client
        self._cache_dir = Path(cache_dir) / "tcg" if cache_dir else None
        if self._cache_dir:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory: dict[str, list[TcgCard]] = {}

    def _cache_file(self, query: str) -> Path | None:
        if not self._cache_dir:
            return None
        digest = hashlib.sha256(query.encode()).hexdigest()[:20]
        return self._cache_dir / f"{digest}.json"

    async def search(self, query: str, page_size: int = 24) -> list[TcgCard]:
        if query in self._memory:
            return self._memory[query]

        cache_file = self._cache_file(query)
        if cache_file and cache_file.exists():
            try:
                cached = json.loads(cache_file.read_text())
                cards = [TcgCard.from_payload(c) for c in cached["data"]]
                self._memory[query] = cards
                return cards
            except (json.JSONDecodeError, KeyError):
                cache_file.unlink(missing_ok=True)

        headers = {}
        if self._config.api_key:
            headers["X-Api-Key"] = self._config.api_key

        try:
            response = await self._client.get(
                f"{self._config.base_url}/cards",
                params={"q": query, "pageSize": str(page_size)},
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            log.warning("pokemontcg.io query %r failed: %s", query, exc)
            return []

        data = payload.get("data") or []
        if cache_file:
            cache_file.write_text(json.dumps({"data": data}))

        cards = [TcgCard.from_payload(c) for c in data]
        self._memory[query] = cards
        return cards


def market_value(card: TcgCard, config: TcgConfig, variant: str | None = None) -> tuple[float | None, str]:
    """Best available market price for a card, plus which series it came from.

    Prefers the TCGplayer series matching the identified variant, then the
    configured order, then Cardmarket. Returns (None, reason) when the card has
    no usable price at all -- common for bulk commons.
    """
    variant_series = {
        "holofoil": "holofoil",
        "reverse_holofoil": "reverseHolofoil",
        "first_edition": "1stEditionHolofoil",
        "normal": "normal",
    }

    order: list[str] = []
    if variant and variant in variant_series:
        order.append(variant_series[variant])
    order.extend(s for s in config.price_preference if s not in order)

    for series_name in order:
        series = card.tcgplayer_prices.get(series_name)
        if not isinstance(series, dict):
            continue
        for field_name in config.price_field_preference:
            value = series.get(field_name)
            if isinstance(value, (int, float)) and value > 0:
                return float(value), f"tcgplayer.{series_name}.{field_name}"

    for field_name in ("averageSellPrice", "trendPrice", "avg30", "avg7"):
        value = card.cardmarket_prices.get(field_name)
        if isinstance(value, (int, float)) and value > 0:
            return float(value), f"cardmarket.{field_name}"

    return None, "no price data"

"""Discord webhook alerts: photos, identified cards, summed value, red flags."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx

from ..config import DiscordConfig
from ..ebay.models import Listing
from ..tcg.matcher import LotValuation
from ..vision.schema import LotIdentification

log = logging.getLogger(__name__)

COLOR_OK = 0x2ECC71
COLOR_FLAGGED = 0xE01E1E
COLOR_ERROR = 0x95A5A6

# Discord renders up to four embeds that share one `url` as a single image
# gallery, which is how we get several listing photos into one alert.
MAX_GALLERY_IMAGES = 4


def _format_countdown(listing: Listing, now: datetime | None = None) -> str:
    hours = listing.hours_to_end(now)
    if hours is None:
        return "unknown"
    if hours < 0:
        return "ended"
    if hours < 1:
        return f"{int(hours * 60)}m"
    return f"{hours:.1f}h"


def _format_card_line(valued) -> str:
    identity = valued.identity
    qty = f"{identity.quantity}x " if identity.quantity > 1 else ""
    where = ""
    if valued.card is not None:
        where = f" — {valued.card.set_name} #{valued.card.number}"
    elif identity.set_name:
        where = f" — {identity.set_name} (unmatched)"

    if valued.unit_value is None:
        money = "no price"
    else:
        money = f"${valued.extended_value:,.2f}"

    confidence = f"{valued.confidence:.0%}"
    return f"{qty}**{identity.name}**{where} · {money} · conf {confidence}"


def build_payload(
    listing: Listing,
    identification: LotIdentification,
    valuation: LotValuation,
    confidence_threshold: float,
    config: DiscordConfig,
    category_kind: str = "unknown",
    now: datetime | None = None,
) -> dict:
    flagged = valuation.low_confidence_cards(confidence_threshold)
    has_flag = bool(flagged) or identification.error is not None

    if identification.error:
        color = COLOR_ERROR
    elif has_flag:
        color = COLOR_FLAGGED
    else:
        color = COLOR_OK

    price = listing.current_price
    price_text = f"${price:,.2f}" if price is not None else "n/a"
    estimate = valuation.total_value

    ratio_text = "n/a"
    if price and price > 0:
        ratio_text = f"{estimate / price:.1f}x current bid"

    fields = [
        {
            "name": "Summed market value",
            "value": f"**${estimate:,.2f}**\n{ratio_text}",
            "inline": True,
        },
        {
            "name": "Current bid",
            "value": f"{price_text} ({listing.bid_count or 0} bids)",
            "inline": True,
        },
        {"name": "Ends in", "value": _format_countdown(listing, now), "inline": True},
        {
            "name": "Watchers",
            "value": "unknown" if listing.watch_count is None else str(listing.watch_count),
            "inline": True,
        },
        {
            "name": "Seller",
            "value": (
                f"{listing.seller_username or 'unknown'}\n"
                f"{listing.seller_feedback_score if listing.seller_feedback_score is not None else '?'} fb"
                f" / {listing.seller_feedback_pct if listing.seller_feedback_pct is not None else '?'}%"
            ),
            "inline": True,
        },
        {"name": "Category", "value": category_kind, "inline": True},
    ]

    ranked = sorted(valuation.cards, key=lambda c: c.extended_value, reverse=True)
    if ranked:
        shown = ranked[:12]
        lines = [_format_card_line(card) for card in shown]
        if len(ranked) > len(shown):
            lines.append(f"_…and {len(ranked) - len(shown)} more_")
        body = "\n".join(lines)
        # Discord caps a field value at 1024 characters.
        if len(body) > 1024:
            body = body[:1000].rsplit("\n", 1)[0] + "\n_…truncated_"
        fields.append({"name": f"Identified cards ({len(ranked)})", "value": body, "inline": False})

    if flagged:
        flag_lines = [
            f"🚩 **{c.identity.name}** — conf {c.confidence:.0%}"
            + (f" — {c.identity.notes}" if c.identity.notes else "")
            for c in sorted(flagged, key=lambda c: c.extended_value, reverse=True)[:8]
        ]
        flagged_value = sum(c.extended_value for c in flagged)
        flag_lines.append(
            f"_${flagged_value:,.2f} of the estimate "
            f"({(flagged_value / estimate * 100) if estimate else 0:.0f}%) rests on these._"
        )
        value = "\n".join(flag_lines)
        if len(value) > 1024:
            value = value[:1000].rsplit("\n", 1)[0] + "\n_…truncated_"
        fields.append(
            {
                "name": f"🚩 BELOW CONFIDENCE THRESHOLD ({confidence_threshold:.0%})",
                "value": value,
                "inline": False,
            }
        )

    if valuation.unmatched_cards:
        names = ", ".join(c.identity.name for c in valuation.unmatched_cards[:10])
        fields.append(
            {
                "name": f"No catalogue match ({len(valuation.unmatched_cards)})",
                "value": (names or "—")[:1024],
                "inline": False,
            }
        )

    if identification.error:
        fields.append(
            {"name": "🚩 Vision error", "value": identification.error[:1024], "inline": False}
        )

    if identification.total_cards_visible:
        fields.append(
            {
                "name": "Coverage",
                "value": (
                    f"{identification.identified_fraction:.0%} of ~"
                    f"{identification.total_cards_visible} visible cards identified"
                    + (f"\n{identification.obstructions}" if identification.obstructions else "")
                )[:1024],
                "inline": False,
            }
        )

    title = listing.title[:250]
    prefix = "🚩 " if has_flag else ""

    main_embed = {
        "title": f"{prefix}{title}",
        "url": listing.url,
        "color": color,
        "fields": fields,
        "footer": {
            "text": (
                f"alert-only · {identification.model or 'no model'} · "
                f"value-weighted conf {valuation.value_weighted_confidence():.0%}"
            )
        },
        "timestamp": (now or datetime.now(timezone.utc)).isoformat(),
    }

    images = listing.image_urls[:MAX_GALLERY_IMAGES]
    if images:
        main_embed["image"] = {"url": images[0]}

    embeds = [main_embed]
    for extra in images[1:]:
        # Same `url` as the main embed -> Discord groups them as a gallery.
        embeds.append({"url": listing.url, "image": {"url": extra}})

    content = (
        f"{'🚩 LOW CONFIDENCE — ' if has_flag else ''}"
        f"${estimate:,.2f} estimated vs {price_text} current · ends in "
        f"{_format_countdown(listing, now)}"
    )

    return {
        "username": config.username,
        "content": content[:2000],
        "embeds": embeds[: config.max_embeds],
    }


class DiscordNotifier:
    def __init__(self, config: DiscordConfig, client: httpx.AsyncClient) -> None:
        self._config = config
        self._client = client

    async def send(self, payload: dict, retries: int = 3) -> bool:
        for attempt in range(retries + 1):
            response = await self._client.post(self._config.webhook_url, json=payload)
            if response.status_code in (200, 204):
                return True
            if response.status_code == 429:
                retry_after = 1.0
                try:
                    retry_after = float(response.json().get("retry_after", 1.0))
                except Exception:  # noqa: BLE001 - malformed 429 body
                    pass
                await asyncio.sleep(min(retry_after, 30.0))
                continue
            log.warning(
                "discord webhook rejected alert: %s %s",
                response.status_code,
                response.text[:400],
            )
            if 400 <= response.status_code < 500:
                return False
            await asyncio.sleep(2**attempt)
        return False

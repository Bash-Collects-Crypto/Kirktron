"""Add qualifying listings to the signed-in user's eBay watchlist.

This is the only part of pokehunt that writes anything to eBay. It still spends
no money: watching a listing places no bid and creates no obligation.

Implementation note, and a caveat worth reading before the first run: this
targets the Trading API's `AddToWatchList` call, authenticated with an OAuth
user access token passed as an IAF token. That is the watchlist endpoint I am
confident exists; if eBay has since published a REST equivalent, this is the
piece to swap. It has NOT been exercised against live eBay from this build --
there were no credentials available to do so -- so treat the first run as the
real integration test. Failures are deliberately loud and carry eBay's own
error text rather than being swallowed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from xml.etree import ElementTree

import httpx

from .user_auth import EbayUserAuth

log = logging.getLogger(__name__)

EBL_NS = "urn:ebay:apis:eBLBaseComponents"
# Trading API schema version. Bump only alongside a tested payload change.
COMPATIBILITY_LEVEL = "1207"

SITE_IDS = {
    "EBAY_US": "0",
    "EBAY_GB": "3",
    "EBAY_DE": "77",
    "EBAY_AU": "15",
    "EBAY_CA": "2",
}


def legacy_item_id(item_id: str, detail: dict | None = None) -> str:
    """Browse ids look like 'v1|110550947617|0'; Trading wants '110550947617'.

    Getting this wrong fails every call, so prefer the `legacyItemId` eBay
    hands back on a getItem response and only fall back to parsing.
    """
    if detail:
        legacy = detail.get("legacyItemId")
        if legacy:
            return str(legacy)

    if "|" in item_id:
        parts = item_id.split("|")
        if len(parts) >= 2 and parts[1]:
            return parts[1]

    return item_id


@dataclass
class WatchResult:
    item_id: str
    ok: bool
    message: str

    @property
    def already_watching(self) -> bool:
        return "already" in self.message.lower()


def _parse_response(body: str) -> tuple[bool, str]:
    """Read Ack and any error text out of a Trading API XML response."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        return False, f"unparseable response from eBay: {exc}"

    ack = root.findtext(f"{{{EBL_NS}}}Ack") or root.findtext("Ack") or ""

    messages = []
    for error in root.iter():
        if not error.tag.endswith("Errors"):
            continue
        short = "".join(
            child.text or ""
            for child in error
            if child.tag.endswith("ShortMessage")
        )
        long = "".join(
            child.text or "" for child in error if child.tag.endswith("LongMessage")
        )
        severity = "".join(
            child.text or ""
            for child in error
            if child.tag.endswith("SeverityCode")
        )
        text = (long or short).strip()
        if text:
            messages.append(f"[{severity or 'Error'}] {text}")

    detail = "; ".join(messages)

    if ack in ("Success", "Warning"):
        return True, detail or ack
    return False, detail or f"eBay returned Ack={ack or 'unknown'}"


class WatchlistClient:
    def __init__(
        self,
        user_auth: EbayUserAuth,
        client: httpx.AsyncClient,
        api_host: str,
        marketplace_id: str = "EBAY_US",
    ) -> None:
        self._auth = user_auth
        self._client = client
        self._url = f"https://{api_host}/ws/api.dll"
        self._site_id = SITE_IDS.get(marketplace_id, "0")

    async def add(self, item_id: str, detail: dict | None = None) -> WatchResult:
        legacy = legacy_item_id(item_id, detail)

        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            f'<AddToWatchListRequest xmlns="{EBL_NS}">'
            f"<ItemID>{legacy}</ItemID>"
            "</AddToWatchListRequest>"
        )

        try:
            token = await self._auth.token()
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            return WatchResult(item_id, False, f"no usable user token: {exc}")

        try:
            response = await self._client.post(
                self._url,
                content=body.encode(),
                headers={
                    "X-EBAY-API-CALL-NAME": "AddToWatchList",
                    "X-EBAY-API-SITEID": self._site_id,
                    "X-EBAY-API-COMPATIBILITY-LEVEL": COMPATIBILITY_LEVEL,
                    "X-EBAY-API-IAF-TOKEN": token,
                    "Content-Type": "text/xml",
                },
            )
        except httpx.HTTPError as exc:
            return WatchResult(item_id, False, f"request failed: {exc}")

        if response.status_code >= 400:
            return WatchResult(
                item_id, False, f"HTTP {response.status_code}: {response.text[:300]}"
            )

        ok, message = _parse_response(response.text)
        return WatchResult(item_id, ok, message)

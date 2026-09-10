"""eBay OAuth client-credentials tokens for the public (application) APIs.

Browse and Taxonomy both accept an application token minted from the
client-credentials grant, so there is no user consent flow to manage.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass

import httpx

from ..config import EbayConfig

# The scope every public Browse/Taxonomy call needs.
APP_SCOPE = "https://api.ebay.com/oauth/api_scope"

# Refresh a little before the token actually dies so a long scan cannot
# expire mid-flight.
_EXPIRY_SLACK_SECONDS = 120


@dataclass
class _Token:
    value: str
    expires_at: float

    def alive(self) -> bool:
        return time.time() < self.expires_at - _EXPIRY_SLACK_SECONDS


class EbayAuth:
    """Caches one application token and re-mints it when it ages out."""

    def __init__(self, config: EbayConfig, client: httpx.AsyncClient) -> None:
        self._config = config
        self._client = client
        self._token: _Token | None = None

    async def token(self) -> str:
        if self._token is not None and self._token.alive():
            return self._token.value

        credentials = f"{self._config.client_id}:{self._config.client_secret}"
        basic = base64.b64encode(credentials.encode()).decode()

        response = await self._client.post(
            f"{self._config.base_url}/identity/v1/oauth2/token",
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials", "scope": APP_SCOPE},
        )
        response.raise_for_status()
        payload = response.json()

        self._token = _Token(
            value=payload["access_token"],
            expires_at=time.time() + float(payload.get("expires_in", 7200)),
        )
        return self._token.value

    async def headers(self, marketplace_id: str | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {await self.token()}"}
        if marketplace_id:
            headers["X-EBAY-C-MARKETPLACE-ID"] = marketplace_id
        return headers

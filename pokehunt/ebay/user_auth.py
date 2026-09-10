"""User-token OAuth, for the calls that act on an account rather than read data.

Everything else in this package uses the client-credentials grant, which
authenticates the *application*. Adding an item to a watchlist touches a
person's account, so it needs a token minted from that person's consent via the
authorization-code grant.

That is a one-time interactive step (see `python -m pokehunt authorize`), after
which the refresh token is stored on disk and exchanged for access tokens
automatically. Refresh tokens are long-lived but not eternal; when one expires
the authorize step has to be repeated.

Two things that trip people up on eBay specifically:

  * `redirect_uri` is NOT a URL here. eBay wants the *RuName* ("redirect URL
    name") from your application keyset, which looks like
    `Your-Company-App-abcdef-xyz`. Passing the actual https URL fails.
  * The scopes your keyset is granted are set in the developer console. If the
    consent screen errors on an unknown scope, the keyset does not have it.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import httpx

from ..config import EbayConfig

log = logging.getLogger(__name__)

# eBay's consent host differs from the API host (and has its own sandbox).
CONSENT_HOST = "https://auth.ebay.com/oauth2/authorize"
SANDBOX_CONSENT_HOST = "https://auth.sandbox.ebay.com/oauth2/authorize"

_EXPIRY_SLACK_SECONDS = 120


class UserAuthError(RuntimeError):
    pass


@dataclass
class StoredGrant:
    refresh_token: str
    refresh_expires_at: float
    scopes: str

    def to_json(self) -> str:
        return json.dumps(self.__dict__, indent=2)

    @classmethod
    def load(cls, path: Path) -> "StoredGrant | None":
        if not path.exists():
            return None
        try:
            return cls(**json.loads(path.read_text()))
        except (json.JSONDecodeError, TypeError) as exc:
            raise UserAuthError(f"stored grant at {path} is unreadable: {exc}") from exc


def consent_url(config: EbayConfig, redirect_uri: str, scopes: str) -> str:
    host = SANDBOX_CONSENT_HOST if "sandbox" in config.api_host else CONSENT_HOST
    query = urlencode(
        {
            "client_id": config.client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": scopes,
        }
    )
    return f"{host}?{query}"


class EbayUserAuth:
    """Exchanges a consent code for a refresh token, then keeps access tokens fresh."""

    def __init__(
        self,
        config: EbayConfig,
        client: httpx.AsyncClient,
        grant_path: Path,
        redirect_uri: str | None = None,
        scopes: str = "",
    ) -> None:
        self._config = config
        self._client = client
        self._grant_path = Path(grant_path)
        self._redirect_uri = redirect_uri
        self._scopes = scopes
        self._access_token: str | None = None
        self._access_expires_at = 0.0

    def _basic(self) -> str:
        raw = f"{self._config.client_id}:{self._config.client_secret}"
        return base64.b64encode(raw.encode()).decode()

    async def _token_request(self, data: dict[str, str]) -> dict:
        response = await self._client.post(
            f"{self._config.base_url}/identity/v1/oauth2/token",
            headers={
                "Authorization": f"Basic {self._basic()}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=data,
        )
        if response.status_code >= 400:
            raise UserAuthError(
                f"eBay rejected the token request ({response.status_code}): "
                f"{response.text[:500]}"
            )
        return response.json()

    async def exchange_code(self, code: str) -> StoredGrant:
        """Trade a one-time consent code for a stored refresh token."""
        if not self._redirect_uri:
            raise UserAuthError("redirect_uri (your eBay RuName) is required")

        payload = await self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._redirect_uri,
            }
        )
        if "refresh_token" not in payload:
            raise UserAuthError(
                "eBay returned no refresh_token; the keyset may not be enabled "
                f"for this grant type. Response: {json.dumps(payload)[:500]}"
            )

        grant = StoredGrant(
            refresh_token=payload["refresh_token"],
            refresh_expires_at=time.time()
            + float(payload.get("refresh_token_expires_in", 47304000)),
            scopes=self._scopes,
        )
        self._grant_path.parent.mkdir(parents=True, exist_ok=True)
        self._grant_path.write_text(grant.to_json())
        # The refresh token is account credentials; keep it off group/other.
        self._grant_path.chmod(0o600)
        return grant

    async def token(self) -> str:
        if self._access_token and time.time() < self._access_expires_at - _EXPIRY_SLACK_SECONDS:
            return self._access_token

        grant = StoredGrant.load(self._grant_path)
        if grant is None:
            raise UserAuthError(
                f"no eBay user grant stored at {self._grant_path}. "
                "Run `python -m pokehunt authorize` once to create one."
            )
        if time.time() > grant.refresh_expires_at:
            raise UserAuthError(
                "the stored eBay refresh token has expired; re-run "
                "`python -m pokehunt authorize`"
            )

        payload = await self._token_request(
            {
                "grant_type": "refresh_token",
                "refresh_token": grant.refresh_token,
                "scope": grant.scopes or self._scopes,
            }
        )
        self._access_token = payload["access_token"]
        self._access_expires_at = time.time() + float(payload.get("expires_in", 7200))
        return self._access_token

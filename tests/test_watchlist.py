import httpx
import pytest

from pokehunt.config import EbayConfig, WatchlistConfig
from pokehunt.ebay.user_auth import EbayUserAuth, StoredGrant, UserAuthError, consent_url
from pokehunt.ebay.watchlist import WatchlistClient, _parse_response, legacy_item_id

SUCCESS = """<?xml version="1.0" encoding="UTF-8"?>
<AddToWatchListResponse xmlns="urn:ebay:apis:eBLBaseComponents">
  <Ack>Success</Ack><WatchListCount>7</WatchListCount>
</AddToWatchListResponse>"""

FAILURE = """<?xml version="1.0" encoding="UTF-8"?>
<AddToWatchListResponse xmlns="urn:ebay:apis:eBLBaseComponents">
  <Ack>Failure</Ack>
  <Errors>
    <ShortMessage>Item cannot be watched.</ShortMessage>
    <LongMessage>The item has ended and cannot be added to your watch list.</LongMessage>
    <SeverityCode>Error</SeverityCode>
  </Errors>
</AddToWatchListResponse>"""


def test_legacy_item_id_unwraps_the_browse_format():
    """Trading wants the numeric id; Browse hands out 'v1|<numeric>|<variation>'."""
    assert legacy_item_id("v1|110550947617|0") == "110550947617"
    assert legacy_item_id("v1|110550947617|123") == "110550947617"
    assert legacy_item_id("110550947617") == "110550947617"


def test_legacy_item_id_prefers_what_ebay_told_us():
    assert legacy_item_id("v1|999|0", {"legacyItemId": "110550947617"}) == "110550947617"


def test_parse_success_and_failure():
    ok, message = _parse_response(SUCCESS)
    assert ok is True

    ok, message = _parse_response(FAILURE)
    assert ok is False
    # eBay's own words survive, so a first-run failure is diagnosable.
    assert "has ended" in message


def test_parse_garbage_is_a_failure_not_a_crash():
    ok, message = _parse_response("<html>502 Bad Gateway</html>")
    assert ok is False


class FakeAuth:
    def __init__(self, token="tok", error=None):
        self._token = token
        self._error = error

    async def token(self):
        if self._error:
            raise self._error
        return self._token


@pytest.mark.asyncio
async def test_add_sends_the_legacy_id_and_iaf_token():
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode()
        seen["headers"] = dict(request.headers)
        return httpx.Response(200, text=SUCCESS)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = WatchlistClient(FakeAuth(), http, "api.ebay.com", "EBAY_US")
        result = await client.add("v1|110550947617|0")

    assert result.ok
    assert "<ItemID>110550947617</ItemID>" in seen["body"]
    assert seen["headers"]["x-ebay-api-call-name"] == "AddToWatchList"
    assert seen["headers"]["x-ebay-api-iaf-token"] == "tok"
    assert seen["headers"]["x-ebay-api-siteid"] == "0"


@pytest.mark.asyncio
async def test_add_reports_ebay_errors_rather_than_swallowing_them():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=FAILURE))
    ) as http:
        client = WatchlistClient(FakeAuth(), http, "api.ebay.com")
        result = await client.add("v1|1|0")
    assert result.ok is False and "has ended" in result.message


@pytest.mark.asyncio
async def test_missing_user_grant_is_a_clear_message_not_a_crash():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=SUCCESS))
    ) as http:
        client = WatchlistClient(
            FakeAuth(error=UserAuthError("no grant stored")), http, "api.ebay.com"
        )
        result = await client.add("v1|1|0")
    assert result.ok is False and "no grant stored" in result.message


def test_consent_url_carries_the_runame_and_scopes():
    config = EbayConfig(client_id="my-app-id", client_secret="s")
    url = consent_url(config, "My-Company-App-abcdef", "https://api.ebay.com/oauth/api_scope")
    assert url.startswith("https://auth.ebay.com/oauth2/authorize?")
    assert "client_id=my-app-id" in url
    assert "redirect_uri=My-Company-App-abcdef" in url
    assert "response_type=code" in url


def test_consent_url_follows_the_host_to_sandbox():
    config = EbayConfig(client_id="i", client_secret="s", api_host="api.sandbox.ebay.com")
    assert consent_url(config, "ru", "scope").startswith("https://auth.sandbox.ebay.com")


@pytest.mark.asyncio
async def test_exchange_code_stores_a_locked_down_grant(tmp_path):
    def handler(request):
        return httpx.Response(200, json={
            "access_token": "at", "expires_in": 7200,
            "refresh_token": "rt", "refresh_token_expires_in": 47304000,
        })

    grant_path = tmp_path / "grant.json"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        auth = EbayUserAuth(
            EbayConfig(client_id="i", client_secret="s"), http, grant_path, "ru", "scope"
        )
        grant = await auth.exchange_code("code123")

    assert grant.refresh_token == "rt"
    assert grant_path.exists()
    # A refresh token is account credentials.
    assert oct(grant_path.stat().st_mode)[-3:] == "600"


@pytest.mark.asyncio
async def test_exchange_code_without_a_runame_refuses(tmp_path):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    ) as http:
        auth = EbayUserAuth(
            EbayConfig(client_id="i", client_secret="s"), http, tmp_path / "g.json"
        )
        with pytest.raises(UserAuthError, match="RuName"):
            await auth.exchange_code("code")


@pytest.mark.asyncio
async def test_token_without_a_stored_grant_points_at_the_fix(tmp_path):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    ) as http:
        auth = EbayUserAuth(
            EbayConfig(client_id="i", client_secret="s"), http, tmp_path / "missing.json"
        )
        with pytest.raises(UserAuthError, match="pokehunt authorize"):
            await auth.token()


@pytest.mark.asyncio
async def test_expired_refresh_token_is_named_as_the_problem(tmp_path):
    grant_path = tmp_path / "grant.json"
    grant_path.write_text(StoredGrant("rt", 0.0, "scope").to_json())

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    ) as http:
        auth = EbayUserAuth(
            EbayConfig(client_id="i", client_secret="s"), http, grant_path
        )
        with pytest.raises(UserAuthError, match="expired"):
            await auth.token()


@pytest.mark.asyncio
async def test_access_tokens_are_reused_until_they_age_out(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"access_token": "at", "expires_in": 7200})

    grant_path = tmp_path / "grant.json"
    grant_path.write_text(StoredGrant("rt", 9e12, "scope").to_json())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        auth = EbayUserAuth(EbayConfig(client_id="i", client_secret="s"), http, grant_path)
        assert await auth.token() == "at"
        assert await auth.token() == "at"
    assert len(calls) == 1

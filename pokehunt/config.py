"""Configuration loaded from the environment.

Everything tunable lives here so the scanner, the settler and the scorer all
agree on thresholds. Nothing in this module hardcodes an eBay category id --
those are discovered at runtime (see pokehunt.ebay.taxonomy).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def _req(name: str) -> str:
    value = _env(name)
    if value is None:
        raise ConfigError(f"missing required environment variable {name}")
    return value


def _int(name: str, default: int) -> int:
    raw = _env(name)
    return default if raw is None else int(raw)


def _float(name: str, default: float) -> float:
    raw = _env(name)
    return default if raw is None else float(raw)


def _bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class EbayConfig:
    client_id: str
    client_secret: str
    marketplace_id: str = "EBAY_US"
    # api.ebay.com for production, api.sandbox.ebay.com for sandbox.
    api_host: str = "api.ebay.com"

    @property
    def base_url(self) -> str:
        return f"https://{self.api_host}"


@dataclass(frozen=True)
class FilterConfig:
    """The hunt criteria. A lot has to clear every one of these."""

    # Only auctions ending inside this window are considered.
    ending_within_hours: float = 24.0
    # Strictly fewer watchers than this. eBay does not always expose a watch
    # count; see WatchCountPolicy for what happens when it is unknown.
    max_watchers: int = 3
    # Strictly fewer feedback points than this -- the premise being that
    # low-feedback sellers price collections badly.
    max_seller_feedback: int = 100
    # Ignore sellers whose positive-feedback percentage is below this, so the
    # feedback filter selects for "new" rather than "burned".
    min_seller_feedback_pct: float = 90.0
    # Skip anything already bid past this; we want unloved lots.
    max_current_price: float = 400.0
    # Unknown watch counts: "skip" (conservative) or "allow" (noisy).
    unknown_watchers: str = "allow"
    # Cap on how many listings we run through the vision model per scan.
    max_vision_calls_per_scan: int = 40
    # Cap on images per listing sent to the vision model.
    max_images_per_listing: int = 8


@dataclass(frozen=True)
class VisionConfig:
    api_key: str
    model: str = "claude-sonnet-5"
    max_tokens: int = 4096
    # Anything at or below this is flagged red in Discord.
    confidence_threshold: float = 0.70


@dataclass(frozen=True)
class TcgConfig:
    api_key: str | None = None
    base_url: str = "https://api.pokemontcg.io/v2"
    # Fallback order through tcgplayer.prices when the vision model could not
    # pin down the printing. Deliberately cheapest-first: an unidentified
    # variant priced as a 1st-edition holo would inflate every estimate, and
    # the whole point of the month-long score is to find out whether the
    # estimates are honest. A confirmed variant jumps its own series to the
    # front (see market_value).
    price_preference: tuple[str, ...] = (
        "normal",
        "reverseHolofoil",
        "unlimitedHolofoil",
        "holofoil",
        "1stEditionNormal",
        "1stEditionHolofoil",
    )
    # Which key inside a price series to read as "market value".
    price_field_preference: tuple[str, ...] = ("market", "mid", "directLow", "low")


@dataclass(frozen=True)
class WatchlistConfig:
    """Adding alerted lots to the eBay watchlist. Costs nothing, bids nothing."""

    enabled: bool = False
    # eBay's RuName from your application keyset -- NOT an https URL.
    redirect_uri: str | None = None
    # Scopes requested at consent time. The base scope is the safe default;
    # if eBay rejects the consent screen or the watchlist call with a scope
    # error, set this to whatever your keyset actually lists.
    scopes: str = "https://api.ebay.com/oauth/api_scope"
    # Where the refresh token lives once you have authorized once.
    grant_path: Path = Path(".pokehunt-cache/ebay-user-grant.json")
    # Optional gates, so a shaky read does not clutter the watchlist. Zero
    # means "watch everything that was worth alerting on".
    min_confidence: float = 0.0
    min_estimated_value: float = 0.0
    # Give up for the rest of the scan after this many consecutive failures,
    # rather than hammering a broken credential forty times.
    failure_circuit_breaker: int = 3


@dataclass(frozen=True)
class DiscordConfig:
    webhook_url: str
    username: str = "pokehunt"
    # Discord caps embeds per message at 10.
    max_embeds: int = 10


@dataclass(frozen=True)
class Config:
    ebay: EbayConfig
    vision: VisionConfig
    tcg: TcgConfig
    discord: DiscordConfig
    watchlist: WatchlistConfig = field(default_factory=WatchlistConfig)
    filters: FilterConfig = field(default_factory=FilterConfig)
    db_path: Path = Path("pokehunt.db")
    cache_dir: Path = Path(".pokehunt-cache")
    # Alert-only means: never bid, never buy. This build has no bidding code
    # at all; the flag exists so the scoring report can assert it.
    alert_only: bool = True

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            ebay=EbayConfig(
                client_id=_req("EBAY_CLIENT_ID"),
                client_secret=_req("EBAY_CLIENT_SECRET"),
                marketplace_id=_env("EBAY_MARKETPLACE_ID", "EBAY_US"),
                api_host=_env("EBAY_API_HOST", "api.ebay.com"),
            ),
            vision=VisionConfig(
                api_key=_req("ANTHROPIC_API_KEY"),
                model=_env("POKEHUNT_VISION_MODEL", "claude-sonnet-5"),
                confidence_threshold=_float("POKEHUNT_CONFIDENCE_THRESHOLD", 0.70),
            ),
            tcg=TcgConfig(api_key=_env("POKEMONTCG_API_KEY")),
            discord=DiscordConfig(webhook_url=_req("DISCORD_WEBHOOK_URL")),
            watchlist=WatchlistConfig(
                enabled=_bool("POKEHUNT_WATCHLIST", False),
                redirect_uri=_env("EBAY_RUNAME"),
                scopes=_env(
                    "EBAY_USER_SCOPES", "https://api.ebay.com/oauth/api_scope"
                ),
                grant_path=Path(
                    _env(
                        "POKEHUNT_GRANT_PATH",
                        str(Path(_env("POKEHUNT_CACHE_DIR", ".pokehunt-cache"))
                            / "ebay-user-grant.json"),
                    )
                ),
                min_confidence=_float("POKEHUNT_WATCHLIST_MIN_CONFIDENCE", 0.0),
                min_estimated_value=_float("POKEHUNT_WATCHLIST_MIN_VALUE", 0.0),
            ),
            filters=FilterConfig(
                ending_within_hours=_float("POKEHUNT_ENDING_WITHIN_HOURS", 24.0),
                max_watchers=_int("POKEHUNT_MAX_WATCHERS", 3),
                max_seller_feedback=_int("POKEHUNT_MAX_SELLER_FEEDBACK", 100),
                min_seller_feedback_pct=_float("POKEHUNT_MIN_SELLER_FEEDBACK_PCT", 90.0),
                max_current_price=_float("POKEHUNT_MAX_CURRENT_PRICE", 400.0),
                unknown_watchers=_env("POKEHUNT_UNKNOWN_WATCHERS", "allow"),
                max_vision_calls_per_scan=_int("POKEHUNT_MAX_VISION_CALLS", 40),
                max_images_per_listing=_int("POKEHUNT_MAX_IMAGES", 8),
            ),
            db_path=Path(_env("POKEHUNT_DB", "pokehunt.db")),
            cache_dir=Path(_env("POKEHUNT_CACHE_DIR", ".pokehunt-cache")),
            alert_only=_bool("POKEHUNT_ALERT_ONLY", True),
        )

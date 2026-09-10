"""One place that wires every client together."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

import httpx

from .alerts.discord import DiscordNotifier
from .config import Config
from .ebay.auth import EbayAuth
from .ebay.browse import BrowseClient
from .ebay.taxonomy import TaxonomyClient
from .ebay.user_auth import EbayUserAuth
from .ebay.watchlist import WatchlistClient
from .store.db import Store
from .tcg.pokemontcg import PokemonTcgClient
from .vision.identify import VisionIdentifier

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


@dataclass
class Clients:
    config: Config
    http: httpx.AsyncClient
    browse: BrowseClient
    taxonomy: TaxonomyClient
    tcg: PokemonTcgClient
    vision: VisionIdentifier
    discord: DiscordNotifier
    store: Store
    # None unless POKEHUNT_WATCHLIST is on and a user grant is configured.
    watchlist: WatchlistClient | None = None


@asynccontextmanager
async def build_clients(config: Config) -> AsyncIterator[Clients]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as http:
        auth = EbayAuth(config.ebay, http)
        store = Store(config.db_path)

        watchlist = None
        if config.watchlist.enabled:
            user_auth = EbayUserAuth(
                config.ebay,
                http,
                grant_path=config.watchlist.grant_path,
                redirect_uri=config.watchlist.redirect_uri,
                scopes=config.watchlist.scopes,
            )
            watchlist = WatchlistClient(
                user_auth, http, config.ebay.api_host, config.ebay.marketplace_id
            )

        try:
            yield Clients(
                config=config,
                http=http,
                browse=BrowseClient(
                    auth, http, config.ebay.base_url, config.ebay.marketplace_id
                ),
                taxonomy=TaxonomyClient(
                    auth, http, config.ebay.base_url, config.ebay.marketplace_id
                ),
                tcg=PokemonTcgClient(config.tcg, http, config.cache_dir),
                vision=VisionIdentifier(config.vision),
                discord=DiscordNotifier(config.discord, http),
                store=store,
                watchlist=watchlist,
            )
        finally:
            store.close()

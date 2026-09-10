"""Discover the real Pokemon category ids from eBay's Taxonomy API.

We never hardcode category ids. The flow is:

  1. Ask for the marketplace's default category tree id.
  2. Ask for category suggestions for a handful of Pokemon queries.
  3. From the suggestions, walk up to the nearest Pokemon-ish ancestor and pull
     that node's whole subtree, so sibling leaves ("... Card Lots") get found
     even when the suggestion endpoint only surfaced one of them.
  4. Classify the leaves into singles vs lots by name.

The result is cached on disk because the tree changes rarely and the endpoint
is rate limited. If classification finds nothing, we raise instead of guessing
-- a wrong category id would silently poison every downstream number.
"""

from __future__ import annotations

import json
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

from .auth import EbayAuth

CACHE_TTL_SECONDS = 30 * 24 * 3600

# Queries chosen to land on both leaves from different directions.
SUGGESTION_QUERIES = (
    "pokemon individual trading card",
    "pokemon card lot",
    "pokemon trading card game single card",
    "pokemon tcg bulk collection lot",
)

_SINGLES_MARKERS = ("individual card", "single card", "individual", "singles")
_LOTS_MARKERS = ("lot", "lots", "bulk", "collection")
_POKEMON_MARKERS = ("pokemon",)
# Guards against wandering into video games / plush / other Pokemon branches.
_CARD_CONTEXT_MARKERS = (
    "ccg",
    "trading card",
    "collectible card",
    "card game",
    "tcg",
    "cards",
)


class CategoryDiscoveryError(RuntimeError):
    pass


def _fold(text: str) -> str:
    """Lowercase and strip accents so 'Pokémon' matches 'pokemon'."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.lower()


@dataclass
class Category:
    category_id: str
    name: str
    path: list[str] = field(default_factory=list)

    @property
    def folded_name(self) -> str:
        return _fold(self.name)


@dataclass
class CategorySet:
    tree_id: str
    marketplace_id: str
    singles: list[Category]
    lots: list[Category]
    discovered_at: float

    @property
    def all_ids(self) -> list[str]:
        return [c.category_id for c in self.singles + self.lots]

    def kind_for(self, category_id: str | None) -> str:
        if category_id is None:
            return "unknown"
        if any(c.category_id == category_id for c in self.singles):
            return "singles"
        if any(c.category_id == category_id for c in self.lots):
            return "lots"
        return "unknown"

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "CategorySet":
        data = json.loads(raw)
        return cls(
            tree_id=data["tree_id"],
            marketplace_id=data["marketplace_id"],
            singles=[Category(**c) for c in data["singles"]],
            lots=[Category(**c) for c in data["lots"]],
            discovered_at=data["discovered_at"],
        )


class TaxonomyClient:
    def __init__(
        self,
        auth: EbayAuth,
        client: httpx.AsyncClient,
        base_url: str,
        marketplace_id: str,
    ) -> None:
        self._auth = auth
        self._client = client
        self._base = f"{base_url}/commerce/taxonomy/v1"
        self._marketplace_id = marketplace_id

    async def _get(self, path: str, params: dict[str, str] | None = None) -> dict:
        response = await self._client.get(
            f"{self._base}{path}",
            params=params,
            headers=await self._auth.headers(self._marketplace_id),
        )
        response.raise_for_status()
        return response.json()

    async def default_tree_id(self) -> str:
        payload = await self._get(
            "/get_default_category_tree_id",
            {"marketplace_id": self._marketplace_id},
        )
        return payload["categoryTreeId"]

    async def suggestions(self, tree_id: str, query: str) -> list[dict]:
        payload = await self._get(
            f"/category_tree/{tree_id}/get_category_suggestions", {"q": query}
        )
        return payload.get("categorySuggestions", [])

    async def subtree(self, tree_id: str, category_id: str) -> dict:
        payload = await self._get(
            f"/category_tree/{tree_id}/get_category_subtree",
            {"category_id": category_id},
        )
        return payload.get("categorySubtreeNode", {})


def _walk_leaves(node: dict, path: list[str] | None = None) -> list[Category]:
    """Flatten a subtree node into its leaf categories, keeping the path."""
    path = path or []
    category = node.get("category", {})
    name = category.get("categoryName", "")
    category_id = str(category.get("categoryId", ""))
    here = path + [name] if name else path

    children = node.get("childCategoryTreeNodes") or []
    if not children:
        if not category_id:
            return []
        return [Category(category_id=category_id, name=name, path=here)]

    leaves: list[Category] = []
    for child in children:
        leaves.extend(_walk_leaves(child, here))
    return leaves


def _looks_pokemon(category: Category) -> bool:
    haystack = _fold(" ".join(category.path + [category.name]))
    if not any(marker in haystack for marker in _POKEMON_MARKERS):
        return False
    return any(marker in haystack for marker in _CARD_CONTEXT_MARKERS)


def classify(leaves: list[Category]) -> tuple[list[Category], list[Category]]:
    """Split Pokemon card leaves into (singles, lots).

    'Lot' wins over 'single' when a name somehow contains both, because a lot
    listing priced as a single is the expensive mistake.
    """
    singles: list[Category] = []
    lots: list[Category] = []

    for leaf in leaves:
        if not _looks_pokemon(leaf):
            continue
        name = leaf.folded_name
        if any(marker in name for marker in _LOTS_MARKERS):
            lots.append(leaf)
        elif any(marker in name for marker in _SINGLES_MARKERS):
            singles.append(leaf)

    return singles, lots


def _pick_expansion_root(suggestion: dict) -> tuple[str, str] | None:
    """Nearest ancestor worth expanding into a subtree.

    Suggestions come back with their ancestor chain ordered nearest-first. We
    want the closest ancestor that still reads as a Pokemon card node, so the
    subtree contains the singles leaf and the lots leaf but not all of
    'Collectible Card Games'.
    """
    ancestors = suggestion.get("categoryTreeNodeAncestors", [])
    for ancestor in ancestors:
        name = _fold(ancestor.get("categoryName", ""))
        if any(marker in name for marker in _POKEMON_MARKERS):
            return str(ancestor["categoryId"]), ancestor.get("categoryName", "")

    # No Pokemon ancestor: fall back to the immediate parent so we at least
    # enumerate siblings of whatever matched.
    if ancestors:
        nearest = ancestors[0]
        return str(nearest["categoryId"]), nearest.get("categoryName", "")
    return None


async def discover_categories(
    taxonomy: TaxonomyClient,
    marketplace_id: str,
    cache_dir: Path | None = None,
    force_refresh: bool = False,
) -> CategorySet:
    cache_path = None
    if cache_dir is not None:
        cache_path = Path(cache_dir) / f"categories-{marketplace_id}.json"
        if not force_refresh and cache_path.exists():
            cached = CategorySet.from_json(cache_path.read_text())
            if time.time() - cached.discovered_at < CACHE_TTL_SECONDS:
                return cached

    tree_id = await taxonomy.default_tree_id()

    # Collect suggestion leaves and the roots we want to expand.
    direct_leaves: dict[str, Category] = {}
    expansion_roots: dict[str, str] = {}

    for query in SUGGESTION_QUERIES:
        for suggestion in await taxonomy.suggestions(tree_id, query):
            category = suggestion.get("category", {})
            category_id = str(category.get("categoryId", ""))
            name = category.get("categoryName", "")
            if not category_id:
                continue
            ancestors = suggestion.get("categoryTreeNodeAncestors", [])
            path = [a.get("categoryName", "") for a in reversed(ancestors)]
            direct_leaves[category_id] = Category(
                category_id=category_id, name=name, path=path
            )
            root = _pick_expansion_root(suggestion)
            if root:
                expansion_roots[root[0]] = root[1]

    # Expand each root so sibling leaves (notably the lots leaf) get seen.
    expanded: dict[str, Category] = dict(direct_leaves)
    for root_id in expansion_roots:
        node = await taxonomy.subtree(tree_id, root_id)
        for leaf in _walk_leaves(node):
            expanded.setdefault(leaf.category_id, leaf)

    singles, lots = classify(list(expanded.values()))

    if not singles or not lots:
        found = sorted(f"{c.category_id}:{c.name}" for c in expanded.values())
        raise CategoryDiscoveryError(
            "taxonomy lookup did not yield both a Pokemon singles and a Pokemon "
            f"lots category for {marketplace_id}. "
            f"singles={[c.category_id for c in singles]} "
            f"lots={[c.category_id for c in lots]}. "
            f"candidates seen: {found}"
        )

    result = CategorySet(
        tree_id=tree_id,
        marketplace_id=marketplace_id,
        singles=singles,
        lots=lots,
        discovered_at=time.time(),
    )

    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(result.to_json())

    return result

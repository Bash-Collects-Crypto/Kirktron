import httpx
import pytest

from pokehunt.ebay.auth import EbayAuth
from pokehunt.ebay.taxonomy import (
    Category,
    CategoryDiscoveryError,
    TaxonomyClient,
    _walk_leaves,
    classify,
    discover_categories,
)
from pokehunt.config import EbayConfig

TREE_ID = "0"

# Shaped like a real Taxonomy response, with ids deliberately not the real ones
# so a test passing proves discovery worked rather than a lucky hardcode.
SUBTREE = {
    "category": {"categoryId": "99001", "categoryName": "Pokémon Trading Card Game"},
    "childCategoryTreeNodes": [
        {
            "category": {"categoryId": "99010", "categoryName": "Pokémon Individual Cards"},
        },
        {
            "category": {"categoryId": "99011", "categoryName": "Pokémon Card Lots"},
        },
        {
            "category": {"categoryId": "99012", "categoryName": "Pokémon Sealed Booster Packs"},
        },
    ],
}


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/oauth2/token"):
        return httpx.Response(200, json={"access_token": "tok", "expires_in": 7200})
    if path.endswith("/get_default_category_tree_id"):
        return httpx.Response(200, json={"categoryTreeId": TREE_ID})
    if path.endswith("/get_category_suggestions"):
        return httpx.Response(
            200,
            json={
                "categorySuggestions": [
                    {
                        "category": {
                            "categoryId": "99010",
                            "categoryName": "Pokémon Individual Cards",
                        },
                        "categoryTreeNodeAncestors": [
                            {"categoryId": "99001", "categoryName": "Pokémon Trading Card Game"},
                            {"categoryId": "2536", "categoryName": "CCG Individual Cards"},
                        ],
                    }
                ]
            },
        )
    if "/get_category_subtree" in path:
        return httpx.Response(200, json={"categorySubtreeNode": SUBTREE})
    return httpx.Response(404)


@pytest.fixture
def taxonomy():
    transport = httpx.MockTransport(_handler)
    client = httpx.AsyncClient(transport=transport)
    config = EbayConfig(client_id="id", client_secret="secret")
    auth = EbayAuth(config, client)
    return TaxonomyClient(auth, client, config.base_url, "EBAY_US"), client


def test_walk_leaves_flattens_subtree():
    leaves = _walk_leaves(SUBTREE)
    assert {leaf.category_id for leaf in leaves} == {"99010", "99011", "99012"}
    assert all("Pokémon Trading Card Game" in leaf.path for leaf in leaves)


def test_classify_splits_singles_and_lots():
    leaves = _walk_leaves(SUBTREE)
    singles, lots = classify(leaves)
    assert [c.category_id for c in singles] == ["99010"]
    assert [c.category_id for c in lots] == ["99011"]


def test_classify_ignores_non_card_pokemon_branches():
    leaves = [
        Category("5", "Pokémon Plush Lots", ["Toys", "Plush"]),
        Category("6", "Pokémon Video Game Lots", ["Video Games"]),
    ]
    singles, lots = classify(leaves)
    assert singles == []
    assert lots == []


def test_classify_prefers_lots_when_a_name_says_both():
    leaves = [Category("7", "Pokémon Individual Card Lots", ["CCG Trading Cards"])]
    singles, lots = classify(leaves)
    assert not singles
    assert [c.category_id for c in lots] == ["7"]


@pytest.mark.asyncio
async def test_discover_categories_pulls_ids_from_the_api(taxonomy, tmp_path):
    client, http = taxonomy
    result = await discover_categories(client, "EBAY_US", cache_dir=tmp_path)
    assert result.tree_id == TREE_ID
    assert [c.category_id for c in result.singles] == ["99010"]
    assert [c.category_id for c in result.lots] == ["99011"]
    assert result.kind_for("99010") == "singles"
    assert result.kind_for("99011") == "lots"
    assert result.kind_for("12345") == "unknown"
    assert (tmp_path / "categories-EBAY_US.json").exists()
    await http.aclose()


@pytest.mark.asyncio
async def test_discover_categories_uses_cache_on_second_call(taxonomy, tmp_path):
    client, http = taxonomy
    first = await discover_categories(client, "EBAY_US", cache_dir=tmp_path)
    second = await discover_categories(client, "EBAY_US", cache_dir=tmp_path)
    assert first.discovered_at == second.discovered_at
    await http.aclose()


@pytest.mark.asyncio
async def test_discover_raises_rather_than_guessing_when_lots_missing(tmp_path):
    def only_singles(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 7200})
        if request.url.path.endswith("/get_default_category_tree_id"):
            return httpx.Response(200, json={"categoryTreeId": TREE_ID})
        if request.url.path.endswith("/get_category_suggestions"):
            return httpx.Response(
                200,
                json={
                    "categorySuggestions": [
                        {
                            "category": {"categoryId": "99010", "categoryName": "Pokémon Individual Cards"},
                            "categoryTreeNodeAncestors": [
                                {"categoryId": "99001", "categoryName": "Pokémon Trading Cards"}
                            ],
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "categorySubtreeNode": {
                    "category": {"categoryId": "99001", "categoryName": "Pokémon Trading Cards"},
                    "childCategoryTreeNodes": [
                        {"category": {"categoryId": "99010", "categoryName": "Pokémon Individual Cards"}}
                    ],
                }
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(only_singles))
    config = EbayConfig(client_id="id", client_secret="secret")
    client = TaxonomyClient(EbayAuth(config, http), http, config.base_url, "EBAY_US")
    with pytest.raises(CategoryDiscoveryError):
        await discover_categories(client, "EBAY_US", cache_dir=tmp_path)
    await http.aclose()

import asyncio
import json

import httpx
import pytest

from backend import mcp_server
from backend.mcp_server import (
    Grimoire, collection_summary, get_deck, list_collections, list_decks, rule_zero, search_cards,
)

COLLECTIONS = {"collections": [
    {"job_id": "aaa1", "name": "Main Binder", "card_count": 40, "created": "2026-11-10"},
    {"job_id": "bbb2", "name": "Trade Box", "card_count": 12, "created": "2026-11-01"}]}
DECKS = {"decks": [{"id": "d1", "name": "Goblin Tribal", "format": "commander",
                    "commander": "Krenko, Mob Boss", "count": 100, "built": True}]}
DECK = {"name": "Goblin Tribal", "format": "commander", "built": True,
        "commander": {"name": "Krenko, Mob Boss"},
        "sections": {"main": [{"scryfall_id": "s1", "name": "Goblin Guide", "count": 1}],
                     "sideboard": [], "maybeboard": []},
        "analysis": {"count": {"main": 2}, "price": 3.5,
                     "cards": {"s1": {"issues": ["not_owned"],
                                      "reasons": {"not_owned": "Main Binder holds no copy."}}},
                     "bracket": {"floor": 2}}}


def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/api/collections":
        return httpx.Response(200, json=COLLECTIONS)
    if path == "/api/decks":
        return httpx.Response(200, json=DECKS)
    if path == "/api/decks/d1":
        return httpx.Response(200, json=DECK)
    if path == "/api/decks/d1/rule-zero":
        return httpx.Response(200, json={"text": "Goblin Tribal\nBracket 1 or 2\n"})
    if path.startswith("/api/collection/") and path.endswith("/search"):
        job = path.split("/")[3]
        return httpx.Response(200, json={"total": 1, "value": 2.0, "query": request.url.params.get("q"),
                                         "cards": [{"name": "Bolt (%s)" % job, "quantity": 2,
                                                    "price": 1.0, "flags": [], "foil": False}]})
    if path.endswith("/insights"):
        return httpx.Response(200, json={"name": "Main Binder", "cards": 40, "value": 99.0,
                                         "price_label": "TCGplayer", "secret": "x"})
    return httpx.Response(404, json={"detail": "Not found"})


@pytest.fixture
def api():
    return Grimoire("http://grimoire.test", transport=httpx.MockTransport(handler))


def test_the_tools_read_collections_and_cards(api):
    assert list_collections(api)[0] == {"name": "Main Binder", "id": "aaa1", "cards": 40,
                                        "imported": "2026-11-10"}
    found = search_cards(api, "t:goblin", "trade")  # a part of the name is enough
    assert found["collection"] == "bbb2"
    assert found["cards"] == [{"name": "Bolt (bbb2)", "quantity": 2, "foil": False, "price": 1.0}]
    assert search_cards(api, "bolt")["collection"] == "aaa1"  # the newest collection
    summary = collection_summary(api)
    assert summary == {"name": "Main Binder", "cards": 40, "value": 99.0, "price_label": "TCGplayer"}
    with pytest.raises(RuntimeError, match="No collection is called 'Nope'"):
        search_cards(api, "", "Nope")


def test_the_tools_read_decks(api):
    assert list_decks(api)[0]["name"] == "Goblin Tribal"
    deck = get_deck(api, "goblin tribal")
    assert deck["commander"] == "Krenko, Mob Boss"
    assert deck["sections"]["main"] == [{"count": 1, "name": "Goblin Guide"}]
    assert deck["card_issues"] == [{"card": "Goblin Guide",
                                    "issues": {"not_owned": "Main Binder holds no copy."}}]
    assert rule_zero(api, "Goblin") == "Goblin Tribal\nBracket 1 or 2\n"
    with pytest.raises(RuntimeError, match="No saved deck"):
        get_deck(api, "Elves")


def test_a_stopped_app_gives_a_clear_message():
    def down(request):
        raise httpx.ConnectError("refused")

    api = Grimoire("http://127.0.0.1:9", transport=httpx.MockTransport(down))
    with pytest.raises(RuntimeError, match="Grimoire is not running"):
        list_collections(api)


def test_the_server_lists_only_read_tools(api):
    server = mcp_server.build_server(api)
    tools = asyncio.run(server.list_tools())
    names = sorted(t.name for t in tools)
    assert names == ["grimoire_collection_summary", "grimoire_get_deck", "grimoire_list_collections",
                     "grimoire_list_decks", "grimoire_pull_list", "grimoire_rule_zero",
                     "grimoire_search_cards"]
    result = asyncio.run(server.call_tool("grimoire_list_decks", {}))
    text = json.dumps(result, default=str)
    assert "Goblin Tribal" in text

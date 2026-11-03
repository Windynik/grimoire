import json

import pytest
from fastapi.testclient import TestClient

from backend.api.dependencies import get_bulk_data_manager, get_collection_store
from backend.core.collection_store import CollectionStore
from main import app
from tests.forge.conftest import make_record
from tests.test_api import FakeBulk

client = TestClient(app)


def write(store, job_id, name, created, cards, original=None):
    payload = {"meta": {"job_id": job_id, "name": name, "created": created,
                        "card_count": len(cards)}, "cards": cards}
    if original:
        payload["original"] = original
    (store.storage_dir / (job_id + ".json")).write_text(json.dumps(payload))


def row(sid, name, qty=1, foil="normal"):
    return {"name": name, "scryfall_id": sid, "quantity": qty, "foil": foil}


@pytest.fixture
def env(tmp_path):
    store = CollectionStore(storage_dir=str(tmp_path / "collections"))
    bolt = make_record("Bolt", "Instant", "{R}", "Deal 3.", ("R",), 1, rarity="common")
    bolt["prices"]["usd"] = "2.00"
    wurm = make_record("Gold Wurm", "Creature — Wurm", "{G}{U}", "", ("G", "U"), 5, rarity="mythic")
    wurm["prices"]["usd"] = "10.00"
    wurm["set"] = "neo"
    elf = make_record("Elf", "Creature — Elf", "{G}", "", ("G",), 1, rarity="rare")
    elf["prices"]["usd"] = "1.00"
    elf["set"] = "neo"
    bulk = FakeBulk({"id-bolt": bolt, "id-wurm": wurm, "id-elf": elf})
    app.dependency_overrides[get_collection_store] = lambda: store
    app.dependency_overrides[get_bulk_data_manager] = lambda: bulk
    write(store, "old", "Old", "2026-01-01T00:00:00+00:00",
          [row("id-bolt", "Bolt"), row("id-elf", "Elf")])
    write(store, "cur", "Current", "2026-02-01T00:00:00+00:00",
          [row("id-bolt", "Bolt", 2), row("id-elf", "Elf"), row("id-wurm", "Gold Wurm")],
          original={"headers": ["Set code", "Set name"],
                    "rows": [{"Set code": "neo", "Set name": "Kamigawa"}]})
    yield store, bulk
    app.dependency_overrides.clear()


def get(url):
    response = client.get(url)
    assert response.status_code == 200, response.text
    return response.json()


def names(url):
    return [c["name"] for c in get(url)["cards"]]


def test_search_returns_cards_facets_and_value(env):
    body = get("/api/collection/cur/search?sort=name")
    assert [c["name"] for c in body["cards"]] == ["Bolt", "Elf", "Gold Wurm"]
    assert body["total"] == 3 and body["offset"] == 0 and body["limit"] == 60
    assert body["value"] == 2.0 * 2 + 1.0 + 10.0
    assert body["facets"]["rarity"]["mythic"] == 1
    card = body["cards"][0]
    assert card["owned"] is True and card["quantity"] == 2 and card["price"] == 2.0
    assert card["set_name"] and card["image_url"] == ""
    for key in ("name", "scryfall_id", "mana_cost", "oracle_text", "type_line",
                "back_image_url", "rarity", "set", "foil", "new", "cmc", "color_identity"):
        assert key in card


def test_search_keywords_and_multi_filters(env):
    assert names("/api/collection/cur/search?q=t:creature&sort=name") == ["Elf", "Gold Wurm"]
    assert names("/api/collection/cur/search?colors=G,R&sort=name") == ["Bolt", "Elf"]
    assert names("/api/collection/cur/search?colors=M") == ["Gold Wurm"]
    assert names("/api/collection/cur/search?rarity=rare,mythic&sort=name") == ["Elf", "Gold Wurm"]
    assert names("/api/collection/cur/search?type=Creature&mv=1,7%2B&sort=name") == ["Elf"]
    assert names("/api/collection/cur/search?set=neo&sort=name") == ["Elf", "Gold Wurm"]
    assert names("/api/collection/cur/search?min_price=5") == ["Gold Wurm"]
    assert names("/api/collection/cur/search?dupes=true") == ["Bolt"]
    assert names("/api/collection/cur/search?format=modern&sort=name") == ["Bolt", "Elf", "Gold Wurm"]


def test_search_pagination_and_limit_cap(env):
    body = get("/api/collection/cur/search?sort=name&limit=1&offset=1")
    assert [c["name"] for c in body["cards"]] == ["Elf"]
    assert body["total"] == 3 and body["limit"] == 1 and body["offset"] == 1
    assert get("/api/collection/cur/search?limit=9999")["limit"] == 200


def test_search_marks_new_cards_against_previous_collection(env):
    cards = {c["name"]: c for c in get("/api/collection/cur/search")["cards"]}
    assert cards["Bolt"]["new"] is True       # quantity 1 -> 2
    assert cards["Gold Wurm"]["new"] is True  # absent before
    assert cards["Elf"]["new"] is False
    assert names("/api/collection/cur/search?q=new&sort=name") == ["Bolt", "Gold Wurm"]
    # the oldest collection has no previous one: nothing is new
    assert not any(c["new"] for c in get("/api/collection/old/search")["cards"])


def test_search_uses_csv_set_names(env):
    cards = {c["name"]: c for c in get("/api/collection/cur/search")["cards"]}
    assert cards["Gold Wurm"]["set_name"] == "Kamigawa"


def test_old_parameters_still_work(env):
    assert names("/api/collection/cur/search?card_type=creature&sort=name") == ["Elf", "Gold Wurm"]
    assert names("/api/collection/cur/search?color=G&sort=name") == ["Elf", "Gold Wurm"]
    assert names("/api/collection/cur/search?color=C") == []
    assert names("/api/collection/cur/search?color=R") == ["Bolt"]
    assert names("/api/collection/cur/search?rarity=rare") == ["Elf"]
    assert names("/api/collection/cur/search?q=gold") == ["Gold Wurm"]
    assert names("/api/collection/cur/search?foil=normal&sort=name") == ["Bolt", "Elf", "Gold Wurm"]
    assert names("/api/collection/cur/search?foil=foil") == []
    assert names("/api/collection/cur/search?sort=price_asc") == ["Elf", "Bolt", "Gold Wurm"]


def test_foil_filter_true_and_false(env):
    store, _ = env
    write(store, "f", "F", "2026-03-01T00:00:00+00:00",
          [row("id-bolt", "Bolt", 1, "foil"), row("id-elf", "Elf")])
    assert names("/api/collection/f/search?foil=true") == ["Bolt"]
    assert names("/api/collection/f/search?foil=foil") == ["Bolt"]
    assert names("/api/collection/f/search?foil=false") == ["Elf"]


def test_unknown_format_is_400_and_unknown_job_is_404(env):
    assert client.get("/api/collection/cur/search?format=historic").status_code == 400
    assert client.get("/api/collection/nope/search").status_code == 404
    assert client.get("/api/collection/nope/search?q=bolt").status_code == 404
    assert client.get("/api/collection/nope/insights").status_code == 404


def test_insights_route(env):
    body = get("/api/collection/cur/insights")
    assert body["cards"] == 4 and body["unique"] == 3
    assert body["value"] == 15.0
    assert body["name"] == "Current"
    assert body["created"] == "2026-02-01T00:00:00+00:00"
    assert body["has_previous"] is True
    assert "card_data_date" in body
    assert get("/api/collection/old/insights")["has_previous"] is False


def test_merge_is_cached_until_file_changes(env, monkeypatch):
    import backend.api.collection_routes as cr
    calls = []
    real = cr.owned_cards
    monkeypatch.setattr(cr, "owned_cards", lambda *a, **k: calls.append(1) or real(*a, **k))
    cr.MERGE_CACHE.clear()
    get("/api/collection/cur/search")
    get("/api/collection/cur/search?q=bolt")
    assert len(calls) == 1
    store, _ = env
    path = store.storage_dir / "cur.json"
    data = json.loads(path.read_text())
    data["cards"].append(row("id-elf", "Elf", 1, "foil"))
    path.write_text(json.dumps(data))
    import os
    os.utime(path, ns=(10**18, 10**18))
    assert get("/api/collection/cur/search")["total"] == 4
    assert len(calls) == 2


def test_archive_search_parses_keywords(env):
    _, bulk = env
    body = get("/api/cards/search?q=t:creature&sort=name")
    assert [c["name"] for c in body["cards"]] == ["Elf", "Gold Wurm"]
    assert "facets" not in body and "value" not in body
    assert [c["name"] for c in get("/api/cards/search?q=mv:5-")["cards"]] == ["Gold Wurm"]
    assert [c["name"] for c in get("/api/cards/search?q=c:ug")["cards"]] == ["Gold Wurm"]
    # collection-only keywords are ignored
    assert get("/api/cards/search?q=foil dupes new")["total"] == 3
    assert [c["name"] for c in get("/api/cards/search?q=bolt foil")["cards"]] == ["Bolt"]
    assert [c["name"] for c in get("/api/cards/search?q=r:mythic")["cards"]] == ["Gold Wurm"]

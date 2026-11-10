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


def test_raw_plus_in_mv_and_uppercase_keywords(env):
    store, bulk = env
    big = make_record("Titan", "Creature", "{7}", "", ("G",), 8)
    bulk.cards["id-titan"] = big
    write(store, "t", "T", "2026-04-01T00:00:00+00:00", [row("id-titan", "Titan"), row("id-elf", "Elf")])
    assert names("/api/collection/t/search?mv=7+") == ["Titan"]
    assert names("/api/collection/t/search?q=T:Creature&sort=name") == ["Elf", "Titan"]
    assert names("/api/collection/cur/search?q=C:UG") == ["Gold Wurm"]


def test_unindexed_card_color_fallback_old_param_facet_and_keyword(env):
    store, _ = env
    write(store, "u", "U", "2026-04-01T00:00:00+00:00",
          [{"name": "Gone", "scryfall_id": "id-gone", "mana_cost": "{1}{G}", "quantity": 1},
           {"name": "Blank", "scryfall_id": "id-blank", "quantity": 1}])
    assert names("/api/collection/u/search?color=G") == ["Gone"]
    assert names("/api/collection/u/search?colors=G") == ["Gone"]
    assert names("/api/collection/u/search?q=c:g") == ["Gone"]
    assert names("/api/collection/u/search?color=C") == ["Blank"]
    assert get("/api/collection/u/search")["facets"]["colors"]["G"] == 1


def test_empty_index_is_not_cached_and_keeps_good_entries(env):
    import backend.api.collection_routes as cr
    store, bulk = env
    cr.MERGE_CACHE.clear()
    get("/api/collection/cur/search")
    good = dict(cr.MERGE_CACHE)
    assert len(good) == 1
    saved = dict(bulk.cards)
    bulk.cards.clear()
    get("/api/collection/cur/search")
    assert len(cr.MERGE_CACHE) <= 1
    bulk.cards.update(saved)
    assert dict(cr.MERGE_CACHE) == good or len(cr.MERGE_CACHE) == 0


def test_cache_cleared_when_index_changes(env):
    import backend.api.collection_routes as cr
    store, bulk = env
    cr.MERGE_CACHE.clear()
    get("/api/collection/cur/search")
    get("/api/collection/old/search")
    assert len(cr.MERGE_CACHE) == 2
    app.dependency_overrides[get_bulk_data_manager] = lambda: FakeBulk(dict(bulk.cards))
    get("/api/collection/cur/search")
    assert len(cr.MERGE_CACHE) == 1
    assert all(m.index is not bulk.cards for m in cr.MERGE_CACHE.values())


def test_rewriting_the_older_collection_refreshes_new_flags(env):
    import os
    store, _ = env
    assert {c["name"]: c["new"] for c in get("/api/collection/cur/search")["cards"]}["Elf"] is False
    write(store, "old", "Old", "2026-01-01T00:00:00+00:00", [row("id-bolt", "Bolt", 2)])
    os.utime(store.storage_dir / "old.json", ns=(2 * 10**18, 2 * 10**18))
    flags = {c["name"]: c["new"] for c in get("/api/collection/cur/search")["cards"]}
    assert flags["Elf"] is True and flags["Bolt"] is False


# --- shelves, sets, deck usage, and the sample collection ---

import datetime

from backend.api import collection_routes, routes
from backend.api.dependencies import get_csv_processor, get_deck_store
from backend.core.csv_processor import CSVProcessor
from backend.decks.store import DeckStore


@pytest.fixture
def set_env(env):
    store, bulk = env
    for sid, name, number, rarity in (("id-neo-9", "Zed", "10", "common"),
                                      ("id-neo-2", "Alpha Wolf", "2", "uncommon")):
        card = make_record(name, "Creature — Wolf", "{G}", "", ("G",), 1, rarity=rarity)
        card["set"] = "neo"
        card["set_name"] = "Kamigawa Neon"
        card["collector_number"] = number
        bulk.cards[sid] = card
    token = make_record("Spirit", "Token Creature — Spirit", "", "", (), 0, layout="token")
    token["set"] = "neo"
    bulk.cards["id-neo-token"] = token
    bulk.cards["id-wurm"]["collector_number"] = "5"
    bulk.cards["id-elf"]["collector_number"] = "100"
    return store, bulk


def test_shelves_lists_and_limits(set_env):
    body = get("/api/collection/cur/shelves")
    assert set(body) == {"spotlight", "valuable", "foils", "new"}
    assert [c["name"] for c in body["valuable"]] == ["Gold Wurm", "Bolt", "Elf"]
    assert body["foils"] == []
    assert [c["name"] for c in body["new"]] == ["Gold Wurm", "Bolt"]
    assert body["new"][0]["new"] is True
    assert get("/api/collection/old/shelves")["new"] == []


def test_shelves_foils_and_unique_by_id_and_foil(set_env):
    store, _ = set_env
    write(store, "dup", "Dup", "2026-03-01T00:00:00+00:00",
          [row("id-bolt", "Bolt"), row("id-bolt", "Bolt", 3), row("id-bolt", "Bolt", 1, "foil")])
    body = get("/api/collection/dup/shelves")
    assert len(body["valuable"]) == 2
    assert [c["name"] for c in body["foils"]] == ["Bolt"] and body["foils"][0]["foil"] is True


def test_shelves_cap_at_twelve(set_env):
    store, bulk = set_env
    rows = []
    for i in range(15):
        card = make_record("Many %d" % i, "Instant", "{R}", "", ("R",), 1, rarity="common")
        card["prices"]["usd"] = str(i + 1)
        bulk.cards["id-many-%d" % i] = card
        rows.append(row("id-many-%d" % i, "Many %d" % i))
    write(store, "big", "Big", "2026-04-01T00:00:00+00:00", rows)
    assert len(get("/api/collection/big/shelves")["valuable"]) == 12


def test_spotlight_is_stable_in_a_day_and_changes_across_days(set_env, monkeypatch):
    def at(day):
        monkeypatch.setattr(collection_routes, "today", lambda: day)
        return get("/api/collection/cur/shelves")["spotlight"]["name"]

    first = datetime.date(2026, 11, 3)
    assert at(first) == at(first)
    days = (first - datetime.date(1970, 1, 1)).days
    assert at(first) == ["Elf", "Gold Wurm"][days % 2]
    assert at(first + datetime.timedelta(days=1)) != at(first)


def test_spotlight_is_null_without_rare_cards(set_env):
    store, _ = set_env
    write(store, "commons", "Commons", "2026-05-01T00:00:00+00:00", [row("id-bolt", "Bolt")])
    assert get("/api/collection/commons/shelves")["spotlight"] is None


def test_sets_totals_ignore_tokens_and_sort_by_completion(set_env):
    sets = get("/api/collection/cur/sets")
    by_code = {s["code"]: s for s in sets}
    neo = by_code["neo"]
    assert neo["name"] == "Kamigawa Neon"
    assert neo["total"] == 4 and neo["owned"] == 2  # Elf, Gold Wurm, Zed, Alpha Wolf; no token
    assert neo["value"] == 11.0 and neo["art_id"] == "id-wurm"
    assert by_code["tst"]["total"] == 1 and by_code["tst"]["owned"] == 1
    assert by_code["tst"]["value"] == 4.0
    assert [s["code"] for s in sets] == ["tst", "neo"]


def test_set_checklist_order_and_owned_printing(set_env):
    body = get("/api/collection/cur/sets/neo")
    assert body["code"] == "neo" and body["name"] == "Kamigawa Neon"
    assert body["total"] == 4 and body["owned"] == 2
    assert [c["name"] for c in body["cards"]] == ["Alpha Wolf", "Gold Wurm", "Zed", "Elf"]
    cards = {c["name"]: c for c in body["cards"]}
    assert cards["Gold Wurm"]["quantity"] == 1 and cards["Gold Wurm"]["price"] == 10.0
    assert cards["Zed"]["quantity"] == 0 and cards["Zed"]["scryfall_id"] == "id-neo-9"
    for key in ("scryfall_id", "name", "mana_cost", "type_line", "rarity",
                "collector_number", "image_url", "price", "quantity", "foil"):
        assert key in body["cards"][0]


def test_set_checklist_unknown_set_is_404(set_env):
    assert client.get("/api/collection/cur/sets/zzz").status_code == 404


def test_deck_usage(env, tmp_path):
    decks = DeckStore(storage_dir=str(tmp_path / "decks"))
    app.dependency_overrides[get_deck_store] = lambda: decks
    record = {"name": "Red", "format": "modern", "commander": None,
              "sections": {"main": [{"scryfall_id": "id-bolt", "name": "Bolt", "count": 1}],
                           "sideboard": [], "maybeboard": []}}
    other = {"name": "Boss", "format": "commander",
             "commander": {"scryfall_id": "id-wurm", "name": "Gold Wurm", "count": 1},
             "sections": {"main": [], "sideboard": [{"scryfall_id": "id-bolt", "name": "Bolt", "count": 1}],
                          "maybeboard": []}}
    red = decks.save(record)
    boss = decks.save(other)
    body = get("/api/decks/usage?ids=id-bolt,id-wurm,id-none")
    assert {d["deck_id"] for d in body["id-bolt"]} == {red, boss}
    assert body["id-wurm"] == [{"deck_id": boss, "name": "Boss"}]
    assert body["id-none"] == []
    assert get("/api/decks/usage?ids=") == {}


def _sample_env(tmp_path, monkeypatch, csv_text):
    store = CollectionStore(storage_dir=str(tmp_path / "collections"))
    bulk = FakeBulk({"id-bolt": make_record("Bolt", "Instant", "{R}", "", ("R",), 1)})
    sample = tmp_path / "sample.csv"
    if csv_text is not None:
        sample.write_text(csv_text)
    monkeypatch.setattr(routes, "SAMPLE_PATH", sample)
    processor = CSVProcessor(progress_dir=str(tmp_path / "progress"))
    app.dependency_overrides[get_collection_store] = lambda: store
    app.dependency_overrides[get_bulk_data_manager] = lambda: bulk
    app.dependency_overrides[get_csv_processor] = lambda: processor
    return store


def test_sample_stream_ends_with_done_and_stores_the_name(tmp_path, monkeypatch):
    store = _sample_env(tmp_path, monkeypatch, "Name,Scryfall ID,Quantity\nBolt,id-bolt,2\n")
    try:
        response = client.post("/api/process/sample")
        events = [json.loads(line[6:]) for line in response.text.splitlines()
                  if line.startswith("data: ")]
        assert events[-1]["type"] == "done"
        job_id = events[-1]["result"]["job_id"]
        assert store.list_collections()[0]["name"] == "Sample collection"
        assert store.get_collection(job_id) is not None
    finally:
        app.dependency_overrides.clear()


def test_sample_missing_file_is_404(tmp_path, monkeypatch):
    _sample_env(tmp_path, monkeypatch, None)
    try:
        response = client.post("/api/process/sample")
        assert response.status_code == 404
        assert response.json() == {"detail": "The sample collection is missing."}
    finally:
        app.dependency_overrides.clear()


def test_real_sample_file_exists():
    assert routes.SAMPLE_PATH.name == "ManaBox_Collection.csv" and routes.SAMPLE_PATH.exists()


def test_archive_card_carries_legality_and_set_details(set_env):
    body = get("/api/cards/search?q=gold%20wurm")
    card = body["cards"][0]
    assert card["legalities"]["modern"] == "legal"
    assert card["legalities"]["standard"] == "legal"
    for key in ("set_name", "collector_number", "edhrec_rank"):
        assert key in card


def test_set_checklist_cards_carry_drawer_fields(set_env):
    cards = {c["name"]: c for c in get("/api/collection/cur/sets/neo")["cards"]}
    for name in ("Gold Wurm", "Zed"):  # one owned, one missing
        card = cards[name]
        assert card["legalities"]["modern"] == "legal"
        for key in ("oracle_text", "back_image_url", "set_name", "edhrec_rank"):
            assert key in card
    assert cards["Zed"]["set_name"] == "Kamigawa Neon"


def test_owned_count_counts_only_catalog_names(set_env):
    store, bulk = set_env
    # An owned name that the catalog of "neo" does not list
    stray = make_record("Stray", "Creature — Cat", "{G}", "", ("G",), 1)
    stray["set"] = "neo"
    bulk.cards["id-stray"] = stray
    write(store, "stray", "Stray", "2026-06-01T00:00:00+00:00",
          [row("id-wurm", "Gold Wurm"), row("id-stray", "Stray")])
    bulk.cards["id-stray"]["type_line"] = "Token Creature — Cat"
    summary = {s["code"]: s for s in get("/api/collection/stray/sets")}
    assert summary["neo"]["owned"] == 1 and summary["neo"]["total"] == 4
    checklist = get("/api/collection/stray/sets/neo")
    assert checklist["owned"] == 1 and checklist["total"] == 4


def test_token_only_set_has_total_zero_and_sorts_last(set_env):
    store, bulk = set_env
    tok = make_record("Treasure", "Token Artifact — Treasure", "", "", (), 0, layout="token")
    tok["set"] = "ttok"
    bulk.cards["id-tok"] = tok
    write(store, "toks", "Toks", "2026-06-02T00:00:00+00:00",
          [row("id-tok", "Treasure"), row("id-bolt", "Bolt")])
    sets = get("/api/collection/toks/sets")
    assert [s["code"] for s in sets][-1] == "ttok"
    assert sets[-1]["total"] == 0 and sets[-1]["owned"] == 1


def test_new_cards_compare_with_the_same_collection(env):
    store, _ = env
    # A trade binder imported between the two imports of the main collection.
    write(store, "trade", "Trade binder", "2026-01-15T00:00:00+00:00",
          [row("id-other", "Other Card"), row("id-more", "More Card")])
    cards = {c["name"]: c for c in get("/api/collection/cur/search")["cards"]}
    assert cards["Bolt"]["new"] is True and cards["Gold Wurm"]["new"] is True
    assert cards["Elf"]["new"] is False
    # The trade binder itself has no earlier import of the same cards.
    assert get("/api/collection/trade/insights")["has_previous"] is False


def test_a_name_with_a_flag_word_is_still_found(env):
    store, _ = env
    write(store, "np", "Words", "2026-03-01T00:00:00+00:00",
          [row("id-np", "New Perspectives"), row("id-foil", "Foil")])
    assert names("/api/collection/np/search?q=new%20perspectives") == ["New Perspectives"]
    assert names("/api/collection/np/search?q=foil") == ["Foil"]

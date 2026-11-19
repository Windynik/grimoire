"""The card pool of the deck editor: one row per card name (see backend.decks.pool)."""

import json

import pytest
from fastapi.testclient import TestClient

from backend.api.dependencies import get_bulk_data_manager, get_collection_store, get_deck_store
from backend.core.collection_store import CollectionStore
from backend.decks.pool import group_by_name
from backend.decks.store import DeckStore
from main import app
from tests.forge.conftest import make_record
from tests.test_api import FakeBulk


def row(sid, name, qty=1, foil="normal"):
    return {"name": name, "scryfall_id": sid, "quantity": qty, "foil": foil, "value": float(qty)}


def test_group_by_name_adds_up_the_printings_and_picks_the_biggest_stack():
    rows = [row("isl-a", "Island", 4), row("bolt", "Bolt", 2), row("isl-a", "Island", 1, "foil"),
            row("isl-b", "Island", 2), row("isl-c", "Island", 6)]
    grouped = group_by_name(rows)
    assert [r["name"] for r in grouped] == ["Island", "Bolt"]
    island, bolt = grouped
    assert island["quantity"] == 13 and island["printings"] == 3
    assert island["scryfall_id"] == "isl-c"  # 6 copies beat 4 + 1 of isl-a
    assert island["value"] == 13.0
    assert bolt["quantity"] == 2 and bolt["printings"] == 1 and bolt["scryfall_id"] == "bolt"


def test_group_by_name_edge_cases():
    assert group_by_name([]) == []
    # A tie keeps the first printing; a string quantity counts.
    tie = group_by_name([row("a", "Forest", 2), row("b", "Forest", "2")])
    assert tie == [dict(row("a", "Forest", 2), quantity=4, printings=2, value=4.0)]
    # Unicode names group as they are written.
    jotun = group_by_name([row("j1", "Jötun Grunt", 1), row("j2", "Jötun Grunt", 3),
                           row("x", "Jotun Grunt", 1)])
    assert [(r["name"], r["quantity"], r["printings"], r["scryfall_id"]) for r in jotun] == [
        ("Jötun Grunt", 4, 2, "j2"), ("Jotun Grunt", 1, 1, "x")]
    # The input rows do not change.
    rows = [row("a", "Plains", 1), row("b", "Plains", 1)]
    group_by_name(rows)
    assert rows == [row("a", "Plains", 1), row("b", "Plains", 1)]


@pytest.fixture
def pool_env(tmp_path):
    store = CollectionStore(storage_dir=str(tmp_path / "collections"))
    index = {}
    for sid, set_code in (("isl-a", "aaa"), ("isl-b", "bbb"), ("isl-c", "ccc")):
        card = make_record("Island", "Basic Land — Island", "", "", ("U",), 0, produced=("U",))
        card.update(id=sid, set=set_code)
        index[sid] = card
    bolt = make_record("Bolt", "Instant", "{R}", "Deal 3.", ("R",), 1)
    index[bolt["id"]] = bolt
    cards = [row("isl-a", "Island", 4), row("isl-b", "Island", 2), row("isl-c", "Island", 6),
             row(bolt["id"], "Bolt", 1)]
    payload = {"meta": {"job_id": "cur", "name": "Current",
                        "created": "2026-02-01T00:00:00+00:00", "card_count": 13},
               "cards": cards}
    (store.storage_dir / "cur.json").write_text(json.dumps(payload))
    app.dependency_overrides[get_collection_store] = lambda: store
    app.dependency_overrides[get_bulk_data_manager] = lambda: FakeBulk(index)
    empty_decks = DeckStore(storage_dir=str(tmp_path / "no-decks"))
    app.dependency_overrides[get_deck_store] = lambda: empty_decks
    yield
    app.dependency_overrides.clear()


def test_owned_search_by_name_gives_one_row_per_card(pool_env):
    client = TestClient(app)
    body = client.get("/api/collection/cur/search?group=name&sort=name").json()
    assert body["total"] == 2
    assert [(c["name"], c["quantity"], c["printings"]) for c in body["cards"]] == [
        ("Bolt", 1, 1), ("Island", 12, 3)]
    assert body["cards"][1]["scryfall_id"] == "isl-c"
    # The paging counts the grouped rows.
    page = client.get("/api/collection/cur/search?group=name&sort=name&limit=1&offset=1").json()
    assert [c["name"] for c in page["cards"]] == ["Island"] and page["total"] == 2
    # Without the option the Collection screen keeps one row per printing.
    plain = client.get("/api/collection/cur/search").json()
    assert plain["total"] == 4 and "printings" not in plain["cards"][0]


def test_archive_search_by_name_gives_one_row_per_card(pool_env):
    client = TestClient(app)
    body = client.get("/api/cards/search?q=island&group=name").json()
    assert body["total"] == 1
    assert body["cards"][0]["name"] == "Island" and body["cards"][0]["printings"] == 3
    assert client.get("/api/cards/search?q=island").json()["total"] == 3

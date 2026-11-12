import json

from backend.core.collection_store import CollectionStore, copies_of


def _row(i, quantity):
    return {"Name": f"Card {i}", "Scryfall ID": f"id-{i}", "Quantity": quantity}


def test_the_card_count_is_the_number_of_copies(tmp_path):
    store = CollectionStore(str(tmp_path))
    bulk = {f"id-{i}": {"prices": {}} for i in range(4)}
    store.store_collection("job1", [_row(i, "4") for i in range(4)], bulk, source_name="Box.csv")
    assert [c["card_count"] for c in store.list_collections()] == [16]


def test_an_older_file_that_counted_rows_shows_copies(tmp_path):
    payload = {"meta": {"job_id": "old", "name": "Old", "created": "2026-01-01T00:00:00Z",
                        "card_count": 2},
               "cards": [{"name": "A", "quantity": 3}, {"name": "B", "quantity": "2"}]}
    (tmp_path / "old.json").write_text(json.dumps(payload))
    assert CollectionStore(str(tmp_path)).list_collections()[0]["card_count"] == 5


def test_copies_of_counts_a_bad_quantity_as_one():
    assert copies_of([{"quantity": "x"}, {"quantity": 2}, {}]) == 4


def test_each_card_keeps_its_binder(tmp_path):
    store = CollectionStore(str(tmp_path))
    rows = [dict(_row(0, "1"), **{"Binder Name": "Trade binder"}), _row(1, "2")]
    store.store_collection("job1", rows, {"id-0": {}, "id-1": {}}, source_name="Box.csv")
    assert [c["binder"] for c in store.get_collection("job1")] == ["Trade binder", ""]


def test_an_older_collection_takes_its_binders_from_the_original_rows(tmp_path):
    payload = {"meta": {"job_id": "old", "name": "Old", "created": "2026-01-01T00:00:00Z"},
               "cards": [{"name": "A", "scryfall_id": "id-a", "quantity": 1, "foil": "normal"}],
               "original": {"headers": ["Binder Name", "Name", "Scryfall ID", "Quantity", "Foil"],
                            "rows": [{"Binder Name": "Red", "Name": "A", "Scryfall ID": "id-a",
                                      "Quantity": "1", "Foil": "normal"}]}}
    (tmp_path / "old.json").write_text(json.dumps(payload))
    cards = CollectionStore(str(tmp_path)).cards_with_binders("old")
    assert [(c["name"], c["binder"]) for c in cards] == [("A", "Red")]
    assert CollectionStore(str(tmp_path)).cards_with_binders("missing") == []

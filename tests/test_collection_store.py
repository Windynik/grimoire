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


# --- rename and replace ---

def _stored(tmp_path, job_id="job1", name="Box.csv", rows=None):
    store = CollectionStore(str(tmp_path))
    rows = rows if rows is not None else [_row(0, "1"), _row(1, "2")]
    bulk = {r["Scryfall ID"]: {"prices": {"usd": "1.00"}} for r in rows}
    store.store_collection(job_id, rows, bulk, source_name=name,
                           original_headers=["Name", "Scryfall ID", "Quantity"], original_rows=rows)
    return store, bulk


def test_rename_changes_only_the_name(tmp_path):
    store, _ = _stored(tmp_path)
    before = store.list_collections()[0]
    meta = store.rename_collection("job1", "Trade binder · Grün ✓")
    assert meta["name"] == "Trade binder · Grün ✓"
    after = store.list_collections()[0]
    assert after["name"] == "Trade binder · Grün ✓"
    assert {k: v for k, v in after.items() if k != "name"} == {
        k: v for k, v in before.items() if k != "name"}
    assert [c["name"] for c in store.get_collection("job1")] == ["Card 0", "Card 1"]
    assert store.get_original("job1") is not None
    assert [p.name for p in tmp_path.iterdir()] == ["job1.json"], "no temporary file stays"


def test_rename_of_an_unknown_collection_is_none(tmp_path):
    store, _ = _stored(tmp_path)
    assert store.rename_collection("nope", "Name") is None
    assert [c["name"] for c in store.list_collections()] == ["Box"]


def test_rename_of_a_legacy_list_file_keeps_its_cards(tmp_path):
    (tmp_path / "legacy.json").write_text(json.dumps([{"name": "A", "quantity": 2}]))
    store = CollectionStore(str(tmp_path))
    assert store.rename_collection("legacy", "Old box")["name"] == "Old box"
    assert store.get_collection("legacy") == [{"name": "A", "quantity": 2}]
    listed = store.list_collections()[0]
    assert (listed["job_id"], listed["name"], listed["card_count"]) == ("legacy", "Old box", 2)


def test_replace_keeps_the_job_id_and_the_name_and_writes_the_new_cards(tmp_path):
    store, bulk = _stored(tmp_path)
    store.rename_collection("job1", "My binder")
    new_rows = [_row(5, "3")]
    bulk["id-5"] = {"prices": {"usd": "2.00"}}
    meta = store.replace_collection("job1", new_rows, bulk, original_headers=["Name"],
                                    original_rows=new_rows)
    assert (meta["job_id"], meta["name"], meta["card_count"]) == ("job1", "My binder", 3)
    assert [(c["job_id"], c["name"]) for c in store.list_collections()] == [("job1", "My binder")]
    assert [c["name"] for c in store.get_collection("job1")] == ["Card 5"]
    assert store.get_original("job1") == (["Name"], new_rows)
    # The cards before the replace stay as the previous import.
    assert [c["name"] for c in store.get_previous("job1")] == ["Card 0", "Card 1"]
    assert [p.name for p in tmp_path.iterdir()] == ["job1.json"], "no temporary file stays"


def test_a_second_replace_keeps_only_the_last_previous_import(tmp_path):
    store, bulk = _stored(tmp_path)
    bulk.update({"id-5": {}, "id-6": {}})
    store.replace_collection("job1", [_row(5, "1")], bulk)
    store.replace_collection("job1", [_row(6, "1")], bulk)
    assert [c["name"] for c in store.get_previous("job1")] == ["Card 5"]
    assert "previous" not in json.loads((tmp_path / "job1.json").read_text())["previous"][0]


def test_replace_of_an_unknown_collection_writes_nothing(tmp_path):
    store, bulk = _stored(tmp_path)
    assert store.replace_collection("nope", [_row(0, "1")], bulk) is None
    assert sorted(p.name for p in tmp_path.iterdir()) == ["job1.json"]


def test_a_collection_that_was_never_replaced_has_no_previous_import(tmp_path):
    store, _ = _stored(tmp_path)
    assert store.get_previous("job1") is None
    assert store.get_previous("nope") is None

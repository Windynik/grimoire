import dataclasses
import json

import pytest

from backend.decks.store import DeckStore
from backend.forge.builder import BuildPlan, BuiltDeck, DeckEntry
from backend.forge.export import decklist_text, deck_to_record
from backend.forge.graph import Backbone
from backend.forge.playbook import load_playbook
from tests.forge.conftest import hydrate_one, make_record


@pytest.fixture(scope="module")
def playbook():
    return load_playbook()


def _backbone():
    return Backbone(id="b", hooks=("death",), name="Aristocrats", members=[],
                    colors=frozenset("BG"), commander_id=None, score=1.0)


def _deck(playbook, fmt="commander"):
    rules = playbook.formats[fmt]
    chief = make_record("Chief", color_identity=("B", "G"), cmc=3, mana_cost="{1}{B}{G}")
    chief["game_changer"] = True
    bear = make_record("Bear", cmc=2)
    ring = make_record("Gem", type_line="Artifact", mana_cost="{1}", color_identity=(), cmc=1)
    ring["game_changer"] = True
    commander = hydrate_one(chief, rules)
    entries = [
        DeckEntry(card=hydrate_one(bear, rules), name="Bear", count=2, role="core",
                  reason="Own reason."),
        DeckEntry(card=hydrate_one(ring, rules), name="Gem", count=1, role="ramp",
                  reason="Ramp."),
        DeckEntry(card=None, name="Forest", count=3, role="basic", reason="Basic.", basic=True),
    ]
    plan = BuildPlan(backbone=_backbone(), playstyle="midrange", commander=commander)
    return BuiltDeck(fmt=rules, plan=plan, entries=entries, land_target=3,
                     warnings=["warn"], notes=["note"])


def _record(playbook, **kw):
    info = {"thesis": "Sacrifice things.",
            "key_interactions": [{"cards": ["Bear", "Gem"], "why": "Fun."}]}
    return deck_to_record(_deck(playbook, **kw), "My Deck", "job1", info, "# Why",
                          {"Bear": "Model reason."}, {"synergy_density": 0.5})


def test_deck_to_record_counts_and_commander_outside_main(playbook):
    rec = _record(playbook)
    assert rec["format"] == "commander" and rec["collection_job_id"] == "job1"
    assert rec["commander"]["name"] == "Chief"
    main = rec["sections"]["main"]
    assert [m["name"] for m in main] == ["Bear", "Gem", "Forest"]
    assert sum(m["count"] for m in main) == 6
    bear, gem, forest = main
    assert bear["reason"] == "Model reason." and gem["reason"] == "Ramp."
    assert bear["scryfall_id"] == "id-bear" and not bear["basic"]
    assert forest["scryfall_id"] is None and forest["basic"] is True
    assert forest["type_line"] == "Basic Land — Forest" and forest["cmc"] == 0
    assert forest["image_url"] == "" and forest["mana_cost"] == ""
    assert rec["sections"]["sideboard"] == [] and rec["sections"]["maybeboard"] == []
    assert rec["backbone"]["name"] == "Aristocrats" and rec["backbone"]["hooks"] == ["death"]
    assert rec["backbone"]["playstyle"] == "midrange"
    assert rec["backbone"]["thesis"] == "Sacrifice things."
    assert rec["game_changers"] == 2  # Gem plus the commander
    assert rec["curve"]["2"] == 2 and rec["curve"]["1"] == 1
    assert rec["warnings"] == ["warn"] and rec["notes"] == ["note"]
    assert rec["explanation"] == "# Why" and rec["metrics"] == {"synergy_density": 0.5}


def test_deck_to_record_without_commander(playbook):
    deck = _deck(playbook, "modern")
    deck = dataclasses.replace(deck, plan=dataclasses.replace(deck.plan, commander=None))
    rec = deck_to_record(deck, "D", "j", {}, "", {}, {})
    assert rec["commander"] is None and rec["game_changers"] == 1


def test_save_get_list_roundtrip(tmp_path, playbook):
    store = DeckStore(str(tmp_path / "decks"))
    rec = _record(playbook)
    deck_id = store.save(rec)
    first = store.get(deck_id)
    assert first["id"] == deck_id and first["created"] and first["updated"]
    created = first["created"]
    first["name"] = "Renamed"
    store.save(first)
    again = store.get(deck_id)
    assert again["created"] == created and again["name"] == "Renamed"
    assert again["updated"] >= created
    other = store.save(_record(playbook))
    rows = store.list()
    assert {r["id"] for r in rows} == {deck_id, other}
    row = next(r for r in rows if r["id"] == deck_id)
    assert row["name"] == "Renamed" and row["format"] == "commander"
    assert row["commander"] == "Chief" and row["count"] == 7
    assert [r["updated"] for r in rows] == sorted((r["updated"] for r in rows), reverse=True)


def test_rejects_bad_ids(tmp_path):
    store = DeckStore(str(tmp_path))
    for bad in ("../x", "A1", "a/b", "", "x.json"):
        assert store.get(bad) is None
    assert store.get("abc-123") is None


def test_decklist_text_sections(playbook):
    rec = _record(playbook)
    assert decklist_text(rec) == "Commander\n1 Chief\n\nDeck\n2 Bear\n1 Gem\n3 Forest"
    rec["commander"] = None
    rec["sections"]["sideboard"] = [{"name": "Side", "count": 2}]
    assert decklist_text(rec) == ("Deck\n2 Bear\n1 Gem\n3 Forest\n\nSideboard\n2 Side")


def test_corrupt_file_is_skipped(tmp_path, playbook):
    store = DeckStore(str(tmp_path))
    good = store.save(_record(playbook))
    (tmp_path / "abc-123.json").write_text("{not json", encoding="utf-8")
    assert store.get("abc-123") is None
    assert [r["id"] for r in store.list()] == [good]


def test_save_rejects_bad_id_and_leaves_no_temp_files(tmp_path, playbook):
    store = DeckStore(str(tmp_path))
    rec = _record(playbook)
    rec["id"] = "../evil"
    with pytest.raises(ValueError):
        store.save(rec)
    store.save(_record(playbook))
    assert [p.suffix for p in tmp_path.iterdir()] == [".json"]


def test_non_dict_json_is_skipped(tmp_path, playbook):
    store = DeckStore(str(tmp_path))
    good = store.save(_record(playbook))
    for name, text in (("aa-1", "[]"), ("aa-2", '"x"'), ("aa-3", "null")):
        (tmp_path / f"{name}.json").write_text(text, encoding="utf-8")
        assert store.get(name) is None
    assert [r["id"] for r in store.list()] == [good]


def test_list_tolerates_odd_fields(tmp_path, playbook):
    store = DeckStore(str(tmp_path))
    rec = _record(playbook)
    rec["updated"] = None
    rec["sections"]["main"].append("junk")
    path = tmp_path / "bb-1.json"
    rec["id"] = "bb-1"
    path.write_text(json.dumps(rec), encoding="utf-8")
    other = store.save(_record(playbook))
    rows = store.list()
    assert [r["id"] for r in rows][0] == other
    assert next(r for r in rows if r["id"] == "bb-1")["count"] == 7


def test_delete_removes_file_and_rejects_bad_id(tmp_path, playbook):
    store = DeckStore(str(tmp_path))
    deck_id = store.save(_record(playbook))
    assert store.delete(deck_id) is True
    assert store.get(deck_id) is None
    assert store.delete(deck_id) is False
    assert store.delete("../x") is False


def test_duplicate_copies_with_new_id_and_name(tmp_path, playbook):
    store = DeckStore(str(tmp_path))
    deck_id = store.save(_record(playbook))
    original = store.get(deck_id)
    new_id = store.duplicate(deck_id)
    assert new_id and new_id != deck_id
    copy = store.get(new_id)
    assert copy["name"] == "My Deck (copy)" and copy["id"] == new_id
    assert copy["sections"] == original["sections"]
    assert copy["created"] >= original["created"]
    assert store.get(deck_id)["name"] == "My Deck"
    assert store.duplicate("nope-1") is None
    assert store.duplicate("../x") is None


def test_duplicate_of_a_long_name_fits_the_name_limit(tmp_path, playbook):
    store = DeckStore(str(tmp_path))
    record = _record(playbook)
    record["name"] = "A" * 120
    copy = store.get(store.duplicate(store.save(record)))
    assert len(copy["name"]) <= 120
    assert copy["name"].endswith(" (copy)")


def test_list_summary_has_image_and_job(tmp_path, playbook):
    store = DeckStore(str(tmp_path))
    rec = _record(playbook)
    rec["commander"]["image_url"] = "http://img/chief"
    with_commander = store.save(rec)
    rec = _record(playbook, fmt="modern")
    rec["commander"] = None
    rec["sections"]["main"][1]["image_url"] = "http://img/gem"
    without = store.save(rec)
    rec = _record(playbook, fmt="modern")
    rec["commander"] = None
    bare = store.save(rec)
    rows = {r["id"]: r for r in store.list()}
    assert rows[with_commander]["image_url"] == "http://img/chief"
    assert rows[without]["image_url"] == "http://img/gem"
    assert rows[bare]["image_url"] == ""
    # The art card's id and name let the page ask for the stored image.
    assert rows[with_commander]["image_id"] == "id-chief"
    assert rows[with_commander]["image_name"] == "Chief"
    assert rows[without]["image_id"] == "id-gem"
    assert rows[without]["image_name"] == "Gem"
    assert rows[bare]["image_id"] == "" and rows[bare]["image_name"] == ""
    assert rows[bare]["collection_job_id"] == "job1"


def test_deck_to_record_has_size_and_copies(playbook):
    rec = _record(playbook)
    assert rec["deck_size"] == playbook.formats["commander"].deck_size
    assert rec["max_copies"] == playbook.formats["commander"].max_copies

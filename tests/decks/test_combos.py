from backend.decks.brackets import bracket_facts
from backend.decks.combos import cards_key, combo_facts, request_body, summarize
from tests.forge.conftest import make_record


def use(name):
    return {"card": {"name": name}, "quantity": 1}


def combo(cid, names, produces=("Win the game",), tag="R", popularity=100, requires=()):
    """A find-my-combos result, in the shape of Commander Spellbook's answer."""
    return {"id": cid, "uses": [use(n) for n in names], "requires": list(requires),
            "produces": [{"feature": {"name": p}} for p in produces],
            "description": "Step one.\nStep two.", "manaNeeded": "{U}{U}{B}",
            "bracketTag": tag, "popularity": popularity}


def deck(main, commander=None, fmt="commander"):
    return {"format": fmt, "commander": commander,
            "sections": {"main": [{"name": n, "count": 1, "scryfall_id": None} for n in main]
                         + [{"name": "Island", "count": 30, "basic": True}],
                         "sideboard": [], "maybeboard": []}}


RESULTS = {
    "included": [
        combo("742-1295", ["Demonic Consultation", "Thassa's Oracle"]),
        combo("1-2-3", ["Card A", "Card B", "Card C"], produces=("Infinite mana",), tag="P"),
    ],
    "almostIncluded": [
        combo("9-10", ["Thassa's Oracle", "Tainted Pact"], tag="R", popularity=900),
        combo("5-6-7", ["Card A", "Missing One", "Missing Two"], tag="S", popularity=5000),
    ],
}


def test_the_request_sends_names_only_and_skips_basics():
    record = deck(["Thassa's Oracle"], commander={"name": "Tasha", "scryfall_id": "x"})
    assert request_body(record) == {"main": [{"card": "Thassa's Oracle", "quantity": 1}],
                                    "commanders": [{"card": "Tasha", "quantity": 1}]}


def test_the_summary_lists_the_combos_and_the_missing_cards():
    record = deck(["Demonic Consultation", "Thassa's Oracle", "Card A", "Card B", "Card C"])
    summary = summarize(RESULTS, record, at="2026-11-14T10:00:00+00:00")
    first = summary["included"][0]
    assert first["cards"] == ["Demonic Consultation", "Thassa's Oracle"]
    assert first["two_card"] and first["tag_label"] == "Ruthless"
    assert first["produces"] == ["Win the game"]
    assert first["url"] == "https://commanderspellbook.com/combo/742-1295/"
    assert not summary["included"][1]["two_card"]
    # One card away comes before two cards away.
    assert [c["missing"] for c in summary["almost"]] == [["Tainted Pact"], ["Missing One", "Missing Two"]]
    assert summary["key"] == cards_key(record)


def test_combos_raise_the_bracket_floor_and_a_changed_deck_is_stale():
    chief = make_record("Chief", type_line="Legendary Creature — Elf")
    index = {chief["id"]: chief}
    record = deck(["Demonic Consultation", "Thassa's Oracle"],
                  commander={"name": "Chief", "scryfall_id": chief["id"]})
    before = bracket_facts(record, index)
    assert before["floor"] == 2 and before["combos"] is None
    assert any("Find combos" in note for note in before["notes"])
    record["combos"] = summarize(RESULTS, record)
    facts = bracket_facts(record, index)
    assert facts["floor"] == 4
    assert facts["reasons"] == [
        "Two-card combo (Demonic Consultation + Thassa's Oracle): bracket 3 or higher.",
        "Ruthless combo (Demonic Consultation + Thassa's Oracle): bracket 4 or higher."]
    assert facts["notes"][-1] == "Combos from Commander Spellbook: 2 in the deck."
    record["sections"]["main"].append({"name": "Sol Ring", "count": 1})
    assert combo_facts(record)["stale"] is True
    assert bracket_facts(record, index)["notes"][-1] == (
        "The deck changed after the last combo check. Press Find combos again.")

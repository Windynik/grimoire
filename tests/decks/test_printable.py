from backend.decks.printable import decklist_page, rule_zero_page
from backend.decks.rulezero import rule_zero
from tests.forge.conftest import make_record

BOLT = make_record("Lightning Bolt", type_line="Instant", mana_cost="{R}")
GOBLIN = make_record("Goblin Guide", type_line="Creature — Goblin Scout", mana_cost="{R}")
MOUNTAIN = make_record("Mountain", type_line="Basic Land — Mountain", mana_cost="")
INDEX = {c["id"]: c for c in (BOLT, GOBLIN, MOUNTAIN)}


def line(card, count):
    return {"scryfall_id": card["id"], "name": card["name"], "count": count}


RECORD = {
    "name": "Red <Rush>", "format": "modern", "commander": None,
    "backbone": {"name": "Aggro", "thesis": "Burn them out fast."},
    "sections": {"main": [line(BOLT, 4), line(GOBLIN, 4), line(MOUNTAIN, 20)],
                 "sideboard": [{"scryfall_id": None, "name": "Smash to Smithereens", "count": 3}],
                 "maybeboard": []},
}


def test_the_rule_zero_card_names_the_bracket_facts_and_the_combos():
    analysis = {"format": {"name": "Commander"}, "count": {"main": 100}, "price": 412.4,
                "bracket": {"floor": 3, "floor_name": "Upgraded",
                            "reasons": ["1 Game Changer: bracket 3 or higher."],
                            "game_changers": ["Rhystic Study"], "mass_land_denial": [],
                            "extra_turns": [], "tutors": ["Demonic Tutor"]}}
    record = dict(RECORD, name="Tasha", commander={"name": "Tasha, the Witch Queen"},
                  combos={"included": [{"cards": ["A", "B"], "produces": ["Win the game"]}]})
    card = rule_zero(record, analysis)
    assert card["lines"] == ["Commander · Tasha, the Witch Queen", "Bracket 3 or higher (Upgraded)",
                             "Plan: Aggro — Burn them out fast.", "100 cards · about $412"]
    titles = {s["title"]: s["items"] for s in card["sections"]}
    assert titles["Game Changers"] == ["Rhystic Study"]
    assert titles["Combos"] == ["A + B (Win the game)"]
    assert titles["Mass land denial"] == ["None"]
    assert "Why this bracket: 1 Game Changer: bracket 3 or higher." in card["text"]
    unchecked = rule_zero(dict(record, combos=None), analysis)
    assert {s["title"]: s["items"] for s in unchecked["sections"]}["Combos"] == [
        "Not checked yet (press Find combos)"]


def test_the_pages_escape_every_name():
    card = rule_zero(RECORD, {"format": {"name": "Modern"}})
    html = rule_zero_page(card)
    assert "Red &lt;Rush&gt;" in html and "<Rush>" not in html
    sheet = decklist_page(RECORD, INDEX, {"player": "<b>Ann</b>"}, "Modern")
    assert "&lt;b&gt;Ann&lt;/b&gt;" in sheet and "<b>Ann</b>" not in sheet


def test_the_decklist_groups_the_cards_and_counts_them():
    sheet = decklist_page(RECORD, INDEX, {}, "Modern")
    assert "<h2>Creatures (4)</h2>" in sheet
    assert "<h2>Other spells (4)</h2>" in sheet
    assert "<h2>Lands (20)</h2>" in sheet
    assert "<h2>Sideboard (3)</h2>" in sheet
    assert "Main deck: 28 cards · Sideboard: 3 cards" in sheet
    assert sheet.index("Goblin Guide") < sheet.index("Lightning Bolt") < sheet.index("Mountain")

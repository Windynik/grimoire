from backend.decks.brackets import (
    bracket_facts, is_extra_turn, is_mass_land_denial, is_tutor,
)
from tests.forge.conftest import make_record

TEXTS = {
    "Armageddon": "Destroy all lands.",
    "Blood Moon": "Nonbasic lands are Mountains.",
    "Winter Orb": "As long as Winter Orb is untapped, players can't untap more than one land "
                  "during their untap steps.",
    "Jokulhaups": "Destroy all artifacts, creatures, and lands. They can't be regenerated.",
    "Sunder": "Return all lands to their owners' hands.",
    "Urborg": "Each land is a Swamp in addition to its other land types.",
    "Ajani": "\u22127: Destroy all lands target player controls.",
    "Rubble": "Up to three target lands don't untap during their controller's next untap step.",
    "Time Warp": "Target player takes an extra turn after this one.",
    "Ugin's Nexus": "If a player would begin an extra turn, that player skips that turn instead.",
    "Demonic Tutor": "Search your library for a card, put that card into your hand, "
                     "then shuffle.",
    "Rampant Growth": "Search your library for a basic land card, put that card onto the "
                      "battlefield tapped, then shuffle.",
    "Worldly Tutor": "Search your library for a creature card, reveal it, then shuffle and "
                     "put the card on top.",
}


def card(name, **extra):
    return make_record(name, oracle_text=TEXTS.get(name, ""), **extra)


def test_mass_land_denial_reads_the_rules_text():
    hits = {name for name in TEXTS if is_mass_land_denial(card(name))}
    assert hits == {"Armageddon", "Blood Moon", "Winter Orb", "Jokulhaups", "Sunder"}


def test_extra_turns_and_tutors():
    assert is_extra_turn(card("Time Warp")) and not is_extra_turn(card("Ugin's Nexus"))
    assert is_tutor(card("Demonic Tutor")) and is_tutor(card("Worldly Tutor"))
    assert not is_tutor(card("Rampant Growth"))


def _deck(cards, fmt="commander"):
    chief = make_record("Chief", type_line="Legendary Creature — Elf")
    index = {c["id"]: c for c in cards + [chief]}
    record = {"format": fmt, "commander": {"scryfall_id": chief["id"], "name": "Chief"},
              "sections": {"main": [{"scryfall_id": c["id"], "name": c["name"], "count": 1}
                                    for c in cards], "sideboard": [], "maybeboard": []}}
    return record, index


def changers(number):
    cards = []
    for i in range(number):
        c = make_record("Changer %d" % i)
        c["game_changer"] = True
        cards.append(c)
    return cards


def test_a_plain_deck_is_bracket_one_or_two():
    facts = bracket_facts(*_deck([card("Demonic Tutor"), card("Time Warp")]))
    assert facts["floor"] == 2 and facts["floor_name"] == "Core"
    assert facts["reasons"] == []
    assert facts["tutors"] == ["Demonic Tutor"] and facts["extra_turns"] == ["Time Warp"]
    assert any("Bracket 1 or 2" in note for note in facts["notes"])
    assert any("two-card combos" in note for note in facts["notes"])


def test_game_changers_and_land_denial_raise_the_floor():
    assert bracket_facts(*_deck(changers(3)))["floor"] == 3
    four = bracket_facts(*_deck(changers(4)))
    assert four["floor"] == 4
    assert four["reasons"] == ["4 Game Changers: more than 3, so bracket 4 or higher."]
    one = bracket_facts(*_deck(changers(1)))
    assert one["reasons"] == ["1 Game Changer: bracket 3 or higher."]
    denial = bracket_facts(*_deck([card("Armageddon")]))
    assert denial["floor"] == 4 and denial["mass_land_denial"] == ["Armageddon"]


def test_two_extra_turn_cards_get_a_note_and_other_formats_get_no_facts():
    turns = [card("Time Warp"), make_record("Walk", oracle_text="You take two extra turns.")]
    facts = bracket_facts(*_deck(turns))
    assert facts["floor"] == 2
    assert facts["notes"][0] == "2 extra-turn cards. Brackets 1 to 3 do not chain extra turns."
    assert bracket_facts(*_deck(turns, fmt="brawl")) is None

"""The facts of the deck list: colors, price and the owned share of a deck."""

from backend.decks.analysis import analyze, list_facts
from tests.forge.conftest import make_record

META = {"job_id": "c1", "name": "Mine"}


def _line(record, count):
    return {"scryfall_id": record["id"], "name": record["name"], "count": count}


def _deck(main, fmt="modern", commander=None, sideboard=None):
    return {"name": "Test", "format": fmt, "commander": commander, "backbone": None,
            "collection_job_id": "c1",
            "sections": {"main": main, "sideboard": sideboard or [], "maybeboard": []}}


def _priced(name, usd, **kw):
    record = make_record(name, **kw)
    record["prices"]["usd"] = usd
    return record


def test_every_owned_copy_gives_100_percent(playbook):
    bear = _priced("Bear", "1.50")
    index = {bear["id"]: bear}
    analysis = analyze(_deck([_line(bear, 4)]), index, [{"scryfall_id": bear["id"], "quantity": 4}],
                       META, playbook)
    assert analysis["owned_percent"] == 100
    assert list_facts(analysis) == {"colors": ["G"], "price": 6.0, "owned_percent": 100}


def test_missing_copies_lower_the_share_and_it_rounds_down(playbook):
    bear = make_record("Bear")
    elf = make_record("Elf")
    index = {bear["id"]: bear, elf["id"]: elf}
    rows = [{"scryfall_id": bear["id"], "quantity": 2}]  # 2 of 3 bears, no elf
    analysis = analyze(_deck([_line(bear, 3), _line(elf, 3)]), index, rows, META, playbook)
    assert analysis["owned_percent"] == 33  # 2 of 6 copies, not 34


def test_basic_lands_count_as_owned_and_unknown_cards_do_not(playbook):
    bear = make_record("Bear")
    index = {bear["id"]: bear}
    main = [_line(bear, 1), {"scryfall_id": None, "name": "Forest", "count": 2, "basic": True},
            {"scryfall_id": "gone", "name": "Lost Card", "count": 1}]
    rows = [{"scryfall_id": bear["id"], "quantity": 1}]
    assert analyze(_deck(main), index, rows, META, playbook)["owned_percent"] == 75


def test_two_printings_share_the_owned_copies_of_the_card(playbook):
    old = make_record("Bear")
    new = dict(make_record("Bear"), id="id-bear-2")  # the same oracle id
    index = {old["id"]: old, new["id"]: new}
    rows = [{"scryfall_id": old["id"], "quantity": 2}]
    analysis = analyze(_deck([_line(old, 2), _line(new, 2)]), index, rows, META, playbook)
    assert analysis["owned_percent"] == 50


def test_the_commander_counts_and_the_sideboard_does_not(playbook):
    chief = make_record("Chief, the Leader", type_line="Legendary Creature — Elf",
                        color_identity=("G", "U"))
    bear = make_record("Bear")
    index = {chief["id"]: chief, bear["id"]: bear}
    record = _deck([_line(bear, 1)], fmt="commander", sideboard=[_line(bear, 3)],
                   commander={"scryfall_id": chief["id"], "name": chief["name"]})
    rows = [{"scryfall_id": bear["id"], "quantity": 1}]
    analysis = analyze(record, index, rows, META, playbook)
    assert analysis["owned_percent"] == 50
    assert list_facts(analysis)["colors"] == ["U", "G"]


def test_an_empty_deck_or_no_collection_has_no_share(playbook):
    bear = make_record("Bear")
    index = {bear["id"]: bear}
    assert analyze(_deck([]), index, [], META, playbook)["owned_percent"] is None
    assert analyze(_deck([_line(bear, 1)]), index, None, None, playbook)["owned_percent"] is None

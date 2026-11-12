from backend.decks.pull import pull_list
from tests.forge.conftest import make_record


def printing(record, card_id, set_code, number):
    """Another printing of a card: a new Scryfall id with the same oracle id."""
    return dict(record, id=card_id, set=set_code, collector_number=number)


def owned(card, quantity, binder="", foil="normal"):
    return {"name": card["name"], "scryfall_id": card["id"], "quantity": quantity,
            "foil": foil, "binder": binder}


def line(card, count):
    return {"scryfall_id": card["id"], "name": card["name"], "count": count}


BOLT = make_record("Lightning Bolt", mana_cost="{R}", color_identity=("R",))
BOLT_2XM = printing(BOLT, "bolt-2xm", "2xm", "129")
SOL = make_record("Sol Ring", type_line="Artifact", mana_cost="{1}")
KRENKO = make_record("Krenko, Mob Boss", type_line="Legendary Creature — Goblin")
INDEX = {c["id"]: c for c in (BOLT, BOLT_2XM, SOL, KRENKO)}


def deck(main, sideboard=(), commander=None, job="main-box"):
    return {"collection_job_id": job, "commander": commander,
            "sections": {"main": list(main), "sideboard": list(sideboard), "maybeboard": [
                line(SOL, 1)]}}


def test_cards_come_from_their_binders_grouped_and_counted():
    collections = [
        ({"job_id": "main-box", "name": "Main box"},
         [owned(BOLT, 2, "Red binder"), owned(SOL, 1, "Artifacts")]),
        ({"job_id": "trade", "name": "Trade box"}, [owned(BOLT_2XM, 4, "Trades")]),
    ]
    record = deck([line(BOLT, 4), line(SOL, 1),
                   {"scryfall_id": None, "name": "Mountain", "count": 18, "basic": True}],
                  commander={"scryfall_id": KRENKO["id"], "name": KRENKO["name"]})
    result = pull_list(record, INDEX, collections)
    groups = [(g["collection"], g["binder"], g["count"],
               [(c["name"], c["count"], c["set"], c["printing"]) for c in g["cards"]])
              for g in result["groups"]]
    # The deck's own collection comes first; the same printing before reprints.
    assert groups == [
        ("Main box", "Artifacts", 1, [("Sol Ring", 1, SOL["set"].upper(), True)]),
        ("Main box", "Red binder", 2, [("Lightning Bolt", 2, BOLT["set"].upper(), True)]),
        ("Trade box", "Trades", 2, [("Lightning Bolt", 2, "2XM", False)]),
    ]
    assert result["basics"] == [{"name": "Mountain", "count": 18}]
    # The commander is not owned; the maybeboard Sol Ring is not pulled.
    assert result["missing"] == [{"name": "Krenko, Mob Boss", "count": 1}]


def test_one_owned_copy_is_not_pulled_twice():
    collections = [({"job_id": "main-box", "name": "Main box"}, [owned(BOLT, 3)])]
    record = deck([line(BOLT, 2)], sideboard=[line(BOLT_2XM, 2)])
    result = pull_list(record, INDEX, collections)
    assert result["groups"][0]["count"] == 3
    assert result["missing"] == [{"name": "Lightning Bolt", "count": 1}]


def test_foil_and_normal_copies_stay_apart():
    collections = [({"job_id": "main-box", "name": "Main box"},
                    [owned(BOLT, 1, "Binder", foil="foil"), owned(BOLT, 1, "Binder")])]
    cards = pull_list(deck([line(BOLT, 2)]), INDEX, collections)["groups"][0]["cards"]
    assert sorted((c["foil"], c["count"]) for c in cards) == [("foil", 1), ("normal", 1)]


def test_a_deck_with_nothing_owned_lists_every_card_as_missing():
    result = pull_list(deck([line(BOLT, 4)]), INDEX, [])
    assert result == {"groups": [], "basics": [],
                      "missing": [{"name": "Lightning Bolt", "count": 4}]}

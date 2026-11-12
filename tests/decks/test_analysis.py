from backend.decks.analysis import analyze, owned_counts, rules_for
from tests.forge.conftest import make_record

LEGAL_ALL = ("commander", "modern", "pauper", "standard")


def _pool(*records):
    return {r["id"]: r for r in records}


def _line(record, count):
    return {"scryfall_id": record["id"], "name": record["name"], "count": count}


def _forest(count):
    return {"scryfall_id": None, "name": "Forest", "count": count, "basic": True}


def _deck(main, fmt="modern", sideboard=None, maybeboard=None, commander=None, **extra):
    record = {"name": "Test", "format": fmt, "commander": commander, "backbone": None,
              "collection_job_id": "c1",
              "sections": {"main": main, "sideboard": sideboard or [],
                           "maybeboard": maybeboard or []}}
    record.update(extra)
    return record


def _rows(index, quantity=4):
    return [{"scryfall_id": i, "quantity": quantity} for i in index]


META = {"job_id": "c1", "name": "Mine"}


def _run(record, index, playbook, rows="all", meta=META):
    rows = _rows(index) if rows == "all" else rows
    return analyze(record, index, rows, meta, playbook)


def test_analysis_counts_curve_price_and_game_changers(playbook):
    cheap = make_record("Cheap Bear", cmc=2)
    cheap["prices"]["usd"] = "1.50"
    big = make_record("Big Wurm", mana_cost="{3}{G}{G}", cmc=5)
    big["prices"]["usd"] = "10.00"
    big["game_changer"] = True
    index = _pool(cheap, big)
    record = _deck([_line(cheap, 4), _line(big, 2), _forest(20)])
    result = _run(record, index, playbook)
    assert result["count"] == {"main": 26, "sideboard": 0, "maybeboard": 0, "target": 60}
    assert result["curve"]["2"] == 4 and result["curve"]["5"] == 2
    assert result["price"] == 26.0
    assert result["game_changers"] == 2
    assert result["colors"] == ["G"]
    assert result["collection"] == {"job_id": "c1", "name": "Mine"}
    assert result["format"]["key"] == "modern" and result["format"]["max_copies"] == 4
    assert result["metrics"]["combined"] >= 0


def test_analysis_entry_issues(playbook):
    owned_two = make_record("Two Owned")
    unowned = make_record("Unowned")
    banned = make_record("Banned One")
    banned["legalities"]["modern"] = "banned"
    illegal = make_record("Illegal One", legal=("commander",))
    token = make_record("Goblin Token", type_line="Token Creature — Goblin", layout="token")
    index = _pool(owned_two, unowned, banned, illegal, token)
    rows = [{"scryfall_id": owned_two["id"], "quantity": "2"},
            {"scryfall_id": banned["id"], "quantity": 4},
            {"scryfall_id": illegal["id"], "quantity": 4},
            {"scryfall_id": token["id"], "quantity": 4}]
    record = _deck([_line(owned_two, 4), _line(unowned, 1), _line(banned, 1),
                    _line(illegal, 1), _line(token, 1),
                    {"scryfall_id": "missing", "name": "Ghost", "count": 1}])
    cards = _run(record, index, playbook, rows)["cards"]
    assert cards[owned_two["id"]]["issues"] == ["short"]
    assert cards[owned_two["id"]]["owned"] == 2
    assert cards[unowned["id"]]["issues"] == ["not_owned"]
    assert "banned" in cards[banned["id"]]["issues"]
    assert "not_legal" in cards[illegal["id"]]["issues"]
    assert cards[token["id"]]["issues"] == ["not_a_card"]
    assert cards["missing"]["issues"] == ["not_a_card"]


def test_analysis_too_many_and_exemptions(playbook):
    bear = make_record("Bear")
    forest = make_record("Forest", type_line="Basic Land — Forest", mana_cost="", cmc=0,
                         produced=("G",))
    swarm = make_record("Swarm", oracle_text="A deck can have any number of cards named Swarm.")
    index = _pool(bear, forest, swarm)
    rows = _rows(index, 40)
    record = _deck([_line(bear, 5), _line(forest, 30), _line(swarm, 9), _forest(2)])
    cards = _run(record, index, playbook, rows)["cards"]
    assert cards[bear["id"]]["issues"] == ["too_many"]
    assert cards[forest["id"]]["issues"] == []
    assert cards[swarm["id"]]["issues"] == []
    assert cards["basic:Forest"] == {"owned": 2, "issues": [], "reasons": {}, "roles": []}
    assert cards[bear["id"]]["reasons"] == {
        "too_many": "Modern allows 4 copies of a card. This deck has 5."}


def test_analysis_maybeboard_only_not_a_card(playbook):
    bear = make_record("Bear")
    token = make_record("Goblin Token", type_line="Token Creature — Goblin", layout="token")
    index = _pool(bear, token)
    record = _deck([], maybeboard=[_line(bear, 1), _line(token, 1)])
    cards = _run(record, index, playbook, rows=[])["cards"]
    assert cards[bear["id"]]["issues"] == []
    assert cards[token["id"]]["issues"] == ["not_a_card"]


def test_analysis_off_color_only_in_commander_formats(playbook):
    chief = make_record("Green Chief", type_line="Legendary Creature — Elf",
                        legal=("commander",))
    red = make_record("Red Bolt", type_line="Instant", mana_cost="{R}",
                      color_identity=("R",), cmc=1, legal=("commander", "modern"))
    green = make_record("Green Bear", legal=("commander", "modern"))
    index = _pool(chief, red, green)
    commander = {"scryfall_id": chief["id"], "name": chief["name"]}
    record = _deck([_line(red, 1), _line(green, 1)], fmt="commander", commander=commander)
    cards = _run(record, index, playbook)["cards"]
    assert cards[red["id"]]["issues"] == ["off_color"]
    assert cards[green["id"]]["issues"] == []
    assert cards[chief["id"]]["issues"] == []
    modern = _run(_deck([_line(red, 1), _line(green, 1)]), index, playbook)["cards"]
    assert "off_color" not in modern[red["id"]]["issues"]


def test_analysis_mana_sources_and_issue(playbook):
    spell = make_record("Greedy", mana_cost="{G}{G}{G}{G}{G}", cmc=5)
    index = _pool(spell)
    record = _deck([_line(spell, 2), _forest(8)])
    result = _run(record, index, playbook)
    primary = playbook.formats["modern"].color_sources["primary"]
    assert result["mana"] == [{"color": "G", "pips": 10, "sources": 8, "needed": primary}]
    assert [i["code"] for i in result["issues"] if i["code"] == "mana"] == ["mana"]


def test_analysis_size_and_no_commander_issues(playbook):
    bear = make_record("Bear", legal=LEGAL_ALL)
    index = _pool(bear)
    short = _run(_deck([_line(bear, 4)]), index, playbook)
    assert {"code": "size", "message": "4 of 60 cards"} in short["issues"]
    over = _run(_deck([_line(bear, 4), _forest(60)]), index, playbook)
    assert not [i for i in over["issues"] if i["code"] == "size"]
    edh = _run(_deck([_line(bear, 1)], fmt="commander"), index, playbook)
    codes = [i["code"] for i in edh["issues"]]
    assert "no_commander" in codes and "size" in codes
    assert {"code": "no_commander", "message": "Choose a commander."} in edh["issues"]
    full = _run(_deck([_forest(100)], fmt="commander"), index, playbook)
    assert not [i for i in full["issues"] if i["code"] == "size"]
    over_edh = _run(_deck([_forest(101)], fmt="commander"), index, playbook)
    assert [i["code"] for i in over_edh["issues"] if i["code"] == "size"] == ["size"]


def test_analysis_commander_counts_in_main(playbook):
    chief = make_record("Green Chief", type_line="Legendary Creature — Elf",
                        legal=("commander",))
    chief["game_changer"] = True
    chief["prices"]["usd"] = "3.00"
    index = _pool(chief)
    commander = {"scryfall_id": chief["id"], "name": chief["name"]}
    result = _run(_deck([_forest(99)], fmt="commander", commander=commander), index, playbook)
    assert result["count"]["main"] == 100
    assert result["game_changers"] == 1 and result["price"] == 3.0
    assert result["colors"] == ["G"]
    assert not [i for i in result["issues"] if i["code"] in ("size", "no_commander")]


def test_analysis_unknown_card_does_not_crash(playbook):
    bear = make_record("Bear")
    index = _pool(bear)
    record = _deck([_line(bear, 4), {"scryfall_id": "nope", "name": "Ghost", "count": 2}])
    result = _run(record, index, playbook)
    assert result["cards"]["nope"]["issues"] == ["not_a_card"]
    assert result["metrics"]
    assert result["count"]["main"] == 6


def test_analysis_without_collection(playbook):
    bear = make_record("Bear")
    index = _pool(bear)
    record = _deck([_line(bear, 4), _forest(10)])
    result = analyze(record, index, None, None, playbook)
    assert result["collection"] == {"job_id": None, "name": ""}
    assert result["cards"][bear["id"]]["issues"] == ["not_owned"]
    assert result["cards"]["basic:Forest"]["issues"] == []


def test_analysis_empty_deck_has_no_metrics(playbook):
    result = analyze(_deck([_forest(10)]), {}, None, None, playbook)
    assert result["metrics"] == {} and result["mana"] == []
    assert result["curve"] == {"0": 0, "1": 0, "2": 0, "3": 0, "4": 0, "5": 0, "6+": 0}


def test_casual_rules_use_record_size(playbook):
    fmt = rules_for({"format": "casual", "deck_size": 80, "max_copies": 2}, playbook)
    assert fmt.deck_size == 80 and fmt.max_copies == 2
    default = rules_for({"format": "casual"}, playbook)
    assert default.deck_size == 60 and default.max_copies == 4
    try:
        rules_for({"format": "bogus"}, playbook)
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError")


def test_owned_counts_merge_printings():
    a = make_record("Bear")
    b = dict(a, id="other-printing")
    index = {a["id"]: a, b["id"]: b}
    rows = [{"scryfall_id": a["id"], "quantity": 2}, {"scryfall_id": "other-printing",
            "quantity": "3"}, {"scryfall_id": "gone", "quantity": 9}]
    assert owned_counts(rows, index) == {a["oracle_id"]: 5}


def _printing(record, card_id):
    """Another printing of a card: a new Scryfall id with the same oracle id."""
    return dict(record, id=card_id)


def test_copy_limits_count_every_printing_of_a_card(playbook):
    bolt = make_record("Lightning Bolt", mana_cost="{R}", color_identity=("R",))
    reprint = _printing(bolt, "bolt-2xm")
    index = _pool(bolt, reprint)
    record = _deck([_line(bolt, 3), _line(reprint, 3)])
    cards = _run(record, index, playbook)["cards"]
    assert "too_many" in cards[bolt["id"]]["issues"]
    assert "too_many" in cards[reprint["id"]]["issues"]


def test_owned_copies_count_every_printing_of_a_card(playbook):
    bolt = make_record("Lightning Bolt", mana_cost="{R}", color_identity=("R",))
    reprint = _printing(bolt, "bolt-2xm")
    index = _pool(bolt, reprint)
    record = _deck([_line(bolt, 2), _line(reprint, 2)])
    rows = [{"scryfall_id": bolt["id"], "quantity": 3}]
    cards = _run(record, index, playbook, rows=rows)["cards"]
    assert "short" in cards[bolt["id"]]["issues"]
    assert "short" in cards[reprint["id"]]["issues"]


def test_seven_dwarves_and_nazgul_allow_their_own_numbers(playbook):
    dwarves = make_record("Seven Dwarves", mana_cost="{1}{R}", color_identity=("R",),
                          oracle_text="A deck can have up to seven cards named Seven Dwarves.")
    nazgul = make_record("Nazgûl", mana_cost="{2}{B}", color_identity=("B",),
                         oracle_text="A deck can have up to nine cards named Nazgûl.")
    index = _pool(dwarves, nazgul)
    seven = _run(_deck([_line(dwarves, 7), _line(nazgul, 9)]), index, playbook,
                 rows=_rows(index, 9))["cards"]
    assert "too_many" not in seven[dwarves["id"]]["issues"]
    assert "too_many" not in seven[nazgul["id"]]["issues"]
    eight = _run(_deck([_line(dwarves, 8)]), index, playbook, rows=_rows(index, 9))["cards"]
    assert "too_many" in eight[dwarves["id"]]["issues"]


def test_the_curve_shows_zero_drops_apart(playbook):
    ornithopter = make_record("Ornithopter", type_line="Artifact Creature — Thopter",
                              mana_cost="{0}", cmc=0, color_identity=())
    bear = make_record("Bear", cmc=1, mana_cost="{G}")
    index = _pool(ornithopter, bear)
    curve = _run(_deck([_line(ornithopter, 4), _line(bear, 2), _forest(20)]), index,
                 playbook)["curve"]
    assert list(curve) == ["0", "1", "2", "3", "4", "5", "6+"]
    assert curve["0"] == 4 and curve["1"] == 2


def test_each_issue_has_a_plain_reason(playbook):
    owned_two = make_record("Two Owned")
    unowned = make_record("Unowned")
    banned = make_record("Banned One")
    banned["legalities"]["modern"] = "banned"
    illegal = make_record("Illegal One", legal=("commander",))
    seven = make_record("Seven Dwarves", oracle_text="A deck can have up to seven cards "
                        "named Seven Dwarves.")
    index = _pool(owned_two, unowned, banned, illegal, seven)
    rows = [{"scryfall_id": owned_two["id"], "quantity": 2},
            {"scryfall_id": banned["id"], "quantity": 1},
            {"scryfall_id": illegal["id"], "quantity": 1},
            {"scryfall_id": seven["id"], "quantity": 8}]
    record = _deck([_line(owned_two, 3), _line(unowned, 1), _line(banned, 1),
                    _line(illegal, 1), _line(seven, 8),
                    {"scryfall_id": "missing", "name": "Ghost", "count": 1}])
    cards = _run(record, index, playbook, rows)["cards"]
    assert cards[owned_two["id"]]["reasons"] == {"short": "This deck has 3 copies; Mine holds 2."}
    assert cards[unowned["id"]]["reasons"] == {"not_owned": "Mine holds no copy of this card."}
    assert cards[banned["id"]]["reasons"]["banned"] == "Banned in Modern."
    assert cards[illegal["id"]]["reasons"]["not_legal"] == "Not legal in Modern."
    assert cards[seven["id"]]["reasons"] == {
        "too_many": "Its rules text allows up to 7. This deck has 8."}
    assert cards["missing"]["reasons"]["not_a_card"].startswith("No card in the card data")


def test_off_color_and_restricted_reasons(playbook):
    chief = make_record("Green Chief", type_line="Legendary Creature — Elf",
                        legal=("commander",))
    grixis = make_record("Grixis Spell", type_line="Instant", mana_cost="{U}{B}{R}",
                         color_identity=("U", "B", "R"), cmc=3, legal=("commander", "vintage"))
    index = _pool(chief, grixis)
    commander = {"scryfall_id": chief["id"], "name": chief["name"]}
    record = _deck([_line(grixis, 1)], fmt="commander", commander=commander)
    cards = _run(record, index, playbook)["cards"]
    assert cards[grixis["id"]]["reasons"]["off_color"] == (
        "Its color identity has blue, black and red. Green Chief allows only green.")
    grixis["legalities"]["vintage"] = "restricted"
    vintage = _run(_deck([_line(grixis, 2)], fmt="vintage"), index, playbook)["cards"]
    assert vintage[grixis["id"]]["reasons"]["too_many"] == (
        "Restricted in Vintage: 1 copy allowed. This deck has 2.")


def test_a_commander_deck_has_bracket_facts_and_other_formats_do_not(playbook):
    chief = make_record("Green Chief", type_line="Legendary Creature — Elf")
    gc = make_record("Power Card")
    gc["game_changer"] = True
    index = _pool(chief, gc)
    commander = {"scryfall_id": chief["id"], "name": chief["name"]}
    result = _run(_deck([_line(gc, 1)], fmt="commander", commander=commander), index, playbook)
    assert result["bracket"]["floor"] == 3
    assert result["bracket"]["game_changers"] == ["Power Card"]
    assert _run(_deck([_line(gc, 1)]), index, playbook)["bracket"] is None

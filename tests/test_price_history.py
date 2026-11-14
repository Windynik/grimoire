from backend.core.price_history import (
    MAX_SNAPSHOTS, add_snapshot, movers, slot, snapshot, value_history,
)


def card(sid, name, price, quantity=1, foil=False):
    return {"scryfall_id": sid, "name": name, "price": price, "quantity": quantity, "foil": foil}


DAY1 = "2026-11-01T00:00:00+00:00"
DAY2 = "2026-11-08T00:00:00+00:00"


def test_a_snapshot_keeps_the_value_the_copies_and_each_unit_price():
    shot = snapshot([card("a", "Bolt", 1.5, 2), card("a", "Bolt", 4.0, 1, foil="foil"),
                     card("b", "Bear", 0, 3)], DAY1, at="now")
    assert shot == {"source": "scryfall", "data_date": DAY1, "at": "now", "value": 7.0, "cards": 6,
                    "prices": {"a|": 1.5, "a|foil": 4.0}}
    assert slot(card("a", "Bolt", 1, foil="normal")) == "a|"


def test_one_snapshot_per_card_data_date_and_none_without_card_data():
    cards = [card("a", "Bolt", 1.0)]
    first = add_snapshot(None, cards, DAY1)
    assert len(first["snapshots"]) == 1
    assert add_snapshot(first, cards, DAY1) is None
    assert add_snapshot(first, cards, None) is None
    second = add_snapshot(first, [card("a", "Bolt", 2.0)], DAY2)
    assert value_history(second) == [{"date": DAY1, "value": 1.0, "cards": 1},
                                     {"date": DAY2, "value": 2.0, "cards": 1}]


def test_the_history_keeps_the_newest_snapshots():
    history = None
    for day in range(MAX_SNAPSHOTS + 3):
        history = add_snapshot(history, [card("a", "Bolt", 1.0)], "d%03d" % day)
    assert len(history["snapshots"]) == MAX_SNAPSHOTS
    assert history["snapshots"][0]["data_date"] == "d003"


def test_movers_count_the_copies_and_skip_small_and_new_cards():
    old = [card("a", "Bolt", 1.0, 4), card("b", "Titan", 10.0), card("c", "Elf", 0.5),
           card("d", "Bear", 3.0)]
    new = [card("a", "Bolt", 2.0, 4), card("b", "Titan", 7.0), card("c", "Elf", 0.52),
           card("d", "Bear", 3.5), card("e", "New", 9.0)]
    history = add_snapshot(add_snapshot(None, old, DAY1), new, DAY2)
    found = movers(history, new)
    assert (found["since"], found["until"]) == (DAY1, DAY2)
    assert [(m["name"], m["change"], m["total"]) for m in found["up"]] == [
        ("Bolt", 1.0, 4.0), ("Bear", 0.5, 0.5)]
    assert [(m["name"], m["before"], m["after"], m["total"]) for m in found["down"]] == [
        ("Titan", 10.0, 7.0, -3.0)]
    assert movers(add_snapshot(None, old, DAY1), old) is None


def test_each_price_source_has_its_own_snapshots_and_movers():
    old = [card("a", "Bolt", 1.0)]
    new = [card("a", "Bolt", 3.0)]
    history = add_snapshot(None, old, DAY1)
    # Card Kingdom prices start their own line: no move from TCGplayer to Card Kingdom.
    history = add_snapshot(history, new, "2026-11-02", source="cardkingdom")
    assert movers(history, new, source="cardkingdom") is None
    assert value_history(history) == [{"date": DAY1, "value": 1.0, "cards": 1}]
    assert value_history(history, "cardkingdom") == [{"date": "2026-11-02", "value": 3.0, "cards": 1}]
    # The same Card Kingdom date adds nothing; a later one does.
    assert add_snapshot(history, new, "2026-11-02", source="cardkingdom") is None
    history = add_snapshot(history, [card("a", "Bolt", 4.0)], "2026-11-09", source="cardkingdom")
    assert movers(history, new, source="cardkingdom")["up"][0]["change"] == 1.0
    # A snapshot from before sources counts as the default provider.
    legacy = {"snapshots": [{"data_date": DAY1, "value": 2.0, "cards": 1, "prices": {}}]}
    assert value_history(legacy) == [{"date": DAY1, "value": 2.0, "cards": 1}]

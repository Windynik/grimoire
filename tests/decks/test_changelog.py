from backend.decks.changelog import (
    MAX_ENTRIES, changes_newest_first, diff, record_edit, record_event,
)


def line(name, count, sid=None):
    return {"scryfall_id": sid or "id-" + name.lower(), "name": name, "count": count}


def deck(main=(), sideboard=(), commander=None, name="Deck", fmt="modern", changelog=None):
    record = {"name": name, "format": fmt, "commander": commander,
              "sections": {"main": list(main), "sideboard": list(sideboard), "maybeboard": []}}
    if changelog is not None:
        record["changelog"] = changelog
    return record


T0 = "2026-11-12T10:00:00+00:00"
T1 = "2026-11-12T10:05:00+00:00"   # 5 minutes later: merges
T2 = "2026-11-12T10:30:00+00:00"   # 25 minutes after T1: a new entry


def test_diff_lists_card_and_field_changes_in_order():
    old = deck([line("Bolt", 2), line("Shock", 1)], name="Red")
    new = deck([line("Bolt", 3), line("Duress", 1)], sideboard=[line("Shock", 1)],
               commander={"scryfall_id": "id-krenko", "name": "Krenko"}, name="Goblins")
    change = diff(old, new)
    assert [(c["section"], c["name"], c["delta"]) for c in change["cards"]] == [
        ("commander", "Krenko", 1), ("main", "Bolt", 1), ("main", "Duress", 1),
        ("main", "Shock", -1), ("sideboard", "Shock", 1)]
    assert change["fields"] == [{"field": "name", "from": "Red", "to": "Goblins"}]


def test_edits_close_in_time_merge_into_the_net_change():
    first = deck([line("Bolt", 2)])
    second = deck([line("Bolt", 3), line("Shock", 1)])
    record_edit(second, first, at=T0)
    third = deck([line("Bolt", 3)])
    record_edit(third, second, at=T1)
    log = third["changelog"]
    assert len(log) == 1
    assert log[0]["at"] == T0 and log[0]["until"] == T1
    assert [(c["name"], c["delta"]) for c in log[0]["cards"]] == [("Bolt", 1)]


def test_an_edit_that_undoes_the_last_one_leaves_no_entry():
    first = deck([line("Bolt", 2)])
    second = deck([line("Bolt", 3)])
    record_edit(second, first, at=T0)
    back = deck([line("Bolt", 2)])
    record_edit(back, second, at=T1)
    assert back["changelog"] == []


def test_a_later_edit_starts_a_new_entry_and_a_rename_keeps_the_first_name():
    a = deck(name="One")
    b = deck(name="Two")
    record_edit(b, a, at=T0)
    c = deck(name="Three")
    record_edit(c, b, at=T1)
    assert c["changelog"][0]["fields"] == [{"field": "name", "from": "One", "to": "Three"}]
    d = deck([line("Bolt", 1)], name="Three")
    record_edit(d, c, at=T2)
    assert len(d["changelog"]) == 2
    assert changes_newest_first(d)[0]["cards"][0]["name"] == "Bolt"


def test_a_save_with_no_change_adds_nothing_and_events_do_not_merge():
    record = deck([line("Bolt", 1)])
    record_event(record, "imported", "Imported from a decklist.", at=T0, with_cards=True)
    assert record["changelog"][0]["cards"][0]["delta"] == 1
    same = deck([line("Bolt", 1)], changelog=record["changelog"])
    record_edit(same, record, at=T1)
    assert len(same.get("changelog")) == 1
    more = deck([line("Bolt", 2)])
    record_edit(more, record, at=T1)
    assert [e["kind"] for e in more["changelog"]] == ["imported", "edit"]


def test_the_changelog_keeps_the_newest_entries():
    record = deck()
    for i in range(MAX_ENTRIES + 5):
        record_event(record, "built" if i % 2 else "unbuilt", at=T0)
    assert len(record["changelog"]) == MAX_ENTRIES

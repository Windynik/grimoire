from backend.decks.records import entry_key
from backend.decks.usage import (
    CopiesInUse, current_collections, deck_copies, free_rows, mark_taken, owned_by_card, taken_cards,
    usage_by_card, used_counts,
)
from tests.forge.conftest import make_record

BOLT = make_record("Lightning Bolt", mana_cost="{R}", color_identity=("R",))
BOLT_2XM = dict(BOLT, id="bolt-2xm", set="2xm")
SOL = make_record("Sol Ring", type_line="Artifact", mana_cost="{1}")
INDEX = {c["id"]: c for c in (BOLT, BOLT_2XM, SOL)}
KEY_BOLT = BOLT["oracle_id"]


def line(card, count):
    return {"scryfall_id": card["id"], "name": card["name"], "count": count}


def deck(deck_id, main, sideboard=(), maybeboard=(), commander=None, built=True):
    return {"id": deck_id, "name": deck_id.title(), "commander": commander, "built": built,
            "sections": {"main": list(main), "sideboard": list(sideboard),
                         "maybeboard": list(maybeboard)}}


def test_a_deck_uses_its_main_sideboard_and_commander_in_any_printing():
    record = deck("red", [line(BOLT, 2), {"scryfall_id": None, "name": "Mountain", "count": 20,
                                         "basic": True}],
                  sideboard=[line(BOLT_2XM, 1)], maybeboard=[line(SOL, 1)],
                  commander={"scryfall_id": SOL["id"], "name": "Sol Ring"})
    copies = deck_copies(record, INDEX)
    assert copies == {KEY_BOLT: 3, SOL["oracle_id"]: 1}


def test_usage_lists_the_decks_and_used_counts_skip_one_deck():
    usage = usage_by_card([deck("red", [line(BOLT, 2)]), deck("burn", [line(BOLT_2XM, 4)])], INDEX)
    assert usage[KEY_BOLT] == [{"deck_id": "red", "name": "Red", "count": 2, "built": True},
                               {"deck_id": "burn", "name": "Burn", "count": 4, "built": True}]
    assert used_counts(usage)[KEY_BOLT] == 6
    assert used_counts(usage, exclude_deck="burn")[KEY_BOLT] == 2


def test_an_older_import_of_the_same_cards_does_not_count_twice():
    row = lambda card, qty: {"scryfall_id": card["id"], "name": card["name"], "quantity": qty}
    newer = ({"job_id": "new"}, [row(BOLT, 3), row(SOL, 1)])
    older = ({"job_id": "old"}, [row(BOLT, 2)])
    binder = ({"job_id": "binder"}, [row(BOLT_2XM, 1)])
    kept = [meta["job_id"] for meta, _ in current_collections([newer, older, binder])]
    assert kept == ["new", "binder"]
    assert owned_by_card([newer, older, binder], INDEX)[KEY_BOLT] == 4


class FakeDecks:
    def __init__(self, records):
        self.records = {r["id"]: r for r in records}

    def list(self):
        return [{"id": i, "name": r["name"]} for i, r in self.records.items()]

    def get(self, deck_id):
        return self.records.get(deck_id)


class FakeCollections:
    def __init__(self, rows):
        self.rows = rows

    def list_collections(self):
        return [{"job_id": "box"}]

    def get_collection(self, job_id):
        return self.rows


def test_copies_in_use_gives_used_owned_and_free_per_card():
    decks = FakeDecks([deck("red", [line(BOLT, 2)]), deck("burn", [line(BOLT, 3)])])
    rows = [{"scryfall_id": BOLT["id"], "name": BOLT["name"], "quantity": 4}]
    copies = CopiesInUse(decks, FakeCollections(rows), INDEX)
    status = copies.status(copies.key(BOLT_2XM["id"]))
    assert (status["used"], status["owned"], status["free"]) == (5, 4, 0)
    assert [d["deck_id"] for d in status["decks"]] == ["red", "burn"]
    alone = copies.status(KEY_BOLT, exclude_deck="burn")
    assert (alone["used"], alone["free"]) == (2, 2)
    assert copies.status(copies.key(None, "Nothing")) == {"decks": [], "used": 0, "owned": 0,
                                                         "free": 0}


def test_a_card_is_taken_when_other_decks_leave_too_few_free_copies():
    burn = deck("burn", [line(BOLT, 3)])
    mine = deck("mine", [line(BOLT_2XM, 2), line(SOL, 1)])
    rows = [{"scryfall_id": BOLT["id"], "name": BOLT["name"], "quantity": 4},
            {"scryfall_id": SOL["id"], "name": SOL["name"], "quantity": 1}]
    copies = CopiesInUse(FakeDecks([burn, mine]), FakeCollections(rows), INDEX)
    taken = taken_cards(mine, "mine", copies)
    # Bolt: 4 owned, Burn uses 3, so 1 is free and this deck needs 2.
    # Sol Ring: no other deck uses it, so it is not taken.
    assert list(taken) == [KEY_BOLT]
    assert taken[KEY_BOLT]["free"] == 1 and taken[KEY_BOLT]["need"] == 2
    assert [d["deck_id"] for d in taken[KEY_BOLT]["decks"]] == ["burn"]

    analysis = {"cards": {entry_key(l): {"owned": 4, "issues": []}
                          for l in mine["sections"]["main"]}}
    mark_taken(analysis, mine, taken, INDEX)
    bolt = analysis["cards"][entry_key(line(BOLT_2XM, 2))]
    assert bolt["issues"] == ["taken"]
    assert bolt["taken"] == {"need": 2, "free": 1, "decks": [
        {"deck_id": "burn", "name": "Burn", "count": 3, "built": True}]}
    assert analysis["cards"][entry_key(line(SOL, 1))]["issues"] == []


def test_a_card_the_owner_lacks_is_not_taken():
    burn = deck("burn", [line(BOLT, 1)])
    mine = deck("mine", [line(BOLT, 4)])
    rows = [{"scryfall_id": BOLT["id"], "name": BOLT["name"], "quantity": 2}]
    copies = CopiesInUse(FakeDecks([burn, mine]), FakeCollections(rows), INDEX)
    # 2 owned and this deck needs 4: the deck is short, whatever the others do.
    assert taken_cards(mine, "mine", copies) == {}


def test_free_rows_keep_only_the_copies_no_deck_uses():
    rows = [{"scryfall_id": BOLT["id"], "name": BOLT["name"], "quantity": 2},
            {"scryfall_id": BOLT_2XM["id"], "name": BOLT["name"], "quantity": 2},
            {"scryfall_id": SOL["id"], "name": SOL["name"], "quantity": 1}]
    decks = FakeDecks([deck("burn", [line(BOLT, 3)]), deck("rings", [line(SOL, 1)])])
    copies = CopiesInUse(decks, FakeCollections(rows), INDEX)
    # 4 Bolts owned in two printings, 3 in Burn: 1 free. The only Sol Ring is in Rings.
    assert free_rows(rows, copies) == [dict(rows[0], quantity=1)]


def test_a_deck_that_is_not_built_holds_no_copies():
    idea = deck("idea", [line(BOLT, 4)], built=False)
    burn = deck("burn", [line(BOLT, 1)])
    rows = [{"scryfall_id": BOLT["id"], "name": BOLT["name"], "quantity": 4}]
    copies = CopiesInUse(FakeDecks([idea, burn]), FakeCollections(rows), INDEX)
    status = copies.status(KEY_BOLT)
    # The drawer still lists the idea, but only Burn uses copies.
    assert [d["deck_id"] for d in status["decks"]] == ["idea", "burn"]
    assert (status["used"], status["free"]) == (1, 3)
    # The idea needs 4 and Burn takes 1, so the idea shows Burn; Burn sees no taker.
    assert [d["deck_id"] for d in taken_cards(idea, "idea", copies)[KEY_BOLT]["decks"]] == ["burn"]
    assert taken_cards(burn, "burn", copies) == {}

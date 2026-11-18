"""The Forge check before a run: the legal cards of the pool, and the least a plan needs."""

from backend.forge.cards import hydrate
from backend.forge.graph import core_need, core_size, plan_room
from backend.forge.pool_check import check_pool
from tests.forge.conftest import make_pool, make_record

SAC = "Sacrifice a creature: Scry 1."
DEATH = "Whenever another creature you control dies, each opponent loses 1 life."


def leader(name="Leader Test", colors=("B",)):
    return make_record(name, type_line="Legendary Creature — Angel", oracle_text=DEATH,
                       mana_cost="{1}" + "".join("{%s}" % c for c in colors), color_identity=colors)


def black(name, n, text=SAC):
    return make_record(name, type_line="Creature — Kind%d" % n, oracle_text=text,
                       color_identity=("B",), mana_cost="{1}{B}")


def white(name, n):
    return make_record(name, type_line="Creature — Kind%d" % n, color_identity=("W",),
                       mana_cost="{1}{W}")


def swamp():
    return make_record("Swamp", type_line="Basic Land — Swamp", mana_cost="", cmc=0,
                       color_identity=("B",), produced=("B",))


def small_commander_pool():
    """A black legend, 8 black spells, a white spell, lands, a card not legal, a second printing.

    Copies: legend 1, spells 8 + 1 extra row, white 1, Swamp 10, not legal 1: 22 in all,
    21 legal. The legend has 8 other black spells, fewer than min_core 10.
    """
    records = [leader()] + [black("Sac %d" % i, i) for i in range(4)]
    records += [black("Pay %d" % i, 10 + i, DEATH) for i in range(4)]
    records += [white("Stray", 30), swamp(),
                make_record("Banned Thing", color_identity=("B",), mana_cost="{B}", legal=())]
    collection, index = make_pool(records, [1] * 10 + [10, 1])
    # A second printing of Sac 0 in the same pool: the copies add up.
    collection.append({"scryfall_id": records[1]["id"], "quantity": 1, "name": "Sac 0"})
    return collection, index


def test_core_need_and_core_size_follow_the_size_rule_of_a_plan(rules):
    assert core_need(rules["commander"]) == 10
    assert core_need(rules["standardbrawl"]) == 8
    # Formats with copies count playsets: half of min_core 8 playsets is 16 copies.
    assert core_need(rules["modern"]) == 16
    assert core_need(rules["casual"].scaled(60, 3)) == 12
    assert core_need(rules["casual"].scaled(60, 1)) == 8
    collection, index = make_pool([black("A", 1), black("B", 2)], [7, 2])
    assert core_size(hydrate(collection, index, rules["modern"]), rules["modern"]) == 6
    assert core_size(hydrate(collection, index, rules["commander"]), rules["commander"]) == 2


def test_plan_room_counts_the_best_commander_without_lands_or_other_colors(rules):
    fmt = rules["commander"]
    collection, index = small_commander_pool()
    assert plan_room(hydrate(collection, index, fmt), fmt) == 8
    # A white legend has only the one white spell; the black legend still wins.
    collection, index = make_pool([leader("White Boss", ("W",)), white("Stray", 30)]
                                  + [black("Sac %d" % i, i) for i in range(9)])
    assert plan_room(hydrate(collection, index, fmt), fmt) == 1
    collection, index = make_pool([leader(), leader("White Boss", ("W",)), white("Stray", 30)]
                                  + [black("Sac %d" % i, i) for i in range(9)])
    assert plan_room(hydrate(collection, index, fmt), fmt) == 9


def test_plan_room_is_zero_without_a_commander(rules):
    fmt = rules["commander"]
    collection, index = make_pool([black("Sac %d" % i, i) for i in range(12)])
    assert plan_room(hydrate(collection, index, fmt), fmt) == 0
    assert plan_room([], fmt) == 0


def test_plan_room_without_a_commander_counts_copies_in_every_color(rules):
    fmt = rules["modern"]
    collection, index = make_pool([black("A", 1), black("B", 2), white("C", 3), swamp()],
                                  [7, 4, 2, 20])
    # 4 (of 7) + 4 + 2; a wish can name both colors, so the white card counts too.
    assert plan_room(hydrate(collection, index, fmt), fmt) == 10
    assert plan_room(hydrate(collection, index, fmt), fmt, frozenset("B")) == 8


def test_too_few_cards_for_a_commander_say_why_and_a_commander_lifts_it(rules):
    collection, index = small_commander_pool()
    check = check_pool(collection, index, rules["commander"])
    assert check["cards"] == 22 and check["legal"] == 21
    assert check["room"] == 8 and check["need"] == 10 and check["commanders"] == 1
    assert check["summary"] == ("21 of your 22 cards are legal in Commander. "
                                "A Commander deck has 100 cards.")
    assert check["problem"] == (
        "A Commander deck needs a commander and at least 10 more different cards in its colors "
        "that are not lands. The best commander you own has 8. Choose a commander, and the "
        "forge builds around it with the cards you have.")
    assert check["commander_lifts"] is True


def test_no_commander_blocks_and_a_commander_cannot_lift_it(rules):
    records = [black("Sac %d" % i, i) for i in range(12)] + [swamp()]
    for record in records:
        record["legalities"]["brawl"] = "legal"
    collection, index = make_pool(records)
    check = check_pool(collection, index, rules["brawl"])
    assert check["commanders"] == 0
    assert check["summary"] == "All 13 of your cards are legal in Brawl. A Brawl deck has 100 cards."
    assert check["problem"] == ("A Brawl deck needs a commander, and none of your legal cards "
                                "can be one.")
    assert check["commander_lifts"] is False


def test_enough_cards_leave_the_run_free_even_with_unicode_names(rules):
    records = [leader("Lim-Dûl the Necromancer")] + [black("Sac %d" % i, i) for i in range(5)]
    records += [black("Pay %d" % i, 10 + i, DEATH) for i in range(4)]
    records += [black("Ætherling Fan", 20)]
    collection, index = make_pool(records)
    check = check_pool(collection, index, rules["commander"])
    assert check["room"] == 10
    assert check["problem"] is None and check["commander_lifts"] is False
    assert check["summary"] == "All 11 of your cards are legal in Commander. A Commander deck has 100 cards."


def test_a_format_with_copies_counts_up_to_the_copy_limit(rules):
    records = [black("A", 1), black("B", 2), black("C", 3), black("D", 4), swamp()]
    collection, index = make_pool(records, [7, 4, 4, 2, 20])
    check = check_pool(collection, index, rules["modern"])
    assert check["room"] == 14 and check["need"] == 16 and check["commanders"] is None
    assert check["summary"] == "All 37 of your cards are legal in Modern. A Modern deck has 60 cards."
    assert check["problem"] == ("A Modern deck needs at least 16 cards that are not lands, "
                                "counting up to 4 copies of each. You have 14.")
    assert check["commander_lifts"] is False


def test_casual_uses_its_size_copies_and_colors(rules):
    records = [black("A", 1), black("B", 2), black("C", 3)] + [white("W%d" % i, 10 + i)
                                                                for i in range(5)]
    collection, index = make_pool(records, [4] * 8)
    fmt = rules["casual"].scaled(40, 2)
    check = check_pool(collection, index, fmt, frozenset("B"))
    assert check["need"] == 8 and check["room"] == 6
    assert check["summary"] == "All 32 of your cards are legal in Casual. A Casual deck has 40 cards."
    assert check["problem"] == ("A Casual deck needs at least 8 cards in your colors that are "
                                "not lands, counting up to 2 copies of each. You have 6.")
    one = check_pool(collection, index, rules["casual"].scaled(60, 1), frozenset("B"))
    assert one["problem"] == ("A Casual deck needs at least 8 different cards in your colors "
                              "that are not lands. You have 3.")
    # Without colors the white cards count too: 3 + 5 cards, 2 copies each, is 16.
    assert check_pool(collection, index, fmt)["problem"] is None


def test_one_card_and_no_cards(rules):
    collection, index = make_pool([black("A", 1), white("B", 2)], [1, 0])
    check = check_pool(collection, index, rules["modern"])
    assert check["summary"] == "1 of your 1 card is legal in Modern. A Modern deck has 60 cards."
    assert check["problem"].endswith("You have 1.")
    collection, index = make_pool([swamp()], [3])
    check = check_pool(collection, index, rules["modern"])
    assert check["summary"] == "All 3 of your cards are legal in Modern. A Modern deck has 60 cards."
    assert check["problem"].endswith("You have none.")
    collection, index = make_pool([leader(), swamp()])
    assert check_pool(collection, index, rules["commander"])["problem"] == (
        "A Commander deck needs a commander and at least 10 more different cards in its colors "
        "that are not lands. No commander you own has any. Choose a commander, and the forge "
        "builds around it with the cards you have.")
    empty = check_pool([], {}, rules["commander"])
    assert empty["summary"] == "" and empty["problem"] == "The chosen collections have no cards."
    assert empty["commander_lifts"] is False
    # Copies of a card that is not in the card data count in the pool, not as legal.
    check = check_pool([{"scryfall_id": "id-ghost", "quantity": 2}], {}, rules["modern"])
    assert check["summary"] == "0 of your 2 cards are legal in Modern. A Modern deck has 60 cards."


def test_the_summary_writes_large_counts_with_thousands_separators():
    from backend.forge.pool_check import _summary
    from backend.forge.playbook import load_playbook
    fmt = load_playbook().formats["commander"]
    assert _summary(1453, 1493, fmt) == ("1,453 of your 1,493 cards are legal in Commander. "
                                         "A Commander deck has 100 cards.")
    assert _summary(1493, 1493, fmt).startswith("All 1,493 of your cards are legal")

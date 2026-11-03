import time

from backend.core.collection_query import (
    Filters,
    collection_set_names,
    parse_query,
    search,
    color_bucket,
    insights,
    new_since,
    owned_cards,
    unit_price,
)


def test_unit_price_non_foil_order():
    p = {"usd": "1.50", "usd_foil": "3.00", "eur": "1", "tix": "0.1"}
    assert unit_price(p, False) == 1.5
    assert unit_price({"usd": None, "usd_foil": "3.00", "eur": "1"}, False) == 3.0
    assert unit_price({"usd": "0.00", "usd_foil": None, "eur": "0.80"}, False) == 0.8
    assert unit_price({"tix": "0.05"}, False) == 0.05


def test_unit_price_foil_order():
    p = {"usd": "1.50", "usd_foil": "3.00", "eur": "1"}
    assert unit_price(p, True) == 3.0
    assert unit_price({"usd": "1.50", "usd_foil": None}, True) == 1.5
    assert unit_price({"usd": "0.00", "usd_foil": "0.00", "eur": "2"}, True) == 2.0


def test_unit_price_empty():
    assert unit_price({}, False) == 0
    assert unit_price(None, True) == 0
    assert unit_price({"usd": "abc", "eur": ""}, False) == 0
    assert unit_price({"usd": "0.00"}, False) == 0


INDEX = {
    "a": {
        "name": "Bolt", "mana_cost": "{R}", "type_line": "Instant", "oracle_text": "x",
        "rarity": "common", "set": "lea", "set_name": "Alpha", "collector_number": "161",
        "cmc": 1, "color_identity": ["R"], "legalities": {"modern": "legal"},
        "edhrec_rank": 5, "image_url": "i", "back_image_url": "",
        "prices": {"usd": "2.00", "usd_foil": "5.00"},
    },
}


def test_owned_cards_merge():
    stored = [{"scryfall_id": "a", "name": "Old", "quantity": "3", "foil": "foil", "set": "lea"}]
    c = owned_cards(stored, INDEX)[0]
    assert c["name"] == "Bolt"
    assert c["quantity"] == 3 and c["foil"] is True
    assert c["price"] == 5.0 and c["value"] == 15.0
    assert c["set_name"] == "Alpha" and c["collector_number"] == "161"
    assert c["cmc"] == 1 and c["color_identity"] == ["R"]


def test_owned_cards_fallback():
    stored = [{"scryfall_id": "zz", "name": "Ghost", "type_line": "Creature", "rarity": "rare",
               "set": "xyz", "quantity": 2, "foil": "normal", "price": "1.25",
               "prices": {"usd": "1.25"}, "image_url": "u"}]
    c = owned_cards(stored, INDEX)[0]
    assert c["name"] == "Ghost" and c["cmc"] == 0
    assert c["color_identity"] == [] and c["legalities"] == {}
    assert c["set_name"] == "XYZ"
    assert c["foil"] is False and c["quantity"] == 2
    assert c["price"] == 1.25 and c["value"] == 2.5


def test_owned_cards_csv_set_name_and_bad_quantity():
    stored = [{"scryfall_id": "zz", "name": "Ghost", "set": "xyz", "quantity": "", "foil": None}]
    names = collection_set_names([{"Set code": "XYZ", "Set name": "Mystery"}])
    assert names == {"xyz": "Mystery"}
    c = owned_cards(stored, INDEX, names)[0]
    assert c["set_name"] == "Mystery"
    assert c["quantity"] == 1 and c["foil"] is False


def test_color_bucket():
    assert color_bucket({"color_identity": ["W"]}) == "W"
    assert color_bucket({"color_identity": ["U", "B"]}) == "M"
    assert color_bucket({"color_identity": []}) == "C"
    assert color_bucket({"color_identity": ["G"], "type_line": "Land"}) == "G"
    assert color_bucket({}) == "C"


def _card(id_, name, rarity, ci, cmc, qty, foil=False, type_line="Creature", price=1.0, set_="s1"):
    return {"scryfall_id": id_, "name": name, "rarity": rarity, "color_identity": ci,
            "cmc": cmc, "quantity": qty, "foil": foil, "type_line": type_line,
            "price": price, "value": price * qty, "set": set_}


def test_insights():
    cards = [
        _card("1", "A", "common", ["W"], 0, 2, price=1.0),
        _card("2", "B", "uncommon", ["U", "R"], 3, 1, foil=True, price=2.5),
        _card("3", "C", "rare", [], 7, 1, price=10.0, set_="s2"),
        _card("4", "D", "mythic", ["G"], 9, 3, price=4.0),
        _card("5", "Forest", "common", ["G"], 0, 4, type_line="Basic Land // Land", price=0.0),
        _card("5", "Forest", "common", ["G"], 0, 1, foil=True, type_line="Basic Land", price=0.0),
    ]
    assert insights(cards) == {
        "value": 2.0 + 2.5 + 10.0 + 12.0,
        "cards": 12,
        "unique": 5,
        "rarity": {"common": 7, "uncommon": 1, "rare": 1, "mythic": 3},
        "foils": 2,
        "colors": {"W": 2, "U": 0, "B": 0, "R": 0, "G": 8, "C": 1, "M": 1},
        "curve": {"0": 2, "1": 0, "2": 0, "3": 1, "4": 0, "5": 0, "6": 0, "7+": 4},
        "sets": 2,
    }


def test_new_since():
    prev = [{"scryfall_id": "a", "foil": False, "quantity": 2},
            {"scryfall_id": "b", "foil": False, "quantity": 1}]
    cur = [
        {"scryfall_id": "a", "foil": False, "quantity": 3},   # more
        {"scryfall_id": "b", "foil": False, "quantity": 1},   # same
        {"scryfall_id": "b", "foil": True, "quantity": 1},    # foil variant new
        {"scryfall_id": "c", "foil": False, "quantity": 1},   # added
    ]
    assert new_since(cur, prev) == {("a", False), ("b", True), ("c", False)}
    assert new_since(cur, None) == set()
    assert new_since(cur, []) == {("a", False), ("b", False), ("b", True), ("c", False)}


# ---- Smart search ----------------------------------------------------------

def mk(name, type_line="Creature", ident=(), cmc=2, rarity="common", set_="tst",
       price=1.0, qty=1, foil=False, text="", legal=("modern",), rank=None, sid=None):
    return {
        "scryfall_id": sid or "id-" + name.lower().replace(" ", "-"),
        "name": name, "type_line": type_line, "oracle_text": text, "mana_cost": "",
        "color_identity": list(ident), "cmc": cmc, "rarity": rarity, "set": set_,
        "set_name": set_.upper(), "price": price, "quantity": qty, "foil": foil,
        "value": price * qty, "edhrec_rank": rank,
        "legalities": {f: "legal" for f in legal} or {},
    }


def names(cards):
    return [c["name"] for c in cards]


def run(cards, q="", sort="name", new_keys=None, **filters):
    return search(cards, parse_query(q), Filters(**filters), sort, new_keys or set())


POOL = [
    mk("Bolt", "Instant", ("R",), 1, "common", "lea", 2.0, text="Deal 3 damage."),
    mk("Counter", "Instant", ("U",), 2, "uncommon", "neo", 0.5, qty=3, text="Counter target spell."),
    mk("Elf Lord", "Legendary Creature — Elf", ("G",), 3, "rare", "neo", 6.0, foil=True,
       text="Draw a card."),
    mk("Gold Wurm", "Creature — Wurm", ("U", "G"), 5, "mythic", "neo", 12.0, legal=("modern", "commander")),
    mk("Rock", "Artifact", (), 0, "common", "lea", 0.0, legal=()),
    mk("Big Land", "Land", (), 0, "rare", "lea", 20.0, foil=True, qty=2, text="Draw a card now."),
    mk("Seven Drop", "Creature — Demon", ("B",), 7, "mythic", "xyz", 3.0, rank=10),
]


def found(q, **kw):
    return names(run(POOL, q, **kw)[0])


def test_parse_name_words_all_must_match():
    assert found("elf lord") == ["Elf Lord"]
    assert found("lord elf") == ["Elf Lord"]
    assert found("elf bolt") == []
    assert found("BOLT") == ["Bolt"]


def test_keyword_type_oracle_and_quotes():
    assert found("t:creature") == ["Elf Lord", "Gold Wurm", "Seven Drop"]
    assert found("t:legendary") == ["Elf Lord"]
    assert found('o:"draw a card"') == ["Big Land", "Elf Lord"]
    assert found("o:draw") == ["Big Land", "Elf Lord"]
    assert found('t:"legendary creature"') == ["Elf Lord"]


def test_keyword_color_includes_all():
    assert found("c:g") == ["Elf Lord", "Gold Wurm"]
    assert found("c:ug") == ["Gold Wurm"]
    assert found("c:c") == ["Big Land", "Rock"]
    assert found("c:gu") == ["Gold Wurm"]


def test_keyword_mana_value_exact_and_ranges():
    assert found("mv:3") == ["Elf Lord"]
    assert found("mv:2-4") == ["Counter", "Elf Lord"]
    assert found("mv:5-") == ["Gold Wurm", "Seven Drop"]
    assert found("mv:0") == ["Big Land", "Rock"]


def test_keyword_rarity_set_format():
    assert found("r:mythic") == ["Gold Wurm", "Seven Drop"]
    assert found("s:neo") == ["Counter", "Elf Lord", "Gold Wurm"]
    assert found("f:commander") == ["Gold Wurm"]
    assert found("s:neo r:rare") == ["Elf Lord"]


def test_keyword_price_comparisons():
    assert found("$>5") == ["Big Land", "Elf Lord", "Gold Wurm"]
    assert found("$>=6") == ["Big Land", "Elf Lord", "Gold Wurm"]
    assert found("$<1") == ["Counter", "Rock"]
    assert found("$<=0.5") == ["Counter", "Rock"]
    assert found("$>1 $<7") == ["Bolt", "Elf Lord", "Seven Drop"]


def test_keyword_flags():
    assert found("foil") == ["Big Land", "Elf Lord"]
    assert found("dupes") == ["Big Land", "Counter"]
    cards, _, _ = run(POOL, "new", new_keys={("id-bolt", False)})
    assert names(cards) == ["Bolt"]


def test_unknown_tokens_are_name_text():
    q = parse_query("x:foo bolt")
    assert q.name_words == ["x:foo", "bolt"]
    assert found("x:foo") == []
    assert parse_query("mv:abc").name_words == ["mv:abc"]
    assert parse_query("c:xyz").name_words == ["c:xyz"]
    assert parse_query("f:nonsense").name_words == ["f:nonsense"]
    assert parse_query("").name_words == []


def test_filters_or_within_and_across():
    assert found("", rarity=["rare", "mythic"]) == ["Big Land", "Elf Lord", "Gold Wurm", "Seven Drop"]
    assert found("", rarity=["rare", "mythic"], colors=["G"]) == ["Elf Lord"]
    assert found("", colors=["G", "R"]) == ["Bolt", "Elf Lord"]
    assert found("", colors=["M"]) == ["Gold Wurm"]
    assert found("", type=["Land", "Artifact"]) == ["Big Land", "Rock"]
    assert found("", mv=["0", "7+"]) == ["Big Land", "Rock", "Seven Drop"]
    assert found("", set=["lea"], rarity=["common"]) == ["Bolt", "Rock"]
    assert found("", format=["commander"]) == ["Gold Wurm"]
    assert found("", min_price=6) == ["Big Land", "Elf Lord", "Gold Wurm"]
    assert found("", foil=True) == ["Big Land", "Elf Lord"]
    assert found("", foil=False, set=["neo"]) == ["Counter", "Gold Wurm"]
    assert found("", dupes=True) == ["Big Land", "Counter"]


def test_facet_counts_ignore_their_own_selection():
    _, facets, _ = run(POOL, "", rarity=["rare"], colors=["G"])
    # rarity facet ignores rarity filter: green cards across all rarities (qty-weighted)
    assert facets["rarity"]["rare"] == 1
    assert facets["rarity"]["mythic"] == 0  # no mono-green mythic
    assert facets["rarity"]["common"] == 0
    # colors facet ignores colors filter: rare cards by bucket
    assert facets["colors"]["G"] == 1
    assert facets["colors"]["C"] == 2  # Big Land x2
    assert facets["colors"]["R"] == 0
    # other facets use both filters
    assert facets["set"] == {"neo": 1, "lea": 0, "xyz": 0}


def test_facet_counts_are_quantity_weighted_and_cover_every_value():
    _, facets, _ = run(POOL, "")
    assert facets["rarity"] == {"common": 2, "uncommon": 3, "rare": 3, "mythic": 2}
    assert facets["colors"]["U"] == 3
    assert facets["colors"]["M"] == 1
    assert set(facets["colors"]) == {"W", "U", "B", "R", "G", "M", "C"}
    assert facets["type"]["Creature"] == 3
    assert facets["type"]["Land"] == 2
    assert facets["type"]["Planeswalker"] == 0
    assert facets["mv"]["7+"] == 1 and facets["mv"]["0"] == 3
    assert facets["foil"] == {"foil": 3, "normal": 7}
    assert facets["format"]["commander"] == 1
    assert facets["format"]["modern"] == 9


def test_facets_respect_query_text():
    _, facets, _ = run(POOL, "t:creature")
    assert facets["rarity"]["mythic"] == 2
    assert facets["rarity"]["common"] == 0


def test_value_is_sum_over_results():
    _, _, value = run(POOL, "")
    assert value == 2.0 + 1.5 + 6.0 + 12.0 + 0.0 + 40.0 + 3.0
    _, _, value = run(POOL, "", rarity=["common"])
    assert value == 2.0


def test_sorts():
    assert names(run(POOL, "", "price")[0])[:3] == ["Big Land", "Gold Wurm", "Elf Lord"]
    assert names(run(POOL, "", "price")[0])[-1] == "Rock"
    assert names(run(POOL, "", "price_asc")[0])[:2] == ["Counter", "Bolt"]
    assert names(run(POOL, "", "price_asc")[0])[-1] == "Rock"
    assert names(run(POOL, "", "name")[0])[:3] == ["Big Land", "Bolt", "Counter"]
    assert names(run(POOL, "", "mv")[0]) == [
        "Big Land", "Rock", "Bolt", "Counter", "Elf Lord", "Gold Wurm", "Seven Drop"]
    assert names(run(POOL, "", "color")[0]) == [
        "Counter", "Seven Drop", "Bolt", "Elf Lord", "Gold Wurm", "Big Land", "Rock"]
    assert names(run(POOL, "", "rarity")[0]) == [
        "Gold Wurm", "Seven Drop", "Big Land", "Elf Lord", "Counter", "Bolt", "Rock"]
    assert names(run(POOL, "", "set")[0]) == [
        "Big Land", "Bolt", "Rock", "Counter", "Elf Lord", "Gold Wurm", "Seven Drop"]
    assert names(run(POOL, "", "edhrec")[0])[0] == "Seven Drop"


def test_edhrec_missing_last_and_ascending():
    cards = [mk("A", rank=50), mk("B"), mk("C", rank=5)]
    assert names(run(cards, "", "edhrec")[0]) == ["C", "A", "B"]


def test_search_performance_with_3000_rows():
    import random
    rnd = random.Random(1)
    rars = ["common", "uncommon", "rare", "mythic"]
    types = ["Creature", "Instant", "Sorcery", "Artifact", "Land", "Legendary Creature — Elf"]
    cards = [
        mk("Card %d" % i, rnd.choice(types), tuple(rnd.sample("WUBRG", rnd.randint(0, 3))),
           rnd.randint(0, 8), rnd.choice(rars), "s%d" % rnd.randint(0, 150),
           rnd.random() * 10, rnd.randint(1, 4), rnd.random() < 0.2,
           "Draw a card.", ("modern", "commander", "pauper"), rnd.randint(1, 20000), "id%d" % i)
        for i in range(3000)
    ]
    started = time.perf_counter()
    results, facets, value = search(
        cards, parse_query("t:creature o:draw"),
        Filters(colors=["G", "R", "M"], rarity=["rare", "mythic", "common"], mv=["2", "3", "7+"],
                format=["modern"], min_price=1, foil=False),
        "rarity", set())
    elapsed = time.perf_counter() - started
    assert results and facets["rarity"] and value > 0
    assert elapsed < 0.3, elapsed

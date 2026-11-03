from backend.core.collection_query import (
    collection_set_names,
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

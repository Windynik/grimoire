from backend.forge.cards import (
    castable_in, fits_colors, front_types, hydrate, is_game_card, quality_prior,
)
from tests.forge.conftest import hydrate_one, make_pool, make_record


def test_lander_token_is_not_a_card(oracle):
    assert not is_game_card(oracle["Lander"])


def test_land_detection_is_whole_word():
    assert front_types("Token Artifact — Lander")[0] == frozenset({"Token", "Artifact"})
    assert "Land" in front_types("Basic Land — Forest")[0]


def test_front_types_first_face_only():
    types, subtypes = front_types("Creature — Human Rogue // Land")
    assert types == frozenset({"Creature"}) and subtypes == ("Human", "Rogue")


def test_mdfc_land_back_counts_as_spell(oracle, rules):
    card = hydrate_one(oracle["Blackbloom Rogue // Blackbloom Bog"], rules["commander"])
    assert not card.is_land and card.mdfc_land_back and card.color_identity == frozenset({"B"})


def test_basic_land(oracle, rules):
    card = hydrate_one(oracle["Forest"], rules["commander"])
    assert card.is_land and card.is_basic and not card.mdfc_land_back


def test_printings_merge_by_oracle_id(rules):
    a = make_record("Bolt", oracle_text="Deal 3.")
    b = dict(a, id="other-print")
    collection = [{"scryfall_id": a["id"], "quantity": "2"}, {"scryfall_id": b["id"], "quantity": 1}]
    cards = hydrate(collection, {a["id"]: a, b["id"]: b}, rules["modern"])
    assert len(cards) == 1 and cards[0].owned == 3


def test_missing_ids_skipped(rules):
    a = make_record("Bolt")
    cards = hydrate([{"scryfall_id": "nope", "quantity": 1},
                     {"scryfall_id": a["id"], "quantity": 1}], {a["id"]: a}, rules["modern"])
    assert [c.name for c in cards] == ["Bolt"]


def test_illegal_cards_dropped_and_restricted_kept(rules):
    only_cmdr = make_record("Cmdr Only", legal=("commander",))
    vintage = make_record("Black Lotus", legal=())
    vintage["legalities"]["vintage"] = "restricted"
    collection, index = make_pool([only_cmdr, vintage])
    pauper = hydrate(collection, index, rules["pauper"])
    assert pauper == []
    cmdr = hydrate(collection, index, rules["commander"])
    assert [c.name for c in cmdr] == ["Cmdr Only"]
    vint = hydrate(collection, index, rules["vintage"])
    assert [(c.name, c.legality) for c in vint] == [("Black Lotus", "restricted")]


def test_casual_has_no_legality_filter(rules):
    card = make_record("Nowhere", legal=())
    collection, index = make_pool([card])
    cards = hydrate(collection, index, rules["casual"])
    assert len(cards) == 1 and cards[0].legality == "legal"


def test_quality_prior_bounds():
    assert quality_prior(None) == 0.5 and quality_prior(1) == 1.0 and quality_prior(10**6) == 0.0


def test_any_number_flag(oracle, rules):
    assert hydrate_one(oracle["Relentless Rats"], rules["modern"]).any_number


def test_pips_hybrid_counts_each_color(rules):
    card = hydrate_one(make_record("Hybrid", mana_cost="{2}{G/W}{G}{B/P}"), rules["modern"])
    assert card.pips == {"G": 2, "W": 1, "B": 1}


def test_price_uses_first_available(rules):
    rec = make_record("Priced")
    rec["prices"] = {"usd": "1.50", "usd_foil": "3.00", "eur": None, "tix": "0.2"}
    assert hydrate_one(rec, rules["modern"]).price == 1.5
    rec["prices"] = {"usd": None, "usd_foil": "3.00", "eur": "2.00", "tix": None}
    assert hydrate_one(rec, rules["modern"]).price == 3.0
    assert hydrate_one(make_record("Free"), rules["modern"]).price is None


def test_castable_in_reads_only_the_mana_cost(oracle, rules):
    modern = rules["modern"]
    gw = frozenset("GW")
    bogle = hydrate_one(oracle["Slippery Bogle"], modern)  # {G/U}
    assert bogle.color_identity == frozenset("GU")
    assert castable_in(bogle, gw) and fits_colors(bogle, gw, modern)
    assert not fits_colors(bogle, gw, rules["commander"])
    ability = hydrate_one(make_record("Blue Ability Bear", mana_cost="{1}{G}",
                                      oracle_text="{U}: Draw a card.", color_identity=("G", "U")),
                          modern)
    assert fits_colors(ability, gw, modern) and not fits_colors(ability, gw, rules["commander"])
    for cost in ("{W/P}", "{2/U}", "{X}{C}", "{3}", ""):
        card = hydrate_one(make_record("Odd Cost", mana_cost=cost, color_identity=()), modern)
        assert castable_in(card, frozenset("G")), cost
    for cost in ("{1}{U}", "{U/R}", "{G}{B}"):
        card = hydrate_one(make_record("Off Cost", mana_cost=cost, color_identity=()), modern)
        assert not castable_in(card, gw), cost


def test_castable_in_needs_one_castable_face(rules):
    modern = rules["modern"]
    split = hydrate_one(make_record("Fire // Ice", type_line="Instant // Instant",
                                    mana_cost="{1}{R} // {1}{U}", color_identity=("R", "U"),
                                    layout="split"), modern)
    assert castable_in(split, frozenset("R")) and castable_in(split, frozenset("U"))
    assert not castable_in(split, frozenset("G"))
    adventure = hydrate_one(make_record("Off Adventure", mana_cost="{1}{B} // {B}{B}",
                                        color_identity=("B",), layout="adventure"), modern)
    assert not castable_in(adventure, frozenset("GW"))


def test_unowned_cards_are_dropped_after_merge(rules):
    zero = make_record("Zero Copies")
    merged = make_record("Two Prints")
    other = dict(merged, id="other-print")
    collection = [{"scryfall_id": zero["id"], "quantity": 0},
                  {"scryfall_id": merged["id"], "quantity": "0"},
                  {"scryfall_id": other["id"], "quantity": 1},
                  {"scryfall_id": "bad", "quantity": "x"}]
    index = {zero["id"]: zero, merged["id"]: merged, other["id"]: other}
    cards = hydrate(collection, index, rules["modern"])
    assert [(c.name, c.owned) for c in cards] == [("Two Prints", 1)]


def test_a_card_without_a_mana_cost_needs_its_colors(rules):
    vision = make_record("Ancestral Vision", type_line="Sorcery", mana_cost="",
                         color_identity=("U",), oracle_text="Suspend 4—{U}")
    card = hydrate_one(vision, rules["modern"])
    assert not castable_in(card, frozenset("R"))
    assert castable_in(card, frozenset("U"))
    assert not fits_colors(card, frozenset("R"), rules["modern"])


def test_casual_leaves_out_cards_that_never_go_in_a_deck(rules):
    recs = [make_record("Backup Plan", type_line="Conspiracy"),
            make_record("Tomb of Annihilation", type_line="Dungeon"),
            make_record("Bumper Cars", type_line="Artifact — Attraction"),
            make_record("Grizzly Bears", type_line="Creature — Bear")]
    names = [c.name for c in hydrate(*make_pool(recs), rules["casual"])]
    assert names == ["Grizzly Bears"]

from dataclasses import replace

from backend.forge.builder import (
    CORE_SHARE, CORE_SHARE_PLAYSETS, TIER_ANY, TIER_DUAL, TIER_UTILITY, BuildPlan, BuiltDeck,
    DeckEntry, build_deck, copies_for, curve_bucket, fetch_colors, land_colors, land_target,
    land_tier, sacrifices_lands,
)
from backend.forge.cards import hydrate
from backend.forge.graph import Backbone, build_graph
from backend.forge.tagging import tag_cards
from tests.forge.conftest import make_pool, make_record

SAC = "Sacrifice a creature: Scry 1."
DEATH_PAYOFF = "Whenever another creature you control dies, each opponent loses 1 life."
REMOVAL = "Destroy target creature."
DRAW = "Draw two cards."
SHORTFALL = "Only {k} playable nonland cards fit; filled the rest with basic lands."


def cost(colors, cmc, pips=1):
    """A mana cost with `pips` pips of the first color and generic mana for the rest."""
    generic = max(0, cmc - pips)
    return ("{%d}" % generic if generic else "") + ("{%s}" % colors[0]) * pips


def creature(name, n, text="", colors=("G",), cmc=2, pips=1, **kw):
    """A creature with a unique made-up subtype, so no tribe forms by accident."""
    kw.setdefault("type_line", f"Creature — Kind{n}")
    return make_record(name, oracle_text=text, color_identity=colors,
                       mana_cost=cost(colors, cmc, pips), cmc=cmc, **kw)


def spell(name, text, colors=("G",), type_line="Instant", cmc=2, pips=1, **kw):
    return make_record(name, type_line=type_line, oracle_text=text, color_identity=colors,
                       mana_cost=cost(colors, cmc, pips), cmc=cmc, **kw)


def land(name, produced, colors=None, text="", **kw):
    identity = tuple(c for c in produced if c != "C") if colors is None else colors
    return make_record(name, type_line="Land", mana_cost="", oracle_text=text,
                       color_identity=identity, cmc=0, produced=produced, **kw)


def basic(name, color):
    return make_record(name, type_line=f"Basic Land — {name}", mana_cost="",
                       color_identity=(color,), cmc=0, produced=(color,))


def tagged(playbook, fmt, records, quantities=None):
    cards = hydrate(*make_pool(records, quantities), playbook.formats[fmt])
    tag_cards(cards, playbook)
    return cards


def by_name(cards):
    return {c.name: c for c in cards}


def backbone(cards, names, colors, commander=None):
    return Backbone(id="test", hooks=("death",), name="Aristocrats",
                    members=[c.id for c in cards if c.name in names],
                    colors=frozenset(colors),
                    commander_id=commander.id if commander else None, score=1.0)


def build(playbook, fmt, cards, bone, playstyle="midrange", **plan_kw):
    graph = build_graph(cards, playbook)
    plan = BuildPlan(backbone=bone, playstyle=playstyle, **plan_kw)
    return build_deck(cards, graph, playbook, plan, playbook.formats[fmt])


def gw_records(bears=30):
    recs = [creature(f"Sac Outlet {i}", i, SAC, colors=("GW"[i % 2],)) for i in range(6)]
    recs += [creature(f"Death Payoff {i}", 10 + i, DEATH_PAYOFF, colors=("GW"[i % 2],))
             for i in range(6)]
    recs += [creature(f"Bear {i}", 100 + i, colors=("GW"[i % 2],), cmc=1 + i % 5)
             for i in range(bears)]
    recs += [spell(f"Removal {i}", REMOVAL, colors=("W",)) for i in range(8)]
    recs += [spell(f"Insight {i}", DRAW, colors=("G",), type_line="Sorcery", cmc=3)
             for i in range(6)]
    return recs


CORE_NAMES = {f"Sac Outlet {i}" for i in range(6)} | {f"Death Payoff {i}" for i in range(6)}


def basics(deck):
    return {e.name: e.count for e in deck.entries if e.basic}


def test_no_tokens_offcolor_or_illegal_cards(playbook):
    recs = gw_records()
    recs += [
        make_record("Lander", type_line="Token Artifact — Lander", layout="token",
                    color_identity=(), mana_cost="", cmc=0),
        make_record("Bog Awakening // Bog Ground", type_line="Sorcery // Land",
                    layout="modal_dfc", color_identity=("B",), mana_cost="{2}{B}", cmc=3,
                    oracle_text="Draw two cards.\n//\n{T}: Add {B}.", rank=10),
        creature("Gilded Rare", 900, DEATH_PAYOFF, colors=("G",), rank=1, rarity="rare",
                 legal=("commander", "modern", "standard")),
        land("Selesnya Grove", ("G", "W")),
        land("Swamp Cave", ("B",)),  # off-color identity
        land("Red Spring", ("R",), colors=()),  # colorless identity, makes only off-color mana
        land("Gruul Path", ("G", "R")),  # makes G, but its identity has R
        basic("Forest", "G"),
    ]
    cards = tagged(playbook, "pauper", recs, [4] * len(recs))
    names = {c.name for c in cards}
    assert "Lander" not in names and "Gilded Rare" not in names  # hydrate drops them
    # The builder also rejects a token and an illegal card that reach it.
    seed = by_name(cards)["Death Payoff 0"]  # a synergy card, so only the filter keeps it out
    cards.append(replace(seed, id="inj-token", oracle_id="inj-token", name="Injected Token",
                         types=frozenset({"Token", "Creature"}), quality=1.0))
    cards.append(replace(seed, id="inj-illegal", oracle_id="inj-illegal",
                         name="Injected Illegal", legality="banned", quality=1.0))
    bone = backbone(cards, CORE_NAMES | {"Injected Token", "Injected Illegal"}, "GW")
    deck = build(playbook, "pauper", cards, bone)

    assert deck.total() == 60
    banned = {"lander", "bog awakening // bog ground", "gilded rare", "swamp cave",
              "red spring", "gruul path", "injected token", "injected illegal"}
    assert not banned & deck.names()
    for entry in deck.entries:
        if entry.basic:
            assert entry.card is None and entry.name in {"Forest", "Plains"}
            continue
        card = entry.card
        assert card.owned >= entry.count
        assert card.legality in ("legal", "restricted")
        assert "Token" not in card.types and not card.is_basic
        assert card.color_identity <= frozenset("GW")
        if card.is_land:  # a source for a deck color, or a colorless utility land
            assert land_colors(card, frozenset("GW")) or card.produced_mana <= {"C"}
    assert "selesnya grove" in deck.names()


def test_deck_size_exact_and_singleton(playbook):
    captain = creature("Selesnya Captain", 999, DEATH_PAYOFF, colors=("G", "W"), cmc=4,
                       type_line="Legendary Creature — Kind999")
    recs = [captain] + gw_records(bears=60)
    recs += [creature("Blue Thing", 950, DEATH_PAYOFF, colors=("U",), rank=1),
             land("Selesnya Grove", ("G", "W")), land("Gruul Path", ("G", "R"))]
    cards = tagged(playbook, "commander", recs, [3] * len(recs))
    commander = by_name(cards)["Selesnya Captain"]
    # Backbone colors are wider than the commander; the commander identity wins.
    bone = backbone(cards, CORE_NAMES, "GWU", commander)
    deck = build(playbook, "commander", cards, bone, commander=commander)

    assert deck.total() == 100
    assert sum(e.count for e in deck.entries) == 99
    assert deck.commander is commander
    assert all(e.count == 1 for e in deck.entries if not e.basic)
    assert all(e.card is None or e.card.id != commander.id for e in deck.entries)
    assert "selesnya captain" in deck.names()
    assert "blue thing" not in deck.names() and "gruul path" not in deck.names()
    lands = sum(e.count for e in deck.entries if e.basic or e.role == "land")
    assert lands == deck.land_target
    assert 36 <= deck.land_target <= 38


def test_constructed_respects_owned_copies(playbook, rules):
    recs = gw_records(bears=10)
    recs += [
        creature("Pair Card", 500, colors=("G",)),
        creature("Rat Pack", 501, "A deck can have any number of cards named Rat Pack.",
                 colors=("G",)),
        creature("Many Card", 502, colors=("G",)),
    ]
    quantities = [1] * (len(recs) - 3) + [2, 7, 6]
    cards = tagged(playbook, "modern", recs, quantities)
    bone = backbone(cards, CORE_NAMES, "GW")
    deck = build(playbook, "modern", cards, bone,
                 required={"Pair Card", "rat pack", "Many Card"})
    counts = {e.name: e.count for e in deck.entries}
    assert counts["Pair Card"] == 2
    assert counts["Rat Pack"] == 7
    assert counts["Many Card"] == 4
    assert deck.total() == 60

    pool = by_name(cards)
    assert copies_for(pool["Rat Pack"], rules["modern"]) == 7
    assert copies_for(pool["Many Card"], rules["modern"]) == 4
    assert copies_for(pool["Rat Pack"], rules["commander"]) == 1
    restricted = replace(pool["Many Card"], legality="restricted")
    assert copies_for(restricted, rules["modern"]) == 1


def test_land_target_formula(rules):
    assert land_target(rules["modern"], 2.0, 0) == 22
    assert land_target(rules["commander"], 3.0, 2) == 36
    assert land_target(rules["modern"], 5.0, 0) == 25
    assert land_target(rules["modern"], 3.0, 3) == 22


def test_curve_bucket():
    assert curve_bucket(0) == "1"
    assert curve_bucket(1) == "1"
    assert curve_bucket(4) == "4"
    assert curve_bucket(7) == "6+"


def test_basics_floor_and_split_by_pips(playbook):
    # 38 nonland copies (avg mana value 70/38 = 1.84) fill the 38 slots of a 22-land deck.
    # Pips: G = 8 cards x 4 copies x 2 = 64, W = 6 copies x 1 = 6.
    recs = [creature(f"Green Beast {i}", 600 + i, colors=("G",), pips=2) for i in range(8)]
    recs += [spell("White Ward A", REMOVAL, colors=("W",), cmc=1),
             spell("White Ward B", REMOVAL, colors=("W",), cmc=1)]
    recs += [land(f"Grove {i}", ("G", "W")) for i in range(8)]
    quantities = [4] * 8 + [4, 2] + [4] * 8
    cards = tagged(playbook, "modern", recs, quantities)
    deck = build(playbook, "modern", cards, backbone(cards, set(), "GW"))

    assert deck.total() == 60
    assert deck.land_target == 22
    assert sum(e.count for e in deck.nonland_entries()) == 38
    # Nonbasics stop at 22 - floor 6 = 16 (four Groves x 4).
    assert sum(e.count for e in deck.entries if e.role == "land") == 16
    # 6 basics: G share 6 * 64/70 = 5.49, W share 0.51. Floors 5 and 0; the
    # last basic goes to the larger remainder (W 0.51 > G 0.49).
    assert basics(deck) == {"Forest": 5, "Plains": 1}
    assert "Add 6 basic lands: 1 Plains, 5 Forest" in deck.notes
    assert deck.warnings == []  # G: 16 + 5 = 21 sources, W: 16 + 1 = 17


def test_utility_land_limit(playbook):
    recs = [creature(f"Green Beast {i}", 600 + i, colors=("G",)) for i in range(12)]
    recs += [land(f"Utility {i}", ("C",), text="{T}: Add {C}.", rank=1) for i in range(5)]
    cards = tagged(playbook, "modern", recs, [4] * len(recs))
    deck = build(playbook, "modern", cards, backbone(cards, set(), "G"))
    utility = sum(e.count for e in deck.entries if e.name.startswith("Utility"))
    assert utility == 2
    assert deck.total() == 60


def test_required_and_prefer(playbook):
    recs = [creature(f"Strong {i}", 700 + i, colors=("GW"[i % 2],), rank=100)
            for i in range(36)]
    recs += [
        creature("Odd Vanilla", 800, colors=("G",), rank=39000),
        creature("Alpha Twin", 801, colors=("G",), rank=30000),
        creature("Zeta Twin", 802, colors=("G",), rank=30000),
    ]
    cards = tagged(playbook, "modern", recs)
    deck = build(playbook, "modern", cards, backbone(cards, set(), "GW"),
                 required={"Odd Vanilla"}, prefer={"Zeta Twin"})
    assert deck.land_target == 22
    assert "odd vanilla" in deck.names()
    assert "zeta twin" in deck.names()
    assert "alpha twin" not in deck.names()
    assert by_name(cards)["Alpha Twin"].id in deck.bench


def test_required_card_outside_pool_warns(playbook):
    recs = gw_records(bears=10) + [creature("Blue Thing", 950, colors=("U",))]
    cards = tagged(playbook, "modern", recs)
    deck = build(playbook, "modern", cards, backbone(cards, CORE_NAMES, "GW"),
                 required={"Blue Thing", "Invented Card"})
    assert "blue thing" not in deck.names()
    assert any("Blue Thing" in w for w in deck.warnings)
    assert any("Invented Card" in w for w in deck.warnings)


def test_quota_creatures_for_aggro(playbook):
    recs = [creature(f"Grunt {i}", 400 + i, colors=("R",), rank=20000) for i in range(10)]
    recs += [spell(f"Shiny Charm {i}", "You gain 3 life.", colors=("R",),
                   type_line="Enchantment", rank=10) for i in range(15)]
    cards = tagged(playbook, "modern", recs, [4] * len(recs))
    deck = build(playbook, "modern", cards, backbone(cards, set(), "R"), playstyle="aggro")
    creatures = sum(e.count for e in deck.nonland_entries() if "Creature" in e.card.types)
    assert creatures >= 18


def test_build_small_pool_reports_shortfall(playbook):
    recs = [creature(f"Tiny {i}", 300 + i, colors=("GW"[i % 2],)) for i in range(5)]
    recs.append(land("Selesnya Grove", ("G", "W")))
    tiny_pauper_pool = tagged(playbook, "pauper", recs)
    deck = build(playbook, "pauper", tiny_pauper_pool, backbone(tiny_pauper_pool, set(), "GW"))
    assert any("only" in w.lower() for w in deck.warnings) and deck.total() == 60  # basics fill
    assert SHORTFALL.format(k=5) in deck.warnings


def test_color_source_warning(playbook):
    recs = [creature(f"Green Beast {i}", 600 + i, colors=("G",), pips=2) for i in range(30)]
    recs += [spell(f"White Ward {i}", REMOVAL, colors=("W",), cmc=1) for i in range(2)]
    cards = tagged(playbook, "modern", recs)
    deck = build(playbook, "modern", cards, backbone(cards, set(), "GW"))
    plains = basics(deck).get("Plains", 0)
    assert plains < 10
    assert f"Only {plains} white sources; 10 recommended." in deck.warnings
    assert not any("green sources" in w for w in deck.warnings)


def test_borderline_and_bench_sizes(playbook):
    cards = tagged(playbook, "modern", gw_records(bears=60))
    deck = build(playbook, "modern", cards, backbone(cards, CORE_NAMES, "GW"))
    placed = {e.card.id for e in deck.nonland_entries()}
    assert 0 < len(deck.borderline_in) <= 15
    assert 0 < len(deck.bench) <= 15
    assert not set(deck.borderline_in) & set(deck.bench)
    assert set(deck.borderline_in) <= placed
    assert not set(deck.bench) & placed


def test_entry_shapes(playbook):
    cards = tagged(playbook, "modern", gw_records())
    deck = build(playbook, "modern", cards, backbone(cards, CORE_NAMES, "GW"))
    assert isinstance(deck, BuiltDeck)
    assert all(isinstance(e, DeckEntry) for e in deck.entries)
    roles = {e.role for e in deck.entries}
    assert "core" in roles and "basic" in roles
    assert {e.name for e in deck.entries if e.role == "core"} <= CORE_NAMES
    for entry in deck.nonland_entries():
        assert not entry.basic and not entry.card.is_land
    assert deck.commander is None


WILDS = ("{T}, Sacrifice this land: Search your library for a basic land card, put it onto "
         "the battlefield tapped, then shuffle.")
HEATH = ("{T}, Pay 1 life, Sacrifice this land: Search your library for a Forest or Plains "
         "card, put it onto the battlefield, then shuffle.")


TOWER_TEXT = "{T}: Add one mana of any color in your commander's color identity."


def any_color_lands(count=5):
    """Command Tower plus other lands that make all five colors, all of top quality."""
    recs = [land("Command Tower", ("W", "U", "B", "R", "G"), colors=(), text=TOWER_TEXT,
                 rank=1)]
    recs += [land(f"Prism Land {i}", ("W", "U", "B", "R", "G"), colors=(), rank=2)
             for i in range(count)]
    return recs


def any_color_count(deck):
    return sum(e.count for e in deck.entries
               if e.name == "Command Tower" or e.name.startswith("Prism Land"))


def test_two_color_sixty_takes_no_any_color_lands(playbook):
    recs = [creature(f"Green Beast {i}", 600 + i, colors=("G",)) for i in range(20)]
    recs += [spell(f"White Ward {i}", REMOVAL, colors=("W",)) for i in range(20)]
    recs += any_color_lands(5)  # 6 any-color lands
    recs += [land("Grove A", ("G", "W"), rank=30000), land("Grove B", ("G", "W"), rank=30000)]
    cards = tagged(playbook, "modern", recs, [1] * 40 + [4] * 8)
    tower = by_name(cards)["Command Tower"]
    assert land_colors(tower, frozenset("GW")) == frozenset("GW")
    deck = build(playbook, "modern", cards, backbone(cards, set(), "GW"))
    assert any_color_count(deck) == 0
    counts = {e.name: e.count for e in deck.entries}
    assert counts["Grove A"] == 4 and counts["Grove B"] == 4
    assert sum(basics(deck).values()) >= 6
    assert deck.total() == 60


def test_hundred_card_two_color_takes_at_most_three_any_color(playbook):
    captain = creature("Selesnya Captain", 999, colors=("G", "W"), cmc=4,
                       type_line="Legendary Creature — Kind999")
    recs = [captain] + gw_records(bears=60) + any_color_lands(5)
    recs += [land("Grove A", ("G", "W")), land("Grove B", ("G", "W"))]
    cards = tagged(playbook, "commander", recs)
    commander = by_name(cards)["Selesnya Captain"]
    deck = build(playbook, "commander", cards, backbone(cards, CORE_NAMES, "GW", commander),
                 commander=commander)
    assert any_color_count(deck) == 3
    tower = [e for e in deck.entries if e.name == "Command Tower"]
    assert tower and tower[0].reason == "Makes W/G mana."
    assert {"grove a", "grove b"} <= deck.names()
    assert deck.total() == 100


def test_three_color_sixty_takes_at_most_two_any_color(playbook):
    recs = [creature(f"Beast {i}", 600 + i, colors=("GWU"[i % 3],)) for i in range(40)]
    recs += any_color_lands(5)
    cards = tagged(playbook, "modern", recs, [1] * 40 + [4] * 6)
    deck = build(playbook, "modern", cards, backbone(cards, set(), "GWU"))
    assert any_color_count(deck) == 2
    assert deck.total() == 60


def test_single_color_nonbasics_respect_utility_limit(playbook):
    recs = [creature(f"Green Beast {i}", 600 + i, colors=("G",)) for i in range(20)]
    recs += [spell(f"White Ward {i}", REMOVAL, colors=("W",)) for i in range(20)]
    recs += [land(f"Mono Grove {i}", ("G",), rank=1) for i in range(5)]
    recs += [land(f"Rogue Path {i}", ("C",), rank=1) for i in range(2)]
    recs.append(land("Grove A", ("G", "W"), rank=30000))
    cards = tagged(playbook, "modern", recs, [1] * 40 + [4] * 8)
    deck = build(playbook, "modern", cards, backbone(cards, set(), "GW"))
    counts = {e.name: e.count for e in deck.entries}
    tier3 = sum(n for name, n in counts.items()
                if name.startswith("Mono Grove") or name.startswith("Rogue Path"))
    assert tier3 == 2  # single-color and colorless lands share the utility limit of 2
    assert counts["Grove A"] == 4  # the dual goes first despite its low quality
    assert deck.total() == 60


def test_basic_fetch_is_a_source_and_not_utility(playbook):
    recs = [creature(f"Green Beast {i}", 600 + i, colors=("G",)) for i in range(20)]
    recs += [spell(f"White Ward {i}", REMOVAL, colors=("W",)) for i in range(20)]
    recs += [land(f"Utility {i}", ("C",), text="{T}: Add {C}.", rank=1) for i in range(5)]
    recs.append(land("Evolving Wilds", (), text=WILDS, rank=40000))
    cards = tagged(playbook, "modern", recs, [4] * len(recs))
    wilds = by_name(cards)["Evolving Wilds"]
    assert fetch_colors(wilds, frozenset("GW")) == frozenset("GW")
    assert land_colors(wilds, frozenset("GWU")) == frozenset("GWU")
    deck = build(playbook, "modern", cards, backbone(cards, set(), "GW"))
    counts = {e.name: e.count for e in deck.entries}
    assert counts["Evolving Wilds"] == 4  # not held back by the utility limit of 2
    assert sum(n for name, n in counts.items() if name.startswith("Utility")) == 2


def test_named_type_fetch_counts_for_those_colors(playbook):
    heath = land("Verdant Heath", (), text=HEATH)
    cards = tagged(playbook, "modern", [heath])
    assert land_colors(cards[0], frozenset("GWU")) == frozenset("GW")
    assert land_colors(cards[0], frozenset("G")) == frozenset("G")

    # 36 green creatures and 2 white spells fill the 38 slots of a 22-land deck.
    recs = [creature(f"Green Beast {i}", 600 + i, colors=("G",), pips=2) for i in range(36)]
    recs += [spell(f"White Ward {i}", REMOVAL, colors=("W",), cmc=1) for i in range(2)]
    recs.append(heath)
    cards = tagged(playbook, "modern", recs, [1] * 38 + [4])
    deck = build(playbook, "modern", cards, backbone(cards, set(), "GW"))
    # 18 basics split 72:2 → 18 Forest, 0 Plains. The 4 fetches are the only W sources.
    assert basics(deck) == {"Forest": 18}
    assert {e.name: e.count for e in deck.entries}["Verdant Heath"] == 4
    assert "Only 4 white sources; 10 recommended." in deck.warnings
    assert not any("green" in w for w in deck.warnings)  # 18 + 4 = 22 sources


def test_duplicate_required_names_place_one_copy(playbook):
    ring = make_record("Sol Ring", type_line="Artifact", mana_cost="{1}", cmc=1,
                       color_identity=(), oracle_text="{T}: Add {C}{C}.")
    captain = creature("Selesnya Captain", 999, colors=("G", "W"), cmc=4,
                       type_line="Legendary Creature — Kind999")
    cards = tagged(playbook, "commander", [captain, ring] + gw_records(), [3] * 58)
    commander = by_name(cards)["Selesnya Captain"]
    deck = build(playbook, "commander", cards, backbone(cards, CORE_NAMES, "GW", commander),
                 commander=commander, required={"Sol Ring", "sol ring "})
    assert sum(e.count for e in deck.entries if e.name == "Sol Ring") == 1
    assert deck.total() == 100


def test_required_cards_that_do_not_fit_warn(playbook):
    recs = [creature(f"Big {i:02d}", 650 + i, colors=("G",)) for i in range(12)]
    recs += [land(f"Utility {i}", ("C",), text="{T}: Add {C}.") for i in range(3)]
    cards = tagged(playbook, "modern", recs, [4] * len(recs))
    names = {f"Big {i:02d}" for i in range(12)} | {f"Utility {i}" for i in range(3)}
    deck = build(playbook, "modern", cards, backbone(cards, set(), "G"), required=names)
    # 12 x 4 copies do not fit in 38 slots: Big 00-08 fill 36, Big 09 gets 2, 10-11 none.
    assert {e.name: e.count for e in deck.entries}["Big 09"] == 2
    assert "Couldn't fit Big 10: no room left in the deck." in deck.warnings
    assert "Couldn't fit Big 11: no room left in the deck." in deck.warnings
    assert not any("Big 09" in w for w in deck.warnings)
    # The utility limit is 2 copies: Utility 0 takes both, the others warn.
    assert "Couldn't fit Utility 1: the utility land limit is full." in deck.warnings
    assert "Couldn't fit Utility 2: the utility land limit is full." in deck.warnings
    assert deck.total() == 60


def test_commander_ignored_outside_commander_formats(playbook):
    captain = creature("Selesnya Captain", 999, colors=("G", "W"), cmc=4,
                       type_line="Legendary Creature — Kind999")
    cards = tagged(playbook, "modern", [captain] + gw_records())
    commander = by_name(cards)["Selesnya Captain"]
    deck = build(playbook, "modern", cards, backbone(cards, CORE_NAMES, "GW"),
                 commander=commander)
    assert deck.commander is None
    assert deck.total() == 60
    assert sum(e.count for e in deck.entries) == 60


def test_land_tiers(playbook):
    recs = any_color_lands(0) + [
        land("Grove", ("G", "W")), land("Mono Grove", ("G",)), land("Rogue Path", ("C",)),
        land("Evolving Wilds", (), text=WILDS), land("Wild Ground", ("G", "R"), colors=()),
        land("Red Spring", ("R",), colors=()), land("Pain Grove", ("G", "W", "C")),
    ]
    cards = by_name(tagged(playbook, "modern", recs))
    gw = frozenset("GW")
    assert land_tier(cards["Grove"], gw) == TIER_DUAL
    assert land_tier(cards["Pain Grove"], gw) == TIER_DUAL
    assert land_tier(cards["Evolving Wilds"], gw) == TIER_DUAL
    assert land_tier(cards["Command Tower"], gw) == TIER_ANY
    assert land_tier(cards["Wild Ground"], gw) == TIER_ANY
    assert land_tier(cards["Mono Grove"], gw) == TIER_UTILITY
    assert land_tier(cards["Rogue Path"], gw) == TIER_UTILITY
    assert land_tier(cards["Mono Grove"], frozenset("G")) == TIER_UTILITY  # no duals in mono
    assert land_tier(cards["Red Spring"], gw) is None


def test_true_lands_rank_before_any_color_lands(playbook):
    # 3 colors, 60 cards: nonbasics stop at 22 - 9 = 13. Low-quality tri-lands (16 copies)
    # fill all 13 before the top-quality any-color lands, which cover the same 3 colors.
    recs = [creature(f"Beast {i}", 600 + i, colors=("GWU"[i % 3],)) for i in range(40)]
    recs += any_color_lands(5)
    recs += [land(f"Tri Land {i}", ("G", "W", "U"), rank=39000) for i in range(4)]
    cards = tagged(playbook, "modern", recs, [1] * 40 + [4] * 10)
    deck = build(playbook, "modern", cards, backbone(cards, set(), "GWU"))
    assert deck.land_target == 22
    assert sum(e.count for e in deck.entries if e.name.startswith("Tri Land")) == 13
    assert any_color_count(deck) == 0
    assert sum(basics(deck).values()) == 9


def test_sixty_card_core_alternates_enablers_and_payoffs(playbook):
    # By synergy into the whole core, outlets (10 payoffs * 1.5) beat payoffs
    # (6 outlets * 1.5) and would fill the core alone. Each next member counts
    # its synergy into the placed cards, so outlets and payoffs alternate.
    recs = [creature(f"Sac Outlet {i}", i, SAC) for i in range(6)]
    recs += [creature(f"Death Payoff {i:02d}", 10 + i, DEATH_PAYOFF) for i in range(10)]
    recs += [creature(f"Bear {i}", 100 + i, cmc=1 + i % 4) for i in range(10)]
    recs += [spell(f"Removal {i}", REMOVAL) for i in range(4)]
    recs += [spell(f"Insight {i}", DRAW, type_line="Sorcery", cmc=3) for i in range(2)]
    cards = tagged(playbook, "modern", recs, [4] * len(recs))
    names = {f"Sac Outlet {i}" for i in range(6)} | {f"Death Payoff {i:02d}" for i in range(10)}
    deck = build(playbook, "modern", cards, backbone(cards, names, "G"))
    core = [e for e in deck.entries if e.role == "core"]
    outlets = sum(e.count for e in core if e.name.startswith("Sac Outlet"))
    payoffs = sum(e.count for e in core if e.name.startswith("Death Payoff"))
    assert abs(outlets - payoffs) <= 4
    # Formats with copies give the core CORE_SHARE_PLAYSETS (0.6) of the nonland slots.
    nonland = sum(e.count for e in deck.nonland_entries())
    assert outlets + payoffs > CORE_SHARE * nonland
    assert outlets + payoffs <= CORE_SHARE_PLAYSETS * nonland + 4


def test_land_that_sacrifices_lands_ranks_last_in_its_tier(playbook, oracle):
    field = oracle["Lotus Field"]
    assert sacrifices_lands(by_name(tagged(playbook, "commander", [field]))["Lotus Field"])
    captain = creature("Selesnya Captain", 999, colors=("G", "W"), cmc=4,
                       type_line="Legendary Creature — Kind999")
    recs = [captain] + gw_records(bears=60) + any_color_lands(2)  # 3 any-color lands
    recs.append(land("Lotus Bloom Field", ("W", "U", "B", "R", "G"), colors=(), rank=1,
                     text="Hexproof\nThis land enters tapped.\nWhen this land enters, sacrifice "
                          "two untapped lands.\n{T}: Add three mana of any one color."))
    cards = tagged(playbook, "commander", recs)
    commander = by_name(cards)["Selesnya Captain"]
    deck = build(playbook, "commander", cards, backbone(cards, CORE_NAMES, "GW", commander),
                 commander=commander)
    assert any_color_count(deck) == 3
    assert "lotus bloom field" not in deck.names()


def test_sixty_card_colors_follow_the_mana_cost(playbook, oracle):
    ability = creature("Blue Ability Bear", 701, "{U}: Draw a card.", colors=("G", "U"))
    mite = make_record("Phyrexian Mite", type_line="Creature — Mite", mana_cost="{W/P}",
                       color_identity=("W",), cmc=1)
    recs = [oracle["Slippery Bogle"], ability, mite] + gw_records()
    cards = tagged(playbook, "modern", recs, [4] * len(recs))
    wanted = {"Slippery Bogle", "Blue Ability Bear", "Phyrexian Mite"}
    deck = build(playbook, "modern", cards, backbone(cards, set(), "GW"), required=wanted)
    assert {n.lower() for n in wanted} <= deck.names()
    assert not deck.warnings or all("left it out" not in w for w in deck.warnings)
    mono = build(playbook, "modern", cards, backbone(cards, set(), "G"), required={"Phyrexian Mite"})
    assert "phyrexian mite" in mono.names()


def test_commander_colors_follow_the_color_identity(playbook, oracle):
    captain = creature("Selesnya Captain", 999, colors=("G", "W"), cmc=4,
                       type_line="Legendary Creature — Kind999")
    recs = [captain, oracle["Slippery Bogle"]] + gw_records(bears=60)
    cards = tagged(playbook, "commander", recs)
    commander = by_name(cards)["Selesnya Captain"]
    deck = build(playbook, "commander", cards, backbone(cards, CORE_NAMES, "GW", commander),
                 commander=commander, required={"Slippery Bogle"})
    assert "slippery bogle" not in deck.names()
    assert any(w.startswith("Slippery Bogle is not") for w in deck.warnings)

from dataclasses import replace

from backend.forge.builder import (
    BuildPlan, BuiltDeck, DeckEntry, build_deck, copies_for, curve_bucket, land_target,
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


def demand(deck):
    pips = {}
    cards = [(e.card, e.count) for e in deck.nonland_entries()]
    if deck.commander is not None:
        cards.append((deck.commander, 1))
    for card, count in cards:
        for color, n in card.pips.items():
            pips[color] = pips.get(color, 0) + n * count
    return pips


def largest_remainder(total, weights):
    whole = sum(weights.values())
    shares = {c: total * w / whole for c, w in weights.items()}
    split = {c: int(s) for c, s in shares.items()}
    order = sorted(weights, key=lambda c: (-(shares[c] - split[c]), "WUBRG".index(c)))
    for c in order[:total - sum(split.values())]:
        split[c] += 1
    return split


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
        land("Swamp Cave", ("B",)),
        land("Wild Ground", ("G", "R"), colors=()),
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
              "wild ground", "injected token", "injected illegal"}
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
        if card.is_land:
            assert card.produced_mana <= frozenset("GWC")
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
    recs = [creature(f"Green Beast {i}", 600 + i, colors=("G",), pips=2) for i in range(12)]
    recs += [spell(f"White Ward {i}", REMOVAL, colors=("W",), cmc=1) for i in range(4)]
    recs += [land(f"Grove {i}", ("G", "W")) for i in range(8)]
    cards = tagged(playbook, "modern", recs, [4] * len(recs))
    bone = backbone(cards, set(), "GW")
    deck = build(playbook, "modern", cards, bone)

    assert deck.total() == 60
    split = basics(deck)
    assert sum(split.values()) >= 6
    nonbasic = sum(e.count for e in deck.entries if e.role == "land")
    assert nonbasic <= deck.land_target - 6
    assert split == {k: v for k, v in {
        "Forest": largest_remainder(sum(split.values()), demand(deck))["G"],
        "Plains": largest_remainder(sum(split.values()), demand(deck))["W"],
    }.items() if v}
    assert split["Forest"] > split["Plains"]
    assert any(n.startswith(f"Add {sum(split.values())} basic lands: ") for n in deck.notes)


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

import random
import time

import pytest

from backend.forge.cards import hydrate
from backend.forge.graph import (
    Backbone, Edge, SynergyGraph, build_graph, commander_candidates, find_backbones,
)
from backend.forge.tagging import tag_cards
from tests.forge.conftest import make_pool, make_record

SAC = "Sacrifice a creature: Scry 1."
DEATH_PAYOFF = "Whenever another creature you control dies, each opponent loses 1 life."
AURA = "Enchant creature\nEnchanted creature gets +2/+2."
AURA_PAYOFF = "Whenever you cast an Aura spell, draw a card."


def creature(name, n, text="", colors=("B",), legendary=False, **kw):
    """A creature with a unique made-up subtype, so no tribe forms by accident."""
    prefix = "Legendary Creature" if legendary else "Creature"
    return make_record(name, type_line=f"{prefix} — Kind{n}", oracle_text=text,
                       color_identity=colors, **kw)


def tagged_pool(playbook, records, fmt="commander", quantities=None):
    cards = hydrate(*make_pool(records, quantities), playbook.formats[fmt])
    tag_cards(cards, playbook)
    return cards


def by_name(cards):
    return {c.name: c for c in cards}


def teysa_record():
    return creature("Teysa Karlov", 900, colors=("W", "B"), legendary=True,
                    text="Whenever another creature you control dies, create a 1/1 "
                         "white and black Spirit creature token with flying.")


def aristocrats_records():
    recs = [creature(f"Sac Outlet {i}", i, SAC, colors=("WB"[i % 2],)) for i in range(6)]
    recs += [creature(f"Death Payoff {i}", 10 + i, DEATH_PAYOFF, colors=("WB"[i % 2],))
             for i in range(6)]
    return recs


def noise_records():
    recs = [creature(f"Vanilla {i}", 100 + i, colors=("WUBRG"[i % 5],)) for i in range(12)]
    recs += [creature(f"Life Giver {i}", 200 + i, "When this creature enters, you gain 3 life.",
                      colors=("W",)) for i in range(4)]
    recs += [creature(f"Life Payoff {i}", 300 + i,
                      "Whenever you gain life, put a +1/+1 counter on this creature.",
                      colors=("B",)) for i in range(4)]
    return recs


def test_edges_from_gives_to_wants(oracle, playbook):
    cards = tagged_pool(playbook, [oracle["Viscera Seer"], oracle["Blood Artist"]])
    seer, artist = by_name(cards)["Viscera Seer"], by_name(cards)["Blood Artist"]
    graph = build_graph(cards, playbook)
    death = [e for e in graph.edges if e.hook == "death"]
    assert death == [Edge(src=seer.id, dst=artist.id, hook="death", weight=1.5)]
    assert death[0].source == "engine"
    assert graph.cards[seer.id] is seer
    assert graph.between([seer.id, artist.id]) == death
    assert graph.between([seer.id]) == []
    assert graph.weight_into(seer.id, [artist.id]) == pytest.approx(1.5)
    assert graph.weight_into(artist.id, [seer.id]) == pytest.approx(1.5)  # both directions


def test_plain_want_has_weight_one(playbook):
    giver = creature("Giver", 1, SAC)
    wanter = creature("Wanter", 2, "When this creature dies, draw a card.")
    cards = tagged_pool(playbook, [giver, wanter])
    graph = build_graph(cards, playbook)
    edge = [e for e in graph.edges if e.hook == "death"][0]
    assert edge.weight == 1.0


def test_add_edge_from_model(playbook):
    cards = tagged_pool(playbook, [creature("A", 1), creature("B", 2)])
    graph = build_graph(cards, playbook)
    a, b = cards[0].id, cards[1].id
    assert graph.weight_into(a, [b]) == 0.0
    graph.add_edge(Edge(src=a, dst=b, hook="tokens", weight=0.5, source="model"))
    assert graph.between([a, b])[0].source == "model"
    assert graph.weight_into(b, [a]) == pytest.approx(0.5)


def test_aristocrats_core_wins_over_noise(playbook, rules):
    cards = tagged_pool(playbook, [teysa_record()] + aristocrats_records() + noise_records())
    teysa = by_name(cards)["Teysa Karlov"]
    graph = build_graph(cards, playbook)
    backbones = find_backbones(cards, graph, rules["commander"], playbook, commander_id=teysa.id)
    assert backbones and "death" in backbones[0].hooks
    top = backbones[0]
    assert top.commander_id == teysa.id
    assert top.colors == frozenset("WB")
    assert teysa.id in top.members
    names = {graph.cards[m].name for m in top.members}
    assert not any(n.startswith("Vanilla") for n in names)
    assert {f"Sac Outlet {i}" for i in range(6)} <= names


def test_backbone_id_and_name_are_stable(playbook, rules):
    recs = [teysa_record()] + aristocrats_records() + noise_records()
    results = []
    for _ in range(2):
        cards = tagged_pool(playbook, recs)
        graph = build_graph(cards, playbook)
        teysa = by_name(cards)["Teysa Karlov"]
        results.append(find_backbones(cards, graph, rules["commander"], playbook,
                                      commander_id=teysa.id))
    assert [b.id for b in results[0]] == [b.id for b in results[1]]
    top = results[0][0]
    assert top.id == "death:WB:teysa-karlov"
    assert top.name == "Aristocrats"
    assert top.hooks == ("death",)


def test_overlapping_groups_merge(playbook, rules):
    # Every death payoff also wants tokens, so the two groups share most members.
    both = ("Whenever another creature you control dies, each opponent loses 1 life.\n"
            "This creature gets +1/+1 for each creature you control.")
    recs = [creature(f"Sac Outlet {i}", i, SAC, colors=("B",)) for i in range(5)]
    recs += [creature(f"Payoff {i}", 10 + i, both, colors=("W",)) for i in range(6)]
    recs += [make_record(f"Token Maker {i}", type_line="Sorcery", color_identity=("W",),
                         oracle_text="Create two 1/1 white Soldier creature tokens.")
             for i in range(5)]
    recs.append(teysa_record())
    cards = tagged_pool(playbook, recs)
    teysa = by_name(cards)["Teysa Karlov"]
    graph = build_graph(cards, playbook)
    top = find_backbones(cards, graph, rules["commander"], playbook, commander_id=teysa.id)[0]
    assert top.hooks == ("death", "tokens")
    assert top.name == "Aristocrats & Go-wide tokens"
    assert top.id == "death+tokens:WB:teysa-karlov"


def test_tribal_backbone_name(playbook, rules):
    goblins = [make_record(f"Goblin {i}", type_line="Creature — Goblin", color_identity=("R",),
                           mana_cost="{R}") for i in range(10)]
    lords = [make_record(f"Goblin Lord {i}", type_line="Creature — Orc", color_identity=("R",),
                         oracle_text="Other Goblins you control get +1/+1.") for i in range(2)]
    boss = make_record("Goblin Boss", type_line="Legendary Creature — Orc",
                       color_identity=("R",), oracle_text="Other Goblins you control have haste.")
    cards = tagged_pool(playbook, goblins + lords + [boss])
    graph = build_graph(cards, playbook)
    top = find_backbones(cards, graph, rules["commander"], playbook)[0]
    assert top.hooks == ("tribal:Goblin",)
    assert top.name == "Goblin tribal"


def base_score(graph, members, fmt):
    density = sum(e.weight for e in graph.between(members)) / len(members)
    quality = sum(0.5 + graph.cards[m].quality * fmt.quality_weight for m in members)
    fill = min(1.0, len(members) / fmt.min_core)
    return density * quality * fill


def test_commander_hooks_double_score(playbook, rules):
    plain = creature("Plain Boss", 901, colors=("W", "B"), legendary=True)
    cards = tagged_pool(playbook, [teysa_record(), plain] + aristocrats_records())
    names = by_name(cards)
    graph = build_graph(cards, playbook)
    fmt = rules["commander"]
    teysa_id, plain_id = names["Teysa Karlov"].id, names["Plain Boss"].id
    with_hook = find_backbones(cards, graph, fmt, playbook, commander_id=teysa_id)[0]
    without = find_backbones(cards, graph, fmt, playbook, commander_id=plain_id)[0]
    assert with_hook.hooks == without.hooks == ("death",)
    assert with_hook.score == pytest.approx(2 * base_score(graph, with_hook.members, fmt))
    assert without.score == pytest.approx(base_score(graph, without.members, fmt))
    assert names["Plain Boss"].id not in without.members


def test_commander_scopes_respect_color_identity(playbook, rules):
    mono_w = creature("White Boss", 902, colors=("W",), legendary=True)
    cards = tagged_pool(playbook, [teysa_record(), mono_w] + aristocrats_records())
    graph = build_graph(cards, playbook)
    backbones = find_backbones(cards, graph, rules["commander"], playbook)
    # Only 6 white death cards fit White Boss, fewer than min_core 10.
    assert [b.commander_id for b in backbones] == [by_name(cards)["Teysa Karlov"].id]


def voltron_records():
    recs = [make_record(f"Aura {i}", type_line="Enchantment — Aura", oracle_text=AURA,
                        color_identity=("W",), mana_cost="{W}") for i in range(5)]
    recs += [creature(f"Aura Fan {i}", 20 + i, AURA_PAYOFF, colors=("G",)) for i in range(3)]
    recs += [creature(f"Hexer {i}", 30 + i, "Trample, hexproof", colors=("G",)) for i in range(2)]
    return recs


def spells_records():
    recs = [make_record(f"Bolt {i}", type_line="Instant", color_identity=("R",), mana_cost="{R}",
                        oracle_text="This spell deals 3 damage to any target.") for i in range(6)]
    recs += [creature(f"Prowler {i}", 40 + i, "Prowess", colors=("U",), keywords=("Prowess",))
             for i in range(4)]
    return recs


def test_sixty_scopes_by_color_pair(playbook, rules):
    gw, ur = voltron_records(), spells_records()
    cards = tagged_pool(playbook, gw + ur, fmt="standard",
                        quantities=[4] * len(gw) + [1] * len(ur))
    graph = build_graph(cards, playbook)
    backbones = find_backbones(cards, graph, rules["standard"], playbook)
    # Auras are enchantments too, so the enchantments group merges into voltron.
    assert backbones[0].hooks == ("enchantments", "voltron")
    assert backbones[0].colors == frozenset("GW")
    assert backbones[0].commander_id is None
    assert backbones[0].id == "enchantments+voltron:WG"
    # Ten single copies count as 2.5 playsets, less than min_core / 2 = 4.
    assert not any("spells" in b.hooks for b in backbones)

    cards = tagged_pool(playbook, gw + ur, fmt="standard", quantities=[4] * (len(gw) + len(ur)))
    graph = build_graph(cards, playbook)
    backbones = find_backbones(cards, graph, rules["standard"], playbook)
    spells = [b for b in backbones if "spells" in b.hooks]
    assert spells and spells[0].colors == frozenset("UR")


def test_sixty_drops_duplicate_hook_groups(playbook, rules):
    # The W, B, WB, WU, BG (and more) scopes all hold a death group.
    recs = aristocrats_records()
    cards = tagged_pool(playbook, recs, fmt="standard", quantities=[4] * len(recs))
    graph = build_graph(cards, playbook)
    backbones = find_backbones(cards, graph, rules["standard"], playbook)
    assert [(b.hooks, b.colors) for b in backbones] == [(("death",), frozenset("WB"))]


def test_given_colors_limit_scope(playbook, rules):
    gw, ur = voltron_records(), spells_records()
    cards = tagged_pool(playbook, gw + ur, fmt="standard", quantities=[4] * (len(gw) + len(ur)))
    graph = build_graph(cards, playbook)
    backbones = find_backbones(cards, graph, rules["standard"], playbook,
                               colors=frozenset("UR"))
    assert backbones
    assert all(b.colors == frozenset("UR") for b in backbones)
    assert all("voltron" not in b.hooks for b in backbones)


def test_no_commander_candidates_returns_empty(playbook, rules):
    cards = tagged_pool(playbook, aristocrats_records() + noise_records())
    graph = build_graph(cards, playbook)
    assert commander_candidates(cards) == []
    assert find_backbones(cards, graph, rules["commander"], playbook) == []


def test_commander_candidates(oracle, playbook):
    walker = make_record("Odd Walker", type_line="Legendary Planeswalker — Odd",
                         oracle_text="Odd Walker can be your commander.")
    land = make_record("Legend Land", type_line="Legendary Land")
    cards = tagged_pool(playbook, [teysa_record(), walker, land, creature("Grunt", 1)])
    assert [c.name for c in commander_candidates(cards)] == ["Teysa Karlov", "Odd Walker"]


TEMPLATES = [  # (type line, oracle text, keywords)
    ("Creature — {sub}", SAC, ()),
    ("Creature — {sub}", DEATH_PAYOFF, ()),
    ("Creature — {sub}", "Whenever another creature you control enters, you gain 1 life.", ()),
    ("Creature — {sub}", "Whenever you gain life, put a +1/+1 counter on this creature.", ()),
    ("Sorcery", "Create two 1/1 white Soldier creature tokens.", ()),
    ("Creature — {sub}", "This creature gets +1/+1 for each creature you control.", ()),
    ("Instant", "This spell deals 2 damage to any target.", ()),
    ("Creature — {sub}", "Prowess", ("Prowess",)),
    ("Enchantment — Aura", AURA, ()),
    ("Creature — {sub}", AURA_PAYOFF, ()),
    ("Artifact", "{T}: Put a +1/+1 counter on target creature.", ()),
    ("Creature — {sub}", "", ()),
]
SUBTYPES = ["Goblin", "Elf", "Zombie", "Human", "Vampire", "Soldier", "Wizard", "Knight"]


def big_pool(playbook, size=850, commanders=40):
    rng = random.Random(7)
    identities = ["W", "U", "B", "R", "G", "WB", "UR", "BG", "RW", "GU", "WUB", ""]
    recs = []
    for i in range(size):
        type_line, text, keywords = TEMPLATES[i % len(TEMPLATES)]
        type_line = type_line.format(sub=rng.choice(SUBTYPES))
        if i < commanders:
            type_line = "Legendary " + type_line if "Creature" in type_line else \
                "Legendary Creature — " + rng.choice(SUBTYPES)
        recs.append(make_record(f"Card {i}", type_line=type_line, oracle_text=text,
                                keywords=keywords, color_identity=tuple(rng.choice(identities)),
                                rank=rng.randint(1, 30000)))
    return tagged_pool(playbook, recs)


def test_find_backbones_is_fast_on_a_real_collection_size(playbook, rules):
    cards = big_pool(playbook)
    assert len(commander_candidates(cards)) == 40
    start = time.perf_counter()
    graph = build_graph(cards, playbook)
    built = time.perf_counter()
    backbones = find_backbones(cards, graph, rules["commander"], playbook)
    done = time.perf_counter()
    assert len(graph.edges) > 1000
    assert backbones and all(isinstance(b, Backbone) for b in backbones)
    assert built - start < 2.0
    assert done - built < 2.0
    assert isinstance(graph, SynergyGraph)

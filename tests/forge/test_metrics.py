import pytest

from backend.forge.graph import build_graph
from backend.forge.metrics import curve, deck_metrics
from tests.forge.test_builder import (
    CORE_NAMES, backbone, basic, build, creature, gw_records, land, spell, tagged,
)


def _deck(playbook):
    recs = gw_records() + [land("Selesnya Grove", ("G", "W")), basic("Forest", "G"),
                           basic("Plains", "W")]
    cards = tagged(playbook, "pauper", recs, [4] * len(recs))
    deck = build(playbook, "pauper", cards, backbone(cards, CORE_NAMES, "GW"))
    return deck, build_graph(cards, playbook)


def test_metrics_ranges_and_combined(playbook):
    deck, graph = _deck(playbook)
    m = deck_metrics(deck, graph, playbook)
    for key, value in m.items():
        if key != "synergy_density":
            assert 0.0 <= value <= 1.0, key
    assert m["synergy_density"] > 0
    w = playbook.metric_weights
    expected = (w["synergy"] * min(1.0, m["synergy_density"] / w["synergy_cap"])
                + w["roles"] * m["role_coverage"] + w["curve"] * m["curve_fit"]
                + w["mana"] * m["mana_consistency"] + w["quality"] * m["avg_quality"])
    assert m["combined"] == pytest.approx(expected)


def test_curve_buckets(playbook):
    recs = [creature("Zero", 1, cmc=0), creature("One", 2, cmc=1), creature("Seven", 3, cmc=7)]
    cards = tagged(playbook, "modern", recs)
    deck = build(playbook, "modern", cards, backbone(cards, set(), "G"))
    counts = curve(deck)
    assert list(counts) == ["1", "2", "3", "4", "5", "6+"]
    assert counts["1"] == 2 and counts["6+"] == 1
    assert sum(counts.values()) == 3


def _hand_deck(playbook, forests, plains, spell_colors=("W",)):
    """3 cards of 4 copies: Bear A x2 (cmc 1, q 0.2), Bear B x1 (cmc 3, q 0.8), Removal x1 (cmc 2, q 0.5)."""
    from dataclasses import replace
    from backend.forge.builder import BuildPlan, BuiltDeck, DeckEntry

    recs = [creature("Bear A", 1, cmc=1), creature("Bear B", 2, cmc=3),
            spell("Zap", "Destroy target creature.", colors=spell_colors, cmc=2),
            basic("Forest", "G"), basic("Plains", "W")]
    cards = tagged(playbook, "modern", recs, [4] * len(recs))
    c = {x.name: x for x in cards}
    quality = {"Bear A": 0.2, "Bear B": 0.8, "Zap": 0.5}
    pick = {n: replace(c[n], quality=q) for n, q in quality.items()}
    entries = [DeckEntry(pick["Bear A"], "Bear A", 2, "synergy", ""),
               DeckEntry(pick["Bear B"], "Bear B", 1, "synergy", ""),
               DeckEntry(pick["Zap"], "Zap", 1, "removal", "")]
    for name, n in (("Forest", forests), ("Plains", plains)):
        if n:
            entries.append(DeckEntry(None, name, n, "basic", "", basic=True))
    plan = BuildPlan(backbone=backbone(cards, set(), "GW"), playstyle="midrange")
    custom = {"midrange": {"quotas": {"60": {"creatures": 4, "removal": 2}, "100": {}},
                           "curve": {"1": 0.5, "2": 0.25, "3": 0.0, "4": 0.25, "5": 0.0,
                                     "6+": 0.0}}}
    from dataclasses import replace as rep
    return (BuiltDeck(fmt=playbook.formats["modern"], plan=plan, entries=entries,
                      land_target=24), build_graph(cards, playbook),
            rep(playbook, playstyles=custom))


def test_metrics_exact_values(playbook):
    deck, graph, pb = _hand_deck(playbook, 14, 9)
    m = deck_metrics(deck, graph, pb)
    # creatures: 2 + 1 = 3 of 4; removal: 1 of 2 -> (3 + 1) / (4 + 2)
    assert m["role_coverage"] == pytest.approx(4 / 6)
    # shares: "1" 2/4, "2" 1/4, "3" 1/4; gaps 0 + 0 + .25 (3) + .25 (4) = .5 -> 1 - .25
    assert m["curve_fit"] == pytest.approx(0.75)
    # (0.2 * 2 + 0.8 * 1 + 0.5 * 1) / 4
    assert m["avg_quality"] == pytest.approx(0.425)
    # G pips 2 + 1 = 3, W pips 1: G share .75 primary (14 sources, has 14), W share .25
    # secondary (10 sources, has 9) -> 1 of 2 colors met
    assert m["mana_consistency"] == pytest.approx(0.5)
    deck2, graph2, pb2 = _hand_deck(playbook, 14, 10)
    assert deck_metrics(deck2, graph2, pb2)["mana_consistency"] == pytest.approx(1.0)


def test_curve_counts_copies(playbook):
    deck, _, _ = _hand_deck(playbook, 14, 10)
    # Bear A x2 (cmc 1) -> "1": 2; Zap (cmc 2) -> "2": 1; Bear B (cmc 3) -> "3": 1
    assert curve(deck) == {"1": 2, "2": 1, "3": 1, "4": 0, "5": 0, "6+": 0}

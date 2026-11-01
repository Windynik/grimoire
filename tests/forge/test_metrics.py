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

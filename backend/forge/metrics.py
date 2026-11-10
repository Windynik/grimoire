"""Deck metrics for the deck forge.

Grades a built deck on synergy, role coverage, curve, mana, and card quality.
The UI shows the metrics and the evaluation harness compares decks with them.
Makes no network calls.
"""

from typing import Dict, FrozenSet

from backend.forge.builder import (
    BuiltDeck, curve_bucket, deck_colors, quota_keys, source_shortfalls,
)
from backend.forge.graph import SynergyGraph
from backend.forge.playbook import Playbook

BUCKETS = ("1", "2", "3", "4", "5", "6+")
SYNERGY_CAP = "synergy_cap"  # metric_weights key that caps synergy_density, not a weight
# metric_weights key for each metric
WEIGHT_KEYS = {"synergy_density": "synergy", "role_coverage": "roles", "curve_fit": "curve",
               "mana_consistency": "mana", "avg_quality": "quality"}


# The buckets that the owner sees: 0-drops apart from 1-drops.
DISPLAY_BUCKETS = ("0", "1", "2", "3", "4", "5", "6+")


def display_curve(deck: BuiltDeck) -> Dict[str, int]:
    """Return the nonland cards per mana value for the owner: "0" to "5", then "6+".

    The curve targets of the builder join 0 and 1 (see curve); a 0-drop must
    still show as a 0-drop.
    """
    counts = {bucket: 0 for bucket in DISPLAY_BUCKETS}
    for entry in deck.nonland_entries():
        value = int(entry.card.cmc)
        counts["6+" if value >= 6 else str(max(0, value))] += entry.count
    return counts


def curve(deck: BuiltDeck) -> Dict[str, int]:
    """Return the number of nonland cards per mana value bucket ("1" to "6+").

    Args:
        deck: Built deck.

    Returns:
        Mapping of bucket to card count (copies). Every bucket is present.
    """
    counts = {bucket: 0 for bucket in BUCKETS}
    for entry in deck.nonland_entries():
        counts[curve_bucket(entry.card.cmc)] += entry.count
    return counts


def _synergy_density(deck: BuiltDeck, graph: SynergyGraph) -> float:
    ids = [entry.card.id for entry in deck.nonland_entries()]
    if not ids:
        return 0.0
    if deck.commander is not None:
        ids.append(deck.commander.id)
    return graph.inner_weight(ids) / (len(ids))


def _role_coverage(deck: BuiltDeck, playbook: Playbook) -> float:
    quotas = playbook.quotas(deck.fmt, deck.plan.playstyle)
    total = sum(quotas.values())
    if total <= 0:
        return 1.0
    have = {}  # type: Dict[str, int]
    for entry in deck.nonland_entries():
        for key in quota_keys(entry.card):
            have[key] = have.get(key, 0) + entry.count
    return sum(min(have.get(key, 0), quota) for key, quota in quotas.items()) / total


def _curve_fit(deck: BuiltDeck, playbook: Playbook) -> float:
    target = playbook.curve_target(deck.fmt, deck.plan.playstyle)
    counts = curve(deck)
    copies = sum(counts.values())
    if not copies:
        return 0.0
    gap = sum(abs(counts[b] / copies - target.get(b, 0.0)) for b in BUCKETS)
    return max(0.0, 1 - 0.5 * gap)


def _pip_demand(deck: BuiltDeck, colors: FrozenSet[str]) -> Dict[str, int]:
    cards = [(e.card, e.count) for e in deck.nonland_entries()]
    if deck.commander is not None:
        cards.append((deck.commander, 1))
    demand = {}  # type: Dict[str, int]
    for card, count in cards:
        for color, pips in card.pips.items():
            if color in colors:
                demand[color] = demand.get(color, 0) + pips * count
    return demand


def _mana_consistency(deck: BuiltDeck) -> float:
    colors = deck_colors(deck.plan, deck.fmt)
    demand = {c: n for c, n in _pip_demand(deck, colors).items() if n > 0}
    if not demand:
        return 1.0
    short = source_shortfalls(deck.entries, demand, deck.fmt, colors)
    return 1 - len(short) / len(demand)


def _avg_quality(deck: BuiltDeck) -> float:
    entries = deck.nonland_entries()
    copies = sum(e.count for e in entries)
    if not copies:
        return 0.0
    return sum(e.card.quality * e.count for e in entries) / copies


def deck_metrics(deck: BuiltDeck, graph: SynergyGraph, playbook: Playbook) -> Dict[str, float]:
    """Grade a built deck.

    Args:
        deck: Built deck.
        graph: Synergy graph of the cards.
        playbook: Playbook with quotas, curve targets and metric weights.

    Returns:
        Mapping with synergy_density (edge weight inside the nonland,
        non-basic cards, commander included, per card; not capped),
        role_coverage (sum of min(have, quota) over the sum of quotas),
        curve_fit (1 - 0.5 * sum of absolute share gaps), mana_consistency
        (share of the demanded deck colors whose land sources meet
        fmt.color_sources, counted as the builder counts them; see
        builder.source_shortfalls), avg_quality (copy-weighted mean card quality),
        and combined (weighted sum, synergy_density / synergy_cap capped at 1).
    """
    metrics = {
        "synergy_density": _synergy_density(deck, graph),
        "role_coverage": _role_coverage(deck, playbook),
        "curve_fit": _curve_fit(deck, playbook),
        "mana_consistency": _mana_consistency(deck),
        "avg_quality": _avg_quality(deck),
    }
    cap = playbook.metric_weights.get(SYNERGY_CAP, 3.0)
    if cap <= 0:
        cap = 1.0
    combined = 0.0
    for name, key in WEIGHT_KEYS.items():
        value = min(1.0, metrics[name] / cap) if name == "synergy_density" else metrics[name]
        combined += playbook.metric_weights.get(key, 0.0) * value
    metrics["combined"] = combined
    return metrics

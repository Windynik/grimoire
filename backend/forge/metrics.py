"""Deck metrics for the deck forge.

Grades a built deck on synergy, role coverage, curve, mana, and card quality.
The UI shows the metrics and the evaluation harness compares decks with them.
Makes no network calls.
"""

from typing import Dict, FrozenSet, List, Tuple

from backend.forge.builder import (
    BASIC_FOR_COLOR, SOURCE_RANKS, BuiltDeck, DeckEntry, _quota_keys, curve_bucket,
    deck_colors, land_colors,
)
from backend.forge.graph import SynergyGraph
from backend.forge.playbook import Playbook

BUCKETS = ("1", "2", "3", "4", "5", "6+")
SYNERGY_CAP = "synergy_cap"  # metric_weights key that caps synergy_density, not a weight
PRIMARY_SHARE = 0.40  # pip share that makes a color primary
SECONDARY_SHARE = 0.15  # pip share that makes a color secondary
# metric_weights key for each metric
WEIGHT_KEYS = {"synergy_density": "synergy", "role_coverage": "roles", "curve_fit": "curve",
               "mana_consistency": "mana", "avg_quality": "quality"}


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
        for key in _quota_keys(entry.card):
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


def _sources(entries: List[DeckEntry], colors: FrozenSet[str]) -> Dict[str, int]:
    sources = {}  # type: Dict[str, int]
    for entry in entries:
        if entry.card is not None and not entry.card.is_land:
            continue
        made = land_colors(entry.card, colors) if entry.card is not None else {
            c for c, n in BASIC_FOR_COLOR.items() if n == entry.name}
        for color in made:
            sources[color] = sources.get(color, 0) + entry.count
    return sources


def _mana_consistency(deck: BuiltDeck) -> float:
    colors = deck_colors(deck.plan, deck.fmt)
    demand = {c: n for c, n in _pip_demand(deck, colors).items() if n > 0}
    if not demand:
        return 1.0
    sources = _sources(deck.entries, colors)
    pips = sum(demand.values())
    met = 0
    for color, n in demand.items():
        share = n / pips
        tier = ("primary" if share >= PRIMARY_SHARE
                else "secondary" if share >= SECONDARY_SHARE else "splash")
        if sources.get(color, 0) >= deck.fmt.color_sources[tier]:
            met += 1
    return met / len(demand)


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
        (share of the colors in the deck whose land sources meet
        fmt.color_sources), avg_quality (copy-weighted mean card quality),
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
    combined = 0.0
    for name, key in WEIGHT_KEYS.items():
        value = min(1.0, metrics[name] / cap) if name == "synergy_density" else metrics[name]
        combined += playbook.metric_weights.get(key, 0.0) * value
    metrics["combined"] = combined
    return metrics

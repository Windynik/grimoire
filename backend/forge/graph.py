"""Synergy graph and deck backbones for the deck forge.

An edge goes from a card that gives a synergy hook to a card that wants it.
A backbone is a dense group of cards around one or two hooks: the central
plan of a deck. Commander formats find one backbone per commander; other
formats find one per color set.
"""

import re
from dataclasses import dataclass
from itertools import combinations
from typing import Collection, Dict, FrozenSet, List, Optional, Set, Tuple

from backend.forge.cards import COLORS, OwnedCard
from backend.forge.playbook import FormatRules, Playbook
from backend.forge.tagging import TRIBAL_PREFIX, is_scaling

SCALING_FACTOR = 1.5
MERGE_OVERLAP = 0.4
COMMANDER_BONUS = 2.0
COMMANDER_PHRASE = "can be your commander"
# Scopes for formats without a commander: the 5 mono colors and the 10 pairs.
COLOR_SCOPES = ([frozenset(c) for c in COLORS]
                + [frozenset(pair) for pair in combinations(COLORS, 2)])

Group = Tuple[Tuple[str, ...], Set[str]]  # (hooks, member ids)
ScoredGroup = Tuple[Tuple[str, ...], Set[str], float]  # (hooks, member ids, score)


@dataclass
class Edge:
    """One synergy: src gives the hook and dst wants it."""

    src: str
    dst: str
    hook: str
    weight: float
    source: str = "engine"


class SynergyGraph:
    """Directed synergy edges between owned cards, with fast lookups."""

    def __init__(self, cards: List[OwnedCard]):
        self.cards = {card.id: card for card in cards}  # type: Dict[str, OwnedCard]
        self.edges = []  # type: List[Edge]
        self._out = {}  # type: Dict[str, List[Edge]]
        self._out_weight = {}  # type: Dict[str, Dict[str, float]]
        self._in_weight = {}  # type: Dict[str, Dict[str, float]]

    def add_edge(self, edge: Edge) -> None:
        """Add an edge from the engine or from the model.

        Args:
            edge: Edge to add. Edges between the same cards add up.

        Returns:
            None.
        """
        self.edges.append(edge)
        self._out.setdefault(edge.src, []).append(edge)
        out = self._out_weight.setdefault(edge.src, {})
        out[edge.dst] = out.get(edge.dst, 0.0) + edge.weight
        into = self._in_weight.setdefault(edge.dst, {})
        into[edge.src] = into.get(edge.src, 0.0) + edge.weight

    def between(self, ids: Collection[str]) -> List[Edge]:
        """Return the edges with both ends in a set of cards.

        Args:
            ids: Card ids.

        Returns:
            Edges whose src and dst are both in ids.
        """
        id_set = _as_set(ids)
        return [edge for src in id_set for edge in self._out.get(src, ())
                if edge.dst in id_set]

    def weight_into(self, card_id: str, core: Collection[str]) -> float:
        """Return the synergy weight between one card and a group of cards.

        Args:
            card_id: Card to measure.
            core: Ids of the group.

        Returns:
            Sum of edge weights from the card into the group and from the
            group into the card.
        """
        core_set = _as_set(core)
        return (_weight_to(self._out_weight.get(card_id, {}), core_set)
                + _weight_to(self._in_weight.get(card_id, {}), core_set))

    def _inner_weight(self, ids: Set[str]) -> float:
        return sum(_weight_to(self._out_weight.get(src, {}), ids) for src in ids)


@dataclass
class Backbone:
    """A deck's central plan: a dense group of cards around one or two hooks."""

    id: str
    hooks: Tuple[str, ...]
    name: str
    members: List[str]
    colors: FrozenSet[str]
    commander_id: Optional[str]
    score: float


def _as_set(ids: Collection[str]):
    return ids if isinstance(ids, (set, frozenset)) else set(ids)


def _weight_to(weights: Dict[str, float], ids) -> float:
    if len(weights) <= len(ids):
        return sum(w for other, w in weights.items() if other in ids)
    return sum(weights.get(other, 0.0) for other in ids)


def build_graph(cards: List[OwnedCard], playbook: Playbook) -> SynergyGraph:
    """Build the synergy graph from tagged cards.

    Args:
        cards: Tagged owned cards (see tagging.tag_cards).
        playbook: Playbook with the scaling patterns.

    Returns:
        A graph with an edge A -> B for every hook in A.gives & B.wants
        (A is not B). The weight is 1.0, or 1.5 when B scales with the hook.
    """
    graph = SynergyGraph(cards)
    wanters = {}  # type: Dict[str, List[Tuple[OwnedCard, float]]]
    for card in cards:
        for hook in sorted(card.wants):
            weight = SCALING_FACTOR if is_scaling(card, hook, playbook) else 1.0
            wanters.setdefault(hook, []).append((card, weight))
    for giver in cards:
        for hook in sorted(giver.gives):
            for wanter, weight in wanters.get(hook, ()):
                if wanter.id != giver.id:
                    graph.add_edge(Edge(src=giver.id, dst=wanter.id, hook=hook, weight=weight))
    return graph


def commander_candidates(cards: List[OwnedCard]) -> List[OwnedCard]:
    """Return the cards that can lead a commander deck.

    Args:
        cards: Owned cards.

    Returns:
        Legendary creatures and cards whose text says they can be your
        commander, in input order.
    """
    return [card for card in cards
            if {"Legendary", "Creature"} <= card.types
            or COMMANDER_PHRASE in (card.oracle_text or "").lower()]


def hook_label(hook: str, playbook: Playbook) -> str:
    """Return the display label of a hook, for example "Goblin tribal".

    Args:
        hook: Hook name.
        playbook: Playbook with the hook labels.

    Returns:
        "<Type> tribal" for tribal hooks, else the playbook label (or the name).
    """
    if hook.startswith(TRIBAL_PREFIX):
        return hook[len(TRIBAL_PREFIX):] + " tribal"
    return playbook.hooks.get(hook, {}).get("label", hook)


def _color_code(colors: FrozenSet[str]) -> str:
    return "".join(c for c in COLORS if c in colors) or "C"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _big_enough(members: List[OwnedCard], fmt: FormatRules) -> bool:
    if fmt.singleton or fmt.max_copies <= 1:
        return len(members) >= fmt.min_core
    # Formats with copies count playsets: four copies of a card fill four slots.
    copies = sum(min(card.owned, fmt.max_copies) for card in members)
    return copies / fmt.max_copies >= fmt.min_core / 2


def _merge(groups: List[Group]) -> List[Group]:
    """Merge pairs of groups that share at least MERGE_OVERLAP of the smaller one.

    The pairs with the most overlap merge first, and each group merges once,
    so a merged group has two hooks.
    """
    pairs = []
    for (i, (hooks_a, a)), (j, (hooks_b, b)) in combinations(enumerate(groups), 2):
        overlap = len(a & b) / min(len(a), len(b))
        if overlap >= MERGE_OVERLAP:
            pairs.append((-overlap, hooks_a + hooks_b, i, j))
    pairs.sort()
    used = set()  # type: Set[int]
    merged = []
    for _, hooks, i, j in pairs:
        if i in used or j in used:
            continue
        used.update((i, j))
        merged.append((tuple(sorted(hooks)), groups[i][1] | groups[j][1]))
    merged += [group for k, group in enumerate(groups) if k not in used]
    return merged


def _scored_groups(by_hook: Dict[str, List[OwnedCard]], scope: FrozenSet[str],
                   graph: SynergyGraph, fmt: FormatRules) -> List[ScoredGroup]:
    """Return (hooks, member ids, score) for the hook groups of one color scope."""
    groups = []
    for hook in sorted(by_hook):
        members = [card for card in by_hook[hook] if card.color_identity <= scope]
        if members and _big_enough(members, fmt):
            groups.append(((hook,), {card.id for card in members}))
    scored = []
    for hooks, ids in _merge(groups):
        density = graph._inner_weight(ids) / len(ids)
        quality = sum(0.5 + graph.cards[i].quality * fmt.quality_weight for i in ids)
        fill = min(1.0, len(ids) / fmt.min_core)
        scored.append((hooks, ids, density * quality * fill))
    return scored


def _scopes(cards: List[OwnedCard], fmt: FormatRules, commander_id: Optional[str],
            colors: Optional[FrozenSet[str]]) -> List[Tuple[FrozenSet[str], Optional[OwnedCard]]]:
    if not fmt.commander:
        return [(colors, None)] if colors is not None else [(s, None) for s in COLOR_SCOPES]
    if commander_id is not None:
        leaders = [card for card in cards if card.id == commander_id]
    else:
        leaders = commander_candidates(cards)
        if colors is not None:
            leaders = [card for card in leaders if card.color_identity <= colors]
    return [(card.color_identity, card) for card in leaders]


def find_backbones(cards: List[OwnedCard], graph: SynergyGraph, fmt: FormatRules,
                   playbook: Playbook, commander_id: Optional[str] = None,
                   colors: Optional[FrozenSet[str]] = None, limit: int = 5) -> List[Backbone]:
    """Find the strongest deck plans in the owned pool.

    Args:
        cards: Tagged owned cards, legal in the format.
        graph: Synergy graph of the cards.
        fmt: Format rules (commander, min_core, quality_weight, copies).
        playbook: Playbook with the hook labels.
        commander_id: In commander formats, use only this commander.
        colors: Use only this color set. In commander formats, use only
            commanders whose color identity fits inside it.
        limit: Largest number of backbones to return.

    Returns:
        The best group of each scope, best score first (ties by id), with no
        two backbones that have the same hooks and commander. Groups with no
        synergy edges (score 0) are no plan and are left out.
    """
    by_hook = {}  # type: Dict[str, List[OwnedCard]]
    for card in cards:
        if not card.is_land:
            for hook in card.gives | card.wants:
                by_hook.setdefault(hook, []).append(card)
    # Hook groups depend only on the scope colors, so commanders that share a
    # color identity share one computation.
    cache = {}  # type: Dict[FrozenSet[str], List[ScoredGroup]]
    best = []  # type: List[Backbone]
    for scope, commander in _scopes(cards, fmt, commander_id, colors):
        if scope not in cache:
            cache[scope] = _scored_groups(by_hook, scope, graph, fmt)
        top = None
        for hooks, ids, score in cache[scope]:
            if commander is not None and (commander.gives | commander.wants) & set(hooks):
                score *= COMMANDER_BONUS
            rank = (-score, _backbone_id(hooks, scope, commander))
            if score > 0 and (top is None or rank < top[0]):
                top = (rank, hooks, ids, score)
        if top is not None:
            _, hooks, ids, score = top
            best.append(_backbone(hooks, ids, scope, commander, score, playbook))
    best.sort(key=lambda b: (-b.score, b.id))
    chosen, seen = [], set()
    for backbone in best:
        key = (backbone.hooks, backbone.commander_id)
        if key in seen:
            continue
        seen.add(key)
        chosen.append(backbone)
        if len(chosen) >= limit:
            break
    for backbone in chosen:
        ids = set(backbone.members)
        backbone.members.sort(key=lambda i: (-graph.weight_into(i, ids), graph.cards[i].name))
    return chosen


def _backbone_id(hooks: Tuple[str, ...], scope: FrozenSet[str],
                 commander: Optional[OwnedCard]) -> str:
    parts = ["+".join(hooks), _color_code(scope)]
    if commander is not None:
        parts.append(_slug(commander.name))
    return ":".join(parts)


def _backbone(hooks: Tuple[str, ...], ids: Set[str], scope: FrozenSet[str],
              commander: Optional[OwnedCard], score: float, playbook: Playbook) -> Backbone:
    return Backbone(
        id=_backbone_id(hooks, scope, commander),
        hooks=hooks,
        name=" & ".join(hook_label(hook, playbook) for hook in hooks),
        members=sorted(ids),
        colors=scope,
        commander_id=commander.id if commander is not None else None,
        score=score,
    )

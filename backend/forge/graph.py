"""Synergy graph and deck backbones for the deck forge.

An edge goes from a card that gives a synergy hook to a card that wants it.
A backbone is a dense group of at most 20 cards around one or two hooks:
the central plan of a deck. Commander formats find backbones per commander;
other formats find them per color set.
"""

import re
from dataclasses import dataclass
from itertools import combinations
from typing import Collection, Dict, FrozenSet, List, Optional, Set, Tuple

from backend.forge.cards import COLORS, OwnedCard, fits_colors
from backend.forge.playbook import FormatRules, Playbook
from backend.forge.tagging import TRIBAL_PREFIX, is_scaling

SCALING_FACTOR = 1.5
MERGE_OVERLAP = 0.4
COMMANDER_BONUS = 2.0  # the commander wants a group hook: the plan is built around it
COMMANDER_GIVES_BONUS = 1.25  # the commander only gives a group hook: one more enabler
COMMANDER_PHRASE = "can be your commander"
# Formats where any legendary planeswalker can be the commander.
PLANESWALKER_COMMANDER_FORMATS = frozenset({"brawl", "standardbrawl"})
MAX_MEMBERS = 20  # a backbone is 8-20 core cards
MIN_WANTERS = 3  # cards that want a hook; type-based piles of givers are no plan
GROUPS_PER_SCOPE = 3
# Scopes for formats without a commander: the 5 mono colors and the 10 pairs.
COLOR_SCOPES = ([frozenset(c) for c in COLORS]
                + [frozenset(pair) for pair in combinations(COLORS, 2)])

Group = Tuple[Tuple[str, ...], Set[str]]  # (hooks, member ids)
ScoredGroup = Tuple[Tuple[str, ...], List[str], float]  # (hooks, member ids, score)


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

    def inner_weight(self, ids: Collection[str]) -> float:
        """Return the total weight of the edges inside a set of cards.

        Args:
            ids: Card ids.

        Returns:
            Sum of the weights of between(ids), without building the edge list.
        """
        id_set = _as_set(ids)
        return sum(_weight_to(self._out_weight.get(src, {}), id_set) for src in id_set)


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


def commander_candidates(cards: List[OwnedCard],
                         fmt: Optional[FormatRules] = None) -> List[OwnedCard]:
    """Return the cards that can lead a commander deck.

    Args:
        cards: Owned cards.
        fmt: Format rules. In Brawl and Standard Brawl, legendary
            planeswalkers can also lead. None uses the Commander rule.

    Returns:
        Cards with at least one owned copy that are legendary creatures (or
        legendary planeswalkers in Brawl formats) or whose text says they
        can be your commander, in input order.
    """
    walkers = fmt is not None and fmt.key in PLANESWALKER_COMMANDER_FORMATS
    return [card for card in cards
            if card.owned > 0
            and ({"Legendary", "Creature"} <= card.types
                 or (walkers and {"Legendary", "Planeswalker"} <= card.types)
                 or COMMANDER_PHRASE in (card.oracle_text or "").lower())]


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


def commander_bonus(commander: Optional[OwnedCard], hooks: Tuple[str, ...]) -> float:
    """Return the score factor that a commander gives a hook group.

    Args:
        commander: The scope's commander, or None.
        hooks: The group's hooks.

    Returns:
        COMMANDER_BONUS when the commander wants one of the hooks (its
        ability pays off the plan), COMMANDER_GIVES_BONUS when it only gives
        one (it is one more enabler), else 1.0.
    """
    if commander is None:
        return 1.0
    if commander.wants & set(hooks):
        return COMMANDER_BONUS
    if commander.gives & set(hooks):
        return COMMANDER_GIVES_BONUS
    return 1.0


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


def card_weight(card: OwnedCard, fmt: FormatRules) -> float:
    """Return a card's weight in a backbone score: quality, and playsets in 60-card formats.

    Args:
        card: Owned card.
        fmt: Format rules (quality_weight, copies).

    Returns:
        (0.5 + quality * quality_weight), times the share of a full playset
        the owner has in formats with copies. A deck plays four copies of its
        key cards, so a plan of single copies is weaker than a plan of playsets.
    """
    weight = 0.5 + card.quality * fmt.quality_weight
    if fmt.singleton or fmt.max_copies <= 1:
        return weight
    return weight * min(card.owned, fmt.copies_allowed(card.legality)) / fmt.max_copies


def _enough_wanters(hooks: Tuple[str, ...], ids: Collection[str], graph: SynergyGraph) -> bool:
    wanted = set(hooks)
    count = 0
    for card_id in ids:
        if graph.cards[card_id].wants & wanted:
            count += 1
            if count >= MIN_WANTERS:
                return True
    return False


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


def _core(ids: Set[str], graph: SynergyGraph) -> List[str]:
    """Return the group's best MAX_MEMBERS cards, most connected first.

    Cards rank by weighted degree inside the whole group, then by quality,
    then by name.
    """
    def rank(card_id):
        card = graph.cards[card_id]
        return -graph.weight_into(card_id, ids), -card.quality, card.name
    return sorted(ids, key=rank)[:MAX_MEMBERS]


def _select(ids: Set[str], graph: SynergyGraph, fmt: FormatRules) -> Set[str]:
    """Return at most MAX_MEMBERS cards of a group that work well together.

    The first card has the most weight into the whole group. Each next card
    adds the most edge weight into the cards chosen before it. Both weights
    count times the card's card_weight, as in the backbone score. Ties go to
    the weight into the whole group, then quality, then name. So enablers and
    payoffs stay in balance (a sixth sac outlet adds no weight while no payoff
    is in), and a weak card loses to a strong card with the same edges.
    """
    if len(ids) <= MAX_MEMBERS:
        return set(ids)
    cards = graph.cards
    factor = {i: card_weight(cards[i], fmt) for i in ids}
    degree = {i: graph.weight_into(i, ids) for i in ids}
    gain = dict.fromkeys(ids, 0.0)
    chosen = set()  # type: Set[str]
    while len(chosen) < MAX_MEMBERS:
        pull = degree if not chosen else gain
        best = min(gain, key=lambda i: (-pull[i] * factor[i], -degree[i], -cards[i].quality,
                                        cards[i].name))
        chosen.add(best)
        del gain[best]
        for weights in (graph._out_weight.get(best, {}), graph._in_weight.get(best, {})):
            for other, weight in weights.items():
                if other in gain:
                    gain[other] += weight
    return chosen


def _scored_groups(by_hook: Dict[str, List[OwnedCard]], scope: FrozenSet[str],
                   commander: Optional[OwnedCard], graph: SynergyGraph,
                   fmt: FormatRules) -> List[ScoredGroup]:
    """Return (hooks, member ids, score) for the hook groups of one scope.

    The commander is never a member. Each group needs MIN_WANTERS cards that
    want one of its hooks, before and after the merge and the cap (see
    _select). Scores use the capped members and card_weight, and do not
    include the commander bonus.
    """
    skip = commander.id if commander is not None else None
    groups = []
    for hook in sorted(by_hook):
        members = [card for card in by_hook[hook]
                   if fits_colors(card, scope, fmt) and card.id != skip]
        ids = {card.id for card in members}
        if members and _big_enough(members, fmt) and _enough_wanters((hook,), ids, graph):
            groups.append(((hook,), ids))
    scored = []
    for hooks, ids in _merge(groups):
        core = _core(_select(ids, graph, fmt), graph)
        if not _enough_wanters(hooks, core, graph):
            continue
        density = graph.inner_weight(core) / len(core)
        quality = sum(card_weight(graph.cards[i], fmt) for i in core)
        fill = min(1.0, len(core) / fmt.min_core)
        scored.append((hooks, core, density * quality * fill))
    return scored


def _scopes(cards: List[OwnedCard], fmt: FormatRules, commander_id: Optional[str],
            colors: Optional[FrozenSet[str]]) -> List[Tuple[FrozenSet[str], Optional[OwnedCard]]]:
    if not fmt.commander:
        return [(colors, None)] if colors is not None else [(s, None) for s in COLOR_SCOPES]
    if commander_id is not None:
        leaders = [card for card in cards if card.id == commander_id]
    else:
        leaders = commander_candidates(cards, fmt)
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
        The best GROUPS_PER_SCOPE groups of each scope, then the best `limit`
        overall, best score first (ties by id), with no two backbones that
        have the same hooks and commander. Each backbone has at most
        MAX_MEMBERS members (chosen by _select), most connected first, and
        never the commander. The score includes commander_bonus.
        Groups with no synergy edges (score 0) are no plan and are left out.
    """
    by_hook = {}  # type: Dict[str, List[OwnedCard]]
    for card in cards:
        if not card.is_land:
            for hook in card.gives | card.wants:
                by_hook.setdefault(hook, []).append(card)
    # Hook groups depend only on the scope colors and on which card is left
    # out as commander. A commander with no hooks is in no group, so such
    # commanders that share a color identity share one computation.
    cache = {}  # type: Dict[Tuple[FrozenSet[str], Optional[str]], List[ScoredGroup]]
    candidates = []  # type: List[Backbone]
    for scope, commander in _scopes(cards, fmt, commander_id, colors):
        in_groups = commander is not None and not commander.is_land and bool(
            commander.gives | commander.wants)
        key = (scope, commander.id if in_groups else None)
        if key not in cache:
            cache[key] = _scored_groups(by_hook, scope, commander if in_groups else None,
                                        graph, fmt)
        options = []
        for hooks, core, score in cache[key]:
            score *= commander_bonus(commander, hooks)
            if score > 0:
                options.append((-score, _backbone_id(hooks, scope, commander), hooks, core, score))
        options.sort(key=lambda option: option[:2])
        for _, _, hooks, core, score in options[:GROUPS_PER_SCOPE]:
            candidates.append(_backbone(hooks, core, scope, commander, score, playbook))
    candidates.sort(key=lambda b: (-b.score, b.id))
    chosen, seen = [], set()
    for backbone in candidates:
        key = (backbone.hooks, backbone.commander_id)
        if key in seen:
            continue
        seen.add(key)
        chosen.append(backbone)
        if len(chosen) >= limit:
            break
    for backbone in chosen:
        backbone.members = _core(set(backbone.members), graph)
    return chosen


def wish_backbone(cards: List[OwnedCard], graph: SynergyGraph, fmt: FormatRules,
                  playbook: Playbook, tribes: Collection[str],
                  commander_id: Optional[str] = None,
                  colors: Optional[FrozenSet[str]] = None) -> Optional[Backbone]:
    """Return the plan for the creature types the owner's wish names, or None.

    A wished tribe needs no payoff cards (MIN_WANTERS) and no synergy edges:
    the owner asked for the type itself. The members are the cards that give
    or want one of the tribal hooks (changelings give every one). The scope is
    the one with the most copies of such cards, then the most quality, then
    the backbone id. The group must still be big enough for the format.

    Args:
        cards: Tagged owned cards, legal in the format. The wished tribes must
            be tagged (see tag_cards extra_tribes).
        graph: Synergy graph of the cards.
        fmt: Format rules.
        playbook: Playbook with the hook labels.
        tribes: Wished creature types, for example {"Angel"}.
        commander_id: In commander formats, use only this commander.
        colors: Use only this color set.

    Returns:
        A backbone with the tribal hooks, or None when no scope has enough cards.
    """
    hooks = tuple(sorted(TRIBAL_PREFIX + tribe for tribe in tribes))
    if not hooks:
        return None
    wanted = set(hooks)
    pool = [card for card in cards if not card.is_land and (card.gives | card.wants) & wanted]
    best = None  # type: Optional[Tuple[tuple, Backbone]]
    for scope, commander in _scopes(cards, fmt, commander_id, colors):
        skip = commander.id if commander is not None else None
        members = [card for card in pool if fits_colors(card, scope, fmt) and card.id != skip]
        if not members or not _big_enough(members, fmt):
            continue
        core = _core(_select({card.id for card in members}, graph, fmt), graph)
        density = graph.inner_weight(core) / len(core)
        quality = sum(card_weight(graph.cards[i], fmt) for i in core)
        score = density * quality * min(1.0, len(core) / fmt.min_core)
        bone = _backbone(hooks, core, scope, commander, score, playbook)
        copies = sum(min(card.owned, fmt.max_copies) for card in members)
        rank = (-copies, -quality, bone.id)
        if best is None or rank < best[0]:
            best = (rank, bone)
    return best[1] if best is not None else None


def _backbone_id(hooks: Tuple[str, ...], scope: FrozenSet[str],
                 commander: Optional[OwnedCard]) -> str:
    parts = ["+".join(hooks), _color_code(scope)]
    if commander is not None:
        parts.append(_slug(commander.name))
    return ":".join(parts)


def _backbone(hooks: Tuple[str, ...], members: List[str], scope: FrozenSet[str],
              commander: Optional[OwnedCard], score: float, playbook: Playbook) -> Backbone:
    return Backbone(
        id=_backbone_id(hooks, scope, commander),
        hooks=hooks,
        name=" & ".join(hook_label(hook, playbook) for hook in hooks),
        members=list(members),
        colors=scope,
        commander_id=commander.id if commander is not None else None,
        score=score,
    )

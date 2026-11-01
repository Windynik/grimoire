"""Deck builder and mana base for the deck forge.

Places owned, legal cards in the deck colors around a backbone, in a fixed
order: required cards, backbone core, role quotas, then a curve-aware fill.
Then builds the mana base from owned lands and basic lands. Basic lands are
the one card the player is assumed to own. Makes no network calls.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from backend.forge.cards import COLORS, OwnedCard
from backend.forge.graph import Backbone, SynergyGraph
from backend.forge.playbook import FormatRules, Playbook

BASIC_FOR_COLOR = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}
COLORLESS_BASIC = "Wastes"
COLOR_NAMES = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}
CREATURES = "creatures"  # quota key that counts creature cards, not a tagged role
CORE_SHARE = 0.4  # backbone members fill at most this share of the nonland slots
WINDOW = 15  # size of borderline_in and of bench
SPLASH_PIPS = 3  # pips of one splash color that make a card hard to cast
SOURCE_RANKS = ("primary", "secondary")  # the third color and after are "splash"
PASSES = 3  # placement passes to settle the land target on the placed cards
LEGAL = ("legal", "restricted")
SHORTFALL = "Only {k} playable nonland cards fit; filled the rest with basic lands."
NO_ROOM = "Couldn't fit {name}: no room left in the deck."
_FETCH = re.compile(r"search your library for ([^.]*)", re.IGNORECASE)
_BASIC_LAND = re.compile(r"\bbasic lands?\b", re.IGNORECASE)
_BASIC_TYPE = re.compile(r"\b(Plains|Island|Swamp|Mountain|Forest)s?\b", re.IGNORECASE)
_TYPE_COLOR = {name.lower(): color for color, name in BASIC_FOR_COLOR.items()}
# Nonbasic land tiers, best first.
TIER_DUAL, TIER_ANY, TIER_UTILITY = 1, 2, 3
TIER_FULL = {TIER_ANY: "the any-color land limit is full",
             TIER_UTILITY: "the utility land limit is full"}
ANY_COLOR_LIMIT_100 = 3
ANY_COLOR_LIMIT_60 = 2
ANY_COLOR_MIN_COLORS_60 = 3  # 60-card decks take any-color lands only with 3+ colors


@dataclass
class BuildPlan:
    """What to build: the backbone, the playstyle, and the owner's wishes."""

    backbone: Backbone
    playstyle: str
    prefer: Set[str] = field(default_factory=set)
    required: Set[str] = field(default_factory=set)
    commander: Optional[OwnedCard] = None


@dataclass
class DeckEntry:
    """One line of a decklist. Basic lands have no card."""

    card: Optional[OwnedCard]
    name: str
    count: int
    role: str
    reason: str
    basic: bool = False


@dataclass
class BuiltDeck:
    """A built deck. The commander is not in entries (see the commander property)."""

    fmt: FormatRules
    plan: BuildPlan
    entries: List[DeckEntry]
    land_target: int
    warnings: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    borderline_in: List[str] = field(default_factory=list)
    bench: List[str] = field(default_factory=list)

    @property
    def commander(self) -> Optional[OwnedCard]:
        """The effective commander: plan.commander in a commander format, else None."""
        return self.plan.commander if self.fmt.commander else None

    def total(self) -> int:
        """Return the number of cards in the deck, the commander included."""
        return sum(entry.count for entry in self.entries) + (1 if self.commander else 0)

    def nonland_entries(self) -> List[DeckEntry]:
        """Return the entries that are not lands (MDFCs with a land back count as nonland)."""
        return [entry for entry in self.entries
                if not entry.basic and entry.card is not None and not entry.card.is_land]

    def names(self) -> Set[str]:
        """Return the lowercase names of every card in the deck, the commander included."""
        names = {entry.name.lower() for entry in self.entries}
        if self.commander is not None:
            names.add(self.commander.name.lower())
        return names


def copies_for(card: OwnedCard, fmt: FormatRules) -> int:
    """Return how many copies of a card a deck can use.

    Args:
        card: Owned card.
        fmt: Format rules.

    Returns:
        1 in singleton formats; else the owned count for "any number" cards;
        else the owned count limited by the format's copy limit.
    """
    if fmt.singleton:
        return 1
    if card.any_number:
        return card.owned
    return min(card.owned, fmt.copies_allowed(card.legality))


def land_target(fmt: FormatRules, avg_cmc: float, mdfc_count: int) -> int:
    """Return the number of land slots for a deck.

    Args:
        fmt: Format rules that give the land range (lo, hi).
        avg_cmc: Average mana value of the nonland cards.
        mdfc_count: Number of nonland cards with a land back face.

    Returns:
        clamp(round(lo + (avg_cmc - 2.5) * 2), lo, hi) - mdfc_count // 2.
    """
    lo, hi = fmt.lands
    return max(lo, min(hi, int(round(lo + (avg_cmc - 2.5) * 2)))) - mdfc_count // 2


def curve_bucket(cmc: float) -> str:
    """Return the curve bucket of a mana value: "1" (0 and 1) to "5", then "6+"."""
    value = int(cmc)
    if value <= 1:
        return "1"
    return "6+" if value >= 6 else str(value)


def deck_colors(plan: BuildPlan, fmt: FormatRules) -> FrozenSet[str]:
    """Return the deck colors: the commander identity in commander formats, else the backbone's."""
    if fmt.commander and plan.commander is not None:
        return frozenset(plan.commander.color_identity)
    return frozenset(plan.backbone.colors)


def _playable(card: OwnedCard, colors: FrozenSet[str], commander_id: Optional[str]) -> bool:
    return (card.owned > 0 and card.id != commander_id and card.legality in LEGAL
            and "Token" not in card.types and not card.is_basic
            and card.color_identity <= colors)


def _quota_keys(card: OwnedCard) -> Set[str]:
    keys = set(card.roles)
    if "Creature" in card.types:
        keys.add(CREATURES)
    return keys


def _ordered(colors) -> List[str]:
    return [c for c in COLORS if c in colors]


@dataclass
class _Pick:
    card: OwnedCard
    count: int
    role: str
    reason: str


@dataclass
class _State:
    """Placement state that card_score reads."""

    fmt: FormatRules
    weights: Dict[str, float]
    graph: SynergyGraph
    core: Set[str]
    quotas: Dict[str, int]
    curve: Dict[str, float]
    splash: FrozenSet[str]
    prefer: Set[str]
    slots: int
    synergy: Dict[str, float]
    filled: int = 0
    counts: Dict[str, int] = field(default_factory=dict)
    have: Dict[str, int] = field(default_factory=dict)
    buckets: Dict[str, int] = field(default_factory=dict)
    picks: List[_Pick] = field(default_factory=list)


def _synergy(card: OwnedCard, state: _State) -> float:
    if card.id not in state.synergy:
        state.synergy[card.id] = state.graph.weight_into(card.id, state.core)
    return state.synergy[card.id]


def _card_score(card: OwnedCard, state: _State) -> float:
    """Score a nonland card for the next open slot.

    synergy into the core + role (fills an open quota) + quality prior
    + curve fit (+1 under the bucket's target count, -1 at or over it)
    + mana (-1 for SPLASH_PIPS pips of one splash color) + prefer, each times
    its playbook weight.
    """
    w = state.weights
    open_keys = {key for key, quota in state.quotas.items() if state.have.get(key, 0) < quota}
    fills = 1 if _quota_keys(card) & open_keys else 0
    bucket = curve_bucket(card.cmc)
    target = state.curve.get(bucket, 0.0) * state.slots
    curve_fit = 1 if state.buckets.get(bucket, 0) < target else -1
    pips = card.pips
    mana = -1 if any(pips.get(c, 0) >= SPLASH_PIPS for c in state.splash) else 0
    prefer = 1 if card.name.lower() in state.prefer else 0
    return (w["synergy"] * _synergy(card, state)
            + w["role"] * fills
            + w["quality"] * card.quality * state.fmt.quality_weight
            + w["curve"] * curve_fit
            + w["mana"] * mana
            + w["prefer"] * prefer)


def _best(candidates: List[OwnedCard], state: _State) -> OwnedCard:
    """Return the best candidate: score, then quality, then name."""
    return min(candidates, key=lambda c: (-_card_score(c, state), -c.quality, c.name))


def _place(card: OwnedCard, role: str, reason: str, state: _State) -> None:
    """Place as many copies as fit. A card is consumed even when no copy fits."""
    if card.id in state.counts:
        return
    count = min(copies_for(card, state.fmt), state.slots - state.filled)
    state.counts[card.id] = max(0, count)
    if count <= 0:
        return
    state.filled += count
    bucket = curve_bucket(card.cmc)
    state.buckets[bucket] = state.buckets.get(bucket, 0) + count
    for key in _quota_keys(card):
        state.have[key] = state.have.get(key, 0) + count
    state.picks.append(_Pick(card, count, role, reason))


def _open(pool: List[OwnedCard], state: _State) -> List[OwnedCard]:
    return [card for card in pool if card.id not in state.counts]


def _fill_reason(card: OwnedCard, state: _State) -> Tuple[str, str]:
    if _synergy(card, state) > 0:
        return "synergy", "Synergy with the core."
    if card.roles:
        role = sorted(card.roles)[0]
        return role, f"Adds {role}."
    return "synergy", "Strong card for the curve."


def _place_nonland(pool: List[OwnedCard], members: List[OwnedCard],
                   required: List[OwnedCard], plan: BuildPlan, state: _State) -> None:
    """Place nonland cards: required, core, role quotas, then the curve-aware fill."""
    for card in required:
        _place(card, "core", "Required card.", state)
    core_cap = state.slots * CORE_SHARE
    left = [card for card in members if card.id not in state.counts]
    while state.filled < core_cap and left:
        card = _best(left, state)
        left.remove(card)
        _place(card, "core", f"Core card of the {plan.backbone.name} plan.", state)
    for key, quota in state.quotas.items():
        while state.have.get(key, 0) < quota and state.filled < state.slots:
            candidates = [c for c in _open(pool, state) if key in _quota_keys(c)]
            if not candidates:
                break
            card = _best(candidates, state)
            if key == CREATURES:
                _place(card, "synergy", "Fills the creature quota.", state)
            else:
                _place(card, key, f"Fills the {key} quota.", state)
    while state.filled < state.slots:
        candidates = _open(pool, state)
        if not candidates:
            break
        card = _best(candidates, state)
        _place(card, *_fill_reason(card, state), state)


def _pip_demand(cards: List[Tuple[OwnedCard, int]], colors: FrozenSet[str]) -> Dict[str, int]:
    demand = {}  # type: Dict[str, int]
    for card, count in cards:
        for color, pips in card.pips.items():
            if color in colors:
                demand[color] = demand.get(color, 0) + pips * count
    return demand


def _color_ranks(demand: Dict[str, int]) -> List[str]:
    """Deck colors with pip demand, most demanded first (ties in WUBRG order)."""
    return sorted((c for c, n in demand.items() if n > 0),
                  key=lambda c: (-demand[c], COLORS.index(c)))


def _splash_colors(demand: Dict[str, int]) -> FrozenSet[str]:
    return frozenset(_color_ranks(demand)[len(SOURCE_RANKS):])


def _split_basics(total: int, colors: FrozenSet[str], demand: Dict[str, int]) -> Dict[str, int]:
    """Split basic lands across the colors by pip share (largest remainder)."""
    if total <= 0:
        return {}
    ordered = _ordered(colors)
    if not ordered:
        return {COLORLESS_BASIC: total}
    weights = {c: demand.get(c, 0) for c in ordered}
    if not sum(weights.values()):
        weights = {c: 1 for c in ordered}
    whole = sum(weights.values())
    shares = {c: total * weights[c] / whole for c in ordered}
    split = {c: int(shares[c]) for c in ordered}
    by_remainder = sorted(ordered, key=lambda c: (-(shares[c] - split[c]), COLORS.index(c)))
    for c in by_remainder[:total - sum(split.values())]:
        split[c] += 1
    return {BASIC_FOR_COLOR[c]: n for c, n in split.items() if n > 0}


def fetch_colors(card: OwnedCard, colors: FrozenSet[str]) -> FrozenSet[str]:
    """Return the deck colors a land can fetch from the library.

    Args:
        card: Land card. Its oracle text is read.
        colors: Deck colors.

    Returns:
        All deck colors when the land searches for a basic land card; the
        colors of the named basic land types ("a Forest or Plains card");
        else an empty set.
    """
    found = set()  # type: Set[str]
    for clause in _FETCH.findall(card.oracle_text or ""):
        if _BASIC_LAND.search(clause):
            return frozenset(colors)
        found.update(_TYPE_COLOR[name.lower()] for name in _BASIC_TYPE.findall(clause))
    return frozenset(found) & colors


def land_colors(card: OwnedCard, colors: FrozenSet[str]) -> FrozenSet[str]:
    """Return the deck colors a land is a source for: the colors it makes or fetches.

    Args:
        card: Land card.
        colors: Deck colors.

    Returns:
        (produced_mana & colors) | fetch_colors(card, colors).
    """
    return (frozenset(card.produced_mana) & colors) | fetch_colors(card, colors)


def land_tier(card: OwnedCard, colors: FrozenSet[str]) -> Optional[int]:
    """Return the priority tier of a nonbasic land for the deck colors.

    Args:
        card: Land card (identity already inside the deck colors).
        colors: Deck colors.

    Returns:
        TIER_DUAL for fetch lands and for lands that make 2+ deck colors and
        nothing outside the deck colors and C; TIER_ANY for lands that make a
        deck color and also colors outside the deck; TIER_UTILITY for every
        other land that makes only deck colors or C (one color, colorless,
        none); None for a land that makes only colors outside the deck.
    """
    if fetch_colors(card, colors):
        return TIER_DUAL
    made = frozenset(card.produced_mana) & colors
    if card.produced_mana - colors - {"C"}:
        return TIER_ANY if made else None
    return TIER_DUAL if len(made) >= 2 else TIER_UTILITY


def _tier_limits(fmt: FormatRules, colors: FrozenSet[str]) -> Dict[int, float]:
    if fmt.deck_size >= 80:
        any_color = ANY_COLOR_LIMIT_100
    else:
        any_color = ANY_COLOR_LIMIT_60 if len(colors) >= ANY_COLOR_MIN_COLORS_60 else 0
    return {TIER_DUAL: float("inf"), TIER_ANY: any_color,
            TIER_UTILITY: fmt.utility_land_limit}


def _mana_base(lands: List[OwnedCard], colors: FrozenSet[str], demand: Dict[str, int],
               fmt: FormatRules, target: int, land_slots: int,
               required: List[OwnedCard]) -> Tuple[List[DeckEntry], List[str], List[str]]:
    """Choose nonbasic lands and basic lands, then check color sources.

    Args:
        lands: Playable owned lands (identity in the deck colors, legal, not basic).
        colors: Deck colors.
        demand: Pip demand per color of the placed nonland cards.
        fmt: Format rules (utility limit, color sources, copies).
        target: Land target. Nonbasics take at most target - basics floor.
        land_slots: Number of land cards to place (more than target on a shortfall).
        required: Required land cards. They go first, inside their tier limit.

    Returns:
        (land entries, warnings, notes). Lands rank by tier (see land_tier),
        then deck colors covered, then quality. Any-color lands stop at 3
        copies in 100-card decks and at 2 in 60-card decks with 3+ colors
        (0 otherwise); other single-color and colorless lands stop at
        fmt.utility_land_limit. Basic lands fill the rest.
    """
    floor = len(colors) * (4 if fmt.deck_size >= 80 else 3)
    cap = max(0, min(target, land_slots) - floor)
    limits = _tier_limits(fmt, colors)
    required_ids = {card.id for card in required}
    warnings = []  # type: List[str]
    tiers = {l.id: land_tier(l, colors) for l in lands}
    for card in required:
        if tiers.get(card.id) is None:
            warnings.append(f"Couldn't fit {card.name}: it makes no mana of the deck colors.")
    ranked = sorted((l for l in lands if tiers[l.id] is not None),
                    key=lambda l: (l.id not in required_ids, tiers[l.id],
                                   -len(land_colors(l, colors)), -l.quality, l.name))
    entries = []  # type: List[DeckEntry]
    taken = 0
    per_tier = {}  # type: Dict[int, int]
    for card in ranked:
        tier = tiers[card.id]
        room = limits[tier] - per_tier.get(tier, 0)
        count = int(min(copies_for(card, fmt), cap - taken, room))
        if count <= 0:
            if card.id in required_ids:
                why = (TIER_FULL[tier] if cap > taken and room <= 0
                       else "no room left for nonbasic lands")
                warnings.append(f"Couldn't fit {card.name}: {why}.")
            continue
        taken += count
        per_tier[tier] = per_tier.get(tier, 0) + count
        made = "/".join(_ordered(land_colors(card, colors)))
        if not made:
            reason = "Utility land."
        elif card.produced_mana & colors:
            reason = f"Makes {made} mana."
        else:
            reason = f"Fetches {made} mana."
        entries.append(DeckEntry(card=card, name=card.name, count=count, role="land",
                                 reason=reason))
    split = _split_basics(land_slots - taken, colors, demand)
    for name, count in split.items():
        color = next((c for c, n in BASIC_FOR_COLOR.items() if n == name), None)
        reason = f"Basic land for {COLOR_NAMES[color]}." if color else "Basic land."
        entries.append(DeckEntry(card=None, name=name, count=count, role="basic",
                                 reason=reason, basic=True))
    notes = []
    if split:
        notes.append(f"Add {sum(split.values())} basic lands: "
                     + ", ".join(f"{n} {name}" for name, n in split.items()))
    return entries, warnings + _source_warnings(entries, demand, fmt, colors), notes


def _source_warnings(entries: List[DeckEntry], demand: Dict[str, int],
                     fmt: FormatRules, colors: FrozenSet[str]) -> List[str]:
    """Warn for each demanded color with fewer sources than fmt.color_sources.

    A nonbasic land is a source for each deck color in land_colors; a basic
    land for its own color.
    """
    sources = {}  # type: Dict[str, int]
    for entry in entries:
        made = land_colors(entry.card, colors) if entry.card is not None else {
            c for c, n in BASIC_FOR_COLOR.items() if n == entry.name}
        for color in made:
            sources[color] = sources.get(color, 0) + entry.count
    warnings = []
    for rank, color in enumerate(_color_ranks(demand)):
        need = fmt.color_sources[SOURCE_RANKS[rank] if rank < len(SOURCE_RANKS) else "splash"]
        have = sources.get(color, 0)
        if have < need:
            warnings.append(f"Only {have} {COLOR_NAMES[color]} sources; {need} recommended.")
    return warnings


def _avg_cmc(cards: List[Tuple[OwnedCard, int]], fallback: float) -> float:
    copies = sum(count for _, count in cards)
    if not copies:
        return fallback
    return sum(card.cmc * count for card, count in cards) / copies


def _curve_mean(curve: Dict[str, float]) -> float:
    total = sum(curve.values())
    if not total:
        return 2.5
    return sum(share * (6 if bucket == "6+" else int(bucket))
               for bucket, share in curve.items()) / total


def _resolve_required(plan: BuildPlan, pool: List[OwnedCard],
                      all_cards: List[OwnedCard]) -> Tuple[List[OwnedCard], List[str]]:
    """Match required names to playable cards. Unmatched names become warnings."""
    by_name = {card.name.lower(): card for card in pool}
    known = {card.name.lower(): card for card in all_cards}
    commander = plan.commander.name.lower() if plan.commander else None
    found, seen, warnings = [], set(), []  # type: List[OwnedCard], Set[str], List[str]
    for name in sorted(plan.required, key=str.lower):
        key = name.strip().lower()
        if key == commander or (key in known and known[key].is_basic):
            continue
        if key in by_name:
            if by_name[key].id not in seen:  # "Sol Ring" and "sol ring " are one card
                seen.add(by_name[key].id)
                found.append(by_name[key])
        else:
            warnings.append(f"{name.strip()} is not an owned, legal card in the deck colors; "
                            "left it out.")
    return found, warnings


def build_deck(cards: List[OwnedCard], graph: SynergyGraph, playbook: Playbook,
               plan: BuildPlan, fmt: FormatRules) -> BuiltDeck:
    """Build a legal deck from owned cards around a backbone.

    Args:
        cards: Tagged owned cards (hydrated for the format).
        graph: Synergy graph of the cards.
        playbook: Playbook with quotas, curve targets and score weights.
        plan: Backbone, playstyle, preferred and required names, commander.
        fmt: Format rules. Pass the scaled rules for a Casual deck.

    Returns:
        The deck. Every entry is owned (basic lands excepted), legal, inside
        the deck colors, and within copies_for. total() equals fmt.deck_size;
        basic lands fill any slots the pool cannot fill.
    """
    commander = plan.commander if fmt.commander else None
    colors = deck_colors(plan, fmt)
    pool = [c for c in cards if _playable(c, colors, commander.id if commander else None)]
    nonland = [c for c in pool if not c.is_land]
    lands = [c for c in pool if c.is_land]
    required, warnings = _resolve_required(plan, pool, cards)
    required_nonland = [c for c in required if not c.is_land]
    member_ids = set(plan.backbone.members)
    members = [c for c in nonland if c.id in member_ids]
    core = set(member_ids) | ({commander.id} if commander else set())
    reserved = 1 if commander else 0
    curve = playbook.curve_target(fmt, plan.playstyle)
    seed = [(c, copies_for(c, fmt)) for c in required_nonland + members]
    seed += [(commander, 1)] if commander else []
    splash = _splash_colors(_pip_demand(seed, colors))
    synergy = {}  # type: Dict[str, float]

    target = land_target(fmt, _avg_cmc(seed, _curve_mean(curve)), 0)
    state = None  # type: Optional[_State]
    for _ in range(PASSES):
        state = _State(fmt=fmt, weights=playbook.weights, graph=graph, core=core,
                       quotas=playbook.quotas(fmt, plan.playstyle), curve=curve,
                       splash=splash, prefer={n.strip().lower() for n in plan.prefer},
                       slots=max(0, fmt.deck_size - target - reserved), synergy=synergy)
        _place_nonland(nonland, members, required_nonland, plan, state)
        placed = [(p.card, p.count) for p in state.picks]
        mdfc = sum(count for card, count in placed if card.mdfc_land_back)
        settled = land_target(fmt, _avg_cmc(placed, _curve_mean(curve)), mdfc)
        if settled == target:
            break
        target = settled
    # The last pass sized its slots with `target` only when it settled; keep that size.
    target = fmt.deck_size - reserved - state.slots

    if state.filled < state.slots:
        warnings.append(SHORTFALL.format(k=state.filled))
    warnings += [NO_ROOM.format(name=c.name) for c in required_nonland
                 if not state.counts.get(c.id)]
    placed = [(p.card, p.count) for p in state.picks]
    demand = _pip_demand(placed + ([(commander, 1)] if commander else []), colors)
    land_slots = fmt.deck_size - reserved - state.filled
    land_entries, source_warnings, notes = _mana_base(
        lands, colors, demand, fmt, target, land_slots,
        [c for c in required if c.is_land])
    warnings += source_warnings

    entries = [DeckEntry(card=p.card, name=p.card.name, count=p.count, role=p.role,
                         reason=p.reason) for p in state.picks]
    bench = sorted(_open(nonland, state),
                   key=lambda c: (-_card_score(c, state), -c.quality, c.name))[:WINDOW]
    return BuiltDeck(
        fmt=fmt, plan=plan, entries=entries + land_entries, land_target=target,
        warnings=warnings, notes=notes,
        borderline_in=[p.card.id for p in state.picks[-WINDOW:]],
        bench=[c.id for c in bench],
    )

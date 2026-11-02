"""Validated one-for-one card swaps for the deck forge.

A local model proposes swaps and may invent names or propose illegal cards.
The engine checks every swap against the deck and the owned, legal pool, and
applies only the valid ones. Makes no network calls.
"""

from typing import Dict, List, Set

from backend.forge.builder import LEGAL, WINDOW, BuiltDeck, DeckEntry, copies_for, deck_colors
from backend.forge.cards import OwnedCard

MAX_SWAPS = 8
WHY_LIMIT = 120


def _key(name) -> str:
    return str(name or "").strip().lower()


def _usable(card: OwnedCard, deck_names: Set[str], colors) -> bool:
    return (card.owned > 0 and card.legality in LEGAL and not card.is_land
            and not card.is_basic and "Token" not in card.types
            and card.color_identity <= colors and card.name.lower() not in deck_names)


def _insert_at(entries: List[DeckEntry]) -> int:
    """Return the index after the last nonland entry (new cards go there)."""
    last = -1
    for i, entry in enumerate(entries):
        if not entry.basic and entry.card is not None and not entry.card.is_land:
            last = i
    return last + 1


def apply_swaps(deck: BuiltDeck, swaps: List[dict], pool: Dict[str, OwnedCard],
                protected: Set[str]) -> List[dict]:
    """Apply the valid swaps to a deck, in place.

    Args:
        deck: Built deck. Its entries, borderline_in and bench change.
        swaps: Proposed swaps, each with "out", "in" and "why".
        pool: Owned cards keyed by lowercase name.
        protected: Names (any case) that must stay in the deck.

    Returns:
        The applied swaps as {"out", "in", "why"} with canonical names. A swap
        is valid when "out" is an unprotected nonland, non-basic, non-commander
        entry and "in" is an owned, legal, nonland card in the deck colors that
        is not in the deck. At most MAX_SWAPS apply. When fewer copies come in
        than go out, the outgoing entry keeps the remaining copies.
    """
    colors = deck_colors(deck.plan, deck.fmt)
    locked = {_key(name) for name in protected}
    commander = deck.commander.name.lower() if deck.commander else None
    applied = []  # type: List[dict]
    outgoing = []  # type: List[OwnedCard]
    for swap in swaps:
        if len(applied) >= MAX_SWAPS:
            break
        if not isinstance(swap, dict):
            continue
        out_key, in_key = _key(swap.get("out")), _key(swap.get("in"))
        entry = next((e for e in deck.nonland_entries() if e.name.lower() == out_key), None)
        card = pool.get(in_key)
        if (entry is None or out_key in locked or out_key == commander
                or card is None or not _usable(card, deck.names(), colors)):
            continue
        why = str(swap.get("why") or "").strip()[:WHY_LIMIT]
        count = min(entry.count, copies_for(card, deck.fmt))
        if count <= 0:
            continue
        if count == entry.count:
            deck.entries.remove(entry)
            outgoing.append(entry.card)
        else:
            entry.count -= count  # partial swap: the rest of the outgoing card stays
        deck.entries.insert(_insert_at(deck.entries), DeckEntry(
            card=card, name=card.name, count=count, role=entry.role, reason=why))
        applied.append({"out": entry.name, "in": card.name, "why": why})
    if applied:
        _refresh(deck, pool, outgoing, colors)
    return applied


def _refresh(deck: BuiltDeck, pool: Dict[str, OwnedCard], outgoing: List[OwnedCard], colors) -> None:
    """Rebuild borderline_in and bench after swaps."""
    nonland = [e.card.id for e in deck.nonland_entries()]
    in_deck = set(nonland)
    # New cards sit after the last nonland entry, so they come last in placement order.
    deck.borderline_in = nonland[-WINDOW:]
    by_id = {c.id: c for c in pool.values()}
    names = deck.names()
    first = [c.id for c in outgoing if c.id not in in_deck]  # newly outgoing cards go first
    bench = first + [i for i in deck.bench if i not in in_deck and i not in first]
    if len(bench) < WINDOW:
        rest = sorted((c for c in by_id.values()
                       if c.id not in bench and _usable(c, names, colors)),
                      key=lambda c: (-c.quality, c.name))
        bench += [c.id for c in rest][:WINDOW - len(bench)]
    deck.bench = bench[:WINDOW]

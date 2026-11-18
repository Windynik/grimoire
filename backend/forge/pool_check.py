"""The Forge check before a run, and the reason when a run finds no plan.

The check builds the card pool as the forge session does (hydrate with the
same format rules) and uses the size rule of the plan search (core_size and
core_need in backend.forge.graph). So the check blocks only a run that is
sure to fail, and the failure of a run gives the same numbers.
"""

from typing import Dict, FrozenSet, List, Optional

from backend.core.collection_store import copies_of
from backend.forge.cards import OwnedCard, hydrate
from backend.forge.graph import (
    commander_candidates, core_need, counts_cards, largest_group, plan_room,
)
from backend.forge.playbook import FormatRules

NO_CARDS = "The chosen collections have no cards."
CHOOSE_COMMANDER = "Choose a commander, and the forge builds around it with the cards you have."


def _unit(fmt: FormatRules) -> str:
    return "different cards" if counts_cards(fmt) else "cards"


def _copies(fmt: FormatRules) -> str:
    return "" if counts_cards(fmt) else ", counting up to %d copies of each" % fmt.max_copies


def _summary(legal: int, cards: int, fmt: FormatRules) -> str:
    if legal == cards > 1:
        head = "All {:,} of your cards are legal".format(cards)
    else:
        head = "{:,} of your {:,} card{} {} legal".format(legal, cards, "" if cards == 1 else "s",
                                                         "is" if legal == 1 else "are")
    return "%s in %s. A %s deck has %d cards." % (head, fmt.name, fmt.name, fmt.deck_size)


def _problem(fmt: FormatRules, leaders: Optional[int], room: int, need: int,
             colors: Optional[FrozenSet[str]]) -> Optional[str]:
    """Return why a run is sure to fail, or None when the pool has room for a plan."""
    name = fmt.name
    if fmt.commander and not leaders:
        return "A %s deck needs a commander, and none of your legal cards can be one." % name
    if room >= need:
        return None
    if fmt.commander:
        have = ("The best commander you own has %d." % room if room
                else "No commander you own has any.")
        return ("A %s deck needs a commander and at least %d more %s in its colors that are not "
                "lands%s. %s %s" % (name, need, _unit(fmt), _copies(fmt), have, CHOOSE_COMMANDER))
    where = " in your colors" if colors is not None else ""
    have = "You have %d." % room if room else "You have none."
    return "A %s deck needs at least %d %s%s that are not lands%s. %s" % (
        name, need, _unit(fmt), where, _copies(fmt), have)


def check_pool(collection: List[dict], index: Dict[str, dict], fmt: FormatRules,
               colors: Optional[FrozenSet[str]] = None) -> dict:
    """Count the legal cards of a pool, and say when no plan can fit.

    Args:
        collection: The rows of the pool, as the forge gets them.
        index: Compact card records keyed by Scryfall id.
        fmt: Format rules, already resized for Casual.
        colors: The colors the owner chose (Casual), or None.

    Returns:
        cards (copies in the pool), legal (copies legal in the format), room
        and need (see plan_room and core_need), commanders (None outside
        commander formats), deck_size, summary (a line for the setup screen),
        problem (why the run is sure to fail, or None), and commander_lifts
        (True when a chosen commander lets the run go on: the forge then
        builds from the best cards in the colors of the commander).
    """
    cards = hydrate(collection, index, fmt)
    total = copies_of(collection)
    legal = sum(card.owned for card in cards)
    leaders = len(commander_candidates(cards, fmt)) if fmt.commander else None
    room = plan_room(cards, fmt, colors)
    need = core_need(fmt)
    result = {"format": fmt.name, "deck_size": fmt.deck_size, "cards": total, "legal": legal,
              "room": room, "need": need, "commanders": leaders, "summary": "",
              "problem": NO_CARDS, "commander_lifts": False}
    if total:
        problem = _problem(fmt, leaders, room, need, colors)
        result.update(summary=_summary(legal, total, fmt), problem=problem,
                      commander_lifts=bool(problem and fmt.commander and leaders))
    return result


def no_plan_message(cards: List[OwnedCard], fmt: FormatRules,
                    colors: Optional[FrozenSet[str]] = None) -> str:
    """Return the error of a run that found no plan, with the numbers behind it.

    Args:
        cards: Tagged owned cards, legal in the format.
        fmt: Format rules of the run.
        colors: The colors of the last plan search, or None.

    Returns:
        "No deck plan fits ..." and why: no commander, or what a plan needs
        and the largest group of the pool, or a large group with too little
        synergy. In commander formats it adds that a chosen commander works.
    """
    text = "No deck plan fits the cards you own in %s." % fmt.name
    leaders = commander_candidates(cards, fmt) if fmt.commander else []
    if fmt.commander and not leaders:
        return text + " None of your legal cards can be your commander."
    best, need = largest_group(cards, fmt, colors), core_need(fmt)
    if not best:
        text += " None of your cards share a theme."
    elif best < need:
        if fmt.commander:
            scope = "and fit the colors of one commander"
        else:
            scope = "in your colors" if colors is not None else "in one or two colors"
        text += (" A plan needs at least %d %s that share a theme %s%s. Your largest group has "
                 "%d." % (need, _unit(fmt), scope, _copies(fmt), best))
    else:
        text += (" Your largest group of cards that share a theme has %d, but they do not work "
                 "together well enough for a plan." % best)
    return text + (" " + CHOOSE_COMMANDER if leaders else "")

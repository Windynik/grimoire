"""The card pool of the deck editor: one row per card name.

The Collection screen shows one row per printing and finish. The editor adds
cards by name, so its search groups the rows: the copies of every printing add
up, and the printing with the most copies stands for the card.
"""

from typing import Dict, List, Tuple


def _copies(value) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def _money(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def group_by_name(cards: List[dict]) -> List[dict]:
    """One row per card name, in the order of the first row of each name.

    Args:
        cards: Owned card rows (name, scryfall_id, quantity, value), one per
            printing and finish. The rows do not change.

    Returns:
        For each name, a copy of the first row of the printing with the most
        copies (the first printing on a tie), with quantity (the copies of all
        printings and finishes), value (their sum) and printings (the number
        of different Scryfall ids).
    """
    stacks = {}  # type: Dict[str, Dict[str, Tuple[int, dict]]]
    values = {}  # type: Dict[str, float]
    for card in cards:
        name = card.get("name") or ""
        printings = stacks.setdefault(name, {})
        sid = str(card.get("scryfall_id") or "")
        copies, first = printings.get(sid, (0, card))
        printings[sid] = (copies + _copies(card.get("quantity")), first)
        values[name] = values.get(name, 0.0) + _money(card.get("value"))
    grouped = []
    for name, printings in stacks.items():  # dicts keep the order of the first row
        # max() keeps the first printing of a tie.
        _, first = max(printings.values(), key=lambda stack: stack[0])
        grouped.append(dict(first,
                            quantity=sum(stack[0] for stack in printings.values()),
                            value=round(values[name], 2),
                            printings=len(printings)))
    return grouped


def first_per_name(matches: List[Tuple[str, dict]]) -> Tuple[List[Tuple[str, dict]], Dict[str, int]]:
    """The first printing of each card name in archive matches, and the printings per name.

    Args:
        matches: (Scryfall id, card record) pairs, in the order to show.

    Returns:
        (the first pair of each name, {name: number of printings})
    """
    kept = []  # type: List[Tuple[str, dict]]
    counts = {}  # type: Dict[str, int]
    for card_id, info in matches:
        name = info.get("name") or ""
        if name not in counts:
            counts[name] = 0
            kept.append((card_id, info))
        counts[name] += 1
    return kept, counts

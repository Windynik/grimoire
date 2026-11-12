"""The pull list of a deck: where to find each card on the shelf.

Each card of the deck (commander, main deck and sideboard) comes from the
owned copies in any collection, in any printing. The list groups the copies
by collection and binder, so the owner can take the cards out one binder at
a time. Pure functions. Makes no network calls.
"""

from typing import Dict, List, Optional, Tuple

from backend.decks.records import entry_key

BASICS_GROUP = "Basic lands"
# The sections whose cards go on the table. The maybeboard stays on the shelf.
PULLED_SECTIONS = ("main", "sideboard")


def _quantity(value) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 1


def _card_key(scryfall_id: Optional[str], name: str, index: Dict[str, dict]) -> str:
    """One key for all printings of a card: the oracle id, else the lower-case name."""
    info = index.get(scryfall_id or "")
    if info is not None:
        return info.get("oracle_id") or info["id"]
    return "name:" + (name or "").strip().lower()


def _is_basic(line: dict, index: Dict[str, dict]) -> bool:
    if line.get("basic"):
        return True
    info = index.get(line.get("scryfall_id") or "")
    type_line = (info or {}).get("type_line") or ""
    return "Basic" in type_line.split("—")[0].split()


def _deck_lines(record: dict) -> List[dict]:
    """The lines to pull, with the commander first and copies of one line merged."""
    lines = []  # type: List[dict]
    commander = record.get("commander")
    if commander:
        lines.append(dict(commander, count=1))
    sections = record.get("sections") or {}
    for section in PULLED_SECTIONS:
        for line in sections.get(section) or []:
            if isinstance(line, dict) and line.get("name") and int(line.get("count") or 0) > 0:
                lines.append(line)
    return lines


def pull_list(record: dict, index: Dict[str, dict],
              collections: List[Tuple[dict, List[dict]]]) -> dict:
    """Return where to find each card of a deck.

    Args:
        record: Deck record (sections, commander, collection_job_id).
        index: Card index keyed by Scryfall id.
        collections: (meta, stored cards) per collection, newest first. A
            stored card has name, scryfall_id, quantity, foil and binder.

    Returns:
        {"groups": [{"job_id", "collection", "binder", "count", "cards"}],
         "basics": [{"name", "count"}], "missing": [{"name", "count"}]}.
        A group card is {"name", "count", "set", "number", "foil",
        "scryfall_id", "printing"}, where printing is True when it is the
        printing that the deck names. The deck's own collection comes first,
        then the others by name; the cards of a group sort by name.
    """
    own_job = record.get("collection_job_id")
    # Every owned stack, keyed by card: [job_id, name, binder, scryfall_id, foil, left].
    stacks = {}  # type: Dict[str, List[list]]
    names = {}  # type: Dict[str, str]
    for position, (meta, cards) in enumerate(collections):
        job_id = meta.get("job_id", "")
        names[job_id] = meta.get("name", "")
        for card in cards or []:
            left = _quantity(card.get("quantity"))
            if left <= 0:
                continue
            key = _card_key(card.get("scryfall_id"), card.get("name", ""), index)
            stacks.setdefault(key, []).append(
                [job_id, position, str(card.get("binder") or ""), card.get("scryfall_id"),
                 card.get("foil"), left])

    groups = {}  # type: Dict[Tuple[str, str], Dict[str, dict]]
    basics = {}  # type: Dict[str, int]
    missing = {}  # type: Dict[str, int]
    for line in _deck_lines(record):
        need = int(line.get("count") or 0)
        if _is_basic(line, index):
            basics[line["name"]] = basics.get(line["name"], 0) + need
            continue
        wanted = line.get("scryfall_id")
        options = stacks.get(_card_key(wanted, line["name"], index), [])
        # Same printing first, then the deck's own collection, then the largest
        # stack, then the newest collection.
        options.sort(key=lambda s: (s[3] != wanted, s[0] != own_job, -s[5], s[1]))
        for stack in options:
            if need <= 0:
                break
            take = min(need, stack[5])
            if take <= 0:
                continue
            stack[5] -= take
            need -= take
            job_id, _, binder, scryfall_id, foil, _ = stack
            info = index.get(scryfall_id or "") or {}
            cards = groups.setdefault((job_id, binder), {})
            item = cards.setdefault(entry_key({"scryfall_id": scryfall_id, "name": line["name"]})
                                    + "|" + str(foil), {
                "name": info.get("name") or line["name"],
                "count": 0,
                "set": (info.get("set") or "").upper(),
                "number": info.get("collector_number") or "",
                "foil": str(foil or "normal"),
                "scryfall_id": scryfall_id,
                "printing": scryfall_id == wanted,
            })
            item["count"] += take
        if need > 0:
            missing[line["name"]] = missing.get(line["name"], 0) + need

    ordered = sorted(groups.items(), key=lambda g: (g[0][0] != own_job,
                                                    names.get(g[0][0], "").lower(),
                                                    g[0][1].lower()))
    return {
        "groups": [{
            "job_id": job_id,
            "collection": names.get(job_id, ""),
            "binder": binder,
            "count": sum(c["count"] for c in cards.values()),
            "cards": sorted(cards.values(), key=lambda c: c["name"].lower()),
        } for (job_id, binder), cards in ordered],
        "basics": [{"name": n, "count": c} for n, c in sorted(basics.items())],
        "missing": [{"name": n, "count": c} for n, c in sorted(missing.items())],
    }

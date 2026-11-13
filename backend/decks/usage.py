"""Copies in use: how many copies of each card the saved decks hold, and how many are free.

A card counts across all its printings (by oracle id). Only a built deck (a
deck the owner put together from real cards, record key "built") holds
copies. A built deck uses the copies of its main deck, its sideboard and its
commander; the maybeboard stays on the shelf. Forge drafts and other ideas are
not built, so they hold no copies. The owned copies are those of the current collections: an older import
of the same collection does not count twice (see current_collections).
"""

from typing import Dict, Iterable, List, Optional, Tuple

from backend.core.collection_query import SAME_COLLECTION_SHARE
from backend.decks.records import entry_key

USED_SECTIONS = ("main", "sideboard")


def card_key(scryfall_id: Optional[str], name: str, index: Dict[str, dict]) -> str:
    """One key for all printings of a card: the oracle id, else the lower-case name."""
    info = index.get(scryfall_id or "")
    if info is not None:
        return info.get("oracle_id") or info["id"]
    return "name:" + (name or "").strip().lower()


def _count(value) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 1


def deck_copies(record: dict, index: Dict[str, dict]) -> Dict[str, int]:
    """The copies of each card that a deck uses (main deck, sideboard, commander)."""
    copies = {}  # type: Dict[str, int]
    commander = record.get("commander")
    if isinstance(commander, dict) and commander.get("name"):
        key = card_key(commander.get("scryfall_id"), commander["name"], index)
        copies[key] = copies.get(key, 0) + 1
    sections = record.get("sections") or {}
    for section in USED_SECTIONS:
        for line in sections.get(section) or []:
            if not isinstance(line, dict) or not line.get("name") or line.get("basic"):
                continue
            key = card_key(line.get("scryfall_id"), line["name"], index)
            copies[key] = copies.get(key, 0) + _count(line.get("count"))
    return copies


def usage_by_card(decks: Iterable[dict], index: Dict[str, dict]) -> Dict[str, List[dict]]:
    """For each card, the decks that hold it: [{"deck_id", "name", "count", "built"}]."""
    usage = {}  # type: Dict[str, List[dict]]
    for record in decks:
        for key, count in deck_copies(record, index).items():
            usage.setdefault(key, []).append(
                {"deck_id": record.get("id", ""), "name": record.get("name", ""), "count": count,
                 "built": bool(record.get("built"))})
    return usage


def decked_keys(deck_store, index: Dict[str, dict]) -> set:
    """The card keys of every saved deck, built or not (main, sideboard, commander)."""
    keys = set()
    for summary in deck_store.list():
        record = deck_store.get(summary.get("id", ""))
        if record is not None:
            keys.update(deck_copies(record, index))
    return keys


def used_counts(usage: Dict[str, List[dict]], exclude_deck: Optional[str] = None) -> Dict[str, int]:
    """The copies of each card that the built decks use, without one deck when given."""
    return {key: sum(d["count"] for d in decks if d["built"] and d["deck_id"] != exclude_deck)
            for key, decks in usage.items()}


def current_collections(collections: List[Tuple[dict, List[dict]]]) -> List[Tuple[dict, List[dict]]]:
    """The collections that hold the cards now, newest first.

    A collection drops out when a newer one holds at least SAME_COLLECTION_SHARE
    of its cards: it is an older import of the same cards. The binders of a
    split import share few cards with each other, so they all stay.
    """
    kept = []  # type: List[Tuple[dict, List[dict]]]
    for meta, rows in collections:
        ids = {row.get("scryfall_id") for row in rows or []}
        if ids and any(len(ids & {r.get("scryfall_id") for r in newer}) / len(ids)
                       >= SAME_COLLECTION_SHARE for _, newer in kept):
            continue
        kept.append((meta, rows))
    return kept


def owned_by_card(collections: List[Tuple[dict, List[dict]]], index: Dict[str, dict]) -> Dict[str, int]:
    """The owned copies of each card in the current collections."""
    owned = {}  # type: Dict[str, int]
    for _, rows in current_collections(collections):
        for row in rows or []:
            key = card_key(row.get("scryfall_id"), row.get("name", ""), index)
            owned[key] = owned.get(key, 0) + _count(row.get("quantity"))
    return owned


class CopiesInUse:
    """The owned and used copies of every card, read once from the stores."""

    def __init__(self, deck_store, collection_store, index: Dict[str, dict]):
        self.index = index
        decks = []
        for summary in deck_store.list():
            record = deck_store.get(summary.get("id", ""))
            if record is not None:
                decks.append(dict(record, id=summary["id"], name=summary.get("name", "")))
        self.usage = usage_by_card(decks, index)
        collections = [(meta, collection_store.get_collection(meta["job_id"]) or [])
                       for meta in collection_store.list_collections()]
        self.owned = owned_by_card(collections, index)

    def key(self, scryfall_id: Optional[str], name: str = "") -> str:
        return card_key(scryfall_id, name, self.index)

    def status(self, key: str, exclude_deck: Optional[str] = None) -> Dict:
        """{"decks", "used", "owned", "free"} of one card, without one deck when given.

        decks lists every saved deck with the card, built or not; used counts
        only the copies in built decks.
        """
        decks = [d for d in self.usage.get(key, []) if d["deck_id"] != exclude_deck]
        used = sum(d["count"] for d in decks if d["built"])
        owned = self.owned.get(key, 0)
        return {"decks": decks, "used": used, "owned": owned, "free": max(0, owned - used)}


def taken_cards(record: dict, deck_id: Optional[str], copies: CopiesInUse) -> Dict[str, dict]:
    """The cards of a deck that need more copies than the other decks leave free.

    Only a card that other decks use counts: a card the owner does not have
    enough copies of at all is "short", not "taken".

    Returns:
        {card key: {"need", "owned", "free", "decks"}}, where decks are the
        other built decks that use the card ({"deck_id", "name", "count", "built"}).
    """
    taken = {}  # type: Dict[str, dict]
    for key, need in deck_copies(record, copies.index).items():
        status = copies.status(key, exclude_deck=deck_id)
        if status["used"] > 0 and status["owned"] >= need > status["free"]:
            taken[key] = {"need": need, "owned": status["owned"], "free": status["free"],
                          "decks": [d for d in status["decks"] if d["built"]]}
    return taken


def mark_taken(analysis: dict, record: dict, taken: Dict[str, dict],
               index: Dict[str, dict]) -> None:
    """Add the issue "taken" and the other decks to each card line in the analysis."""
    if not taken:
        return
    lines = [record["commander"]] if isinstance(record.get("commander"), dict) else []
    sections = record.get("sections") or {}
    for section in USED_SECTIONS:
        lines.extend(line for line in sections.get(section) or [] if isinstance(line, dict))
    cards = analysis.get("cards") or {}
    for line in lines:
        found = taken.get(card_key(line.get("scryfall_id"), line.get("name", ""), index))
        report = cards.get(entry_key(line))
        if found is None or report is None or "taken" in report["issues"]:
            continue
        report["issues"].append("taken")
        report["taken"] = {"need": found["need"], "free": found["free"],
                           "decks": found["decks"]}
        names = ", ".join(d["name"] + (" ×%d" % d["count"] if d["count"] > 1 else "")
                          for d in found["decks"])
        report.setdefault("reasons", {})["taken"] = (
            "Other built decks use these copies: %s. This deck needs %d; %d free."
            % (names, found["need"], found["free"]))


def free_rows(rows: List[dict], copies: CopiesInUse) -> List[dict]:
    """The rows of a collection with only the copies that no built deck uses.

    The free copies of a card (owned in all collections minus the copies in
    decks) fill the rows in order; a row with no free copy drops out.
    """
    left = {}  # type: Dict[str, int]
    kept = []
    for row in rows or []:
        key = copies.key(row.get("scryfall_id"), row.get("name", ""))
        if key not in left:
            left[key] = copies.status(key)["free"]
        take = min(_count(row.get("quantity")), left[key])
        if take > 0:
            left[key] -= take
            kept.append(dict(row, quantity=take))
    return kept

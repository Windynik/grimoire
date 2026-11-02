"""Live deck analysis for the deck editor.

Checks every card line of a saved deck against the card index and a collection,
and grades the main deck with the forge's own metrics. Makes no network calls.
"""

from typing import Dict, FrozenSet, List, Optional

from backend.api.routes import best_price
from backend.decks.records import entry_key
from backend.forge.builder import (
    SOURCE_RANKS, BuildPlan, BuiltDeck, DeckEntry, color_ranks, color_sources,
)
from backend.forge.cards import (
    ANY_NUMBER_PHRASE, OwnedCard, build_card, fits_colors, is_game_card,
)
from backend.forge.graph import Backbone, build_graph
from backend.forge.metrics import _pip_demand, curve, deck_metrics
from backend.forge.playbook import FormatRules, Playbook
from backend.forge.tagging import tag_cards

ISSUE_CODES = ("not_a_card", "not_owned", "short", "banned", "not_legal", "off_color",
               "too_many")
CASUAL = "casual"
COLOR_ORDER = "WUBRG"


def _quantity(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _oracle_key(info: dict) -> str:
    return info.get("oracle_id") or info["id"]


def owned_counts(collection: List[dict], index: Dict[str, dict]) -> Dict[str, int]:
    """Count the owned copies of each card.

    Args:
        collection: Stored rows with scryfall_id and quantity (int or string)
        index: Card index keyed by Scryfall id

    Returns:
        Owned copies per oracle id, with all printings merged. A row whose id is
        not in the index is skipped.
    """
    counts = {}  # type: Dict[str, int]
    for row in collection:
        info = index.get(row.get("scryfall_id"))
        if info is None:
            continue
        key = _oracle_key(info)
        counts[key] = counts.get(key, 0) + _quantity(row.get("quantity"))
    return counts


def rules_for(record: dict, playbook: Playbook) -> FormatRules:
    """Return the format rules of a deck record.

    Args:
        record: Deck record
        playbook: Playbook with the formats

    Returns:
        The playbook format. Casual is resized to the record's deck_size
        (default 60) and max_copies (default 4).

    Raises:
        KeyError: The format is not in the playbook.
    """
    fmt = playbook.formats[record.get("format")]
    if fmt.key == CASUAL:
        return fmt.scaled(record.get("deck_size") or 60, record.get("max_copies") or 4)
    return fmt


def _legality(info: dict, fmt: FormatRules) -> str:
    if fmt.legality_key is None:
        return "legal"
    return (info.get("legalities") or {}).get(fmt.legality_key, "not_legal")


def _known(info: Optional[dict]) -> bool:
    return info is not None and is_game_card(info)


def _entry_cards(record: dict, index: Dict[str, dict], owned: Dict[str, int],
                 fmt: FormatRules) -> Dict[str, OwnedCard]:
    """Build one OwnedCard per known game card in the main deck and the commander."""
    lines = list((record.get("sections") or {}).get("main") or [])
    if record.get("commander"):
        lines.append(record["commander"])
    cards = {}  # type: Dict[str, OwnedCard]
    for line in lines:
        card_id = line.get("scryfall_id")
        info = index.get(card_id or "")
        if card_id in cards or not _known(info):
            continue
        cards[card_id] = build_card(info, _legality(info, fmt), owned.get(_oracle_key(info), 0))
    return cards


def deck_from_record(record: dict, index: Dict[str, dict], owned: Dict[str, int],
                     fmt: FormatRules, playbook: Playbook) -> BuiltDeck:
    """Turn a deck record into a tagged BuiltDeck of its main entries.

    Args:
        record: Deck record
        index: Card index keyed by Scryfall id
        owned: Owned copies per oracle id (see owned_counts)
        fmt: Format rules of the deck
        playbook: Playbook for the tags and the backbone defaults

    Returns:
        A BuiltDeck of the main section. Cards that are not in the index or are
        not game cards are left out. A basic land with no id has no card. The
        deck colors are the commander identity in commander formats, else the
        colors of the main nonland cards.
    """
    cards = _entry_cards(record, index, owned, fmt)
    tag_cards(list(cards.values()), playbook)
    entries = []  # type: List[DeckEntry]
    for line in (record.get("sections") or {}).get("main") or []:
        card_id = line.get("scryfall_id")
        if not card_id and line.get("basic"):
            entries.append(DeckEntry(card=None, name=line["name"], count=line["count"],
                                     role=line.get("role", ""), reason=line.get("reason", ""),
                                     basic=True))
        elif card_id in cards:
            entries.append(DeckEntry(card=cards[card_id], name=line["name"],
                                     count=line["count"], role=line.get("role", ""),
                                     reason=line.get("reason", "")))
    commander_line = record.get("commander") or {}
    commander = cards.get(commander_line.get("scryfall_id")) if fmt.commander else None
    if commander is not None:
        colors = frozenset(commander.color_identity)
    else:
        colors = frozenset(c for e in entries
                           if e.card is not None and not e.card.is_land
                           for c in e.card.color_identity)
    backbone = record.get("backbone") or {}
    bone = Backbone(id="editor", hooks=tuple(backbone.get("hooks") or ()),
                    name=backbone.get("name") or record.get("name", ""), members=[],
                    colors=colors, commander_id=commander.id if commander else None,
                    score=0.0)
    plan = BuildPlan(backbone=bone, playstyle=backbone.get("playstyle") or "midrange",
                     commander=commander)
    return BuiltDeck(fmt=fmt, plan=plan, entries=entries, land_target=0)


def _price(info: Optional[dict]) -> float:
    try:
        return float(best_price((info or {}).get("prices")))
    except (TypeError, ValueError):
        return 0.0


def _limit(info: dict, fmt: FormatRules) -> Optional[int]:
    """Copies of a card a deck may hold, or None for no limit."""
    if ANY_NUMBER_PHRASE in (info.get("oracle_text") or "").lower():
        return None
    if "Basic" in (info.get("type_line") or "").split("—")[0].split():
        return None
    return fmt.copies_allowed(_legality(info, fmt))


def _card_issues(info: Optional[dict], copies: int, owned: int, fmt: FormatRules,
                 commander_colors: Optional[FrozenSet[str]], full: bool) -> List[str]:
    if not _known(info):
        return ["not_a_card"]
    if not full:
        return []
    issues = []
    if owned == 0:
        issues.append("not_owned")
    elif owned < copies:
        issues.append("short")
    legality = _legality(info, fmt)
    if fmt.legality_key is not None and legality == "banned":
        issues.append("banned")
    elif fmt.legality_key is not None and legality not in ("legal", "restricted"):
        issues.append("not_legal")
    if commander_colors is not None:
        identity = frozenset(info.get("color_identity") or [])
        card = build_card(info, legality, owned)
        fits = identity <= commander_colors if card.is_land else fits_colors(
            card, commander_colors, fmt)
        if not fits:
            issues.append("off_color")
    limit = _limit(info, fmt)
    if limit is not None and copies > limit:
        issues.append("too_many")
    return issues


def _card_report(record: dict, index: Dict[str, dict], owned: Dict[str, int],
                 fmt: FormatRules, deck: BuiltDeck) -> Dict[str, dict]:
    sections = record.get("sections") or {}
    commander = record.get("commander")
    copies = {}  # type: Dict[str, int]
    lines = {}  # type: Dict[str, dict]
    for section in ("main", "sideboard"):
        for line in sections.get(section) or []:
            key = entry_key(line)
            copies[key] = copies.get(key, 0) + line["count"]
            lines.setdefault(key, line)
    if commander:
        key = entry_key(commander)
        copies[key] = copies.get(key, 0) + 1
        lines.setdefault(key, commander)
    for line in sections.get("maybeboard") or []:
        lines.setdefault(entry_key(line), line)
    commander_colors = None
    if fmt.commander and deck.commander is not None:
        commander_colors = frozenset(deck.commander.color_identity)
    roles = {e.card.id: sorted(e.card.roles) for e in deck.entries if e.card is not None}
    if deck.commander is not None:
        roles.setdefault(deck.commander.id, sorted(deck.commander.roles))
    report = {}
    for key, line in lines.items():
        info = index.get(line.get("scryfall_id") or "")
        basic = info is None and bool(line.get("basic")) and not line.get("scryfall_id")
        have = owned.get(_oracle_key(info), 0) if info is not None else 0
        if basic or (info is not None and "Basic" in (info.get("type_line") or "")):
            have = max(have, copies.get(key, 0))
        if basic:
            issues = []  # type: List[str]
        else:
            issues = _card_issues(info, copies.get(key, 0), have, fmt, commander_colors,
                                  key in copies)
        report[key] = {"owned": have, "issues": issues,
                       "roles": roles.get(line.get("scryfall_id"), [])}
    return report


def _mana(deck: BuiltDeck, fmt: FormatRules, colors: FrozenSet[str]) -> List[dict]:
    demand = {c: n for c, n in _pip_demand(deck, colors).items() if n > 0}
    ranks = color_ranks(demand)
    sources = color_sources(deck.entries, colors)
    rows = []
    for color in sorted(demand, key=COLOR_ORDER.index):
        rank = ranks.index(color)
        rows.append({"color": color, "pips": demand[color],
                     "sources": sources.get(color, 0),
                     "needed": fmt.color_sources[
                         SOURCE_RANKS[rank] if rank < len(SOURCE_RANKS) else "splash"]})
    return rows


def _totals(record: dict, index: Dict[str, dict]):
    """Return (price, game changer copies) of the main deck and the commander."""
    lines = [(line, line["count"]) for line in (record.get("sections") or {}).get("main") or []]
    if record.get("commander"):
        lines.append((record["commander"], 1))
    price = 0.0
    changers = 0
    for line, count in lines:
        info = index.get(line.get("scryfall_id") or "")
        price += count * _price(info)
        if info is not None and info.get("game_changer"):
            changers += count
    return round(price, 2), changers


def analyze(record: dict, index: Dict[str, dict], collection: Optional[List[dict]],
            collection_meta: Optional[dict], playbook: Playbook) -> dict:
    """Analyze a deck record against the card index and a collection.

    Args:
        record: Stored deck record
        index: Card index keyed by Scryfall id
        collection: Stored rows of the collection the deck uses, or None
        collection_meta: Metadata of that collection (job_id, name), or None
        playbook: Playbook with formats, quotas and weights

    Returns:
        Mapping with collection, format, count, curve, colors, mana, price,
        game_changers, metrics, cards (issue codes per entry key) and issues
        (deck level, each with a code and a message).

    Raises:
        KeyError: The record's format is not in the playbook.
    """
    fmt = rules_for(record, playbook)
    owned = owned_counts(collection or [], index)
    deck = deck_from_record(record, index, owned, fmt, playbook)
    colors = deck.plan.backbone.colors
    sections = record.get("sections") or {}
    count = {section: sum(line["count"] for line in sections.get(section) or [])
             for section in ("main", "sideboard", "maybeboard")}
    if record.get("commander"):
        count["main"] += 1
    count["target"] = fmt.deck_size
    mana = _mana(deck, fmt, colors)
    issues = []  # type: List[dict]
    if (count["main"] != fmt.deck_size) if fmt.commander else (count["main"] < fmt.deck_size):
        issues.append({"code": "size",
                       "message": "%d of %d cards" % (count["main"], fmt.deck_size)})
    if fmt.commander and not record.get("commander"):
        issues.append({"code": "no_commander", "message": "Choose a commander."})
    for row in mana:
        if row["sources"] < row["needed"]:
            issues.append({"code": "mana", "message": "%d %s sources; %d recommended." % (
                row["sources"], row["color"], row["needed"])})
    metrics = {}
    if deck.nonland_entries():
        cards = {e.card.id: e.card for e in deck.entries if e.card is not None}
        if deck.commander is not None:
            cards[deck.commander.id] = deck.commander
        metrics = deck_metrics(deck, build_graph(list(cards.values()), playbook), playbook)
    price, changers = _totals(record, index)
    meta = collection_meta or {}
    return {
        "collection": {"job_id": meta.get("job_id"), "name": meta.get("name") or ""},
        "format": {"key": fmt.key, "name": fmt.name, "deck_size": fmt.deck_size,
                   "commander": fmt.commander, "singleton": fmt.singleton,
                   "max_copies": fmt.max_copies},
        "count": count,
        "curve": curve(deck),
        "colors": sorted(colors, key=COLOR_ORDER.index),
        "mana": mana,
        "price": price,
        "game_changers": changers,
        "metrics": metrics,
        "cards": _card_report(record, index, owned, fmt, deck),
        "issues": issues,
    }

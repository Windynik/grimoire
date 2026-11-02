"""Deck records and plain-text decklists for the deck forge.

Turns a built deck into the JSON record the deck store saves, and a saved
record into a decklist that can be copied. Makes no network calls.
"""

from datetime import datetime, timezone
from typing import Dict, List

from backend.forge.builder import BuiltDeck
from backend.forge.metrics import curve


def _main_line(entry, reason: str) -> dict:
    card = entry.card
    if entry.basic or card is None:
        return {"scryfall_id": None, "name": entry.name, "count": entry.count,
                "role": entry.role, "reason": reason, "basic": True, "image_url": "",
                "mana_cost": "", "type_line": f"Basic Land — {entry.name}", "cmc": 0}
    return {"scryfall_id": card.id, "name": entry.name, "count": entry.count,
            "role": entry.role, "reason": reason, "basic": False,
            "image_url": card.image_url, "mana_cost": card.mana_cost,
            "type_line": card.type_line, "cmc": card.cmc}


def deck_to_record(deck: BuiltDeck, name: str, job_id: str, backbone_info: dict,
                   explanation: str, reasons: Dict[str, str],
                   metrics: Dict[str, float]) -> dict:
    """Convert a built deck to the JSON record the deck store saves.

    Args:
        deck: Built deck
        name: Deck name
        job_id: Id of the collection the deck was forged from
        backbone_info: Backbone keys (name, hooks, thesis, playstyle,
            key_interactions); missing name, hooks and playstyle come from deck.plan
        explanation: Markdown explanation of the deck
        reasons: Reason per card name; overrides the entry's own reason
        metrics: Deck metrics

    Returns:
        Deck record without an id (the store sets it). created and updated are
        set to now; the store keeps created and refreshes updated. The commander is outside sections.main, and null in other formats.
    """
    commander = deck.commander
    bone = deck.plan.backbone
    info = backbone_info or {}
    now = datetime.now(timezone.utc).isoformat()
    game_changers = sum(e.count for e in deck.nonland_entries() if e.card.game_changer)
    if commander is not None and commander.game_changer:
        game_changers += 1
    return {
        "name": name,
        "format": deck.fmt.key,
        "collection_job_id": job_id,
        "commander": ({"scryfall_id": commander.id, "name": commander.name,
                       "image_url": commander.image_url} if commander else None),
        "backbone": {
            "name": info.get("name") or bone.name,
            "hooks": list(info.get("hooks") or bone.hooks),
            "thesis": info.get("thesis", ""),
            "playstyle": info.get("playstyle") or deck.plan.playstyle,
            "key_interactions": list(info.get("key_interactions") or []),
        },
        "sections": {
            "main": [_main_line(e, reasons.get(e.name) or e.reason) for e in deck.entries],
            "sideboard": [],
            "maybeboard": [],
        },
        "explanation": explanation,
        "metrics": dict(metrics),
        "curve": curve(deck),
        "warnings": list(deck.warnings),
        "notes": list(deck.notes),
        "game_changers": game_changers,
        "created": now,
        "updated": now,
    }


def decklist_text(record: dict) -> str:
    """Return a plain-text decklist for a deck record.

    Args:
        record: Deck record

    Returns:
        Sections "Commander" (when present), "Deck", and "Sideboard" (when not
        empty), split by a blank line. Each card line is "{count} {name}".
    """
    sections = []  # type: List[str]
    commander = record.get("commander")
    if commander:
        sections.append("Commander\n1 " + commander["name"])
    sections_data = record.get("sections", {})
    main = sections_data.get("main", [])
    sections.append("\n".join(["Deck"] + [f"{c['count']} {c['name']}" for c in main]))
    side = sections_data.get("sideboard", [])
    if side:
        sections.append("\n".join(["Sideboard"] + [f"{c['count']} {c['name']}" for c in side]))
    return "\n\n".join(sections)

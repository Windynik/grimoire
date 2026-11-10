"""Deck records for saved decks: request models, edits, and display data.

A stored deck keeps only the facts the user edits plus the forge's own fields.
Card display data (mana cost, type, price) comes from the card index when the
deck is read. Makes no network calls.
"""

import copy
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from backend.core.prices import best_price

EDITABLE = ("name", "format", "commander", "collection_job_id", "deck_size", "max_copies",
            "sections")
DISPLAY_FIELDS = ("image_url", "back_image_url", "mana_cost", "type_line", "cmc", "price",
                  "set", "collector_number", "layout", "game_changer")
SECTIONS = ("main", "sideboard", "maybeboard")
# Display data the store keeps: the deck list shows one art URL without the card index
_KEPT_DISPLAY = ("image_url",)


class EntryIn(BaseModel):
    scryfall_id: Optional[str] = Field(None, max_length=64)
    name: str = Field(max_length=200)
    count: int = Field(ge=1, le=250)
    basic: bool = False
    role: str = Field("", max_length=40)
    reason: str = Field("", max_length=300)


class SectionsIn(BaseModel):
    main: List[EntryIn] = Field(default_factory=list, max_length=400)
    sideboard: List[EntryIn] = Field(default_factory=list, max_length=400)
    maybeboard: List[EntryIn] = Field(default_factory=list, max_length=400)


class CommanderIn(BaseModel):
    scryfall_id: str = Field(max_length=64)
    name: str = Field(max_length=200)


class EditIn(BaseModel):
    """The order mark of an editor save.

    client: a random id of one editor tab. seq: rises with each save of that
    tab. base_revision: the deck revision the tab last saw.
    """
    client: str = Field(min_length=1, max_length=64)
    seq: int = Field(ge=0)
    base_revision: int = Field(0, ge=0)


class DeckIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    format: str = Field(max_length=40)
    commander: Optional[CommanderIn] = None
    collection_job_id: Optional[str] = Field(None, max_length=64)
    deck_size: Optional[int] = Field(None, ge=40, le=250)
    max_copies: Optional[int] = Field(None, ge=1, le=4)
    sections: SectionsIn
    edit: Optional[EditIn] = None


def edit_check(stored: dict, edit: Optional[EditIn]) -> str:
    """Decide what to do with a save: "write", "stale" or "conflict".

    A save of the tab that wrote last is "write" when it is newer, else "stale"
    (an older request that landed late). A save of another tab is "write" only
    when the tab saw the newest revision, else "conflict". A save without a
    mark (an older client) is "write".
    """
    if edit is None:
        return "write"
    last = stored.get("edit") or {}
    if last.get("client") == edit.client:
        return "write" if edit.seq > int(last.get("seq", -1)) else "stale"
    return "write" if edit.base_revision == int(stored.get("revision", 0)) else "conflict"


class CreateDeck(BaseModel):
    name: str = Field("New deck", min_length=1, max_length=120)
    format: str = Field(max_length=40)
    collection_job_id: Optional[str] = Field(None, max_length=64)


def entry_key(entry: dict) -> str:
    """Key that identifies a card line: its Scryfall id, or "basic:{name}" for a basic land."""
    return entry.get("scryfall_id") or "basic:" + entry["name"]


def new_record(name: str, fmt_key: str, job_id: Optional[str]) -> dict:
    """Return an empty deck record (the shape of backend.forge.export.deck_to_record).

    Args:
        name: Deck name
        fmt_key: Playbook format key
        job_id: Id of the collection the deck uses, or None

    Returns:
        Deck record with empty sections and no id (the store sets it)
    """
    return {
        "name": name,
        "format": fmt_key,
        "collection_job_id": job_id,
        "deck_size": None,
        "max_copies": None,
        "commander": None,
        "backbone": None,
        "sections": {"main": [], "sideboard": [], "maybeboard": []},
        "explanation": "",
        "metrics": {},
        "curve": {},
        "warnings": [],
        "notes": [],
        "game_changers": 0,
    }


def apply_update(stored: dict, incoming: DeckIn) -> dict:
    """Return the stored record with the editable keys replaced by the incoming values.

    Args:
        stored: Stored deck record
        incoming: Validated edit from the client

    Returns:
        A new record. An entry's role and reason come from the incoming entry when
        not empty, else from the stored entry with the same entry_key. All other
        stored keys (backbone, explanation, metrics, notes, created) stay.
    """
    old = {}  # type: Dict[str, dict]
    for entries in (stored.get("sections") or {}).values():
        for entry in entries:
            if isinstance(entry, dict) and entry.get("name"):
                old.setdefault(entry_key(entry), entry)
    data = incoming.model_dump()
    sections = {}
    for section in SECTIONS:
        entries = []
        for entry in data["sections"][section]:
            previous = old.get(entry_key(entry), {})
            for field in ("role", "reason"):
                entry[field] = entry[field] or previous.get(field, "")
            entries.append(entry)
        sections[section] = entries
    record = dict(stored)
    for key in EDITABLE:
        record[key] = data[key]
    record["sections"] = sections
    record["revision"] = int(stored.get("revision", 0)) + 1
    if incoming.edit is not None:
        record["edit"] = {"client": incoming.edit.client, "seq": incoming.edit.seq}
    return record


def _fill(item: dict, info: dict) -> None:
    item["image_url"] = info.get("image_url", "")
    item["back_image_url"] = info.get("back_image_url", "")
    item["mana_cost"] = info.get("mana_cost", "")
    item["type_line"] = info.get("type_line", "")
    item["cmc"] = info.get("cmc", 0)
    item["price"] = best_price(info.get("prices"))
    item["set"] = info.get("set", "")
    item["collector_number"] = info.get("collector_number", "")
    item["layout"] = info.get("layout", "normal")
    item["game_changer"] = bool(info.get("game_changer", False))


def hydrate_record(record: dict, index: Dict[str, dict]) -> dict:
    """Return a deep copy of a record whose cards carry display data from the index.

    Args:
        record: Stored deck record
        index: Card index keyed by Scryfall id

    Returns:
        The copy. Entries and the commander get the DISPLAY_FIELDS; an id that is
        not in the index keeps its stored values. A basic land with no id gets
        type_line "Basic Land — {name}" and cmc 0.
    """
    result = copy.deepcopy(record)
    commander = result.get("commander")
    cards = [commander] if isinstance(commander, dict) else []
    for entries in (result.get("sections") or {}).values():
        cards.extend(e for e in entries if isinstance(e, dict))
    for card in cards:
        info = index.get(card.get("scryfall_id") or "")
        if info:
            _fill(card, info)
        elif not card.get("scryfall_id") and card.get("basic"):
            card["type_line"] = "Basic Land — " + card.get("name", "")
            card["cmc"] = 0
    return result


def strip_display(record: dict) -> dict:
    """Return a copy of a record without the display data the store must not keep.

    Args:
        record: Deck record, hydrated or not

    Returns:
        The copy without the DISPLAY_FIELDS on entries and the commander (image_url
        stays) and without the key "analysis".
    """
    result = copy.deepcopy(record)
    result.pop("analysis", None)
    commander = result.get("commander")
    cards = [commander] if isinstance(commander, dict) else []
    for entries in (result.get("sections") or {}).values():
        cards.extend(e for e in entries if isinstance(e, dict))
    for card in cards:
        for field in DISPLAY_FIELDS:
            if field not in _KEPT_DISPLAY:
                card.pop(field, None)
    return result

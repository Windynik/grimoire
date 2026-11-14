"""Collection exports in the formats of other apps.

Each exporter writes the CSV (or the card list) that the app's own import
reads: ManaBox, Moxfield, Archidekt and Deckbox, plus a plain card list that
most apps take as pasted text. Grimoire's importer reads all of them back
(see backend.core.importers). The stored rows give the name, quantity, finish
and binder; the card index gives the printing (set, set name, number,
rarity). Pure functions. Makes no network calls.

Grimoire does not track condition or language, so the exports write
"Near Mint" and "English", the defaults of each app.
"""

import csv
import io
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from backend.core.card_flags import flag_key
from backend.core.importers import foil_value


@dataclass
class Export:
    kind: str
    label: str
    extension: str
    media_type: str
    body: str


def _quantity(value) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 1


def _printing(row: dict, index: Dict[str, dict], flags: Dict[str, List[str]]) -> dict:
    """One owned stack with its printing filled in from the card index."""
    info = index.get(row.get("scryfall_id") or "") or {}
    quantity = _quantity(row.get("quantity"))
    marked = flags.get(flag_key(row.get("scryfall_id"), row.get("foil")), [])
    return {
        "trade": quantity if "trade" in marked else 0,
        "name": info.get("name") or row.get("name") or "",
        "quantity": _quantity(row.get("quantity")),
        "finish": foil_value(str(row.get("foil") or "")),
        "set": (info.get("set") or row.get("set") or "").lower(),
        "set_name": info.get("set_name") or "",
        "number": str(info.get("collector_number") or ""),
        "rarity": info.get("rarity") or row.get("rarity") or "",
        "scryfall_id": row.get("scryfall_id") or "",
        "binder": str(row.get("binder") or ""),
    }


def _csv(header: List[str], rows: List[list]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue()


def manabox(cards: List[dict]) -> str:
    """ManaBox's collection CSV, with the binder of each card."""
    header = ["Binder Name", "Name", "Set code", "Set name", "Collector number", "Foil",
              "Rarity", "Quantity", "Scryfall ID", "Condition", "Language"]
    return _csv(header, [[c["binder"], c["name"], c["set"].upper(), c["set_name"], c["number"],
                          c["finish"], c["rarity"], c["quantity"], c["scryfall_id"],
                          "near_mint", "en"] for c in cards])


def moxfield(cards: List[dict]) -> str:
    """Moxfield's collection CSV."""
    header = ["Count", "Tradelist Count", "Name", "Edition", "Condition", "Language", "Foil",
              "Tags", "Last Modified", "Collector Number", "Alter", "Proxy", "Purchase Price"]
    return _csv(header, [[c["quantity"], c["trade"], c["name"], c["set"], "Near Mint", "English",
                          "" if c["finish"] == "normal" else c["finish"], "", "",
                          c["number"], "False", "False", ""] for c in cards])


def archidekt(cards: List[dict]) -> str:
    """Archidekt's collection CSV."""
    header = ["Quantity", "Name", "Finish", "Condition", "Language", "Edition Name",
              "Edition Code", "Scryfall ID", "Collector Number", "Tags"]
    return _csv(header, [[c["quantity"], c["name"], c["finish"].capitalize(), "NM", "English",
                          c["set_name"], c["set"], c["scryfall_id"], c["number"], c["binder"]]
                         for c in cards])


def deckbox(cards: List[dict]) -> str:
    """Deckbox's inventory CSV. Deckbox names the edition by its set name."""
    header = ["Count", "Tradelist Count", "Name", "Edition", "Card Number", "Condition",
              "Language", "Foil", "Signed", "Artist Proof", "Altered Art", "Misprint",
              "Promo", "Textless", "My Price"]
    return _csv(header, [[c["quantity"], c["trade"], c["name"], c["set_name"], c["number"],
                          "Near Mint", "English", "" if c["finish"] == "normal" else "foil",
                          "", "", "", "", "", "", ""] for c in cards])


def card_list(cards: List[dict]) -> str:
    """One line per stack: "4 Lightning Bolt (2X2) 117 *F*". Most apps take it as pasted text."""
    lines = []
    for c in cards:
        where = " (%s)" % c["set"].upper() if c["set"] else ""
        number = " %s" % c["number"] if c["set"] and c["number"] else ""
        mark = {"foil": " *F*", "etched": " *E*"}.get(c["finish"], "")
        lines.append("%d %s%s%s%s" % (c["quantity"], c["name"], where, number, mark))
    return "\n".join(lines) + ("\n" if lines else "")


# kind -> (label, extension, writer)
KINDS = {
    "manabox": ("ManaBox", "csv", manabox),
    "moxfield": ("Moxfield", "csv", moxfield),
    "archidekt": ("Archidekt", "csv", archidekt),
    "deckbox": ("Deckbox", "csv", deckbox),
    "list": ("Card list", "txt", card_list),
}  # type: Dict[str, tuple]


def export_collection(kind: str, rows: List[dict], index: Dict[str, dict],
                      flags: Optional[Dict[str, List[str]]] = None) -> Export:
    """Write the rows of a collection in one app's format.

    flags (see backend.core.card_flags) mark the stacks for trade: Moxfield and
    Deckbox get them as the trade list count.

    Raises:
        KeyError: The kind is not in KINDS.
    """
    label, extension, writer = KINDS[kind]  # type: str, str, Callable[[List[dict]], str]
    cards = sorted((_printing(row, index, flags or {}) for row in rows if row.get("name") or
                    row.get("scryfall_id")),
                   key=lambda c: (c["binder"].lower(), c["name"].lower(), c["set"], c["number"]))
    media = "text/csv; charset=utf-8" if extension == "csv" else "text/plain; charset=utf-8"
    return Export(kind, label, extension, media, writer(cards))

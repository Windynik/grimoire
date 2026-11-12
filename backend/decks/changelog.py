"""The changelog of a deck: what changed, and when.

The record key "changelog" holds the entries, oldest first. An entry is

    {"at": ISO time, "until": ISO time, "kind": str, "note": str,
     "cards": [{"section", "name", "key", "delta"}],
     "fields": [{"field", "from", "to"}]}

kind is "edit" for an editor save, else an event: "created", "imported",
"forged", "copied", "built" or "unbuilt". The editor saves after each short
pause, so the edits of one sitting merge into one entry: an edit within
MERGE_SECONDS of the last edit entry joins it, and the net change stays
(add a card, then remove it, and nothing is left). Pure functions. Makes no
network calls.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from backend.decks.records import entry_key

MERGE_SECONDS = 600
MAX_ENTRIES = 200
SECTION_ORDER = ("commander", "main", "sideboard", "maybeboard")
# The fields of a deck that the changelog follows, besides the cards.
FIELDS = ("name", "format")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _counts(record: dict) -> Dict[Tuple[str, str], Tuple[str, int]]:
    """{(section, entry key): (name, copies)} of a deck, with the commander as a section."""
    counts = {}  # type: Dict[Tuple[str, str], Tuple[str, int]]
    commander = record.get("commander")
    if isinstance(commander, dict) and commander.get("name"):
        counts[("commander", entry_key(commander))] = (commander["name"], 1)
    for section, lines in (record.get("sections") or {}).items():
        for line in lines or []:
            if not isinstance(line, dict) or not line.get("name"):
                continue
            key = (section, entry_key(line))
            name, count = counts.get(key, (line["name"], 0))
            counts[key] = (name, count + int(line.get("count") or 0))
    return counts


def _order(item: dict) -> tuple:
    section = item["section"]
    rank = SECTION_ORDER.index(section) if section in SECTION_ORDER else len(SECTION_ORDER)
    return (rank, -1 if item["delta"] > 0 else 1, item["name"].lower())


def diff(old: dict, new: dict) -> dict:
    """The change from one deck record to the next: {"cards", "fields"}."""
    before, after = _counts(old), _counts(new)
    cards = []
    for key in set(before) | set(after):
        delta = after.get(key, ("", 0))[1] - before.get(key, ("", 0))[1]
        if delta:
            name = (after.get(key) or before.get(key))[0]
            cards.append({"section": key[0], "name": name, "key": key[1], "delta": delta})
    fields = [{"field": f, "from": old.get(f), "to": new.get(f)}
              for f in FIELDS if old.get(f) != new.get(f)]
    return {"cards": sorted(cards, key=_order), "fields": fields}


def _seconds_between(earlier: str, later: str) -> float:
    try:
        return (datetime.fromisoformat(later) - datetime.fromisoformat(earlier)).total_seconds()
    except (TypeError, ValueError):
        return float("inf")


def _merge(entry: dict, change: dict) -> None:
    """Add a change to an edit entry, and keep only the net change."""
    cards = {(c["section"], c["key"]): dict(c) for c in entry.get("cards") or []}
    for card in change["cards"]:
        slot = (card["section"], card["key"])
        if slot in cards:
            cards[slot]["delta"] += card["delta"]
        else:
            cards[slot] = dict(card)
    entry["cards"] = sorted((c for c in cards.values() if c["delta"]), key=_order)
    fields = {f["field"]: dict(f) for f in entry.get("fields") or []}
    for field in change["fields"]:
        if field["field"] in fields:
            fields[field["field"]]["to"] = field["to"]
        else:
            fields[field["field"]] = dict(field)
    entry["fields"] = [f for f in fields.values() if f["from"] != f["to"]]


def _trim(log: List[dict]) -> None:
    if len(log) > MAX_ENTRIES:
        del log[:len(log) - MAX_ENTRIES]


def record_edit(record: dict, old: dict, at: Optional[str] = None) -> None:
    """Add the change from old to record to the record's changelog.

    An edit within MERGE_SECONDS of the last edit entry merges into it. An
    entry whose net change is empty drops out.
    """
    change = diff(old, record)
    if not change["cards"] and not change["fields"]:
        return
    at = at or now_iso()
    log = list(old.get("changelog") or [])
    last = log[-1] if log else None
    if (last is not None and last.get("kind") == "edit"
            and _seconds_between(last.get("until") or last.get("at"), at) <= MERGE_SECONDS):
        last = dict(last)
        _merge(last, change)
        last["until"] = at
        if last["cards"] or last["fields"]:
            log[-1] = last
        else:
            log.pop()
    else:
        log.append({"at": at, "until": at, "kind": "edit", "note": "",
                    "cards": change["cards"], "fields": change["fields"]})
    _trim(log)
    record["changelog"] = log


def record_event(record: dict, kind: str, note: str = "", at: Optional[str] = None,
                 with_cards: bool = False) -> None:
    """Add an event entry ("created", "forged", "copied", ...) to the record's changelog.

    with_cards lists every card of the deck as added (for a new deck that
    already holds cards, such as an imported list or a forged deck).
    """
    at = at or now_iso()
    cards = diff({}, record)["cards"] if with_cards else []
    log = list(record.get("changelog") or [])
    log.append({"at": at, "until": at, "kind": kind, "note": note, "cards": cards,
                "fields": []})
    _trim(log)
    record["changelog"] = log


def changes_newest_first(record: dict) -> List[dict]:
    return list(reversed(record.get("changelog") or []))

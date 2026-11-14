"""Deck text export (plain, with printings, Arena, MTGO, CSV) and decklist import.

Pure functions on deck records and the card index. Makes no network calls.
"""

import csv
import io
import re
from typing import Dict, List, Optional, Tuple

from backend.decks.records import entry_key

ParsedLine = Tuple[str, int, str, Optional[str], Optional[str]]

_HEADERS = {
    "commander": "commander", "deck": "main", "main": "main", "mainboard": "main",
    "sideboard": "sideboard", "maybeboard": "maybeboard", "considering": "maybeboard",
    # Arena lists the companion under "Companion" and again in the sideboard.
    "companion": "companion",
}
# A header line, with an optional card count: "Sideboard", "Deck (60)", "Sideboard: 15".
_HEADER_LINE = re.compile(r"^(%s)\s*(?:\(\d+\)|:\s*\d*)?\s*$" % "|".join(_HEADERS), re.IGNORECASE)
# A card line with its section in front: "Commander: Atraxa", "SB: 2 Duress".
_INLINE = re.compile(r"^(commander|sideboard|sb|companion|maybeboard)\s*:\s*(.+)$", re.IGNORECASE)
# Archidekt adds category tags after the set: "1x Sol Ring (cmr) 472 [Ramp]".
_TAGS = re.compile(r"(\([A-Za-z0-9]{2,6}\)\s*\S*)\s*\[[^\]]*\]\s*$")
_BASICS = ("Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes")
BASIC_NAMES = {n.lower(): n for n in _BASICS}
BASIC_NAMES.update({("snow-covered " + n).lower(): "Snow-Covered " + n
                    for n in _BASICS if n != "Wastes"})
MAX_COUNT = 250  # the deck editor accepts 1..250 copies per entry
CSV_HEADER = ["Section", "Count", "Name", "Set", "Collector Number", "Mana Cost", "Type Line",
              "Scryfall ID"]

_COUNT = re.compile(r"^(\d{1,3})\s*[xX]?\s+(.+)$")
_FOIL = re.compile(r"\s*\*[A-Za-z]\*\s*$")
_PAREN_SET = re.compile(r"\s*\(([A-Za-z0-9]{2,6})\)\s*(\S+)?\s*$")
_BRACKET_SET = re.compile(r"\s*\[([A-Za-z0-9]{2,6})\]\s*$")


def _lines(entries: List[dict]) -> List[str]:
    return ["%d %s" % (c["count"], c["name"]) for c in entries]


def export_text(record: dict) -> str:
    """Return a plain-text decklist for a deck record.

    Args:
        record: Deck record

    Returns:
        Sections "Commander" (when present), "Deck", "Sideboard" and "Maybeboard"
        (each when not empty), split by a blank line. Each card line is
        "{count} {name}".
    """
    sections = []  # type: List[str]
    commander = record.get("commander")
    if commander:
        sections.append("Commander\n1 " + commander["name"])
    data = record.get("sections", {})
    sections.append("\n".join(["Deck"] + _lines(data.get("main", []))))
    for key, title in (("sideboard", "Sideboard"), ("maybeboard", "Maybeboard")):
        if data.get(key):
            sections.append("\n".join([title] + _lines(data[key])))
    return "\n\n".join(sections)


def _arena_name(name: str, info: dict) -> str:
    """Arena names a double-faced card by its front face; split cards keep the full name."""
    if " // " in name and info.get("layout") != "split":
        return name.split(" // ")[0]
    return name


def _arena_line(entry: dict, index: Dict[str, dict]) -> str:
    info = index.get(entry.get("scryfall_id") or "") or {}
    name = _arena_name(entry["name"], info)
    code, number = info.get("set"), info.get("collector_number")
    if code and number:
        return "%d %s (%s) %s" % (entry["count"], name, code.upper(), number)
    return "%d %s" % (entry["count"], name)


def export_arena(record: dict, index: Dict[str, dict]) -> str:
    """Return a decklist for MTG Arena import.

    Args:
        record: Deck record
        index: Card index keyed by Scryfall id

    Returns:
        Sections "Commander", "Deck" and "Sideboard" (when not empty). A line is
        "{count} {name} ({SET}) {number}", or "{count} {name}" when the set or
        number is unknown.
    """
    sections = []  # type: List[str]
    commander = record.get("commander")
    if commander:
        line = _arena_line(dict(commander, count=1), index)
        sections.append("Commander\n" + line)
    data = record.get("sections", {})
    sections.append("\n".join(["Deck"] + [_arena_line(e, index) for e in data.get("main", [])]))
    if data.get("sideboard"):
        sections.append("\n".join(["Sideboard"] + [_arena_line(e, index)
                                                     for e in data["sideboard"]]))
    return "\n\n".join(sections)


def _printing_line(entry: dict, index: Dict[str, dict]) -> str:
    """"{count} {name} ({SET}) {number}" with the full card name, else "{count} {name}"."""
    info = index.get(entry.get("scryfall_id") or "") or {}
    code, number = info.get("set"), info.get("collector_number")
    if code and number:
        return "%d %s (%s) %s" % (entry["count"], entry["name"], code.upper(), number)
    return "%d %s" % (entry["count"], entry["name"])


def export_printings(record: dict, index: Dict[str, dict]) -> str:
    """Return the plain-text decklist with the printing of each card.

    The same sections as export_text, and each line names its set and
    collector number, as Moxfield, Archidekt and ManaBox read them.
    """
    sections = []  # type: List[str]
    commander = record.get("commander")
    if commander:
        sections.append("Commander\n" + _printing_line(dict(commander, count=1), index))
    data = record.get("sections", {})
    sections.append("\n".join(["Deck"] + [_printing_line(e, index) for e in data.get("main", [])]))
    for key, title in (("sideboard", "Sideboard"), ("maybeboard", "Maybeboard")):
        if data.get(key):
            sections.append("\n".join([title] + [_printing_line(e, index) for e in data[key]]))
    return "\n\n".join(sections)


def _mtgo_name(name: str) -> str:
    """MTGO names a split card "Fire/Ice" and a double-faced card by its front face."""
    if " // " not in name:
        return name
    return name.split(" // ")[0]


def export_mtgo(record: dict, index: Dict[str, dict]) -> str:
    """Return a decklist that Magic Online imports (.txt).

    The main deck, a blank line, then the sideboard. A commander goes in the
    sideboard, as MTGO expects. The maybeboard stays out.
    """
    def line(entry: dict) -> str:
        info = index.get(entry.get("scryfall_id") or "") or {}
        name = entry["name"]
        if " // " in name and info.get("layout") == "split":
            name = name.replace(" // ", "/")
        else:
            name = _mtgo_name(name)
        return "%d %s" % (entry["count"], name)

    data = record.get("sections", {})
    main = [line(e) for e in data.get("main", [])]
    side = [line(e) for e in data.get("sideboard", [])]
    commander = record.get("commander")
    if commander:
        side.insert(0, line(dict(commander, count=1)))
    text = "\n".join(main)
    if side:
        text += "\n\n" + "\n".join(side)
    return text + "\n"


def export_csv(record: dict, index: Dict[str, dict]) -> str:
    """Return a CSV of every card in a deck record.

    Args:
        record: Deck record
        index: Card index keyed by Scryfall id

    Returns:
        CSV text with the header in CSV_HEADER. The commander row comes first.
    """
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_HEADER)

    def row(section: str, entry: dict) -> None:
        info = index.get(entry.get("scryfall_id") or "") or {}
        type_line = info.get("type_line") or ("Basic Land — " + entry["name"]
                                              if entry.get("basic") else "")
        writer.writerow([section, entry.get("count", 1), entry["name"],
                         (info.get("set") or "").upper(), info.get("collector_number", ""),
                         info.get("mana_cost", ""), type_line, entry.get("scryfall_id") or ""])

    commander = record.get("commander")
    if commander:
        row("Commander", commander)
    data = record.get("sections", {})
    for key, title in (("main", "Main"), ("sideboard", "Sideboard"),
                       ("maybeboard", "Maybeboard")):
        for entry in data.get(key, []):
            row(title, entry)
    return out.getvalue()


def _header(line: str) -> Optional[str]:
    match = _HEADER_LINE.match(line.strip())
    return _HEADERS[match.group(1).lower()] if match else None


def parse_decklist(text: str) -> List[ParsedLine]:
    """Parse a pasted decklist.

    Args:
        text: Decklist text (plain, Arena, or MTGO style)

    Returns:
        (section, count, name, set code, collector number) per card line. Sections
        come from header lines. In a text with no header line, a blank line after
        main lines starts the sideboard (plain Arena exports). Set code is upper case.
        A count outside 1..250 makes the whole line a name that matches no card.
    """
    lines = text.splitlines()
    has_headers = any(_header(line) for line in lines)
    section, seen_main = "main", False
    about = False  # inside Arena's "About" block, which names the deck
    parsed = []  # type: List[ParsedLine]
    for raw in lines:
        line = raw.strip()
        if not line:
            about = False
            if not has_headers and section == "main" and seen_main:
                section = "sideboard"
            continue
        if line.startswith("//") or line.startswith("#"):
            continue
        if line.lower() == "about":
            about = True
            continue
        if about:
            continue
        header = _header(line)
        if header:
            section = header
            continue
        line_section = section
        inline = _INLINE.match(line)
        if inline:
            word = inline.group(1).lower()
            line_section = "sideboard" if word == "sb" else _HEADERS[word]
            line = inline.group(2).strip()
        line = _TAGS.sub(r"\1", line)
        line = _FOIL.sub("", line)
        count = 1
        match = _COUNT.match(line)
        if match and 1 <= int(match.group(1)) <= MAX_COUNT:
            count, line = int(match.group(1)), match.group(2)
        # Any other count (0, over 250, over 3 digits) stays in the name, so the line is unknown
        code, number = None, None
        match = _PAREN_SET.search(line)
        if match:
            code, number = match.group(1).upper(), match.group(2)
        else:
            match = _BRACKET_SET.search(line)
            if match:
                code = match.group(1).upper()
        if match:
            line = line[:match.start()]
        name = line.strip()
        if not name:
            continue
        if line_section == "main":
            seen_main = True
        parsed.append((line_section, count, name, code, number))
    return _place_companions(parsed)


def _place_companions(parsed: List[ParsedLine]) -> List[ParsedLine]:
    """Put each companion in the sideboard once: drop it when the sideboard lists it too."""
    listed = {name.lower() for section, _, name, _, _ in parsed if section == "sideboard"}
    out = []  # type: List[ParsedLine]
    for line in parsed:
        section, count, name, code, number = line
        if section == "companion":
            if name.lower() in listed:
                continue
            line = ("sideboard", count, name, code, number)
        out.append(line)
    return out


def _oracle_key(info: dict) -> str:
    return info.get("oracle_id") or info["id"]


def _name_map(index: Dict[str, dict]) -> Dict[str, List[dict]]:
    """Map lower-case full and front-face names to index records, in index order.

    A front-face name ("Delver of Secrets") finds a two-faced card only when no
    card has that full name: a reversible printing ("Tasha, the Witch Queen //
    Tasha, the Witch Queen") must not hide the normal card.
    """
    names = {}  # type: Dict[str, List[dict]]
    fronts = {}  # type: Dict[str, List[dict]]
    for info in index.values():
        name = (info.get("name") or "").lower()
        if not name:
            continue
        names.setdefault(name, []).append(info)
        if " // " in name:
            fronts.setdefault(name.split(" // ")[0], []).append(info)
    for front, found in fronts.items():
        names.setdefault(front, found)
    return names


def _pick(options: List[dict], code: Optional[str], number: Optional[str],
          owned: Dict[str, int]) -> dict:
    """Pick one printing: exact set and number, else an owned one, else the last seen."""
    if code:
        exact = [o for o in options if (o.get("set") or "").upper() == code
                 and (not number or o.get("collector_number") == number)]
        if exact:
            return exact[-1]
    for option in reversed(options):
        if owned.get(_oracle_key(option), 0) > 0:
            return option
    return options[-1]


def resolve(lines: List[ParsedLine], index: Dict[str, dict],
            owned: Dict[str, int]) -> Tuple[dict, Optional[dict], List[str]]:
    """Match parsed lines to cards in the index.

    Args:
        lines: Output of parse_decklist
        index: Card index keyed by Scryfall id
        owned: Owned copies per oracle id (see backend.decks.analysis.owned_counts)

    Returns:
        (sections, commander, unknown_names). sections has the keys main, sideboard
        and maybeboard with entries. commander is the first commander line as
        {"scryfall_id", "name"}, or None; later commander lines go to main. A
        basic land becomes an entry with no id. The same card twice in a section
        merges. unknown_names lists each name with no match once, in order.
    """
    names = _name_map(index)
    sections = {"main": [], "sideboard": [], "maybeboard": []}  # type: Dict[str, List[dict]]
    commander = None  # type: Optional[dict]
    unknown = []  # type: List[str]
    for section, count, name, code, number in lines:
        basic = BASIC_NAMES.get(name.lower())
        if basic:
            entry = {"scryfall_id": None, "name": basic, "count": count, "basic": True,
                     "role": "", "reason": ""}
        else:
            options = names.get(name.lower())
            if not options:
                if name not in unknown:
                    unknown.append(name)
                continue
            info = _pick(options, code, number, owned)
            entry = {"scryfall_id": info["id"], "name": info["name"], "count": count,
                     "basic": False, "role": "", "reason": ""}
            if section == "commander" and commander is None:
                commander = {"scryfall_id": info["id"], "name": info["name"]}
                continue
        target = sections["main" if section == "commander" else section]
        for existing in target:
            if entry_key(existing) == entry_key(entry):
                existing["count"] = min(MAX_COUNT, existing["count"] + count)
                break
        else:
            target.append(entry)
    return sections, commander, unknown

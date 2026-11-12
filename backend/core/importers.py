"""Read collection exports from many apps and find each card in the card data.

The rest of the import keys every row on its Scryfall ID, and only ManaBox
writes one. This module reads a CSV export of another app, or a plain card
list such as "4 Lightning Bolt", and returns rows in the ManaBox column shape.
For each row without a Scryfall ID, it finds the card by set and collector
number, or by name.

A row keeps the columns of the source app, and the module adds the ManaBox
columns. On a matched row, the card data sets the ManaBox columns, so a source
column with a ManaBox name (such as "Rarity") gets the app's spelling.
"""

import csv
import re
import unicodedata
from dataclasses import dataclass
from io import StringIO
from typing import Dict, Iterable, List, Optional, Tuple

from backend.core.bulk_data import NON_GAME_LAYOUTS

# The column names that the rest of the app reads (the ManaBox names).
NAME = "Name"
QUANTITY = "Quantity"
SET_CODE = "Set code"
SET_NAME = "Set name"
NUMBER = "Collector number"
FOIL = "Foil"
RARITY = "Rarity"
SCRYFALL_ID = "Scryfall ID"
CANONICAL = (NAME, SET_CODE, SET_NAME, NUMBER, FOIL, RARITY, QUANTITY, SCRYFALL_ID)
# Where the card is kept: ManaBox's binder, Dragon Shield's folder, Sorted's
# list. Only an export that has such a column gets it.
BINDER = "Binder Name"

# Header spellings of each field, after `_header_key` (lower case, letters and
# digits only), in order of preference. "set" and "edition" hold a set code in
# some apps and a set name in others, so a row tries each set column in turn.
# TCGplayer adds a variant to "Name", such as "(Showcase)", so its
# "Simple Name" comes first.
_ALIASES = {
    "name": ("simplename", "name", "cardname", "card", "englishname"),
    "quantity": ("quantity", "count", "qty", "amount", "copies", "totalquantity"),
    "set_code": ("setcode", "editioncode", "expansioncode", "setid", "set", "edition"),
    "set_name": ("setname", "editionname", "expansionname", "expansion"),
    "number": ("collectornumber", "collectorsnumber", "cardnumber", "number",
               "collectorno", "collector", "cn"),
    "foil": ("foil", "finish", "printing", "isfoil", "foiled", "premium"),
    "scryfall_id": ("scryfallid", "scryfalluuid", "scryfallcardid", "id"),
    "binder": ("bindername", "foldername", "listname", "binder", "folder", "location"),
}
# The set columns that a row tries, in order, when it looks for its set.
_SET_FIELDS = ("set_code", "set_name", "set_other")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

# Header signatures that name the source app. The first match wins.
_SIGNATURES = (
    ("manabox", "ManaBox", ("manaboxid",)),
    # A ManaBox file without the ManaBox ID, or the enhanced CSV of this app.
    ("manabox", "ManaBox", ("name", "setcode", "collectornumber", "foil", "quantity",
                            "scryfallid")),
    ("dragon_shield", "Dragon Shield", ("foldername", "cardname")),
    ("tcgplayer", "TCGplayer", ("productid",)),
    ("tcgplayer", "TCGplayer", ("simplename",)),
    ("moxfield", "Moxfield", ("tradelistcount", "lastmodified")),
    ("moxfield", "Moxfield", ("tradelistcount", "collectornumber", "alter")),
    ("deckbox", "Deckbox", ("tradelistcount",)),
    ("topdecked", "TopDecked", ("acquireddate", "finish")),
    ("archidekt", "Archidekt", ("editioncode", "editionname")),
    ("archidekt", "Archidekt", ("finish", "quantity", "dateadded")),
    ("mtggoldfish", "MTGGoldfish", ("setid", "variation")),
    ("mtgo", "Magic Online", ("premium", "sideboarded")),
    ("sorted", "Sorted", ("listtype", "listname")),
)

# Section headings inside a deck list, such as "Sideboard", "Commander (1)"
# or "Sideboard: 15".
_SECTION = re.compile(
    r"^(deck|main ?deck|mainboard|sideboard|commander|companion|maybeboard|"
    r"considering|tokens?|about)\s*(\(\d+\)|:\s*\d*)?$",
    re.IGNORECASE)
# A sideboard prefix of MTGO and old list formats, such as "SB: 2 Duress".
_SB_PREFIX = re.compile(r"^SB:\s*", re.IGNORECASE)
# "4 Lightning Bolt", "4x Lightning Bolt", "1 Sol Ring (CMR) 472 *F*",
# "1 Sol Ring [CMR]" and "Sol Ring" (one copy). A quantity has at most three
# digits, so "1996 World Champion" stays a name.
_LINE = re.compile(
    r"^(?:(?P<qty>\d{1,3})[xX]?\s+)?"
    r"(?P<name>.+?)"
    r"(?:\s+[\(\[](?P<set>[A-Za-z0-9]{2,6})[\)\]](?:\s+(?P<num>[A-Za-z0-9★†\-]+))?)?"
    r"(?P<marks>(?:\s+(?:\*[A-Za-z]+\*|\([FE]\)))*)\s*$")
_FOIL_MARKS = {"*F*": "foil", "*FOIL*": "foil", "(F)": "foil",
               "*E*": "etched", "*ETCHED*": "etched", "(E)": "etched"}
# A variant note at the end of a name, such as "(Showcase)" or "(Borderless)".
_VARIANT = re.compile(r"\s*\([^()]*\)\s*$")

NO_ROWS = ("Grimoire could not read this file. Use a CSV export with a card name "
           "column, or a list with one card on each line, such as \"4 Lightning Bolt\".")
NO_NAME_COLUMN = ("This CSV has no card name column. Grimoire looks for a column such as "
                  "\"Name\" or \"Card Name\".")
NO_DATA_ROWS = "The file has a header but no card rows."
NOT_TEXT = "This file is not text. Export a CSV file or a card list, not a spreadsheet."
OLD_CARD_DATA = ("Your card data has no collector numbers, so Grimoire matched each card "
                 "by name and set. Update the card data on Home to get the exact printings.")


@dataclass
class ParsedImport:
    """The rows of one import in the ManaBox column shape."""
    source: str  # a key such as "moxfield", "csv" or "text"
    label: str  # the source as people read it, such as "Moxfield"
    headers: List[str]
    rows: List[dict]
    notice: Optional[str] = None  # a note for the summary, such as OLD_CARD_DATA


class ImportFormatError(ValueError):
    """The text is not a collection that the app can read."""


def decode_upload(content: bytes) -> str:
    """Decode the bytes of an uploaded file.

    Most apps write UTF-8. Some write UTF-16, with or without a byte order
    mark, or the Windows code page, so those come next. Raises
    ImportFormatError for a binary file, such as a spreadsheet.
    """
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = content.decode("utf-16", errors="replace")
    elif len(content) >= 4 and content[1:20:2].count(0) >= 8 and 0 not in content[0:20:2]:
        # Text with a zero after each byte is UTF-16 without a byte order mark.
        text = content.decode("utf-16-le", errors="replace")
    elif len(content) >= 4 and content[0:20:2].count(0) >= 8 and 0 not in content[1:20:2]:
        text = content.decode("utf-16-be", errors="replace")
    else:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("cp1252", errors="replace")
    if "\x00" in text:
        raise ImportFormatError(NOT_TEXT)
    return text


def name_key(name: str) -> str:
    """A key that matches a card name in any case, accent or face spelling."""
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s*/{1,2}\s*", " // ", text.casefold())
    return re.sub(r"\s+", " ", text).strip()


def _header_key(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (header or "").casefold())


def _is_game_card(card: dict) -> bool:
    """False for a token, an emblem, an art card and the like."""
    if card.get("layout") in NON_GAME_LAYOUTS:
        return False
    return "Token" not in (card.get("type_line") or "").split("—")[0]


# The gold-bordered World Championship decks and the Pro Tour Collector Set
# are legal in the card data, but they are not tournament cards.
_GOLD_BORDER_SETS = re.compile(r"^(wc\d\d|ptc)$")


def _printing_tier(card: dict) -> int:
    """0 for a normal printing, 1 for a printing that no format allows or a
    gold-bordered one, and 2 for a token and the like."""
    if not _is_game_card(card):
        return 2
    if not _is_legal_somewhere(card) or _GOLD_BORDER_SETS.match(card.get("set") or ""):
        return 1
    return 0


def _is_legal_somewhere(card: dict) -> bool:
    """False for a printing that no format allows, such as an Astral card."""
    legalities = card.get("legalities")
    if not legalities:
        return True
    return any(v in ("legal", "restricted") for v in legalities.values())


class CardIndex:
    """Look up cards of the card data by set and number, or by name."""

    def __init__(self, bulk_data: Dict[str, dict]):
        self.bulk_data = bulk_data
        self.by_number: Dict[Tuple[str, str], str] = {}
        self.by_name: Dict[str, List[str]] = {}
        self.by_face: Dict[str, List[str]] = {}
        self.set_codes: set = set()
        self.set_by_name: Dict[str, str] = {}
        for card_id, card in bulk_data.items():
            code = (card.get("set") or "").lower()
            number = (card.get("collector_number") or "").lower()
            if code:
                self.set_codes.add(code)
                if number:
                    self.by_number.setdefault((code, number), card_id)
                if card.get("set_name"):
                    self.set_by_name.setdefault(name_key(card["set_name"]), code)
            name = card.get("name") or ""
            if not name:
                continue
            self.by_name.setdefault(name_key(name), []).append(card_id)
            if "//" in name:
                for face in name.split("//"):
                    self.by_face.setdefault(name_key(face), []).append(card_id)

    @property
    def has_numbers(self) -> bool:
        """False for card data from an older version, which has no collector numbers."""
        return bool(self.by_number)

    def set_code_for(self, value: str) -> Optional[str]:
        """The set code of a set code or a set name, or None."""
        text = (value or "").strip()
        if not text:
            return None
        if text.lower() in self.set_codes:
            return text.lower()
        return self.set_by_name.get(name_key(text))

    def find(self, name: str = "", set_code: Optional[str] = None,
             number: str = "", foil: bool = False) -> Optional[str]:
        """The Scryfall ID of the best printing, or None.

        The set and the collector number win. A name alone takes the
        cheapest game printing with a price, so that a plain list does not
        overstate the value of a collection. A variant note at the end of a
        name, such as "(Showcase)", is tried without the note too.
        """
        names = [name]
        bare = _VARIANT.sub("", name or "")
        if bare and bare != name:
            names.append(bare)
        number = (number or "").strip().lower()
        if set_code and number:
            card_id = self.by_number.get((set_code, number))
            if card_id and (not name or any(self._same_card(card_id, n) for n in names)):
                return card_id
        for candidate in names:
            key = name_key(candidate)
            ids = (self.by_name.get(key) or self.by_face.get(key) or []) if key else []
            if not ids:
                continue
            if set_code:
                in_set = [i for i in ids if self.bulk_data[i].get("set") == set_code]
                if in_set:
                    ids = in_set
            return self._cheapest(ids, foil)
        return None

    def _same_card(self, card_id: str, name: str) -> bool:
        card_name = self.bulk_data[card_id].get("name") or ""
        key = name_key(name)
        return key == name_key(card_name) or key in (
            name_key(face) for face in card_name.split("//"))

    def _cheapest(self, ids: List[str], foil: bool) -> str:
        """The cheapest printing.

        A normal printing comes first, then an Astral or gold-bordered
        printing, then a token of the same name (see `_printing_tier`). A foil
        row compares foil prices first, and the regular price only for a
        printing without a foil price.
        """
        order = ("usd_foil", "usd") if foil else ("usd", "usd_foil")

        def rank(card_id: str) -> Tuple[int, int, float, str]:
            card = self.bulk_data[card_id]
            game = _printing_tier(card)
            prices = card.get("prices") or {}
            for tier, kind in enumerate(order):
                try:
                    return (game, tier, float(prices.get(kind)), card_id)
                except (TypeError, ValueError):
                    continue
            # A printing with no price (such as a digital one) comes last.
            return (game, len(order), 0.0, card_id)

        return min(ids, key=rank)


def foil_value(value: str) -> str:
    """The ManaBox finish ("normal", "foil" or "etched") of a source value."""
    text = (value or "").strip().casefold()
    if "etch" in text:
        return "etched"
    if text in ("true", "yes", "y", "1", "f", "x") or ("foil" in text and "non" not in text):
        return "foil"
    return "normal"


def _quantity(value) -> int:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group()) if match else 1


def _body(text: str) -> str:
    """The text without leading blank lines and a "sep=," line.

    Dragon Shield (and Excel) can start a CSV with a "sep=," line, quoted or not.
    """
    body = (text or "").lstrip("\r\n \t")
    first, newline, rest = body.partition("\n")
    if first.strip().strip('"').lower().startswith("sep="):
        body = rest.lstrip("\r\n")
    return body


def _field_columns(headers: List[str]) -> Dict[str, str]:
    """Map each field to the header that spells it best."""
    keys = {}
    for header in headers:
        keys.setdefault(_header_key(header), header)
    columns = {}
    for name, aliases in _ALIASES.items():
        for alias in aliases:
            if alias in keys and keys[alias] not in columns.values():
                columns[name] = keys[alias]
                break
    # A "set" or "edition" column that is not the set code can hold a set name.
    for alias in ("edition", "set"):
        if alias in keys and keys[alias] not in columns.values():
            columns["set_other"] = keys[alias]
            break
    return columns


def _identify(headers: List[str]) -> Tuple[str, str]:
    keys = {_header_key(h) for h in headers}
    for source, label, needed in _SIGNATURES:
        if all(k in keys for k in needed):
            return source, label
    return "csv", "a CSV file"


def _read_csv(body: str) -> Optional[Tuple[List[str], List[dict]]]:
    """Read the text as a CSV with a header, or return None for a card list.

    A first line with a delimiter is a header, unless it starts with a digit
    (a list line such as "4 Borrowing 100,000 Arrows"). Raises
    ImportFormatError for a header without a card name column.
    """
    first = body.split("\n", 1)[0]
    delimiter = max((",", ";", "\t"), key=first.count)
    if first.count(delimiter) == 0 or first.lstrip()[:1].isdigit():
        return None
    reader = csv.DictReader(StringIO(body, newline=""), delimiter=delimiter)
    headers = [h for h in (reader.fieldnames or []) if h]
    columns = _field_columns(headers)
    if "name" not in columns and "scryfall_id" not in columns:
        raise ImportFormatError(NO_NAME_COLUMN)
    rows = []
    for row in reader:
        clean = {k: (v if isinstance(v, str) else "") for k, v in row.items() if k}
        if any(v.strip() for v in clean.values()):
            rows.append(clean)
    return headers, rows


def _read_text(body: str) -> List[dict]:
    """Read a plain card list. Each row has the canonical columns.

    A row also keeps "_full": the name with any set note, for a card name
    that ends in parentheses, such as "Hazmat Suit (Used)".
    """
    rows = []
    for raw in body.splitlines():
        line = _SB_PREFIX.sub("", raw.strip())
        if not line or line.startswith(("//", "#")) or _SECTION.match(line):
            continue
        match = _LINE.match(line)
        if not match:
            continue
        marks = (match.group("marks") or "").upper().split()
        finishes = {_FOIL_MARKS[m] for m in marks if m in _FOIL_MARKS}
        foil = "etched" if "etched" in finishes else ("foil" if finishes else "normal")
        name = match.group("name").strip()
        full = name
        if match.group("set"):
            full = line[match.start("name"):match.end("num") if match.group("num")
                        else match.end("set") + 1].strip()
        rows.append({
            NAME: name,
            QUANTITY: str(_quantity(match.group("qty"))),
            SET_CODE: (match.group("set") or "").lower(),
            NUMBER: match.group("num") or "",
            FOIL: foil,
            "_full": full,
        })
    return rows


def _complete(row: dict, card_id: Optional[str], index: CardIndex) -> None:
    """Set the Scryfall ID of a row, and set its ManaBox columns from the card."""
    if not card_id:
        return
    card = index.bulk_data[card_id]
    row[SCRYFALL_ID] = card_id
    # The card data has the last word on the set and the rarity, so the
    # Vault filters show the printing that the import chose.
    row[SET_CODE] = card.get("set", "")
    row[RARITY] = card.get("rarity", "")
    for column, key in ((SET_NAME, "set_name"), (NUMBER, "collector_number")):
        if card.get(key):
            row[column] = card[key]
    if not str(row.get(NAME) or "").strip():
        row[NAME] = card.get("name", "")


def _normalize_csv(headers: List[str], rows: List[dict], index: CardIndex) -> List[dict]:
    columns = _field_columns(headers)

    def value(row: dict, name: str) -> str:
        return (row.get(columns[name]) or "").strip() if name in columns else ""

    out = []
    for source_row in rows:
        row = dict(source_row)
        name = value(row, "name")
        set_values = [value(row, f) for f in _SET_FIELDS]
        set_code = next((c for c in map(index.set_code_for, set_values) if c), None)
        number = value(row, "number")
        foil = foil_value(value(row, "foil"))
        given_id = value(row, "scryfall_id")
        # A bare "ID" column holds a Scryfall ID in some apps and a local
        # number in others, so only a UUID counts there.
        if _header_key(columns.get("scryfall_id", "")) == "id" and not _UUID.match(given_id.lower()):
            given_id = ""

        row[NAME] = name
        row[QUANTITY] = str(_quantity(value(row, "quantity"))) if "quantity" in columns else "1"
        row[FOIL] = foil
        row.setdefault(SET_CODE, set_code or "")
        row.setdefault(SET_NAME, set_values[1])
        row.setdefault(NUMBER, number)
        row.setdefault(RARITY, "")
        row[SCRYFALL_ID] = given_id
        if "binder" in columns:
            row[BINDER] = value(row, "binder")
        if given_id in index.bulk_data:
            _complete(row, given_id, index)
        else:
            # The card data can be older than the export. Then the name finds
            # the card. When it does not, the unknown ID stays on the row, so
            # the summary can name it.
            found = index.find(name, set_code, number, foil != "normal")
            _complete(row, found, index)
        out.append(row)
    return out


def _normalize_text(rows: List[dict], index: CardIndex) -> List[dict]:
    for row in rows:
        full = row.pop("_full")
        set_code = index.set_code_for(row[SET_CODE])
        found = None
        if row[SET_CODE] and set_code is None:
            # "(Used)" is not a set, so it is a part of the name.
            found = index.find(full, None, "", row[FOIL] != "normal")
            if found:
                row[NAME] = full
        if found is None:
            found = index.find(row[NAME], set_code, row[NUMBER], row[FOIL] != "normal")
        row[SET_CODE] = set_code or ""
        row[SCRYFALL_ID] = ""
        row[RARITY] = ""
        row.setdefault(SET_NAME, "")
        if found:
            # A list has no source columns, so the card name is the clean one,
            # such as "Fire // Ice" for "fire/ice".
            row[NAME] = index.bulk_data[found].get("name") or row[NAME]
        _complete(row, found, index)
    return rows


def _with_canonical(headers: Iterable[str]) -> List[str]:
    out = list(headers)
    extra = (BINDER,) if "binder" in _field_columns(out) else ()
    for column in CANONICAL + extra:
        if column not in out:
            out.append(column)
    return out


def binder_of(row: dict) -> str:
    """The binder, folder or list that holds a card row, or "" when the export has none."""
    return str(row.get(BINDER) or "").strip()


def _numbers_notice(index: CardIndex, rows: List[dict]) -> Optional[str]:
    """OLD_CARD_DATA when a row has a collector number that the data cannot use."""
    if index.has_numbers or not index.bulk_data:
        return None
    return OLD_CARD_DATA if any(str(r.get(NUMBER) or "").strip() for r in rows) else None


def read_import(text: str, bulk_data: Dict[str, dict]) -> ParsedImport:
    """Read a collection export or a card list, and find each card.

    Raises ImportFormatError when the text holds no card rows.
    """
    body = _body(text)
    try:
        table = _read_csv(body)
    except ImportFormatError:
        # A list whose first line has a comma, such as "Ach! Hans, Run!",
        # looks like a header. It is a list when its lines name real cards.
        index = CardIndex(bulk_data)
        rows = _normalize_text(_read_text(body), index)
        if not any(r[SCRYFALL_ID] for r in rows):
            raise
        return ParsedImport("text", "a card list", list(CANONICAL), rows,
                            _numbers_notice(index, rows))
    if table is not None:
        headers, rows = table
        if not rows:
            raise ImportFormatError(NO_DATA_ROWS)
        source, label = _identify(headers)
        if source == "manabox":
            # A ManaBox export already has every column. Keep it as it is.
            return ParsedImport(source, label, list(headers), rows)
        index = CardIndex(bulk_data)
        rows = _normalize_csv(headers, rows, index)
        return ParsedImport(source, label, _with_canonical(headers), rows,
                            _numbers_notice(index, rows))
    rows = _read_text(body)
    if not rows:
        raise ImportFormatError(NO_ROWS)
    index = CardIndex(bulk_data)
    rows = _normalize_text(rows, index)
    return ParsedImport("text", "a card list", list(CANONICAL), rows,
                        _numbers_notice(index, rows))

"""Collection data core: prices, buckets, insights, and new cards.

Pure functions. Tasks for search, facets, shelves, and sets build on them.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from backend.forge.playbook import load_playbook

RARITIES = ("common", "uncommon", "rare", "mythic")
COLOR_BUCKETS = ("W", "U", "B", "R", "G", "C", "M")
CURVE_BUCKETS = ("0", "1", "2", "3", "4", "5", "6", "7+")

_NON_FOIL_ORDER = ("usd", "usd_foil", "eur", "tix")
_FOIL_ORDER = ("usd_foil", "usd", "eur", "tix")


def _is_foil(value) -> bool:
    if isinstance(value, bool):
        return value
    return value not in (None, "", "normal")


def _quantity(value) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 1


def _number(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def unit_price(prices: Optional[dict], foil: bool) -> float:
    """First numeric price above zero in the foil or non-foil order, else 0."""
    prices = prices or {}
    for key in (_FOIL_ORDER if foil else _NON_FOIL_ORDER):
        number = _number(prices.get(key))
        if number > 0:
            return number
    return 0


def collection_set_names(original_rows: Optional[list]) -> Dict[str, str]:
    """Map lower-case set code to the "Set name" of an original CSV."""
    names = {}  # type: Dict[str, str]
    for row in original_rows or []:
        code = (row.get("Set code") or "").strip().lower()
        name = (row.get("Set name") or "").strip()
        if code and name and code not in names:
            names[code] = name
    return names


def _identity_from_mana(mana_cost: str) -> List[str]:
    """Colors named inside the {...} symbols of a mana cost, in WUBRG order."""
    symbols = " ".join(re.findall(r"\{([^}]*)\}", (mana_cost or "").upper()))
    return [c for c in "WUBRG" if c in symbols]


def owned_cards(stored: list, index: dict, csv_set_names: Optional[Dict[str, str]] = None) -> List[dict]:
    """One dict per stored row, with the index fields merged in."""
    csv_set_names = csv_set_names or {}
    cards = []
    for row in stored:
        entry = index.get(row.get("scryfall_id"))
        indexed = entry is not None
        entry = entry or {}
        foil = _is_foil(row.get("foil"))
        quantity = _quantity(row.get("quantity"))
        prices = entry.get("prices") if indexed else row.get("prices")
        prices = prices or row.get("prices") or {}
        price = unit_price(prices, foil)
        if not price and not indexed:
            price = _number(row.get("price"))
        set_code = entry.get("set") or row.get("set") or ""
        set_name = (entry.get("set_name")
                    or csv_set_names.get(set_code.lower())
                    or set_code.upper())

        def pick(key, default=""):
            return (entry.get(key) if indexed and entry.get(key) not in (None, "") else row.get(key)) or default

        cards.append({
            "scryfall_id": row.get("scryfall_id"),
            "name": pick("name"),
            "mana_cost": pick("mana_cost"),
            "type_line": pick("type_line"),
            "oracle_text": pick("oracle_text"),
            "rarity": pick("rarity"),
            "set": set_code,
            "set_name": set_name,
            "collector_number": entry.get("collector_number") or "",
            "cmc": entry.get("cmc") or 0,
            "color_identity": (list(entry.get("color_identity") or []) if indexed
                               else _identity_from_mana(pick("mana_cost"))),
            "legalities": dict(entry.get("legalities") or {}),
            "edhrec_rank": entry.get("edhrec_rank"),
            "image_url": pick("image_url"),
            "back_image_url": pick("back_image_url"),
            "prices": prices,
            "quantity": quantity,
            "foil": foil,
            "price": price,
            "value": price * quantity,
        })
    return cards


def color_bucket(card: dict) -> str:
    """Exclusive color bucket from color identity."""
    identity = card.get("color_identity") or []
    if not identity:
        return "C"
    if len(identity) > 1:
        return "M"
    return identity[0] if identity[0] in COLOR_BUCKETS else "C"


def _is_land(card: dict) -> bool:
    return "Land" in (card.get("type_line") or "").split("//")[0]


def insights(cards: list) -> dict:
    """Totals for a list of owned cards, weighted by quantity."""
    rarity = {r: 0 for r in RARITIES}
    colors = {b: 0 for b in COLOR_BUCKETS}
    curve = {b: 0 for b in CURVE_BUCKETS}
    value = 0.0
    total = 0
    foils = 0
    names = set()
    sets = set()
    for card in cards:
        qty = _quantity(card.get("quantity"))
        total += qty
        value += card.get("value", 0) or 0
        names.add(card.get("name"))
        if card.get("set"):
            sets.add(card.get("set"))
        if card.get("rarity") in rarity:
            rarity[card["rarity"]] += qty
        if _is_foil(card.get("foil")):
            foils += qty
        colors[color_bucket(card)] += qty
        if not _is_land(card):
            cmc = int(_number(card.get("cmc")))
            curve["7+" if cmc >= 7 else str(max(cmc, 0))] += qty
    return {
        "value": value,
        "cards": total,
        "unique": len(names),
        "rarity": rarity,
        "foils": foils,
        "colors": colors,
        "curve": curve,
        "sets": len(sets),
    }


def new_since(current: list, previous: Optional[list]) -> Set[Tuple[str, bool]]:
    """(id, foil) pairs missing from, or with a higher quantity than, the previous collection."""
    if previous is None:
        return set()
    before = {}  # type: Dict[Tuple[str, bool], int]
    for row in previous:
        key = (row.get("scryfall_id"), _is_foil(row.get("foil")))
        before[key] = before.get(key, 0) + _quantity(row.get("quantity"))
    now = {}  # type: Dict[Tuple[str, bool], int]
    for row in current:
        key = (row.get("scryfall_id"), _is_foil(row.get("foil")))
        now[key] = now.get(key, 0) + _quantity(row.get("quantity"))
    return {key for key, qty in now.items() if qty > before.get(key, 0)}


# ---- Smart search ----------------------------------------------------------

TYPES = ("Creature", "Instant", "Sorcery", "Artifact", "Enchantment", "Planeswalker", "Battle", "Land")
_FORMAT_KEYS = {key: rules.legality_key for key, rules in load_playbook().formats.items()}
_LEGAL = ("legal", "restricted")
_COLOR_RANK = {b: i for i, b in enumerate(("W", "U", "B", "R", "G", "M", "C"))}
_RARITY_RANK = {"mythic": 0, "rare": 1, "uncommon": 2, "common": 3}
_TOKEN = re.compile(r'(?:[^\s"]+:)?"[^"]*"|\S+')
_PRICE = re.compile(r'^\$(>=|<=|>|<)(\d+(?:\.\d+)?)$')
_RANGE = re.compile(r'^(\d+)(?:(-)(\d*))?$')


@dataclass
class Query:
    name_words: List[str] = field(default_factory=list)
    types: List[str] = field(default_factory=list)
    oracle: List[str] = field(default_factory=list)
    colors: List[str] = field(default_factory=list)  # each entry: letters that must all be present
    mv: List[Tuple[float, float]] = field(default_factory=list)
    rarity: List[str] = field(default_factory=list)
    sets: List[str] = field(default_factory=list)
    formats: List[str] = field(default_factory=list)
    prices: List[Tuple[str, float]] = field(default_factory=list)
    foil: bool = False
    dupes: bool = False
    new: bool = False


@dataclass
class Filters:
    colors: List[str] = field(default_factory=list)
    rarity: List[str] = field(default_factory=list)
    type: List[str] = field(default_factory=list)
    mv: List[str] = field(default_factory=list)
    format: List[str] = field(default_factory=list)
    set: List[str] = field(default_factory=list)
    min_price: Optional[float] = None
    foil: Optional[bool] = None
    dupes: bool = False
    # Old single-value parameters of the deck editor's search
    type_contains: str = ""
    includes_color: str = ""


def _unquote(value: str) -> str:
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] == '"' else value.strip('"')


def parse_query(q: str) -> Query:
    """Split a search string into keyword filters and name words."""
    query = Query()
    for token in _TOKEN.findall(q or ""):
        low = token.lower()
        if low in ("foil", "dupes", "new"):
            setattr(query, low, True)
            continue
        price = _PRICE.match(token)
        if price:
            query.prices.append((price.group(1), float(price.group(2))))
            continue
        key, sep, raw = token.partition(":")
        key = key.lower()
        value = _unquote(raw).strip().lower() if sep else ""
        if sep and value and key in ("t", "o"):
            (query.types if key == "t" else query.oracle).append(value)
        elif sep and value and key == "c" and re.fullmatch(r"[wubrgc]+", value):
            query.colors.append(value)
        elif sep and value and key == "mv" and _RANGE.match(value):
            m = _RANGE.match(value)
            lo = float(m.group(1))
            if not m.group(2):
                hi = lo
            else:
                hi = float(m.group(3)) if m.group(3) else float("inf")
            query.mv.append((lo, hi))
        elif sep and value and key == "r":
            query.rarity.append(value)
        elif sep and value and key == "s":
            query.sets.append(value)
        elif sep and value and key == "f" and value in _FORMAT_KEYS:
            query.formats.append(value)
        else:
            query.name_words.append(_unquote(token).lower() if token.count('"') >= 2 else token.lower())
    return query


def _legal_formats(card: dict) -> Set[str]:
    legalities = card.get("legalities") or {}
    if not legalities:
        return set()
    return {key for key, lk in _FORMAT_KEYS.items()
            if lk is None or legalities.get(lk) in _LEGAL}


def _card_types(card: dict) -> Set[str]:
    line = card.get("type_line") or ""
    return {t for t in TYPES if t in line}


def _mv_value(card: dict) -> str:
    cmc = int(_number(card.get("cmc")))
    return "7+" if cmc >= 7 else str(max(cmc, 0))


def _cmp(op: str, value: float, ref: float) -> bool:
    if op == ">":
        return value > ref
    if op == ">=":
        return value >= ref
    if op == "<":
        return value < ref
    return value <= ref


def _query_passes(card: dict, query: Query, new_keys) -> bool:
    name = (card.get("name") or "").lower()
    for word in query.name_words:
        if word not in name:
            return False
    type_line = (card.get("type_line") or "").lower()
    for value in query.types:
        if value not in type_line:
            return False
    text = (card.get("oracle_text") or "").lower()
    for value in query.oracle:
        if value not in text:
            return False
    if query.colors:
        identity = set(card.get("color_identity") or [])
        for letters in query.colors:
            if letters == "c":
                if identity:
                    return False
            elif not set(letters.upper()) <= identity:
                return False
    if query.mv:
        cmc = _number(card.get("cmc"))
        if not any(lo <= cmc <= hi for lo, hi in query.mv):
            return False
    if query.rarity and (card.get("rarity") or "").lower() not in query.rarity:
        return False
    if query.sets and (card.get("set") or "").lower() not in query.sets:
        return False
    if query.formats:
        legal = _legal_formats(card)
        if not all(f in legal for f in query.formats):
            return False
    price = _number(card.get("price"))
    for op, ref in query.prices:
        if not _cmp(op, price, ref):
            return False
    if query.foil and not _is_foil(card.get("foil")):
        return False
    if query.dupes and _quantity(card.get("quantity")) <= 1:
        return False
    if query.new and (card.get("scryfall_id"), _is_foil(card.get("foil"))) not in new_keys:
        return False
    return True


def _sort_key(sort: str):
    def name(c):
        return (c.get("name") or "").lower()

    def price(c):
        return _number(c.get("price"))

    if sort == "price":
        return lambda c: (-price(c), name(c))
    if sort == "price_asc":
        return lambda c: (price(c) <= 0, price(c), name(c))
    if sort == "name":
        return name
    if sort == "mv":
        return lambda c: (_number(c.get("cmc")), name(c))
    if sort == "color":
        return lambda c: (_COLOR_RANK[color_bucket(c)], name(c))
    if sort == "rarity":
        return lambda c: (_RARITY_RANK.get((c.get("rarity") or "").lower(), 4), -price(c), name(c))
    if sort == "set":
        return lambda c: ((c.get("set") or "").lower(), name(c))
    if sort == "edhrec":
        def edhrec(c):
            rank = c.get("edhrec_rank")
            return (rank is None, rank if rank is not None else 0, name(c))
        return edhrec
    return None


def search(cards: list, query: Query, filters: Filters, sort: str = "", new_keys=None):
    """Filter, sort, and count a list of owned cards.

    Returns (results, facets, value). Each facet counts (by quantity) the
    cards that pass the query and every filter except that facet's own.
    """
    new_keys = new_keys or set()
    f = filters
    rarity_sel = {r.lower() for r in f.rarity}
    set_sel = {s.lower() for s in f.set}
    color_sel, type_sel = set(f.colors), set(f.type)
    mv_sel, format_sel = set(f.mv), set(f.format)
    type_text = f.type_contains.lower()
    facets = {
        "colors": {b: 0 for b in COLOR_BUCKETS},
        "rarity": {r: 0 for r in RARITIES},
        "type": {t: 0 for t in TYPES},
        "mv": {b: 0 for b in CURVE_BUCKETS},
        "format": {k: 0 for k in _FORMAT_KEYS},
        "set": {},
        "foil": {"foil": 0, "normal": 0},
    }
    results = []
    value = 0.0
    for card in cards:
        if not _query_passes(card, query, new_keys):
            continue
        qty = _quantity(card.get("quantity"))
        foil = _is_foil(card.get("foil"))
        if type_text and type_text not in (card.get("type_line") or "").lower():
            continue
        if f.includes_color:
            identity = card.get("color_identity") or []
            if f.includes_color == "C":
                if identity:
                    continue
            elif f.includes_color not in identity:
                continue
        if f.dupes and qty <= 1:
            continue
        if f.min_price is not None and _number(card.get("price")) < f.min_price:
            continue

        bucket = color_bucket(card)
        rarity = (card.get("rarity") or "").lower()
        code = (card.get("set") or "").lower()
        if code:
            facets["set"].setdefault(code, 0)  # every set shows, even at 0
        types = _card_types(card)
        mv = _mv_value(card)
        legal = _legal_formats(card)

        ok = {
            "colors": not color_sel or bucket in color_sel,
            "rarity": not rarity_sel or rarity in rarity_sel,
            "type": not type_sel or bool(types & type_sel),
            "mv": not mv_sel or mv in mv_sel,
            "format": not format_sel or bool(legal & format_sel),
            "set": not set_sel or code in set_sel,
            "foil": f.foil is None or f.foil == foil,
        }
        failing = [k for k, v in ok.items() if not v]
        if len(failing) > 1:
            continue
        if not failing:
            results.append(card)
            value += card.get("value", 0) or 0
        only = failing[0] if failing else None  # the one facet this card still counts in
        if only in (None, "colors"):
            facets["colors"][bucket] += qty
        if only in (None, "rarity") and rarity in facets["rarity"]:
            facets["rarity"][rarity] += qty
        if only in (None, "type"):
            for t in types:
                facets["type"][t] += qty
        if only in (None, "mv"):
            facets["mv"][mv] += qty
        if only in (None, "format"):
            for k in legal:
                facets["format"][k] += qty
        if only in (None, "set") and code:
            facets["set"][code] = facets["set"].get(code, 0) + qty
        if only in (None, "foil"):
            facets["foil"]["foil" if foil else "normal"] += qty

    # A set value the filter selects always appears, even with a zero count
    for code in set_sel:
        facets["set"].setdefault(code, 0)
    key = _sort_key(sort)
    if key:
        results.sort(key=key)
    return results, facets, value


def archive_matches(info: dict, query: Query) -> bool:
    """Keyword match of one raw index entry (archive search).

    The collection-only keywords (foil, dupes, new) are ignored.
    """
    if query.prices:
        info = dict(info, price=unit_price(info.get("prices"), False))
    flags = (query.foil, query.dupes, query.new)
    query.foil = query.dupes = query.new = False
    try:
        return _query_passes(info, query, ())
    finally:
        query.foil, query.dupes, query.new = flags

"""Collection data core: prices, buckets, insights, and new cards.

Pure functions. Tasks for search, facets, shelves, and sets build on them.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from backend.core.card_flags import flag_key
from backend.core.prices import unit_price  # noqa: F401  (part of this module's API)
from backend.forge.cards import is_game_card
from backend.forge.playbook import load_playbook

RARITIES = ("common", "uncommon", "rare", "mythic")
COLOR_BUCKETS = ("W", "U", "B", "R", "G", "C", "M")
CURVE_BUCKETS = ("0", "1", "2", "3", "4", "5", "6", "7+")



def _is_foil(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("none", "", "normal")


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
        price = unit_price(prices, row.get("foil"))
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
            "oracle_id": entry.get("oracle_id") or "",
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
            "layout": entry.get("layout") or "",
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


# An older collection counts as the previous import of this one when at least
# this share of its cards are still in this one. A trade binder or a friend's
# collection shares few cards, so it is not the previous import.
SAME_COLLECTION_SHARE = 0.5
# The number of older collections to compare.
MAX_PREVIOUS = 10


def previous_import(current: list, olders: List[list]) -> Optional[int]:
    """Return the position in `olders` (newest first) of this collection's previous import.

    That is the older collection with the largest share of its card ids still
    in `current`, at least SAME_COLLECTION_SHARE; a tie takes the newer one.
    None when no older collection shares enough cards.
    """
    ids = {row.get("scryfall_id") for row in current}
    best = None  # type: Optional[Tuple[float, int]]
    for position, rows in enumerate(olders):
        before = {row.get("scryfall_id") for row in rows or []}
        if not before:
            continue
        share = len(before & ids) / len(before)
        if share >= SAME_COLLECTION_SHARE and (best is None or share > best[0]):
            best = (share, position)
    return best[1] if best is not None else None


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


# The words of the flag keyword: "flag:trade", "flag:sell", "flag:keep", "flag:lent".
FLAG_KEYWORDS = {"trade": "trade", "sell": "sell", "keep": "keep", "lent": "lent"}

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
    # "is:free" (a copy no deck uses) and "is:used" (in a saved deck). The route
    # fills `copies` (card key -> (used, owned)) when one of them is on.
    free: bool = False
    used: bool = False
    copies: Optional[Dict[str, Tuple[int, int]]] = None
    # "is:gem": a popular card (see is_gem_card) that no saved deck holds. The
    # route fills `decked` (the card keys of every saved deck) when it is on.
    gem: bool = False
    decked: Optional[Set[str]] = None
    # "flag:trade" and the other card flags (see backend.core.card_flags). The
    # route fills `card_flags` (flag key -> flags) when one of them is on.
    flags: List[str] = field(default_factory=list)
    card_flags: Optional[Dict[str, List[str]]] = None

    @property
    def wants_copies(self) -> bool:
        return self.free or self.used

    @property
    def wants_decks(self) -> bool:
        return self.gem


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


FLAG_WORDS = ("foil", "dupes", "new")


def has_flag_words(q: str) -> bool:
    """True when the search has a bare "foil", "dupes" or "new" (see parse_query)."""
    return any(token.lower() in FLAG_WORDS for token in _TOKEN.findall(q or ""))


def parse_query(q: str, flags_as_text: bool = False) -> Query:
    """Split a search string into keyword filters and name words.

    The bare words "foil", "dupes" and "new" are filters, unless
    flags_as_text is True: then they are name words, as in "New
    Perspectives". "is:foil", "is:dupes" and "is:new" are always filters.
    """
    query = Query()
    for token in _TOKEN.findall(q or ""):
        low = token.lower()
        flag = low[3:] if low.startswith("is:") else (low if not flags_as_text else "")
        if flag == "dupe":
            flag = "dupes"
        if flag in FLAG_WORDS:
            setattr(query, flag, True)
            continue
        if low in ("is:free", "is:used"):
            setattr(query, low[3:], True)
            continue
        if low in ("is:gem", "is:gems"):
            query.gem = True
            continue
        if low.startswith("flag:") and low[5:] in FLAG_KEYWORDS:
            query.flags.append(FLAG_KEYWORDS[low[5:]])
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
    game_card = is_game_card(card)
    return {key for key, lk in _FORMAT_KEYS.items()
            if (game_card if lk is None else legalities.get(lk) in _LEGAL)}


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
    if query.prices and price <= 0:
        # A card with no price is not cheap: no price comparison matches it.
        return False
    for op, ref in query.prices:
        if not _cmp(op, price, ref):
            return False
    if query.foil and not _is_foil(card.get("foil")):
        return False
    if query.dupes and _quantity(card.get("quantity")) <= 1:
        return False
    if query.wants_copies:
        used, owned = (query.copies or {}).get(card_key(card), (0, 0))
        if query.used and used <= 0:
            return False
        if query.free and owned - used <= 0:
            return False
    if query.gem and (not is_gem_card(card) or card_key(card) in (query.decked or set())):
        return False
    if query.flags:
        has = (query.card_flags or {}).get(flag_key(card.get("scryfall_id"), card.get("foil")), [])
        if not all(f in has for f in query.flags):
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
    flags = (query.foil, query.dupes, query.new, query.free, query.used, query.gem, query.flags)
    query.foil = query.dupes = query.new = query.free = query.used = query.gem = False
    query.flags = []
    try:
        return _query_passes(info, query, ())
    finally:
        (query.foil, query.dupes, query.new, query.free, query.used, query.gem,
         query.flags) = flags


# --- shelves and sets ---

SHELF_SIZE = 12
# A card in the top GEM_RANK of EDHREC (the most played Commander cards) is a
# gem when no saved deck holds it.
GEM_RANK = 2000


def card_key(card: dict) -> str:
    """One key for all printings of a card: the oracle id, else the lower-case name."""
    return card.get("oracle_id") or "name:" + (card.get("name") or "").strip().lower()


def is_gem_card(card: dict) -> bool:
    """True for a popular card (EDHREC rank up to GEM_RANK) that is not a basic land."""
    rank = card.get("edhrec_rank")
    if not isinstance(rank, int) or rank <= 0 or rank > GEM_RANK:
        return False
    return "Basic" not in (card.get("type_line") or "").split("—")[0].split()


def _unique_by_price(cards: list) -> list:
    """Cards by unit price, highest first, one per (id, foil)."""
    seen = set()
    result = []
    for card in sorted(cards, key=lambda c: (-c["price"], c["name"])):
        key = (card["scryfall_id"], bool(card["foil"]))
        if key not in seen:
            seen.add(key)
            result.append(card)
    return result


def spotlight(cards: list, day: int) -> Optional[dict]:
    """The rare or mythic card of the day: day index modulo the sorted list."""
    pool = sorted((c for c in cards if c.get("rarity") in ("rare", "mythic")),
                  key=lambda c: (c["name"], c["scryfall_id"] or "", bool(c["foil"])))
    return pool[day % len(pool)] if pool else None


def forgotten_gems(cards: list, decked: Set[str]) -> list:
    """The popular cards that no saved deck holds, most played first, one per card."""
    seen = set()
    gems = []
    for card in sorted((c for c in cards if is_gem_card(c)),
                       key=lambda c: (c["edhrec_rank"], -c.get("price", 0), c["name"])):
        key = card_key(card)
        if key in decked or key in seen:
            continue
        seen.add(key)
        gems.append(card)
    return gems


def shelves(cards: list, new_keys, day: int, decked: Optional[Set[str]] = None) -> dict:
    """Spotlight plus the valuable, foil, new and forgotten-gem shelves of a collection.

    decked holds the card keys of every saved deck; without it there is no
    gems shelf.
    """
    new_keys = new_keys or set()
    flagged = [dict(c, new=(c["scryfall_id"], bool(c["foil"])) in new_keys) for c in cards]
    pick = spotlight(flagged, day)
    return {
        "spotlight": pick,
        "valuable": _unique_by_price(flagged)[:SHELF_SIZE],
        "foils": _unique_by_price([c for c in flagged if c["foil"]])[:SHELF_SIZE],
        "new": _unique_by_price([c for c in flagged if c["new"]])[:SHELF_SIZE],
        "gems": forgotten_gems(flagged, decked)[:SHELF_SIZE] if decked is not None else [],
    }


def set_catalog(index: dict) -> Dict[str, dict]:
    """Per set code: {"name", "cards": {lower name: first printing id}} for game cards."""
    catalog = {}  # type: Dict[str, dict]
    for sid, record in index.items():
        if not is_game_card(record):
            continue
        code = (record.get("set") or "").lower()
        if not code:
            continue
        entry = catalog.setdefault(code, {"name": "", "cards": {}})
        if not entry["name"] and record.get("set_name"):
            entry["name"] = record["set_name"]
        entry["cards"].setdefault((record.get("name") or "").lower(), sid)
    return catalog


def _by_set(cards: list) -> Dict[str, List[dict]]:
    grouped = {}  # type: Dict[str, List[dict]]
    for card in cards:
        code = (card.get("set") or "").lower()
        if code:
            grouped.setdefault(code, []).append(card)
    return grouped


def sets_summary(cards: list, catalog: Dict[str, dict]) -> List[dict]:
    """One row per owned set: completion, value, and the most valuable card."""
    rows = []
    for code, owned in _by_set(cards).items():
        best = max(owned, key=lambda c: c["price"])
        names = (catalog.get(code) or {}).get("cards") or {}
        total = len(names)
        rows.append({
            "code": code,
            "name": (catalog.get(code) or {}).get("name") or owned[0]["set_name"] or code.upper(),
            "owned": len({(c["name"] or "").lower() for c in owned} & set(names)) if total
                     else len({(c["name"] or "").lower() for c in owned}),
            "total": total,
            "value": sum(c["value"] for c in owned),
            "art_id": best["scryfall_id"],
        })
    rows.sort(key=lambda r: (not r["total"], -(r["owned"] / r["total"] if r["total"] else 0),
                             -r["owned"], r["name"]))
    return rows


def _number_key(number: str):
    match = re.match(r"\d+", number or "")
    return (0, int(match.group()), number) if match else (1, 0, number or "")


_DETAIL_KEYS = ("legalities", "oracle_text", "back_image_url", "set_name", "edhrec_rank")


def set_checklist(cards: list, index: dict, catalog: Dict[str, dict], code: str) -> Optional[dict]:
    """Every game card of one set, owned printing first, in collector order."""
    code = code.lower()
    owned = _by_set(cards).get(code, [])
    names = (catalog.get(code) or {}).get("cards")
    if not names and not owned:
        return None
    best = {}  # type: Dict[str, dict]
    for card in owned:
        key = (card["name"] or "").lower()
        if key not in best or card["price"] > best[key]["price"]:
            best[key] = card
    entries = {}
    for key, sid in (names or {}).items():
        card = best.get(key)
        if card:
            entries[key] = {"scryfall_id": card["scryfall_id"], "name": card["name"],
                            "mana_cost": card["mana_cost"], "type_line": card["type_line"],
                            "rarity": card["rarity"], "collector_number": card["collector_number"],
                            "image_url": card["image_url"], "price": card["price"],
                            "quantity": card["quantity"], "foil": card["foil"],
                            **{k: card.get(k) for k in _DETAIL_KEYS}}
        else:
            record = index.get(sid) or {}
            entries[key] = {"scryfall_id": sid, "name": record.get("name", ""),
                            "mana_cost": record.get("mana_cost", ""),
                            "type_line": record.get("type_line", ""),
                            "rarity": record.get("rarity", ""),
                            "collector_number": record.get("collector_number") or "",
                            "image_url": record.get("image_url", ""),
                            "price": unit_price(record.get("prices"), False),
                            "quantity": 0, "foil": False,
                            "legalities": dict(record.get("legalities") or {}),
                            "oracle_text": record.get("oracle_text", ""),
                            "back_image_url": record.get("back_image_url", ""),
                            "set_name": record.get("set_name", ""),
                            "edhrec_rank": record.get("edhrec_rank")}
    for key, card in best.items():  # owned names the index does not list for this set
        if key not in entries:
            entries[key] = {k: card[k] for k in ("scryfall_id", "name", "mana_cost", "type_line", "rarity",
                                                 "collector_number", "image_url", "price", "quantity", "foil",
                                                 *_DETAIL_KEYS)}
    ordered = sorted(entries.values(),
                     key=lambda e: (_number_key(e["collector_number"]), e["name"])
                     if e["collector_number"] else ((1, 0, ""), e["name"]))
    # cards with a number come first in numeric order, the rest by name
    name = (catalog.get(code) or {}).get("name") or (owned[0]["set_name"] if owned else code.upper())
    return {"code": code, "name": name, "total": len(names or {}),
            "owned": len(set(best) & set(names)) if names else len(best), "cards": ordered}

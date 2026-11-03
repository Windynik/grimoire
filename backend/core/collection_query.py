"""Collection data core: prices, buckets, insights, and new cards.

Pure functions. Tasks for search, facets, shelves, and sets build on them.
"""
from typing import Dict, List, Optional, Set, Tuple

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
            "color_identity": list(entry.get("color_identity") or []),
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

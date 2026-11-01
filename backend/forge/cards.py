"""Owned-card hydration for the deck forge.

Turns stored collection rows plus the compact card index into OwnedCard
objects: merged by oracle id, filtered by format legality, and parsed into
types, colors and flags. Makes no network calls.
"""

import math
import re
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from backend.core.bulk_data import NON_GAME_LAYOUTS
from backend.forge.playbook import FormatRules

COLORS = "WUBRG"
ANY_NUMBER_PHRASE = "a deck can have any number of cards named"
_SYMBOL = re.compile(r"\{([^}]*)\}")
_LAND_WORD = re.compile(r"\bLand\b")


@dataclass
class OwnedCard:
    """One owned card (all printings merged) with parsed deckbuilding fields."""

    id: str
    oracle_id: str
    name: str
    mana_cost: str
    oracle_text: str
    type_line: str
    types: FrozenSet[str]
    subtypes: Tuple[str, ...]
    cmc: float
    color_identity: FrozenSet[str]
    keywords: Tuple[str, ...]
    produced_mana: FrozenSet[str]
    edhrec_rank: Optional[int]
    game_changer: bool
    rarity: str
    legality: str
    owned: int
    image_url: str
    back_image_url: str
    price: Optional[float]
    is_land: bool
    is_basic: bool
    mdfc_land_back: bool
    any_number: bool
    roles: Set[str] = field(default_factory=set)
    gives: Set[str] = field(default_factory=set)
    wants: Set[str] = field(default_factory=set)
    quality: float = 0.5

    @property
    def pips(self) -> Dict[str, int]:
        """Colored mana pips in the mana cost. Hybrid symbols count each color."""
        counts = {}  # type: Dict[str, int]
        for symbol in _SYMBOL.findall(self.mana_cost):
            for part in symbol.split("/"):
                if part in COLORS:
                    counts[part] = counts.get(part, 0) + 1
        return counts


def front_types(type_line: str) -> Tuple[FrozenSet[str], Tuple[str, ...]]:
    """Split the front face of a type line into types and subtypes.

    Args:
        type_line: Full type line, possibly with " // " between faces.

    Returns:
        (types, subtypes) for the first face only.
    """
    front = (type_line or "").split(" // ")[0]
    left, _, right = front.partition("—")
    return frozenset(left.split()), tuple(right.split())


def is_game_card(record: dict) -> bool:
    """Return True when a record is a real game card (not a token or similar)."""
    if record.get("layout") in NON_GAME_LAYOUTS:
        return False
    return "Token" not in front_types(record.get("type_line", ""))[0]


def quality_prior(rank: Optional[int]) -> float:
    """Convert an EDHREC rank to a 0-1 quality prior.

    Args:
        rank: EDHREC rank, or None when unknown.

    Returns:
        0.5 for None, else 1.0 for rank 1 falling to 0.0 at rank 40000 and beyond.
    """
    if rank is None:
        return 0.5
    if rank <= 1:
        return 1.0
    return max(0.0, min(1.0, 1 - math.log10(rank) / math.log10(40000)))


def _quantity(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _best_price(prices: dict) -> Optional[float]:
    for key in ("usd", "usd_foil", "eur", "tix"):
        try:
            return float(prices.get(key))
        except (TypeError, ValueError):
            continue
    return None


def _mdfc_land_back(record: dict) -> bool:
    if record.get("layout") != "modal_dfc":
        return False
    faces = (record.get("type_line") or "").split(" // ")
    if len(faces) < 2:
        return False
    return not _LAND_WORD.search(faces[0]) and bool(_LAND_WORD.search(faces[1]))


def _build(record: dict, legality: str, owned: int) -> OwnedCard:
    types, subtypes = front_types(record.get("type_line", ""))
    return OwnedCard(
        id=record["id"],
        oracle_id=record.get("oracle_id") or record["id"],
        name=record.get("name", ""),
        mana_cost=record.get("mana_cost", ""),
        oracle_text=record.get("oracle_text", ""),
        type_line=record.get("type_line", ""),
        types=types,
        subtypes=subtypes,
        cmc=float(record.get("cmc") or 0),
        color_identity=frozenset(record.get("color_identity") or []),
        keywords=tuple(record.get("keywords") or []),
        produced_mana=frozenset(record.get("produced_mana") or []),
        edhrec_rank=record.get("edhrec_rank"),
        game_changer=bool(record.get("game_changer", False)),
        rarity=record.get("rarity", ""),
        legality=legality,
        owned=owned,
        image_url=record.get("image_url", ""),
        back_image_url=record.get("back_image_url", ""),
        price=_best_price(record.get("prices") or {}),
        is_land="Land" in types,
        is_basic="Basic" in types,
        mdfc_land_back=_mdfc_land_back(record),
        any_number=ANY_NUMBER_PHRASE in (record.get("oracle_text") or "").lower(),
    )


def hydrate(collection: List[dict], index: Dict[str, dict], fmt: FormatRules) -> List[OwnedCard]:
    """Build the owned, legal card pool for a format.

    Args:
        collection: Stored rows with scryfall_id and quantity (int or string).
        index: Compact card records keyed by scryfall id.
        fmt: Format rules that give the legality key. A None key (Casual)
            treats every game card as legal.

    Returns:
        One OwnedCard per oracle id, in first-seen order. Missing ids,
        non-game cards and cards that are not legal or restricted are dropped.
    """
    merged = {}  # type: Dict[str, OwnedCard]
    for row in collection:
        record = index.get(row.get("scryfall_id"))
        if record is None or not is_game_card(record):
            continue
        if fmt.legality_key is None:
            legality = "legal"
        else:
            legality = (record.get("legalities") or {}).get(fmt.legality_key, "not_legal")
        if legality not in ("legal", "restricted"):
            continue
        key = record.get("oracle_id") or record["id"]
        qty = _quantity(row.get("quantity"))
        if key in merged:
            merged[key].owned += qty
        else:
            merged[key] = _build(record, legality, qty)
    return list(merged.values())

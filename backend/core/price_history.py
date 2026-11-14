"""Price snapshots of a collection: its value over time, and the price movers.

Grimoire works offline, so a price changes only when the card data updates.
Each card-data download is one snapshot: the first time the Vault reads a
collection with new card data, the collection's value and the unit price of
each card go into its history. Pure functions. Makes no network calls.

A history is {"snapshots": [{"source", "data_date", "at", "value", "cards",
"prices"}]}, oldest first. source is the price provider (see
backend.core.provider_prices); each provider has its own line of snapshots, so
a switch of provider never shows as a price move. A snapshot without a source
is from the default provider. prices maps a card slot (scryfall id and finish)
to its unit price in USD. cards is the copy count of the collection then.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

DEFAULT_SOURCE = "scryfall"
MAX_SNAPSHOTS = 120
MOVERS = 5
# A price change smaller than this (in USD per copy) is noise.
MIN_MOVE = 0.05


def slot(card: dict) -> str:
    """The key of one owned stack: the Scryfall id and the finish."""
    finish = card.get("foil")
    finish = "" if finish in (None, False, "", "normal", "false") else str(finish)
    return "%s|%s" % (card.get("scryfall_id") or "", finish)


def _source(shot: dict) -> str:
    return shot.get("source") or DEFAULT_SOURCE


def _of(history: Optional[dict], source: str) -> List[dict]:
    return [s for s in (history or {}).get("snapshots") or [] if _source(s) == source]


def snapshot(cards: List[dict], data_date: str, at: Optional[str] = None,
             source: str = DEFAULT_SOURCE) -> dict:
    """A snapshot of owned cards (as from owned_cards): value, copies and unit prices."""
    prices = {}  # type: Dict[str, float]
    value = 0.0
    copies = 0
    for card in cards:
        quantity = int(card.get("quantity") or 0)
        price = float(card.get("price") or 0)
        copies += quantity
        value += price * quantity
        if price > 0 and card.get("scryfall_id"):
            prices[slot(card)] = round(price, 2)
    return {"source": source, "data_date": data_date,
            "at": at or datetime.now(timezone.utc).isoformat(),
            "value": round(value, 2), "cards": copies, "prices": prices}


def add_snapshot(history: Optional[dict], cards: List[dict], data_date: Optional[str],
                 at: Optional[str] = None, source: str = DEFAULT_SOURCE) -> Optional[dict]:
    """Return the history with a new snapshot, or None when it needs none.

    It needs one when there are prices (a date) and the newest snapshot of
    the same source has other prices.
    """
    if not data_date:
        return None
    same = _of(history, source)
    if same and same[-1].get("data_date") == data_date:
        return None
    snapshots = list((history or {}).get("snapshots") or [])
    snapshots.append(snapshot(cards, data_date, at, source))
    return {"snapshots": snapshots[-MAX_SNAPSHOTS:]}


def value_history(history: Optional[dict], source: str = DEFAULT_SOURCE) -> List[dict]:
    """[{"date", "value", "cards"}] per snapshot of one source, oldest first. date is the price date."""
    return [{"date": s.get("data_date"), "value": s.get("value", 0), "cards": s.get("cards", 0)}
            for s in _of(history, source)]


def movers(history: Optional[dict], cards: List[dict], limit: int = MOVERS,
           source: str = DEFAULT_SOURCE) -> Optional[dict]:
    """The owned cards whose price moved most between the two newest snapshots.

    The change counts the copies owned now, so a stack of 4 moves 4 times as
    much as one copy. Returns None with fewer than two snapshots, else
    {"since", "until", "up", "down"}; each mover is the owned card plus
    "before", "after", "change" (per copy) and "total" (all copies).
    """
    snapshots = _of(history, source)
    if len(snapshots) < 2:
        return None
    before, after = snapshots[-2].get("prices") or {}, snapshots[-1].get("prices") or {}
    moved = []
    seen = set()
    for card in cards:
        key = slot(card)
        if key in seen or key not in before or key not in after:
            continue
        seen.add(key)
        change = round(after[key] - before[key], 2)
        if abs(change) < MIN_MOVE:
            continue
        quantity = int(card.get("quantity") or 0)
        moved.append(dict(card, before=before[key], after=after[key], change=change,
                          total=round(change * quantity, 2)))
    up = sorted((m for m in moved if m["total"] > 0), key=lambda m: (-m["total"], m["name"]))
    down = sorted((m for m in moved if m["total"] < 0), key=lambda m: (m["total"], m["name"]))
    return {"since": snapshots[-2].get("data_date"), "until": snapshots[-1].get("data_date"),
            "up": up[:limit], "down": down[:limit]}

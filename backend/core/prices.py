"""Card price helpers shared by the API and the deck code.

Every price is in US dollars. Scryfall's EUR and MTGO ticket prices are other
units, so a card with only those has no price here.
"""
from typing import Optional, Union

# The price keys to try for each finish, best first.
PRICE_ORDER = {
    "normal": ("usd", "usd_foil"),
    "foil": ("usd_foil", "usd"),
    "etched": ("usd_etched", "usd_foil", "usd"),
}


def finish_of(value: Union[bool, str, None]) -> str:
    """The finish ("normal", "foil" or "etched") of a stored foil value."""
    if isinstance(value, bool):
        return "foil" if value else "normal"
    text = str(value or "").strip().lower()
    if "etch" in text:
        return "etched"
    return "normal" if text in ("", "none", "normal", "false") else "foil"


def unit_price(prices: Optional[dict], finish: Union[bool, str, None] = "normal") -> float:
    """The US dollar price of one copy in a finish: the first number above 0, else 0."""
    prices = prices or {}
    for key in PRICE_ORDER[finish_of(finish)]:
        try:
            number = float(prices.get(key))
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return 0.0


def best_price(prices: dict):
    """The non-foil US dollar price, or None when the card has none."""
    price = unit_price(prices, "normal")
    return price if price > 0 else None

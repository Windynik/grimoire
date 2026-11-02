"""Card price helpers shared by the API and the deck code."""


def best_price(prices: dict):
    """Best available price: USD, then USD foil, EUR, TIX."""
    prices = prices or {}
    return (
        prices.get("usd")
        or prices.get("usd_foil")
        or prices.get("eur")
        or prices.get("tix")
    )

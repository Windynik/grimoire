"""Card prices from other stores, and the owner's choice of price provider.

Scryfall's card data carries TCGplayer prices only (in US dollars). MTGJSON
publishes the daily prices of more stores, keyed by its own card id (uuid),
with a table that links each uuid to a Scryfall id:

- AllPricesToday.json.gz (about 5 MB): data -> uuid -> "paper" -> store ->
  "retail" or "buylist" -> finish ("normal", "foil", "etched") -> {date: price}.
- csv/cardIdentifiers.csv.gz (about 14 MB): uuid, scryfallId and other ids.

The download keeps only the stores in PROVIDERS, for the Scryfall ids in
them, in one compact file. The chosen provider then replaces the US dollar
prices of the card index; a card the store does not price keeps its
Scryfall (TCGplayer) price. Only US dollar stores are here, because the app
shows every price in dollars.
"""

import csv
import gzip
import io
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

DEFAULT_PROVIDER = "scryfall"
# key -> (label, note, (MTGJSON store, list)); the default has no MTGJSON source.
PROVIDERS = {
    "scryfall": ("TCGplayer", "Market prices from the card data. No extra download.", None),
    "cardkingdom": ("Card Kingdom", "What Card Kingdom sells each card for.",
                    ("cardkingdom", "retail")),
    "cardkingdom_buylist": ("Card Kingdom buylist", "What Card Kingdom pays you for each card.",
                            ("cardkingdom", "buylist")),
    "manapool": ("Mana Pool", "What Mana Pool sells each card for.", ("manapool", "retail")),
}
PRICES_URL = "https://mtgjson.com/api/v5/AllPricesToday.json.gz"
IDS_URL = "https://mtgjson.com/api/v5/csv/cardIdentifiers.csv.gz"
FINISH_KEYS = (("normal", "usd"), ("foil", "usd_foil"), ("etched", "usd_etched"))
PRICES_FILE = "provider_prices.json"
SETTINGS_FILE = "price_settings.json"


class PriceDownloadError(Exception):
    """The store prices could not be downloaded or read. The message is for the owner."""


def read_identifiers(lines: Iterable[str]) -> Dict[str, str]:
    """{MTGJSON uuid: Scryfall id} from the lines of cardIdentifiers.csv."""
    found = {}
    for row in csv.DictReader(lines):
        if row.get("uuid") and row.get("scryfallId"):
            found[row["uuid"]] = row["scryfallId"]
    return found


def _newest(by_date: dict) -> Optional[float]:
    if not isinstance(by_date, dict) or not by_date:
        return None
    try:
        value = float(by_date[max(by_date)])
    except (TypeError, ValueError):
        return None
    return round(value, 2) if value > 0 else None


def read_prices(data: dict, ids: Dict[str, str]) -> Dict[str, Dict[str, Dict[str, float]]]:
    """{Scryfall id: {provider: {finish: price}}} for the providers in PROVIDERS."""
    sources = {key: spec[2] for key, spec in PROVIDERS.items() if spec[2]}
    cards = {}  # type: Dict[str, Dict[str, Dict[str, float]]]
    for card_uuid, entry in (data or {}).items():
        scryfall_id = ids.get(card_uuid)
        paper = (entry or {}).get("paper") if isinstance(entry, dict) else None
        if not scryfall_id or not isinstance(paper, dict):
            continue
        for key, (store, kind) in sources.items():
            listing = paper.get(store) or {}
            if listing.get("currency", "USD") != "USD":
                continue
            by_finish = listing.get(kind) or {}
            prices = {finish: price for finish in ("normal", "foil", "etched")
                      for price in [_newest(by_finish.get(finish))] if price}
            if prices:
                # Two faces of one card share a Scryfall id: the first one counts.
                cards.setdefault(scryfall_id, {}).setdefault(key, prices)
    return cards


def overlay(index: Dict[str, dict], cards: Dict[str, Dict[str, Dict[str, float]]],
            provider: str) -> Tuple[Dict[str, dict], int]:
    """The card index with the provider's US dollar prices, and the count of cards it priced.

    A card (or a finish) that the provider does not price keeps its own price.
    """
    priced = 0
    result = dict(index)
    for scryfall_id, stores in cards.items():
        found = stores.get(provider)
        record = index.get(scryfall_id)
        if not found or record is None:
            continue
        prices = dict(record.get("prices") or {})
        for finish, key in FINISH_KEYS:
            if finish in found:
                prices[key] = "%.2f" % found[finish]
        result[scryfall_id] = dict(record, prices=prices)
        priced += 1
    return result, priced


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".%s.%s.tmp" % (path.name, uuid.uuid4().hex))
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _read_json(path: Path) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


class ProviderPrices:
    """The chosen price provider, the downloaded store prices, and the priced index."""

    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.prices_file = self.cache_dir / PRICES_FILE
        self.settings_file = self.cache_dir / SETTINGS_FILE
        self._data = None  # type: Optional[dict]
        self._loaded = False
        self._priced_key = None  # type: Optional[tuple]
        self._priced = None  # type: Optional[Dict[str, dict]]
        self._covered = 0

    # --- the choice ---

    @property
    def provider(self) -> str:
        saved = (_read_json(self.settings_file) or {}).get("provider")
        return saved if saved in PROVIDERS else DEFAULT_PROVIDER

    def set_provider(self, provider: str) -> None:
        if provider not in PROVIDERS:
            raise KeyError(provider)
        _write_json(self.settings_file, {"provider": provider})

    # --- the downloaded prices ---

    def data(self) -> Optional[dict]:
        if not self._loaded:
            self._data = _read_json(self.prices_file)
            self._loaded = True
        return self._data

    def save(self, cards: Dict[str, Dict[str, Dict[str, float]]], date: str) -> None:
        data = {"date": date, "downloaded": datetime.now(timezone.utc).isoformat(),
                "cards": cards}
        _write_json(self.prices_file, data)
        self._data, self._loaded = data, True
        self._priced_key = None

    def clear(self) -> None:
        if self.prices_file.exists():
            self.prices_file.unlink()
        self._data, self._loaded = None, True
        self._priced_key = None

    def date(self) -> Optional[str]:
        return (self.data() or {}).get("date")

    def active(self) -> str:
        """The provider whose prices the app shows: the choice, or the default without data."""
        provider = self.provider
        if provider != DEFAULT_PROVIDER and not (self.data() or {}).get("cards"):
            return DEFAULT_PROVIDER
        return provider

    def stamp(self, card_data_date: Optional[str]) -> Tuple[str, Optional[str]]:
        """(source, date) of the prices now shown, for the price snapshots."""
        source = self.active()
        return source, (card_data_date if source == DEFAULT_PROVIDER else self.date())

    def priced_index(self, index: Dict[str, dict]) -> Dict[str, dict]:
        """The index with the active provider's prices. The same object until something changes."""
        source = self.active()
        if source == DEFAULT_PROVIDER or not index:
            return index
        data = self.data() or {}
        key = (id(index), source, data.get("downloaded"))
        if key != self._priced_key:
            self._priced, self._covered = overlay(index, data.get("cards") or {}, source)
            self._priced_key = key
        return self._priced

    def status(self, index_size: int = 0) -> dict:
        data = self.data() or {}
        cards = data.get("cards") or {}
        active = self.active()
        counts = {}
        for stores in cards.values():
            for key in stores:
                counts[key] = counts.get(key, 0) + 1
        return {
            "provider": self.provider,
            "active": active,
            "date": data.get("date"),
            "downloaded": data.get("downloaded"),
            "providers": [{"key": key, "label": label, "note": note,
                           "needs_download": spec is not None,
                           "cards": counts.get(key, 0) if spec else index_size}
                          for key, (label, note, spec) in PROVIDERS.items()],
        }


def parse_download(prices_gz: bytes, ids_gz: bytes) -> Tuple[Dict[str, Dict[str, Dict[str, float]]], str]:
    """Read the two MTGJSON downloads: (cards, price date)."""
    try:
        ids = read_identifiers(io.StringIO(gzip.decompress(ids_gz).decode("utf-8")))
        payload = json.loads(gzip.decompress(prices_gz).decode("utf-8"))
    except (OSError, ValueError, EOFError) as error:
        raise PriceDownloadError("The price files from MTGJSON could not be read (%s)." % error)
    if not ids or not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise PriceDownloadError("The price files from MTGJSON have no prices.")
    cards = read_prices(payload["data"], ids)
    date = str((payload.get("meta") or {}).get("date") or "")
    return cards, date

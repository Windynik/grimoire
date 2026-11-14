import gzip
import json

import pytest
from fastapi.testclient import TestClient

from backend.api import price_routes
from backend.api.dependencies import get_bulk_data_manager, get_provider_prices
from backend.core.provider_prices import (
    DEFAULT_PROVIDER, PriceDownloadError, ProviderPrices, overlay, parse_download, read_identifiers,
    read_prices,
)
from main import app

DAY = "2026-11-13"
IDS_CSV = ("uuid,scryfallId,cardKingdomId\n"
           "u-bolt,s-bolt,1\nu-sol,s-sol,2\nu-ghost,,3\n")
PRICES = {
    "meta": {"date": DAY},
    "data": {
        "u-bolt": {"paper": {
            "cardkingdom": {"retail": {"normal": {"2026-11-12": 1.5, DAY: 1.99},
                                       "foil": {DAY: 4.5}},
                            "buylist": {"normal": {DAY: 0.8}}, "currency": "USD"},
            "cardmarket": {"retail": {"normal": {DAY: 0.9}}, "currency": "EUR"},
            "manapool": {"retail": {"normal": {DAY: 1.25}}, "buylist": {}, "currency": "USD"}}},
        "u-sol": {"paper": {"cardkingdom": {"retail": {"normal": {DAY: 2.49}}, "buylist": {},
                                            "currency": "USD"}}},
        "u-ghost": {"paper": {"cardkingdom": {"retail": {"normal": {DAY: 9.0}}}}},
    },
}
INDEX = {
    "s-bolt": {"id": "s-bolt", "name": "Lightning Bolt", "prices": {"usd": "1.00", "usd_foil": "3.00"}},
    "s-sol": {"id": "s-sol", "name": "Sol Ring", "prices": {"usd": "1.10"}},
    "s-bear": {"id": "s-bear", "name": "Bear", "prices": {"usd": "0.10"}},
}


def gz(text):
    return gzip.compress(text.encode("utf-8"))


def test_the_download_keeps_the_usd_stores_by_scryfall_id():
    ids = read_identifiers(IDS_CSV.splitlines())
    assert ids == {"u-bolt": "s-bolt", "u-sol": "s-sol"}
    cards = read_prices(PRICES["data"], ids)
    assert cards["s-bolt"] == {"cardkingdom": {"normal": 1.99, "foil": 4.5},
                               "cardkingdom_buylist": {"normal": 0.8},
                               "manapool": {"normal": 1.25}}
    assert cards["s-sol"] == {"cardkingdom": {"normal": 2.49}}
    parsed, date = parse_download(gz(json.dumps(PRICES)), gz(IDS_CSV))
    assert parsed == cards and date == DAY
    with pytest.raises(PriceDownloadError):
        parse_download(b"not gzip", gz(IDS_CSV))


def test_the_overlay_replaces_the_usd_prices_and_keeps_the_rest():
    cards = read_prices(PRICES["data"], read_identifiers(IDS_CSV.splitlines()))
    priced, covered = overlay(INDEX, cards, "cardkingdom")
    assert covered == 2
    assert priced["s-bolt"]["prices"] == {"usd": "1.99", "usd_foil": "4.50"}
    assert priced["s-bear"] is INDEX["s-bear"]  # no Card Kingdom price: the own price stays
    assert INDEX["s-bolt"]["prices"]["usd"] == "1.00"  # the base index does not change
    buylist, _ = overlay(INDEX, cards, "cardkingdom_buylist")
    # The buylist has no foil price: the foil keeps the TCGplayer price.
    assert buylist["s-bolt"]["prices"] == {"usd": "0.80", "usd_foil": "3.00"}


def test_the_choice_needs_downloaded_prices(tmp_path):
    prices = ProviderPrices(tmp_path)
    assert prices.provider == DEFAULT_PROVIDER
    prices.set_provider("cardkingdom")
    assert prices.provider == "cardkingdom"
    # No store prices yet: the app still shows TCGplayer prices.
    assert prices.active() == DEFAULT_PROVIDER
    assert prices.priced_index(INDEX) is INDEX
    prices.save(read_prices(PRICES["data"], read_identifiers(IDS_CSV.splitlines())), DAY)
    assert prices.active() == "cardkingdom"
    first = prices.priced_index(INDEX)
    assert first["s-sol"]["prices"]["usd"] == "2.49"
    assert prices.priced_index(INDEX) is first  # cached until something changes
    assert prices.stamp("2026-11-01") == ("cardkingdom", DAY)
    # A new instance reads the saved choice and prices.
    again = ProviderPrices(tmp_path)
    assert again.active() == "cardkingdom" and again.date() == DAY
    again.clear()
    assert again.active() == DEFAULT_PROVIDER
    assert again.stamp("2026-11-01") == (DEFAULT_PROVIDER, "2026-11-01")
    with pytest.raises(KeyError):
        prices.set_provider("ebay")


class FakeBulk:
    def __init__(self, prices):
        self.provider_prices = prices

    async def load_bulk_data(self):
        return self.provider_prices.priced_index(INDEX)


@pytest.fixture
def price_env(tmp_path, monkeypatch):
    prices = ProviderPrices(tmp_path)
    app.dependency_overrides[get_provider_prices] = lambda: prices
    app.dependency_overrides[get_bulk_data_manager] = lambda: FakeBulk(prices)

    async def fake_fetch(transport=None):
        return gz(json.dumps(PRICES)), gz(IDS_CSV)

    monkeypatch.setattr(price_routes, "fetch_store_prices", fake_fetch)
    yield prices
    app.dependency_overrides.clear()


def test_the_price_routes_choose_download_and_clear(price_env):
    with TestClient(app) as client:
        status = client.get("/api/prices").json()
        assert status["provider"] == "scryfall" and status["active"] == "scryfall"
        assert [p["key"] for p in status["providers"]] == [
            "scryfall", "cardkingdom", "cardkingdom_buylist", "manapool"]
        assert status["providers"][0]["cards"] == 3 and not status["providers"][0]["needs_download"]
        chosen = client.put("/api/prices/provider", json={"provider": "cardkingdom"}).json()
        assert chosen["provider"] == "cardkingdom" and chosen["active"] == "scryfall"
        loaded = client.post("/api/prices/download").json()
        assert loaded["active"] == "cardkingdom" and loaded["date"] == DAY
        assert {p["key"]: p["cards"] for p in loaded["providers"]}["cardkingdom"] == 2
        assert client.put("/api/prices/provider", json={"provider": "x"}).status_code == 400
        assert client.delete("/api/prices").json()["active"] == "scryfall"


def test_a_failed_download_says_so(price_env, monkeypatch):
    import httpx

    async def broken(transport=None):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(price_routes, "fetch_store_prices", broken)
    with TestClient(app) as client:
        response = client.post("/api/prices/download")
        assert response.status_code == 502
        assert "Could not download the store prices" in response.json()["detail"]


def test_the_card_data_loader_returns_the_chosen_store_prices(tmp_path):
    import asyncio

    from backend.core.bulk_data import BulkDataManager

    manager = BulkDataManager(cache_dir=str(tmp_path))
    manager.index_file.write_text("".join(json.dumps(c) + "\n" for c in INDEX.values()))
    manager.provider_prices = ProviderPrices(tmp_path)
    plain = asyncio.run(manager.load_bulk_data())
    assert plain["s-bolt"]["prices"]["usd"] == "1.00"
    manager.provider_prices.save(read_prices(PRICES["data"], read_identifiers(IDS_CSV.splitlines())),
                                 DAY)
    manager.provider_prices.set_provider("manapool")
    priced = asyncio.run(manager.load_bulk_data())
    assert priced["s-bolt"]["prices"]["usd"] == "1.25"
    assert priced["s-sol"]["prices"]["usd"] == "1.10"  # Mana Pool has no Sol Ring price

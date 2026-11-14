"""The price provider: which store's prices the app shows, and their download."""

import asyncio

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.api.dependencies import get_bulk_data_manager, get_provider_prices
from backend.core.bulk_data import BulkDataManager
from backend.core.provider_prices import (
    IDS_URL, PRICES_URL, PROVIDERS, PriceDownloadError, ProviderPrices, parse_download,
)
from backend.core.tls import tls_context

router = APIRouter(prefix="/api")

USER_AGENT = "Grimoire/1.0 (offline MTG collection app)"
DOWNLOAD_FAILED = ("Could not download the store prices from MTGJSON. Check the internet "
                   "connection, then try again.")
_download_lock = asyncio.Lock()


class ProviderIn(BaseModel):
    provider: str


async def _status(prices: ProviderPrices, bulk: BulkDataManager) -> dict:
    index = await bulk.load_bulk_data()
    return prices.status(len(index or {}))


@router.get("/prices")
async def price_status(
    prices: ProviderPrices = Depends(get_provider_prices),
    bulk: BulkDataManager = Depends(get_bulk_data_manager),
):
    """The chosen provider, the providers, and the date of the store prices."""
    return await _status(prices, bulk)


@router.put("/prices/provider")
async def set_provider(
    request: ProviderIn,
    prices: ProviderPrices = Depends(get_provider_prices),
    bulk: BulkDataManager = Depends(get_bulk_data_manager),
):
    """Choose the price provider. A store provider shows its prices after a download."""
    if request.provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail="Unknown price provider: %s" % request.provider)
    prices.set_provider(request.provider)
    return await _status(prices, bulk)


async def fetch_store_prices(transport=None) -> tuple:
    """Download today's MTGJSON prices and the id table. Returns (prices gz, ids gz)."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0), verify=tls_context(),
                                 headers={"User-Agent": USER_AGENT}, follow_redirects=True,
                                 transport=transport) as client:
        found = []
        for url in (PRICES_URL, IDS_URL):
            response = await client.get(url)
            response.raise_for_status()
            found.append(response.content)
        return tuple(found)


@router.post("/prices/download")
async def download_prices(
    prices: ProviderPrices = Depends(get_provider_prices),
    bulk: BulkDataManager = Depends(get_bulk_data_manager),
):
    """Download today's store prices from MTGJSON (about 20 MB)."""
    if _download_lock.locked():
        raise HTTPException(status_code=409, detail="The store prices are downloading already.")
    async with _download_lock:
        try:
            prices_gz, ids_gz = await fetch_store_prices()
        except httpx.HTTPError:
            raise HTTPException(status_code=502, detail=DOWNLOAD_FAILED)
        try:
            cards, date = await asyncio.to_thread(parse_download, prices_gz, ids_gz)
        except PriceDownloadError as error:
            raise HTTPException(status_code=502, detail=str(error))
        await asyncio.to_thread(prices.save, cards, date)
    return await _status(prices, bulk)


@router.delete("/prices")
async def clear_prices(
    prices: ProviderPrices = Depends(get_provider_prices),
    bulk: BulkDataManager = Depends(get_bulk_data_manager),
):
    """Delete the downloaded store prices. The app shows TCGplayer prices again."""
    prices.clear()
    return await _status(prices, bulk)

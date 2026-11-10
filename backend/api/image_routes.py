import asyncio
import json
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from backend.api.dependencies import (
    get_bulk_data_manager,
    get_collection_store,
    get_deck_store,
    get_image_store,
)
from backend.core.bulk_data import BulkDataManager
from backend.core.collection_store import CollectionStore
from backend.core.image_store import (
    ImageError,
    ImageStore,
    SIZES,
    prefetch_events,
    priority_targets,
    size_url,
    stamp_of,
)
from backend.decks.store import DeckStore


router = APIRouter(prefix="/api")

CACHE_CONTROL = "public, max-age=31536000, immutable"
STALE_CACHE_CONTROL = "no-cache"


@router.get("/images/status")
async def image_status(
    store: ImageStore = Depends(get_image_store),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
    collections: CollectionStore = Depends(get_collection_store),
    decks: DeckStore = Depends(get_deck_store),
):
    """Count the stored images and the images of owned cards."""
    index = await bulk_data_manager.load_bulk_data()

    def count():
        targets = priority_targets(collections, decks, index)
        owned = {"small": 0, "normal": 0}
        for sid, face, url in targets:
            stamp = stamp_of(url)
            for size in SIZES:
                if size_url(url, size) and store.has(sid, face, size, stamp):
                    owned[size] += 1
        # Without the card data, the store cannot tell which images the owned
        # cards need, so "card_data" lets the page say why the counts are 0.
        return {**store.stats(), "owned_total": len(targets),
                "owned_small": owned["small"], "owned_normal": owned["normal"],
                "card_data": bool(index)}

    return await asyncio.to_thread(count)


@router.delete("/images")
async def delete_images(store: ImageStore = Depends(get_image_store)):
    """Delete the stored card images. Refused while a download runs."""
    if store.prefetch_running:
        return JSONResponse(status_code=409,
                            content={"detail": "Wait for the image download to end."})
    removed = await asyncio.to_thread(store.clear)
    return {"removed": removed}


@router.post("/images/prefetch")
async def prefetch_images(
    store: ImageStore = Depends(get_image_store),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
    collections: CollectionStore = Depends(get_collection_store),
    decks: DeckStore = Depends(get_deck_store),
):
    """Download the images of owned cards in the background. Stream the progress."""
    if store.prefetch_running:
        return JSONResponse(status_code=409,
                            content={"detail": "A download is already running."})
    index = await bulk_data_manager.load_bulk_data()
    targets = await asyncio.to_thread(priority_targets, collections, decks, index)

    async def generate():
        # Claim the run here, not in the route. A response that is dropped before
        # the body starts never runs this code, so the claim cannot leak.
        if not store.begin_prefetch():
            event = {"type": "done", "phase": "normal", "done": 0, "total": 0, "failed": 0, "skipped": 0,
                     "busy": True}
            yield "data: %s\n\n" % json.dumps(event)
            return
        events = prefetch_events(store, targets)
        try:
            async for event in events:
                yield "data: %s\n\n" % json.dumps(event)
        finally:
            await events.aclose()
            store.end_prefetch()

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/images/{scryfall_id}/{face}")
async def get_image(
    scryfall_id: str,
    face: str,
    size: str = "normal",
    v: Optional[str] = None,
    store: ImageStore = Depends(get_image_store),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
):
    """Serve a card image from the store. Download it first when it is missing.

    A file with an old version stamp is served at once. A background download
    replaces it.
    """
    try:
        store.path_for(scryfall_id, face, size)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid card id, face, or size")
    index: Dict[str, dict] = await bulk_data_manager.load_bulk_data()
    card = index.get(scryfall_id)
    url = (card or {}).get("image_url" if face == "front" else "back_image_url")
    if card is None:
        # The card data is missing, for example after "Clear card data". A
        # stored image still shows: the page's stamp "v" picks the copy.
        stored = store.stored_path(scryfall_id, face, size, v)
        if stored is not None:
            return FileResponse(str(stored), media_type="image/jpeg",
                                headers={"Cache-Control": STALE_CACHE_CONTROL})
    if not url or not size_url(url, size):
        raise HTTPException(status_code=404, detail="No image for this card")
    stamp = stamp_of(url)
    current = store.path_for(scryfall_id, face, size, stamp)
    if current.is_file():
        return FileResponse(str(current), media_type="image/jpeg",
                            headers={"Cache-Control": CACHE_CONTROL})
    stale = store.stale_path(scryfall_id, face, size, stamp)
    if stale is not None:
        store.refresh_in_background(scryfall_id, face, url, size)
        return FileResponse(str(stale), media_type="image/jpeg",
                            headers={"Cache-Control": STALE_CACHE_CONTROL})
    try:
        path = await store.fetch(scryfall_id, face, url, size)
    except ImageError:
        raise HTTPException(status_code=502, detail="Image download failed")
    return FileResponse(str(path), media_type="image/jpeg",
                        headers={"Cache-Control": CACHE_CONTROL})

import asyncio
import json
from typing import Dict

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
    prefetch_events,
    priority_targets,
)
from backend.decks.store import DeckStore


router = APIRouter(prefix="/api")

CACHE_CONTROL = "public, max-age=31536000, immutable"


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
        cached = sum(1 for sid, face, _ in targets if store.has(sid, face))
        return {**store.stats(), "owned_total": len(targets), "owned_cached": cached}

    return await asyncio.to_thread(count)


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
            event = {"type": "done", "done": 0, "total": 0, "failed": 0, "skipped": 0,
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
    store: ImageStore = Depends(get_image_store),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
):
    """Serve a card image from the store. Download it first when it is missing."""
    try:
        store.path_for(scryfall_id, face)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid card id or face")
    index: Dict[str, dict] = await bulk_data_manager.load_bulk_data()
    card = index.get(scryfall_id)
    url = (card or {}).get("image_url" if face == "front" else "back_image_url")
    if not url:
        raise HTTPException(status_code=404, detail="No image for this card")
    try:
        path = await store.fetch(scryfall_id, face, url)
    except ImageError:
        raise HTTPException(status_code=502, detail="Image download failed")
    return FileResponse(str(path), media_type="image/jpeg",
                        headers={"Cache-Control": CACHE_CONTROL})

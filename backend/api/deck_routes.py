from typing import Dict

from fastapi import APIRouter, Depends, HTTPException

from backend.api.dependencies import (
    get_bulk_data_manager,
    get_collection_store,
    get_deck_store,
)
from backend.core.bulk_data import BulkDataManager
from backend.core.collection_store import CollectionStore
from backend.decks.records import (
    CreateDeck,
    DeckIn,
    apply_update,
    hydrate_record,
    new_record,
    strip_display,
)
from backend.decks.store import DeckStore
from backend.forge.playbook import load_playbook


router = APIRouter(prefix="/api")

_FORMATS = load_playbook().formats


def deck_response(record: dict, index: Dict[str, dict], collections: CollectionStore) -> dict:
    """Build the body every deck route returns.

    Args:
        record: Stored deck record
        index: Card index keyed by Scryfall id
        collections: Collection store (the analysis uses it)

    Returns:
        The hydrated record plus the key "analysis" (empty for now)
    """
    deck = hydrate_record(record, index)
    deck["analysis"] = {}
    return deck


def _check_format(key: str) -> None:
    if key not in _FORMATS:
        raise HTTPException(status_code=400, detail="Unknown format: %s" % key)


def _stored(store: DeckStore, deck_id: str) -> dict:
    record = store.get(deck_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Deck not found")
    return record


@router.get("/decks")
async def list_decks(store: DeckStore = Depends(get_deck_store)):
    """Summaries of the saved decks, newest first."""
    decks = store.list()
    return {"decks": decks, "total": len(decks)}


@router.post("/decks", status_code=201)
async def create_deck(
    request: CreateDeck,
    store: DeckStore = Depends(get_deck_store),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
    collections: CollectionStore = Depends(get_collection_store),
):
    """Create an empty deck."""
    _check_format(request.format)
    record = new_record(request.name, request.format, request.collection_job_id)
    store.save(record)
    index = await bulk_data_manager.load_bulk_data()
    return deck_response(record, index, collections)


@router.get("/decks/{deck_id}")
async def get_deck(
    deck_id: str,
    store: DeckStore = Depends(get_deck_store),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
    collections: CollectionStore = Depends(get_collection_store),
):
    """One saved deck."""
    record = _stored(store, deck_id)
    index = await bulk_data_manager.load_bulk_data()
    return deck_response(record, index, collections)


@router.put("/decks/{deck_id}")
async def update_deck(
    deck_id: str,
    request: DeckIn,
    store: DeckStore = Depends(get_deck_store),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
    collections: CollectionStore = Depends(get_collection_store),
):
    """Replace the editable parts of a saved deck."""
    stored = _stored(store, deck_id)
    _check_format(request.format)
    index = await bulk_data_manager.load_bulk_data()
    # Hydrate before the strip so the saved entries keep their art URL
    record = strip_display(hydrate_record(apply_update(stored, request), index))
    store.save(record)
    return deck_response(record, index, collections)


@router.delete("/decks/{deck_id}")
async def delete_deck(deck_id: str, store: DeckStore = Depends(get_deck_store)):
    """Delete a saved deck."""
    if not store.delete(deck_id):
        raise HTTPException(status_code=404, detail="Deck not found")
    return {"success": True}


@router.post("/decks/{deck_id}/duplicate", status_code=201)
async def duplicate_deck(
    deck_id: str,
    store: DeckStore = Depends(get_deck_store),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
    collections: CollectionStore = Depends(get_collection_store),
):
    """Save a copy of a deck."""
    new_id = store.duplicate(deck_id)
    if new_id is None:
        raise HTTPException(status_code=404, detail="Deck not found")
    index = await bulk_data_manager.load_bulk_data()
    return deck_response(store.get(new_id), index, collections)

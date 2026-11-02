import re
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.api.dependencies import (
    get_bulk_data_manager,
    get_collection_store,
    get_deck_store,
)
from backend.core.bulk_data import BulkDataManager
from backend.core.collection_store import CollectionStore
from backend.decks.analysis import analyze, owned_counts
from backend.decks.records import (
    CreateDeck,
    DeckIn,
    apply_update,
    hydrate_record,
    new_record,
    strip_display,
)
from backend.decks.store import DeckStore
from backend.decks.textio import export_arena, export_csv, export_text, parse_decklist, resolve
from backend.forge.playbook import load_playbook


router = APIRouter(prefix="/api")

_PLAYBOOK = load_playbook()
_FORMATS = _PLAYBOOK.formats
MAX_SECTION_ENTRIES = 400  # the same cap as SectionsIn


def _collection_for(record: dict, collections: CollectionStore) -> Tuple[Optional[List[dict]],
                                                                         Optional[dict]]:
    """Return (rows, metadata) of the deck's collection, else of the newest one, else (None, None)."""
    listed = collections.list_collections()
    chosen = next((m for m in listed if m["job_id"] == record.get("collection_job_id")), None)
    chosen = chosen or (listed[0] if listed else None)
    if chosen is None:
        return None, None
    return collections.get_collection(chosen["job_id"]), chosen


def deck_response(record: dict, index: Dict[str, dict], collections: CollectionStore) -> dict:
    """Build the body every deck route returns.

    Args:
        record: Stored deck record
        index: Card index keyed by Scryfall id
        collections: Collection store (the analysis uses it)

    Returns:
        The hydrated record plus the key "analysis" (see backend.decks.analysis.analyze)
    """
    deck = hydrate_record(record, index)
    rows, meta = _collection_for(record, collections)
    deck["analysis"] = analyze(record, index, rows, meta, _PLAYBOOK)
    return deck


class ImportDeck(BaseModel):
    text: str = Field(min_length=1, max_length=50000)
    name: str = Field("Imported deck", min_length=1, max_length=120)
    format: str = Field(max_length=40)
    collection_job_id: Optional[str] = Field(None, max_length=64)


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


@router.post("/decks/import", status_code=201)
async def import_deck(
    request: ImportDeck,
    store: DeckStore = Depends(get_deck_store),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
    collections: CollectionStore = Depends(get_collection_store),
):
    """Create a deck from a pasted decklist. Lists the names that match no card."""
    _check_format(request.format)
    index = await bulk_data_manager.load_bulk_data()
    record = new_record(request.name, request.format, request.collection_job_id)
    rows, _ = _collection_for(record, collections)
    owned = owned_counts(rows, index) if rows else {}
    sections, commander, unknown = resolve(parse_decklist(request.text), index, owned)
    if commander is not None and not _FORMATS[request.format].commander:
        # Only a commander format has a commander: the card joins the main deck
        same = [e for e in sections["main"] if e["scryfall_id"] == commander["scryfall_id"]]
        if same:
            same[0]["count"] += 1
        else:
            sections["main"].insert(0, {"scryfall_id": commander["scryfall_id"],
                                        "name": commander["name"], "count": 1, "basic": False,
                                        "role": "", "reason": ""})
        commander = None
    if commander is None and not any(sections.values()):
        raise HTTPException(status_code=400, detail="No card in the list matches the card data.")
    if any(len(entries) > MAX_SECTION_ENTRIES for entries in sections.values()):
        raise HTTPException(status_code=422, detail="A section has more than %d different cards."
                            % MAX_SECTION_ENTRIES)
    record["commander"] = commander
    record["sections"] = sections
    # Hydrate before the strip so the saved entries keep their art URL
    record = strip_display(hydrate_record(record, index))
    store.save(record)
    body = deck_response(record, index, collections)
    body["unknown"] = unknown
    return body


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


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "deck"


@router.get("/decks/{deck_id}/export")
async def export_deck(
    deck_id: str,
    kind: str = Query("text"),
    store: DeckStore = Depends(get_deck_store),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
):
    """Download a deck as plain text, an Arena list, or CSV."""
    if kind not in ("text", "arena", "csv"):
        raise HTTPException(status_code=400, detail="Unknown export kind: %s" % kind)
    record = _stored(store, deck_id)
    if kind == "text":
        body = export_text(record)
    else:
        index = await bulk_data_manager.load_bulk_data()
        body = export_arena(record, index) if kind == "arena" else export_csv(record, index)
    csv_kind = kind == "csv"
    media = "text/csv" if csv_kind else "text/plain; charset=utf-8"
    filename = "%s.%s" % (_slug(record.get("name", "")), "csv" if csv_kind else "txt")
    return Response(content=body, media_type=media,
                    headers={"Content-Disposition": 'attachment; filename="%s"' % filename})

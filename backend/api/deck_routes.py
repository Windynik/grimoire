import asyncio
import re
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.api.dependencies import (
    get_bulk_data_manager,
    get_collection_store,
    get_deck_store,
    get_ollama_client,
)
from backend.core.bulk_data import BulkDataManager
from backend.core.collection_store import CollectionStore
from backend.core.ollama_client import ModelError, OllamaClient
from backend.decks.agent import run_agent
from backend.decks.analysis import analyze, owned_counts
from backend.decks.records import (
    CreateDeck,
    DeckIn,
    apply_update,
    edit_check,
    hydrate_record,
    new_record,
    strip_display,
)
from backend.decks.changelog import changes_newest_first, record_edit, record_event
from backend.decks.pull import pull_list
from backend.decks.store import DeckStore
from backend.decks.usage import CopiesInUse, mark_taken, taken_cards
from backend.decks.textio import (
    MAX_COUNT, export_arena, export_csv, export_text, parse_decklist, resolve,
)
from backend.forge.playbook import load_playbook


router = APIRouter(prefix="/api")

DECK_CHANGED = ("This deck changed in another tab or window. "
                "Reload the page to get the newest version, then edit again.")
_DECK_LOCKS: Dict[str, asyncio.Lock] = {}


def _deck_lock(deck_id: str) -> asyncio.Lock:
    """The lock of one deck's saves. A lock binds to the running event loop."""
    lock = _DECK_LOCKS.get(deck_id)
    if lock is None:
        lock = _DECK_LOCKS[deck_id] = asyncio.Lock()
    return lock

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


def deck_response(record: dict, index: Dict[str, dict], collections: CollectionStore,
                  decks: Optional[DeckStore] = None) -> dict:
    """Build the body every deck route returns.

    Args:
        record: Stored deck record
        index: Card index keyed by Scryfall id
        collections: Collection store (the analysis uses it)
        decks: Deck store. When given, a card that needs copies that other
            decks use gets the issue "taken" (see backend.decks.usage).

    Returns:
        The hydrated record plus the key "analysis" (see backend.decks.analysis.analyze)
    """
    deck = hydrate_record(record, index)
    deck.setdefault("revision", 0)
    deck.pop("edit", None)
    deck.pop("changelog", None)
    rows, meta = _collection_for(record, collections)
    deck["analysis"] = analyze(record, index, rows, meta, _PLAYBOOK)
    if decks is not None:
        copies = CopiesInUse(decks, collections, index)
        mark_taken(deck["analysis"], record, taken_cards(record, record.get("id"), copies), index)
    return deck


async def full_response(record: dict, index: Dict[str, dict], collections: CollectionStore,
                        decks: DeckStore) -> dict:
    """deck_response with the "taken" check, off the event loop (it reads every store)."""
    return await asyncio.to_thread(deck_response, record, index, collections, decks)


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


MAX_USAGE_IDS = 200


@router.get("/decks/usage")
async def deck_usage(
    ids: str = "",
    store: DeckStore = Depends(get_deck_store),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
    collections: CollectionStore = Depends(get_collection_store),
):
    """For each card id: the decks that use the card (any printing), and the copies.

    Each value is {"decks": [{"deck_id", "name", "count"}], "used", "owned", "free"}.
    """
    wanted = [i.strip() for i in ids.split(",") if i.strip()][:MAX_USAGE_IDS]
    if not wanted:
        return {}
    index = await bulk_data_manager.load_bulk_data()
    copies = await asyncio.to_thread(CopiesInUse, store, collections, index)
    return {sid: copies.status(copies.key(sid)) for sid in wanted}


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
    record_event(record, "created")
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
            same[0]["count"] = min(MAX_COUNT, same[0]["count"] + 1)
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
    record_event(record, "imported", "Imported from a decklist.", with_cards=True)
    store.save(record)
    body = await full_response(record, index, collections, store)
    body["unknown"] = unknown
    return body


@router.get("/decks/{deck_id}/pull-list")
async def deck_pull_list(
    deck_id: str,
    store: DeckStore = Depends(get_deck_store),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
    collections: CollectionStore = Depends(get_collection_store),
):
    """Where to find each card of a deck: grouped by collection and binder."""
    record = _stored(store, deck_id)
    index = await bulk_data_manager.load_bulk_data()

    def build():
        owned = [(meta, collections.cards_with_binders(meta["job_id"]))
                 for meta in collections.list_collections()]
        return pull_list(record, index, owned)

    return await asyncio.to_thread(build)


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
    return await full_response(record, index, collections, store)


@router.put("/decks/{deck_id}")
async def update_deck(
    deck_id: str,
    request: DeckIn,
    store: DeckStore = Depends(get_deck_store),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
    collections: CollectionStore = Depends(get_collection_store),
):
    """Replace the editable parts of a saved deck.

    The order mark of the editor (see edit_check) keeps a late, older save from
    replacing a newer one, and refuses a save from a tab that missed another
    tab's save.
    """
    _check_format(request.format)
    index = await bulk_data_manager.load_bulk_data()
    # One save of a deck at a time, so the check and the write cannot interleave.
    async with _deck_lock(deck_id):
        stored = _stored(store, deck_id)
        decision = edit_check(stored, request.edit)
        if decision == "conflict":
            raise HTTPException(status_code=409, detail=DECK_CHANGED)
        if decision == "stale":
            return await full_response(stored, index, collections, store)
        # Hydrate before the strip so the saved entries keep their art URL
        record = strip_display(hydrate_record(apply_update(stored, request), index))
        record_edit(record, stored)
        store.save(record)
    return await full_response(record, index, collections, store)


@router.get("/decks/{deck_id}/changes")
async def deck_changes(deck_id: str, store: DeckStore = Depends(get_deck_store)):
    """The changelog of a deck, newest first (see backend.decks.changelog)."""
    record = _stored(store, deck_id)
    return {"changes": changes_newest_first(record),
            "since": (record.get("changelog") or [{}])[0].get("at") or record.get("created")}


class BuiltIn(BaseModel):
    built: bool


@router.put("/decks/{deck_id}/built")
async def set_built(deck_id: str, request: BuiltIn, store: DeckStore = Depends(get_deck_store)):
    """Mark a deck as built (put together from real cards) or not.

    Only a built deck holds copies of cards (see backend.decks.usage). The
    change leaves the revision and the order mark of the editor as they are.
    """
    async with _deck_lock(deck_id):
        record = _stored(store, deck_id)
        if bool(record.get("built")) != request.built:
            record_event(record, "built" if request.built else "unbuilt")
        record["built"] = request.built
        store.save(record)
    return {"built": request.built}


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
    return await full_response(store.get(new_id), index, collections, store)


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


class AgentAsk(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    model: str = Field("", max_length=100)


@router.post("/decks/{deck_id}/agent")
async def deck_agent(
    deck_id: str,
    request: AgentAsk,
    store: DeckStore = Depends(get_deck_store),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
    collections: CollectionStore = Depends(get_collection_store),
    client: OllamaClient = Depends(get_ollama_client),
):
    """Ask the local model for swaps and cuts. The engine checks them and nothing is saved."""
    record = _stored(store, deck_id)
    status = await client.status()
    model = request.model or status.get("default_model")
    if not status.get("available") or not model:
        raise HTTPException(status_code=503, detail="The local model is not running.")
    _check_format(record.get("format"))
    index = await bulk_data_manager.load_bulk_data()
    rows, meta = _collection_for(record, collections)
    try:
        result = await run_agent(record, request.message, model, index, rows or [],
                                 _PLAYBOOK, client)
    except ModelError:
        raise HTTPException(status_code=502,
                            detail="The model did not give a usable answer. Try again.")
    # The result sections come from the stripped file: add the card display data back
    result["sections"] = hydrate_record({"sections": result["sections"]}, index)["sections"]
    proposed = dict(record, sections=result["sections"])
    result["analysis"] = analyze(proposed, index, rows, meta, _PLAYBOOK)
    return result

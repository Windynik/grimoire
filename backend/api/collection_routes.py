import asyncio
import datetime
import os
from pathlib import Path
from collections import OrderedDict
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException

from backend.api.dependencies import get_bulk_data_manager, get_collection_store, get_deck_store
from backend.api.routes import check_format
from backend.core.bulk_data import BulkDataManager
from backend.core.collection_query import (
    MAX_PREVIOUS,
    Filters,
    collection_set_names,
    insights,
    new_since,
    owned_cards,
    has_flag_words,
    parse_query,
    previous_import,
    search,
    set_catalog,
    set_checklist,
    sets_summary,
    shelves,
)
from backend.core.collection_store import CollectionStore
from backend.decks.store import DeckStore
from backend.decks.usage import CopiesInUse, decked_keys, used_counts

router = APIRouter(prefix="/api")

CACHE_SIZE = 4
# (job_id, file mtime, id(index), directory mtime) -> merged collection
MERGE_CACHE = OrderedDict()
_INDEX_ID = None
# id(index) -> (index, set catalog); the index has ~108k records, so build once
_CATALOG = {}


def today() -> datetime.date:
    """The server's local date. Tests replace it."""
    return datetime.date.today()


def get_catalog(index: dict) -> dict:
    cached = _CATALOG.get(id(index))
    if cached is not None and cached[0] is index:
        return cached[1]
    _CATALOG.clear()
    catalog = set_catalog(index)
    _CATALOG[id(index)] = (index, catalog)
    return catalog


class Merged:
    """A collection merged with the card index, ready to search."""

    def __init__(self, cards, new_keys, meta, has_previous, index):
        self.cards = cards
        self.new_keys = new_keys
        self.meta = meta
        self.has_previous = has_previous
        self.index = index  # keeps id(index) from being reused while cached


def _stamp(store, job_id: str):
    """File mtimes of the collection and of every stored collection.

    Any change (add, delete, in-place rewrite) changes the stamp, so the
    "new" flags that depend on the previous collection stay fresh.
    """
    root = getattr(store, "storage_dir", None)
    if root is None:
        return None
    try:
        files = tuple(sorted((p.name, p.stat().st_mtime_ns) for p in Path(str(root)).glob("*.json")))
        mine = os.stat(os.path.join(str(root), job_id + ".json")).st_mtime_ns
    except OSError:
        return None
    return (mine, files)


def _merge(store, job_id: str, index: dict) -> Merged:
    stored = store.get_collection(job_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    original = store.get_original(job_id)
    cards = owned_cards(stored, index, collection_set_names(original[1] if original else None))
    listing = store.list_collections()
    position = next((i for i, m in enumerate(listing) if m.get("job_id") == job_id), None)
    meta = listing[position] if position is not None else {}
    # The previous import of the same collection, not just the last import:
    # an unrelated collection in between must not make every card "new".
    olders = listing[position + 1:position + 1 + MAX_PREVIOUS] if position is not None else []
    older_rows = [store.get_collection(m["job_id"]) or [] for m in olders]
    found = previous_import(stored, older_rows)
    previous_rows = older_rows[found] if found is not None else None
    new_keys = new_since(stored, previous_rows) if previous_rows is not None else set()
    return Merged(cards, new_keys, meta, previous_rows is not None, index)


def get_merged(store, job_id: str, index: dict) -> Merged:
    """Merged cards of a collection, cached until the file or the index changes."""
    global _INDEX_ID
    if id(index) != _INDEX_ID:
        MERGE_CACHE.clear()  # drop entries that hold the old index
        _INDEX_ID = id(index)
    stamp = _stamp(store, job_id) if index else None  # an empty index is not cached
    key = (job_id, stamp, id(index))
    if stamp is not None:
        hit = MERGE_CACHE.get(key)
        if hit is not None and hit.index is index:
            MERGE_CACHE.move_to_end(key)
            return hit
    merged = _merge(store, job_id, index)
    if stamp is not None:
        MERGE_CACHE[key] = merged
        while len(MERGE_CACHE) > CACHE_SIZE:
            MERGE_CACHE.popitem(last=False)
    return merged


def _csv(value: str) -> List[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def _tri_state(value: str) -> Optional[bool]:
    value = (value or "").strip().lower()
    if value in ("1", "true", "yes", "foil"):
        return True
    if value in ("0", "false", "no", "normal", "nonfoil"):
        return False
    return None


def _mv_values(value: str) -> List[str]:
    # "+" in a URL decodes to a space, so "7+" can arrive as "7"
    return ["7+" if v in ("7", "7+") else v for v in _csv(value)]


@router.get("/collection/{job_id}/search")
async def search_collection(
    job_id: str,
    q: str = "",
    limit: int = 60,
    offset: int = 0,
    sort: str = "",
    colors: str = "",
    rarity: str = "",
    type: str = "",
    mv: str = "",
    format: str = "",
    set: str = "",
    min_price: Optional[float] = None,
    foil: str = "",
    dupes: str = "",
    card_type: str = "",
    color: str = "",
    store: CollectionStore = Depends(get_collection_store),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
    deck_store: DeckStore = Depends(get_deck_store),
):
    """Search a collection: keywords, multi-value filters, live facets, value."""
    formats = _csv(format)
    for key in formats:
        check_format(key)
    index = await bulk_data_manager.load_bulk_data()
    merged = get_merged(store, job_id, index)
    filters = Filters(
        colors=[c.upper() for c in _csv(colors)],
        rarity=[r.lower() for r in _csv(rarity)],
        type=[t.capitalize() for t in _csv(type)],
        mv=_mv_values(mv),
        format=formats,
        set=[s.lower() for s in _csv(set)],
        min_price=min_price,
        foil=_tri_state(foil),
        dupes=_tri_state(dupes) is True,
        type_contains=card_type.strip(),
        includes_color=color.strip().upper(),
    )
    query = parse_query(q)
    if query.wants_copies:
        copies = await asyncio.to_thread(CopiesInUse, deck_store, store, index)
        # Only built decks hold copies (see backend.decks.usage).
        used = used_counts(copies.usage)
        query.copies = {key: (used.get(key, 0), copies.owned.get(key, 0))
                        for key in used.keys() | copies.owned.keys()}
    if query.wants_decks:
        query.decked = await asyncio.to_thread(decked_keys, deck_store, index)
    results, facets, value = search(merged.cards, query, filters, sort, merged.new_keys)
    if not results and has_flag_words(q):
        # "new perspectives" or the card "Foil": the bare word was a name.
        found = search(merged.cards, parse_query(q, flags_as_text=True), filters, sort,
                       merged.new_keys)
        if found[0]:
            results, facets, value = found

    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    page = [
        dict(card, owned=True,
             new=(card["scryfall_id"], bool(card["foil"])) in merged.new_keys)
        for card in results[offset:offset + limit]
    ]
    return {"cards": page, "total": len(results), "offset": offset, "limit": limit,
            "facets": facets, "value": value}


@router.get("/collection/{job_id}/insights")
async def collection_insights(
    job_id: str,
    store: CollectionStore = Depends(get_collection_store),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
):
    """Totals, mix, and curve of a collection, plus its name and dates."""
    index = await bulk_data_manager.load_bulk_data()
    merged = get_merged(store, job_id, index)
    data_date = None
    status_of = getattr(bulk_data_manager, "get_cache_status", None)
    if status_of:
        data_date = getattr(status_of(), "download_date", None)
    result = insights(merged.cards)
    result.update({
        "name": merged.meta.get("name") or "Collection " + job_id[:8],
        "created": merged.meta.get("created"),
        "card_data_date": data_date,
        "has_previous": merged.has_previous,
    })
    return result


@router.get("/collection/{job_id}/shelves")
async def collection_shelves(
    job_id: str,
    store: CollectionStore = Depends(get_collection_store),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
    deck_store: DeckStore = Depends(get_deck_store),
):
    """Spotlight, most valuable, foils, new cards, and forgotten gems."""
    index = await bulk_data_manager.load_bulk_data()
    merged = get_merged(store, job_id, index)
    day = (today() - datetime.date(1970, 1, 1)).days
    decked = await asyncio.to_thread(decked_keys, deck_store, index)
    return shelves(merged.cards, merged.new_keys, day, decked)


@router.get("/collection/{job_id}/sets")
async def collection_sets(
    job_id: str,
    store: CollectionStore = Depends(get_collection_store),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
):
    """Owned sets with completion and value."""
    index = await bulk_data_manager.load_bulk_data()
    merged = get_merged(store, job_id, index)
    return sets_summary(merged.cards, get_catalog(index))


@router.get("/collection/{job_id}/sets/{code}")
async def collection_set(
    job_id: str,
    code: str,
    store: CollectionStore = Depends(get_collection_store),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
):
    """The checklist of one set."""
    index = await bulk_data_manager.load_bulk_data()
    merged = get_merged(store, job_id, index)
    result = set_checklist(merged.cards, index, get_catalog(index), code)
    if result is None:
        raise HTTPException(status_code=404, detail="Set not found")
    return result

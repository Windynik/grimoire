import asyncio
import json
import re
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from fastapi.responses import StreamingResponse, FileResponse

from backend.api.dependencies import (
    get_bulk_data_manager,
    get_collection_store,
    get_csv_processor,
    get_ollama_client,
)
from backend.core.bulk_data import NON_GAME_LAYOUTS, BulkDataManager
from backend.core.collection_query import archive_matches, parse_query
from backend.core.collection_store import CollectionStore
from backend.core.paths import cache_path
from backend.core.prices import best_price  # noqa: F401  (re-exported)
from backend.core.csv_processor import CSVProcessor, enrich_rows, write_enriched_csv
from backend.core.ollama_client import OllamaClient
from backend.forge.cards import is_game_card
from backend.forge.playbook import load_playbook
from backend.models.schemas import CacheStatus, ProcessResult


router = APIRouter(prefix="/api")

RECOMMENDED_MODEL = "qwen3.5:9b"
PROGRESS_DIR = cache_path("progress")


def progress_file(job_id: str) -> Path:
    """Path of a job's enhanced CSV, checked to lie inside the progress directory."""
    progress_dir = PROGRESS_DIR.resolve()
    output_file = (progress_dir / f"{job_id}.csv").resolve()
    try:
        output_file.relative_to(progress_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID")
    return output_file


def serialize_bulk_card(card_id: str, card_info: dict) -> dict:
    """Build the card payload returned by browse/search endpoints."""
    prices = card_info.get("prices", {})
    return {
        "name": card_info.get("name", ""),
        "scryfall_id": card_id,
        "mana_cost": card_info.get("mana_cost", ""),
        "oracle_text": card_info.get("oracle_text", ""),
        "type_line": card_info.get("type_line", ""),
        "image_url": card_info.get("image_url", ""),
        "back_image_url": card_info.get("back_image_url", ""),
        "rarity": card_info.get("rarity", ""),
        "set": card_info.get("set", ""),
        "price": best_price(prices),
        "prices": prices,
        "quantity": 0,
        "owned": False,
    }


HYDRATED_FIELDS = ("image_url", "back_image_url", "mana_cost", "oracle_text")


def hydrate(cards: list, bulk_data: dict) -> list:
    """Fill fields that older stored collections lack from the card index.

    Collections saved before multi-face support have empty images and text
    for transform/MDFC cards; the index has them.
    """
    if not bulk_data:
        return cards
    for card in cards:
        info = bulk_data.get(card.get("scryfall_id", ""))
        if not info:
            continue
        for field in HYDRATED_FIELDS:
            if not card.get(field) and info.get(field):
                card[field] = info[field]
    return cards


def mark_owned(cards: list) -> list:
    """Flag collection cards as owned for the frontend."""
    for card in cards:
        card["owned"] = True
    return cards


def matches_filters(card: dict, card_type: str, color: str, rarity: str, foil: str,
                    identity=None) -> bool:
    """Check a card dict against the optional viewer filters.

    Works for both bulk-data cards and stored collection cards.
    When `identity` is a list, the color filter uses the Scryfall color identity.
    When `identity` is None, the card is not in the index, so the color filter
    uses the mana cost.
    """
    if card_type and card_type.lower() not in (card.get("type_line") or "").lower():
        return False

    if rarity and (card.get("rarity") or "").lower() != rarity.lower():
        return False

    if foil:
        is_foil = (card.get("foil") or "normal").lower() not in ("normal", "")
        if (foil == "foil") != is_foil:
            return False

    if color:
        color = color.upper()
        if identity is not None:
            if color == "C":
                if identity:
                    return False
            elif color not in identity:
                return False
        else:
            mana = (card.get("mana_cost") or "").upper()
            if color == "C":
                if any(c in mana for c in "WUBRG"):
                    return False
            elif color not in mana:
                return False

    return True


def card_price(card: dict):
    """Numeric price of a card dict (serialized or raw index entry), or None."""
    price = card["price"] if "price" in card else best_price(card.get("prices"))
    try:
        return float(price) if price else None
    except (TypeError, ValueError):
        return None


def sort_key(sort: str):
    """Key function and direction for a sort name, or None for no sorting.

    Unpriced cards always sort to the end, in either price direction.
    """
    if sort == "name":
        return (lambda c: (c.get("name") or "").lower()), False
    if sort == "price":  # high to low
        return (lambda c: card_price(c) if card_price(c) is not None else -1.0), True
    if sort == "price_asc":  # low to high
        return (lambda c: card_price(c) if card_price(c) is not None else float("inf")), False
    return None


def sort_cards(cards: list, sort: str) -> list:
    """Sort card dicts in place by the requested key."""
    spec = sort_key(sort)
    if spec:
        key, reverse = spec
        cards.sort(key=key, reverse=reverse)
    return cards


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "version": "1.0.0"}


@router.get("/cache/status", response_model=CacheStatus)
async def get_cache_status(
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager)
):
    """Get bulk data cache status."""
    return bulk_data_manager.get_cache_status()


@router.post("/cache/download")
async def download_cache(
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager)
):
    """Download bulk data with SSE progress updates."""

    async def generate_progress():
        progress_updates = []

        def progress_callback(percentage: int):
            progress_updates.append(percentage)

        # Start download as background task
        async def download_task():
            return await bulk_data_manager.download_bulk_data(progress_callback)

        task = asyncio.create_task(download_task())
        last_percentage = 0

        # Stream progress while download is running
        while not task.done():
            if progress_updates and progress_updates[-1] != last_percentage:
                last_percentage = progress_updates[-1]
                yield f"data: {json.dumps({'percentage': last_percentage})}\n\n"
            await asyncio.sleep(0.5)

        # Get final result
        success = await task

        if success:
            yield f"data: {json.dumps({'percentage': 100, 'status': 'complete'})}\n\n"
        else:
            yield f"data: {json.dumps({'error': 'Download failed'})}\n\n"

    return StreamingResponse(
        generate_progress(),
        media_type="text/event-stream"
    )


@router.delete("/cache")
async def clear_cache(
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager)
):
    """Clear bulk data cache."""
    success = bulk_data_manager.clear_cache()
    return {"success": success}


@router.post("/process", response_model=ProcessResult)
async def process_csv(
    file: UploadFile = File(...),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
    csv_processor: CSVProcessor = Depends(get_csv_processor),
    store: CollectionStore = Depends(get_collection_store),
):
    """Upload and process CSV file."""

    # Load bulk data
    bulk_data = await bulk_data_manager.load_bulk_data()

    if not bulk_data:
        raise HTTPException(
            status_code=400,
            detail="Bulk data not available. Please download cache first."
        )

    # Read CSV content
    content = await file.read()
    csv_content = content.decode('utf-8')

    # Process CSV
    result = await csv_processor.process_csv(csv_content, bulk_data)

    # Store collection for viewer
    if result.status == "complete" and hasattr(result, '_enriched_rows'):
        store.store_collection(
            result.job_id, result._enriched_rows, bulk_data,
            source_name=file.filename or "",
            original_headers=getattr(result, '_original_headers', None),
            original_rows=getattr(result, '_original_rows', None),
        )

    return result


SAMPLE_PATH = Path(__file__).resolve().parents[2] / "examples" / "ManaBox_Collection.csv"
SAMPLE_NAME = "Sample collection.csv"


def import_stream(content: bytes, filename: str, bulk_data: dict,
                  csv_processor: CSVProcessor, store: CollectionStore) -> StreamingResponse:
    """Process CSV bytes and stream progress as server-sent events."""
    def sse(payload: dict) -> str:
        return f"data: {json.dumps(payload)}\n\n"

    async def generate():
        try:
            csv_content = content.decode('utf-8')
        except UnicodeDecodeError:
            yield sse({"type": "error", "detail": "File must be UTF-8 encoded text"})
            return

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def on_progress(info: dict):
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "progress", **info})

        worker = asyncio.ensure_future(asyncio.to_thread(
            csv_processor.process_csv_sync, csv_content, bulk_data, on_progress))
        worker.add_done_callback(
            lambda _: loop.call_soon_threadsafe(queue.put_nowait, None))

        last_current = None
        total = None
        while True:
            item = await queue.get()
            if item is None:
                break
            last_current, total = item["current"], item["total"]
            yield sse(item)

        try:
            result = worker.result()
        except Exception as exc:
            yield sse({"type": "error", "detail": str(exc) or "Processing failed"})
            return

        if result.status == "error":
            detail = (result.errors[0].get("error") if result.errors else None)
            yield sse({"type": "error", "detail": detail or "Processing failed"})
            return

        if last_current != result.total_processed:
            yield sse({"type": "progress", "current": result.total_processed,
                       "total": result.total_processed, "current_card": "",
                       "errors": result.error_count})

        if hasattr(result, '_enriched_rows'):
            store.store_collection(
                result.job_id, result._enriched_rows, bulk_data,
                source_name=filename,
                original_headers=getattr(result, '_original_headers', None),
                original_rows=getattr(result, '_original_rows', None),
            )

        yield sse({"type": "done", "result": {
            "job_id": result.job_id,
            "status": result.status,
            "total_processed": result.total_processed,
            "success_count": result.success_count,
            "error_count": result.error_count,
            "errors": result.errors,
        }})

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/process/stream")
async def process_csv_stream(
    file: UploadFile = File(...),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
    csv_processor: CSVProcessor = Depends(get_csv_processor),
    store: CollectionStore = Depends(get_collection_store),
):
    """Upload and process a CSV file. Stream progress as server-sent events."""
    bulk_data = await bulk_data_manager.load_bulk_data()

    if not bulk_data:
        raise HTTPException(
            status_code=400,
            detail="Bulk data not available. Please download cache first."
        )

    content = await file.read()
    return import_stream(content, file.filename or "", bulk_data, csv_processor, store)


@router.post("/process/sample")
async def process_sample(
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
    csv_processor: CSVProcessor = Depends(get_csv_processor),
    store: CollectionStore = Depends(get_collection_store),
):
    """Import the sample collection that ships with the app."""
    try:
        content = SAMPLE_PATH.read_bytes()
    except OSError:
        raise HTTPException(status_code=404, detail="The sample collection is missing.")
    bulk_data = await bulk_data_manager.load_bulk_data()
    if not bulk_data:
        raise HTTPException(
            status_code=400,
            detail="Bulk data not available. Please download cache first."
        )
    return import_stream(content, SAMPLE_NAME, bulk_data, csv_processor, store)


@router.get("/download/{job_id}")
async def download_result(job_id: str):
    """Download processed CSV file."""
    # Validate job_id format (UUID or safe alphanumeric)
    if not re.match(r'^[a-f0-9-]+$', job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    output_file = progress_file(job_id)

    if not output_file.exists():
        raise HTTPException(status_code=404, detail="Job not found")

    return FileResponse(
        path=str(output_file),
        media_type="text/csv",
        filename=f"enhanced_collection_{job_id}.csv"
    )


@router.get("/collection/{job_id}/export")
async def export_collection(
    job_id: str,
    store: CollectionStore = Depends(get_collection_store),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
):
    """Export the enhanced CSV, rebuilding it from the original rows if needed."""
    if not re.match(r'^[a-f0-9-]+$', job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID format")
    if store.get_collection(job_id) is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    output_file = progress_file(job_id)
    if not output_file.exists():
        original = store.get_original(job_id)
        if original is None:
            raise HTTPException(
                status_code=409,
                detail="This collection was stored before the app kept the original "
                       "CSV. Import the CSV again to export it.",
            )
        bulk_data = await bulk_data_manager.load_bulk_data()
        if not bulk_data:
            raise HTTPException(
                status_code=400,
                detail="Bulk data not available. Please download cache first."
            )
        headers, rows, _errors, _count = enrich_rows(original[0], original[1], bulk_data)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        write_enriched_csv(output_file, headers, rows)

    return FileResponse(
        path=str(output_file),
        media_type="text/csv",
        filename=f"enhanced_collection_{job_id}.csv"
    )


@router.get("/collections")
async def list_collections(
    store: CollectionStore = Depends(get_collection_store)
):
    """All remembered (previously imported) collections, newest first."""
    collections = store.list_collections()
    return {"collections": collections, "total": len(collections)}


@router.delete("/collection/{job_id}")
async def delete_collection(
    job_id: str,
    store: CollectionStore = Depends(get_collection_store)
):
    """Delete a remembered collection (and its processed CSV, if present)."""
    if not re.match(r'^[a-f0-9-]+$', job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    deleted = store.delete_collection(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Collection not found")

    # Clean up the enhanced CSV produced by the same job, if it's still around
    try:
        output_file = progress_file(job_id)
        if output_file.exists():
            output_file.unlink()
    except (HTTPException, OSError):
        pass

    return {"success": True}


@router.get("/collection/{job_id}")
async def get_collection(
    job_id: str,
    store: CollectionStore = Depends(get_collection_store),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
):
    """Get collection data with images."""
    collection = store.get_collection(job_id)

    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    hydrate(collection, await bulk_data_manager.load_bulk_data())
    mark_owned(collection)

    return {
        "cards": collection,
        "total": len(collection)
    }


_FORMATS = load_playbook().formats


def legal_in(record: dict, fmt_key: str) -> bool:
    """Return True when an index record is a game card playable in a format.

    A format with a legality key keeps `legal` and `restricted` cards.
    A format without one (casual) keeps every game card.
    """
    if not is_game_card(record):
        return False
    legality_key = _FORMATS[fmt_key].legality_key
    if legality_key is None:
        return True
    return (record.get("legalities") or {}).get(legality_key) in ("legal", "restricted")


def check_format(fmt_key: str) -> None:
    """Raise 400 when a non-empty format key is not in the playbook."""
    if fmt_key and fmt_key not in _FORMATS:
        raise HTTPException(status_code=400, detail="Unknown format: " + fmt_key)


@router.get("/cards/search")
async def search_all_cards(
    q: str = "",
    limit: int = 60,
    offset: int = 0,
    sort: str = "",
    card_type: str = "",
    color: str = "",
    rarity: str = "",
    format: str = "",
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager)
):
    """Search/browse the full bulk data archive with pagination and filters.

    Empty query browses every card. `total` reflects all matches so the
    frontend can page through the entire archive.
    """
    bulk_data = await bulk_data_manager.load_bulk_data()

    if not bulk_data:
        raise HTTPException(
            status_code=400,
            detail="Bulk data not available. Please download cache first."
        )

    check_format(format)
    query = parse_query(q)
    matches = [
        (card_id, card_info)
        for card_id, card_info in bulk_data.items()
        if card_info.get("layout") not in NON_GAME_LAYOUTS
        and archive_matches(card_info, query)
        and matches_filters(card_info, card_type, color, rarity, "",
                           identity=card_info.get("color_identity"))
        and (not format or legal_in(card_info, format))
    ]

    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    # Sort the raw index entries, then serialize only the requested page
    spec = sort_key(sort)
    if spec:
        key, reverse = spec
        matches.sort(key=lambda item: key(item[1]), reverse=reverse)

    cards = [
        serialize_bulk_card(cid, info)
        for cid, info in matches[offset:offset + limit]
    ]

    return {"cards": cards, "total": len(matches), "offset": offset, "limit": limit}


@router.get("/ai/status")
async def ai_status(ollama: OllamaClient = Depends(get_ollama_client)):
    """Whether a local Ollama server (and at least one model) is available."""
    status = await ollama.status()
    status["recommended"] = RECOMMENDED_MODEL
    return status

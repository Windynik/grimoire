import asyncio
import json
import random
import re
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel

from backend.api.dependencies import (
    get_bulk_data_manager,
    get_collection_store,
    get_csv_processor,
    get_ollama_client,
)
from backend.core.bulk_data import NON_GAME_LAYOUTS, BulkDataManager
from backend.core.collection_store import CollectionStore
from backend.core.csv_processor import CSVProcessor
from backend.core.deck_builder import (
    SPELL_BUCKETS,
    DeckBuilder,
    apply_swaps,
    color_identity,
    compute_curve,
    deck_card,
)
from backend.core.ollama_client import OllamaClient
from backend.models.schemas import CacheStatus, ProcessResult


router = APIRouter(prefix="/api")


def best_price(prices: dict):
    """Best available price: USD, then USD foil, EUR, TIX."""
    prices = prices or {}
    return (
        prices.get("usd")
        or prices.get("usd_foil")
        or prices.get("eur")
        or prices.get("tix")
    )


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


def matches_filters(card: dict, card_type: str, color: str, rarity: str, foil: str) -> bool:
    """Check a card dict against the optional viewer filters.

    Works for both bulk-data cards and stored collection cards; color is
    derived from the mana cost so it needs no extra stored fields.
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
        mana = (card.get("mana_cost") or "").upper()
        color = color.upper()
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
        )

    return result


@router.get("/download/{job_id}")
async def download_result(job_id: str):
    """Download processed CSV file."""
    # Validate job_id format (UUID or safe alphanumeric)
    if not re.match(r'^[a-f0-9-]+$', job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    progress_dir = Path(".scryfall_cache/progress").resolve()
    output_file = (progress_dir / f"{job_id}.csv").resolve()

    # Ensure the resolved path is within the expected directory
    try:
        output_file.relative_to(progress_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID")

    if not output_file.exists():
        raise HTTPException(status_code=404, detail="Job not found")

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
    progress_dir = Path(".scryfall_cache/progress").resolve()
    output_file = (progress_dir / f"{job_id}.csv").resolve()
    try:
        output_file.relative_to(progress_dir)
        if output_file.exists():
            output_file.unlink()
    except (ValueError, OSError):
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


@router.get("/collection/{job_id}/search")
async def search_collection(
    job_id: str,
    q: str = "",
    limit: int = 60,
    offset: int = 0,
    sort: str = "",
    card_type: str = "",
    color: str = "",
    rarity: str = "",
    foil: str = "",
    store: CollectionStore = Depends(get_collection_store),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
):
    """Search/browse a collection with pagination and filters."""
    results = store.get_collection(job_id)
    if results is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    if q:
        query_lower = q.lower()
        results = [c for c in results if query_lower in (c.get("name") or "").lower()]

    if card_type or color or rarity or foil:
        results = [
            card for card in results
            if matches_filters(card, card_type, color, rarity, foil)
        ]

    mark_owned(results)
    sort_cards(results, sort)

    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    page = hydrate(results[offset:offset + limit], await bulk_data_manager.load_bulk_data())

    return {"cards": page, "total": len(results), "offset": offset, "limit": limit}


@router.get("/collection/{job_id}/random")
async def get_random_cards(
    job_id: str,
    limit: int = 20,
    store: CollectionStore = Depends(get_collection_store),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
):
    """Get random cards from collection."""
    collection = store.get_collection(job_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    sample_size = min(limit, len(collection))
    random_cards = mark_owned(random.sample(collection, sample_size))
    hydrate(random_cards, await bulk_data_manager.load_bulk_data())

    return {"cards": random_cards, "total": len(random_cards)}


@router.get("/cards/search")
async def search_all_cards(
    q: str = "",
    limit: int = 60,
    offset: int = 0,
    sort: str = "",
    card_type: str = "",
    color: str = "",
    rarity: str = "",
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

    query_lower = q.lower()
    matches = [
        (card_id, card_info)
        for card_id, card_info in bulk_data.items()
        if card_info.get("layout") not in NON_GAME_LAYOUTS
        and (not query_lower or query_lower in card_info.get("name", "").lower())
        and matches_filters(card_info, card_type, color, rarity, "")
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


@router.get("/cards/random")
async def get_random_all_cards(
    limit: int = 30,
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager)
):
    """Get random cards from all bulk data."""
    bulk_data = await bulk_data_manager.load_bulk_data()

    if not bulk_data:
        raise HTTPException(
            status_code=400,
            detail="Bulk data not available. Please download cache first."
        )

    all_cards = [
        item for item in bulk_data.items()
        if item[1].get("layout") not in NON_GAME_LAYOUTS
    ]
    sample_size = min(limit, len(all_cards))
    random_sample = random.sample(all_cards, sample_size)

    cards = [
        serialize_bulk_card(card_id, card_info)
        for card_id, card_info in random_sample
    ]

    return {"cards": cards, "total": len(cards)}


# ---------------------------------------------------------------------------
# Deck Forge — offline rules-engine deck builder + optional local AI
# ---------------------------------------------------------------------------

class DeckBuildRequest(BaseModel):
    job_id: str
    format: str = "commander"
    commander: str = ""
    # Custom format knobs
    deck_size: int = 60
    singleton: bool = False
    max_copies: int = 4
    colors: str = ""


class DeckExplainRequest(BaseModel):
    deck: dict
    model: str = ""


class DeckRefineRequest(BaseModel):
    job_id: str
    deck: dict
    message: str
    history: list = []
    model: str = ""


class AiForgeRequest(BaseModel):
    job_id: str
    wish: str = ""
    model: str = ""
    format: str = "commander"
    # Custom format knobs (mirror DeckBuildRequest)
    deck_size: int = 60
    singleton: bool = False
    max_copies: int = 4
    colors: str = ""


# Format -> (deck_size, land_target) for sizing the authoring budget
FORMAT_SIZES = {
    "commander": (99, 36),
    "brawl": (59, 24),
}


def nonland_budget(request: AiForgeRequest) -> int:
    """How many nonland cards the AI may author for the chosen format."""
    if request.format in FORMAT_SIZES:
        size, lands = FORMAT_SIZES[request.format]
        return size - lands
    size = request.deck_size if request.format == "custom" else 60
    return size - round(size * 0.38)


def build_authored(
    builder: DeckBuilder,
    request: AiForgeRequest,
    commander_name: str,
    focus_tags: list,
    colors: set,
    chosen_names: set,
    rarity_limits: dict = None,
    required_names: set = None,
) -> dict:
    """Build the chosen format, guaranteeing the AI's card picks land first."""
    fmt = request.format
    if fmt == "commander":
        return builder.build_commander_deck(
            commander_name or None, focus_tags=focus_tags,
            chosen_names=chosen_names, rarity_limits=rarity_limits,
            required_names=required_names,
        )
    if fmt == "brawl":
        return builder.build_commander_deck(
            commander_name or None, deck_size=59, land_target=24,
            focus_tags=focus_tags, chosen_names=chosen_names,
            rarity_limits=rarity_limits, required_names=required_names,
        )
    if fmt == "pauper":
        return builder.build_constructed(
            colors=colors or None, rarity="common", focus_tags=focus_tags,
            chosen_names=chosen_names, rarity_limits=rarity_limits,
            required_names=required_names, format_name="pauper",
        )
    if fmt == "custom":
        return builder.build_constructed(
            deck_size=request.deck_size, singleton=request.singleton,
            max_copies=request.max_copies, colors=colors or None,
            focus_tags=focus_tags, chosen_names=chosen_names,
            rarity_limits=rarity_limits, required_names=required_names,
            format_name="custom",
        )
    return builder.build_constructed(
        colors=colors or None, focus_tags=focus_tags,
        chosen_names=chosen_names, rarity_limits=rarity_limits,
        required_names=required_names, format_name="sixty",
    )


def load_deck_builder(job_id: str, store: CollectionStore) -> DeckBuilder:
    collection = store.get_collection(job_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    return DeckBuilder(collection)


def build_from_request(builder: DeckBuilder, request: DeckBuildRequest) -> dict:
    """Dispatch a build request to the right engine entry point."""
    fmt = request.format
    if fmt == "commander":
        return builder.build_commander_deck(request.commander or None)
    if fmt == "brawl":
        return builder.build_commander_deck(
            request.commander or None, deck_size=59, land_target=24
        )
    if fmt == "pauper":
        return builder.build_constructed(rarity="common", format_name="pauper")
    if fmt == "custom":
        colors = {c for c in request.colors.upper() if c in "WUBRG"} or None
        return builder.build_constructed(
            deck_size=request.deck_size,
            singleton=request.singleton,
            max_copies=request.max_copies,
            colors=colors,
            format_name="custom",
        )
    return builder.build_constructed(format_name="sixty")


@router.get("/deck/commanders/{job_id}")
async def get_commander_candidates(
    job_id: str,
    store: CollectionStore = Depends(get_collection_store)
):
    """Legendary creatures in the collection that can lead a Commander deck."""
    builder = load_deck_builder(job_id, store)
    candidates = [deck_card(c, []) for c in builder.commander_candidates()]
    return {"commanders": candidates, "total": len(candidates)}


@router.post("/deck/build")
async def build_deck(
    request: DeckBuildRequest,
    store: CollectionStore = Depends(get_collection_store)
):
    """Build a deck from owned cards only — fully offline, no model needed."""
    builder = load_deck_builder(request.job_id, store)

    try:
        return build_from_request(builder, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/ai/status")
async def ai_status(ollama: OllamaClient = Depends(get_ollama_client)):
    """Whether a local Ollama server (and at least one model) is available."""
    return await ollama.status()


@router.post("/deck/ai-forge")
async def ai_forge_deck(
    request: AiForgeRequest,
    store: CollectionStore = Depends(get_collection_store),
    ollama: OllamaClient = Depends(get_ollama_client),
):
    """Agentic deck forge: the local model authors the decklist itself.

    Two grounded stages, streamed as SSE:
      1. Strategy — the model picks a commander (or colors) + themes from the
         player's real collection facts.
      2. Authoring — the model is handed the player's OWNED cards in that
         identity and writes the decklist, choosing the actual cards by name.

    Every pick is validated against the collection (invented names are dropped),
    and the rules engine guarantees legality: it honors the AI's picks first,
    then completes the mana base and backfills any shortfall. The deck is always
    legal and fully owned, no matter what the model returns.
    """
    status = await ollama.status()
    if not status["available"]:
        raise HTTPException(
            status_code=503,
            detail="No local Ollama server found — see the AI setup panel.",
        )

    builder = load_deck_builder(request.job_id, store)
    summary = builder.collection_summary()
    model = request.model or None
    fmt = request.format

    # An explicitly named format in the wish beats the dropdown
    # (except custom, whose knobs the user set deliberately)
    wish_lower = request.wish.lower()
    format_override = None
    if re.search(r"\b60\b|sixty", wish_lower):
        format_override = "sixty"
    elif "pauper" in wish_lower:
        format_override = "pauper"
    elif "brawl" in wish_lower:
        format_override = "brawl"
    elif re.search(r"\bcommander\b|\bedh\b", wish_lower):
        format_override = "commander"
    if format_override and format_override != fmt and fmt != "custom":
        fmt = format_override
        request.format = format_override

    is_commander = fmt in ("commander", "brawl")

    def sse(payload: dict) -> str:
        return f"data: {json.dumps(payload)}\n\n"

    # Owned cards the wish references by name — hard requirements downstream
    wish_cards = builder.find_wish_cards(request.wish)
    wish_card_info = [
        {
            "name": c.get("name", ""),
            "colors": "".join(sorted(color_identity(c))) or "C",
            "rarity": c.get("rarity", ""),
            "type": (c.get("type_line") or "").split("—")[0].strip(),
        }
        for c in wish_cards
    ]

    async def generate():
        # ----- Stage 1: strategy -----
        strategy_message = "Reading your collection and choosing a strategy…"
        if format_override and fmt == format_override:
            labels = {"sixty": "60-card", "pauper": "Pauper", "brawl": "Brawl", "commander": "Commander"}
            strategy_message = (
                f"Your wish asks for a {labels.get(fmt, fmt)} deck — building that. "
                "Reading your collection…"
            )
        yield sse({"stage": "strategy", "message": strategy_message})

        facts = {k: v for k, v in summary.items() if k != "commanders"}
        commander_name = ""
        colors: set = set()

        wish_note = (
            "The wish references these OWNED cards — the deck MUST be able to "
            f"include them, so pick compatible colors: {json.dumps(wish_card_info)}\n"
            if wish_card_info else ""
        )
        constraints_spec = (
            '"key_cards": [names from the referenced cards above that must be in the deck], '
            '"max_mythics": <number if the wish limits how many mythic rares, else null>, '
        )

        if is_commander:
            if not summary["commanders"]:
                yield sse({"error": "No legendary creatures in this collection to lead a Commander deck."})
                return
            commander_menu = [
                {"name": c["name"], "colors": c["identity"], "tags": c["tags"], "types": c["types"]}
                for c in summary["commanders"][:40]
            ]
            strategy_prompt = (
                "You are choosing a Commander deck strategy from a real MTG collection.\n"
                f"Owner's wish: {request.wish or 'surprise me with the strongest synergy'}\n"
                + wish_note
                + f"Collection facts: {json.dumps(facts)}\n"
                f"Available commanders (choose EXACTLY one name from this list; prefer one "
                f"whose colors contain the referenced cards' colors): {json.dumps(commander_menu)}\n"
                'Reply as JSON: {"commander": "<exact name from the list>", '
                + constraints_spec +
                '"focus_tags": [up to 3 from: ramp, draw, removal, boardwipe, counterspell, tokens, '
                'counters, graveyard, sacrifice, lifegain, spellslinger, artifacts, enchantments], '
                '"deck_name": "<evocative 2-5 word deck name>", '
                '"blurb": "<one sentence on the game plan>"}'
            )
        else:
            strategy_prompt = (
                f"You are choosing a {fmt} MTG deck strategy from a real collection.\n"
                f"Owner's wish: {request.wish or 'surprise me with the strongest synergy'}\n"
                + wish_note
                + f"Collection facts (color_depth shows how many owned cards per color): {json.dumps(facts)}\n"
                'Reply as JSON: {"colors": "<1-3 letters from WUBRG, the deck\'s colors — '
                'they must cover the referenced cards>", '
                + constraints_spec +
                '"focus_tags": [up to 3 from: ramp, draw, removal, boardwipe, counterspell, tokens, '
                'counters, graveyard, sacrifice, lifegain, spellslinger, artifacts, enchantments], '
                '"deck_name": "<evocative 2-5 word deck name>", '
                '"blurb": "<one sentence on the game plan>"}'
            )

        try:
            strategy = await ollama.chat_json(strategy_prompt, model=model)
        except Exception as exc:
            yield sse({"error": f"Local model error during strategy: {exc}"})
            return

        focus_tags = [str(t) for t in strategy.get("focus_tags", [])][:3]
        deck_name = str(strategy.get("deck_name", "")) or "The Grimoire's Choice"
        blurb = str(strategy.get("blurb", ""))

        # Key cards: what the model echoed, but only names we actually matched.
        # Default to all wish-referenced cards if the model echoed none.
        wish_names = {c["name"].lower(): c["name"] for c in wish_card_info}
        key_cards = {
            wish_names[str(n).strip().lower()]
            for n in (strategy.get("key_cards") or [])
            if str(n).strip().lower() in wish_names
        } or set(wish_names.values())

        max_mythics = strategy.get("max_mythics")
        rarity_limits = None
        if isinstance(max_mythics, int) and max_mythics >= 0:
            rarity_limits = {"mythic": max_mythics}

        if is_commander:
            picked = str(strategy.get("commander", ""))
            valid = {c["name"].lower() for c in summary["commanders"]}
            commander = builder.pick_commander(picked if picked.lower() in valid else None)
            commander_name = commander["name"]
            identity = color_identity(commander)
            rarity = None
            exclude = commander_name
            # The commander itself may be a wish-referenced card
            key_cards.discard(commander_name)
        else:
            # Custom colors from the request win; otherwise the model's pick
            colors = {c for c in request.colors.upper() if c in "WUBRG"}
            if not colors:
                colors = {c for c in str(strategy.get("colors", "")).upper() if c in "WUBRG"}
            if not colors:
                colors = {c for c, _ in list(facts.get("color_depth", {}).items())[:2]}
            identity = colors
            rarity = "common" if fmt == "pauper" else None
            exclude = None

        # ----- Stage 2: authoring -----
        yield sse({
            "stage": "authoring",
            "message": f"Writing “{deck_name}”"
                       + (f" around {commander_name}" if commander_name else "")
                       + " from your collection…",
        })

        candidates = builder.authoring_candidates(
            identity, focus_tags=focus_tags, rarity=rarity, exclude=exclude,
            limit=160, must_include=key_cards,
        )
        budget = nonland_budget(request)

        chosen_names: set = set(key_cards)
        rejected = 0
        author_error = ""
        if candidates:
            compact = [
                {"n": c["name"], "t": c["type"], "mv": c["mv"], "r": c["rarity"]}
                for c in candidates
            ]
            constraint_lines = ""
            if key_cards:
                constraint_lines += (
                    f"MUST include: {json.dumps(sorted(key_cards))}.\n"
                )
            if rarity_limits:
                constraint_lines += (
                    f"HARD LIMIT: at most {rarity_limits['mythic']} cards with r=mythic "
                    "in the whole deck (the r field shows each card's rarity).\n"
                )
            author_prompt = (
                f"You are authoring a {fmt} MTG deck named “{deck_name}”"
                + (f" led by {commander_name}" if commander_name else "")
                + f" with themes {focus_tags}.\n"
                f"Owner's wish: {request.wish or 'a strong, synergistic deck'}\n"
                + constraint_lines
                + f"Choose up to {budget} NONLAND cards for this deck, ONLY by exact name "
                "from the owned pool below. Lands and the mana base are added automatically, "
                "so do not pick lands. Favor the strategy, removal/draw, and a healthy mana curve.\n"
                f"Owned pool (n=name, t=type, mv=mana value, r=rarity): {json.dumps(compact)}\n"
                'Reply as JSON: {"cards": ["Exact Name", "Exact Name", ...]}'
            )

            try:
                authored = await ollama.chat_json(author_prompt, model=model)
                by_name = {c["name"].lower(): c["name"] for c in candidates}
                for raw in authored.get("cards", []):
                    key = str(raw).strip().lower()
                    if key in by_name:
                        chosen_names.add(by_name[key])
                    else:
                        rejected += 1
            except Exception as exc:
                # The deck is still built by the engine; just note what happened
                author_error = f"AI authoring step failed ({exc}); the engine built the deck."

        yield sse({"stage": "building", "message": "Completing the mana base and finalizing…"})

        # ----- Stage 3: assemble (engine guarantees legality + constraints) -----
        try:
            deck = build_authored(
                builder, request, commander_name, focus_tags, colors,
                chosen_names, rarity_limits, key_cards,
            )
        except ValueError as exc:
            yield sse({"error": str(exc)})
            return

        # ----- Stage 4: self-review — the model audits its own decklist -----
        review_notes = []
        bench_now = deck.get("bench", [])
        for iteration in (1, 2):
            yield sse({
                "stage": "review",
                "message": f"Self-reviewing the finished decklist (pass {iteration})…",
            })

            spells_by_bucket = {
                bucket: [
                    f"{e['count']}x {e['name']} [{(e.get('rarity') or '?')[:1]}]"
                    for e in deck["categories"].get(bucket, [])
                ]
                for bucket in ("ramp", "draw", "removal", "synergy")
            }
            bench_compact = [
                {"n": e["name"], "mv": e.get("cmc"), "r": e.get("rarity", "")}
                for e in bench_now[:40]
            ]
            review_prompt = (
                f"You are auditing a finished {fmt} MTG decklist named “{deck_name}”"
                + (f" led by {commander_name}" if commander_name else "")
                + ".\n"
                f"Owner's wish: {request.wish or 'a strong synergistic deck'}\n"
                + (f"Hard requirements (already enforced, do not undo): include {sorted(key_cards)}"
                   + (f"; at most {rarity_limits['mythic']} mythics" if rarity_limits else "")
                   + ".\n" if (key_cards or rarity_limits) else "")
                + "Decklist by role (rarity in brackets: m=mythic, r=rare, u=uncommon, c=common):\n"
                f"{json.dumps(spells_by_bucket)}\n"
                f"Mana curve: {json.dumps(deck['curve'])}\n"
                f"Available replacements (owned, legal): {json.dumps(bench_compact)}\n"
                "Audit critically: does the deck satisfy the wish? Any off-theme, weak, or "
                "curve-breaking cards? If changes are needed, propose one-for-one swaps by "
                "exact name ('in' from the replacements list). Reply as JSON: "
                '{"verdict": "pass" or "revise", "issues": ["<short issue>", ...], '
                '"swaps": [{"out": "...", "in": "...", "why": "<short>"}]}'
            )

            try:
                review = await ollama.chat_json(review_prompt, model=model)
            except Exception:
                review_notes.append("Self-review skipped (local model error).")
                break

            verdict = str(review.get("verdict", "pass")).lower()
            issues = [str(i)[:140] for i in (review.get("issues") or [])][:4]
            proposed_swaps = review.get("swaps") or []
            applied = apply_swaps(
                deck,
                proposed_swaps if isinstance(proposed_swaps, list) else [],
                builder,
                protected=key_cards,
                rarity_limits=rarity_limits,
            )
            for s in applied:
                review_notes.append(f"Self-review swap: {s['out']} → {s['in']} — {s['why']}")
            swapped_in = {s["in"].lower() for s in applied}
            bench_now = [e for e in bench_now if e["name"].lower() not in swapped_in]

            if verdict == "pass":
                review_notes.insert(0, (
                    f"Self-review: deck approved on pass {iteration}"
                    + (" after fixes." if applied else ".")
                ))
                break
            if not applied:
                review_notes.insert(0, "Self-review wanted changes, but none were possible with owned cards.")
                review_notes.extend(f"Reviewer: {i}" for i in issues[:2])
                break
            if iteration == 2:
                review_notes.insert(0, "Self-review: revised the deck twice and settled.")

        authored_in_deck = sum(
            1
            for bucket in deck["categories"].values()
            for entry in bucket
            if "AI pick" in entry.get("reasons", [])
        )

        # Honest reporting on the wish's hard requirements
        deck_names_lower = {
            e["name"].lower()
            for k, bucket in deck["categories"].items()
            if k != "basics"
            for e in bucket
        }
        if commander_name:
            deck_names_lower.add(commander_name.lower())
        notes = deck.setdefault("notes", [])
        for name in sorted(key_cards):
            if name.lower() in deck_names_lower:
                notes.insert(0, f"As wished: {name} is in the deck.")
            else:
                notes.insert(0, (
                    f"Couldn't include {name} — it doesn't fit this deck's colors "
                    "or format. Try a commander/colors that match it."
                ))
        if rarity_limits:
            mythic_count = sum(
                e.get("count", 1)
                for k, bucket in deck["categories"].items()
                if k != "basics"
                for e in bucket
                if (e.get("rarity") or "").lower() == "mythic"
            )
            notes.insert(0, f"Mythic cap honored: {mythic_count} of at most {rarity_limits['mythic']} mythics.")

        notes[:0] = review_notes

        deck["deck_name"] = deck_name
        deck["blurb"] = blurb
        deck["ai_authored"] = authored_in_deck
        deck["ai_rejected"] = rejected
        if author_error:
            notes.insert(0, author_error)
        deck.pop("bench", None)
        yield sse({"stage": "final", "deck": deck})

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/deck/refine")
async def refine_deck(
    request: DeckRefineRequest,
    store: CollectionStore = Depends(get_collection_store),
    ollama: OllamaClient = Depends(get_ollama_client),
):
    """Conversational deck tuning: chat about the deck, get validated changes.

    The model replies in JSON with a conversational answer plus optional
    one-for-one swaps. Swaps are validated against the collection and the
    deck's color identity via apply_swaps — the deck can never go illegal.
    """
    status = await ollama.status()
    if not status["available"]:
        raise HTTPException(
            status_code=503,
            detail="No local Ollama server found — see the AI setup panel.",
        )

    builder = load_deck_builder(request.job_id, store)
    deck = request.deck
    if not deck.get("categories"):
        raise HTTPException(status_code=400, detail="No deck to refine — forge one first.")

    identity = set(deck.get("identity", []))
    commander = (deck.get("commander") or {}).get("name", "")

    # Cards currently in the deck, grouped for the prompt
    current = {
        bucket: [f"{e['count']}x {e['name']}" for e in deck["categories"].get(bucket, [])]
        for bucket in SPELL_BUCKETS
    }
    in_deck_names = {
        e["name"].lower()
        for bucket in SPELL_BUCKETS
        for e in deck["categories"].get(bucket, [])
    }

    # Owned, identity-legal cards not already in the deck — the swap pool
    bench = [
        c for c in builder.authoring_candidates(identity, exclude=commander or None, limit=140)
        if c["name"].lower() not in in_deck_names
    ][:100]
    bench_compact = [{"n": c["name"], "t": c["type"], "mv": c["mv"]} for c in bench]

    history_lines = "\n".join(
        f"{str(m.get('role', 'player'))}: {str(m.get('content', ''))[:300]}"
        for m in request.history[-8:]
    )

    prompt = (
        f"You are tuning “{deck.get('deck_name') or 'a deck'}” "
        f"({deck.get('format', 'commander')}"
        + (f", commander: {commander}" if commander else "")
        + f", colors: {''.join(deck.get('identity', [])) or 'C'}, "
        f"themes: {', '.join(deck.get('themes', [])) or 'goodstuff'}).\n"
        f"Current spells by role: {json.dumps(current)}\n"
        f"Available replacements — owned and legal (n=name, t=type, mv=mana value): "
        f"{json.dumps(bench_compact)}\n"
        + (f"Conversation so far:\n{history_lines}\n" if history_lines else "")
        + f"Player: {request.message}\n\n"
        "Answer the player conversationally in 'reply' (under 120 words). If they want "
        "changes, propose one-for-one swaps: 'out' must be an exact name currently in the "
        "deck, 'in' an exact name from the available replacements. Max 8 swaps; none if "
        "they only asked a question. Reply as JSON: "
        '{"reply": "<answer>", "swaps": [{"out": "...", "in": "...", "why": "<short>"}]}'
    )

    system = (
        "You are the Grimoire's deck-tuning assistant for Magic: The Gathering. "
        "Be concise, concrete, and friendly. Never mention or pick cards that are not "
        "in the provided lists."
    )

    try:
        result = await ollama.chat_json(prompt, system=system, model=request.model or None)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Local model error: {exc}")

    reply = str(result.get("reply", "")).strip() or "Hmm — the pages flutter, but no answer forms."
    proposed = result.get("swaps") or []
    proposed = proposed if isinstance(proposed, list) else []
    applied = apply_swaps(deck, proposed, builder)

    # The model wanted changes but none survived validation — say so honestly
    if proposed and not applied:
        reply += (
            " …though on closer inspection, none of those swaps were possible with "
            "your owned cards, so the deck is unchanged."
        )

    return {"reply": reply, "deck": deck, "swaps": applied}


@router.post("/deck/explain")
async def explain_deck(
    request: DeckExplainRequest,
    ollama: OllamaClient = Depends(get_ollama_client),
):
    """Stream a strategy explanation of a built deck from the local model."""
    status = await ollama.status()
    if not status["available"]:
        raise HTTPException(
            status_code=503,
            detail="No local Ollama server found. Install from ollama.com and pull a model "
                   "(e.g. `ollama pull llama3.1:8b`) to enable deck explanations.",
        )

    deck = request.deck
    commander = deck.get("commander") or {}
    categories = deck.get("categories", {})

    def names(bucket: str, cap: int) -> str:
        cards = categories.get(bucket, [])[:cap]
        return ", ".join(
            f"{c.get('count', 1)}x {c['name']}" for c in cards
        ) or "none"

    prompt = (
        f"Here is a {('Commander' if deck.get('format') == 'commander' else '60-card casual')} "
        f"Magic: The Gathering deck built only from cards I own.\n"
        + (f"Commander: {commander.get('name')} — {commander.get('type_line')}\n" if commander else "")
        + f"Colors: {''.join(deck.get('identity', [])) or 'C'}\n"
        f"Themes: {', '.join(deck.get('themes', [])) or 'goodstuff'}\n"
        f"Ramp: {names('ramp', 12)}\n"
        f"Card draw: {names('draw', 12)}\n"
        f"Removal: {names('removal', 12)}\n"
        f"Synergy & creatures: {names('synergy', 40)}\n"
        f"Lands: {names('lands', 10)} plus basics.\n\n"
        "In under 250 words: 1) explain the deck's game plan, 2) name its biggest weakness, "
        "3) suggest which 3 cards FROM THE LIST ABOVE are the most important to mulligan toward. "
        "Only reference cards from the list. No card name inventions."
    )

    system = (
        "You are a friendly, sharp Magic: The Gathering deck coach. "
        "Be concrete and concise. Never mention cards that are not in the provided list."
    )

    async def generate():
        try:
            async for chunk in ollama.stream_chat(prompt, system=system, model=request.model or None):
                yield f"data: {json.dumps({'text': chunk})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'error': f'Local model error: {exc}'})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")

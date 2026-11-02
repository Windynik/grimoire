import asyncio
import json
import re
from typing import AsyncIterator, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.api.dependencies import (
    get_bulk_data_manager,
    get_collection_store,
    get_deck_store,
    get_forge_manager,
    get_ollama_client,
)
from backend.core.bulk_data import BulkDataManager
from backend.core.collection_store import CollectionStore
from backend.core.ollama_client import OllamaClient
from backend.decks.store import DeckStore
from backend.forge.cards import hydrate
from backend.forge.events import TERMINAL
from backend.forge.graph import commander_candidates
from backend.forge.playbook import load_playbook
from backend.forge.session import ForgeManager, ForgeParams


router = APIRouter(prefix="/api")

KEEPALIVE_SECONDS = 15.0


class ForgeRequest(BaseModel):
    job_id: str = Field(max_length=64)
    format: str = Field(max_length=40)
    commander: str = Field(default="", max_length=200)
    wish: str = Field(default="", max_length=2000)
    model: str = Field(default="", max_length=100)
    ask_mode: Literal["countdown", "wait", "never"] = "countdown"
    question_timeout: float = Field(default=20.0, gt=0, le=600)
    deck_size: int = Field(default=60, ge=40, le=250)
    max_copies: int = Field(default=4, ge=1, le=4)
    colors: str = Field(default="", max_length=10)


class AnswerRequest(BaseModel):
    question_id: str
    option: int


def _session(manager: ForgeManager, forge_id: str):
    session = manager.get(forge_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Forge not found")
    return session


async def _load_collection(job_id: str, store: CollectionStore) -> list:
    if not re.match(r'^[a-f0-9-]+$', job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID format")
    collection = store.get_collection(job_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    return collection


@router.get("/forge/formats")
async def forge_formats():
    """Formats the forge can build, in playbook order."""
    playbook = load_playbook()
    return {"formats": [
        {"key": f.key, "name": f.name, "deck_size": f.deck_size, "commander": f.commander}
        for f in playbook.formats.values()
    ]}


@router.get("/forge/commanders/{job_id}")
async def forge_commanders(
    job_id: str,
    format: str = "commander",
    store: CollectionStore = Depends(get_collection_store),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
):
    """Owned, legal cards that can lead a commander deck."""
    playbook = load_playbook()
    fmt = playbook.formats.get(format)
    if fmt is None:
        raise HTTPException(status_code=400, detail="Unknown format")
    collection = await _load_collection(job_id, store)
    if not fmt.commander:
        raise HTTPException(status_code=400, detail="Format has no commander")
    index = await bulk_data_manager.load_bulk_data()

    def find() -> list:
        return commander_candidates(hydrate(collection, index, fmt), fmt)

    found = await asyncio.to_thread(find)
    commanders = [{"id": c.id, "name": c.name, "image_url": c.image_url,
                   "color_identity": sorted(c.color_identity)} for c in found]
    return {"commanders": commanders, "total": len(commanders)}


@router.post("/forge")
async def start_forge(
    request: ForgeRequest,
    store: CollectionStore = Depends(get_collection_store),
    bulk_data_manager: BulkDataManager = Depends(get_bulk_data_manager),
    manager: ForgeManager = Depends(get_forge_manager),
    deck_store: DeckStore = Depends(get_deck_store),
    ollama: OllamaClient = Depends(get_ollama_client),
):
    """Start a forge run in the background and return its id."""
    playbook = load_playbook()
    if request.format not in playbook.formats:
        raise HTTPException(status_code=400, detail="Unknown format")
    collection = await _load_collection(request.job_id, store)
    index = await bulk_data_manager.load_bulk_data()
    if not index:
        raise HTTPException(
            status_code=400,
            detail="Card data not available. Download it on the Home screen first.")
    params = ForgeParams(**{name: getattr(request, name) for name in ForgeParams.__dataclass_fields__})
    session = manager.start(params, collection, index, playbook, ollama, deck_store)
    return {"forge_id": session.id}


def _frame(index: int, event: dict) -> str:
    data = {k: v for k, v in event.items() if k != "type"}
    return "id: %d\nevent: %s\ndata: %s\n\n" % (index, event["type"], json.dumps(data))


async def _stream(session, after: int) -> AsyncIterator[str]:
    """Yield SSE frames, with a keepalive comment after each quiet period."""
    events = session.subscribe(after=after)
    pending = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(events.__anext__())
            done, _ = await asyncio.wait({pending}, timeout=KEEPALIVE_SECONDS)
            if not done:
                yield ": keepalive\n\n"
                continue
            task, pending = pending, None
            try:
                index, event = task.result()
            except StopAsyncIteration:
                return
            yield _frame(index, event)
            if event["type"] in TERMINAL:
                return
    finally:
        if pending is not None:
            pending.cancel()
            try:
                await pending
            except BaseException:
                pass
        await events.aclose()


@router.get("/forge/{forge_id}/events")
async def forge_events(
    forge_id: str,
    last_event_id: Optional[str] = Header(default=None),
    manager: ForgeManager = Depends(get_forge_manager),
):
    """Stream the events of a forge run as server-sent events."""
    session = _session(manager, forge_id)
    try:
        after = int(last_event_id) if last_event_id is not None else -1
    except ValueError:
        after = -1
    return StreamingResponse(_stream(session, after), media_type="text/event-stream")


@router.post("/forge/{forge_id}/answer")
async def forge_answer(
    forge_id: str,
    request: AnswerRequest,
    manager: ForgeManager = Depends(get_forge_manager),
):
    """Answer the open question of a forge run."""
    session = _session(manager, forge_id)
    return {"accepted": session.answer(request.question_id, request.option)}


@router.post("/forge/{forge_id}/cancel")
async def forge_cancel(
    forge_id: str,
    manager: ForgeManager = Depends(get_forge_manager),
):
    """Cancel a forge run."""
    _session(manager, forge_id).cancel()
    return {"cancelled": True}


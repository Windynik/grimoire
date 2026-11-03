import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api.dependencies import (
    get_bulk_data_manager,
    get_collection_store,
    get_deck_store,
    get_image_store,
)
from backend.core.image_store import ImageStore
from main import app
from tests.test_image_store import (
    A, B, C, JPEG, URL, FakeCollections, FakeDecks, card, deck,
)
from tests.test_api import FakeBulk


@pytest.fixture
def setup(tmp_path):
    calls = []
    state = {"status": 200, "delay": 0}

    async def handler(request):
        calls.append(str(request.url))
        if state["delay"]:
            await asyncio.sleep(state["delay"])
        return httpx.Response(state["status"], content=JPEG,
                              headers={"content-type": "image/jpeg"})

    store = ImageStore(root=tmp_path / "images", transport=httpx.MockTransport(handler))
    index = {A: card(A, back=True), B: card(B), C: {"image_url": "", "back_image_url": ""}}
    decks = FakeDecks([deck("d", main=[A, B])])
    cols = FakeCollections([("c", [{"scryfall_id": B, "quantity": 1, "name": "b"}])])
    app.dependency_overrides[get_image_store] = lambda: store
    app.dependency_overrides[get_bulk_data_manager] = lambda: FakeBulk(index)
    app.dependency_overrides[get_deck_store] = lambda: decks
    app.dependency_overrides[get_collection_store] = lambda: cols
    yield store, calls, state
    app.dependency_overrides.clear()


def test_serves_a_stored_image(setup):
    store, calls, _ = setup
    path = store.path_for(A, "front")
    path.parent.mkdir(parents=True)
    path.write_bytes(JPEG)
    with TestClient(app) as client:
        response = client.get("/api/images/%s/front" % A)
    assert response.status_code == 200
    assert response.content == JPEG
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert calls == []


def test_downloads_then_serves(setup):
    store, calls, _ = setup
    with TestClient(app) as client:
        first = client.get("/api/images/%s/back" % A)
        second = client.get("/api/images/%s/back" % A)
    assert first.status_code == second.status_code == 200
    assert first.content == JPEG
    assert len(calls) == 1
    assert calls[0].endswith("-b")


def test_error_statuses(setup):
    _, _, state = setup
    with TestClient(app) as client:
        assert client.get("/api/images/not-an-id/front").status_code == 400
        assert client.get("/api/images/%s/side" % A).status_code == 400
        assert client.get("/api/images/%s/front" % ("9" * 8 + "-0000-0000-0000-000000000000")
                          ).status_code == 404
        assert client.get("/api/images/%s/front" % C).status_code == 404
        assert client.get("/api/images/%s/back" % B).status_code == 404
        state["status"] = 500
        assert client.get("/api/images/%s/front" % A).status_code == 502


def test_status_counts(setup):
    store, _, _ = setup
    with TestClient(app) as client:
        before = client.get("/api/images/status").json()
        assert before == {"count": 0, "bytes": 0, "owned_total": 3, "owned_cached": 0}
        client.get("/api/images/%s/front" % A)
        after = client.get("/api/images/status").json()
    assert after == {"count": 1, "bytes": len(JPEG), "owned_total": 3, "owned_cached": 1}


def events_of(response):
    return [json.loads(line[6:]) for line in response.text.splitlines()
            if line.startswith("data: ")]


def test_prefetch_events_and_skips(setup):
    store, calls, _ = setup
    with TestClient(app) as client:
        client.get("/api/images/%s/front" % A)
        calls.clear()
        response = client.post("/api/images/prefetch")
        events = events_of(response)
        again = events_of(client.post("/api/images/prefetch"))
    assert response.headers["content-type"].startswith("text/event-stream")
    assert events[-1] == {"type": "done", "done": 2, "total": 2, "failed": 0, "skipped": 1}
    assert again[-1] == {"type": "done", "done": 0, "total": 0, "failed": 0, "skipped": 3}
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_second_prefetch_gets_409_while_a_real_run_is_active(tmp_path):
    gate = asyncio.Event()
    started = asyncio.Event()

    async def handler(request):
        started.set()
        await gate.wait()
        return httpx.Response(200, content=JPEG, headers={"content-type": "image/jpeg"})

    store = ImageStore(root=tmp_path / "images", transport=httpx.MockTransport(handler))
    index = {A: card(A)}
    app.dependency_overrides[get_image_store] = lambda: store
    app.dependency_overrides[get_bulk_data_manager] = lambda: FakeBulk(index)
    app.dependency_overrides[get_deck_store] = lambda: FakeDecks([deck("d", main=[A])])
    app.dependency_overrides[get_collection_store] = lambda: FakeCollections([])
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            first = asyncio.ensure_future(client.post("/api/images/prefetch"))
            await asyncio.wait_for(started.wait(), 2)
            second = await client.post("/api/images/prefetch")
            assert second.status_code == 409
            assert second.json() == {"detail": "A download is already running."}
            gate.set()
            response = await first
        assert events_of(response)[-1]["done"] == 1
        assert not store.prefetch_running
        await store.aclose()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_dropped_response_does_not_leak_the_guard(setup):
    from backend.api.image_routes import prefetch_images
    store, _, _ = setup
    index = {A: card(A)}
    response = await prefetch_images(
        store=store, bulk_data_manager=FakeBulk(index),
        collections=FakeCollections([]), decks=FakeDecks([deck("d", main=[A])]))
    assert response.status_code == 200
    del response  # dropped before the body started
    assert not store.prefetch_running
    with TestClient(app) as client:
        assert events_of(client.post("/api/images/prefetch"))[-1]["type"] == "done"

import json

import pytest
from fastapi.testclient import TestClient

from backend.api.dependencies import (
    get_bulk_data_manager, get_collection_store, get_deck_store, get_forge_manager,
    get_ollama_client,
)
from backend.core.collection_store import CollectionStore
from backend.decks.store import DeckStore
from backend.forge.session import ForgeManager
from main import app
from tests.forge.conftest import make_record


class FakeBulk:
    def __init__(self, cards):
        self.cards = cards

    async def load_bulk_data(self):
        return self.cards


class OffClient:
    """An Ollama client that reports no server, so the forge runs engine-only."""

    async def status(self):
        return {"available": False, "models": [], "default_model": None}

    async def list_models(self):
        return []


SAC = "Sacrifice a creature: Scry 1."
DEATH = "Whenever another creature you control dies, each opponent loses 1 life."


def synthetic_records():
    """A small black Aristocrats pool: one commander candidate, 10 spells, one basic land."""
    records = [make_record("Atraxa Test", type_line="Legendary Creature — Angel",
                           mana_cost="{1}{B}", color_identity=("B",), cmc=2, oracle_text=DEATH)]
    for n in range(5):
        records.append(make_record("Sac Outlet %d" % n, type_line="Creature — Kind%d" % n,
                                   oracle_text=SAC, color_identity=("B",), mana_cost="{1}{B}"))
        records.append(make_record("Death Payoff %d" % n, type_line="Creature — Kind%d" % (10 + n),
                                   oracle_text=DEATH, color_identity=("B",), mana_cost="{1}{B}"))
    records.append(make_record("Swamp", type_line="Basic Land — Swamp", mana_cost="", cmc=0,
                               color_identity=("B",), produced=("B",)))
    return records


@pytest.fixture
def overrides(tmp_path):
    store = CollectionStore(storage_dir=str(tmp_path / "collections"))
    decks = DeckStore(storage_dir=str(tmp_path / "decks"))
    records = synthetic_records()
    index = {r["id"]: r for r in records}
    cards = [{"Scryfall ID": r["id"], "Quantity": 4, "Name": r["name"]} for r in records]
    store.store_collection("aaa1", cards, index)
    bulk = FakeBulk(index)
    manager = ForgeManager()
    app.dependency_overrides[get_collection_store] = lambda: store
    app.dependency_overrides[get_bulk_data_manager] = lambda: bulk
    app.dependency_overrides[get_deck_store] = lambda: decks
    app.dependency_overrides[get_forge_manager] = lambda: manager
    app.dependency_overrides[get_ollama_client] = lambda: OffClient()
    yield store, bulk, decks
    app.dependency_overrides.clear()


def read_events(client, forge_id, headers=None):
    """Return a list of (id, event, data) from the SSE stream."""
    frames = []
    with client.stream("GET", "/api/forge/%s/events" % forge_id, headers=headers or {}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        block = []
        for line in r.iter_lines():
            if line:
                block.append(line)
                continue
            if block and not block[0].startswith(":"):
                fields = dict(item.split(": ", 1) for item in block)
                frames.append((int(fields["id"]), fields["event"], json.loads(fields["data"])))
            block = []
    return frames


def test_forge_start_errors(overrides):
    with TestClient(app) as client:
        assert client.post("/api/forge", json={"job_id": "abc", "format": "commander"}
                           ).status_code == 404
        assert client.post("/api/forge", json={"job_id": "aaa1", "format": "bogus"}
                           ).json()["detail"] == "Unknown format"
        store, bulk, _ = overrides
        bulk.cards = {}
        response = client.post("/api/forge", json={"job_id": "aaa1", "format": "commander"})
        assert response.status_code == 400
        assert "Download it on the Home screen" in response.json()["detail"]


def test_forge_runs_engine_only_to_done(overrides):
    _, _, decks = overrides
    with TestClient(app) as client:
        response = client.post("/api/forge", json={"job_id": "aaa1", "format": "casual",
                                                   "colors": "B", "ask_mode": "never"})
        assert response.status_code == 200
        frames = read_events(client, response.json()["forge_id"])
        kinds = [kind for _, kind, _ in frames]
        assert kinds[-1] == "done", frames[-1]
        assert "type" not in frames[-1][2]
        assert [i for i, _, _ in frames] == list(range(len(frames)))
        assert decks.get(frames[-1][2]["deck_id"]) is not None


def test_events_replay_after_last_event_id(overrides):
    with TestClient(app) as client:
        forge_id = client.post("/api/forge", json={"job_id": "aaa1", "format": "casual",
                                                   "colors": "B", "ask_mode": "never"}
                               ).json()["forge_id"]
        full = read_events(client, forge_id)
        assert len(full) > 4
        replay = read_events(client, forge_id, {"Last-Event-ID": "3"})
        assert [f[0] for f in replay] == list(range(4, len(full)))
        bad = read_events(client, forge_id, {"Last-Event-ID": "x"})
        assert len(bad) == len(full)


def test_events_unknown_forge_404(overrides):
    with TestClient(app) as client:
        assert client.get("/api/forge/nope/events").status_code == 404


def test_answer_and_cancel_unknown_forge_404(overrides):
    with TestClient(app) as client:
        assert client.post("/api/forge/nope/answer",
                           json={"question_id": "q", "option": 0}).status_code == 404
        assert client.post("/api/forge/nope/cancel").status_code == 404


def test_answer_rejected_and_cancel(overrides):
    with TestClient(app) as client:
        forge_id = client.post("/api/forge", json={"job_id": "aaa1", "format": "casual",
                                                   "colors": "B", "ask_mode": "never"}
                               ).json()["forge_id"]
        read_events(client, forge_id)
        answer = client.post("/api/forge/%s/answer" % forge_id,
                             json={"question_id": "q", "option": 0})
        assert answer.json() == {"accepted": False}
        assert client.post("/api/forge/%s/cancel" % forge_id).json() == {"cancelled": True}


def test_formats_and_commanders(overrides):
    with TestClient(app) as client:
        formats = client.get("/api/forge/formats").json()["formats"]
        assert formats[0].keys() == {"key", "name", "deck_size", "commander"}
        assert "commander" in [f["key"] for f in formats]
        body = client.get("/api/forge/commanders/aaa1?format=commander").json()
        assert body["total"] == 1
        assert body["commanders"][0]["name"] == "Atraxa Test"
        assert set(body["commanders"][0]) == {"id", "name", "image_url", "color_identity"}
        assert client.get("/api/forge/commanders/dead").status_code == 404
        no_cmd = client.get("/api/forge/commanders/aaa1?format=casual")
        assert no_cmd.status_code == 400
        assert no_cmd.json()["detail"] == "Format has no commander"


def test_commanders_route_does_not_tag_cards(overrides, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("tag_cards ran")

    monkeypatch.setattr("backend.forge.tagging.tag_cards", fail)
    monkeypatch.setattr("backend.api.forge_routes.tag_cards", fail, raising=False)
    with TestClient(app) as client:
        body = client.get("/api/forge/commanders/aaa1?format=commander").json()
    assert [c["name"] for c in body["commanders"]] == ["Atraxa Test"]


def test_decks_read_routes(overrides):
    _, _, decks = overrides
    with TestClient(app) as client:
        assert client.get("/api/decks").json() == {"decks": [], "total": 0}
        assert client.get("/api/decks/missing").status_code == 404
        assert client.get("/api/decks/missing").json()["detail"] == "Deck not found"


def test_ai_status_recommends_model(overrides):
    with TestClient(app) as client:
        body = client.get("/api/ai/status").json()
        assert body["recommended"] == "gpt-oss:20b"
        assert body["available"] is False


def test_old_deck_routes_removed():
    client = TestClient(app)
    assert client.post("/api/deck/build", json={}).status_code in (404, 405)


def test_request_validation_422(overrides):
    with TestClient(app) as client:
        for bad in ({"ask_mode": "sometimes"}, {"question_timeout": 0}, {"deck_size": 5},
                    {"max_copies": 9}, {"colors": "x" * 50}):
            body = dict({"job_id": "aaa1", "format": "casual"}, **bad)
            assert client.post("/api/forge", json=body).status_code == 422, bad


def test_bad_job_ids_and_deck_ids(overrides):
    with TestClient(app) as client:
        body = {"job_id": "../x", "format": "commander"}
        response = client.post("/api/forge", json=body)
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid job ID format"
        assert client.get("/api/forge/commanders/..%2Fx").status_code in (400, 404)
        assert client.get("/api/forge/commanders/XYZ").json()["detail"] == "Invalid job ID format"
        assert client.get("/api/decks/..%2Fx").status_code == 404
        assert client.get("/api/decks/not-an-id").status_code == 404


def test_format_checked_before_collection(overrides):
    with TestClient(app) as client:
        response = client.post("/api/forge", json={"job_id": "abc", "format": "bogus"})
        assert response.status_code == 400
        assert response.json()["detail"] == "Unknown format"


def test_closing_the_stream_early_is_clean(overrides):
    with TestClient(app) as client:
        forge_id = client.post("/api/forge", json={"job_id": "aaa1", "format": "casual",
                                                   "colors": "B", "ask_mode": "never"}
                               ).json()["forge_id"]
        with client.stream("GET", "/api/forge/%s/events" % forge_id) as r:
            lines = r.iter_lines()
            assert next(lines).startswith("id:")
        # The server cleaned up; a new stream still works.
        assert read_events(client, forge_id)[-1][1] == "done"


@pytest.mark.asyncio
async def test_keepalive_then_next_event(tmp_path, monkeypatch):
    """A quiet session gets keepalive comments, and the next event still arrives."""
    import asyncio
    from backend.api import forge_routes
    from backend.forge.playbook import load_playbook
    from backend.forge.session import ForgeParams, ForgeSession
    monkeypatch.setattr(forge_routes, "KEEPALIVE_SECONDS", 0.05)
    session = ForgeSession(ForgeParams(job_id="aaa1", format="casual"), [], {}, load_playbook(),
                           None, DeckStore(storage_dir=str(tmp_path / "decks")))
    stream = forge_routes._stream(session, -1)
    assert await asyncio.wait_for(stream.__anext__(), 2) == ": keepalive\n\n"
    assert await asyncio.wait_for(stream.__anext__(), 2) == ": keepalive\n\n"
    session._thought("later")
    frame = await asyncio.wait_for(stream.__anext__(), 2)
    assert frame.startswith("id: 0\nevent: thought\n")
    session._finish("cancelled")
    assert (await asyncio.wait_for(stream.__anext__(), 2)).startswith("id: 1\nevent: cancelled")
    with pytest.raises(StopAsyncIteration):
        await stream.__anext__()
